"""TUI visual em terminal (stdlib, sem dependências).

Organizada por OBJETIVO, não por comando técnico:
- "Quero um vídeo pronto" → narração IA, sai com MP4 final.
- "Quero narrar eu mesmo" → assistente em 2 passos, deixando explícito que
  o vídeo final SÓ existe depois do passo 2 (finalize com sua voz).
- "Ajuda" explica os fluxos, arquivos e o que fazer em cada etapa.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sys

from . import verify as verify_mod
from .config import ALLOWED_INSERT_STYLES as INSERT_STYLES
from .config import CurioConfig, parse_duration
from .pipeline import (_paths_for_slug, iter_projects, run_pipeline)
from .pipeline_media import MediaStandby
from .slug import find_project_root, project_dir, slugify_with_timestamp
from .tui_terminal import (TUIExit as _TUIExit, ask as _ask,
                          banner as _banner, browse_path, clear as _clear,
                          colors as _colors, pause as _pause, select_option)

QUICK_TEST_IDEA = "De onde veio a palavra salário?"
QUICK_TEST_SLUG = "teste-rapido"

LLM_PROVIDERS = ("nvidia", "openrouter", "gemini", "groq")
MEDIA_PROVIDERS = ("pixabay", "unsplash", "pexels", "nasa", "met", "aic", "wikimedia", "openverse")


def _confirm_twice(prompt: str, confirm_text: str = "SIM") -> bool:
    """Confirmação dupla para ações destrutivas."""
    first = _ask(f"{prompt} [s/N]: ").strip().lower()
    if not first.startswith("s"):
        return False
    second = _ask(f"Tem certeza? Digite '{confirm_text}' para confirmar: ").strip()
    return second == confirm_text


def _status_summary(cfg: CurioConfig) -> list[str]:
    """Linha de status sempre visível: projetos, filas, idioma, mídia."""
    try:
        n_projects = sum(1 for e in os.listdir(cfg.out_dir)
                         if os.path.isdir(os.path.join(cfg.out_dir, e))) if os.path.isdir(cfg.out_dir) else 0
    except OSError:
        n_projects = 0
    try:
        from .queue import default_queues_dir, list_queue_files
        qdir = default_queues_dir(cfg)
        n_queues = len(list_queue_files(qdir)) if os.path.isdir(qdir) else 0
    except Exception:
        n_queues = 0
        qdir = cfg.queues_dir
    lang = "EN" if str(cfg.language).lower().startswith("en") else "PT"
    return [f"projetos: {n_projects}   filas: {n_queues}   idioma: {lang}   mídia: {cfg.media_providers}",
            f"out: {cfg.out_dir}   filas em: {qdir}"]


def _ask_duration(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    """Meta de duração (nunca corta): auto ou segundos. Padrão: auto."""
    from .config import parse_duration
    raw = _ask("Duração [auto/30/45/60/90/120/180/outro Nºs, padrão auto]: ").strip()
    if not raw:
        print("Duração: automática (o conteúdo manda).")
        import dataclasses as _dc
        return _dc.replace(cfg, duration_target=0.0)
    if raw.strip().lower().startswith("person"):
        raw = _ask("Quantos segundos (5..600)? ").strip()
    try:
        seconds = parse_duration(raw)
    except ValueError as exc:
        print(f"{exc} — mantendo atual.")
        return cfg
    import dataclasses
    if seconds <= 0:
        print("Duração: automática (o conteúdo manda).")
    else:
        print(f"Duração-alvo: {seconds:.0f}s (meta, sem corte).")
    return dataclasses.replace(cfg, duration_target=seconds)


def _progress(idx: int, total: int, label: str, status: str) -> None:
    print(f"  [{idx}/{total}] {label}... {status}", flush=True)


def _run_event(record: dict) -> None:
    if record.get("event") in {"log_ready", "progress", "warning", "fallback", "provider",
                                "result", "cache", "retry", "error"}:
        from .runlog import safe_text
        print(f"    {safe_text(record.get('message', ''))[:240]}", flush=True)


def _show_standby(c: dict[str, str], exc: MediaStandby) -> None:
    """Painel de standby: sem imagens, usuário provê fotos e continua."""
    print(f"\n{c['yellow']}◷ STANDBY — nenhuma imagem encontrada "
          f"para {exc.n_scenes} cena(s).{c['reset']}")
    print("O vídeo NÃO foi produzido (sem tela preta/vazia).")
    print(f"  1) Coloque fotos (.jpg/.png/.webp) em:\n     {exc.manual_dir}")
    print("  2) Volte aqui e rode o mesmo fluxo de novo (sem refazer).")


def _show_sources(c: dict[str, str], meta: dict) -> None:
    research = (meta or {}).get("research") or {}
    n = int(research.get("sources") or 0)
    titles = [t for t in (research.get("titles") or []) if t][:3]
    extra = f" ({'; '.join(titles)})" if titles else ""
    print(f"Fontes: {n} [{research.get('status', '?')}]" + extra)


def _show_verify(c: dict[str, str], mp4: str, srt: str, cfg: CurioConfig) -> bool:
    print(f"\n{c['bold']}Verificação do vídeo:{c['reset']}")
    rep = verify_mod.verify_video(mp4, srt, cfg.duration_target, cfg.width, cfg.height)
    for chk in rep.checks:
        mark = f"{c['green']}OK   {c['reset']}" if chk.ok else f"{c['red']}FALHA{c['reset']}"
        extra = f" {c['dim']}— {chk.detail}{c['reset']}" if chk.detail else ""
        print(f"[{mark}] {chk.label}{extra}")
    print(f"\n{c['bold']}{rep.passed}/{rep.total} verificações passaram.{c['reset']}")
    return rep.success


def _project_status(cfg: CurioConfig, slug: str) -> tuple[str, dict]:
    """Retorna (situação legível, metadata). Aceita `slug` e `genero/slug`."""
    genre_part, sep, rest = slug.partition("/")
    root = None
    if sep:
        cand = project_dir(cfg.out_dir, genre_part, rest)
        if os.path.isdir(cand):
            root = cand
    else:
        root = find_project_root(cfg.out_dir, slug)
    if root is None:
        return "não encontrado", {}
    meta_path = os.path.join(root, "metadata.json")
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except json.JSONDecodeError:
        return "metadados corrompidos", {}
    if meta.get("status") == "standby-no-media":
        manual = meta.get("manual_dir", "assets/manual")
        return (f"STANDBY sem imagens — coloque fotos em {manual} "
                f"e rode o generate de novo"), meta
    mode = meta.get("narration", "ai")
    tag = " (roteiro pronto)" if meta.get("mode") == "script" else ""
    if mode == "human-pending":
        return "aguardando sua voz (sem vídeo final ainda)" + tag, meta
    if mode == "human":
        return "vídeo final com SUA voz" + tag, meta
    return "vídeo final pronto (voz de IA)" + tag, meta


# ------------------------------------------------------- configuração avançada
def _apply_language(cfg: CurioConfig, lang: str) -> CurioConfig:
    """Aplica o idioma ao cfg, ajustando a voz padrão junto."""
    from .config import normalize_language
    lang = normalize_language(lang)
    cfg = dataclasses.replace(cfg, language=lang)
    if lang == "en-US" and cfg.tts_voice == "pt-BR-AntonioNeural":
        cfg = dataclasses.replace(cfg, tts_voice="en-US-GuyNeural")
    elif lang == "pt-BR" and cfg.tts_voice == "en-US-GuyNeural":
        cfg = dataclasses.replace(cfg, tts_voice="pt-BR-AntonioNeural")
    return cfg


def _ask_language(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    """Seletor de idioma do vídeo: PT-BR ou EN-US (100% inglês)."""
    from .config import normalize_language
    idx = select_option(
        c, "Idioma do vídeo",
        ["Português (PT-BR) — roteiro, título, narração e legendas em português",
         "English (EN-US) — 100% in English: script, title, voice and captions"],
        status=[f"atual: {cfg.language}   voz: {cfg.tts_voice}"])
    if idx is None:
        return cfg
    cfg = _apply_language(cfg, "en-US" if idx == 1 else "pt-BR")
    print(f"Idioma: {cfg.language}   voz: {cfg.tts_voice}")
    return cfg


def _ask_queues_dir(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    idx = select_option(
        c, "Pasta padrão das filas",
        ["Usar pasta padrão (queues/)",
         "Escolher outro caminho",
         "Cancelar"],
        status=[f"atual: {cfg.queues_dir}"])
    if idx is None or idx == 2:
        return cfg
    if idx == 0:
        return dataclasses.replace(cfg, queues_dir="queues")
    picked = browse_path(c, cfg.queues_dir or ".", "Pasta das filas", dirs_only=True)
    if picked:
        return dataclasses.replace(cfg, queues_dir=picked)
    return cfg


def _show_current_config(c: dict[str, str], cfg: CurioConfig) -> None:
    print(f"\n{c['bold']}Configuração atual:{c['reset']}")
    print(f"  Idioma do vídeo: {cfg.language} (voz: {cfg.tts_voice})")
    print(f"  Diretório de saída: {cfg.out_dir}")
    print(f"  Pasta das filas: {cfg.queues_dir}")
    print(f"  Cache: {cfg.cache_dir}")
    print(f"  LLM: {cfg.nvidia_model} (base: {cfg.nvidia_base_url})")
    print(f"  OpenRouter: {cfg.openrouter_model} (base: {cfg.openrouter_base_url})")
    print(f"  Gemini: {cfg.gemini_model} (base: {cfg.gemini_base_url})")
    print(f"  Groq: {cfg.groq_model} (base: {cfg.groq_base_url})")
    print(f"  Mistral: {cfg.mistral_model} (base: {cfg.mistral_base_url})")
    print(f"  TTS: {cfg.tts_provider} / {cfg.tts_voice} / speed {cfg.tts_speed}")
    print(f"  Render: {cfg.render_backend} / {cfg.render_encoder}")
    print(f"  Mídia providers: {cfg.media_providers}")
    print(f"  Imagens por cena: {cfg.visual_max_images}")
    print(f"  Inserções por vídeo: {cfg.visual_insertions} "
          f"(estilo {cfg.visual_insert_style}, "
          f"som {cfg.visual_insert_gain_db} dB)")
    print(f"  Overlap visual: {cfg.visual_overlap}")
    print(f"  SFX visual: {cfg.visual_sfx}")
    print(f"  Música: {cfg.music_mode} ({cfg.music_gain_db} dB) · "
          f"ducking {cfg.music_ducking} · biblioteca {cfg.audio_library_dir}")
    print(f"  Whisper: {cfg.whisper_model}")
    _show_genre(c, cfg)


def _provider_menu(c: dict[str, str], cfg: CurioConfig, providers: tuple[str, ...],
                   label: str, current: str, env_prefix: str) -> CurioConfig:
    print(f"\n{c['bold']}Selecionar {label} (provedores disponíveis: {', '.join(providers)}, none):{c['reset']}")
    print(f"  Atual: {current}")
    choice = _ask(f"  Novo ({'|'.join(providers)}/none, Enter=pula): ").strip().lower()
    if not choice:
        return cfg
    if choice == "none":
        new_val = "none"
    elif choice in providers:
        new_val = choice
    else:
        print(f"{c['red']}Inválido. Opções: {', '.join(providers)}, none{c['reset']}")
        return cfg
    return dataclasses.replace(cfg, **{f"{env_prefix}_providers": new_val})


def _ask_llm_provider(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    return _provider_menu(c, cfg, LLM_PROVIDERS, "LLM", cfg.nvidia_model, "nvidia_model")


def _ask_media_providers(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    # Para mídia, aceita CSV
    print(f"\n{c['bold']}Providers de mídia (CSV, ex.: pixabay,unsplash,nasa,wikimedia):{c['reset']}")
    print(f"  Atual: {cfg.media_providers}")
    choice = _ask(f"  Novo (Enter=pula): ").strip().lower()
    if not choice:
        return cfg
    valid = set(MEDIA_PROVIDERS + ("none",))
    chosen = [p.strip() for p in choice.split(",") if p.strip()]
    if all(p in valid for p in chosen):
        return dataclasses.replace(cfg, media_providers=",".join(chosen))
    print(f"{c['red']}Inválido. Use: {', '.join(MEDIA_PROVIDERS)} ou none{c['reset']}")
    return cfg


def _ask_cache_dir(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    print(f"\n{c['bold']}Diretório de cache (atual: {cfg.cache_dir}):{c['reset']}")
    choice = _ask("  Novo caminho (Enter=pula): ").strip()
    if not choice:
        return cfg
    return dataclasses.replace(cfg, cache_dir=choice)


def _ask_output_dir(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    print(f"\n{c['bold']}Diretório de saída (atual: {cfg.out_dir}):{c['reset']}")
    choice = _ask("  Novo caminho (Enter=pula): ").strip()
    if not choice:
        return cfg
    return dataclasses.replace(cfg, out_dir=choice)


def _config_flow(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    while True:
        _clear()
        _banner(c)
        _show_current_config(c, cfg)
        idx = select_option(
            c, "Configurações — o que ajustar?",
            ["Idioma do vídeo (PT-BR / EN-US)",
             "Provider LLM",
             "Providers de mídia",
             "Diretório de cache",
             "Diretório de saída (projetos)",
             "Pasta padrão das filas",
             "Duração-alvo",
             "TTS (provider/voz/speed)",
             "Render (backend/encoder)",
             "Visual (inserções/max_images/overlap/SFX)",
             "Áudio (música/biblioteca/transições)",
             "Gênero editorial (padrão de vídeo)",
             "Voltar"],
            status=_status_summary(cfg))
        if idx is None or idx == 12:
            return cfg
        if idx == 0:
            cfg = _ask_language(c, cfg)
        elif idx == 1:
            cfg = _ask_llm_provider(c, cfg)
        elif idx == 2:
            cfg = _ask_media_providers(c, cfg)
        elif idx == 3:
            cfg = _ask_cache_dir(c, cfg)
        elif idx == 4:
            cfg = _ask_output_dir(c, cfg)
        elif idx == 5:
            cfg = _ask_queues_dir(c, cfg)
        elif idx == 6:
            cfg = _ask_duration(c, cfg)
        elif idx == 7:
            cfg = _ask_tts(c, cfg)
        elif idx == 8:
            cfg = _ask_render(c, cfg)
        elif idx == 9:
            cfg = _ask_visual(c, cfg)
        elif idx == 10:
            cfg = _ask_audio(c, cfg)
        elif idx == 11:
            cfg = _ask_genre(c, cfg)
        _pause(c)
    return cfg


def _ask_tts(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    print(f"\n{c['bold']}Configuração TTS:{c['reset']}")
    prov = _ask(f"  Provider [{cfg.tts_provider}]: ").strip()
    if prov:
        cfg = dataclasses.replace(cfg, tts_provider=prov)
    voice = _ask(f"  Voz [{cfg.tts_voice}]: ").strip()
    if voice:
        cfg = dataclasses.replace(cfg, tts_voice=voice)
    speed = _ask(f"  Speed [{cfg.tts_speed}]: ").strip()
    if speed:
        try:
            cfg = dataclasses.replace(cfg, tts_speed=float(speed))
        except ValueError:
            print(f"{c['red']}Speed inválido{c['reset']}")
    return cfg


def _ask_render(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    print(f"\n{c['bold']}Configuração Render:{c['reset']}")
    backend = _ask(f"  Backend [{cfg.render_backend}] (arc/auto/vaapi/qsv/cpu): ").strip()
    if backend:
        cfg = dataclasses.replace(cfg, render_backend=backend)
    encoder = _ask(f"  Encoder [{cfg.render_encoder}] (ex.: hevc,h264): ").strip()
    if encoder:
        cfg = dataclasses.replace(cfg, render_encoder=encoder)
    return cfg


def _ask_visual(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    print(f"\n{c['bold']}Configuração Visual:{c['reset']}")
    mi = _ask(f"  Max images por cena [{cfg.visual_max_images}] (1-5): ").strip()
    if mi:
        try:
            cfg = dataclasses.replace(cfg, visual_max_images=max(1, min(5, int(mi))))
        except ValueError:
            print(f"{c['red']}Inválido{c['reset']}")
    ins = _ask(f"  Inserções por vídeo [{cfg.visual_insertions}] (0-5, 1-2 o ideal): ").strip()
    if ins:
        try:
            cfg = dataclasses.replace(cfg, visual_insertions=max(0, min(5, int(ins))))
        except ValueError:
            print(f"{c['red']}Inválido{c['reset']}")
    if cfg.visual_insertions > 0:
        style = _ask(f"  Estilo da inserção [{cfg.visual_insert_style}] "
                     f"({'|'.join(INSERT_STYLES)}): ").strip().lower()
        if style:
            if style in INSERT_STYLES:
                cfg = dataclasses.replace(cfg, visual_insert_style=style)
            else:
                print(f"{c['red']}Estilo inválido. Use: "
                      f"{'|'.join(INSERT_STYLES)}{c['reset']}")
        gain = _ask(f"  Volume do som [{cfg.visual_insert_gain_db}] dB "
                    f"(-45..-12, -21 audível): ").strip()
        if gain:
            try:
                cfg = dataclasses.replace(
                    cfg, visual_insert_gain_db=max(-45, min(-12, int(gain))))
            except ValueError:
                print(f"{c['red']}Inválido{c['reset']}")
    ov = _ask(f"  Overlap cap [{cfg.visual_overlap}] (0-1): ").strip()
    if ov:
        try:
            cfg = dataclasses.replace(cfg, visual_overlap=float(ov))
        except ValueError:
            print(f"{c['red']}Inválido{c['reset']}")
    sfx = _ask(f"  SFX [{cfg.visual_sfx}] (s/n): ").strip().lower()
    if sfx in ("s", "sim", "y", "yes", "true"):
        cfg = dataclasses.replace(cfg, visual_sfx=True)
    elif sfx in ("n", "nao", "no", "false"):
        cfg = dataclasses.replace(cfg, visual_sfx=False)
    return cfg


def _ask_audio(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    from .audio.library import AudioLibrary, AudioLibraryError

    choices = ["Automática (biblioteca local)", "Nenhuma música",
               "Escolher arquivo", "Atualizar biblioteca", "Voltar"]
    selected = {"auto": 0, "none": 1, "manual": 2}.get(cfg.music_mode, 0)
    idx = select_option(
        c, "MÚSICA — opcional; automática usa a biblioteca local",
        choices, selected=selected,
        status=[f"biblioteca: {cfg.audio_library_dir}",
                f"gênero: {cfg.genre or 'selecione um gênero para baixar'}"])
    if idx is None or idx == 4:
        return cfg
    if idx == 3:
        cfg = dataclasses.replace(cfg, audio_enabled=True)
        if not cfg.genre:
            print("Escolha um gênero antes de atualizar a biblioteca.")
        else:
            try:
                lib = AudioLibrary(cfg.audio_library_dir)
                report = lib.update("music", cfg.genre,
                                    cfg.music_target_per_genre,
                                    cfg.music_max_per_genre)
                print(f"{cfg.genre}: adicionadas {report['added']} faixa(s); "
                      f"total {report.get('after', report['before'])}.")
            except (AudioLibraryError, OSError) as exc:
                print(f"Biblioteca não atualizada: {exc}")
        return cfg
    mode = ("auto", "none", "manual")[idx]
    cfg = dataclasses.replace(cfg, music_mode=mode, audio_enabled=True)
    if mode == "manual":
        path = _ask("Arquivo de música (mp3/wav/ogg/flac): ").strip()
        if path:
            cfg = dataclasses.replace(cfg, music_file=os.path.expanduser(path))
    gain = _ask(f"Volume musical [{cfg.music_gain_db} dB] (-40..-3): ").strip()
    if gain:
        try:
            cfg = dataclasses.replace(cfg, music_gain_db=max(-40, min(-3, int(gain))))
        except ValueError:
            print("Volume inválido; mantendo valor anterior.")
    duck = _ask(f"Ducking sob a narração [{cfg.music_ducking}] (s/n): ").strip().lower()
    if duck in ("s", "sim", "y", "yes"):
        cfg = dataclasses.replace(cfg, music_ducking=True)
    elif duck in ("n", "nao", "não", "no"):
        cfg = dataclasses.replace(cfg, music_ducking=False)
    return cfg


# ------------------------------------------------------- limpeza
def _clear_cache(c: dict[str, str], cfg: CurioConfig) -> None:
    print(f"\n{c['bold']}LIMPAR CACHE{c['reset']}")
    print(f"  Diretório: {cfg.cache_dir}")
    if not os.path.isdir(cfg.cache_dir):
        print(f"  {c['yellow']}Cache não existe.{c['reset']}")
        return
    # Mostra tamanho
    total = 0
    for root, dirs, files in os.walk(cfg.cache_dir):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    print(f"  Tamanho atual: {total / (1024*1024):.1f} MB")
    if _confirm_twice(f"Apagar TODO o cache em {cfg.cache_dir}?"):
        try:
            shutil.rmtree(cfg.cache_dir)
            print(f"{c['green']}Cache removido.{c['reset']}")
        except Exception as exc:
            print(f"{c['red']}Erro: {exc}{c['reset']}")
    else:
        print("Cancelado.")


def _clear_output(c: dict[str, str], cfg: CurioConfig) -> None:
    print(f"\n{c['bold']}LIMPAR PASTA DE SAÍDA{c['reset']}")
    print(f"  Diretório: {cfg.out_dir}")
    if not os.path.isdir(cfg.out_dir):
        print(f"  {c['yellow']}Pasta não existe.{c['reset']}")
        return
    # Conta projetos (plano legado + pastas de gênero)
    projects = [ref for ref, _root in iter_projects(cfg.out_dir)]
    tops = sorted({ref.split("/")[0] for ref in projects})
    print(f"  Projetos encontrados: {len(projects)}")
    for p in projects:
        print(f"    - {p}")
    if _confirm_twice(f"Apagar TODOS os {len(projects)} projetos em {cfg.out_dir}?", "APAGAR TUDO"):
        try:
            for p in tops:
                shutil.rmtree(os.path.join(cfg.out_dir, p))
            print(f"{c['green']}Pasta de saída limpa.{c['reset']}")
        except Exception as exc:
            print(f"{c['red']}Erro: {exc}{c['reset']}")
    else:
        print("Cancelado.")


def _clear_project(c: dict[str, str], cfg: CurioConfig) -> None:
    slug = _ask("Projeto (slug da pasta em output/): ").strip()
    if not slug:
        return
    try:
        _, paths = _paths_for_slug(cfg.out_dir, slug)
        proj_path = paths.root
    except FileNotFoundError:
        print(f"{c['red']}Projeto '{slug}' não encontrado.{c['reset']}")
        return
    status, meta = _project_status(cfg, slug)
    print(f"  {slug}: {status}")
    if _confirm_twice(f"Apagar projeto '{slug}'?", slug.upper()):
        try:
            shutil.rmtree(proj_path)
            print(f"{c['green']}Projeto removido.{c['reset']}")
        except Exception as exc:
            print(f"{c['red']}Erro: {exc}{c['reset']}")
    else:
        print("Cancelado.")


def _cleanup_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    while True:
        idx = select_option(
            c, "Limpeza e manutenção",
            ["Limpar cache (imagens, fontes)",
             "Limpar projeto específico",
             "LIMPAR TUDO (cache + output) — IRREVERSÍVEL",
             "Ver tamanho do cache e output",
             "Voltar"],
            status=_status_summary(cfg))
        if idx is None or idx == 4:
            return
        if idx == 0:
            _clear_cache(c, cfg)
        elif idx == 1:
            _clear_project(c, cfg)
        elif idx == 2:
            if _confirm_twice(f"{c['red']}APAGAR CACHE + OUTPUT TODOS?{c['reset']}", "SIM APAGUE TUDO"):
                _clear_cache(c, cfg)
                _clear_output(c, cfg)
            else:
                print("Cancelado.")
        elif idx == 3:
            _show_sizes(c, cfg)
        _pause(c)


def _show_sizes(c: dict[str, str], cfg: CurioConfig) -> None:
    def _size(path: str) -> float:
        if not os.path.isdir(path):
            return 0.0
        total = 0
        for root, dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total / (1024 * 1024)
    
    cache_mb = _size(cfg.cache_dir)
    output_mb = _size(cfg.out_dir)
    print(f"\n{c['bold']}Tamanhos:{c['reset']}")
    print(f"  Cache: {cache_mb:.1f} MB ({cfg.cache_dir})")
    print(f"  Output: {output_mb:.1f} MB ({cfg.out_dir})")
    print(f"  Total: {cache_mb + output_mb:.1f} MB")


# ------------------------------------------------------- fila de ideias
def _queue_status_lines(queue) -> list[str]:
    from .queue import QueueItemStatus
    icons = {QueueItemStatus.WAITING: "○", QueueItemStatus.PROCESSING: "▶",
             QueueItemStatus.COMPLETED: "✓", QueueItemStatus.ERROR: "✗",
             QueueItemStatus.PAUSED: "⏸", QueueItemStatus.CANCELLED: "⊘"}
    lines = [queue.progress_str()]
    for it in queue.items:
        err = f" — {it.error[:60]}" if it.error else ""
        lines.append(f"{icons.get(it.status, '?')} {it.idea[:60]}{err}")
    return lines


def _queue_choose_save_path(c, cfg, default_name: str) -> str | None:
    from .queue import ensure_queues_dir
    idx = select_option(
        c, "Onde deseja salvar a fila?",
        ["Usar pasta padrão", "Escolher outro caminho", "Cancelar"],
        status=[f"pasta padrão: {cfg.queues_dir}"])
    if idx is None or idx == 2:
        return None
    name = _ask(f"Nome do arquivo [{default_name}]: ").strip() or default_name
    if not name.lower().endswith((".txt", ".json")):
        name += ".json"
    if idx == 0:
        ensure_queues_dir(cfg)
        return os.path.join(cfg.queues_dir, os.path.basename(name))
    picked_dir = browse_path(c, cfg.queues_dir or ".", "Pasta da fila", dirs_only=True)
    if picked_dir is None:
        return None
    return os.path.join(picked_dir, os.path.basename(name))


def _queue_create(c, cfg) -> None:
    from .queue import VideoQueue, ensure_queues_dir
    from datetime import datetime
    name_default = f"ideias-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    print(f"\n{c['bold']}Nova fila — digite as ideias (linha vazia termina).{c['reset']}")
    ideas: list[str] = []
    while True:
        idea = _ask("  > ").strip()
        if not idea:
            break
        ideas.append(idea)
    if not ideas:
        print("Nenhuma ideia — fila não criada.")
        return
    queue = VideoQueue()
    queue.add_from_list(ideas)
    save_path = _queue_choose_save_path(c, cfg, name_default)
    if save_path is None:
        print("Criação cancelada (ideias descartadas).")
        return
    queue.save(save_path)
    print(f"{c['green']}Fila salva:{c['reset']} {save_path} ({len(ideas)} ideias)")
    _queue_detail(c, cfg, save_path)


def _queue_open(c, cfg) -> None:
    from .queue import VideoQueue, ensure_queues_dir, list_queue_files
    ensure_queues_dir(cfg)
    files = list_queue_files(cfg.queues_dir)
    opts = [f"{os.path.basename(f)}" for f in files] + ["Procurar em outro caminho", "Voltar"]
    idx = select_option(c, "Abrir fila existente", opts,
                        status=[f"pasta padrão: {cfg.queues_dir}",
                                f"{len(files)} fila(s) encontrada(s)"])
    if idx is None or idx == len(opts) - 1:
        return
    if idx == len(opts) - 2:
        picked = browse_path(c, cfg.queues_dir or ".", "Abrir fila")
        if picked is None:
            return
        path = picked
    else:
        path = files[idx]
    _queue_detail(c, cfg, path)


def _queue_detail(c, cfg, path: str) -> None:
    from .queue import (VideoQueue, process_queue, retry_failed,
                        reorder_items, remove_item)
    try:
        queue = VideoQueue.load(path)
    except Exception as exc:
        print(f"{c['red']}Não foi possível abrir {path}: {exc}{c['reset']}")
        _pause(c)
        return
    while True:
        counts = queue.progress_str()
        idx = select_option(
            c, f"Fila: {os.path.basename(path)}",
            ["Processar fila", "Adicionar ideias", "Remover ideia",
             "Reordenar ideia", "Repetir itens com erro/standby",
             "Ver status detalhado", "Voltar"],
            status=_queue_status_lines(queue)[:5] + [counts, f"arquivo: {path}"])
        if idx is None or idx == 6:
            try:
                queue.save(path)
            except Exception:
                pass
            return
        if idx == 0:
            _queue_run(c, cfg, queue, path)
        elif idx == 1:
            print("Digite as novas ideias (linha vazia termina):")
            added = 0
            while True:
                idea = _ask("  > ").strip()
                if not idea:
                    break
                queue.add(idea)
                added += 1
            queue.save(path)
            print(f"{added} ideia(s) adicionada(s).")
            _pause(c)
        elif idx == 2:
            cand = [f"{it.idea[:70]}" for it in queue.items] + ["Voltar"]
            pick = select_option(c, "Remover ideia", cand)
            if pick is None or pick == len(cand) - 1:
                continue
            if remove_item(queue, pick):
                queue.save(path)
                print("Ideia removida.")
            else:
                print(f"{c['yellow']}Só é possível remover itens ainda não processados.{c['reset']}")
            _pause(c)
        elif idx == 3:
            cand = [f"{it.idea[:70]}" for it in queue.items] + ["Voltar"]
            pick = select_option(c, "Mover qual ideia?", cand)
            if pick is None or pick == len(cand) - 1:
                continue
            dest_raw = _ask(f"Nova posição [1-{len(queue.items)}]: ").strip()
            try:
                dest = int(dest_raw) - 1
            except ValueError:
                print("Posição inválida.");
                _pause(c)
                continue
            if reorder_items(queue, pick, dest):
                queue.save(path)
                print("Ideia reordenada.")
            else:
                print(f"{c['yellow']}Só é possível reordenar itens aguardando.{c['reset']}")
            _pause(c)
        elif idx == 4:
            n = retry_failed(queue)
            queue.save(path)
            print(f"{n} item(ns) com erro voltaram para aguardando.")
            _pause(c)
        elif idx == 5:
            _clear()
            _banner(c)
            for line in queue.status_lines():
                print(line)
            print(f"\narquivo: {path}")
            _pause(c)


def _queue_run(c, cfg, queue, path: str) -> None:
    import time as _time
    from .queue import process_queue
    if not queue.items:
        print("Fila vazia.")
        _pause(c)
        return
    n_wait = sum(1 for it in queue.items if str(it.status) == "waiting")
    if n_wait == 0:
        print("Nada aguardando (use 'Repetir itens com erro' se precisar).")
        _pause(c)
        return
    go = select_option(c, f"Processar {n_wait} vídeo(s)?",
                       ["Iniciar agora", "Cancelar"],
                       status=_queue_status_lines(queue)[:6])
    if go != 0:
        return
    started = _time.monotonic()
    state: dict = {"stage": "", "last_error": ""}

    def on_start(item):
        print(f"\n▶ {item.idea}")

    def on_done(item, ok: bool):
        if ok:
            print(f"✓ {item.idea} ({item.duration_seconds:.0f}s) → {item.video_path}")
        else:
            from .runlog import safe_text
            state["last_error"] = safe_text(item.error)
            print(f"{c['red']}✗ {item.idea}: {safe_text(item.error)[:500]}{c['reset']}")
            print("Continuando para o próximo item...")

    def on_progress(q):
        elapsed = _time.monotonic() - started
        done = sum(1 for it in q.items if str(it.status) in ("completed", "error", "cancelled"))
        print(f"— {q.progress_str()}   decorrido: {elapsed:.0f}s   "
              f"restam: {len(q.items) - done}")

    queue.save(path)
    try:
        process_queue(queue, cfg, cfg.out_dir,
                      on_item_start=on_start, on_item_complete=on_done,
                      on_progress=on_progress, on_event=_run_event)
    except Exception as exc:
        print(f"{c['red']}ERRO na fila: {exc}{c['reset']}")
    queue.save(path)
    _clear()
    _banner(c)
    print(f"\n{c['bold']}CURIO — FILA (resultado){c['reset']}")
    for line in queue.status_lines():
        print(line)
    ok_n = sum(1 for it in queue.items if str(it.status) == "completed")
    err_n = sum(1 for it in queue.items if str(it.status) == "error")
    print(f"\nConcluídos: {ok_n}   erros: {err_n}   projetos em: {cfg.out_dir}/")
    _pause(c)


def _queue_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    while True:
        idx = select_option(
            c, "Fila de ideias — cada ideia vira um projeto independente",
            ["Criar nova fila", "Abrir fila existente", "Voltar"],
            status=_status_summary(cfg))
        if idx is None or idx == 2:
            return
        if idx == 0:
            _queue_create(c, cfg)
        else:
            _queue_open(c, cfg)


# ---------------------------------------------------------------- ajuda

HELP_TEXT = """\
COMO FUNCIONA — dois jeitos de produzir:

[A] VÍDEO PRONTO (voz de IA)
    Ideia → roteiro → cenas → fotos → narração de IA → legendas → MP4 final.
    Você sai daqui com o vídeo pronto para assistir e publicar.

[B] NARRAR EU MESMO (2 passos — não existe vídeo final no passo 1!)
    Passo 1 — preparar a base: ideia → roteiro → cenas → fotos →
              vídeo SILENCIOSO + TELEPROMPTER (texto grande para ler).
    Passo 2 — você grava sua voz assistindo ao teleprompter (qualquer
              gravador: celular, Audacity...), volta aqui e finaliza:
              a máquina transcreve SUA voz, sincroniza as legendas nela
              e entrega o MP4 final.
    Ou seja: narração humana sem vídeo? Nunca — o vídeo final nasce no
    passo 2, com a sua voz como fonte da sincronia.

ONDE FICAM AS COISAS (pasta output/<projeto>/):
    render/final.mp4          o vídeo final (só existe no fim do fluxo A ou B)
    render/silent.mp4         base silenciosa (passo 1 do fluxo B)
    teleprompter/teleprompter.mp4   o texto grande para você ler gravando
    timeline/visual_timeline.json   fotos por trecho (só no modo roteiro-pronto)
    audio/                    narração da IA ou a SUA voz + transcrição
    metadata.json             tudo sobre o projeto (capítulos, licenças, tempos)

[C] ROTEIRO PRONTO (opção 9 — sem reescrever nada)
    Você entrega o texto final; a máquina divide em trechos, busca fotos
    para cada um e monta a sequência em álbum (fotos entrando umas sobre
    as outras, nunca slides). A narração sai idêntica ao seu texto.

DICAS:
    - Reexecutar sem --force reaproveita o já pronto (rápido e sem custo).
    - Legendas vêm de timestamps reais (voz de IA ou transcrição da sua).
    - Sem internet: voz local simples; sem chave NVIDIA: roteiros locais.
"""


def _help_flow(c: dict[str, str]) -> None:
    print(f"\n{c['bold']}AJUDA{c['reset']}\n")
    print(HELP_TEXT)


# ------------------------------------------------------- fluxo A (IA)

def _ask_genre(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    """Seletor vertical de gênero; mantém as chaves editoriais existentes.

    Fica antes da ideia, e não depois: o gênero muda a pesquisa, então
    perguntar o tema primeiro levaria o usuário a escrever o tema pensando
    no formato errado.
    """
    from .stages import editorial
    opcoes = editorial.choices()
    atual = cfg.genre
    inicial = next((i for i, (k, _l) in enumerate(opcoes) if k == atual), 0)

    def detalhes(indice: int) -> list[str]:
        key = opcoes[indice][0]
        perfil = editorial.get(key)
        if perfil is None:
            return ["Sem perfil editorial."]
        p = perfil.pacing
        return [perfil.description,
                f"ritmo {p.target_scene_seconds:g}s/cena · "
                f"densidade {p.information_density} · "
                f"legenda {p.caption_max_words} palavras"]

    idx = select_option(
        c, "GÊNERO DO VÍDEO", [label for _key, label in opcoes],
        selected=inicial, details_for=detalhes, fit_labels=True,
        footer="↑ ↓ selecionar   Enter confirmar   Esc voltar")
    if idx is None:
        return cfg
    return dataclasses.replace(cfg, genre=opcoes[idx][0])


def _show_genre(c: dict[str, str], cfg: CurioConfig) -> None:
    from .stages import editorial
    perfil = editorial.get(cfg.genre)
    if perfil is None:
        print(f"  Gênero: {c['dim']}(padrão — sem gênero){c['reset']}")
        return
    p = perfil.pacing
    print(f"  Gênero: {c['bold']}{perfil.label}{c['reset']}")
    print(f"    ritmo {p.target_scene_seconds:g}s/cena · "
          f"densidade {p.information_density} · "
          f"legenda {p.caption_max_words} palavras")


def _ai_flow(c: dict[str, str], cfg: CurioConfig,
             idea: str | None = None, slug: str | None = None,
             force: bool = False) -> None:
    print(f"\n{c['bold']}VÍDEO PRONTO — voz de IA, você sai com o MP4 final.{c['reset']}")
    if idea is None:
        cfg = _ask_genre(c, cfg)
        lang_idx = select_option(
            c, "Idioma do vídeo",
            ["Português (PT-BR)", "English (EN-US) — 100% in English"],
            status=[f"atual: {cfg.language}"])
        if lang_idx is not None:
            cfg = _apply_language(cfg, "en-US" if lang_idx == 1 else "pt-BR")
        prompt = ("Video idea (e.g.: How does fiber internet cross the ocean?): "
                  if str(cfg.language).lower().startswith("en") else
                  "Ideia do vídeo (ex.: De onde veio a palavra salário?): ")
        idea = _ask(prompt).strip()
        if not idea:
            print("Ideia vazia — voltando ao menu.")
            return
        slug = slugify_with_timestamp(idea)
        print(f"Pasta do projeto: {project_dir(cfg.out_dir, cfg.genre, slug)}/   "
              f"idioma: {cfg.language}   gênero: {cfg.genre or 'padrão'}")
        cfg = _ask_duration(c, cfg)
        force = _ask("Refazer etapas já concluídas? [s/N]: ").strip().lower().startswith("s")
    try:
        meta = run_pipeline(idea, cfg, slug=slug, force=force,
                            narration="ai", on_progress=_progress,
                            on_event=_run_event)
    except KeyboardInterrupt:
        print("\nExecução interrompida. Consulte log em output/[<genero>/]<slug>/logs/.")
        return
    except MediaStandby as exc:
        _show_standby(c, exc)
        return
    except Exception as exc:  # noqa: BLE001 — TUI exibe erro e volta ao menu
        from .runlog import safe_text
        print(f"\n{c['red']}ERRO: {safe_text(exc)[:500]}{c['reset']}")
        print("O que já estava pronto foi preservado — tente de novo.")
        return
    print(f"\n{c['green']}Pronto!{c['reset']} Vídeo final: {meta['artifacts']['video']} "
          f"({meta['duration_actual']}s em {meta['processing_time_seconds']}s)")
    _show_sources(c, meta)
    _show_verify(c, meta["artifacts"]["video"], meta["artifacts"]["subtitles"], cfg)


def _quick_test_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    print(f"\n{c['bold']}Teste rápido:{c['reset']} gera o vídeo-exemplo "
          f"{c['yellow']}{QUICK_TEST_IDEA!r}{c['reset']} do zero e verifica tudo.")
    ok = _ask("Continuar? [S/n]: ").strip().lower()
    if ok not in ("", "s", "y", "sim"):
        return
    _ai_flow(c, cfg, idea=QUICK_TEST_IDEA, slug=QUICK_TEST_SLUG, force=True)


# ------------------------------------------------------- fluxo B (humano)

def _human_step1(c: dict[str, str], cfg: CurioConfig) -> str | None:
    print(f"\n{c['bold']}PASSO 1 de 2 — preparar a base (SEM vídeo final ainda).{c['reset']}")
    print("Isso gera: vídeo silencioso + teleprompter para você ler gravando.")
    idea = _ask("Ideia do vídeo (ex.: De onde veio a palavra salário?): ").strip()
    if not idea:
        print("Ideia vazia — voltando ao menu.")
        return None
    slug = slugify_with_timestamp(idea)
    print(f"Pasta do projeto: {project_dir(cfg.out_dir, cfg.genre, slug)}/")
    cfg = _ask_duration(c, cfg)
    try:
        meta = run_pipeline(idea, cfg, slug=slug, force=False,
                            narration="human", on_progress=_progress,
                            on_event=_run_event)
    except KeyboardInterrupt:
        print("\nExecução interrompida. Consulte log em output/[<genero>/]<slug>/logs/.")
        return None
    except MediaStandby as exc:
        _show_standby(c, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        from .runlog import safe_text
        print(f"\n{c['red']}ERRO: {safe_text(exc)[:500]}{c['reset']}")
        print("O que já estava pronto foi preservado — tente de novo.")
        return None
    print(f"\n{c['green']}Base pronta!{c['reset']} (repare: ainda NÃO há vídeo final)")
    print(f"  1. Assista e leia: {meta['artifacts']['teleprompter']}")
    print(f"  2. Grave sua voz (~{meta['duration_actual']}s) com qualquer gravador")
    print(f"  3. Volte aqui → opção 'Passo 2: finalizar com minha voz'")
    from .openers import open_after_teleprompter
    if _ask("\nAbrir a pasta do teleprompter + gravador agora? [S/n]: "
            ).strip().lower() in ("", "s", "y", "sim"):
        for msg in open_after_teleprompter(
                cfg, os.path.dirname(meta['artifacts']['teleprompter']),
                force=True):
            print(f"  {msg}")
    return slug


def _human_step2(c: dict[str, str], cfg: CurioConfig,
                 slug: str | None = None) -> None:
    from .cli import _final_progress
    from .pipeline import finalize_project
    print(f"\n{c['bold']}PASSO 2 de 2 — finalizar com a sua voz (gera o MP4 final).{c['reset']}")
    if slug is None:
        slug = _ask("Projeto (slug da pasta em output/): ").strip()
    if not slug:
        return
    status, _meta = _project_status(cfg, slug)
    if "aguardando sua voz" not in status and "final" not in status:
        print(f"{c['red']}Projeto '{slug}': {status}.{c['reset']}")
        print("Rode o passo 1 antes (opção 'Passo 1: preparar a base').")
        return
    audio = _ask("Arquivo de áudio com sua voz (wav/mp3): ").strip()
    if not audio:
        return
    try:
        meta = finalize_project(slug, os.path.expanduser(audio), cfg,
                                on_progress=_final_progress,
                                on_event=_run_event)
    except KeyboardInterrupt:
        print("\nFinalização interrompida. Consulte log em output/[<genero>/]<slug>/logs/.")
        return
    except Exception as exc:  # noqa: BLE001
        from .runlog import safe_text
        print(f"\n{c['red']}ERRO: {safe_text(exc)[:500]}{c['reset']}")
        return
    print(f"\n{c['green']}Pronto!{c['reset']} Vídeo final: {meta['artifacts']['video']} "
          f"({meta['duration_actual']}s)")
    for w in meta.get("finalize_warnings", []):
        print(f"{c['yellow']}AVISO: {w}{c['reset']}")
    _show_verify(c, meta["artifacts"]["video"], meta["artifacts"].get(
        "subtitles") or _fallback_subs(cfg, slug),
        cfg)


def _fallback_subs(cfg: CurioConfig, slug: str) -> str:
    """subs.srt do projeto, no layout novo ou legado (só p/ fallback)."""
    try:
        _, paths = _paths_for_slug(cfg.out_dir, slug)
        return paths.subs_srt
    except FileNotFoundError:
        return os.path.join(cfg.out_dir, slug, "subtitles", "subs.srt")


def _human_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    slug = _human_step1(c, cfg)
    if slug is None:
        return
    if _ask("\nJá tem o áudio gravado e quer finalizar AGORA? [s/N]: "
            ).strip().lower().startswith("s"):
        _human_step2(c, cfg, slug=slug)
    else:
        print("Sem pressa: quando gravar, volte → 'Passo 2: finalizar com minha voz'.")


# ------------------------------------------------------- roteiro pronto

SCRIPT_INPUT_TERMINATOR = "<<FIM_DO_ROTEIRO>>"


def _read_multiline_script() -> str:
    """Read pasted narration until the explicit marker; preserve all other lines."""
    print("Cole abaixo o roteiro completo. O texto será usado como narração e "
          "o Curio cuidará das próximas etapas.")
    print(f"Finalize digitando {SCRIPT_INPUT_TERMINATOR} em uma linha isolada.")
    lines = []
    while True:
        line = _ask("| ")
        if line == SCRIPT_INPUT_TERMINATOR:
            return "\n".join(lines)
        lines.append(line)


def _script_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    from .pipeline import run_script_pipeline
    print(f"\n{c['bold']}ROTEIRO PRONTO{c['reset']}")
    script_text = _read_multiline_script()
    if not script_text.strip():
        print(f"{c['red']}ERRO: roteiro vazio — cole a narração completa.{c['reset']}")
        return
    print(f"Roteiro recebido: {len(script_text)} caracteres, "
          f"{len(script_text.split())} palavras.")
    nar = _ask("Narração: [1] voz de IA (vídeo final) / [2] eu mesmo (2 passos)? [1]: "
               ).strip()
    narration = "human" if nar == "2" else "ai"
    cfg = _ask_duration(c, cfg)
    raw_max = _ask(f"Fotos por cena com sobreposição [1-5, padrão "
                   f"{cfg.visual_max_images}]: ").strip()
    if raw_max:
        try:
            import dataclasses
            cfg = dataclasses.replace(
                cfg, visual_max_images=max(1, min(5, int(raw_max))))
        except ValueError:
            print("Valor inválido — mantendo o padrão.")
    try:
        meta = run_script_pipeline(script_text, cfg, narration=narration,
                                   on_progress=_progress,
                                   on_event=_run_event)
    except KeyboardInterrupt:
        print("\nExecução interrompida. Consulte log em output/[<genero>/]<slug>/logs/.")
        return
    except MediaStandby as exc:
        _show_standby(c, exc)
        return
    except Exception as exc:  # noqa: BLE001 — TUI exibe erro e volta ao menu
        from .runlog import safe_text
        print(f"\n{c['red']}ERRO: {safe_text(exc)[:500]}{c['reset']}")
        print("O que já estava pronto foi preservado — tente de novo.")
        return
    if narration == "human":
        print(f"\n{c['green']}Base pronta!{c['reset']} (repare: ainda NÃO há vídeo final)")
        print(f"  1. Assista e leia: {meta['artifacts']['teleprompter']}")
        print(f"  2. Grave sua voz (~{meta['duration_actual']}s) com qualquer gravador")
        print(f"  3. Volte aqui → opção 'Passo 2: finalizar com minha voz'")
        print("Sem pressa: quando gravar, volte → 'Passo 2: finalizar com minha voz'.")
        return
    print(f"\n{c['green']}Pronto!{c['reset']} Vídeo final: {meta['artifacts']['video']} "
          f"({meta['duration_actual']}s em {meta['processing_time_seconds']}s)")
    _show_sources(c, meta)
    _show_verify(c, meta["artifacts"]["video"], meta["artifacts"]["subtitles"], cfg)


# ------------------------------------------------------- projetos

def _verify_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    slug = _ask("Projeto (slug da pasta em output/): ").strip()
    if not slug:
        return
    status, _meta = _project_status(cfg, slug)
    if "aguardando sua voz" in status:
        print(f"'{slug}' ainda não tem vídeo final — finalize primeiro "
              f"(opção 'Passo 2: finalizar com minha voz').")
        return
    try:
        _, paths = _paths_for_slug(cfg.out_dir, slug)
    except FileNotFoundError:
        print(f"{c['red']}Projeto '{slug}': {status}; sem MP4 final.{c['reset']}")
        return
    if not os.path.isfile(paths.final_mp4):
        print(f"{c['red']}Projeto '{slug}': {status}; sem MP4 final.{c['reset']}")
        return
    _show_verify(c, paths.final_mp4, paths.subs_srt, cfg)


# ------------------------------------------------------- projetos (navegável)

def _projects_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    while True:
        if not os.path.isdir(cfg.out_dir):
            print("Nenhum projeto ainda — comece por 'Criar vídeo'.")
            _pause(c)
            return
        entries = [ref for ref, _root in iter_projects(cfg.out_dir)]
        if not entries:
            print("Nenhum projeto ainda — comece por 'Criar vídeo'.")
            _pause(c)
            return
        labels = []
        for entry in entries:
            status, _meta = _project_status(cfg, entry)
            if "STANDBY" in status:
                mark = "◷"
            else:
                mark = "○" if "aguardando" in status else "●"
            labels.append(f"{mark} {entry} — {status}")
        labels.append("Voltar")
        idx = select_option(c, "Projetos", labels, status=_status_summary(cfg))
        if idx is None or idx == len(labels) - 1:
            return
        slug = entries[idx]
        act = select_option(
            c, f"Projeto: {slug}",
            ["Verificar vídeo", "Ver detalhes", "Apagar projeto", "Voltar"])
        if act is None or act == 3:
            continue
        if act == 0:
            _verify_project(c, cfg, slug)
            _pause(c)
        elif act == 1:
            _show_project(c, cfg, slug)
            _pause(c)
        elif act == 2:
            _delete_project(c, cfg, slug)
            _pause(c)


def _verify_project(c: dict[str, str], cfg: CurioConfig, slug: str) -> None:
    status, _meta = _project_status(cfg, slug)
    if "aguardando sua voz" in status:
        print(f"'{slug}' ainda não tem vídeo final — finalize primeiro.")
        return
    try:
        _, paths = _paths_for_slug(cfg.out_dir, slug)
    except FileNotFoundError:
        print(f"{c['red']}Projeto '{slug}': {status}; sem MP4 final.{c['reset']}")
        return
    if not os.path.isfile(paths.final_mp4):
        print(f"{c['red']}Projeto '{slug}': {status}; sem MP4 final.{c['reset']}")
        return
    _show_verify(c, paths.final_mp4, paths.subs_srt, cfg)


def _show_project(c: dict[str, str], cfg: CurioConfig, slug: str) -> None:
    status, meta = _project_status(cfg, slug)
    print(f"\n{c['bold']}{slug}{c['reset']}: {status}")
    if not meta:
        return
    for key in ("video_title", "duration_actual", "tts_provider", "tts_voice",
                "render_encoder", "subtitle_cues", "processing_time_seconds"):
        if meta.get(key) is not None:
            print(f"  {key}: {meta.get(key)}")
    arts = meta.get("artifacts", {}) or {}
    for key in ("video", "subtitles", "audio"):
        if arts.get(key):
            print(f"  {key}: {arts.get(key)}")


def _delete_project(c: dict[str, str], cfg: CurioConfig, slug: str) -> None:
    try:
        _, paths = _paths_for_slug(cfg.out_dir, slug)
    except FileNotFoundError:
        print(f"{c['red']}Projeto '{slug}' não encontrado.{c['reset']}")
        return
    proj_path = paths.root
    if _confirm_twice(f"Apagar projeto '{slug}'?", slug.upper()):
        try:
            shutil.rmtree(proj_path)
            print(f"{c['green']}Projeto removido.{c['reset']}")
        except Exception as exc:
            print(f"{c['red']}Erro: {exc}{c['reset']}")
    else:
        print("Cancelado.")


# ------------------------------------------------------- menu

def run(cfg: CurioConfig | None = None) -> int:
    cfg = cfg or CurioConfig.load()
    c = _colors()
    try:
        while True:
            idx = select_option(
                c, "O que você quer fazer?",
                ["Criar vídeo",
                 "Narrar eu mesmo (2 passos)",
                 "Roteiro pronto (colar narração)",
                 "Fila de ideias",
                 "Projetos",
                 "Configurações",
                 "Diagnóstico",
                 "Ajuda",
                 "Sair"],
                status=_status_summary(cfg))
            if idx is None or idx == 8:
                print("Até logo!")
                return 0
            if idx == 0:
                sub = select_option(
                    c, "Criar vídeo",
                    ["Voz de IA (MP4 final)",
                     "Passo 1: preparar base (silencioso + teleprompter)",
                     "Passo 2: finalizar com minha voz",
                     "Teste rápido",
                     "Voltar"],
                    status=_status_summary(cfg))
                if sub is None or sub == 4:
                    continue
                if sub == 0:
                    _ai_flow(c, cfg)
                elif sub == 1:
                    _human_flow(c, cfg)
                elif sub == 2:
                    _human_step2(c, cfg)
                elif sub == 3:
                    _quick_test_flow(c, cfg)
            elif idx == 1:
                _human_flow(c, cfg)
            elif idx == 2:
                _script_flow(c, cfg)
            elif idx == 3:
                _queue_flow(c, cfg)
            elif idx == 4:
                _projects_flow(c, cfg)
            elif idx == 5:
                cfg = _config_flow(c, cfg)
            elif idx == 6:
                sub = select_option(
                    c, "Diagnóstico",
                    ["Checar ambiente (doctor)",
                     "Verificar um vídeo",
                     "Ver tamanhos (cache/output)",
                     "Limpeza e manutenção",
                     "Voltar"],
                    status=_status_summary(cfg))
                if sub is None or sub == 4:
                    continue
                if sub == 0:
                    from .cli import cmd_doctor
                    cmd_doctor(argparse.Namespace(), cfg)
                elif sub == 1:
                    _verify_flow(c, cfg)
                elif sub == 2:
                    _show_sizes(c, cfg)
                elif sub == 3:
                    _cleanup_flow(c, cfg)
            elif idx == 7:
                _help_flow(c)
            _pause(c)
    except _TUIExit:
        print("\nAté logo!")
        return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
