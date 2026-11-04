from types import SimpleNamespace

import pytest

from curio import pipeline_audio
from curio.stages.scene_contract import SemanticScene, TimelineSpan
from curio.stages.tts import TTSResult
from curio.stage_timing import StageTimings


@pytest.mark.parametrize("provider", ["espeak-ng", "tts.ai"])
def test_audio_stage_returns_its_timings_and_warnings(tmp_path, monkeypatch, provider):
    paths = SimpleNamespace(
        tts_manifest_json=str(tmp_path / "tts-manifest.json"),
        narration_wav=str(tmp_path / "narration.wav"),
        words_json=str(tmp_path / "words.json"),
        timeline_json=str(tmp_path / "timeline.json"),
        metadata_json=str(tmp_path / "metadata.json"),
        subs_ass=str(tmp_path / "subtitles.ass"),
        subs_srt=str(tmp_path / "subtitles.srt"),
    )

    calls = {"tts": 0, "transcribe": 0}
    captured_words = []
    words = [{"text": token, "start": index, "end": index + .5}
             for index, token in enumerate("Cena de teste.".split())]

    def synthesize(_text, path, provider, voice, speed, _duration, **_kwargs):
        calls["tts"] += 1
        with open(path, "wb") as stream:
            stream.write(b"audio")
        return TTSResult(path, 4.0, provider, voice, speed, None)

    def write_subtitles(*_args, **kwargs):
        captured_words.append(kwargs["words"])
        with open(paths.subs_ass, "w", encoding="utf-8") as stream:
            stream.write("subtitle")
        return 1

    def transcribe(*_args, **_kwargs):
        calls["transcribe"] += 1
        return words

    monkeypatch.setattr(pipeline_audio.tts_stage, "synthesize", synthesize)
    monkeypatch.setattr(pipeline_audio.subs_stage, "write_subtitles",
                        write_subtitles)
    monkeypatch.setattr(pipeline_audio.transcribe_stage, "transcribe", transcribe)
    monkeypatch.setattr(pipeline_audio.ff, "probe_duration", lambda _path: 4.0)
    def failed_alignment(*_args):
        raise ValueError("bad word alignment")

    monkeypatch.setattr(pipeline_audio, "align_word_boundaries", failed_alignment)
    monkeypatch.setattr(pipeline_audio, "proportional_spans",
                        lambda _scenes, _spans, _duration, _cursor:
                        (TimelineSpan(1, 4, 0, 4),))
    persisted = {}
    cfg = SimpleNamespace(tts_provider=provider, tts_voice="pt-br", whisper_model="base",
                          tts_speed=170, tts_preview=False, duration_target=0, language="pt-BR",
                          width=1080, height=1920, sub_font_size=80,
                          sub_margin_v=120, cache_dir=str(tmp_path))
    result = pipeline_audio.run_audio_stages(
        "Cena de teste.", (SemanticScene(1, "Cena de teste."),),
        (TimelineSpan(1, 4),), paths, cfg, True, None,
        lambda *_args, **_kwargs: None,
        lambda path, value: persisted.update({path: value}),
    )

    assert result.timeline_spans == (TimelineSpan(1, 4, 0, 4),)
    assert result.stage_times.keys() == {"tts", "subs"}
    assert result.timed_source == "proporcional"
    assert result.warnings == ("timeline proporcional (bad word alignment)",)
    assert list(persisted.values())[0][0]["id"] == 1
    assert captured_words == [words if provider == "tts.ai" else None]
    if provider == "tts.ai":
        cached = pipeline_audio.run_audio_stages(
            "Cena de teste.", (SemanticScene(1, "Cena de teste."),),
            (TimelineSpan(1, 4),), paths, cfg, False, None,
            lambda *_args, **_kwargs: None,
            lambda path, value: persisted.update({path: value}))
        assert calls == {"tts": 1, "transcribe": 1}
        assert cached.words == words
        assert captured_words == [words, words]
    with pytest.raises(AttributeError):
        result.audio_duration = 3


def test_audio_stage_result_rejects_invalid_timing_contract():
    with pytest.raises(ValueError, match="timing source"):
        pipeline_audio.AudioStageResult(
            timeline_spans=(TimelineSpan(1, 1),), words=None,
            audio_duration=1, tts_info={"provider": "test"},
            timed_source="unknown", cue_count=0, subtitles_changed=False,
            warnings=(), stage_times=StageTimings())


def test_audio_stage_result_rejects_untyped_stage_times():
    with pytest.raises(TypeError, match="requires StageTimings"):
        pipeline_audio.AudioStageResult(
            timeline_spans=(TimelineSpan(1, 1),), words=None,
            audio_duration=1, tts_info={"provider": "test"},
            timed_source="wordboundary", cue_count=0, subtitles_changed=False,
            warnings=(), stage_times={"tts": -1})
