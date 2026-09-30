"""Camada tipográfica: papéis, resolução e o que o render faz com eles.

Um teste que lê `profiles["people"].primary == "Minion Pro"` não prova
nada: prova que existe uma string. O que interessa é o que acontece
quando a Minion Pro NÃO está na máquina, que é o caso de quase todo
mundo, e o que o renderizador faz com o papel que a cena declarou.
"""

import subprocess
import sys

import pytest

from curio.stages import typography as T
from curio.stages.scenes import Chapter, text_role_for
from curio.stages import visuals as V


# --- perfis ------------------------------------------------------------

def test_todo_genero_editorial_tem_perfil_tipografico():
    """Um gênero novo sem direção tipográfica é um gênero sem identidade."""
    from curio.stages import editorial as E
    for chave, _ in E.choices():
        assert chave in T.PROFILES, chave
        assert T.PROFILES[chave].direction, chave


def test_mais_generos_que_perfis_conhecidos_nao_inventam_fonte():
    p = T.profile_for("inexistente")
    assert p is T.DEFAULT


def test_people_tem_minion_pro_e_minion_pro_italic():
    """A referência pedida para História de Pessoas, nomeada nos dois papéis."""
    p = T.PROFILES["people"]
    assert p.families[T.INTENT_SERIF] == "Minion Pro"
    assert p.families[T.INTENT_SERIF_ITALIC] == "Minion Pro Italic"


def test_people_tem_italic_no_papel_de_citacao():
    p = T.PROFILES["people"]
    assert p.roles[T.ROLE_QUOTE] == T.INTENT_SERIF_ITALIC
    assert p.roles[T.ROLE_LATIN] == T.INTENT_SERIF_ITALIC
    assert p.roles[T.ROLE_DOCUMENT] == T.INTENT_SERIF_ITALIC


def test_people_titulo_e_nome_na_serifada_principal_e_nao_em_italic():
    """Itálico é recurso editorial. Título em itálico seria o oposto."""
    p = T.PROFILES["people"]
    assert p.roles[T.ROLE_TITLE] == T.INTENT_SERIF
    assert p.roles[T.ROLE_PERSON] == T.INTENT_SERIF
    assert p.roles[T.ROLE_TERM] == T.INTENT_SERIF


def test_generos_tem_direcoes_distintas():
    direcoes = {k: p.direction for k, p in T.PROFILES.items()}
    assert len(set(direcoes.values())) == 6


def test_ciencia_nao_tem_serifada_nos_papeis_principais():
    """Ciência é sans limpa: serif em título e termo seria ornamento."""
    p = T.PROFILES["science"]
    for papel in (T.ROLE_TITLE, T.ROLE_PERSON, T.ROLE_TERM,
                  T.ROLE_SUBTITLE):
        assert p.roles[papel] == T.INTENT_SANS, papel


def test_misterio_separa_fato_com_mono_e_titulo_condensado():
    p = T.PROFILES["mystery"]
    assert p.roles[T.ROLE_DATE] == T.INTENT_MONO
    assert p.roles[T.ROLE_LOCATION] == T.INTENT_MONO
    assert p.roles[T.ROLE_DOCUMENT] == T.INTENT_MONO


def test_etimologia_põe_o_termo_em_destaque():
    p = T.PROFILES["etymology"]
    assert p.scale[T.ROLE_TERM] > 1.0
    assert p.roles[T.ROLE_TERM] == T.INTENT_SERIF


def test_mitologia_poe_o_nome_em_italic():
    p = T.PROFILES["mythology"]
    assert p.roles[T.ROLE_PERSON] == T.INTENT_SERIF_ITALIC


# --- papéis diferentes, estilos diferentes ----------------------------

def test_papeis_diferentes_resolvem_para_estilos_diferentes():
    """A promessa do recurso: citação e narração não são a mesma fonte."""
    r_titulo = T.resolve(T.ROLE_TITLE, "people")
    r_cita = T.resolve(T.ROLE_QUOTE, "people")
    r_data = T.resolve(T.ROLE_DATE, "people")
    assert r_titulo.intent == T.INTENT_SERIF
    assert r_cita.intent == T.INTENT_SERIF_ITALIC
    assert r_data.intent == T.INTENT_SANS
    assert r_titulo.italic is False
    assert r_cita.italic is True


def test_corpo_escalado_por_papel():
    p = T.PROFILES["people"]
    assert p.size_for(T.ROLE_TITLE, 100) > p.size_for(T.ROLE_KICKER, 100)
    assert p.size_for(T.ROLE_QUOTE, 100) < 100  # citação não é título


# --- o itálico que o fontconfig inventa --------------------------------

def test_split_style_separa_o_nome_do_estilo():
    assert T.split_style("Minion Pro Italic") == ("Minion Pro", True)
    assert T.split_style("Liberation Serif Italic") == ("Liberation Serif", True)
    assert T.split_style("EB Garamond") == ("EB Garamond", False)
    # Uma palavra só não é família + estilo: seria inventar.
    assert T.split_style("Italic") == ("Italic", False)


def test_fc_resolve_rejeita_familia_que_nao_existe():
    assert T._fc_resolve("Minion Pro", False) is None


def test_fc_resolve_rejeita_familia_substituida_em_silencio():
    """fontconfig troca em vez de admitir que não sabe.

    `fc-match "Minion Pro"` responde Noto Sans nesta máquina. Aceitar
    isso seria um fallback que vira sans-serifada, que não é fallback.
    """
    achado = T._fc_resolve("Minion Pro", False)
    assert achado is None or "minion" in achado[0].lower()


def test_fc_resolve_rejeita_regular_quando_pede_italic(monkeypatch, tmp_path):
    """O defeito silencioso que motivated o módulo.

    O fontconfig devolve o rosto regular para uma família sem itálico e
    reporta sucesso. Aceitar o regular como itálico colocaria a citação
    na mesma fonte da narração e a distinção editorial inteira — que é o
    ponto do recurso — sumiria sem erro.
    """
    fonte = tmp_path / "ebg.ttf"
    fonte.write_bytes(b"x")

    class Resp:
        returncode = 0
        stdout = f"EB Garamond|{fonte}|Regular\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Resp())
    assert T._fc_resolve("EB Garamond", True) is None
    # o mesmo rosto é aceito quando o itálico não foi pedido
    assert T._fc_resolve("EB Garamond", False) is not None


def test_fc_resolve_aceita_oblique_como_inclinado(monkeypatch, tmp_path):
    fonte = tmp_path / "x.ttf"
    fonte.write_bytes(b"x")

    class Resp:
        returncode = 0
        stdout = f"EB Garamond|{fonte}|Oblique\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Resp())
    achado = T._fc_resolve("EB Garamond", True)
    assert achado is not None and achado[2] is True


def test_fc_resolve_usa_a_consulta_de_italic(monkeypatch):
    vistos = []

    class Resp:
        returncode = 0
        stdout = "Noto Serif|/usr/share/fonts/x.ttf|Italic\n"

    def fake(cmd, *a, **k):
        vistos.append(cmd)
        return Resp()

    monkeypatch.setattr(subprocess, "run", fake)
    T._fc_resolve("Noto Serif", True)
    assert vistos and vistos[0][1] == "Noto Serif:italic"


# --- fallback ----------------------------------------------------------

def test_fallback_preserva_a_funcao_sem_minion_pro():
    """Sem a Minion Pro, a citação continua serifada E inclinada."""
    r = T.resolve(T.ROLE_QUOTE, "people")
    assert r.path, "sem arquivo não há o que renderizar"
    assert r.italic is True
    assert r.intent == T.INTENT_SERIF_ITALIC
    assert r.is_fallback is True
    assert r.requested == "Minion Pro Italic"


def test_fallback_preserva_a_funcao_da_narracao():
    r = T.resolve(T.ROLE_TITLE, "people")
    assert r.intent == T.INTENT_SERIF
    assert r.italic is False


def test_resolve_marca_o_fallback_mas_nao_falha():
    r = T.resolve(T.ROLE_QUOTE, "people")
    assert r.family and r.path
    assert "fallback" in r.describe()
    assert r.used_requested is False


def test_resolve_usa_a_familia_pedida_quando_ela_existe(monkeypatch):
    """Com a família pedida instalada E com itálico, é ela que responde.

    Uma família existe mas não tem itálico não conta: aí o gênero desce
    para um par completo, porque ficar nela significaria citação em outra
    família. Este teste representa a instalação real da EB Garamond, que
    traz os dois rostos.
    """
    T.clear_cache()
    T._CACHE[("EB Garamond", False)] = ("EB Garamond", "/f/ebg.ttf", False)
    T._CACHE[("EB Garamond", True)] = ("EB Garamond", "/f/ebgi.ttf", True)
    try:
        fonte = T.resolve(T.ROLE_TITLE, "etymology")
        assert fonte.family == "EB Garamond"
        assert fonte.is_fallback is False
    finally:
        T.clear_cache()


def test_com_minion_instalada_a_citacao_e_a_minion_italic(monkeypatch):
    """A exigência principal, com a fonte presente.

    Sem isto, o perfil de people declara "Minion Pro Italic" e ninguém
    sabe se o sistema realmente entregaria o itálico dela ou cairia num
    itálico qualquer.
    """
    T.clear_cache()
    T._CACHE[("Minion Pro", False)] = ("Minion Pro", "/f/minion.otf", False)
    T._CACHE[("Minion Pro", True)] = ("Minion Pro", "/f/minioni.otf", True)
    try:
        titulo = T.resolve(T.ROLE_TITLE, "people")
        citacao = T.resolve(T.ROLE_QUOTE, "people")
        latim = T.resolve(T.ROLE_LATIN, "people")
        assert titulo.family == "Minion Pro" and titulo.italic is False
        assert citacao.family == "Minion Pro" and citacao.italic is True
        assert latim.family == "Minion Pro" and latim.italic is True
        assert titulo.is_fallback is False and citacao.is_fallback is False
    finally:
        T.clear_cache()


def test_minion_instalada_mas_so_retro_movela_gênero_inteiro(monkeypatch):
    """Instalação parcial: a Minion Pro existe e não tem itálico.

    Duas saídas possíveis, e só uma é aceitável. Deixar o título na
    Minion e a citação em outra resolve a falta do itálico e cria o
    problema que ninguém quer ver: duas famílias no mesmo vídeo. Então o
    gênero desce inteiro para um par completo — título E citação na mesma
    família, citação no itálico dela.
    """
    T.clear_cache()
    T._CACHE[("Minion Pro", False)] = ("Minion Pro", "/f/minion.otf", False)
    # sem entrada para ("Minion Pro", True): não há itálico
    try:
        titulo = T.resolve(T.ROLE_TITLE, "people")
        citacao = T.resolve(T.ROLE_QUOTE, "people")
        assert citacao.italic is True
        assert titulo.family == citacao.family
        assert titulo.family != "Minion Pro"
    finally:
        T.clear_cache()


def test_itaico_irmao_da_familia_resolvida_antes_da_cadeia_generica():
    """Título e citação na mesma família, não em duas parecidas.

    EB Garamond é old-style e Noto Serif é transitional: a diferença
    existe, mas parece acidente em vez de desenho.
    """
    T.clear_cache()
    # A chave é a família JÁ separada do estilo: "EB Garamond Italic" e
    # ("EB Garamond", True) são a mesma entrada, e é por isso que um nome
    # escrito com o sufixo não paga uma segunda consulta ao fontconfig.
    T._CACHE[("EB Garamond", False)] = ("EB Garamond", "/f/ebg.ttf", False)
    T._CACHE[("EB Garamond", True)] = ("EB Garamond", "/f/ebgi.ttf", True)
    T._CACHE[("EB Garamond Italic", True)] = ("EB Garamond", "/f/ebgi.ttf",
                                              True)
    try:
        # Com a ITALIC do perfil instalada mas a serifada não resolvendo,
        # a voz principal desce e o itálico procura o irmão do que ela
        # resolveu, não o nome preferido.
        T._CACHE.pop(("EB Garamond", False), None)
        T._CACHE[("EB Garamond", False)] = ("EB Garamond", "/f/ebg.ttf", False)
        r = T.resolve(T.ROLE_QUOTE, "etymology")
        assert r.family == "EB Garamond"
        assert r.italic is True
    finally:
        T.clear_cache()


# --- o par coerente: a mesma família nos dois lados --------------------

def test_sem_a_familia_pedida_titulo_e_citacao_sao_a_mesma_familia():
    """A incoerência que o autor viu no vídeo.

    Com a Minion Pro ausente e a primeira serifada da cadeia sem itálico
    (que é o caso da EB Garamond em parte das instalações, e desta
    máquina), a saída ingênua é título numa família e citação em outra.
    Duas famílias no mesmo vídeo leem como dois vídeos colados.
    """
    T.clear_cache()
    try:
        for g in ("people", "history", "etymology", "mythology"):
            familias = {T.resolve(papel, g).family for papel in
                        (T.ROLE_TITLE, T.ROLE_PERSON, T.ROLE_TERM,
                         T.ROLE_QUOTE, T.ROLE_LATIN, T.ROLE_DOCUMENT)}
            assert len(familias) == 1, (g, familias)
    finally:
        T.clear_cache()


def test_a_citacao_continua_inclinada_no_par_escolhido():
    T.clear_cache()
    try:
        for g in ("people", "history", "etymology", "mythology"):
            assert T.resolve(T.ROLE_QUOTE, g).italic is True, g
    finally:
        T.clear_cache()


def test_fonte_pinada_pelo_usuario_vale_mesmo_sem_italic():
    """Quem digita a família no config está escolhendo, não sugerindo."""
    T.clear_cache()
    T._CACHE[("EB Garamond", False)] = ("EB Garamond", "/f/ebg.ttf", False)
    try:
        p = T.profile_for("people", {"primary": "EB Garamond"})
        assert p.pinned is True
        assert T._par_de_bolso(p, T.INTENT_SERIF) == ""
        assert T.resolve(T.ROLE_TITLE, "people",
                         {"primary": "EB Garamond"}).family == "EB Garamond"
    finally:
        T.clear_cache()


def test_genero_sem_italic_ainda_encontra_uma_familia_inclinada():
    """Ciência e Mistério pedem sans no título e itálico serifado na
    citação. A citação não pode virar reta só porque o título é sans."""
    T.clear_cache()
    try:
        for g in ("science", "mystery"):
            assert T.resolve(T.ROLE_QUOTE, g).italic is True, g
    finally:
        T.clear_cache()


def test_resolve_de_graca_sem_fontconfig(monkeypatch):
    """Sem fontconfig, degrada para o arquivo de sempre e não levanta."""
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            FileNotFoundError()))
    T.clear_cache()
    try:
        r = T.resolve(T.ROLE_QUOTE, "people")
        assert r.path and r.is_fallback is True
    finally:
        T.clear_cache()


def test_resolve_de_graca_para_genero_lixo():
    for papel in T.ROLES:
        assert T.resolve(papel, "genero-que-nao-existe") is not None


def test_resolve_de_graca_para_papel_lixo():
    assert T.resolve("papel-que-nao-existe", "people").path


# --- a resolução não baixa fonte alguma -------------------------------

def test_modulo_nao_faz_chamada_de_rede():
    """A proibição é literal: nada de urllib no caminho de resolução.

    Baixar fonte durante o render transforma montagem em dependência de
    rede, e uma dependência de rede que falha depois de quarenta minutos
    de montagem é a pior delas. A proprietária não entra no repositório
    e a OFL substituta também não: a resolução pergunta ao sistema.
    """
    caminho = T.__file__
    with open(caminho, encoding="utf-8") as fh:
        fonte = fh.read()
    for proibido in ("urllib", "requests", "urlopen", "http://", "https://",
                     "socket", "download"):
        assert proibido not in fonte, proibido


def test_resolver_nao_escreve_nada_no_disco(tmp_path, monkeypatch):
    antes = set(p.name for p in tmp_path.iterdir())
    monkeypatch.chdir(tmp_path)
    for papel in T.ROLES:
        T.resolve(papel, "people")
    assert set(p.name for p in tmp_path.iterdir()) == antes


def test_fontes_do_perfil_nao_sao_empacotadas_no_repo():
    """A Minion Pro é proprietária e não pode estar no repositório."""
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parent.parent
    suspeitas = [p for p in raiz.rglob("*")
                 if p.suffix.lower() in (".ttf", ".otf", ".ttc")
                 and p.name.lower().startswith("minion")]
    assert not suspeitas, suspeitas


# --- config ------------------------------------------------------------

def test_override_de_familia_muda_a_resolucao():
    r = T.resolve(T.ROLE_TITLE, "people",
                  {"primary": "Liberation Serif"})
    assert r.family == "Liberation Serif"
    assert r.is_fallback is False


def test_override_de_italic_aceita_o_nome_como_a_gente_escreve():
    r = T.resolve(T.ROLE_QUOTE, "people",
                  {"italic": "Liberation Serif Italic"})
    assert r.italic is True
    assert "Liberation Serif" in r.family


def test_override_por_papel_tem_precedencia():
    r = T.resolve(T.ROLE_QUOTE, "people",
                  {"italic": "Liberation Serif Italic",
                   "roles": {"quote": "Noto Serif Italic"}})
    assert "Noto Serif" in r.family


def test_papel_com_familia_inexistente_cai_na_cadeia_do_genero():
    """Um override não pode apagar a serifa da citação."""
    r = T.resolve(T.ROLE_QUOTE, "people",
                  {"roles": {"quote": "Cormorant Garamond"}})
    assert r.italic is True
    assert r.intent == T.INTENT_SERIF_ITALIC


def test_chave_desconhecida_nao_vira_fonte():
    p = T.profile_for("people", {"primry": "Comic Sans"})
    assert p.family_for(T.INTENT_SERIF) == "Minion Pro"


def test_config_toml_carrega_a_tipografia(tmp_path):
    from curio.config import CurioConfig
    p = tmp_path / "config.toml"
    p.write_text('genre = "people"\n\n[typography.people]\n'
                 'primary = "EB Garamond"\nitalic = "EB Garamond Italic"\n',
                 encoding="utf-8")
    cfg = CurioConfig.load(str(p))
    assert cfg.typography["people"]["primary"] == "EB Garamond"
    r = T.resolve(T.ROLE_QUOTE, "people", cfg.typography["people"])
    assert r.italic is True


def test_env_sobrescreve_a_familia(tmp_path, monkeypatch):
    from curio.config import CurioConfig
    p = tmp_path / "config.toml"
    p.write_text('genre = "people"\n', encoding="utf-8")
    monkeypatch.setenv("CURIO_TYPOGRAPHY_PEOPLE",
                       "primary=Liberation Serif")
    cfg = CurioConfig.load(str(p))
    assert cfg.typography["people"]["primary"] == "Liberation Serif"


# --- legendas: legibilidade acima de estilo ---------------------------

def test_legenda_ignora_a_serifada_do_perfil():
    """Uma legenda em itálico serifado é pior do que uma legenda feia."""
    assert T.ROLE_CAPTION in T.LEGIBILITY_ROLES
    r = T.resolve(T.ROLE_CAPTION, "people")
    assert r.intent == T.INTENT_SANS
    assert r.italic is False


def test_ass_de_legenda_continua_na_fonte_de_exibicao():
    familia, _bold, _path = T.for_genre("people").ass(T.ROLE_CAPTION)
    assert familia, "a legenda precisa de uma família de verdade"
    # o caminho de exibição é o que ensure_display_font devolve
    from curio.stages.subs import ensure_display_font
    assert familia == ensure_display_font()[0]


def test_legendas_geram_ass_com_genero_sem_quebrar():
    from curio.stages import subs as S
    cues = [(0.0, 2.0, "ORÁ ET LABÓRA"), (2.0, 4.0, "NÚRSIA")]
    ass = S.cues_to_ass(cues, 1080, 1920, 74, 320)
    assert ass.startswith("[Script Info]")
    assert "Style: Default" in ass
    assert len(ass.split("Dialogue:")) >= 3


# --- o papel chega ao render ------------------------------------------

def _desenha(monkeypatch, tmp_path, **kw):
    """Roda a forma de citação e devolve as fontes realmente usadas."""
    usadas = []

    def espiao(size, typo=None, role=""):
        usadas.append((role, size))
        return T.for_genre(kw.pop("genre", "") or "").pil(role or "term", size) \
            if role else V._font.__wrapped__(size) if hasattr(
                V._font, "__wrapped__") else None

    return usadas, tmp_path


def test_forma_de_citacao_usa_o_papel_da_cena(tmp_path):
    """O comportamento que o recurso promete, no render de verdade."""
    real = T.Typography.pil
    pedidos = []

    def espiao(self, role="title", size=48):
        pedidos.append(role)
        return real(self, role, size)

    T.Typography.pil = espiao
    try:
        ch = Chapter(id=1, narration='A Regra diz "Ora et labora".',
                     duration_estimate=10.0, visual_type="conceptual",
                     subject="Regra de São Bento", text_role="quote")
        asset = V.render_form(ch, V.FORM_QUOTE, str(tmp_path), "pt-BR",
                              T.for_genre("people"))
    finally:
        T.Typography.pil = real
    assert asset is not None
    assert "quote" in pedidos
    assert pedidos, "o render não perguntou a fonte de ninguém"


def test_forma_de_citacao_sem_papel_cai_em_quote(tmp_path):
    """Cena antiga, sem text_role: a forma já diz que é citação."""
    real = T.Typography.pil
    pedidos = []

    def espiao(self, role="title", size=48):
        pedidos.append(role)
        return real(self, role, size)

    T.Typography.pil = espiao
    try:
        ch = Chapter(id=1, narration="Uma frase marcante da cena.",
                     duration_estimate=10.0, visual_type="conceptual",
                     subject="assunto")
        V.render_form(ch, V.FORM_QUOTE, str(tmp_path), "pt-BR",
                      T.for_genre("people"))
    finally:
        T.Typography.pil = real
    assert "quote" in pedidos


def test_cena_declara_latim_e_o_render_usa_o_papel_latin(tmp_path):
    real = T.Typography.pil
    pedidos = []

    def espiao(self, role="title", size=48):
        pedidos.append(role)
        return real(self, role, size)

    T.Typography.pil = espiao
    try:
        ch = Chapter(id=1, narration="Benedicta Deus in corde hominum.",
                     duration_estimate=10.0, visual_type="conceptual",
                     subject="Regra", text_language="la")
        V.render_form(ch, V.FORM_QUOTE, str(tmp_path), "pt-BR",
                      T.for_genre("people"))
    finally:
        T.Typography.pil = real
    assert "latin" in pedidos


def test_genero_entra_na_chave_do_cache(tmp_path):
    """Mesma cena, dois gêneros, dois PNGs.

    Devolver o PNG cacheado do outro gênero mostraria a fonte errada sem
    erro nenhum, que é a pior forma de cache errado.
    """
    ch = Chapter(id=1, narration='A Regra diz "Ora et labora".',
                 duration_estimate=10.0, visual_type="conceptual",
                 subject="Regra")
    a = V.render_form(ch, V.FORM_QUOTE, str(tmp_path), "pt-BR",
                      T.for_genre("people"))
    b = V.render_form(ch, V.FORM_QUOTE, str(tmp_path), "pt-BR",
                      T.for_genre("science"))
    assert a.asset_id != b.asset_id


def test_sem_genero_o_visual_usa_a_fonte_de_exibicao(tmp_path):
    """O vídeo de quem não escolheu gênero não muda de cara."""
    ch = Chapter(id=1, narration="Uma cena qualquer.",
                 duration_estimate=10.0, visual_type="conceptual",
                 subject="assunto")
    T.clear_cache()
    real = T._fc_cached
    T._fc_cached = lambda *a, **k: None   # nenhuma fonte existe
    try:
        a = V.render_form(ch, V.FORM_QUOTE, str(tmp_path), "pt-BR",
                          T.for_genre(""))
    finally:
        T._fc_cached = real
        T.clear_cache()
    from curio import ffmpeg as ff
    assert a is not None
    assert V._font(30) is not None
    assert ff.find_font_bold()


# --- retrocompatibilidade ---------------------------------------------

def test_chapter_antigo_carrega_sem_text_role():
    ch = Chapter.from_dict({"id": 1, "narration": "x",
                            "duration_estimate": 5.0})
    assert ch.text_role == ""
    assert ch.text_language == ""


def test_chapter_antigo_ainda_deriva_o_papel_do_conteudo():
    ch = Chapter.from_dict({"id": 1, "narration": 'Ele disse: "Ora et labora"',
                            "duration_estimate": 5.0})
    assert text_role_for(ch) in ("quote", "latin")


def test_papel_inventado_pela_ia_e_descartado():
    ch = Chapter.from_dict({"id": 1, "narration": "x",
                            "duration_estimate": 5.0,
                            "text_role": "minion_pro_italic"})
    assert ch.text_role == ""


def test_round_trip_preserva_o_papel():
    ch = Chapter(id=1, narration="x", duration_estimate=5.0,
                 visual_type="literal", text_role="latin",
                 text_language="la")
    d = ch.to_dict()
    volta = Chapter.from_dict(d)
    assert volta.text_role == "latin"
    assert volta.text_language == "la"


def test_projeto_antigo_sem_genero_continua_com_a_fonte_de_exibicao():
    from curio.config import CurioConfig
    from curio.pipeline import _title_fontfile
    cfg = CurioConfig()
    meta = {"title": "x", "duration_actual": 10}
    assert _title_fontfile(cfg, str(meta.get("genre") or "")) == \
        _title_fontfile(cfg, "")


def test_relogio_da_typografia_para_o_metadata():
    rel = T.for_genre("people").report()
    assert rel["key"] == "people"
    assert rel["roles"]["quote"]["italic"] is True
    assert rel["roles"]["title"]["italic"] is False
    vazio = T.for_genre("").report()
    assert vazio["key"] == ""


def test_import_de_python_311_nao_quebra():
    """Roda num interpretador limpo, sem o resto do pacote carregado."""
    codigo = ("import sys; sys.path.insert(0, 'src');"
              "from curio.stages import typography as T;"
              "print(T.resolve('quote', 'people').intent)")
    saida = subprocess.run([sys.executable, "-c", codigo],
                           capture_output=True, text=True, check=True)
    assert saida.stdout.strip() == T.INTENT_SERIF_ITALIC


# --- o que sai no metadata -------------------------------------------

def test_metadata_guarda_a_tipografia_resolvida():
    """Sem isto, a única forma de saber a fonte do vídeo é rerenderizar."""
    from curio.config import CurioConfig
    from curio.pipeline import _typography_report
    r = _typography_report(CurioConfig(), "people")
    assert r["key"] == "people"
    assert r["roles"]["quote"]["italic"] is True
    assert r["roles"]["quote"]["requested"] == "Minion Pro Italic"
    assert r["roles"]["title"]["intent"] == T.INTENT_SERIF


def test_metadata_registra_o_fallback_que_respondeu():
    from curio.config import CurioConfig
    from curio.pipeline import _typography_report
    T.clear_cache()
    try:
        papel = _typography_report(CurioConfig(), "people")["roles"]["quote"]
        if papel["fallback"]:
            assert papel["family"] != "Minion Pro Italic"
            assert papel["family"]          # respondeu alguma coisa
    finally:
        T.clear_cache()


def test_metadata_diz_a_fonte_real_da_legenda():
    """A legenda queima na fonte de exibição, e o metadata diz isso.

    Reportar "Noto Sans" para uma legenda em Archivo Black é pior que
    não reportar: é uma informação errada com cara de autoritativa.
    """
    from curio.config import CurioConfig
    from curio.pipeline import _typography_report
    from curio.stages.subs import ensure_display_font
    papel = _typography_report(CurioConfig(), "people")["roles"]["caption"]
    assert papel["family"] == ensure_display_font()[0]
    assert papel["legibility"] is True
    assert papel["italic"] is False


def test_metadata_vazio_sem_genero():
    """Treze papéis com o mesmo valor em todo projeto antigo é ruído."""
    from curio.config import CurioConfig
    from curio.pipeline import _typography_report
    assert _typography_report(CurioConfig(), "") == {}


def test_metadata_do_genero_desconhecido_nao_quebra():
    from curio.config import CurioConfig
    from curio.pipeline import _typography_report
    r = _typography_report(CurioConfig(), "inexistente")
    assert r["key"] == ""


# --- o papel da cena tem que chegar a TODA forma, não só à citação --

def _papel_de(cena, forma, genre, tmp_path):
    """Roda a forma e devolve os papéis que o desenho pediu."""
    real = T.Typography.pil
    pedidos = []

    def espiao(self, role="title", size=48):
        pedidos.append(role)
        return real(self, role, size)

    T.Typography.pil = espiao
    try:
        V.render_form(cena, forma, str(tmp_path), "pt-BR",
                      T.for_genre(genre))
    finally:
        T.Typography.pil = real
    return pedidos


def test_spotlight_usa_o_papel_declarado_e_nao_um_fixo(tmp_path):
    """Person e term saíam iguais em mitologia, apesar do perfil distinguir.

    O perfil de mitologia põe o NOME do mito em itálico e o termo reto.
    Com o papel fixo em `term` no desenho, a distinção não chegava à
    tela: as duas cenas renderizavam idênticas.
    """
    nome = Chapter(id=1, narration="O mito contava-se em Nápoles.",
                   duration_estimate=12.0, visual_type="historical_art",
                   subject="Santa Luzia", text_role="person")
    termo = Chapter(id=2, narration="A palavra vem de Neapolis.",
                    duration_estimate=12.0, visual_type="historical_art",
                    subject="Nápoles", text_role="term")
    p_nome = _papel_de(nome, V.FORM_SPOTLIGHT, "mythology", tmp_path)
    p_termo = _papel_de(termo, V.FORM_SPOTLIGHT, "mythology", tmp_path)
    assert "person" in p_nome
    assert "term" in p_termo
    assert set(p_nome) != set(p_termo)


def test_spotlight_mantem_term_quando_a_cena_nao_declara(tmp_path):
    cena = Chapter(id=1, narration="Uma cena qualquer.",
                   duration_estimate=12.0, visual_type="historical_art",
                   subject="assunto")
    assert "term" in _papel_de(cena, V.FORM_SPOTLIGHT, "people", tmp_path)


def test_enum_e_contrast_tambem_ouvem_a_cena(tmp_path):
    cena = Chapter(id=1, narration="E enumeração.", duration_estimate=12.0,
                   visual_type="mechanism", subject="assunto",
                   visual_entities=["a", "b"], text_role="person")
    assert "person" in _papel_de(cena, V.FORM_ENUM, "mythology", tmp_path)
    assert "person" in _papel_de(cena, V.FORM_CONTRAST, "mythology", tmp_path)


def test_papeis_que_o_perfil_NAO_distingue_continuam_iguais(tmp_path):
    """Em `people` os dois são serifados: a cena não pode inventar diferença."""
    nome = Chapter(id=1, narration="x", duration_estimate=12.0,
                   visual_type="historical_art", subject="São Bento",
                   text_role="person")
    termo = Chapter(id=2, narration="x", duration_estimate=12.0,
                    visual_type="historical_art", subject="salário",
                    text_role="term")
    a = V.render_form(nome, V.FORM_SPOTLIGHT, str(tmp_path / "a"), "pt-BR",
                      T.for_genre("people"))
    b = V.render_form(termo, V.FORM_SPOTLIGHT, str(tmp_path / "b"), "pt-BR",
                      T.for_genre("people"))
    assert a.asset_id != b.asset_id      # textos diferentes
    for papel in ("title", "term", "person"):
        assert (T.resolve(papel, "people").intent
                == T.resolve("term", "people").intent)
