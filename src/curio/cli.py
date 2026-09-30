"""Interface CLI (PRD §14)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from . import __version__
from . import ffmpeg as ff
from . import queue as queue_mod
from . import verify as verify_mod
from .config import CurioConfig, parse_duration
from .metrics import backfill_from_metadata
from .pipeline import (MediaStandby, _build_silent, _build_silent_visual,
                        _narration_with_sfx, _read, _read_json, _sfx_track_for,
                        _write_json, finalize_project, run_pipeline,
                        run_script_pipeline, video_paths)
from .stages.scenes import Chapter
from .slug import slugify, slugify_with_timestamp
from .stages import nvidia as nvidia_stage
from .stages import research as research_stage
from .stages import transcribe as transcribe_stage
from .stages import tts as tts_stage
from .stages import media_rules
from .stages import scoring as scoring_stage
from .stages import visual as visual_stage


def _progress(idx: int, total: int, label: str, status: str) -> None:
    print(f"[{idx}/{total}] {label}... {status}", flush=True)


def _standby_exit(exc: MediaStandby) -> int:
    """Projeto sem imagens: instruções de retomada (código 3, não é erro)."""
    print(f"\nSTANDBY: {exc}", file=sys.stderr)
    print(f"  1) Coloque fotos (.jpg/.png/.webp) em:\n     {exc.manual_dir}",
          file=sys.stderr)
    print(f"  2) Rode de novo (sem --force) para continuar o vídeo.",
          file=sys.stderr)
    return 3


def _fail(stage: str, exc: BaseException, hint: str = "") -> int:
    print(f"\nERRO na etapa '{stage}': {exc}", file=sys.stderr)
    if hint:
        print(f"Motivo provável: {hint}", file=sys.stderr)
    print("Dica: artefatos anteriores foram preservados — corrija e rode de novo "
          "sem --force para reaproveitá-los.", file=sys.stderr)
    return 1


def _apply_duration(args, cfg: CurioConfig) -> int:
    """Aplica --duration (meta, nunca corte). Retorna 0 ou código de erro."""
    if getattr(args, "duration", None) is None:
        return 0
    try:
        cfg.duration_target = parse_duration(args.duration)
    except ValueError as exc:
        print(f"Duração inválida: {exc}", file=sys.stderr)
        return 2
    if cfg.duration_target <= 0:
        print("Duração: automática (o conteúdo manda).")
    else:
        print(f"Duração-alvo: {cfg.duration_target:.0f}s (meta, sem corte).")
    return 0


def _duration_suffix(meta: dict) -> str:
    target = float(meta.get("duration_target", 0) or 0)
    if target <= 0:
        return "modo auto"
    return f"meta: {target:.0f}s"


def cmd_generate(args, cfg: CurioConfig) -> int:
    idea = " ".join(args.idea).strip()
    narration = getattr(args, "narration", "ai")
    rc = _apply_duration(args, cfg)
    if rc:
        return rc
    if narration not in ("ai", "human"):
        print("Narração deve ser 'ai' ou 'human'.", file=sys.stderr)
        return 2
    try:
        meta = run_pipeline(idea, cfg, slug=args.slug, force=args.force,
                            narration=narration, on_progress=_progress)
    except MediaStandby as exc:
        return _standby_exit(exc)
    except research_stage.ResearchError as exc:
        return _fail("pesquisa", exc, "sem fonte real não há roteiro; "
                                      "verifique a rede ou reformule a ideia.")
    except ValueError as exc:
        return _fail("roteiro", exc, "ideia vazia ou inválida.")
    except nvidia_stage.NvidiaError as exc:
        return _fail("LLM", exc, "tentativas esgotadas na NVIDIA e no fallback; "
                                 "verifique chaves/modelos (`video-gen doctor`), "
                                 "rede e limites das contas; "
                                 "sem chave, o gerador local é usado; "
                                 "com roteiro em cache, rode de novo para reaproveitá-lo.")
    except tts_stage.TTSError as exc:
        return _fail("narração", exc, "verifique espeak-ng (`video-gen doctor`).")
    except ff.FFMpegError as exc:
        return _fail("montagem", exc, "verifique ffmpeg/VA-API (`video-gen doctor`).")
    except Exception as exc:  # noqa: BLE001 — CLI deve exibir erro amigável
        traceback.print_exc()
        return _fail("pipeline", exc, "erro inesperado; veja o traceback acima.")
    if narration == "human":
        print(f"\nSilencioso: {meta['artifacts']['silent']}")
        print(f"Teleprompter: {meta['artifacts']['teleprompter']}")
        if not getattr(args, "no_open", False):
            from .openers import open_after_teleprompter
            for msg in open_after_teleprompter(
                    cfg, os.path.dirname(meta['artifacts']['teleprompter'])):
                print(msg)
        print(f"Grave sua voz e rode:\n"
              f"  video-gen finalize {meta['slug']} --audio minha-voz.wav")
        return 0
    print(f"\nOutput: {meta['artifacts']['video']}")
    print(f"Duração: {meta['duration_actual']}s ({_duration_suffix(meta)}) | "
          f"TTS: {meta['tts_provider']} | render: {meta['render_encoder']} | "
          f"tempo: {meta['processing_time_seconds']}s")
    _print_sources(meta)
    return 0


def _print_sources(meta: dict) -> None:
    research = meta.get("research") or {}
    n = int(research.get("sources") or 0)
    titles = [t for t in (research.get("titles") or []) if t][:3]
    extra = f" ({'; '.join(titles)})" if titles else ""
    print(f"Fontes: {n} [{research.get('status', '?')}]" + extra)
    print(f"[finalize] {label}... {status}", flush=True)


def cmd_from_script(args, cfg: CurioConfig) -> int:
    """Modo roteiro-pronto: organiza mídia sobre narração existente."""
    narration = getattr(args, "narration", "ai")
    if narration not in ("ai", "human"):
        print("Narração deve ser 'ai' ou 'human'.", file=sys.stderr)
        return 2
    rc = _apply_duration(args, cfg)
    if rc:
        return rc
    max_images = getattr(args, "max_images", None)
    if max_images is not None:
        cfg.visual_max_images = max(1, min(5, int(max_images)))
    insertions = getattr(args, "insertions", None)
    if insertions is not None:
        cfg.visual_insertions = max(0, min(5, int(insertions)))
    try:
        script_text = visual_stage.read_script_file(args.script)
    except (FileNotFoundError, ValueError) as exc:
        return _fail("roteiro", exc, "arquivo de roteiro inválido.")
    try:
        meta = run_script_pipeline(
            script_text, cfg, title=getattr(args, "title", None),
            slug=args.slug, force=args.force, narration=narration,
            on_progress=_progress)
    except MediaStandby as exc:
        return _standby_exit(exc)
    except research_stage.ResearchError as exc:
        return _fail("pesquisa", exc, "sem fonte real não há vídeo; "
                                      "verifique a rede ou reformule o tema.")
    except ValueError as exc:
        return _fail("roteiro", exc, "roteiro vazio ou divisão inválida.")
    except nvidia_stage.NvidiaError as exc:
        return _fail("LLM", exc, "tentativas esgotadas na NVIDIA e no fallback; "
                                 "verifique chaves/modelos (`video-gen doctor`); "
                                 "sem chave, a divisão local é usada.")
    except tts_stage.TTSError as exc:
        return _fail("narração", exc, "verifique espeak-ng (`video-gen doctor`).")
    except ff.FFMpegError as exc:
        return _fail("montagem", exc, "verifique ffmpeg/VA-API (`video-gen doctor`).")
    except Exception as exc:  # noqa: BLE001 — CLI deve exibir erro amigável
        traceback.print_exc()
        return _fail("pipeline", exc, "erro inesperado; veja o traceback acima.")
    if narration == "human":
        print(f"\nSilencioso: {meta['artifacts']['silent']}")
        print(f"Teleprompter: {meta['artifacts']['teleprompter']}")
        if not getattr(args, "no_open", False):
            from .openers import open_after_teleprompter
            for msg in open_after_teleprompter(
                    cfg, os.path.dirname(meta['artifacts']['teleprompter'])):
                print(msg)
        print(f"Grave sua voz e rode:\n"
              f"  video-gen finalize {meta['slug']} --audio minha-voz.wav")
        return 0
    print(f"\nOutput: {meta['artifacts']['video']}")
    print(f"Duração: {meta['duration_actual']}s ({_duration_suffix(meta)}) | "
          f"TTS: {meta['tts_provider']} | render: {meta['render_encoder']} | "
          f"tempo: {meta['processing_time_seconds']}s")
    _print_sources(meta)
    return 0


def cmd_sources(args, cfg: CurioConfig) -> int:
    """Gerencia o registro de fontes de um projeto."""
    from .stages import sources as sources_stage
    paths = video_paths(cfg.out_dir, args.slug)
    reg = sources_stage.SourceRegistry.load(paths.sources_json)
    reg.slug = args.slug
    if getattr(args, "add", None):
        src = reg.add_claim(
            claim=args.add, title=args.title, url=args.url,
            evidence=args.evidence or "", author=args.author or "",
            date=args.date or "", status=args.status or "confirmed",
            notes=args.notes or "")
        reg.save(paths.sources_json)
        print(f"Fonte registrada: {src.title} ({src.status})")
        return 0
    if not os.path.isfile(paths.sources_json):
        print(f"Projeto '{args.slug}' ainda não tem fontes registradas.")
        return 0
    print(f"Fontes de {args.slug}:")
    print(f"  Afirmações factuais: {len(reg.claims)}")
    for c in reg.claims:
        mark = {"confirmed": "OK", "partial": "~", "contested": "!",
                "unverified": "?"}.get(c.status, "?")
        print(f"    [{mark}] {c.claim}")
        print(f"        {c.title} — {c.url}")
        if c.evidence:
            print(f"        evidência: {c.evidence[:120]}")
    print(f"  Mídias: {len(reg.media)}")
    for m in reg.media:
        print(f"    - {m.title} ({m.provider}) — {m.origin_url}")
    return 0


def cmd_finalize(args, cfg: CurioConfig) -> int:
    try:
        meta = finalize_project(args.slug, args.audio, cfg,
                                force=args.force, on_progress=_final_progress)
    except FileNotFoundError as exc:
        return _fail("finalize", exc, "projeto ou áudio não encontrado.")
    except ValueError as exc:
        return _fail("finalize", exc, "áudio inválido.")
    except transcribe_stage.TranscribeError as exc:
        return _fail("transcrição", exc, "instale faster-whisper "
                                        "(`scripts/install.sh`).")
    except ff.FFMpegError as exc:
        return _fail("montagem", exc, "verifique ffmpeg/VA-API (`video-gen doctor`).")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return _fail("finalize", exc, "erro inesperado; veja o traceback acima.")
    print(f"\nOutput: {meta['artifacts']['video']}")
    print(f"Duração: {meta['duration_actual']}s | legendas: "
          f"{meta['subtitle_cues']} blocos ({meta['subtitle_source']})")
    for w in meta.get("finalize_warnings", []):
        print(f"AVISO: {w}")
    return 0


def cmd_list(args, cfg: CurioConfig) -> int:
    if not os.path.isdir(cfg.out_dir):
        print(f"Nenhum vídeo ainda (diretório {cfg.out_dir}/ não existe).")
        return 0
    found = 0
    for entry in sorted(os.listdir(cfg.out_dir)):
        meta_path = os.path.join(cfg.out_dir, entry, "metadata.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        except json.JSONDecodeError:
            continue
        found += 1
        print(f"- {entry}: {meta.get('title', '?')} "
              f"({meta.get('duration_actual', '?')}s, {meta.get('created_at', '?')})")
    if not found:
        print("Nenhum vídeo encontrado.")
    return 0


def cmd_info(args, cfg: CurioConfig) -> int:
    slug = args.slug or slugify(" ".join(args.idea)) if args.idea else args.slug
    if not slug:
        print("Informe --slug ou a ideia.", file=sys.stderr)
        return 2
    meta_path = os.path.join(cfg.out_dir, slug, "metadata.json")
    if not os.path.isfile(meta_path):
        print(f"Vídeo '{slug}' não encontrado em {cfg.out_dir}/.", file=sys.stderr)
        return 1
    with open(meta_path, encoding="utf-8") as fh:
        print(json.dumps(json.load(fh), ensure_ascii=False, indent=2))
    return 0


def cmd_review(args, cfg: CurioConfig) -> int:
    """Abre a folha de contato, ou imprime a decisão por cena (--dry-run)."""
    from .stages import review as review_stage
    from .stages import scoring as scoring_stage
    slug = args.slug
    paths = video_paths(cfg.out_dir, slug)
    if not os.path.isfile(paths.chapters_json):
        print(f"Projeto '{slug}' incompleto ({paths.chapters_json} ausente).",
              file=sys.stderr)
        return 1
    chapters = [Chapter.from_dict(d) for d in _read_json(paths.chapters_json)]
    media = _read_json(paths.media_json) if os.path.isfile(paths.media_json) else []
    # O gênero vive no metadata.json, escrito na geração. Um projeto
    # antigo não tem a chave: aí não há gênero para mostrar, e a revisão
    # sai igual à de antes.
    _meta = _read_json(paths.metadata_json) if os.path.isfile(
        paths.metadata_json) else {}
    genre = str(_meta.get("genre") or "")
    if args.dry_run:
        print(review_stage.dry_run_text(
            chapters, media, threshold=scoring_stage.threshold(),
            genre=genre, typography=_meta.get("typography")))
        return 0
    out = review_stage.write_contact_sheet(
        paths.contact_sheet, chapters, media, paths.root, slug,
        threshold=scoring_stage.threshold(), genre=genre,
        typography=_meta.get("typography"))
    print(f"Folha de contato: {out}")
    return 0


def cmd_swap(args, cfg: CurioConfig) -> int:
    """Troca a imagem de uma cena por outra, sem refazer narração.

    A escolha é sempre entre candidatos JÁ baixados e avaliados (o pick é o
    índice na lista da cena). Assim o swap é instantâneo e não volta à
    rede nem re-sintetiza áudio — que é o ponto: revisar um vídeo não pode
    custar uma nova geração de voz.
    """
    from .stages import visual as visual_stage
    paths = video_paths(cfg.out_dir, args.slug)
    if not os.path.isfile(paths.media_json):
        print(f"Projeto '{args.slug}' sem media.json — rode o generate antes.",
              file=sys.stderr)
        return 1
    media = _read_json(paths.media_json)
    target = next((s for s in media if s.get("chapter_id") == args.scene), None)
    if target is None:
        print(f"Cena {args.scene} não existe no projeto.", file=sys.stderr)
        return 1
    entries = target.get("assets") or []
    if not entries:
        print(f"Cena {args.scene} não tem imagens escolhidas para trocar.",
              file=sys.stderr)
        return 1
    if not 0 <= args.pick < len(entries):
        print(f"--pick fora da faixa: a cena tem {len(entries)} imagem(ns) "
              f"(0..{len(entries) - 1}).", file=sys.stderr)
        return 1
    entry = entries[args.pick]
    asset = entry.get("asset") or {}
    if not asset.get("local_path") or not os.path.isfile(asset["local_path"]):
        print("A imagem escolhida não está em disco — refaça a etapa de mídia.",
              file=sys.stderr)
        return 1
    # Reordena: a escolhida vai para order 0 e é a única visível da cena.
    previous_id = ((target.get("asset") or {}).get("asset_id") or "")
    others = [e for i, e in enumerate(entries) if i != args.pick]
    novo = dict(entry)
    novo["order"] = 0
    target["assets"] = [novo] + [dict(e, order=i + 1)
                                 for i, e in enumerate(others)]
    target["asset"] = asset
    if previous_id and previous_id != asset.get("asset_id"):
        target["swapped_from"] = previous_id
    with open(paths.media_json, "w", encoding="utf-8") as fh:
        json.dump(media, fh, ensure_ascii=False, indent=1)
    print(f"Cena {args.scene}: agora usa "
          f"'{asset.get('title', '')[:70]}' ({asset.get('provider', '?')}).")
    print(f"Rode `video-gen rerender --slug {args.slug}` para aplicar.")
    return 0


def cmd_rerender(args, cfg: CurioConfig) -> int:
    """Refaz só o que mudou: visual, legendas queimadas, MP4.

    Narração, transcrição, roteiro e pesquisa ficam em cache e não são
    refeitos — trocar uma imagem não pode custar uma nova voz.
    """
    from .stages import render as render_stage
    from .stages import subs as subs_stage
    paths = video_paths(cfg.out_dir, args.slug)
    for need, dica in ((paths.chapters_json, "rode o generate"),
                       (paths.media_json, "rode o generate"),
                       (paths.narration_wav, "rode o generate")):
        if not os.path.isfile(need):
            print(f"Falta {os.path.basename(need)} em {paths.root}/ — {dica}.",
                  file=sys.stderr)
            return 1
    if not os.path.isfile(paths.timeline_json):
        print(f"Falta timeline.json em {paths.root}/ — rode o generate.",
              file=sys.stderr)
        return 1

    chapters = [Chapter.from_dict(d) for d in _read_json(paths.chapters_json)]
    media = _read_json(paths.media_json)
    audio_duration = ff.probe_duration(paths.narration_wav)

    visual_timeline = None
    if os.path.isfile(paths.visual_json):
        try:
            visual_timeline = _read_json(paths.visual_json)
        except json.JSONDecodeError:
            visual_timeline = None
    if visual_timeline is not None:
        # Replaneja só a geometria: as imagens podem ter mudado de ordem.
        visual_timeline = visual_stage.rebuild_visual_timeline(
            chapters, media, visual_timeline, cfg)
        _write_json(paths.visual_json, visual_timeline)

    if visual_timeline:
        _build_silent_visual(chapters, visual_timeline, args.slug, cfg,
                             paths, paths.silent_mp4)
    else:
        durations = [max(0.5, c.end - c.start) for c in chapters]
        _build_silent(chapters, media, args.slug, durations, paths, cfg,
                      paths.silent_mp4)

    total = round(audio_duration + 0.8, 2)
    wav = paths.narration_wav
    if visual_timeline and cfg.visual_sfx:
        sfx = _sfx_track_for(visual_timeline, total, paths)
        if sfx:
            wav = _narration_with_sfx(paths.narration_wav, sfx, total, paths)
    title = None
    if os.path.isfile(paths.title_txt):
        title = _read(paths.title_txt).strip() or None
    info = render_stage.burn_final(
        paths.silent_mp4, paths.subs_ass, wav, paths.final_mp4, cfg, total,
        title=title,
        title_fontfile=subs_stage.ensure_display_font(cfg.cache_dir)[2])
    print(f"Refeito: {info['path']} ({info['duration']}s, {info['encoder']})")
    print("Narração, roteiro e legendas vieram do cache — não foram refeitos.")
    return 0


def cmd_verify(args, cfg: CurioConfig) -> int:
    slug = args.slug
    paths = video_paths(cfg.out_dir, slug)
    if not os.path.isfile(paths.final_mp4):
        print(f"Vídeo '{slug}' não encontrado em {cfg.out_dir}/.", file=sys.stderr)
        return 1
    # A meta de duração é a do projeto (metadata), não a config atual.
    target = cfg.duration_target
    try:
        with open(paths.metadata_json, encoding="utf-8") as fh:
            target = float(json.load(fh).get("duration_target", target))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    rep = verify_mod.verify_video(paths.final_mp4, paths.subs_srt,
                                  target, cfg.width, cfg.height)
    print(f"Verificação: {slug}\n{rep.render()}")
    return 0 if rep.success else 1


def cmd_metrics(args, cfg: CurioConfig) -> int:
    """Backfill: métricas a partir do metadata de projetos existentes."""
    if getattr(args, "slug", None):
        slugs = [args.slug]
    elif os.path.isdir(cfg.out_dir):
        slugs = sorted(d for d in os.listdir(cfg.out_dir)
                       if os.path.isfile(os.path.join(cfg.out_dir, d,
                                                      "metadata.json")))
    else:
        slugs = []
    if not slugs:
        print("Nenhum projeto com metadata.json.", file=sys.stderr)
        return 1
    for slug in slugs:
        meta_path = os.path.join(cfg.out_dir, slug, "metadata.json")
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"PULADO {slug}: {exc}", file=sys.stderr)
            continue
        path = backfill_from_metadata(slug, meta, cfg.metrics_dir)
        dur = meta.get("duration_actual", "?")
        print(f"{slug}: {dur}s → {path}")
    return 0


def cmd_voices(_args, _cfg) -> int:
    voices = tts_stage.available_providers()
    print("Provedores TTS disponíveis: " + (", ".join(voices) if voices else "nenhum"))
    return 0


def cmd_doctor(_args, cfg: CurioConfig) -> int:
    ok = True

    def check(name: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        print(f"[{'OK' if good else 'FALTA'}] {name}{(' — ' + detail) if detail else ''}")
        ok = ok and good

    import shutil
    check("python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0])
    check("ffmpeg", shutil.which("ffmpeg") is not None)
    check("ffprobe", shutil.which("ffprobe") is not None)
    check("espeak-ng (TTS local, fallback)", shutil.which("espeak-ng") is not None)
    import importlib.util
    has_edge = importlib.util.find_spec("edge_tts") is not None
    check("edge-tts (voz neural PT-BR masculina)", has_edge,
          "pt-BR-AntonioNeural" if has_edge else "pip install edge-tts (ou use espeak-ng)")
    check("filtro libass (legendas queimadas)",
          "libass" in (ff.run(["ffmpeg", "-hide_banner", "-h", "filter=subtitles"])
                       .stdout.lower()))
    dev = ff.intel_render_node()
    hw = ff.intel_hw_encoder()
    check("Intel Arc B580 (nó DRI)", dev is not None, dev or "sem GPU Intel")
    check("Encode HW Intel (VA-API)", hw is not None,
          f"{hw[1]} em {hw[0]}" if hw else "indisponível — render cai para CPU")
    dev_any = ff.vaapi_device()
    check("VA-API (qualquer GPU)", dev_any is not None, dev_any or "vai usar CPU (libx264)")
    check("fonte para título", ff.find_font_bold() is not None,
          ff.find_font_bold() or "título será omitido")
    # Informativo: ausência de chave NÃO falha o doctor (gerador local cobre).
    # A tipografia é configuração, não download: o doctor diz qual fonte
    # CADA papel vai usar e, quando não é a pedida, diz isso. Um vídeo que
    # saiu com a serifada errada sem ninguém avisar é pior do que um vídeo
    # que não saiu, e "Minion Pro não está instalada" é uma frase que o
    # autor precisa ler antes de montar 40 minutos de vídeo.
    from .stages import typography as typo_stage
    _perfil = typo_stage.profile_for(cfg.genre)
    if not cfg.genre:
        print("[--] Tipografia — sem gênero: fonte de exibição de sempre")
    else:
        _quedas = []
        for _papel in (typo_stage.ROLE_TITLE, typo_stage.ROLE_QUOTE,
                       typo_stage.ROLE_LATIN, typo_stage.ROLE_CAPTION):
            _r = typo_stage.resolve(_papel, cfg.genre,
                                    (cfg.typography or {}).get(cfg.genre))
            if _r.is_fallback and _r.requested:
                _quedas.append(f"{_papel}: {_r.requested} → {_r.family}")
        _detalhe = f"{_perfil.label} — {_perfil.direction}"
        print(f"[{'--' if _quedas else 'OK'}] Tipografia — {_detalhe}")
        for _q in _quedas:
            print(f"       fonte ausente, usando {_q}")
    from .ua import aviso_contato, user_agent
    _aviso_ua = aviso_contato()
    print(f"[{'OK' if not _aviso_ua else '--'}] User-Agent Wikimedia"
          f"{'' if not _aviso_ua else ' — ' + user_agent()}")
    if _aviso_ua:
        print(f"       {_aviso_ua}")
    # Chain LLM: NVIDIA → OpenRouter → Gemini → Groq (1º com chave tenta).
    _llm_models = {"nvidia": cfg.nvidia_model, "openrouter": cfg.openrouter_model,
                   "gemini": cfg.gemini_model, "groq": cfg.groq_model}
    for pid in nvidia_stage.PROVIDER_ORDER:
        spec = nvidia_stage.PROVIDER_SPECS[pid]
        creds = nvidia_stage.CREDENTIALS[pid].from_env()
        mark = "OK" if creds.available else "--"
        if creds.available:
            detail = f"chave configurada ({_llm_models[pid]})"
        else:
            detail = f"sem chave (pula no rodízio; defina {spec['key_envs'][0]})"
        if pid == "nvidia" and not creds.available:
            detail = "sem chave (roteiros locais)"
        print(f"[{mark}] {spec['display']} (LLM) — {detail}")
    has_fw = importlib.util.find_spec("faster_whisper") is not None
    print(f"[{'OK' if has_fw else '--'}] faster-whisper (transcrição local) "
          f"{'— ' + cfg.whisper_model if has_fw else '— finalize indisponível; pip install faster-whisper'}")
    from .media import providers as media_prov
    print(f"\nProvedores de mídia (configurado: {cfg.media_providers}):")
    # Lista um por um, com o motivo de cada um estar fora. Um resumo
    # "pixabay=OK, nasa/wikimedia/openverse sem chave" não diz o que
    # acontece com um provedor DESCONHECIDO no config, nem se a ordem
    # está efetiva — e a ordem é o que decide quem responde primeiro.
    ativos, motivos = media_prov.providers_status(cfg)
    for nome, status in ativos:
        print(f"[OK] {nome:<12} ativo")
    for nome, motivo in motivos:
        print(f"[--] {nome:<12} ignorado — {motivo}")
    if cfg.media_providers.strip().lower() == "none":
        print("[--] nenhum provedor: as cenas vão para diagrama/cartão "
              "(nenhuma foto será buscada)")
    print(f"[{'OK' if media_prov.check_connectivity() else '--'}] "
          f"rede — Wikipedia {'alcançável' if media_prov.check_connectivity() else 'inacessível'}")
    print(f"[--] seleção — mínimo de nota "
          f"{scoring_stage.threshold():.0f}/100 "
          f"(CURIO_MEDIA_SCORE_MIN), lado mínimo "
          f"{media_rules.min_dimension()}px "
          f"(CURIO_MEDIA_MIN_DIMENSION)")
    _clip = clip_status()
    if _clip is None:
        print("[--] scoring semântico (CLIP) — desligado; usando a camada base")
    else:
        print(f"[--] CLIP — {_clip}")
    print(f"\nConfig: out_dir={cfg.out_dir} tts={cfg.tts_provider}/{cfg.tts_voice} "
          f"backend={cfg.render_backend} nvidia_model={cfg.nvidia_model}")
    return 0 if ok else 1


def _queue_progress(queue: queue_mod.VideoQueue) -> None:
    os.system("clear" if os.name == "posix" else "cls")
    queue.print_status()


def cmd_queue(args, cfg: CurioConfig) -> int:
    """Processa uma fila de ideias de vídeos sequencialmente."""
    queue = queue_mod.VideoQueue()
    
    if args.file:
        queue.add_from_file(args.file)
    elif args.ideas:
        queue.add_from_list(args.ideas)
    
    if not queue.items:
        print("Nenhuma ideia fornecida. Use --file ou passe ideias como argumentos.", file=sys.stderr)
        return 2
    
    if args.save:
        queue.queue_file = args.save
        queue.save(args.save)
        print(f"Fila salva em {args.save}")
    
    if args.load:
        queue = queue_mod.VideoQueue.load(args.load)
    
    if args.list:
        queue.print_status()
        return 0
    
    if args.retry:
        count = queue_mod.retry_failed(queue)
        print(f"{count} itens com erro marcados para reprocessamento.")
        if queue.queue_file:
            queue.save(queue.queue_file)
        return 0
    
    if args.cancel_index is not None:
        if queue_mod.cancel_item(queue, args.cancel_index):
            print(f"Item {args.cancel_index} cancelado.")
        else:
            print(f"Não foi possível cancelar item {args.cancel_index}.")
        if queue.queue_file:
            queue.save(queue.queue_file)
        return 0
    
    if args.move:
        from_idx, to_idx = args.move
        if queue_mod.reorder_items(queue, from_idx, to_idx):
            print(f"Item {from_idx} movido para posição {to_idx}.")
        else:
            print("Não foi possível mover (apenas itens aguardando).")
        if queue.queue_file:
            queue.save(queue.queue_file)
        return 0
    
    # Processa a fila
    print(f"Iniciando processamento de {len(queue.items)} vídeos...")
    print(f"Saída: {cfg.out_dir}")
    print()
    
    def on_item_start(item):
        print(f"\n▶ [{item.slug}] {item.idea}")
    
    def on_item_complete(item, success):
        if success:
            print(f"✓ [{item.slug}] Concluído em {item.duration_seconds:.1f}s")
            if item.video_path:
                print(f"  Vídeo: {item.video_path}")
        else:
            print(f"✗ [{item.slug}] ERRO: {item.error}")
    
    queue_mod.process_queue(
        queue, cfg, cfg.out_dir,
        on_item_start=on_item_start,
        on_item_complete=on_item_complete,
        on_progress=_queue_progress if not args.no_progress else None,
    )
    
    if queue.queue_file:
        queue.save(queue.queue_file)
    
    print("\n" + "=" * 50)
    queue.print_status()
    
    # Retorna erro se algum item falhou
    errors = sum(1 for i in queue.items if i.status == queue_mod.QueueItemStatus.ERROR)
    return 1 if errors > 0 else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="video-gen",
                                 description="Máquina de Conteúdo Educativo em Vídeo (MVP)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--config", default=None, help="caminho do config.toml")
    ap.add_argument("--out-dir", default=None, help="sobrescreve diretório de saída")
    ap.add_argument("--tts", default=None, help="provedor TTS (ex.: espeak-ng)")
    ap.add_argument("--voice", default=None, help="voz TTS (ex.: pt-br)")
    ap.add_argument("--backend", default=None, help="arc|auto|vaapi|qsv|cpu")
    ap.add_argument("--language", default=None, help="idioma do vídeo: pt-BR ou en-US")
    ap.add_argument("--queues-dir", default=None, help="pasta padrão das filas de ideias")
    sub = ap.add_subparsers(dest="cmd", required=False)

    g = sub.add_parser("generate", help="gerar vídeo a partir de uma ideia")
    g.add_argument("idea", nargs="+", help="ideia textual entre aspas")
    g.add_argument("--slug", default=None, help="nome do diretório de saída")
    g.add_argument("--force", action="store_true", help="refazer todas as etapas")
    g.add_argument("--duration", default=None,
                   help="meta de duração (não corta): auto (padrão), 30, 45, "
                        "60, 90, 120, 180 ou segundos 5..600")
    g.add_argument("--narration", default="ai", choices=["ai", "human"],
                   help="ai = vídeo final com Edge TTS; human = silencioso + teleprompter")
    g.add_argument("--no-open", action="store_true",
                   help="não abrir pasta/gravador após o teleprompter")
    g.add_argument("--language", default=None, help="idioma do vídeo: pt-BR ou en-US")
    g.set_defaults(func=cmd_generate)

    fin = sub.add_parser("finalize", help="unir áudio humano ao vídeo silencioso")
    fin.add_argument("slug", help="projeto criado com --narration human")
    fin.add_argument("--audio", required=True, help="wav/mp3 com a narração humana")
    fin.add_argument("--force", action="store_true", help="retranscrever e refazer")
    fin.set_defaults(func=cmd_finalize)

    src = sub.add_parser("sources", help="gerenciar fontes de um projeto")
    src.add_argument("slug", help="nome do diretório do projeto")
    src.add_argument("--add", default=None,
                    help="afirmação factual a registrar (ou 'show' p/ listar)")
    src.add_argument("--title", default=None, help="título da fonte")
    src.add_argument("--url", default=None, help="URL completa da fonte")
    src.add_argument("--evidence", default=None,
                    help="trecho/evidência que sustenta a afirmação")
    src.add_argument("--author", default=None, help="autor ou instituição")
    src.add_argument("--date", default=None, help="data da fonte")
    src.add_argument("--status", default="confirmed",
                    choices=["confirmed", "partial", "contested", "unverified"])
    src.add_argument("--notes", default=None, help="observações")
    src.set_defaults(func=cmd_sources)

    fs = sub.add_parser("from-script", help="organizar mídia sobre um roteiro pronto "
                                           "(sem reescrever a narração)")
    fs.add_argument("script", help="arquivo .txt com o roteiro (ou - para stdin)")
    fs.add_argument("--slug", default=None, help="nome do diretório de saída")
    fs.add_argument("--title", default=None, help="título do vídeo "
                                                  "(padrão: 1ª linha do roteiro)")
    fs.add_argument("--force", action="store_true", help="refazer todas as etapas")
    fs.add_argument("--duration", default=None,
                    help="meta de duração (não corta): auto (padrão), 30, 45, "
                         "60, 90, 120, 180 ou segundos 5..600")
    fs.add_argument("--narration", default="ai", choices=["ai", "human"],
                    help="ai = vídeo final com Edge TTS; human = silencioso + teleprompter")
    fs.add_argument("--max-images", type=int, default=None,
                    help="fotos por cena com sobreposição 1-5 (padrão: config)")
    fs.add_argument("--insertions", type=int, default=None,
                    help="fotos complementares que caem sobre o fundo, no "
                         "TOTAL do vídeo, 0-5 (1-2 o ideal; padrão: config). "
                         "0 = cada cena mostra só a imagem de fundo")
    fs.add_argument("--no-open", action="store_true",
                    help="não abrir pasta/gravador após o teleprompter")
    fs.add_argument("--language", default=None, help="idioma do vídeo: pt-BR ou en-US")
    fs.set_defaults(func=cmd_from_script)

    t = sub.add_parser("tui", help="interface interativa em terminal")
    t.set_defaults(func=lambda a, c: __import__("curio.tui", fromlist=["run"]).run(c))

    ls = sub.add_parser("list", help="listar vídeos gerados")
    ls.set_defaults(func=cmd_list)

    inf = sub.add_parser("info", help="mostrar metadados de um vídeo")
    inf.add_argument("idea", nargs="*", help="ideia original ou --slug")
    inf.add_argument("--slug", default=None)
    inf.set_defaults(func=cmd_info)

    vf = sub.add_parser("verify", help="verificar um vídeo gerado (PRD §19)")
    vf.add_argument("--slug", required=True, help="nome do diretório do vídeo")
    vf.set_defaults(func=cmd_verify)

    rv = sub.add_parser(
        "review", help="folha de contato da escolha visual (revisão humana)")
    rv.add_argument("--slug", required=True, help="nome do diretório do vídeo")
    rv.add_argument("--dry-run", action="store_true",
                    help="imprime a decisão por cena em texto, sem HTML")
    rv.set_defaults(func=cmd_review)

    sw = sub.add_parser("swap", help="trocar a imagem de uma cena")
    sw.add_argument("--slug", required=True, help="nome do diretório do vídeo")
    sw.add_argument("--scene", type=int, required=True,
                    help="número da cena (1-based, como no vídeo)")
    sw.add_argument("--pick", type=int, default=0,
                    help="índice da imagem escolhida nesta cena (0-based)")
    sw.set_defaults(func=cmd_swap)

    rr = sub.add_parser(
        "rerender", help="refazer vídeo e legendas a partir do que mudou "
                         "(não re-sintetiza a narração)")
    rr.add_argument("--slug", required=True, help="nome do diretório do vídeo")
    rr.set_defaults(func=cmd_rerender)

    met = sub.add_parser("metrics", help="gerar métricas de vídeos existentes")
    met.add_argument("--slug", default=None,
                     help="só este projeto (padrão: todos com metadata.json)")
    met.set_defaults(func=cmd_metrics)

    v = sub.add_parser("voices", help="listar provedores TTS disponíveis")
    v.set_defaults(func=cmd_voices)

    d = sub.add_parser("doctor", help="checar dependências do ambiente")
    d.set_defaults(func=cmd_doctor)

    q = sub.add_parser("queue", help="processar fila de vídeos sequencialmente")
    q.add_argument("ideas", nargs="*", help="ideias textuais (ou use --file)")
    q.add_argument("--file", "-f", default=None, help="arquivo com uma ideia por linha")
    q.add_argument("--save", default=None, help="salvar fila em arquivo JSON")
    q.add_argument("--load", default=None, help="carregar fila de arquivo JSON")
    q.add_argument("--list", action="store_true", help="apenas listar status da fila")
    q.add_argument("--retry", action="store_true", help="reprocessar itens com erro")
    q.add_argument("--cancel", dest="cancel_index", type=int, default=None,
                   help="cancelar item por índice (aguardando ou erro)")
    q.add_argument("--move", nargs=2, type=int, metavar=("FROM", "TO"),
                   help="reordenar item aguardando")
    q.add_argument("--no-progress", action="store_true",
                   help="não mostrar progresso visual (limpa tela)")
    q.set_defaults(func=cmd_queue)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    cfg = CurioConfig.load(args.config)
    if args.out_dir:
        cfg.out_dir = args.out_dir
    if getattr(args, "tts", None):
        cfg.tts_provider = args.tts
    if getattr(args, "voice", None):
        cfg.tts_voice = args.voice
    if getattr(args, "backend", None):
        cfg.render_backend = args.backend
    if getattr(args, "language", None):
        from .config import normalize_language
        cfg.language = normalize_language(args.language)
        if cfg.language == "en-US" and cfg.tts_voice == "pt-BR-AntonioNeural":
            cfg.tts_voice = "en-US-GuyNeural"
    if getattr(args, "queues_dir", None):
        cfg.queues_dir = args.queues_dir
    if args.cmd is None:
        # Sem subcomando: abre a interface visual (TUI) — ex.: ./scripts/run.sh
        from .tui import run as run_tui
        return run_tui(cfg)
    return args.func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
