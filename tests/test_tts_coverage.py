"""Gate anti-corte da narração: stream parcial não vira vídeo curto.

Cobre tts_coverage_ok, _check_edge_result, retry do edge-tts, fallback
p/ espeak e a autocura do cache parcial no pipeline.
"""

import json
import os

import pytest

from curio.stages import tts as tts_stage
from curio.stages import subs as subs_stage
from curio.stages import render as render_stage
from curio.stages import research as research_stage
from curio.stages.tts import (
    TTSError,
    TTSResult,
    _check_edge_result,
    tts_coverage_ok,
)
from curio.audio.artifacts import (TTSCacheManifest, legacy_words_match_text,
                                   tts_input_signature, words_signature)


def _words(n, step=0.4):
    return [{"text": f"w{i}", "start": round(i * step, 3),
             "end": round((i + 1) * step, 3)} for i in range(n)]


def _text(n):
    return " ".join(f"w{i}" for i in range(n))


def test_coverage_ok_caso_real():
    # 358/359: divergência legítima de tokenização passa com folga.
    assert tts_coverage_ok(_words(358), _text(359)) is True


def test_coverage_ok_caso_incidente():
    # 54/359: o incidente real (stream interrompido) é barrado.
    assert tts_coverage_ok(_words(54), _text(359)) is False


def test_coverage_ok_bordas():
    assert tts_coverage_ok([], _text(10)) is False
    assert tts_coverage_ok(None, _text(10)) is False
    assert tts_coverage_ok(_words(5), "") is False
    assert tts_coverage_ok(_words(9), _text(10)) is True  # 90% exato passa
    assert tts_coverage_ok(_words(8), _text(10)) is False


def test_tts_cache_signature_includes_text_and_voice_configuration():
    base = tts_input_signature("Texto inicial", "edge-tts", "pt-BR-AntonioNeural",
                               170, 0.0, "pt-BR")
    assert base != tts_input_signature("Outro texto", "edge-tts",
                                       "pt-BR-AntonioNeural", 170, 0.0,
                                       "pt-BR")
    assert base != tts_input_signature("Texto inicial", "espeak-ng", "pt-br",
                                       170, 0.0, "pt-BR")
    assert base != tts_input_signature("Texto inicial", "edge-tts",
                                       "pt-BR-AntonioNeural", 180, 0.0,
                                       "pt-BR")


def test_legacy_word_boundaries_must_match_text_not_only_word_count():
    assert legacy_words_match_text(_words(3), _text(3))
    assert not legacy_words_match_text(_words(3), "foo bar baz")


def test_legacy_tts_cache_rejects_same_length_script_with_different_words(
        tmp_path):
    from types import SimpleNamespace
    from curio.config import CurioConfig
    from curio.pipeline_audio import _cache_result

    old_text = "red fox runs"
    new_text = "blue car fly"
    assert len(old_text) == len(new_text)
    metadata = {"script_chars": len(old_text), "duration_target": 0.0,
                "tts_provider": "edge-tts",
                "tts_voice": "pt-BR-AntonioNeural", "tts_speed": 170}
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    cfg = CurioConfig()
    paths = SimpleNamespace(metadata_json=str(metadata_path))

    assert _cache_result(None, [
        {"text": word, "start": index, "end": index + 1}
        for index, word in enumerate(old_text.split())
    ], "signature", new_text, paths, cfg) is None


def test_legacy_tts_cache_rejects_missing_producer_settings(tmp_path):
    from types import SimpleNamespace
    from curio.config import CurioConfig
    from curio.pipeline_audio import _cache_result

    text = "red fox runs"
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps({
        "script_chars": len(text), "duration_target": 0.0,
        "tts_provider": "edge-tts", "tts_voice": "pt-BR-AntonioNeural",
    }), encoding="utf-8")
    words = [{"text": word, "start": index, "end": index + 1}
             for index, word in enumerate(text.split())]

    assert _cache_result(None, words, "signature", text,
                         SimpleNamespace(metadata_json=str(metadata_path)),
                         CurioConfig()) is None


def test_tts_manifest_rejects_inconsistent_boundary_provenance():
    manifest = TTSCacheManifest("sig", "edge-tts", "voice", 170, 2.0,
                                True, words_signature(_words(1)))
    assert TTSCacheManifest.from_dict(manifest.to_dict()) == manifest
    invalid = manifest.to_dict()
    invalid["words_signature"] = None
    with pytest.raises(ValueError, match="disagrees"):
        TTSCacheManifest.from_dict(invalid)


def test_check_edge_result_ok():
    words = _words(100)
    _check_edge_result(words, words[-1]["end"] + 0.5, _text(100), "voz")


def test_check_edge_result_parcial_levanta():
    with pytest.raises(TTSError, match="parcial"):
        _check_edge_result(_words(54), 14.8, _text(359), "voz")


def test_check_edge_result_audio_inconsistente_levanta():
    words = _words(100)
    with pytest.raises(TTSError, match="inconsistente"):
        _check_edge_result(words, words[-1]["end"] - 5.0, _text(100), "voz")


def test_synthesize_tenta_edge_3x_antes_do_fallback(monkeypatch):
    calls = []

    def fake_edge(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise TTSError("edge-tts retornou narração parcial (voz='v'): 1/10")
        return TTSResult(path="x.wav", duration=10.0, provider="edge-tts",
                         voice="v", speed=60, words=_words(10))

    monkeypatch.setattr(tts_stage, "_synthesize_edge", fake_edge)
    monkeypatch.setattr(tts_stage.ff, "require_tools", lambda: None)
    monkeypatch.setattr("time.sleep", lambda s: None)
    res = tts_stage.synthesize(_text(10), "x.wav", "edge-tts", "v",
                               170, 0.0, language="pt-BR")
    assert res.provider == "edge-tts"
    assert len(calls) == 3


def test_synthesize_cai_p_espeak_apos_3_parciais(monkeypatch):
    monkeypatch.setattr(
        tts_stage, "_synthesize_edge",
        lambda *a, **k: (_ for _ in ()).throw(
            TTSError("edge-tts retornou narração parcial")))
    monkeypatch.setattr(tts_stage.ff, "require_tools", lambda: None)
    monkeypatch.setattr(tts_stage.shutil, "which",
                        lambda name: "/usr/bin/espeak-ng")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(
        tts_stage, "_synthesize_espeak",
        lambda *a, **k: TTSResult(path="x.wav", duration=60.0,
                                  provider="espeak-ng", voice="pt-br",
                                  speed=170, words=None))
    res = tts_stage.synthesize(_text(100), "x.wav", "edge-tts", "v",
                               170, 0.0, language="pt-BR")
    assert res.provider == "espeak-ng"


def _seed_caches(root, script_words=359, audio_words=54):
    os.makedirs(os.path.join(root, "script"), exist_ok=True)
    os.makedirs(os.path.join(root, "audio"), exist_ok=True)
    os.makedirs(os.path.join(root, "render"), exist_ok=True)
    text = " ".join(f"w{i}" for i in range(script_words))
    with open(os.path.join(root, "script", "script.txt"), "w",
              encoding="utf-8") as fh:
        fh.write(text)
    with open(os.path.join(root, "script", "title.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("Título de teste para o vídeo?")
    chapters = [
        {"id": 1, "narration": " ".join(f"w{i}" for i in range(180)),
         "duration_estimate": 5.0, "visual_queries": [], "start": 0.0,
         "end": 5.0},
        {"id": 2, "narration": " ".join(f"w{i}" for i in range(180, 359)),
         "duration_estimate": 5.0, "visual_queries": [], "start": 5.0,
         "end": 10.0},
    ]
    with open(os.path.join(root, "script", "chapters.json"), "w",
              encoding="utf-8") as fh:
        json.dump(chapters, fh)
    asset = {"local_path": os.path.join(root, "audio", "x.png"),
             "title": "t", "provider": "manual", "author": "",
             "license": "manual", "license_url": "", "source_url": "",
             "download_url": "", "width": 10, "height": 10}
    open(os.path.join(root, "audio", "x.png"), "wb").write(b"\x89PNG")
    media = [{"chapter_id": 1, "asset": asset, "assets": [],
              "reused_from": None},
             {"chapter_id": 2, "asset": asset, "assets": [],
              "reused_from": None}]
    os.makedirs(os.path.join(root, "media"), exist_ok=True)
    with open(os.path.join(root, "media", "media.json"), "w",
              encoding="utf-8") as fh:
        json.dump(media, fh)
    os.makedirs(os.path.join(root, "subtitles"), exist_ok=True)
    open(os.path.join(root, "subtitles", "subs.srt"), "w").write("")
    open(os.path.join(root, "subtitles", "subs.ass"), "w").write("")
    open(os.path.join(root, "audio", "narration.wav"), "wb").write(b"RIFF")
    words = [{"text": f"w{i}", "start": i * 0.16, "end": (i + 1) * 0.16}
             for i in range(audio_words)]
    with open(os.path.join(root, "audio", "words.json"), "w",
              encoding="utf-8") as fh:
        json.dump(words, fh)
    with open(os.path.join(root, "metadata.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"script_chars": len(text), "duration_target": 0.0,
                   "tts_provider": "edge-tts",
                   "tts_voice": "pt-BR-AntonioNeural",
                   "tts_speed": 170}, fh)
    open(os.path.join(root, "render", "final.mp4"), "wb").write(b"ftyp")
    return text


def _fake_sources():
    from curio.stages.entity import TargetEntity
    from curio.stages.research import ResearchResult, ResearchSource
    return ResearchResult(
        TargetEntity(name="Sal", is_entity=False),
        [ResearchSource(title="Sal", url="https://pt.wikipedia.org/wiki/Sal",
                        snippet="O sal é cloreto de sódio.")])


def test_pipeline_recusa_cache_parcial_e_ressintetiza(tmp_path, monkeypatch):
    from curio import pipeline as pipe
    from curio.config import CurioConfig

    out_dir = str(tmp_path / "output")
    slug = "caso-9s"
    text = _seed_caches(os.path.join(out_dir, slug))
    cfg = CurioConfig(audio_enabled=False)
    cfg.out_dir = out_dir
    cfg.metrics_dir = str(tmp_path / "metrics")
    monkeypatch.setattr(research_stage, "research_topic",
                        lambda *a, **k: _fake_sources())

    full_words = [{"text": f"w{i}", "start": i * 0.3, "end": (i + 1) * 0.3}
                  for i in range(359)]
    called = {}

    def fake_synth(*args, **kwargs):
        called["n"] = called.get("n", 0) + 1
        return TTSResult(path="x.wav", duration=108.0, provider="edge-tts",
                         voice="v", speed=200, words=full_words)

    monkeypatch.setattr(tts_stage, "synthesize", fake_synth)
    monkeypatch.setattr("curio.ffmpeg.probe_duration", lambda p: 8.64)
    monkeypatch.setattr(subs_stage, "write_subtitles",
                        lambda *a, **k: 10)
    monkeypatch.setattr(render_stage, "burn_final",
                        lambda *a, **k: {"duration": 108.0,
                                         "backend": "test", "encoder": "test"})
    meta = pipe.run_pipeline("ideia teste", cfg, slug=slug, max_images=1)
    assert called.get("n") == 1  # cache parcial ignorado, sintetizou
    assert meta["audio_duration"] == 108.0
    assert any("parcial em cache" in w for w in meta["warnings"])


def test_pipeline_reusa_cache_integro(tmp_path, monkeypatch):
    from curio import pipeline as pipe
    from curio.config import CurioConfig

    out_dir = str(tmp_path / "output")
    slug = "caso-ok"
    _seed_caches(os.path.join(out_dir, slug), script_words=100,
                 audio_words=100)
    cfg = CurioConfig(audio_enabled=False)
    cfg.out_dir = out_dir
    cfg.metrics_dir = str(tmp_path / "metrics")
    monkeypatch.setattr(research_stage, "research_topic",
                        lambda *a, **k: _fake_sources())

    def boom(*a, **k):
        raise AssertionError("synthesize não deveria ser chamado")

    monkeypatch.setattr(tts_stage, "synthesize", boom)
    monkeypatch.setattr("curio.ffmpeg.probe_duration", lambda p: 30.0)
    monkeypatch.setattr(subs_stage, "write_subtitles",
                        lambda *a, **k: 10)
    monkeypatch.setattr(render_stage, "burn_final",
                        lambda *a, **k: {"duration": 30.0,
                                         "backend": "test", "encoder": "test"})
    meta = pipe.run_pipeline("ideia teste", cfg, slug=slug, max_images=1)
    assert meta["tts_reused"] is True
    assert meta["audio_duration"] == 30.0
    from curio.project_paths import video_paths
    assert os.path.isfile(video_paths(out_dir, slug).tts_manifest_json)
