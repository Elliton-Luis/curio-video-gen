from curio.pipeline_media_sources import record_selected_media
from curio.media.selection_result import MediaStageResult
from curio.stages.scene_projection import Chapter
from tests.media_test_support import with_selection


class _Registry:
    def __init__(self):
        self.media = []

    def add_media(self, **record):
        self.media.append(record)


def test_selected_asset_provenance_records_credit_and_missing_author_warning():
    scene = Chapter(id=1, narration="Mohács", duration_estimate=4,
                    subject="Battle of Mohács").semantic_scene()
    asset = {"provider": "wikimedia", "asset_id": "mohacs-1",
             "title": "Battle of Mohács", "license": "CC BY 4.0",
             "license_url": "https://creativecommons.org/licenses/by/4.0/",
             "source_url": "https://commons.wikimedia.org/item",
             "local_path": "/tmp/mohacs.jpg", "author": ""}
    registry = _Registry()

    selections = MediaStageResult.from_rows(
        [with_selection({"chapter_id": 1,
          "asset": asset,
          "assets": [{"asset": asset, "query": "Battle of Mohács"}]})],
        "provider").scenes
    result = record_selected_media(
        [scene], selections,
        registry)

    assert registry.media[0]["rights_status"] == "clear"
    assert registry.media[0]["title"] == (
        "cena 1 · Battle of Mohács [wikimedia_mohacs-1]")
    assert registry.media[0]["query"] == "Battle of Mohács"
    assert len(result.credits) == 1
    assert "autor não informado" in result.credits[0]
    assert len(result.rights_notes) == 1
    assert "não informou o autor" in result.rights_notes[0]


def test_unknown_license_is_registered_with_explicit_verification_note():
    scene = Chapter(id=1, narration="Cena", duration_estimate=4).semantic_scene()
    asset = {"provider": "openverse", "asset_id": "unknown-1",
             "title": "Historical object", "license": "", "source_url": "https://example.org",
             "local_path": "/tmp/object.jpg", "author": "Artist"}
    registry = _Registry()

    selections = MediaStageResult.from_rows(
        [with_selection({"chapter_id": 1,
          "asset": asset,
          "assets": [{"asset": asset, "query": "historical object"}]})],
        "provider").scenes
    result = record_selected_media(
        [scene], selections,
        registry)

    assert registry.media[0]["rights_status"] == "verify"
    assert not result.credits
    assert len(result.rights_notes) == 1
    assert "licença a conferir" in result.rights_notes[0]
