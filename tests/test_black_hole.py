"""Regressão do caso real: vídeo sobre buracos negros sem foto de buraco negro.

O último vídeo do tema saiu ilustrado com laboratório, microscópio e o
rover Curiosity ("Mars Science Laboratory" casa com a query "laboratory"),
porque:
- as cenas locais vinham sem `visual_queries`/`subject` (núcleo do scoring
  virava a narração em PT contra títulos em EN: nota 0);
- `PT_EN` não conhecia "buraco negro" (queries viravam "field"/"time");
- o fallback genérico de ciência era bancada ("laboratory");
- "mito" em "não é um mito de ficção científica" virava `historical_art`.
"""

from types import SimpleNamespace

from curio.media.providers import MediaAsset
from curio.metrics import RunMetrics
from curio.stages import media_rules, scoring
from curio.stages import scenes as S
from curio.stages import visual as V
from curio.stages.scene_local_planning import (
    local_visual_representations, recover_legacy_chapters)
from curio.stages.scenes import Chapter


N1 = ("Um buraco negro é um objeto astronômico denso e massivo cujo intenso "
      "campo gravitacional impede qualquer coisa de escapar, inclusive a luz. "
      "Isso não é um mito de ficção científica.")
N4 = ("Essa radiação tem o mesmo espectro que um corpo negro de temperatura "
      "inversamente proporcional à sua massa.")


def _ch(narration, **extra):
    base = dict(visual_queries=[], global_visual_queries=[],
                visual_type="literal", subject="", subject_aliases=[],
                visual_entities=[], context=[], forbidden=[])
    base.update(extra)
    return Chapter(id=1, narration=narration, duration_estimate=5, **base)


def test_queries_locais_trazem_buraco_negro():
    assert local_visual_representations(N1)[0] == "black hole"
    assert local_visual_representations(N4)[0] == "black hole"


def test_cascata_espacial_sem_laboratorio():
    from tests.test_support.search_plan import plan_queries
    local = _ch(N1)
    assert recover_legacy_chapters([local])
    qs, generics = plan_queries(local)
    assert "black hole" in qs
    assert "laboratory" not in qs
    assert "microscope" not in qs
    assert generics and "laboratory" not in generics
    legacy = _ch(N4)
    assert recover_legacy_chapters([legacy])
    qs4, _ = plan_queries(legacy)
    assert "black hole" in qs4
    assert "laboratory" not in qs4


def test_cena_espacial_bloqueia_bancada_e_msl():
    ch = _ch(N1, visual_queries=["black hole"], subject="black hole",
             visual_entities=["black hole"])
    bloqueados = media_rules.scene_blocklist(ch)
    assert "laboratory" in bloqueados
    assert media_rules.rejection_reason(
        {"title": "chemistry laboratory microscope"}, bloqueados)
    assert media_rules.rejection_reason(
        {"title": "Mars Science Laboratory Mission Curiosity Rover Stereo"},
        bloqueados)


def test_foto_de_buraco_negro_passa_e_lab_cai():
    ch = _ch(N1, visual_queries=["black hole", "gravity"],
             subject="black hole", visual_entities=["black hole", "gravity"])
    boa = {"title": "black hole galaxy center telescope"}
    ruim = {"title": "chemistry laboratory microscope"}
    assert scoring.base_score(boa, ch)["score"] >= scoring.threshold()
    assert media_rules.rejection_reason(
        ruim, media_rules.scene_blocklist(ch))


def test_mito_em_texto_de_ciencia_nao_vira_arte_historica():
    assert S.classify_visual_type(N1) == "literal"


def test_cenas_locais_carregam_vocabulario_em_ingles():
    chs = S.build_local_semantic_scenes(N1, 1).semantic_scenes
    assert chs[0].subject == "black hole"
    assert "black hole" in chs[0].visual_queries


def test_local_planner_preserva_topico_descritivo_em_queries_contextuais():
    from curio.stages.entity import resolve_entity_heuristic
    from curio.stages.scene_enrichment import enrich_scenes
    from curio.stages.search_planning import build_search_plan
    from curio.stages.visual_planning import build_visual_plan

    title = "Buracos negros: sombras e ondas"
    target = resolve_entity_heuristic(title)
    local = S.build_local_semantic_scenes(
        "Um buraco negro se forma e possui horizonte de eventos.", 1)
    enriched = enrich_scenes(
        local.semantic_scenes, topic=title, target=target, source="local",
        planning_mode="deterministic")
    plan = build_visual_plan(enriched.semantic_scenes[0])
    queries = [item.query for item in build_search_plan(plan, "science").queries]

    assert plan.topic == "Buracos negros"
    assert "black hole Buracos negros" in queries
    assert all(query.casefold() != "buracos" for query in queries)


def test_busca_prefere_buraco_negro_a_laboratorio(tmp_path, monkeypatch):
    from tests.test_media_waterfall import _FakeProv, _mock_download
    _mock_download(monkeypatch, tmp_path)
    lab = MediaAsset(provider="pixabay", asset_id="lab",
                     title="chemistry laboratory microscope",
                     download_url="https://cdn.x/lab.jpg",
                     width=1920, height=1280, license="CC BY 4.0")
    buraco = MediaAsset(provider="nasa", asset_id="bh",
                        title="black hole galaxy center",
                        download_url="http://images-assets.nasa.gov/bh.jpg",
                        width=1920, height=1280, license="Domínio público (NASA)")
    prov = _FakeProv("nasa", [lab, buraco])
    ch = _ch(N1, visual_queries=["black hole", "gravity"],
             global_visual_queries=["black hole"],
             subject="black hole", visual_entities=["black hole", "gravity"])
    cfg = SimpleNamespace(cache_dir=str(tmp_path), language="pt-BR")
    scenes, _ = V._search_scene_with_shortcircuit(
        ch, [prov], cfg, 1, RunMetrics("s", "i", "n"), str(tmp_path))
    assert scenes[0]["asset"]["asset_id"] == "bh"
