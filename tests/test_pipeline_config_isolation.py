import json

from curio import pipeline
from curio import pipeline_finalize
from curio.audio import composition as audio_composition
from curio.config import CurioConfig


def test_generation_audio_request_does_not_mutate_interface_config(tmp_path,
                                                                   monkeypatch):
    config = CurioConfig(out_dir=str(tmp_path), audio_enabled=False)
    seen = {}

    def fake_run(_idea, run_config, **_kwargs):
        seen["config"] = run_config
        audio_composition.apply_audio_request(run_config, {
            "music": {"mode": "none", "gain_db": -12, "ducking": False},
            "transitions": {"mode": "none"},
        })
        return {"artifacts": {}}

    monkeypatch.setattr(pipeline, "_run_pipeline", fake_run)
    result = pipeline.run_pipeline("A topic", config, slug="config-isolation")

    assert result == {"artifacts": {}}
    assert seen["config"] is not config
    assert seen["config"].audio_enabled is True
    assert seen["config"].music_mode == "none"
    assert config.audio_enabled is False
    assert config.music_mode == "auto"
    assert config.music_gain_db == -3
    assert config.music_ducking is True
    assert config.music_transitions == "auto"


def test_finalize_policy_does_not_mutate_interface_config(tmp_path, monkeypatch):
    root = tmp_path / "history" / "video"
    root.mkdir(parents=True)
    (root / "metadata.json").write_text(json.dumps({}), encoding="utf-8")
    config = CurioConfig(out_dir=str(tmp_path), audio_enabled=True)
    seen = {}

    def fake_finalize(_slug, _audio, run_config, *_args, **_kwargs):
        seen["config"] = run_config
        run_config.audio_enabled = False
        run_config.music_mode = "none"
        return {"status": "finalized"}

    monkeypatch.setattr(pipeline_finalize, "run_finalize", fake_finalize)
    result = pipeline.finalize_project("history/video", "unused.wav", config)

    assert result == {"status": "finalized"}
    assert seen["config"] is not config
    assert config.audio_enabled is True
    assert config.music_mode == "auto"
