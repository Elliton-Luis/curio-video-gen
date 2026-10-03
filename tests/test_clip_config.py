"""CLIP stays opt-in and settings load without ML dependencies."""

from curio.config import CurioConfig
from curio.stages import scoring


def test_clip_config_defaults_off_and_cpu_requires_explicit_permission(monkeypatch):
    for key in ("CURIO_CLIP_ENABLED", "CURIO_CLIP_DEVICE", "CURIO_CLIP_ALLOW_CPU"):
        monkeypatch.delenv(key, raising=False)
    cfg = CurioConfig.load(None)
    assert cfg.visual_clip_enabled is False
    assert cfg.visual_clip_device == "auto"
    assert cfg.visual_clip_allow_cpu is False
    assert scoring.clip_enabled(cfg) is False
    monkeypatch.setattr(scoring, "clip_device", lambda _cfg=None: "cpu")
    assert scoring.clip_cpu_allowed(cfg) is False


def test_clip_toml_settings_enable_device_and_cpu_opt_in(tmp_path, monkeypatch):
    for key in ("CURIO_CLIP_ENABLED", "CURIO_CLIP_DEVICE", "CURIO_CLIP_ALLOW_CPU"):
        monkeypatch.delenv(key, raising=False)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[visual]\nclip_enabled = true\nclip_device = "cpu"\n'
        'clip_allow_cpu = false\n', encoding="utf-8")
    cfg = CurioConfig.load(str(config_path))
    assert scoring.clip_enabled(cfg) is True
    assert scoring.clip_device(cfg) == "cpu"
    assert scoring.clip_cpu_allowed(cfg) is True


def test_clip_environment_overrides_toml(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[visual]\nclip_enabled = false\nclip_device = "auto"\n',
        encoding="utf-8")
    monkeypatch.setenv("CURIO_CLIP_ENABLED", "1")
    monkeypatch.setenv("CURIO_CLIP_DEVICE", "xpu")
    cfg = CurioConfig.load(str(config_path))
    assert scoring.clip_enabled(cfg) is True
    assert scoring.clip_device(cfg) == "xpu"
