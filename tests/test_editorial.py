"""Gêneros editoriais: a diferença tem que ser estrutural.

Um teste que só verifica `genre == "people"` não prova nada. O que
interessa é que o mesmo tema, em dois gêneros, produza planos
diferentes: mais ou menos cenas, outra forma visual, outra escada de
medium, outra densidade de legenda. Se esses números batem, o gênero é
rótulo.
"""

import pytest

from curio.config import CurioConfig
from curio.stages import editorial as E
from curio.stages import visuals as V
from curio.stages.scenes import Chapter, scenes_for_length


# --- o registro --------------------------------------------------------

def test_seis_generos_com_labels_distintos():
    chaves = [k for k, _l in E.choices()]
    assert chaves == ["history", "etymology", "mythology", "mystery",
                      "science", "people"]
    rotulos = [l for _k, l in E.choices()]
    assert len(set(rotulos)) == 6


def test_perfil_desconhecido_da_none():
    assert E.get("inexistente") is None
    assert E.get("") is None
    assert E.get(None) is None


def test_genero_e_case_insensitive():
    assert E.get("PEOPLE") is E.get("people")


def test_todo_perfil_tem_os_campos_obrigatorios():
    for chave, _ in E.choices():
        p = E.get(chave)
        assert p.description, chave
        assert p.narrative.direction, chave
        assert p.narrative.avoid, chave
        assert p.ending, chave
        assert p.caption, chave
        assert p.visual.scene_direction, chave
        assert p.pacing.target_scene_seconds > 0, chave


# --- pacing é número, não adjetivo ------------------------------------

def _cenas(perfil, palavras: int) -> int:
    """Conta cenas como o pipeline faz: alvo E teto do perfil."""
    return scenes_for_length(palavras, perfil.pacing.target_scene_seconds,
                             perfil.pacing.max_scenes)


def test_cada_genero_produz_um_numero_de_cenas_diferente():
    """A diferença mais visível: quantas cenas o mesmo roteiro vira."""
    palavras = 298
    contagens = {k: _cenas(E.get(k), palavras) for k, _ in E.choices()}
    assert len(set(contagens.values())) >= 4, contagens
    # etimologia é o mais rápido, ciência e pessoas os mais lentos
    assert contagens["etymology"] == max(contagens.values())
    assert contagens["science"] < contagens["etymology"]
    assert contagens["people"] < contagens["etymology"]


def test_pacing_alvo_e_invertido_entre_os_extremos():
    rapidos = {"etymology", "history"}
    lentos = {"science", "people", "mythology"}
    for k in rapidos:
        assert E.get(k).pacing.target_scene_seconds <= 9.0, k
    for k in lentos:
        assert E.get(k).pacing.target_scene_seconds >= 12.0, k


def test_cena_tem_limite_minimo_e_maximo_por_genero():
    for k, _ in E.choices():
        p = E.get(k).pacing
        assert 2.0 <= p.min_scene_seconds < p.target_scene_seconds, k
        assert p.target_scene_seconds <= p.max_scene_seconds, k


def test_densidade_de_legenda_diferente_por_genero():
    etim = E.get("etymology").pacing
    cien = E.get("science").pacing
    assert etim.caption_max_words < cien.caption_max_words
    assert etim.caption_max_words <= 4
    assert cien.caption_max_words >= 6


def test_pacing_muda_a_saida_real_das_cenas():
    """Não é só o parâmetro: a função de contagem realmente muda."""
    # 298 palavras é o caso real (roteiro de ~2 min). Acima de ~14 cenas
    # o teto de scenes_for_length achata as três contagens, e o teste
    # mediria o teto em vez do pacing.
    palavras = 298
    base = scenes_for_length(palavras)
    cien = _cenas(E.get("science"), palavras)
    etim = _cenas(E.get("etymology"), palavras)
    assert etim > base > cien
    assert len({base, cien, etim}) == 3


# --- diretrizes de pesquisa e narrativa -------------------------------

def test_estrategia_de_pesquisa_difere_por_genero():
    consultas = {k: set(E.get(k).research.queries) for k, _ in E.choices()}
    assert "cognato" in consultas["etymology"]
    assert "biografia" in consultas["people"]
    assert "mecanismo" in consultas["science"]
    assert consultas["etymology"] != consultas["people"]


def test_etimologia_exige_separar_origem_de_hipotese():
    d = E.get("etymology").research.must_distinguish
    assert "origem documentada" in d and "hipótese" in d


def test_misterio_exige_separar_fato_de_hipotese():
    d = E.get("mystery").research.must_distinguish
    assert "fato documentado" in d
    assert any("hipótese" in x for x in d)


def test_pessoas_exige_resolver_a_identidade():
    """Um homônimo é um erro de fonte, não de roteiro."""
    g = E.get("people").research.guidance
    assert "QUEM" in g or "quem" in g
    assert "homônimo" in g.lower() or "homonimo" in g.lower()


def test_pessoas_proibe_biografia_cronologica_seca():
    a = E.get("people").narrative.avoid
    assert "hagiografia" in a or "propaganda" in a


def test_mistério_proibe_inventar_resolução():
    assert "resolução" in E.get("mystery").narrative.avoid


def test_historia_proibe_resumo_cronologico():
    assert "cronol" in E.get("history").narrative.avoid


def test_bloco_de_roteiro_muda_por_genero():
    a = E.script_directive(E.get("people"))
    b = E.script_directive(E.get("etymology"))
    assert a != b
    assert "legado" in a.lower()
    assert "significado" in b.lower() or "origem" in b.lower()


def test_blocos_vazios_sem_genero():
    assert E.script_directive(None) == ""
    assert E.research_directive(None) == ""
    assert E.scene_directive(None) == ""


# --- estratégia visual ------------------------------------------------

def test_escada_de_medium_difere_por_genero():
    ch = Chapter(id=1, narration="x", duration_estimate=5.0,
                 visual_type="mechanism", subject="s")
    cien = V.strategies_for(ch, "science")
    etim = V.strategies_for(ch, "etymology")
    assert cien[0] == "diagram", cien
    assert etim[0] == "typographic", etim
    assert cien != etim


def test_ciencia_nao_pega_foto_decorativa_antes_do_diagrama():
    ch = Chapter(id=1, narration="x", duration_estimate=5.0,
                 visual_type="mechanism", subject="s")
    esc = V.strategies_for(ch, "science")
    assert esc.index("diagram") < esc.index("literal")


def test_etimologia_tem_tipografia_antes_de_foto():
    ch = Chapter(id=1, narration="x", duration_estimate=5.0,
                 visual_type="literal", subject="s")
    esc = V.strategies_for(ch, "etymology")
    assert esc.index("typographic") < esc.index("literal")


def test_sem_genero_a_escada_continua_sendo_a_do_tipo():
    ch = Chapter(id=1, narration="x", duration_estimate=5.0,
                 visual_type="mechanism", subject="s")
    assert V.strategies_for(ch, "") == ["diagram", "card"]


def test_forma_preferida_difere_por_genero():
    ch = Chapter(id=1, narration="Uma frase com quatro palavras aqui.",
                 duration_estimate=5.0, visual_type="mechanism", subject="x",
                 visual_entities=["a", "b"])
    assert V.choose_form(ch, None, "people") == E.get("people").visual.\
        preferred_forms[0]
    assert V.choose_form(ch, None, "science") == E.get("science").visual.\
        preferred_forms[0]


def test_etimologia_nao_repete_o_rosto_da_pessoa():
    """Continuidade visual: pessoa + época + lugar + obra."""
    assert "rosto" in E.get("people").visual.avoid or "retrato" in \
        E.get("people").visual.avoid
    assert "portrait painting" in E.get("people").visual.media_hints


def test_mitologia_nao_aplica_terror_por_padrao():
    assert "terror" in E.get("mythology").visual.avoid


def test_ciencia_avisa_sobre_laboratorio_decorativo():
    assert "laboratório" in E.get("science").visual.avoid


def test_diretriz_de_cena_muda_por_genero():
    a = E.scene_directive(E.get("people"))
    b = E.scene_directive(E.get("etymology"))
    assert a != b
    assert "PALAVRA" in b or "palavra" in b
    assert "pessoa" in a.lower()


# --- config, persistência e compatibilidade ---------------------------

def test_genero_vazio_preserva_comportamento():
    cfg = CurioConfig.load(None)
    assert cfg.genre == ""
    assert E.get(cfg.genre) is None


def test_genero_lido_da_config(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('genre = "people"\n', encoding="utf-8")
    assert CurioConfig.load(str(p)).genre == "people"


def test_genero_por_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_GENRE", "Science")
    assert CurioConfig.load(None).genre == "science"


def test_genero_desconhecido_nao_quebra_nem_e_normalizado_silenciosamente(
        tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('genre = "inexistente"\n', encoding="utf-8")
    cfg = CurioConfig.load(str(p))
    assert cfg.genre == "inexistente"
    assert E.get(cfg.genre) is None


def test_resumo_do_perfil_para_metadata():
    s = E.summary(E.get("people"))
    assert s["key"] == "people"
    assert s["pacing"]["target_scene_seconds"] == 13.0
    assert s["pacing"]["caption_max_words"] == 6
    assert s["visual"]["preferred_forms"]
    assert s["research"]["queries"]
    vazio = E.summary(None)
    assert vazio["key"] == "" and vazio["pacing"] == {}


# --- integração: dois gêneros, mesmo tema, planos diferentes ---------

def test_mesmo_roteiro_da_planos_editoriais_distintos():
    """O teste conceitual do critério de aceitação.

    A mesma frase, em História de pessoas e em Etimologia, tem de gerar
    planos que diferem em NÚMEROS e ESTRUTURA — não só em rótulo.
    """
    palavras = 298
    pessoas = E.get("people")
    etim = E.get("etymology")
    plano = {}

    for nome, perfil in (("people", pessoas), ("etymology", etim)):
        cenas = _cenas(perfil, palavras)
        ch = Chapter(id=1, narration="Uma frase de teste com conteúdo.",
                     duration_estimate=10.0, visual_type="literal",
                     subject="assunto", visual_entities=["a", "b"])
        plano[nome] = {
            "cenas": cenas,
            "forma": V.choose_form(ch, None, perfil.key),
            "escada": V.strategies_for(ch, perfil.key),
            "legenda": perfil.pacing.caption_max_words,
            "destaque": perfil.pacing.caption_highlight,
            "queries": perfil.research.queries,
            "estrutura": perfil.narrative.direction,
        }

    a, b = plano["people"], plano["etymology"]
    assert a["cenas"] != b["cenas"]
    assert a["escada"] != b["escada"]
    assert a["legenda"] != b["legenda"]
    assert a["estrutura"] != b["estrutura"]
    assert set(a["queries"]) != set(b["queries"])
    # e o que se vê na tela também difere
    assert a["forma"] != b["forma"] or a["escada"] != b["escada"]


def test_genero_nao_altera_projetos_antigos(tmp_path):
    """Um metadata.json sem 'genre' tem de continuar legível."""
    from curio.stages import editorial
    meta = {"title": "x", "duration_actual": 10}
    assert editorial.get(meta.get("genre", "")) is None


# --- estratégia de consulta (a parte que a Wikipedia devolve) --------

def _queries_de(alvo, genre, monkeypatch):
    """Roda a pesquisa com a rede desligada e devolve as queries tentadas."""
    from curio.stages import research as R
    vistas = []

    def fake(q, lang, timeout=None):
        vistas.append(q)
        return []

    monkeypatch.setattr(R, "wikipedia_search", fake)
    monkeypatch.setattr(R, "duckduckgo_abstract", lambda *a, **k: None)
    from curio.stages import entity as EN
    monkeypatch.setattr(EN, "resolve_entity", lambda *a, **k: alvo)
    with pytest.raises(R.ResearchError):
        R.research_topic("qualquer ideia de teste", "pt-BR", max_sources=1,
                         cfg=CurioConfig(), genre=genre)
    return vistas


def test_consulta_de_entidade_une_o_nome_ao_termo_do_genero(monkeypatch):
    from curio.stages.entity import TargetEntity
    alvo = TargetEntity(name="São Bento de Núrsia", is_entity=True)
    qs = _queries_de(alvo, "people", monkeypatch)
    assert qs[0] == "São Bento de Núrsia biografia"
    assert "São Bento de Núrsia obras" in qs
    assert "São Bento de Núrsia legado" in qs


def test_consulta_de_tema_usa_os_topic_terms_do_estagio_de_entidade(
        monkeypatch):
    from curio.stages.entity import TargetEntity
    alvo = TargetEntity(name="Cor azul do céu", is_entity=False,
                        topic_terms=["por que o céu é azul?", "cor do céu",
                                     "dispersão de rayleigh"])
    qs = _queries_de(alvo, "science", monkeypatch)
    assert qs[:3] == ["por que o céu é azul?", "cor do céu",
                      "dispersão de rayleigh"]


def test_consulta_de_tema_nao_pendura_o_termo_na_pergunta(monkeypatch):
    """'por que o céu é azul? mecanismo' não é uma query, é um Frankenstein."""
    from curio.stages.entity import TargetEntity
    alvo = TargetEntity(name="por que o céu é azul?", is_entity=False,
                        topic_terms=["por que o céu é azul?", "cor do céu",
                                     "dispersão de rayleigh"])
    qs = _queries_de(alvo, "science", monkeypatch)
    assert not any("?" in q and "mecanismo" in q for q in qs)
    assert "céu azul mecanismo" in qs or "cor do céu mecanismo" in qs


def test_consulta_nao_repete_termo_que_ja_esta_no_nome(monkeypatch):
    from curio.stages.entity import TargetEntity
    alvo = TargetEntity(name="etimologia salário", is_entity=False,
                        topic_terms=["etimologia salário"])
    qs = _queries_de(alvo, "etymology", monkeypatch)
    assert "etimologia salário etimologia" not in qs
    assert "etimologia salário cognato" in qs


def test_genero_muda_a_primeira_consulta_de_mesma_ideia(monkeypatch):
    from curio.stages.entity import TargetEntity
    alvo = TargetEntity(name="São Bento de Núrsia", is_entity=True)
    assert _queries_de(alvo, "people", monkeypatch)[0] != \
        _queries_de(alvo, "mystery", monkeypatch)[0]


# --- o portão de relevância precisa aceitar a fonte certa --------------

def _fonte(titulo, trecho):
    from curio.stages.research import ResearchSource
    return ResearchSource(title=titulo, url="u", snippet=trecho)


def _alvo_etimologia():
    from curio.stages.entity import TargetEntity
    return TargetEntity(name="Etimologia da palavra salário", is_entity=False,
                        topic_terms=["origem da palavra salário",
                                     "etimologia salário",
                                     "salário significado histórico"])


def test_fonte_que_define_a_palavra_e_aceita():
    """O artigo 'Salário' É a fonte de etimologia. Rejeitá-lo quebra o tema.

    Os topic_terms são frases de busca, e nenhuma fonte se intitula
    'origem da palavra salário' — exigir a frase inteira rejeitava a
    única fonte boa e deixava o tema com zero fontes.
    """
    from curio.stages.entity import source_verdict
    motivo, _ = source_verdict(
        _fonte("Salário", "Salário é a remuneração recebida por um trabalho."),
        _alvo_etimologia())
    assert motivo == "ok"


def test_fonte_que_so_parte_da_palavra_continua_barrada():
    from curio.stages.entity import source_verdict
    for titulo, trecho in [
        ("Via Salária", "A Via Salária é uma rua do centro de Porto Alegre."),
        # tem "salário" na descrição e mesmo assim não é artigo sobre a
        # palavra — o título é que diz sobre o que o artigo é
        ("Pro-labore", "Pro-labore é um adiantamento de salário."),
        ("Instância (ciência da computação)",
         "Em computação, uma instância é um objeto com dados e operações."),
    ]:
        motivo, _ = source_verdict(_fonte(titulo, trecho), _alvo_etimologia())
        assert motivo == "baixa relevância com o tema", titulo


def test_frase_inteira_continua_servindo_de_caminho():
    from curio.stages.entity import source_verdict, TargetEntity
    alvo = TargetEntity(name="Dispersão de Rayleigh", is_entity=False,
                        topic_terms=["dispersão de rayleigh", "céu azul"])
    assert source_verdict(_fonte("Dispersão de Rayleigh",
                                 "A dispersão de Rayleigh explica o céu azul."),
                          alvo)[0] == "ok"
    assert source_verdict(_fonte("Céu", "O céu é azul."), alvo)[0] == \
        "baixa relevância com o tema"


def test_substantivo_final_ignora_ponto_e_interrogacao():
    from curio.stages.entity import _head_noun
    assert _head_noun("por que o céu é azul?") == "azul"
    assert _head_noun("Cor azul do céu") == "céu"
    assert _head_noun("") == ""


def test_tema_sem_nome_e_sem_topic_terms_nao_bloqueia():
    from curio.stages.entity import source_verdict, TargetEntity
    alvo = TargetEntity(name="", is_entity=False, topic_terms=[])
    assert source_verdict(_fonte("Qualquer", "texto"), alvo)[0] == "ok"


def test_entidade_continua_usando_identidade_e_nao_substantivo():
    """A folga é só para tema: nome próprio segue exigindo discriminante."""
    from curio.stages.entity import source_verdict, TargetEntity
    alvo = TargetEntity(name="São Bento", is_entity=True,
                        discriminants=["Núrsia"],
                        forbidden=["Papa Bento"])
    assert source_verdict(_fonte("São Bento de Núrsia",
                                 "Monge italiano do século VI."), alvo)[0] == "ok"
    assert source_verdict(_fonte("Bento", "Um nome qualquer."), alvo)[0] != "ok"
    assert source_verdict(_fonte("Papa Bento XVI", "Bento é um papa."),
                          alvo)[0] == "fala de um homônimo conhecido do tema"


# --- paridade com o pipeline herdado quando não há gênero -------------

def _antigo_por_tamanho(words: int) -> int:
    """scenes_for_length como era antes dos perfis existirem."""
    est = max(1, words) / 150 * 60
    return max(3, min(12, round(est / 9)))


def _antigo_por_duracao(dur: float) -> int:
    """scenes_for_duration como era antes dos perfis existirem."""
    return max(3, min(7, round(dur / 9)))


@pytest.mark.parametrize("words", [40, 80, 150, 225, 298, 400, 600, 900,
                                  1500, 3000, 8000])
def test_sem_genero_o_tamanho_do_roteiro_da_exatamente_o_antigo(words):
    assert scenes_for_length(words) == _antigo_por_tamanho(words)


@pytest.mark.parametrize("dur", [0.0, 10.0, 20.0, 30.0, 45.0, 60.0, 63.0,
                                 90.0, 120.0, 300.0])
def test_sem_genero_a_meta_de_duracao_da_exatamente_o_antigo(dur):
    from curio.stages.scenes import scenes_for_duration
    assert scenes_for_duration(dur) == _antigo_por_duracao(dur)


def test_teto_subiu_so_para_quem_tem_genero():
    """O teto de 12 foi estendido; estender para todos mudaria o vídeo de
    quem não pediu nada. 700 palavras/passam de 12 cenas só com perfil."""
    from curio.stages.scenes import scenes_for_duration
    assert scenes_for_length(700) == 12
    etim = E.get("etymology")
    assert scenes_for_length(700, etim.pacing.target_scene_seconds,
                             etim.pacing.max_scenes) > 12
    cien = E.get("science")
    assert scenes_for_length(700, cien.pacing.target_scene_seconds,
                             cien.pacing.max_scenes) < 12
    assert scenes_for_duration(90.0) == 7
    assert scenes_for_duration(90.0, etim.pacing.target_scene_seconds,
                               etim.pacing.max_scenes) > 7


def test_todo_genero_tem_teto_proprio():
    for chave, _ in E.choices():
        p = E.get(chave)
        assert p.pacing.max_scenes >= 3, chave
        # teto tem de ser coerente com o alvo: 12 cenas cobrem o alvo inteiro
        alvo = p.pacing.target_scene_seconds
        assert p.pacing.max_scenes >= 1, chave
        assert 3 <= p.pacing.max_scenes <= 24, chave


def test_scenes_for_script_respeita_o_genero():
    from curio.stages.visual import scenes_for_script
    cfg = CurioConfig()
    cfg.duration_target = 0
    texto = " ".join(["palavra"] * 700)
    assert scenes_for_script(texto, cfg, "") == _antigo_por_tamanho(700)
    etim = E.get("etymology")
    assert scenes_for_script(texto, cfg, "etymology") == scenes_for_length(
        700, etim.pacing.target_scene_seconds, etim.pacing.max_scenes)


def test_teto_aparece_no_resumo_do_perfil():
    assert E.summary(E.get("etymology"))["pacing"]["max_scenes"] == 20
