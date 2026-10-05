"""Etapa 5 — estratégia visual: a cena nunca fica sem visual.

O ponto que este arquivo trava: quando não há fotografia adequada, a cena
troca de MEDIUM. Ela não fica vazia e não recebe imagem genérica. Um
diagrama ou um cartão é a cena certa mostrada do jeito certo, e por isso
não pode ser contado como falha nas métricas.
"""

import os

import pytest

from curio.config import CurioConfig
from curio.stages import scoring, visuals
from curio.stages.scenes import Chapter

PIL = pytest.importorskip("PIL")


def _ch(vtype="mechanism", subject="thermal receipt paper", entities=(),
        narration="O calor altera o corante e a imagem aparece.",
        queries=()):
    return Chapter(id=1, narration=narration, duration_estimate=8.0,
                   visual_type=vtype, subject=subject,
                   visual_entities=list(entities), context=[], forbidden=[],
                   visual_queries=list(queries))


# --- a escada depende do tipo de visual -------------------------------

@pytest.mark.parametrize("vtype,primeira", [
    ("mechanism", "diagram"),      # processo: foto não mostra
    ("typographic", "card"),       # a ideia é uma palavra
    ("conceptual", "card"),
    ("historical_art", "art"),     # tenta arte de domínio público antes
    ("literal", "image"),
])
def test_escada_comeca_pela_estrategia_certa(vtype, primeira):
    assert visuals.strategies_for(_ch(vtype))[0] == primeira


def test_historico_nao_cai_em_diagrama_antes_do_cartao():
    """Um diagrama "fresco → monge → bird" não explica um santo."""
    escada = visuals.strategies_for(_ch("historical_art"))
    assert escada.index("card") < escada.index("diagram")


def test_typographic_card_emits_a_complete_selection_decision(monkeypatch, tmp_path):
    from curio.media.providers import MediaAsset
    from curio.media.selection_result import MediaStageResult
    from curio.stages.scene_contract import SemanticScene
    from curio.stages.visual import _search_scene_with_shortcircuit

    card = MediaAsset(provider="synth", asset_id="card-1", title="Salarium",
                      local_path=str(tmp_path / "card.png"))
    monkeypatch.setattr(visuals, "visual_for_scene", lambda *args: card)
    scene = SemanticScene(1, "A palavra salário vem do latim salarium.",
                          visual_type="typographic", subject="salarium",
                          planning_mode="deterministic")

    rows, _ = _search_scene_with_shortcircuit(
        scene, [], CurioConfig(), 1, None, str(tmp_path))
    result = MediaStageResult.from_rows(rows, "provider")

    assert result.scenes[0].decision.status == "synthetic"
    assert result.scenes[0].decision.fallback_level == "typographic_card"
    assert result.scenes[0].visual_audit["search_exhaustion_reason"] == (
        "typographic_visual_requires_card")


def test_mecanismo_nao_comeca_por_foto():
    escada = visuals.strategies_for(_ch("mechanism"))
    assert "image" not in escada[:1]
    assert escada[0] == "diagram"


def test_tipo_desconhecido_cai_na_escada_literal():
    assert visuals.strategies_for(_ch("banana")) == visuals.strategies_for(
        _ch("literal"))


# --- o visual produzido ------------------------------------------------

def test_mecanismo_vira_diagrama(tmp_path):
    a = visuals.visual_for_scene(_ch("mechanism",
                                     entities=["thermal printer", "heat",
                                               "dye change", "image appears"]),
                                 str(tmp_path))
    assert a is not None
    assert a.provider == "synth"
    assert a.kind == "image"
    assert "Diagrama" in a.title
    assert a.width == visuals.W and a.height == visuals.H
    assert os.path.getsize(a.local_path) > 10000


def test_tipografico_vira_cartao_com_a_palavra(tmp_path):
    a = visuals.visual_for_scene(
        _ch("typographic", subject="salarium", queries=["salarium", "sal"],
            narration="A palavra salário vem do latim salarium."), str(tmp_path))
    assert "Card" in a.title
    assert os.path.isfile(a.local_path)
    assert os.path.getsize(a.local_path) > 10000


def test_historico_sem_arte_cai_no_cartao(tmp_path):
    a = visuals.visual_for_scene(
        _ch("historical_art", subject="saint francis of assisi",
            entities=["fresco", "monk"]), str(tmp_path))
    assert "Card" in a.title, "histórico não deve virar diagrama"


def test_visual_e_licenca_livre_por_ser_nosso(tmp_path):
    """provider='synth' é o que faz classify_rights marcar como clear."""
    from curio.media.providers import classify_rights
    a = visuals.visual_for_scene(_ch("mechanism", entities=["a"]), str(tmp_path))
    assert a.rights_status == "clear"
    assert classify_rights(a.license, a.provider) == "clear"


def test_visual_tem_licenca_e_autor_declarados(tmp_path):
    a = visuals.visual_for_scene(_ch("mechanism", entities=["a"]), str(tmp_path))
    assert a.license
    assert a.used_in.startswith("cena ")


# --- determinismo e cache ---------------------------------------------

def test_mesma_cena_gera_o_mesmo_arquivo(tmp_path):
    ch = _ch("mechanism", entities=["a", "b"])
    a1 = visuals.visual_for_scene(ch, str(tmp_path))
    a2 = visuals.visual_for_scene(ch, str(tmp_path))
    assert a1.local_path == a2.local_path
    assert a1.asset_id == a2.asset_id


def test_diagram_cache_identity_includes_rendered_narration(tmp_path):
    first = visuals.render_diagram(
        "M87 black hole", [], "The supermassive black hole is at the center.",
        str(tmp_path))
    second = visuals.render_diagram(
        "M87 black hole", [], "Gravity bends light around the event horizon.",
        str(tmp_path))
    same = visuals.render_diagram(
        "M87 black hole", [], "The supermassive black hole is at the center.",
        str(tmp_path))

    assert first.asset_id != second.asset_id
    assert first.local_path != second.local_path
    assert first.asset_id == same.asset_id


def test_cache_reaproveita_o_png(tmp_path):
    ch = _ch("mechanism", entities=["a", "b"])
    a1 = visuals.visual_for_scene(ch, str(tmp_path))
    mtime = os.path.getmtime(a1.local_path)
    visuals.visual_for_scene(ch, str(tmp_path))
    assert os.path.getmtime(a1.local_path) == mtime, "re-desenhou do zero"


def test_cenas_diferentes_geram_arquivos_diferentes(tmp_path):
    a1 = visuals.visual_for_scene(_ch("mechanism", subject="papel termico",
                                      entities=["x"]), str(tmp_path))
    a2 = visuals.visual_for_scene(_ch("mechanism", subject="bateria",
                                      entities=["y"]), str(tmp_path))
    assert a1.local_path != a2.local_path


# --- robustez: nada aqui pode quebrar o vídeo -------------------------

def test_cena_sem_nada_declarado_ainda_produz_visual(tmp_path):
    """Campos vazios (divisão local, IA sem os campos) não podem quebrar."""
    a = visuals.visual_for_scene(
        Chapter(id=1, narration="Uma cena qualquer.", duration_estimate=5.0,
                visual_type="mechanism"), str(tmp_path))
    assert a is not None
    assert os.path.getsize(a.local_path) > 10000


def test_texto_muito_longo_quebra_em_linhas(tmp_path):
    a = visuals.visual_for_scene(
        _ch("typographic",
            subject="uma expressao absurdamente longa para caber numa linha so",
            narration="palavra " * 60), str(tmp_path))
    assert os.path.getsize(a.local_path) > 10000


def test_build_visual_recusa_estrategia_desconhecida(tmp_path):
    assert visuals.build_visual(_ch("mechanism"), "video3d",
                                str(tmp_path)) is None


def test_cena_literal_tem_escada_ate_o_cartao(tmp_path):
    """Literal sem foto não pode ficar vazia: o cartão é o último chão."""
    escada = visuals.strategies_for(_ch("literal"))
    assert escada[-1] == "card"


# --- integração: o renderizador consome sem mudança -------------------

def test_visual_entra_no_render_sem_ajuste(tmp_path):
    """Prova de que a escada não exigiu tocar no renderizador: o PNG gerado
    é um MediaAsset comum e o collage o aceita como imagem normal."""
    from curio.config import CurioConfig
    from curio.stages import render as render_stage
    a = visuals.visual_for_scene(_ch("mechanism", entities=["a", "b"]),
                                 str(tmp_path))
    cfg = CurioConfig(render_backend="cpu", width=160, height=284, fps=12)
    seg = render_stage.render_image_segment(a.local_path, 1.5,
                                            str(tmp_path / "seg.mp4"), cfg, 0)
    assert os.path.isfile(seg)
    assert os.path.getsize(seg) > 1000


# --- pontuação: núcleo prova o assunto, apoio só desempata ------------

def _ch_score(subject, entities=(), queries=()):
    return Chapter(id=1, narration="n", duration_estimate=5.0,
                   visual_type="literal", subject=subject,
                   visual_entities=list(entities), context=[],
                   visual_queries=list(queries))


def test_titulo_de_acervo_nao_perde_a_primeira_palavra():
    """'File:Saint Francis' não pode virar 'file:saint' e não casar.

    Separar token só por espaço colava o prefixo do Wikimedia na
    primeira palavra — ou seja, todo título de acervo perdia um termo, e
    justamente nos provedores sem chave que guardam a arte pública.
    """
    ch = _ch_score("saint francis of assisi")
    nota = scoring.base_score(
        {"title": "File:Saint Francis of Assisi - Allori.jpg"}, ch)
    # cobertura total do núcleo = CORE_MAX (o bônus de apoio é que leva
    # até 100; aqui a cena não pediu apoio)
    assert nota["score"] == scoring.CORE_MAX
    assert nota["matched"] == ["saint", "francis", "assisi"]


def test_uma_palavra_do_assunto_nao_basta_para_entrar():
    """'thermal' contra o sujeito 'thermal receipt paper' não é o tema."""
    ch = _ch_score("thermal receipt paper",
                   entities=["thermal printer", "heat", "dye change"])
    nota = scoring.base_score({"title": "thermal power station at dusk"}, ch)
    assert nota["score"] < scoring.DEFAULT_THRESHOLD
    ok, _low = scoring.below_threshold([{"score": nota["score"]}])
    assert not ok, "a usina voltou a passar"


def test_bonus_de_apoio_nao_compra_imagem_errada():
    ch = _ch_score("thermal receipt paper",
                   entities=["thermal", "power", "station"])
    # casaria com apoio, mas o núcleo não prova nada
    nota = scoring.base_score({"title": "thermal power station"}, ch)
    assert nota["support"], "o título casa com as entidades"
    assert nota["score"] < scoring.DEFAULT_THRESHOLD


def test_entidade_presente_desempata_a_favor():
    """Duas imagens do mesmo assunto: vence a que tem o apoio pedido."""
    ch = _ch_score("saint francis of assisi", entities=["fresco", "monk"])
    sem = scoring.base_score({"title": "saint francis of assisi statue"}, ch)
    com = scoring.base_score(
        {"title": "saint francis of assisi fresco with monk"}, ch)
    assert com["score"] > sem["score"]
    assert "fresco" in com["support"]


def test_assunto_dominina_as_consultas():
    """Consultas são busca, não identidade: não podem diluir o sujeito."""
    ch = _ch_score("saint francis of assisi",
                   queries=["saint francis assisi", "franciscan friar"])
    nota = scoring.base_score(
        {"title": "File:Saint Francis in Ecstasy.jpg"}, ch)
    # 2 de 3 palavras do assunto: as consultas NÃO entraram no denominador,
    # então a nota é 2/3 do núcleo, bem acima do corte
    assert nota["score"] == pytest.approx(scoring.CORE_MAX * 2 / 3, abs=1)
    ok, _low = scoring.below_threshold([{"score": nota["score"]}])
    assert ok


def test_narracao_sem_plano_semantico_nao_vira_termos_de_scoring():
    ch = Chapter(id=1, narration="Rome preserved food with salt.",
                 duration_estimate=5.0, visual_type="literal")
    nota = scoring.base_score({"title": "Rome preserved food with salt"}, ch)
    assert nota["score"] == 0


def test_representacao_materializada_forma_nucleo_de_scoring():
    ch = Chapter(id=1, narration="Rome preserved food with salt.",
                 duration_estimate=5.0, visual_type="literal",
                 representations=[{"query": "Roman food preservation",
                                   "kind": "artifact"}])
    nota = scoring.base_score({"title": "Roman food preservation with salt"}, ch)
    assert nota["score"] > 0


def test_arte_historica_passa_e_foto_moderna_nao():
    """Critério de aceite 2: a arte entra, a foto de banco não."""
    ch = _ch_score("saint francis of assisi", entities=["fresco", "monk"])
    arte = scoring.base_score(
        {"title": "File:Saint Francis in Ecstasy - Zurbaran.jpg"}, ch)
    foto = scoring.base_score(
        {"title": "File:Assisi Basilica - modern tourist photo"}, ch)
    assert arte["score"] > foto["score"]
    ok_arte, _ = scoring.below_threshold([{"score": arte["score"]}])
    ok_foto, _ = scoring.below_threshold([{"score": foto["score"]}])
    assert ok_arte and not ok_foto


# --- a concatenação precisa produzir UMA série de codec ---------------
# O sintoma era: vídeo falhava em ~14,9 s (fronteira do 2º segmento) com
# "Error reinitializing filters!" e -38, deixando um final.mp4 truncado
# como se tivesse funcionado. Causa: -c copy do demuxer concat justapõe
# N séries de codec, e o segundo encode precisa reiniciar o filtergraph ao
# atravessar cada fronteira — o que o hwupload do VA-API não implementa.

def _segmentos(tmp_path, n=3):
    from PIL import Image
    import subprocess
    segs = []
    for i in range(n):
        p = str(tmp_path / f"seg{i}.mp4")
        src = str(tmp_path / f"img{i}.png")
        Image.new("RGB", (480, 854), (40 + i * 30, 90, 140)).save(src)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1",
                        "-framerate", "24", "-t", "2", "-i", src,
                        "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", p], check=True)
        segs.append(p)
    return segs


def _n_series(path):
    """Conta trocas de série observing os keyframes do stream."""
    import subprocess
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout
    return sum(1 for ln in out.splitlines() if ",K" in ln or ln.endswith("K"))


def test_concat_copy_normaliza_quando_o_encode_final_e_vaapi(tmp_path):
    from curio.stages import render as R
    cfg = CurioConfig(render_backend="vaapi")
    out = str(tmp_path / "silent.mp4")
    R.concat_copy(_segmentos(tmp_path), out, cfg)
    assert os.path.isfile(out)
    assert _n_series(out) <= 1, "o concat precisa sair com série única"


def test_concat_copy_nao_paga_passe_extra_no_caminho_software(tmp_path):
    from curio.stages import render as R
    cfg = CurioConfig(render_backend="cpu")
    out = str(tmp_path / "silent.mp4")
    R.concat_copy(_segmentos(tmp_path), out, cfg)
    assert os.path.isfile(out)
    assert not os.path.exists(out + ".norm.mp4"), "normalizou sem precisar"


def test_concat_copy_sem_cfg_comporta_se_como_antes(tmp_path):
    from curio.stages import render as R
    out = str(tmp_path / "silent.mp4")
    R.concat_copy(_segmentos(tmp_path), out)
    assert os.path.isfile(out) and os.path.getsize(out) > 1000


def test_needs_single_sequence_depende_do_encoder(tmp_path):
    from curio.stages import render as R
    assert R._needs_single_sequence(CurioConfig(render_backend="vaapi"))
    assert R._needs_single_sequence(CurioConfig(render_backend="arc"))
    assert not R._needs_single_sequence(CurioConfig(render_backend="cpu"))


# --- variedade: fallback ≠ card genérico repetido ----------------------
# O vídeo de São Bento saiu com 9 de 12 cenas viradas em card, e várias
# eram "São Bento name origin question" / "mystery" / "speculation": a
# mesma forma, com o mesmo texto quase igual, N vezes seguidas.

def _ch2(vtype="conceptual", subject="assunto", entities=(), narration="Uma "
         "frase de narração com pelo menos quatro palavras para o rodapé.",
         context=()):
    return Chapter(id=1, narration=narration, duration_estimate=6.0,
                   visual_type=vtype, subject=subject,
                   visual_entities=list(entities), context=list(context),
                   visual_queries=[])


def test_cada_forma_e_visualmente_diferente(tmp_path):
    """Cinco formas, cinco arquivos, cinco conteúdos distintos."""
    vistos = set()
    for forma in visuals.FORMS:
        ch = _ch2(entities=["USP campus", "PUC building", "law books"],
                  narration="Ele se formou em Direito pela USP em 1963.")
        a = visuals.render_form(ch, forma, str(tmp_path), "pt-BR")
        assert a is not None and os.path.getsize(a.local_path) > 10000
        vistos.add(a.local_path)
    assert len(vistos) == len(visuals.FORMS)


def test_forma_depende_do_que_a_cena_comunica():
    assert visuals.choose_form(_ch2("typographic", "salarium",
                                    ["sal", "romano"])) == visuals.FORM_DEFINITION
    assert visuals.choose_form(_ch2("mechanism", "thermal paper",
                                    ["heat", "dye"])) == visuals.FORM_ENUM
    # negativa explícita pede contraste, não definição
    assert visuals.choose_form(
        _ch2("conceptual", "A não tem relação com B", ["A", "B"])
    ) == visuals.FORM_CONTRAST


def test_assunto_repetido_vira_spotlight():
    """A forma de uma cena cujo assunto já apareceu não pode ser a mesma."""
    st = visuals.VisualState()
    primeira = _ch2("conceptual", "São Bento name origin question")
    f1 = visuals.choose_form(primeira, st)
    st.record(primeira.subject, f1)
    segunda = _ch2("conceptual", "São Bento name origin mystery")
    f2 = visuals.choose_form(segunda, st)
    assert f1 != f2
    assert f2 == visuals.FORM_SPOTLIGHT


def test_negacao_no_assunto_nao_esconde_a_repeticao():
    """"Lack of X information" é o mesmo assunto com um 'não' na frente."""
    st = visuals.VisualState()
    st.record("São Bento name origin question", "definition")
    assert st.subject_repeated("Lack of São Bento name origin information")
    assert st.subject_repeated("São Bento name origin speculation")


def test_um_video_de_6_cenas_iguais_nao_repete_forma():
    """O caso real: seis cenas quase iguais, seis visuais distintos."""
    st = visuals.VisualState()
    assuntos = [
        "Serra Gaúcha characteristics",
        "Serra Gaúcha cultural and economic identity",
        "Serra Gaúcha tourism and wine",
        "Serra Gaúcha location and borders",
        "Serra Gaúcha history of settlement",
        "Serra Gaúcha current population",
    ]
    formas = []
    for a in assuntos:
        ch = _ch2("literal", a, ["primeiro item", "segundo item"])
        f = visuals.choose_form(ch, st)
        formas.append(f)
        st.record(a, f)
    assert len(set(formas)) >= 2, formas
    # e nenhuma das repetições é a forma mais usada no vídeo
    assert formas.count(max(set(formas), key=formas.count)) <= 3, formas


def test_o_estado_registra_o_que_foi_mostrado():
    st = visuals.VisualState()
    st.record("assunto um", "spotlight")
    st.record("assunto dois", "definition")
    assert st.forms == ["spotlight", "definition"]
    assert st.subject_repeated("assunto um")
    assert not st.subject_repeated("outro tema")


def test_cena_negativa_nao_vira_cartao_de_definicao():
    """Um cartão de definição diria o contrário do que a cena afirma."""
    ch = _ch2("conceptual", "Michel Temer não tem relação com São Bento",
              ["Michel Temer", "São Bento"])
    assert visuals.choose_form(ch) == visuals.FORM_CONTRAST
    a = visuals.render_form(ch, visuals.FORM_CONTRAST, "/tmp/opencode/x", "pt-BR")
    assert os.path.getsize(a.local_path) > 10000


def test_visual_for_scene_passa_o_estado_e_registra(tmp_path):
    st = visuals.VisualState()
    ch = _ch2("conceptual", "primeiro assunto", ["a", "b"])
    a1 = visuals.visual_for_scene(ch, str(tmp_path), "pt-BR", st)
    assert a1 is not None
    assert st.forms, "o estado não registrou a forma usada"
    assert st.subjects


def test_todas_as_formas_aceitam_cena_vazia(tmp_path):
    """Cena sem assunto nem entidades não pode quebrar nenhum layout."""
    for forma in visuals.FORMS:
        ch = _ch2("conceptual", "", [], narration="")
        a = visuals.render_form(ch, forma, str(tmp_path), "pt-BR")
        assert a is not None, forma
        # confere a imagem de verdade, não o tamanho: uma cena quase vazia
        # gera um PNG legítimo e pequeno
        from PIL import Image
        with Image.open(a.local_path) as im:
            assert im.size == (visuals.W, visuals.H), forma
            assert im.format == "PNG", forma


# --- a forma "dated": nome + datas, o exemplo de direção de arte ------

def _ch_pessoa(sujeito, datas=None, papel="person", extra_ctx=("mosteiro",),
               **kw):
    """Cena de pessoa. Sem papel nem data por padrão, para os casos
    negativos não serem vencidos por uma declaração explícita."""
    from curio.stages.scenes import Chapter
    ctx = ([datas] if datas else []) + list(extra_ctx)
    return Chapter(id=1, narration="Uma frase sobre a pessoa.",
                   duration_estimate=13.0, visual_type="historical_art",
                   subject=sujeito, context=ctx, text_role=papel, **kw)


def test_nome_com_datas_usa_a_forma_dated():
    ch = _ch_pessoa("São Bento de Núrsia", "c. 480 — 547")
    assert visuals.choose_form(ch, None, "people") == visuals.FORM_DATED


def test_sao_jeronimo_e_reconhecido_como_pessoa():
    """O caso real que motivou a forma."""
    ch = _ch_pessoa("São Jerônimo", "c. 347 — 420")
    assert visuals._looks_person(ch, "people")
    assert visuals.choose_form(ch, None, "people") == visuals.FORM_DATED


def test_forma_latina_longa_tambem_e_pessoa():
    ch = _ch_pessoa("Eusebius Sophronius Hieronymus", "séc. IV")
    assert visuals.choose_form(ch, None, "people") == visuals.FORM_DATED


def test_instituicao_nao_e_pessoa_mesmo_com_data():
    """O falso positivo óbvio: duas palavras capitalizadas não é pessoa."""
    for sujeito in ("Império Romano", "Concílio de Éfeso", "Guerra Civil",
                   "Reino do Sol", "Ordem de São Bento"):
        # sem papel declarado: aqui o que decide é a heurística
        ch = _ch_pessoa(sujeito, "séc. V", papel="")
        assert not visuals._looks_person(ch, "people"), sujeito
        assert visuals.choose_form(ch, None, "people") != visuals.FORM_DATED


def test_conceito_com_data_nao_vira_ficha_de_pessoa():
    ch = _ch_pessoa("Salário", "séc. I a.C.", papel="", extra_ctx=())
    assert visuals.choose_form(ch, None, "etymology") != visuals.FORM_DATED


def test_datas_reconhecidas_em_varios_formatos():
    from curio.stages.scenes import Chapter
    for bruto, esperado in (("c. 480 — 547", "c. 480 — 547"),
                            ("480-547", "480-547"),
                            ("347 ao 420", "347 ao 420"),
                            ("séc. VI", "séc. VI"),
                            # De um campo declarado, um ano solto é data.
                            # O que entra na tela é o ANO, não a frase: o
                            # cartão mostra "480", não "nasceu em 480".
                            ("nascida em 480", "480")):
        ch = Chapter(id=1, narration="x", duration_estimate=9.0,
                     subject="São Bento", context=[bruto])
        assert visuals._date_range(ch) == esperado, bruto


def test_sem_data_a_forma_dated_nao_dispara():
    ch = _ch_pessoa("São Bento de Núrsia", None)
    assert visuals.choose_form(ch, None, "people") != visuals.FORM_DATED


def test_a_data_vem_do_declarado_antes_da_narracao():
    """A narração diz 'por volta de 480'; a fonte de tela é a declaration."""
    from curio.stages.scenes import Chapter
    ch = Chapter(id=1, narration="nasceu por volta de 480 em Núrsia",
                 duration_estimate=9.0, subject="São Bento",
                 context=["c. 480 — 547"], text_role="person")
    assert visuals._date_range(ch) == "c. 480 — 547"


def test_forma_dated_desenha_nome_e_data(tmp_path):
    ch = _ch_pessoa("São Bento de Núrsia", "c. 480 — 547")
    a = visuals.render_form(ch, visuals.FORM_DATED, str(tmp_path), "pt-BR")
    assert a is not None
    assert os.path.getsize(a.local_path) > 10000


def test_forma_dated_usa_papeis_diferentes_para_nome_e_data(tmp_path):
    """Nome na serifada principal, data discreta: são papéis distintos."""
    from curio.stages import typography as T
    real = T.Typography.pil
    pedidos = []

    def espiao(self, role="title", size=48):
        pedidos.append(role)
        return real(self, role, size)

    T.Typography.pil = espiao
    try:
        ch = _ch_pessoa("São Bento de Núrsia", "c. 480 — 547")
        visuals.render_form(ch, visuals.FORM_DATED, str(tmp_path), "pt-BR",
                            T.for_genre("people"))
    finally:
        T.Typography.pil = real
    assert "person" in pedidos
    assert "date" in pedidos


def test_forma_dated_esta_em_todas_as_formas_visiveis():
    assert visuals.FORM_DATED in visuals.FORMS


def test_ano_que_so_na_narracao_nao_vira_ficha_de_data():
    """"em 480 cenas" não é uma data, e a narração é texto falado."""
    from curio.stages.scenes import Chapter
    ch = Chapter(id=1, narration="O sal foi medido em 480 gramas.",
                 duration_estimate=9.0, subject="Salário",
                 text_role="person")
    assert visuals._date_range(ch) == ""
    assert visuals.choose_form(ch, None, "people") != visuals.FORM_DATED
