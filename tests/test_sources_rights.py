"""Fontes, direitos autorais e conferência anti-invenção.

Três promessas que precisam ser verificáveis, não só documentadas:
1. nenhum texto sai sem ao menos uma fonte real (RAG);
2. o que a IA afirma em número/data tem de bater com a fonte;
3. imagem com licença bloqueada não entra no vídeo, e toda imagem usada
   fica registrada com autor/licência/link na pasta de informações.
"""

import json
import os

import pytest

from curio.config import CurioConfig
from curio.media.providers import classify_rights, license_ok
from curio.stages import research as R
from curio.stages import sources as S


def _src(title="Marte", url="https://pt.wikipedia.org/wiki/Marte",
         snippet="Marte é o quarto planeta do Sistema Solar.", origin="wikipedia"):
    return R.ResearchSource(title=title, url=url, snippet=snippet, origin=origin)


# --- grounding: a IA não inventa número -------------------------------

def test_numero_que_esta_na_fonte_e_confirmado():
    out = R.verify_grounding(
        "Marte leva 687 dias para dar a volta no Sol.",
        [_src(snippet="Marte completa sua órbita em 687 dias terrestres.")])
    assert out["checked"] >= 1
    assert "687" in out["grounded"]
    assert out["unverified"] == []
    assert out["coverage"] == 1.0


def test_numero_ausente_das_fontes_e_apontado():
    out = R.verify_grounding(
        "Marte tem 12 volcanoes e 900 crateras.",
        [_src(snippet="Marte é o quarto planeta do Sistema Solar.")])
    assert out["unverified"], "número inventado passou sem conferência"
    assert "12" in out["unverified"]
    assert out["coverage"] < 1.0


def test_ano_e_medida_sao_conferidos():
    out = R.verify_grounding(
        "Oreated em 1969, com 38 km de distância da Terra.",
        [_src(snippet="Apollo 11 landed in 1969, about 384000 km away.")])
    assert "1969" in out["grounded"]
    assert "38" in out["unverified"]  # a fonte traz 384000 km, não 38 km


def test_roteiro_sem_numeros_passa_por_cem_por_cento():
    out = R.verify_grounding(
        "A água do mar é salgada por causa da evaporação.",
        [_src()])
    assert out["checked"] == 0
    assert out["coverage"] == 1.0
    assert out["unverified"] == []


def test_sem_fontes_tudo_fica_nao_verificado():
    out = R.verify_grounding("Diz 42%", [])
    assert out["unverified"]


def test_mesmos_numeros_com_formatos_diferentes_batem():
    """'1.500' no texto e '1500' na fonte são o mesmo fato."""
    out = R.verify_grounding("A cidade tinha 1.500 habitantes em 1880.",
                             [_src(snippet="População: 1500 habitantes (1880).")])
    assert out["unverified"] == [], out


def test_grounding_nao_quebra_com_texto_vazio():
    out = R.verify_grounding("", [_src()])
    assert out["checked"] == 0 and out["coverage"] == 1.0


# --- fontes: ao menos uma, senão falha explícita -----------------------

def test_sem_fonte_a_pesquisa_falha_explicitamente(monkeypatch):
    """A promessa 'nunca só a IA' precisa ser falha, não script vazio.

    Rede fora da equação: a Wikipedia é stubada para não devolver nada, e
    o DuckDuckGo (que hoje é o complemento) também. O que se verifica é o
    contrato: sem fonte nenhuma, levanta ResearchError.
    """
    monkeypatch.setattr(R, "wikipedia_search",
                        lambda *a, **k: (_ for _ in ()).throw(
                            R.ResearchError("sem rede")))
    monkeypatch.setattr(R, "duckduckgo_abstract", lambda *a, **k: None)
    with pytest.raises(R.ResearchError):
        R.research_topic("assunto sem nenhuma fonte", max_sources=3)


def test_fonte_unica_ja_satisfaz_o_requisito(monkeypatch):
    """O piso é ≥1 fonte, não 'tantas quanto possível'."""
    monkeypatch.setattr(R, "wikipedia_search",
                        lambda *a, **k: [{"title": "Marte"}])
    monkeypatch.setattr(R, "wikipedia_extract",
                        lambda t, *a, **k: _src(snippet="Marte: 687 dias."))
    monkeypatch.setattr(R, "duckduckgo_abstract", lambda *a, **k: None)
    found = R.research_topic("quanto tempo Marte leva", max_sources=1)
    assert len(found) == 1
    assert found[0].url.startswith("https://")


def test_prompt_de_fontes_e_injetado_no_roteiro():
    pack = R.format_for_prompt([_src()], "pt-BR")
    assert "FONTES OBRIGATÓRIAS" in pack
    assert "https://pt.wikipedia.org/wiki/Marte" in pack
    pack_en = R.format_for_prompt([_src()], "en-US")
    assert "MANDATORY SOURCES" in pack_en


# --- direitos autorais ------------------------------------------------

@pytest.mark.parametrize("lic,esperado", [
    ("CC0 1.0", "clear"),
    ("Public domain", "clear"),
    ("CC BY-SA 4.0", "clear"),
    ("Pixabay License", "clear"),
    ("CC BY-NC 2.0", "verify"),
    ("", "verify"),
    ("Todos os direitos reservados", "blocked"),
    ("© 2024 somebody", "blocked"),
])
def test_classificacao_de_licenca(lic, esperado):
    assert classify_rights(lic, "wikimedia") == esperado


def test_licenca_nd_e_rejeitada_para_video():
    assert not license_ok("CC BY-ND 4.0")
    assert license_ok("CC BY 4.0")


def test_licenca_bloqueada_nao_passa_no_gate_do_visual():
    """O gate que roda ANTES do download descarta licença bloqueada."""
    from curio.stages.visual import _validate_asset
    from curio.media.providers import MediaAsset
    blocked = MediaAsset(provider="wikimedia", asset_id="x",
                         title="Foto protegida",
                         download_url="https://exemplo.org/foto.jpg",
                         license="Todos os direitos reservados", width=2000,
                         height=2000)
    assert not _validate_asset(blocked)


def test_licenca_livre_passa_no_gate():
    from curio.stages.visual import _validate_asset
    from curio.media.providers import MediaAsset
    ok = MediaAsset(provider="wikimedia", asset_id="y", title="Foto livre",
                    download_url="https://exemplo.org/livre.jpg",
                    license="CC0 1.0", width=2000, height=2000)
    assert _validate_asset(ok)


# --- registro e relatório ---------------------------------------------

def test_relatorio_traz_fontes_e_imagens(tmp_path):
    reg = S.SourceRegistry(slug="meu-projeto")
    reg.add_claim(claim="Marte tem dois luas", title="Marte",
                  url="https://pt.wikipedia.org/wiki/Marte",
                  evidence="Marte possui Fobos e Deimos.", status="confirmed")
    reg.add_media(title="Cratera de Marte", origin_url="https://nasa.gov/x",
                  file_url="https://nasa.gov/x.jpg",
                  provider="nasa", author="NASA", license="Public domain",
                  license_url="https://nasa.gov/licenca",
                  local_path="output/x/media/nasa/y.jpg",
                  used_in="cena 2", rights_status="clear")
    reg.add_media(title="Foto sem licença clara", origin_url="https://ex.org/z",
                  file_url="https://ex.org/z.jpg",
                  provider="desconhecido", license="", rights_status="verify")

    out = tmp_path / "FONTES.md"
    S.write_report(str(out), reg, research=[_src()],
                   grounding={"checked": 3, "coverage": 0.667,
                              "grounded": ["2"], "unverified": ["7"]})
    txt = out.read_text(encoding="utf-8")

    # informações
    assert "Marte tem dois luas" in txt
    assert "https://pt.wikipedia.org/wiki/Marte" in txt
    # imagens + copyright
    assert "Cratera de Marte" in txt
    assert "Public domain" in txt
    assert "https://nasa.gov/licenca" in txt
    assert "cena 2" in txt
    assert "livre (uso comercial permitido)" in txt
    # licença incente não aparece como liberada
    assert "REVISAR" in txt
    # conferência anti-invenção
    assert "anti-invenção" in txt
    assert "`7`" in txt


def test_registro_nao_duplica_fontes():
    reg = S.SourceRegistry(slug="p")
    a = reg.add_claim(claim="c", title="t", url="u", evidence="e")
    b = reg.add_claim(claim="c", title="t", url="u", evidence="e")
    assert a is b
    assert len(reg.claims) == 1


def test_registro_sobrevive_a_reabertura(tmp_path):
    p = str(tmp_path / "sources.json")
    reg = S.SourceRegistry(slug="p")
    reg.add_claim(claim="c", title="t", url="u", evidence="e")
    reg.add_media(title="img", origin_url="o", file_url="f",
                  provider="nasa")
    reg.save(p)

    outro = S.SourceRegistry.load(p)
    assert outro.slug == "p"
    assert outro.claims[0].url == "u"
    assert outro.media[0].provider == "nasa"
    assert json.loads(open(p, encoding="utf-8").read())["slug"] == "p"


def test_registro_corrompido_nao_derruba_o_projeto(tmp_path):
    p = tmp_path / "sources.json"
    p.write_text("{isto nao e json", encoding="utf-8")
    assert S.SourceRegistry.load(str(p)).claims == []


def test_status_de_evidencia_desconhecido_vira_nao_verificado():
    assert S.Source.from_dict({"claim": "c", "title": "t", "url": "u",
                               "status": "inventado"}).status == "unverified"


# --- config das inserções ---------------------------------------------

def test_config_padrao_de_insercao_e_1_ou_2():
    cfg = CurioConfig.load(None)
    assert cfg.visual_insertions == 2
    assert cfg.visual_insert_style == "drop_in"
    assert -45 <= cfg.visual_insert_gain_db <= -12


def test_config_limita_insercoes_e_ganho(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[visual]\ninsertions = 99\ninsert_gain_db = 0\n',
                 encoding="utf-8")
    cfg = CurioConfig.load(str(p))
    assert cfg.visual_insertions == 5
    assert cfg.visual_insert_gain_db == -12


def test_config_rejeita_estilo_desconhecido(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[visual]\ninsert_style = "explodir"\n', encoding="utf-8")
    assert CurioConfig.load(str(p)).visual_insert_style == "drop_in"


def test_config_por_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_VISUAL_INSERTIONS", "1")
    monkeypatch.setenv("CURIO_VISUAL_INSERT_GAIN_DB", "-40")
    cfg = CurioConfig.load(None)
    assert cfg.visual_insertions == 1
    assert cfg.visual_insert_gain_db == -40
