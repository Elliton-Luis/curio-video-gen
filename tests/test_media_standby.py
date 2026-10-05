"""Standby sem imagens: zero assets não produz vídeo; fotos manuais retomam."""

import json
import os

from curio.project_paths import video_paths
from curio.pipeline_media import (
    MediaStandby,
    count_assets,
    manual_media_scenes,
    manual_media_dir,
)
from curio.media.selection_result import MediaStageResult
from curio.queue import QueueItemStatus, VideoQueue, retry_failed
from curio.stages.scene_projection import Chapter


def _semantic_scenes(n=3):
    return [Chapter(id=i + 1, narration=f"Narração da cena {i + 1}.",
                    duration_estimate=5.0).semantic_scene()
            for i in range(n)]


def test_count_assets_suporta_os_dois_formatos():
    multi = [{"chapter_id": 1, "asset": {"local_path": "/x.jpg"}, "assets": []},
             {"chapter_id": 2, "asset": None, "assets": []}]
    assert count_assets(multi) == 1
    singular = [{"chapter_id": 1, "asset": None},
                {"chapter_id": 2, "asset": {"local_path": "/y.jpg"}}]
    assert count_assets(singular) == 1
    assert count_assets([]) == 0
    assert count_assets([{"chapter_id": 1, "asset": None, "assets": []}]) == 0


def test_manual_sem_fotos_retorna_none(tmp_path):
    paths = video_paths(str(tmp_path), "slug-teste")
    assert manual_media_scenes(_semantic_scenes(), manual_media_dir(paths)) is None


def test_manual_mapeia_fotos_em_ordem_e_reusa(tmp_path):
    paths = video_paths(str(tmp_path), "slug-teste")
    manual = manual_media_dir(paths)
    os.makedirs(manual)
    # PNG mínimo válido (1x1) para o ffprobe não quebrar o teste
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
           b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
           b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd84"
           b"\x00\x00\x00\x00IEND\xaeB`\x82")
    for name in ("02-meio.png", "01-abertura.png"):
        with open(os.path.join(manual, name), "wb") as fh:
            fh.write(png)
    with open(os.path.join(manual, "notas.txt"), "w") as fh:
        fh.write("ignorado")
    scenes = manual_media_scenes(_semantic_scenes(3), manual)
    assert scenes is not None and len(scenes) == 3
    assert count_assets(scenes) == 3
    # ordem alfabética: cena1=abertura, cena2=meio, cena3=abertura (rodízio)
    assert scenes[0]["asset"]["local_path"].endswith("01-abertura.png")
    assert scenes[1]["asset"]["local_path"].endswith("02-meio.png")
    assert scenes[2]["asset"]["local_path"].endswith("01-abertura.png")
    assert scenes[0]["reused_from"] is None
    assert scenes[2]["reused_from"] == 1
    assert all(s["asset"]["provider"] == "manual" for s in scenes)
    decisions = [s["visual_decision"]["selection"] for s in scenes]
    assert [decision["status"] for decision in decisions] == [
        "real", "real", "reused"]
    assert decisions[2]["reuse_reason"] == "manual file already assigned to scene 1"
    assert decisions[2]["reason"] == "user supplied image reused from scene 1"
    typed = MediaStageResult.from_rows(scenes, "manual")
    assert [scene.decision.status for scene in typed.scenes] == [
        "real", "real", "reused"]


def test_manual_media_rejects_chapter_instead_of_reading_semantics_from_it(tmp_path):
    import pytest
    chapter = Chapter(id=1, narration="Cena.", duration_estimate=5)
    with pytest.raises(TypeError, match="SemanticScene"):
        manual_media_scenes([chapter], str(tmp_path / "manual"))


def test_standby_carrega_slug_e_pasta():
    exc = MediaStandby("meu-slug", "/x/manual", 4)
    assert exc.slug == "meu-slug"
    assert exc.manual_dir == "/x/manual"
    assert exc.n_scenes == 4
    assert "STANDBY" in str(exc)


def test_retry_inclui_pausados():
    q = VideoQueue()
    q.add_from_list(["A?", "B?", "C?"])
    q.items[0].status = QueueItemStatus.ERROR
    q.items[1].status = QueueItemStatus.PAUSED
    assert retry_failed(q) == 2
    assert all(i.status == QueueItemStatus.WAITING for i in q.items)


def test_metadata_standby_e_legivel(tmp_path):
    meta = {"slug": "s", "status": "standby-no-media", "narration": "standby",
            "manual_dir": "/m", "n_scenes": 2}
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(meta), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["status"] == "standby-no-media"
