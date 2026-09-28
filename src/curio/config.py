"""Configuração centralizada (PRD §18).

Precedência: CLI > variáveis de ambiente > config.toml > padrões.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field


@dataclass
class CurioConfig:
    duration_target: float = 45.0
    out_dir: str = "output"
    tts_provider: str = "espeak-ng"
    tts_voice: str = "pt-br"
    tts_speed: int = 170
    render_backend: str = "auto"  # auto | vaapi | qsv | cpu
    width: int = 1080
    height: int = 1920
    fps: int = 30
    sub_font_size: int = 64
    sub_margin_v: int = 200
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""

    @classmethod
    def load(cls, path: str | None = None) -> "CurioConfig":
        data: dict = {}
        candidates = [p for p in [path, "config.toml"] if p]
        for cand in candidates:
            if os.path.isfile(cand):
                with open(cand, "rb") as fh:
                    data = tomllib.load(fh)
                break
        cfg = cls()
        cfg.duration_target = float(data.get("duration_target", cfg.duration_target))
        cfg.out_dir = str(data.get("out_dir", cfg.out_dir))
        tts = data.get("tts", {}) if isinstance(data.get("tts"), dict) else {}
        cfg.tts_provider = str(tts.get("provider", cfg.tts_provider))
        cfg.tts_voice = str(tts.get("voice", cfg.tts_voice))
        cfg.tts_speed = int(tts.get("speed", cfg.tts_speed))
        rnd = data.get("render", {}) if isinstance(data.get("render"), dict) else {}
        cfg.render_backend = str(rnd.get("backend", cfg.render_backend))
        cfg.width = int(rnd.get("width", cfg.width))
        cfg.height = int(rnd.get("height", cfg.height))
        cfg.fps = int(rnd.get("fps", cfg.fps))
        sub = data.get("subtitles", {}) if isinstance(data.get("subtitles"), dict) else {}
        cfg.sub_font_size = int(sub.get("font_size", cfg.sub_font_size))
        cfg.sub_margin_v = int(sub.get("margin_v", cfg.sub_margin_v))
        llm = data.get("llm", {}) if isinstance(data.get("llm"), dict) else {}
        cfg.llm_base_url = str(llm.get("base_url", ""))
        cfg.llm_model = str(llm.get("model", ""))
        key_env = str(llm.get("api_key_env", "CURIO_LLM_API_KEY"))
        cfg.llm_api_key = os.environ.get(key_env, "")

        # Overrides via ambiente.
        cfg.out_dir = os.environ.get("CURIO_OUT_DIR", cfg.out_dir)
        cfg.tts_provider = os.environ.get("CURIO_TTS", cfg.tts_provider)
        cfg.tts_voice = os.environ.get("CURIO_VOICE", cfg.tts_voice)
        if os.environ.get("CURIO_SPEED"):
            cfg.tts_speed = int(os.environ["CURIO_SPEED"])
        cfg.render_backend = os.environ.get("CURIO_BACKEND", cfg.render_backend)
        if os.environ.get("CURIO_DURATION"):
            cfg.duration_target = float(os.environ["CURIO_DURATION"])
        return cfg

    def as_dict(self) -> dict:
        return {
            "duration_target": self.duration_target,
            "out_dir": self.out_dir,
            "tts_provider": self.tts_provider,
            "tts_voice": self.tts_voice,
            "tts_speed": self.tts_speed,
            "render_backend": self.render_backend,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
        }
