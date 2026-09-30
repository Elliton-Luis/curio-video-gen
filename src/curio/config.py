"""Configuração centralizada (PRD §18).

Precedência: CLI > variáveis de ambiente > config.toml > padrões.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field


def _as_bool(value, default: bool = True) -> bool:
    """Interpreta bool de config/env (true/false/1/0/sim/não)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in (
        "0", "false", "no", "n", "nao", "não", "off")


DURATION_AUTO = 0.0  # Automático/Ilimitado: o conteúdo determina a duração.


def parse_duration(raw) -> float:
    """Duração desejada em segundos; 0.0 = Automático/Ilimitado.

    Aceita número, "auto"/"ilimitado"/"unlimited"/"" ou None (=auto).
    Número precisa estar em 5..600 (fora disso, ValueError — sem clamp
    silencioso: a meta é do usuário, não nossa).
    """
    if raw is None:
        return DURATION_AUTO
    text = str(raw).strip().lower()
    if text in ("", "auto", "automatico", "automático", "ilimitado",
                "unlimited", "none", "0", "0.0"):
        return DURATION_AUTO
    try:
        seconds = float(text.replace(",", "."))
    except ValueError:
        raise ValueError(
            f"duração inválida: {raw!r} — use 'auto', 30, 45, 60, 90, 120, "
            "180 ou segundos (5..600)")
    if not 5 <= seconds <= 600:
        raise ValueError(f"duração fora do intervalo (5..600 s): {raw!r}")
    return seconds


@dataclass
class CurioConfig:
    duration_target: float = DURATION_AUTO  # 0 = Automático/Ilimitado (padrão)
    out_dir: str = "output"
    tts_provider: str = "edge-tts"  # edge-tts (neural, grátis) | espeak-ng (local)
    tts_voice: str = "pt-BR-AntonioNeural"  # masculina PT-BR (edge); espeak: "pt-br"
    tts_speed: int = 170
    render_backend: str = "auto"  # auto | vaapi | qsv | cpu
    width: int = 1080
    height: int = 1920
    fps: int = 30
    sub_font_size: int = 92  # base p/ altura 1920, em pixels reais (ASS PlayRes=vRes)
    sub_margin_v: int = 200
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    nvidia_timeout: int = 15  # timeout estrito para chamadas LLM
    openrouter_model: str = "google/gemini-2.5-flash"  # modelo padrão via OpenRouter
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    gemini_model: str = "gemini-2.5-flash"  # Gemini direto (GEMINI_API_KEY)
    gemini_base_url: str = ("https://generativelanguage.googleapis.com/v1beta/openai")
    groq_model: str = "openai/gpt-oss-120b"  # Groq (GROQ_API_KEY)
    groq_base_url: str = "https://api.groq.com/openai/v1"
    media_providers: str = "pixabay,pexels,wikimedia"  # csv; "none" = só fallback
    cache_dir: str = "cache"
    teleprompter_wpm: int = 150
    whisper_model: str = "base"
    metrics_dir: str = "metrics"
    visual_max_images: int = 3  # fotos por cena no modo roteiro-pronto (1–5)
    visual_overlap: float = 0.9  # sobreposição máxima (s) entre fotos
    visual_sfx: bool = True  # SFX discretos em ~1/3 das inserções
    file_manager: str = "dolphin"  # pasta do teleprompter pós-geração
    audio_recorder: str = "audacity"  # gravador aberto pós-teleprompter
    auto_open: bool = True  # abre apps após teleprompter (só c/ sessão gráfica)
    # Idioma do vídeo: "pt-BR" ou "en-US"
    language: str = "pt-BR"
    # Chaves NVIDIA NÃO vivem aqui: lidas direto do ambiente
    # (NVIDIA_API_KEY / NVIDIA_API_KEYS) via NvidiaCredentials,
    # para nunca vazarem em logs, erros ou metadata.

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
        cfg.duration_target = parse_duration(
            data.get("duration_target", cfg.duration_target))
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
        nvidia = data.get("nvidia", {}) if isinstance(data.get("nvidia"), dict) else {}
        cfg.nvidia_base_url = str(nvidia.get("base_url", cfg.nvidia_base_url))
        cfg.nvidia_model = str(nvidia.get("model", cfg.nvidia_model))
        cfg.nvidia_timeout = int(nvidia.get("timeout", cfg.nvidia_timeout))
        orouter = data.get("openrouter", {}) if isinstance(data.get("openrouter"), dict) else {}
        cfg.openrouter_model = str(orouter.get("model", cfg.openrouter_model))
        cfg.openrouter_base_url = str(orouter.get("base_url", cfg.openrouter_base_url))
        gemini = data.get("gemini", {}) if isinstance(data.get("gemini"), dict) else {}
        cfg.gemini_model = str(gemini.get("model", cfg.gemini_model))
        cfg.gemini_base_url = str(gemini.get("base_url", cfg.gemini_base_url))
        groq = data.get("groq", {}) if isinstance(data.get("groq"), dict) else {}
        cfg.groq_model = str(groq.get("model", cfg.groq_model))
        cfg.groq_base_url = str(groq.get("base_url", cfg.groq_base_url))

        # Overrides via ambiente.
        cfg.out_dir = os.environ.get("CURIO_OUT_DIR", cfg.out_dir)
        cfg.tts_provider = os.environ.get("CURIO_TTS", cfg.tts_provider)
        cfg.tts_voice = os.environ.get("CURIO_VOICE", cfg.tts_voice)
        if os.environ.get("CURIO_SPEED"):
            cfg.tts_speed = int(os.environ["CURIO_SPEED"])
        cfg.render_backend = os.environ.get("CURIO_BACKEND", cfg.render_backend)
        if os.environ.get("CURIO_DURATION") is not None:
            cfg.duration_target = parse_duration(os.environ["CURIO_DURATION"])
        cfg.nvidia_model = os.environ.get("NVIDIA_MODEL", cfg.nvidia_model)
        cfg.nvidia_base_url = os.environ.get("NVIDIA_BASE_URL", cfg.nvidia_base_url)
        if os.environ.get("NVIDIA_TIMEOUT"):
            cfg.nvidia_timeout = int(os.environ["NVIDIA_TIMEOUT"])
        cfg.openrouter_model = os.environ.get("OPENROUTER_MODEL",
                                              cfg.openrouter_model)
        cfg.openrouter_base_url = os.environ.get("OPENROUTER_BASE_URL",
                                                 cfg.openrouter_base_url)
        cfg.gemini_model = os.environ.get("GEMINI_MODEL", cfg.gemini_model)
        cfg.gemini_base_url = os.environ.get("GEMINI_BASE_URL",
                                             cfg.gemini_base_url)
        cfg.groq_model = os.environ.get("GROQ_MODEL", cfg.groq_model)
        cfg.groq_base_url = os.environ.get("GROQ_BASE_URL", cfg.groq_base_url)
        cfg.media_providers = os.environ.get("CURIO_MEDIA_PROVIDERS",
                                             cfg.media_providers)
        cfg.cache_dir = os.environ.get("CURIO_CACHE_DIR", cfg.cache_dir)
        if os.environ.get("CURIO_WPM"):
            cfg.teleprompter_wpm = int(os.environ["CURIO_WPM"])
        cfg.whisper_model = os.environ.get("CURIO_WHISPER_MODEL",
                                           cfg.whisper_model)
        cfg.metrics_dir = os.environ.get("CURIO_METRICS_DIR",
                                           cfg.metrics_dir)
        vis = data.get("visual", {}) if isinstance(data.get("visual"), dict) else {}
        cfg.visual_max_images = int(vis.get("max_images", cfg.visual_max_images))
        cfg.visual_overlap = float(vis.get("overlap", cfg.visual_overlap))
        if os.environ.get("CURIO_VISUAL_MAX_IMAGES"):
            cfg.visual_max_images = int(os.environ["CURIO_VISUAL_MAX_IMAGES"])
        if os.environ.get("CURIO_VISUAL_OVERLAP"):
            cfg.visual_overlap = float(os.environ["CURIO_VISUAL_OVERLAP"])
        cfg.visual_max_images = max(1, min(5, cfg.visual_max_images))
        cfg.visual_sfx = _as_bool(vis.get("sfx", cfg.visual_sfx),
                                  cfg.visual_sfx)
        if os.environ.get("CURIO_VISUAL_SFX") is not None:
            cfg.visual_sfx = _as_bool(os.environ["CURIO_VISUAL_SFX"], True)
        cfg.file_manager = os.environ.get("CURIO_FILE_MANAGER",
                                          cfg.file_manager)
        cfg.audio_recorder = os.environ.get("CURIO_AUDIO_RECORDER",
                                            cfg.audio_recorder)
        if os.environ.get("CURIO_AUTO_OPEN") is not None:
            cfg.auto_open = os.environ["CURIO_AUTO_OPEN"].strip().lower() not in (
                "0", "false", "no", "n")
        cfg.language = os.environ.get("CURIO_LANGUAGE", cfg.language)
        lang = data.get("language", cfg.language)
        if lang:
            cfg.language = str(lang)
        return cfg

    def llm_overrides(self) -> dict:
        """Overrides (model, base_url) p/ fallbacks do chain (gemini, groq).

        Valores já com precedência CLI > env > config.toml > padrão.
        """
        return {
            "gemini": (self.gemini_model, self.gemini_base_url),
            "groq": (self.groq_model, self.groq_base_url),
        }

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
