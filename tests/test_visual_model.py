"""Etapa 2 — modelo visual da cena.

O contrato: toda cena sabe o que precisa mostrar (`subject`,
`visual_entities`, `context`), o que NÃO pode aparecer (`forbidden`) e
qual estratégia visual serve (`visual_type`). Sem isso, o estágio 3 só
tem `narration` e acaba sorteando foto de banco por qualquer coisa.

Retrocompatibilidade é parte do contrato: um `chapters.json` gravado
antes deste campo tem de continuar carregando, e uma IA que devolve o
formato antigo tem de ser entendida.
"""

import pytest

from curio.stages import nvidia as nv
from curio.stages.scenes import (
    VISUAL_TYPES, Chapter, _coerce_str_list, _coerce_visual_terms,
    build_semantic_scenes, classify_visual_type,
)
from curio.config import CurioConfig


# --- classificação -----------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    # mecanismo: a cena explica um processo que foto não mostra
    ("O papel térmico funciona assim: o calor altera o corante.", "mechanism"),
    ("E é assim que a reação acontece dentro da célula.", "mechanism"),
    ("Passo a passo, a energia se transforma em movimento.", "mechanism"),
    ("How does a lithium battery work inside the cell?", "mechanism"),
    # tipográfico: a ideia É uma palavra
    ("A palavra salário vem do latim salarium.", "typographic"),
    ("O termo quasar tem um significado curious aqui.", "typographic"),
    ("Etymology matters when the word changes meaning.", "typographic"),
    # histórico: pede arte, não foto moderna
    ("São Francisco de Assis nasceu em 1181 e fundou a ordem dos franciscanos.",
     "historical_art"),
    ("Cleópatra foi a última rainha do Egito, no século I a.C.", "historical_art"),
    ("O império Romano caiu no século V.", "historical_art"),
    # literal: dá para fotografar
    ("Um gato preto dorme no sofá de veludo.", "literal"),
    ("A cidade de Lisboa tem Tram 28 e prédios azuis.", "literal"),
    # texto vazio não quebra
    ("", "literal"),
])
def test_classificacao_por_texto(texto, esperado):
    assert classify_visual_type(texto) == esperado


def test_classificacao_sempre_devolve_tipo_conhecido():
    for texto in ("", "a", "Como funciona?", "12345", "º§", "um teste qualquer"):
        assert classify_visual_type(texto) in VISUAL_TYPES


def test_mecanismo_vence_historico():
    """Cena que explica um processo pede diagrama, mesmo falando de um
    santo: a foto do santo não mostra o processo."""
    assert classify_visual_type(
        "Veja como funciona a tinta que os monges faziam no século XII."
    ) == "mechanism"


# --- retrocompatibilidade do Chapter ----------------------------------

def test_chapter_antigo_sem_campos_novos_carrega():
    """chapters.json gravado antes da Etapa 2: não pode quebrar."""
    antigo = {"id": 1, "narration": "Como funciona a impressão térmica?",
              "duration_estimate": 5.0, "start": 0.0, "end": 5.0}
    ch = Chapter.from_dict(antigo)
    assert ch.visual_type == "mechanism"  # derivado, não assumir literal
    assert ch.forbidden == []
    assert ch.visual_entities == []
    assert ch.subject == ""


def test_chapter_com_visual_type_invalido_cai_para_literal():
    ch = Chapter.from_dict({"id": 1, "narration": "Um gato dorme",
                            "visual_type": "banana"})
    assert ch.visual_type == "literal"


def test_round_trip_nao_perde_campo():
    ch = Chapter(id=2, narration="x", duration_estimate=3.0,
                 visual_type="historical_art", subject="saint francis",
                 visual_entities=["fresco", "monk"],
                 context=["basilica"], forbidden=["statue of liberty"])
    rt = Chapter.from_dict(ch.to_dict())
    for campo in ("visual_type", "subject", "visual_entities", "context",
                  "forbidden", "visual_queries", "global_visual_queries"):
        assert getattr(rt, campo) == getattr(ch, campo), campo


# --- coerção dos campos vindos da IA ----------------------------------

def test_lista_nova_preserva_as_frases():
    """A frase inteira é o termo — separar por espaço a destrói."""
    terms, _ = _coerce_visual_terms({"visual_search_terms": [
        "thermal paper receipt", "receipt paper roll",
        "thermal printer receipt"]})
    assert terms == ["thermal paper receipt", "receipt paper roll",
                     "thermal printer receipt"]
    assert "thermal" not in terms, "a frase não pode virar palavra solta"


def test_string_com_virgula_separa_por_virgula():
    terms, _ = _coerce_visual_terms(
        {"visual_search_terms": "thermal receipt, receipt roll, faded receipt"})
    assert terms == ["thermal receipt", "receipt roll", "faded receipt"]


def test_string_com_espaco_mantem_compatibilidade_antiga():
    terms, _ = _coerce_visual_terms({"visual_search_terms": "water glass"})
    assert terms == ["water", "glass"]


def test_campo_legado_visual_queries_ainda_funciona():
    terms, _ = _coerce_visual_terms(
        {"visual_search_terms": "", "visual_queries": ["sal coin"]})
    assert terms == ["sal", "coin"]


def test_termos_sao_limitados_a_cinco():
    terms, _ = _coerce_visual_terms({"visual_search_terms": [
        f"term {i} ctx" for i in range(9)]})
    assert len(terms) == 5


def test_lista_nao_repete_termo():
    terms, _ = _coerce_visual_terms(
        {"visual_search_terms": ["thermal receipt", "thermal receipt"]})
    assert terms == ["thermal receipt"]


@pytest.mark.parametrize("valor,esperado", [
    (["a", "b"], ["a", "b"]),
    ("a, b", ["a", "b"]),
    ("a;b", ["a", "b"]),
    ([], []),
    ("", []),
    (None, []),
    (42, []),
])
def test_coerce_str_list(valor, esperado):
    assert _coerce_str_list({"k": valor}, "k", 5) == esperado


def test_coerce_str_list_respeita_limite():
    assert _coerce_str_list({"k": list("abcdefgh")}, "k", 3) == ["a", "b", "c"]


# --- payload completo da IA -------------------------------------------

@pytest.fixture
def llm(monkeypatch):
    """LLM presente, com payload controlado. monkeypatch restaura sozinho —
    um `del` no módulo apagaria a função real para os testes seguintes."""
    def _set(payload):
        monkeypatch.setattr(nv, "any_llm_available", lambda: True)
        monkeypatch.setattr(nv, "complete_json",
                            lambda *a, **k: (payload, "openrouter:test"))
    return _set


def _build(llm, payload, script="texto"):
    llm(payload)
    plan = build_semantic_scenes(script, CurioConfig.load(None), n_scenes=1)
    return plan.semantic_scenes[0]


def test_payload_novo_e_lido_inteiro(llm):
    ch = _build(llm, {"scenes": [{
        "index": 1,
        "narration": "O papel térmico funciona assim.",
        "subject": "thermal receipt paper",
        "visual_type": "mechanism",
        "visual_search_terms": ["thermal paper receipt", "receipt paper roll"],
        "visual_entities": ["receipt", "paper roll"],
        "context": ["cash register"],
        "forbidden": ["power plant", "wallpaper"],
    }]}, script="O papel térmico funciona assim.")
    assert ch.visual_type == "mechanism"
    assert ch.subject == "thermal receipt paper"
    assert not hasattr(ch, "duration_estimate")
    assert tuple(rep.query for rep in ch.representations) == (
        "thermal paper receipt", "receipt paper roll")
    assert ch.visual_entities == ("receipt", "paper roll")
    assert ch.context == ("cash register",)
    assert ch.forbidden == ("power plant", "wallpaper")


def test_payload_antigo_da_ia_ainda_da_cena_util(llm):
    """IA com prompt antigo: o tipo é derivado do texto, não perdido."""
    ch = _build(llm, {"scenes": [{
        "index": 1, "narration": "Como o papel de recibo muda de cor?",
        "visual_search_terms": "water glass"}]},
        script="Como o papel de recibo muda de cor?")
    assert ch.visual_type == "mechanism"
    assert tuple(rep.query for rep in ch.representations) == ("water", "glass")
    assert ch.forbidden == ()


def test_ia_que_inventa_tipo_desconhecido_cai_para_literal(llm):
    ch = _build(llm, {"scenes": [{
        "index": 1, "narration": "Um gato dorme no sofá.",
        "visual_type": "holographic", "visual_search_terms": "cat sofa"}]},
        script="Um gato dorme no sofá.")
    assert ch.visual_type == "literal"


# --- divisão local (sem chave de LLM) ---------------------------------

def test_divisao_local_tambem_classifica(monkeypatch):
    """Sem chave, a estratégia ainda é dedutível do texto."""
    monkeypatch.setattr(nv, "any_llm_available", lambda: False)
    script = ("O gato dorme no sofá. "
              "O papel térmico funciona assim: o calor altera o corante. "
              "A palavra salário vem do latim salarium.")
    plan = build_semantic_scenes(script, CurioConfig.load(None), n_scenes=3)
    chs = plan.semantic_scenes
    assert plan.source == "local"
    assert all(not hasattr(scene, "start") for scene in chs)
    assert tuple(span.scene_id for span in plan.timeline_spans) == tuple(
        scene.id for scene in chs)
    tipos = {c.visual_type for c in chs}
    assert "mechanism" in tipos or "typographic" in tipos
    assert all(c.visual_type in VISUAL_TYPES for c in chs)


# --- doctor: provedores e camadas de scoring ---------------------------

def test_doctor_lista_provedores_ativos_e_ignorados():
    """Um provedor ignorado precisa dizer POR QUÊ, não só sumir."""
    from curio.config import CurioConfig
    from curio.media.providers import providers_status
    cfg = CurioConfig()
    cfg.media_providers = "wikimedia,provedor-que-nao-existe,openverse"
    ativos, motivos = providers_status(cfg)
    assert [n for n, _ in ativos] == ["wikimedia", "openverse"]
    d = dict(motivos)
    assert "desconhecido" in d["provedor-que-nao-existe"]


def test_doctor_reporta_chave_ausente_como_motivo(monkeypatch):
    from curio.config import CurioConfig
    from curio.media import providers as P
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    cfg = CurioConfig()
    cfg.media_providers = "pixabay"
    ativos, motivos = P.providers_status(cfg)
    assert not ativos
    assert "PIXABAY_API_KEY" in motivos[0][1]


def test_media_providers_none_desliga_tudo_com_motivo():
    from curio.config import CurioConfig
    from curio.media.providers import providers_status
    cfg = CurioConfig()
    cfg.media_providers = "none"
    ativos, motivos = providers_status(cfg)
    assert ativos == []
    assert "none" in motivos[0][1]


# --- clip é plugável e desligado por padrão ---------------------------

def test_clip_desligado_por_padrao(monkeypatch):
    from curio.stages import scoring
    monkeypatch.delenv("CURIO_CLIP_ENABLED", raising=False)
    assert scoring.clip_enabled() is False
    assert scoring.clip_status() is None


def test_clip_sem_bibliotecas_nao_quebra(monkeypatch):
    """Habilitado mas sem torch: avisa e devolve None, não levanta."""
    from curio.stages import scoring
    monkeypatch.setenv("CURIO_CLIP_ENABLED", "1")
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda n: None)
    status = scoring.clip_status()
    assert status is None or "não está instalado" in status


def test_clip_device_sem_torch_devolve_cpu(monkeypatch):
    import importlib.util
    from curio.stages import scoring
    monkeypatch.setattr(importlib.util, "find_spec", lambda n: None)
    assert scoring.clip_device() == "cpu"


def test_clip_device_honra_env_explicito(monkeypatch):
    import importlib.util
    from curio.stages import scoring
    monkeypatch.setattr(importlib.util, "find_spec", lambda n: None)
    monkeypatch.setenv("CURIO_CLIP_DEVICE", "xpu")
    assert scoring.clip_device() == "xpu"


# --- relatório de estratégia visual -----------------------------------

def test_relatorio_visual_conta_estrategia_e_nao_chama_de_falha():
    from curio.metrics import RunMetrics
    m = RunMetrics("s", "i", "n")
    m.media_record_visual_type("mechanism")
    m.media_record_visual_type("literal")
    m.media_record_fallback("diagram")
    m.media_record_score(71.5)
    m.media_record_rejection("nota abaixo do mínimo")
    rel = m.media_visual_report(4)
    assert rel["cenas"] == 4
    assert rel["por_tipo"]["mechanism"] == 1
    assert rel["por_estrategia"]["diagram"] == 1
    assert rel["nota_media"] == 71.5
    assert rel["rejeicoes"]
    # nenhuma cena sem visual -> não é falha
    assert rel["sem_visual"] == 0


def test_relatorio_distingue_assets_unicos_reusados_e_sinteticos():
    from curio.metrics import RunMetrics
    from curio.stages.scene_contract import TimelineSpan
    spans = [TimelineSpan(i, 5.0, 0.0, 5.0) for i in (1, 2, 3)]
    reused = {"asset": {"provider": "wiki", "asset_id": "map"}}
    fresh = {"asset": {"provider": "wiki", "asset_id": "event"}}
    synthetic = {"asset": {"provider": "synth", "asset_id": "card"}}
    media = [
        {"chapter_id": 1, "assets": [reused]},
        {"chapter_id": 2, "assets": [reused, fresh]},
        {"chapter_id": 3, "assets": [synthetic]},
    ]
    metrics = RunMetrics("s", "i", "n")
    from curio.media.selection_metrics import MediaMetricsInput
    metrics.visual_plan(spans, MediaMetricsInput.from_persisted_rows(media), 2.1)
    metrics.media_duplicate_queries = 4
    report = metrics.media_visual_report(3)
    assert report["unique_assets"] == 2
    assert report["reused_assets"] == 1
    assert report["reuse_count"] == 1
    assert report["unique_asset_ratio"] == 0.667
    assert report["scenes_with_new_asset"] == 1
    assert report["scenes_with_reused_asset"] == 1
    assert report["synthetic_scenes"] == 1
    assert report["queries_abandoned_duplicates"] == 4


def test_uma_cena_sem_visual_e_a_unica_falha():
    from curio.metrics import RunMetrics
    m = RunMetrics("s", "i", "n")
    m.media_record_visual_type("mechanism")
    m.media_record_no_visual()
    assert m.media_visual_report(2)["sem_visual"] == 1
