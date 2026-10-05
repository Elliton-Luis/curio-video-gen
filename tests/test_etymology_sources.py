"""Fontes especializadas de etimologia: Wiktionary, Logeion, Perseus.

Rede sempre mockada: os testes fixam o wikitexto/HTML e provam parse,
cadeia, prioridade no prompt, entidades visuais, atribuição e degradação
graciosa — sem depender de API externa.
"""

import json

from curio.stages import etymology as E
from curio.stages import research as R
from curio.stages.scene_projection import Chapter


CANDIDATO_PT = """==Portuguese==

===Etymology 1===
{{ety|pt|:lbor|la:candidātus|text=+|tree=1}}

====Noun====
{{pt-noun|m|f=}}

# [[candidate]]
# [[applicant]]"""

CANDIDATUS_LA = """==Latin==

===Etymology 1===
{{etymid|la|adjective}} From {{af|la|candidus|-ātus|t1=white, shining, clear|id2=adjective}}.

====Adjective====
{{la-adj|candidātus}}

# dressed in [[white]]

===Etymology 2===
{{nom|la|candidātus#Adjective}}, since candidates for office wore a white toga.

====Noun====
{{la-noun|candidātus<2>}}

# a [[candidate]] for the [[praetorship]]"""


def _wikitext_for(word):
    return {"candidato": CANDIDATO_PT, "candidātus": CANDIDATUS_LA,
            "candidatus": CANDIDATUS_LA}.get(word)


def test_parse_extracao_de_elo_e_glosa():
    blocks = E.parse_etymology_blocks(CANDIDATO_PT)
    assert blocks[0]["relations"] == [("lbor", "la", "candidātus")]
    blocks = E.parse_etymology_blocks(CANDIDATUS_LA)
    assert "candidus" in blocks[0]["affix_parts"]
    assert blocks[0]["glosses"] == ["white, shining, clear"]
    assert "white toga" in blocks[1]["note"]


def test_cadeia_candidato_ate_candidus():
    chain, origem, codigo = E.build_chain(
        "candidato", "pt-BR", fetch=lambda w, t=20: _wikitext_for(w))
    termos = [e.term for e in chain]
    assert termos[:3] == ["candidato", "candidātus", "candidus"]
    assert codigo == "la" and origem == "latim"
    assert E.Etymology(word="candidato", chain=chain).chain_text().startswith(
        "candidato")


def test_headword_da_ideia():
    assert E.headword_of("De onde veio a palavra candidato?") == "candidato"
    assert E.headword_of('Fale sobre a palavra "escola"') == "escola"
    assert E.headword_of("qual a origem do termo candidato") == "candidato"
    assert E.headword_of("Por que o céu é azul?") == ""


def test_conceitos_visuais_roma_toga():
    chain, _, _ = E.build_chain(
        "candidato", "pt-BR", fetch=lambda w, t=20: _wikitext_for(w))
    entidades, contexto = E.visual_concepts(chain, "candidato")
    assert "candidātus" in entidades and "candidus" in entidades
    assert "candidato" not in entidades  # a palavra pedida não se repete
    assert not any(e.startswith("-") for e in entidades)  # sem afixo solto
    assert "Roma antiga" in contexto and any("toga" in c for c in contexto)


def test_lookup_com_cache_e_fontes_com_licenca(tmp_path, monkeypatch):
    chamadas = []

    def fake_fetch(word, timeout=20):
        chamadas.append(word)
        return _wikitext_for(word)

    monkeypatch.setattr(E, "wiktionary_wikitext", fake_fetch)
    # Logeion/Perseus degradam para referência pura (sem rede real).
    monkeypatch.setattr(E, "_fetch_text", lambda *a, **k: None)
    ety = E.lookup("candidato", "De onde veio a palavra candidato?",
                   "pt-BR", str(tmp_path))
    assert ety is not None and len(ety.chain) >= 3
    origens = [s.origin for s in ety.sources]
    assert origens[0] == "wiktionary"  # primária primeiro
    assert "logeion" in origens and "perseus" in origens
    wikt = ety.sources[0]
    assert wikt.license.startswith("CC BY-SA") and wikt.url.startswith(
        "https://en.wiktionary.org/wiki/")
    assert wikt.license_url.startswith("https://")
    assert all(s.url.startswith("http") for s in ety.sources)
    # Segunda chamada sai do cache: sem nova rede no Wiktionary.
    n = len(chamadas)
    ety2 = E.lookup("candidato", "De onde veio a palavra candidato?",
                    "pt-BR", str(tmp_path))
    assert ety2 is not None and len(chamadas) == n
    assert ety2.chain_text() == ety.chain_text()


def test_lookup_sem_verbete_devolve_none_sem_levantar(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "wiktionary_wikitext", lambda *a, **k: None)
    assert E.lookup("xzq palavra", "xzq palavra", "pt-BR",
                    str(tmp_path)) is None


def test_prompt_prioriza_cadeia_e_manda_parafrasear():
    chain = [E.Etymon(term="candidato", language="português"),
             E.Etymon(term="candidātus", language="latim",
                      language_code="la", gloss="dressed in white",
                      url="https://en.wiktionary.org/wiki/candidatus")]
    ety = E.Etymology(word="candidato", chain=chain, sources=[])
    bloco = E.prompt_block(ety)
    assert "PARAFRASEIE" in bloco and "candidātus" in bloco
    assert "https://en.wiktionary.org/wiki/candidatus" in bloco
    assert E.prompt_block(None) == ""


def test_enrich_preenche_vazio_e_preserva_ia():
    from curio.stages.scene_contract import SemanticScene
    ety = E.Etymology(word="candidato", visual_entities=["candidatus"],
                      visual_context=["Roma antiga"])
    vazia = SemanticScene(1, "A palavra vem do latim.")
    cheia = SemanticScene(2, "Outra cena.", visual_entities=("sal",),
                    context=["roma"])
    enriched = E.enrich_scenes([vazia, cheia], ety)
    assert enriched[0].visual_entities == ("candidatus",)
    assert enriched[0].context == ("Roma antiga",)
    assert enriched[1].visual_entities == ("sal",)  # plano existente intacto
    assert E.enrich_scenes([cheia], None) == (cheia,)


def test_research_etymology_soma_sem_substituir(monkeypatch, tmp_path):
    from curio.stages.entity import TargetEntity
    fake_ety = E.Etymology(
        word="candidato",
        chain=[E.Etymon(term="candidato"), E.Etymon(term="candidatus")],
        sources=[R.ResearchSource(title="Wiktionary — candidato",
                                  url="https://en.wiktionary.org/wiki/candidato",
                                  snippet="candidato → candidatus",
                                  origin="wiktionary")])
    monkeypatch.setattr(E, "lookup", lambda *a, **k: fake_ety)
    monkeypatch.setattr("curio.stages.entity.resolve_entity",
                        lambda *a, **k: TargetEntity(
                            name="candidato", is_entity=False,
                            topic_terms=["candidato"]))
    monkeypatch.setattr(R, "wikipedia_search",
                        lambda *a, **k: [{"title": "Candidato"}])
    monkeypatch.setattr(R, "wikipedia_extract",
                        lambda *a, **k: R.ResearchSource(
                            title="Candidato", url="https://pt.wikipedia.org/wiki/x",
                            snippet="Candidato é ...", origin="wikipedia"))
    res = R.research_topic("De onde veio a palavra candidato?", "pt-BR",
                           max_sources=3, cfg=None, genre="etymology",
                           allow_weak=True)
    assert res.etymology is fake_ety
    assert any(s.origin == "wikipedia" for s in res.sources)  # gerais intactas
    pack = R.format_for_prompt(res, "pt-BR")
    assert pack.index("candidatus") < pack.index("wikipedia")


def test_research_outros_generos_sem_etymology(monkeypatch):
    from curio.stages.entity import TargetEntity
    chamadas = []
    monkeypatch.setattr(E, "lookup",
                        lambda *a, **k: chamadas.append(1) or None)
    monkeypatch.setattr("curio.stages.entity.resolve_entity",
                        lambda *a, **k: TargetEntity(name="Sol"))
    monkeypatch.setattr(R, "wikipedia_search",
                        lambda *a, **k: [{"title": "Sol"}])
    monkeypatch.setattr(R, "wikipedia_extract",
                        lambda *a, **k: R.ResearchSource(
                            title="Sol", url="https://pt.wikipedia.org/wiki/y",
                            snippet="Sol é ...", origin="wikipedia"))
    res = R.research_topic("Por que o sol queima?", "pt-BR", max_sources=1,
                           cfg=None, genre="science", allow_weak=True)
    assert res.etymology is None and not chamadas


def test_attribution_roundtrip_json():
    src = R.ResearchSource(title="Wiktionary — x", url="https://u",
                           snippet="s", origin="wiktionary",
                           license="CC BY-SA 4.0", license_url="https://l")
    d = json.loads(json.dumps(src.to_dict()))
    volta = R.ResearchSource.from_dict(d)
    assert (volta.license, volta.license_url) == ("CC BY-SA 4.0", "https://l")
    velho = R.ResearchSource.from_dict({"title": "t", "url": "u"})
    assert (velho.license, velho.origin) == ("", "wikipedia")
