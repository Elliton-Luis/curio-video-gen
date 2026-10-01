"""Persistência, licenciamento, seleção e política de atualização do áudio."""

import json
from pathlib import Path

import pytest

from curio.audio.library import (
    AudioLibrary, AudioLibraryError, FreesoundAudioSource, _license_kind,
    audio_seed,
)
from curio.audio.selection import resolve_audio
from curio.config import CurioConfig


class FakeSource:
    def __init__(self, results):
        self.results = results
        self.queries = []
        self.downloads = []

    def search(self, query, limit=30):
        self.queries.append((query, limit))
        return self.results

    def download_preview(self, url, path):
        self.downloads.append(url)
        Path(path).write_bytes(url.encode("utf-8"))


def _item(idx, license="Attribution", duration=80):
    return {
        "id": idx, "name": f"Track {idx}", "username": "author",
        "url": f"https://freesound.org/people/author/sounds/{idx}/",
        "license": license, "duration": duration,
        "previews": {"preview-hq-mp3":
                     f"https://cdn.freesound.org/previews/{idx}.mp3"},
    }


def _register(library, tmp_path, monkeypatch, name, use_count=0, category=None):
    path = tmp_path / f"{name}.mp3"
    path.write_bytes(name.encode())
    monkeypatch.setattr("curio.audio.library.ff.probe_duration", lambda _p: 80.0)
    asset = library.register("music" if category is None else "sfx", "people", {
        "asset_id": name, "source": "freesound", "title": name,
        "author": "A", "license": "CC BY", "license_url": "https://creativecommons.org/licenses/by/3.0/",
        "source_url": f"https://freesound.org/sounds/{name}/",
        "downloaded_path": str(path), "mood": ["contemplative"],
    }, category=category, max_count=10, min_duration=1)
    meta_path = Path(asset["path"]).with_suffix(".json")
    data = json.loads(meta_path.read_text())
    data["use_count"] = use_count
    meta_path.write_text(json.dumps(data), encoding="utf-8")
    return asset


def test_library_creates_genre_dirs_and_reads_sidecar(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "assets" / "library")
    asset = _register(library, tmp_path, monkeypatch, "id1")
    assert (tmp_path / "assets/library/music/people").is_dir()
    items = library.assets("music", "people")
    assert items[0]["title"] == "id1"
    assert items[0]["source"] == "freesound"
    assert items[0]["license"] == "CC BY"
    assert items[0]["path"] == asset["path"]


@pytest.mark.parametrize(("value", "accepted"), [
    ("Attribution", "CC BY"),
    ("Creative Commons 0", "CC0"),
    ("https://creativecommons.org/licenses/by/4.0/", "CC BY"),
    ("Attribution NonCommercial", None),
    ("https://creativecommons.org/licenses/by-nd/4.0/", None),
    ("https://creativecommons.org/licenses/by-sa/4.0/", None),
    ("free download", None),
    ("", None),
])
def test_only_cc0_and_cc_by_are_accepted(value, accepted):
    assert _license_kind(value) == accepted


def test_library_limit_and_duplicate_id_prevent_registration(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    first = _register(library, tmp_path, monkeypatch, "same")
    dup_path = tmp_path / "duplicate.mp3"
    dup_path.write_bytes(b"different")
    assert library.register("music", "people", {
        "asset_id": "same", "source": "freesound", "downloaded_path": str(dup_path)
    }, max_count=10) is None
    second_path = tmp_path / "other.mp3"
    second_path.write_bytes(b"other")
    assert library.register("music", "people", {
        "asset_id": "other", "source": "freesound", "downloaded_path": str(second_path)
    }, max_count=1) is None
    assert library.count("music", "people") == 1
    assert Path(first["path"]).is_file()


def test_library_deduplicates_identical_file_content(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    first = _register(library, tmp_path, monkeypatch, "first")
    duplicate = tmp_path / "duplicate-content.mp3"
    duplicate.write_bytes(Path(first["path"]).read_bytes())
    monkeypatch.setattr("curio.audio.library.ff.probe_duration", lambda _p: 80.0)
    result = library.register("music", "people", {
        "asset_id": "different-source-id", "source": "freesound",
        "downloaded_path": str(duplicate),
    }, max_count=10, min_duration=1)
    assert result is None
    assert library.count("music", "people") == 1


def test_update_does_not_search_or_need_key_when_target_is_met(tmp_path, monkeypatch):
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    library = AudioLibrary(tmp_path / "lib")
    for i in range(3):
        _register(library, tmp_path, monkeypatch, f"have{i}")
    report = library.update("music", "people", target=3, max_count=10)
    assert report["before"] == report["after"] == 3
    assert report["added"] == 0


def test_explicit_update_requires_api_key_without_failing_generation(tmp_path, monkeypatch):
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    library = AudioLibrary(tmp_path / "lib")
    with pytest.raises(AudioLibraryError, match="FREESOUND_API_KEY"):
        library.update("music", "people", target=3, max_count=10)


def test_freesound_uses_official_api_token_header_not_url(monkeypatch):
    source = FreesoundAudioSource(api_key="not-a-real-secret")
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"results": []}'

    def fake_open(req, timeout):
        requests.append((req, timeout))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    assert source.search("contemplative instrumental", 4) == []
    req, timeout = requests[0]
    assert req.full_url.startswith("https://freesound.org/apiv2/search/")
    assert "token=" not in req.full_url
    assert req.get_header("Authorization") == "Token not-a-real-secret"
    assert timeout > 0


def test_download_rejects_external_preview_url(tmp_path):
    source = FreesoundAudioSource(api_key="placeholder")
    with pytest.raises(AudioLibraryError, match="não pertence ao Freesound"):
        source.download_preview("https://example.com/audio.mp3", tmp_path / "x.mp3")


def test_update_downloads_only_needed_licensed_files(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    _register(library, tmp_path, monkeypatch, "have0")
    _register(library, tmp_path, monkeypatch, "have1")
    source = FakeSource([
        _item(10, "Attribution NonCommercial"),
        _item(11, "Attribution"),
        _item(12, "Creative Commons 0"),
    ])
    monkeypatch.setattr("curio.audio.library.ff.probe_duration", lambda _p: 80.0)
    report = library.update("music", "people", target=4, max_count=10,
                            source=source)
    assert report["added"] == 2
    assert report["rejected_license"] == 1
    assert len(source.downloads) == 2
    assert report["after"] == 4
    metadata = library.assets("music", "people")
    assert all(a["source_url"].startswith("https://freesound.org/") for a in metadata)
    assert all(a["downloaded_at"] and a["genres"] == ["people"] for a in metadata)


def test_update_stops_at_target_and_deduplicates_source_id(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    _register(library, tmp_path, monkeypatch, "dup-id")
    source = FakeSource([_item("dup-id"), _item("new-id"), _item("extra")])
    monkeypatch.setattr("curio.audio.library.ff.probe_duration", lambda _p: 80.0)
    report = library.update("music", "people", target=2, max_count=10,
                            source=source)
    assert report["added"] == 1
    assert report["duplicates"] == 1
    assert len(source.downloads) == 1
    assert report["after"] == 2


def test_invalid_duration_is_rejected_and_temp_file_removed(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    source = FakeSource([_item(1, duration=4)])
    monkeypatch.setattr("curio.audio.library.ff.probe_duration", lambda _p: 4.0)
    report = library.update("music", "people", target=1, max_count=5,
                            source=source)
    assert report["added"] == 0
    assert "duração fora dos limites" in report["errors"][0]
    assert library.count("music", "people") == 0


def test_selection_is_stable_for_same_seed_and_prefers_least_used(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    _register(library, tmp_path, monkeypatch, "used", use_count=4)
    _register(library, tmp_path, monkeypatch, "unused", use_count=0)
    first = library.select("music", "people", "project-1")
    again = library.select("music", "people", "project-1")
    assert first["source_asset_id"] == again["source_asset_id"] == "unused"
    library.select("music", "people", "project-1", mark_used=True)
    assert library.select("music", "people", "another-project")["use_count"] == 1


def test_audio_seed_is_stable_and_tracks_script_identity():
    assert audio_seed("p", "title", "script") == audio_seed("p", "title", "script")
    assert audio_seed("p", "title", "script") != audio_seed("p", "title", "changed")


def test_auto_uses_local_track_and_none_never_selects(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    _register(library, tmp_path, monkeypatch, "track")
    cfg = CurioConfig()
    cfg.audio_library_dir = str(tmp_path / "lib")
    cfg.music_mode = "auto"
    cfg.audio_enabled = True
    cfg.music_auto_fill = False
    plan = resolve_audio(cfg, "people", "stable", "title", "script", [])
    assert plan["music_asset"]["source_asset_id"] == "track"
    cfg.music_mode = "none"
    none = resolve_audio(cfg, "people", "stable", "title", "script", [])
    assert none["music_asset"] is None
    assert none["metadata"]["music"]["mode"] == "none"


def test_audio_is_enabled_by_default_and_can_be_disabled(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    _register(library, tmp_path, monkeypatch, "local")
    cfg = CurioConfig()
    cfg.audio_library_dir = str(tmp_path / "lib")
    cfg.music_auto_fill = False
    plan = resolve_audio(cfg, "people", "p", "title", "script", [])
    assert cfg.audio_enabled is True
    assert plan["music_asset"] is not None
    assert plan["metadata"]["music"]["mode"] == "auto"
    assert plan["metadata"]["transitions"]["mode"] == "auto"
    assert plan["metadata"]["credits"]
    cfg.audio_enabled = False
    plan = resolve_audio(cfg, "people", "p", "title", "script", [])
    assert plan["metadata"]["music"]["mode"] == "none"
    assert plan["metadata"]["transitions"]["mode"] == "none"


def test_empty_library_does_not_download_during_render(tmp_path, monkeypatch):
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    cfg = CurioConfig()
    cfg.audio_library_dir = str(tmp_path / "empty")
    cfg.audio_enabled = True
    cfg.music_auto_fill = False
    plan = resolve_audio(cfg, "people", "project", "title", "script", [])
    assert plan["music_asset"] is None
    assert plan["metadata"]["music"]["track"] is None
    assert plan["warnings"]


def test_new_sfx_events_are_not_hidden_by_cached_empty_selection(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    _register(library, tmp_path, monkeypatch, "music")
    _register(library, tmp_path, monkeypatch, "paper", category="paper")
    cfg = CurioConfig(audio_library_dir=str(tmp_path / "lib"),
                      music_auto_fill=False, sfx_auto_fill=False)
    previous = resolve_audio(cfg, "people", "p", "title", "script", [])
    assert previous["metadata"]["sfx"]["mode"] == "none"
    plan = resolve_audio(cfg, "people", "p", "title", "script",
                         [{"kind": "swish", "at": 1.0}],
                         previous=previous["metadata"])
    assert plan["metadata"]["sfx"]["mode"] == "library"
    assert plan["metadata"]["sfx"]["assets"]


def test_autofill_failure_falls_back_to_video_without_music(tmp_path, monkeypatch):
    cfg = CurioConfig()
    cfg.audio_enabled = True
    cfg.audio_library_dir = str(tmp_path / "empty")
    cfg.music_auto_fill = True
    monkeypatch.setattr(
        "curio.audio.selection.AudioLibrary.update",
        lambda *_a, **_kw: (_ for _ in ()).throw(AudioLibraryError("source offline")))
    plan = resolve_audio(cfg, "people", "p", "title", "script", [])
    assert plan["music_asset"] is None
    assert any("source offline" in warning for warning in plan["warnings"])


def test_invalid_manual_audio_is_non_fatal(tmp_path, monkeypatch):
    path = tmp_path / "not-audio.mp3"
    path.write_bytes(b"invalid")
    monkeypatch.setattr("curio.audio.selection.ff.probe_duration",
                        lambda _path: (_ for _ in ()).throw(RuntimeError("bad stream")))
    cfg = CurioConfig()
    cfg.audio_enabled = True
    cfg.music_mode = "manual"
    cfg.music_file = str(path)
    plan = resolve_audio(cfg, "people", "p", "title", "script", [])
    assert plan["music_asset"] is None
    assert any("áudio inválido" in warning for warning in plan["warnings"])


def test_opt_in_autofill_only_checks_below_minimum(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    _register(library, tmp_path, monkeypatch, "one")
    cfg = CurioConfig()
    cfg.audio_library_dir = str(tmp_path / "lib")
    cfg.audio_enabled = True
    cfg.music_auto_fill = True
    cfg.music_min_per_genre = 1
    updates = []
    monkeypatch.setattr("curio.audio.selection.AudioLibrary.update",
                        lambda self, *a, **kw: updates.append((a, kw)) or {})
    resolve_audio(cfg, "people", "project", "title", "script", [])
    assert updates == []
    cfg.music_min_per_genre = 2
    resolve_audio(cfg, "people", "another", "title", "script", [])
    assert len(updates) == 1


def test_second_render_uses_sufficient_library_without_download(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    _register(library, tmp_path, monkeypatch, "local")
    cfg = CurioConfig()
    cfg.audio_library_dir = str(tmp_path / "lib")
    cfg.audio_enabled = True
    cfg.music_auto_fill = True
    cfg.music_min_per_genre = 1
    monkeypatch.setattr(
        "curio.audio.selection.AudioLibrary.update",
        lambda *_a, **_kw: pytest.fail("não deveria atualizar biblioteca suficiente"))
    first = resolve_audio(cfg, "people", "project-one", "one", "script", [])
    second = resolve_audio(cfg, "people", "project-two", "two", "script", [])
    assert first["music_asset"] and second["music_asset"]


def test_project_rerun_keeps_previous_track_even_after_use_count_changes(
        tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    _register(library, tmp_path, monkeypatch, "a", use_count=0)
    _register(library, tmp_path, monkeypatch, "b", use_count=0)
    cfg = CurioConfig()
    cfg.audio_library_dir = str(tmp_path / "lib")
    cfg.audio_enabled = True
    cfg.music_auto_fill = False
    first = resolve_audio(cfg, "people", "stable-project", "title", "script", [])
    chosen = first["music_asset"]["asset_id"]
    library.select("music", "people", "stable-project", mark_used=True)
    second = resolve_audio(cfg, "people", "stable-project", "title", "script", [],
                           previous=first["metadata"])
    assert second["music_asset"]["asset_id"] == chosen


def test_render_identity_changes_with_genre_gain_and_ducking(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    _register(library, tmp_path, monkeypatch, "track")
    cfg = CurioConfig()
    cfg.audio_library_dir = str(tmp_path / "lib")
    cfg.audio_enabled = True
    cfg.music_auto_fill = False
    base = resolve_audio(cfg, "people", "p", "title", "script", [])
    cfg.music_gain_db = -20
    gain = resolve_audio(cfg, "people", "p", "title", "script", [])
    cfg.music_gain_db = -30
    cfg.music_ducking = False
    no_duck = resolve_audio(cfg, "people", "p", "title", "script", [])
    other_genre = resolve_audio(cfg, "science", "p", "title", "script", [])
    signatures = {base["metadata"]["signature"], gain["metadata"]["signature"],
                  no_duck["metadata"]["signature"],
                  other_genre["metadata"]["signature"]}
    assert len(signatures) == 4


def test_sfx_library_asset_is_selected_for_planned_event(tmp_path, monkeypatch):
    library = AudioLibrary(tmp_path / "lib")
    _register(library, tmp_path, monkeypatch, "paper", category="paper")
    cfg = CurioConfig()
    cfg.audio_library_dir = str(tmp_path / "lib")
    cfg.audio_enabled = True
    cfg.sfx_auto_fill = False
    events = [{"kind": "swish", "at": 1.0, "gain_db": -30}]
    plan = resolve_audio(cfg, "people", "project", "title", "script", events)
    assert events[0]["path"].endswith("paper.mp3")
    assert events[0]["category"] == "paper"
    assert plan["metadata"]["sfx"]["mode"] == "library"
    assert plan["metadata"]["sfx"]["assets"][0]["license"] == "CC BY"


def test_config_loads_audio_limits_modes_and_gain(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('''
[audio]
library_dir = "library-data"
transitions = "none"
[music]
mode = "manual"
file = "theme.mp3"
gain_db = -25
auto_fill = true
[music.library]
min_per_genre = 8
max_per_genre = 4
[sfx]
auto_fill = true
[sfx.library]
min_per_category = 8
max_per_category = 4
''', encoding="utf-8")
    cfg = CurioConfig.load(str(path))
    assert cfg.audio_library_dir == "library-data"
    assert cfg.music_mode == "manual" and cfg.music_file == "theme.mp3"
    assert cfg.music_gain_db == -25 and cfg.music_auto_fill is True
    assert (cfg.music_min_per_genre, cfg.music_target_per_genre,
            cfg.music_max_per_genre) == (4, 4, 4)
    assert (cfg.sfx_min_per_category, cfg.sfx_target_per_category,
            cfg.sfx_max_per_category) == (4, 4, 4)
