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

# Estilos de entrada válidos para as inserções esparsas. Mesmos nomes de
# `stages.visual.ENTRY_STYLES` (+ o legado "fade_scale"), declarados aqui
# para a config validar sem importar o pacote de estágios (evita ciclo).
ALLOWED_INSERT_STYLES = ("drop_in", "slide_left", "slide_right", "fade",
                         "scale_in", "tilt_in", "fade_scale")


def normalize_language(raw) -> str:
    """Normaliza idioma do vídeo: 'pt-BR' (padrão) ou 'en-US'."""
    text = str(raw or "").strip().lower().replace("_", "-")
    if text in ("en", "en-us", "english", "inglês", "ingles"):
        return "en-US"
    return "pt-BR"


def is_english(language: str) -> bool:
    return normalize_language(language) == "en-US"


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
    render_backend: str = "arc"  # arc (Intel B580 primeiro) | auto | vaapi | qsv | cpu
    width: int = 1080
    height: int = 1920
    fps: int = 30
    sub_font_size: int = 92  # base p/ altura 1920, em pixels reais (ASS PlayRes=vRes)
    sub_margin_v: int = 200
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.3-70b-instruct"
    # Espera de RESPOSTA/processamento por chamada LLM (s): um 550B no NIM
    # não responde em 15 s. Separado da espera de CONEXÃO (handshake),
    # que tem teto próprio e curto (ver nvidia_connect_timeout).
    nvidia_timeout: int = 60
    # Teto do mesmo timeout (resposta/processamento). Configurável para
    # que um modelo grande e lento tenha orçamento; 120 é o padrão.
    # Ver nvidia.call_timeout_max.
    nvidia_timeout_max: int = 120
    # Espera de CONEXÃO/handshake TLS por chamada LLM (s): se o host não
    # atende aqui, é rede ou endpoint — não modelo lento. Curto de
    # propósito; não consome o orçamento de geração.
    nvidia_connect_timeout: int = 10
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    gemini_model: str = "gemini-2.5-flash"  # Gemini direto (GEMINI_API_KEY)
    gemini_base_url: str = ("https://generativelanguage.googleapis.com/v1beta/openai")
    groq_model: str = "openai/gpt-oss-20b"  # Groq (GROQ_API_KEY)
    groq_base_url: str = "https://api.groq.com/openai/v1"
    mistral_model: str = "mistral-small-latest"
    mistral_base_url: str = "https://api.mistral.ai/v1"
    media_providers: str = "pixabay,unsplash,pexels,nasa,wikimedia"  # csv; "none" = só fallback
    cache_dir: str = "cache"
    queues_dir: str = "queues"  # pasta padrão das filas de ideias
    teleprompter_wpm: int = 150
    whisper_model: str = "base"
    metrics_dir: str = "metrics"
    research_max_sources: int = 3  # fontes web exigidas p/ grounding (≥1)
    research_timeout: int = 20  # teto por chamada da Wikipedia (s)
    visual_max_images: int = 3  # fotos por cena no modo roteiro-pronto (1–5)
    visual_overlap: float = 0.9  # sobreposição máxima (s) entre fotos
    visual_sfx: bool = True  # SFX discretos em ~1/3 das inserções
    # Inserções esparsas: fotos COMPLEMENTARES que caem por cima da imagem
    # de fundo, no total do vídeo (não por cena). 1–2 é o ponto ideal: mais
    # que isso vira slideshow. 0 = nunca insere (só a foto de fundo por cena).
    visual_insertions: int = 2
    visual_insert_style: str = "drop_in"  # entrada estilo "cai do álbum"
    visual_insert_gain_db: int = -24  # som da inserção: audível, sem brigar
    # Música local por gênero, com transições e SFX habilitados por padrão.
    audio_library_dir: str = "assets/library"
    audio_enabled: bool = True
    music_mode: str = "auto"  # auto | none | manual
    music_file: str = ""
    music_auto_fill: bool = True
    music_min_per_genre: int = 3
    music_target_per_genre: int = 6
    music_max_per_genre: int = 10
    music_gain_db: int = -18
    music_ducking: bool = True
    music_transitions: str = "auto"  # auto | none
    sfx_library_enabled: bool = True
    sfx_auto_fill: bool = True
    sfx_min_per_category: int = 2
    sfx_target_per_category: int = 5
    sfx_max_per_category: int = 8
    file_manager: str = "dolphin"  # pasta do teleprompter pós-geração
    audio_recorder: str = "audacity"  # gravador aberto pós-teleprompter
    auto_open: bool = True  # abre apps após teleprompter (só c/ sessão gráfica)
    # Idioma do vídeo: "pt-BR" ou "en-US"
    language: str = "pt-BR"
    # Gênero editorial (ver stages/editorial.py). VAZIO = nenhum gênero
    # escolhido, e aí o pipeline se comporta exatamente como antes do
    # recurso. Aceita as chaves de `editorial.GENRES`.
    genre: str = ""
    # Tipografia por gênero: `{"people": {"primary": "Minion Pro", ...}}`.
    # Vazio = as famílias que cada perfil pede, com o fallback automático
    # de `stages/typography.py`. Ver `[typography.<gênero>]` no
    # config.example.toml.
    typography: dict = field(default_factory=dict)
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
        cfg.nvidia_timeout_max = int(
            nvidia.get("timeout_max", cfg.nvidia_timeout_max))
        try:
            cfg.nvidia_connect_timeout = int(
                nvidia.get("connect_timeout", cfg.nvidia_connect_timeout))
            if cfg.nvidia_connect_timeout <= 0:
                cfg.nvidia_connect_timeout = 10
        except (TypeError, ValueError):
            cfg.nvidia_connect_timeout = 10
        orouter = data.get("openrouter", {}) if isinstance(data.get("openrouter"), dict) else {}
        cfg.openrouter_model = str(orouter.get("model", cfg.openrouter_model))
        cfg.openrouter_base_url = str(orouter.get("base_url", cfg.openrouter_base_url))
        gemini = data.get("gemini", {}) if isinstance(data.get("gemini"), dict) else {}
        cfg.gemini_model = str(gemini.get("model", cfg.gemini_model))
        cfg.gemini_base_url = str(gemini.get("base_url", cfg.gemini_base_url))
        groq = data.get("groq", {}) if isinstance(data.get("groq"), dict) else {}
        cfg.groq_model = str(groq.get("model", cfg.groq_model))
        cfg.groq_base_url = str(groq.get("base_url", cfg.groq_base_url))
        mistral = data.get("mistral", {}) if isinstance(data.get("mistral"), dict) else {}
        cfg.mistral_model = str(mistral.get("model", cfg.mistral_model))
        cfg.mistral_base_url = str(mistral.get("base_url", cfg.mistral_base_url))

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
        if os.environ.get("NVIDIA_TIMEOUT_MAX"):
            cfg.nvidia_timeout_max = int(os.environ["NVIDIA_TIMEOUT_MAX"])
        if os.environ.get("NVIDIA_CONNECT_TIMEOUT"):
            try:
                v = int(os.environ["NVIDIA_CONNECT_TIMEOUT"])
                if v > 0:
                    cfg.nvidia_connect_timeout = v
            except ValueError:
                pass
        cfg.openrouter_model = os.environ.get("OPENROUTER_MODEL",
                                              cfg.openrouter_model)
        cfg.openrouter_base_url = os.environ.get("OPENROUTER_BASE_URL",
                                                 cfg.openrouter_base_url)
        cfg.gemini_model = os.environ.get("GEMINI_MODEL", cfg.gemini_model)
        cfg.gemini_base_url = os.environ.get("GEMINI_BASE_URL",
                                             cfg.gemini_base_url)
        cfg.groq_model = os.environ.get("GROQ_MODEL", cfg.groq_model)
        cfg.groq_base_url = os.environ.get("GROQ_BASE_URL", cfg.groq_base_url)
        cfg.mistral_model = os.environ.get("MISTRAL_MODEL", cfg.mistral_model)
        cfg.mistral_base_url = os.environ.get("MISTRAL_BASE_URL", cfg.mistral_base_url)
        cfg.media_providers = os.environ.get("CURIO_MEDIA_PROVIDERS",
                                             cfg.media_providers)
        cfg.cache_dir = os.environ.get("CURIO_CACHE_DIR", cfg.cache_dir)
        if os.environ.get("CURIO_WPM"):
            cfg.teleprompter_wpm = int(os.environ["CURIO_WPM"])
        cfg.whisper_model = os.environ.get("CURIO_WHISPER_MODEL",
                                           cfg.whisper_model)
        cfg.metrics_dir = os.environ.get("CURIO_METRICS_DIR",
                                           cfg.metrics_dir)
        research = data.get("research", {}) if isinstance(data.get("research"), dict) else {}
        cfg.research_max_sources = max(1, int(research.get("max_sources", cfg.research_max_sources)))
        cfg.research_timeout = max(5, int(research.get("timeout", cfg.research_timeout)))
        if os.environ.get("CURIO_RESEARCH_MAX_SOURCES"):
            cfg.research_max_sources = max(1, int(os.environ["CURIO_RESEARCH_MAX_SOURCES"]))
        if os.environ.get("CURIO_RESEARCH_TIMEOUT"):
            cfg.research_timeout = max(5, int(os.environ["CURIO_RESEARCH_TIMEOUT"]))
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
        cfg.visual_insertions = int(vis.get("insertions",
                                            cfg.visual_insertions))
        cfg.visual_insert_style = str(vis.get("insert_style",
                                              cfg.visual_insert_style)).strip()
        cfg.visual_insert_gain_db = int(vis.get("insert_gain_db",
                                                cfg.visual_insert_gain_db))
        if os.environ.get("CURIO_VISUAL_INSERTIONS"):
            cfg.visual_insertions = int(os.environ["CURIO_VISUAL_INSERTIONS"])
        if os.environ.get("CURIO_VISUAL_INSERT_STYLE"):
            cfg.visual_insert_style = os.environ["CURIO_VISUAL_INSERT_STYLE"]
        if os.environ.get("CURIO_VISUAL_INSERT_GAIN_DB"):
            cfg.visual_insert_gain_db = int(
                os.environ["CURIO_VISUAL_INSERT_GAIN_DB"])
        # 0–5: acima de 5 deixa de ser "complemento" e vira slideshow.
        cfg.visual_insertions = max(0, min(5, cfg.visual_insertions))
        if cfg.visual_insert_style not in ALLOWED_INSERT_STYLES:
            cfg.visual_insert_style = "drop_in"
        # -45..-12 dB: abaixo de -45 some; acima de -12 compete com a narração.
        cfg.visual_insert_gain_db = max(-45, min(-12,
                                                 cfg.visual_insert_gain_db))
        audio = data.get("audio", {}) if isinstance(data.get("audio"), dict) else {}
        music = data.get("music", {}) if isinstance(data.get("music"), dict) else {}
        music_lib = music.get("library", {}) if isinstance(music.get("library"), dict) else {}
        sfx = data.get("sfx", {}) if isinstance(data.get("sfx"), dict) else {}
        sfx_lib = sfx.get("library", {}) if isinstance(sfx.get("library"), dict) else {}
        cfg.audio_enabled = _as_bool(audio.get("enabled", cfg.audio_enabled),
                                     cfg.audio_enabled)
        cfg.audio_library_dir = str(audio.get("library_dir", cfg.audio_library_dir))
        if os.environ.get("CURIO_AUDIO_LIBRARY_DIR"):
            cfg.audio_library_dir = os.environ["CURIO_AUDIO_LIBRARY_DIR"]
        cfg.music_mode = str(music.get("mode", cfg.music_mode)).strip().lower()
        if cfg.music_mode not in ("auto", "none", "manual"):
            cfg.music_mode = "auto"
        cfg.music_file = str(music.get("file", cfg.music_file))
        cfg.music_auto_fill = _as_bool(
            music.get("auto_fill", cfg.music_auto_fill), cfg.music_auto_fill)
        if os.environ.get("CURIO_MUSIC_MODE"):
            mode = os.environ["CURIO_MUSIC_MODE"].strip().lower()
            if mode in ("auto", "none", "manual"):
                cfg.music_mode = mode
                cfg.audio_enabled = True
        if os.environ.get("CURIO_MUSIC_FILE"):
            cfg.music_file = os.environ["CURIO_MUSIC_FILE"]
            cfg.audio_enabled = True
        if os.environ.get("CURIO_MUSIC_AUTO_FILL") is not None:
            cfg.music_auto_fill = _as_bool(os.environ["CURIO_MUSIC_AUTO_FILL"])
            cfg.audio_enabled = True
        cfg.music_max_per_genre = max(0, int(music_lib.get(
            "max_per_genre", cfg.music_max_per_genre)))
        cfg.music_min_per_genre = max(0, min(cfg.music_max_per_genre,
            int(music_lib.get("min_per_genre", cfg.music_min_per_genre))))
        cfg.music_target_per_genre = max(cfg.music_min_per_genre, min(
            cfg.music_max_per_genre, int(music_lib.get(
                "target_per_genre", cfg.music_target_per_genre))))
        cfg.music_gain_db = max(-40, min(-15, int(music.get(
            "gain_db", cfg.music_gain_db))))
        cfg.music_ducking = _as_bool(music.get("ducking", cfg.music_ducking),
                                     cfg.music_ducking)
        cfg.music_transitions = str(audio.get("transitions", "auto")).lower()
        if cfg.music_transitions not in ("auto", "none"):
            cfg.music_transitions = "auto"
        cfg.sfx_library_enabled = _as_bool(sfx.get(
            "library_enabled", cfg.sfx_library_enabled), cfg.sfx_library_enabled)
        cfg.sfx_auto_fill = _as_bool(sfx.get("auto_fill", cfg.sfx_auto_fill),
                                    cfg.sfx_auto_fill)
        cfg.sfx_max_per_category = max(0, int(sfx_lib.get(
            "max_per_category", cfg.sfx_max_per_category)))
        cfg.sfx_min_per_category = max(0, min(cfg.sfx_max_per_category,
            int(sfx_lib.get("min_per_category", cfg.sfx_min_per_category))))
        cfg.sfx_target_per_category = max(cfg.sfx_min_per_category, min(
            cfg.sfx_max_per_category, int(sfx_lib.get(
                "target_per_category", cfg.sfx_target_per_category))))
        cfg.file_manager = os.environ.get("CURIO_FILE_MANAGER",
                                          cfg.file_manager)
        cfg.audio_recorder = os.environ.get("CURIO_AUDIO_RECORDER",
                                            cfg.audio_recorder)
        if os.environ.get("CURIO_AUTO_OPEN") is not None:
            cfg.auto_open = os.environ["CURIO_AUTO_OPEN"].strip().lower() not in (
                "0", "false", "no", "n")
        lang_toml = data.get("language", None)
        if lang_toml:
            cfg.language = str(lang_toml)
        if os.environ.get("CURIO_LANGUAGE"):
            cfg.language = str(os.environ["CURIO_LANGUAGE"])
        cfg.language = normalize_language(cfg.language)
        if is_english(cfg.language) and cfg.tts_voice == "pt-BR-AntonioNeural":
            cfg.tts_voice = "en-US-GuyNeural"
        # Gênero editorial. Guardado como veio (minúsculo, sem validar):
        # um valor desconhecido tem de ser visível no doctor/dry-run, não
        # normalizado em silêncio para o padrão.
        cfg.genre = str(data.get("genre", cfg.genre) or "").strip().lower()
        if os.environ.get("CURIO_GENRE"):
            cfg.genre = os.environ["CURIO_GENRE"].strip().lower()
        # Tipografia: `[typography.<gênero>]` com família por INTENÇÃO
        # (primary, italic, sans, mono, condensed, fallback) e, se
        # preciso, por PAPEL em `[typography.<gênero>.roles]`. Fica no
        # config.toml de sempre — o usuário troca a fonte do gênero sem
        # tocar em código.
        typo = data.get("typography")
        cfg.typography = {}
        if isinstance(typo, dict):
            for g, tabela in typo.items():
                if isinstance(tabela, dict):
                    cfg.typography[str(g).strip().lower()] = {
                        str(k): v for k, v in tabela.items()}
        for g, tabela in cfg.typography.items():
            env = os.environ.get(f"CURIO_TYPOGRAPHY_{g.upper()}")
            if env:
                # "primary=Minion Pro;italic=Minion Pro Italic"
                for pedaco in env.split(";"):
                    if "=" in pedaco:
                        k, v = pedaco.split("=", 1)
                        tabela[k.strip()] = v.strip()
        # E o env sozinho, sem nenhuma tabela no arquivo: é o caso de quem
        # não mantém config.toml. Sem esta volta, `CURIO_TYPOGRAPHY_PEOPLE`
        # seria ignorado justamente quando não há `[typography.people]`
        # para ele sobrescrever, que é quando ele é a única fonte.
        for variavel, valor in os.environ.items():
            if not variavel.startswith("CURIO_TYPOGRAPHY_") or not valor:
                continue
            g = variavel[len("CURIO_TYPOGRAPHY_"):].strip().lower()
            if not g or g in cfg.typography:
                continue
            tabela = {}
            for pedaco in valor.split(";"):
                if "=" in pedaco:
                    k, v = pedaco.split("=", 1)
                    tabela[k.strip()] = v.strip()
            if tabela:
                cfg.typography[g] = tabela
        cfg.queues_dir = str(data.get("queues_dir", cfg.queues_dir))
        if os.environ.get("CURIO_QUEUES_DIR"):
            cfg.queues_dir = str(os.environ["CURIO_QUEUES_DIR"])
        return cfg

    def llm_overrides(self) -> dict:
        """Overrides de modelo e base_url para fallbacks do chain.

        Valores já com precedência CLI > env > config.toml > padrão.
        """
        return {
            "gemini": (self.gemini_model, self.gemini_base_url),
            "groq": (self.groq_model, self.groq_base_url),
            "mistral": (self.mistral_model, self.mistral_base_url),
        }

    def as_dict(self) -> dict:
        return {
            "duration_target": self.duration_target,
            "out_dir": self.out_dir,
            "queues_dir": self.queues_dir,
            "language": self.language,
            "tts_provider": self.tts_provider,
            "tts_voice": self.tts_voice,
            "tts_speed": self.tts_speed,
            "render_backend": self.render_backend,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "music_mode": self.music_mode,
            "audio_library_dir": self.audio_library_dir,
            "audio_enabled": self.audio_enabled,
        }
