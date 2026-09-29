"""Interface CLI (PRD §14)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from . import __version__
from . import ffmpeg as ff
from . import verify as verify_mod
from .config import CurioConfig
from .metrics import backfill_from_metadata
from .pipeline import finalize_project, run_pipeline, video_paths
from .slug import slugify
from .stages import nvidia as nvidia_stage
from .stages import transcribe as transcribe_stage
from .stages import tts as tts_stage


def _progress(idx: int, total: int, label: str, status: str) -> None:
    print(f"[{idx}/{total}] {label}... {status}", flush=True)


def _fail(stage: str, exc: BaseException, hint: str = "") -> int:
    print(f"\nERRO na etapa '{stage}': {exc}", file=sys.stderr)
    if hint:
        print(f"Motivo provável: {hint}", file=sys.stderr)
    print("Dica: artefatos anteriores foram preservados — corrija e rode de novo "
          "sem --force para reaproveitá-los.", file=sys.stderr)
    return 1


def cmd_generate(args, cfg: CurioConfig) -> int:
    idea = " ".join(args.idea).strip()
    narration = getattr(args, "narration", "ai")
    if getattr(args, "duration", None):
        cfg.duration_target = float(args.duration)
        print(f"Duração-alvo: {cfg.duration_target:.0f}s (aproximada).")
    if narration not in ("ai", "human"):
        print("Narração deve ser 'ai' ou 'human'.", file=sys.stderr)
        return 2
    try:
        meta = run_pipeline(idea, cfg, slug=args.slug, force=args.force,
                            narration=narration, on_progress=_progress)
    except ValueError as exc:
        return _fail("roteiro", exc, "ideia vazia ou inválida.")
    except nvidia_stage.NvidiaError as exc:
        return _fail("NVIDIA", exc, "verifique NVIDIA_API_KEY/NVIDIA_MODEL; "
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
    print(f"Duração: {meta['duration_actual']}s (alvo: {meta['duration_target']}s) | "
          f"TTS: {meta['tts_provider']} | render: {meta['render_encoder']} | "
          f"tempo: {meta['processing_time_seconds']}s")
    return 0


def _final_progress(label: str, status: str) -> None:
    print(f"[finalize] {label}... {status}", flush=True)


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
    dev = ff.vaapi_device()
    check("VA-API (Intel Arc/discreta/iGPU)", dev is not None, dev or "vai usar CPU (libx264)")
    check("fonte para título", ff.find_font_bold() is not None,
          ff.find_font_bold() or "título será omitido")
    creds = nvidia_stage.NvidiaCredentials.from_env()
    # Informativo: ausência de chave NÃO falha o doctor (gerador local cobre).
    extra = f" ({creds.count} configurada(s), usa a 1ª)" if creds.available else ""
    print(f"[{'OK' if creds.available else '--'}] NVIDIA API "
          f"{'— chave configurada' + extra if creds.available else '— sem chave (roteiros locais)'}")
    has_fw = importlib.util.find_spec("faster_whisper") is not None
    print(f"[{'OK' if has_fw else '--'}] faster-whisper (transcrição local) "
          f"{'— ' + cfg.whisper_model if has_fw else '— finalize indisponível; pip install faster-whisper'}")
    from .media import providers as media_prov
    print(f"[{'OK' if media_prov.check_connectivity() else '--'}] "
          f"Wikimedia Commons (mídia: {cfg.media_providers})")
    print(f"\nConfig: out_dir={cfg.out_dir} tts={cfg.tts_provider}/{cfg.tts_voice} "
          f"backend={cfg.render_backend} nvidia_model={cfg.nvidia_model}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="video-gen",
                                 description="Máquina de Conteúdo Educativo em Vídeo (MVP)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--config", default=None, help="caminho do config.toml")
    ap.add_argument("--out-dir", default=None, help="sobrescreve diretório de saída")
    ap.add_argument("--tts", default=None, help="provedor TTS (ex.: espeak-ng)")
    ap.add_argument("--voice", default=None, help="voz TTS (ex.: pt-br)")
    ap.add_argument("--backend", default=None, help="auto|vaapi|qsv|cpu")
    sub = ap.add_subparsers(dest="cmd", required=False)

    g = sub.add_parser("generate", help="gerar vídeo a partir de uma ideia")
    g.add_argument("idea", nargs="+", help="ideia textual entre aspas")
    g.add_argument("--slug", default=None, help="nome do diretório de saída")
    g.add_argument("--force", action="store_true", help="refazer todas as etapas")
    g.add_argument("--duration", type=float, default=None,
                   help="duração aproximada em segundos (ex.: 30, 45, 60)")
    g.add_argument("--narration", default="ai", choices=["ai", "human"],
                   help="ai = vídeo final com Edge TTS; human = silencioso + teleprompter")
    g.add_argument("--no-open", action="store_true",
                   help="não abrir pasta/gravador após o teleprompter")
    g.set_defaults(func=cmd_generate)

    fin = sub.add_parser("finalize", help="unir áudio humano ao vídeo silencioso")
    fin.add_argument("slug", help="projeto criado com --narration human")
    fin.add_argument("--audio", required=True, help="wav/mp3 com a narração humana")
    fin.add_argument("--force", action="store_true", help="retranscrever e refazer")
    fin.set_defaults(func=cmd_finalize)

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

    met = sub.add_parser("metrics", help="gerar métricas de vídeos existentes")
    met.add_argument("--slug", default=None,
                     help="só este projeto (padrão: todos com metadata.json)")
    met.set_defaults(func=cmd_metrics)

    v = sub.add_parser("voices", help="listar provedores TTS disponíveis")
    v.set_defaults(func=cmd_voices)

    d = sub.add_parser("doctor", help="checar dependências do ambiente")
    d.set_defaults(func=cmd_doctor)
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
    if args.cmd is None:
        # Sem subcomando: abre a interface visual (TUI) — ex.: ./scripts/run.sh
        from .tui import run as run_tui
        return run_tui(cfg)
    return args.func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
