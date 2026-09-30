"""Regressão: as fontes de São Bento (o caso real).

Um vídeo sobre a história de São Bento — o santo do século VI — saiu
fundamentado em três fontes autênticas sobre assuntos completamente
diferentes:

    Serra Gaúcha          (município do RS)
    Michel Temer           (pessoa)
    Lei dos Sexagenários  (lei)

E o log dizia "Fundamentação: 3 dado(s) conferidos, todos nas fontes", o
que era verdadeiro e irrelevante: o roteiro era fiel às fontes, e as
fontes não eram sobre o tema. O sistema se autovalidava em cima do
próprio desvio.

Estes testes travam a porta: fontes de homônimo não podem fundamentar um
tema, e a fonte certa tem que continuar entrando.
"""

import pytest

from curio.stages import entity as E
from curio.stages import research as R
from curio.stages.research import ResearchError, ResearchSource

# As três fontes que entraram no vídeo errado, com os trechos que a
# Wikipedia de fato devolve.
SERRA_GAUCHA = ResearchSource(
    title="Serra Gaúcha",
    url="https://pt.wikipedia.org/wiki/Serra_Gaucha",
    snippet="A Serra Gaúcha é uma região do Rio Grande do Sul. Faz "
            "limite com o município de São Bento, que faz parte da região.")
MICHEL_TEMER = ResearchSource(
    title="Michel Temer",
    url="https://pt.wikipedia.org/wiki/Michel_Temer",
    snippet="Michel Temer é um político brasileiro. Bento é um de seus "
            "nomes de registro e há outro político chamado Bento na "
            "mesma lista.")
SEXAGENARIOS = ResearchSource(
    title="Lei dos Sexagenários",
    url="https://pt.wikipedia.org/wiki/Lei_dos_Sexagen%C3%A1rios",
    snippet="A Lei dos Sexagenários é uma lei brasileira sobre direito de "
            "propriedade rural, sem relação com São Bento.")
# A fonte correta: existe na Wikipedia e é sobre o santo.
SAO_BENTO_DE_NURSIA = ResearchSource(
    title="São Bento de Núrsia",
    url="https://pt.wikipedia.org/wiki/S%C3%A3o_Bento_de_N%C3%BArsia",
    snippet="São Bento de Núrsia (Núrsia, 480 – Monte Cassino, 547) foi um "
            "monge e abade italiano. Fundou a ordem de São Bento e é "
            "considerado padroeiro da Europa.")


def _alvo():
    """O alvo que a resolução por LLM produz para este tema."""
    return E.TargetEntity(
        name="São Bento de Núrsia",
        aliases=["São Bento", "Benedito de Nursia"],
        discriminants=["Núrsia", "Nursia", "Benedito", "monge italiano"],
        search_queries=["São Bento de Núrsia", "Benedito de Nursia monge"],
        forbidden=["Serra Gaúcha", "São Bento município", "Bento sobrenome"],
        is_entity=True, source="llm")


# --- as fontes erradas NÃO podem fundamentar ---------------------------

@pytest.mark.parametrize("fonte,nome", [
    (SERRA_GAUCHA, "Serra Gaúcha"),
    (MICHEL_TEMER, "Michel Temer"),
    (SEXAGENARIOS, "Lei dos Sexagenários"),
])
def test_homonimo_e_rejeitado(fonte, nome):
    motivo, _ = E.source_verdict(fonte, _alvo())
    assert motivo != E.REASON_OK, f"{nome} foi aceito como fonte do tema"


def test_o_motivo_diz_que_e_homonimo():
    """A Serra Gaúcha CITA 'São Bento' — é por isso que passou antes."""
    assert E.source_verdict(SERRA_GAUCHA, _alvo())[0] == E.REASON_FORBIDDEN
    # "Bento" sozinho não é o nome do santo: nem chega ao discriminante.
    assert E.source_verdict(MICHEL_TEMER, _alvo())[0] == E.REASON_ENTITY
    # A Lei dos SexagenARIOS CITA "São Bento" (para dizer que não tem
    # relação), então passa pelo nome e cai no discriminante — que é
    # precisamente o caso que prova que citar o nome não basta.
    assert E.source_verdict(SEXAGENARIOS, _alvo())[0] == E.REASON_DISCRIMINANT


def test_coincidencia_de_nome_nao_basta_sem_discriminante():
    """Sem o discriminante, a fonte cita o nome e nada mais.

    Este é o teste que isola o mecanismo: tira "Núrsia" da lista de
    proibidos e da de discriminantes, e a fonte errada volta a passar.
    """

    alvo = E.TargetEntity(name="São Bento de Núrsia",
                          aliases=["São Bento"],
                          discriminants=["Núrsia"],
                          forbidden=[], is_entity=True)
    # com o discriminante: rejeitada
    assert E.source_verdict(SERRA_GAUCHA, alvo)[0] == E.REASON_DISCRIMINANT
    # sem discriminante algum: aceita, porque só há o nome em comum
    fraco = E.TargetEntity(name="São Bento", aliases=[], discriminants=[],
                           forbidden=[], is_entity=True)
    assert E.source_verdict(SERRA_GAUCHA, fraco)[0] == E.REASON_OK


# --- a fonte CERTA tem que continuar entrando -------------------------

def test_fonte_certa_e_aceita():
    motivo, _ = E.source_verdict(SAO_BENTO_DE_NURSIA, _alvo())
    assert motivo == E.REASON_OK


def test_resolucao_heuristica_marca_ambiguidade():
    """Sem LLM, o nome curto tem de ser sinalizado como ambíguo."""
    alvo = E.resolve_entity_heuristic("Fale da História de São Bento")
    assert alvo.is_entity is True
    assert alvo.name == "São Bento"
    assert alvo.discriminants == []
    assert alvo.source == "heuristic"
    # e a limitação é dita, não escondida
    assert "homônimos podem passar" in E.explain(alvo, [], [])


def test_tema_com_nome_composto_acha_o_nome_certo():
    for ideia, esperado in [
        ("Fale da História de São Bento", "São Bento"),
        ("História de Roma Antiga", "Roma Antiga"),
        ("A vida de Alexandre, o Grande", "Alexandre"),
    ]:
        blocos = E._capitalized_spans(ideia)
        assert esperado in blocos, f"{ideia!r} -> {blocos}"


# --- a ambiguidade legítima: dois "Alexandre" --------------------------

def test_ambiguidade_legitima_aceita_o_certo_e_barra_o_outro():
    """Alexandre o Grande vs. Alexandre Dumas: mesmo nome, entidades distintas.

    Aqui a ambiguidade é real e o portão tem que acertar as duas.
    """
    alvo = E.TargetEntity(
        name="Alexandre, o Grande",
        aliases=["Alexandre Magno"],
        discriminants=["Macedônia", "Rosto", "Reino da Macedônia"],
        forbidden=[],
        search_queries=["Alexandre o Grande"],
        is_entity=True, source="llm")
    certo = ResearchSource(
        title="Alexandre, o Grande",
        url="https://pt.wikipedia.org/wiki/Alexandre,_o_Grande",
        snippet="Alexandre, o Grande foi rei da Macedônia e roi do Império "
                "Persa, nascido em Pella.")
    errado = ResearchSource(
        title="Alexandre Dumas",
        url="https://pt.wikipedia.org/wiki/Alexandre_Dumas",
        snippet="Alexandre Dumas foi um romancista francês, autor do "
                "Conde de Monte Cristo.")
    assert E.source_verdict(certo, alvo)[0] == E.REASON_OK
    assert E.source_verdict(errado, alvo)[0] == E.REASON_DISCRIMINANT


# --- o portão tem de derrubar a pipeline, não só a função --------------

def test_research_topic_rejeita_e_explica(monkeypatch):
    """Sem fonte do tema certo, a pipeline PARA — e diz por quê."""
    import curio.stages.research as mod
    acervo = {"Serra Gaúcha": SERRA_GAUCHA, "Michel Temer": MICHEL_TEMER,
              "Lei dos Sexagenários": SEXAGENARIOS}

    def fake(url, timeout=20):
        if "list=search" in url:
            return {"query": {"search": [{"title": t} for t in acervo]}}
        if "prop=extracts" in url:
            import urllib.parse as up
            titulo = (up.parse_qs(up.urlparse(url).query).get("titles")
                      or [""])[0]
            art = acervo.get(titulo)
            if not art:
                return {"query": {"pages": {}}}
            return {"query": {"pages": {"1": {"title": titulo,
                                               "extract": art.snippet}}}}
        if "api.duckduckgo.com" in url:
            return {"AbstractText": "", "AbstractURL": ""}
        raise AssertionError(f"URL inesperada: {url}")

    monkeypatch.setattr(mod, "_get_json", fake)
    monkeypatch.setattr(E, "resolve_entity", lambda *a, **k: _alvo())
    with pytest.raises(ResearchError) as exc:
        mod.research_topic("Fale da História de São Bento", max_sources=3)
    msg = str(exc.value)
    assert "São Bento de Núrsia" in msg
    assert "homônimo" in msg
    # a mensagem cita as fontes descartadas: é o que permite reconhecer
    # o desvio sem abrir o log inteiro
    assert "Serra Gaúcha" in msg


def test_research_topic_aceita_quando_ha_fonte_do_tema(monkeypatch):
    import curio.stages.research as mod
    acervo = {"Serra Gaúcha": SERRA_GAUCHA, "São Bento de Núrsia":
              SAO_BENTO_DE_NURSIA}

    def fake(url, timeout=20):
        if "list=search" in url:
            return {"query": {"search": [{"title": t} for t in acervo]}}
        if "prop=extracts" in url:
            import urllib.parse as up
            titulo = (up.parse_qs(up.urlparse(url).query).get("titles")
                      or [""])[0]
            art = acervo.get(titulo)
            if not art:
                return {"query": {"pages": {}}}
            return {"query": {"pages": {"1": {"title": titulo,
                                               "extract": art.snippet}}}}
        if "api.duckduckgo.com" in url:
            return {"AbstractText": "", "AbstractURL": ""}
        raise AssertionError(f"URL inesperada: {url}")

    monkeypatch.setattr(mod, "_get_json", fake)
    monkeypatch.setattr(E, "resolve_entity", lambda *a, **k: _alvo())
    res = mod.research_topic("Fale da História de São Bento", max_sources=3)
    fontes = list(res)
    assert [f.title for f in fontes] == ["São Bento de Núrsia"]
    # a rejeitada continua registrada, com motivo
    titulos_rejeitados = [s.title for s, _m, _d in res.rejected]
    assert "Serra Gaúcha" in titulos_rejeitados
    motivos = {m for _s, m, _d in res.rejected}
    assert E.REASON_FORBIDDEN in motivos


def test_diagnostico_mostra_alvo_aceitas_e_rejeitadas():
    alvo = _alvo()
    txt = E.explain(alvo, [SAO_BENTO_DE_NURSIA],
                    [(SERRA_GAUCHA, E.REASON_FORBIDDEN, "Serra Gaúcha"),
                     (MICHEL_TEMER, E.REASON_DISCRIMINANT, "")])
    assert "São Bento de Núrsia" in txt
    assert "Núrsia" in txt
    assert "Fontes aceitas (1)" in txt
    assert "Fontes rejeitadas (2)" in txt
    assert "homônimo" in txt
    assert "motivo:" in txt


# --- o gate tem que CONTINUAR funcionando sem entidade ----------------

def test_tema_comum_continua_funcionando():
    """'Por que o mar é salgado?' não tem entidade e não pode quebrar.

    O portão mede identidade quando há nome próprio e pertinência
    temática quando não há. Exigir a frase inteira rejeitaria todas as
    fontes de um tema que sempre funcionou.
    """
    alvo = E.resolve_entity_heuristic("Por que o mar é salgado?")
    assert alvo.is_entity is False
    mar = ResearchSource(
        title="Mar", url="https://pt.wikipedia.org/wiki/Mar",
        snippet="O mar é a maior massa de água salgada do planeta.")
    erro = ResearchSource(
        title="Astronomia", url="https://pt.wikipedia.org/wiki/Astronomia",
        snippet="Astronomia é a ciência que estuda os astros e o universo.")
    assert E.source_verdict(mar, alvo)[0] == E.REASON_OK
    assert E.source_verdict(erro, alvo)[0] == E.REASON_OFFTOPIC


def test_tema_comum_aceita_qualquer_um_dos_termos():
    alvo = E.resolve_entity_heuristic("Como funciona a impressão térmica "
                                      "do recibo?")
    assert set(alvo.topic_terms) & {"impressao", "recibo", "termica"}
    fonte = ResearchSource(
        title="Impressora térmica", url="https://pt.wikipedia.org/wiki/X",
        snippet="Uma impressora térmica usa calor para imprimir.")
    assert E.source_verdict(fonte, alvo)[0] == E.REASON_OK


def test_termos_de_topico_aceitam_palavras_de_3_letras():
    assert "mar" in E.topic_terms_of("Por que o mar é salgado?")
    assert "ocean" in E.topic_terms_of("Why is the ocean salty?")
    for stop in ("por", "que", "the", "why"):
        assert stop not in E.topic_terms_of(f"{stop} {stop} teste")
