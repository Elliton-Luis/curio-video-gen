"""TUI em terminal (stdlib, sem dependências): fluxo guiado do MVP."""

from __future__ import annotations

import os

from . import ffmpeg as ff
from .config import CurioConfig
from .pipeline import run_pipeline
from .slug import slugify
from .stages import tts as tts_stage


def _progress(idx: int, total: int, label: str, status: str) -> None:
    print(f"  [{idx}/{total}] {label}... {status}", flush=True)


def _generate_flow(cfg: CurioConfig) -> None:
    idea = input("\nIdeia do vídeo (ex.: De onde veio a palavra salário?): ").strip()
    if not idea:
        print("Ideia vazia — voltando ao menu.")
        return
    slug = slugify(idea)
    print(f"Diretório de saída: {cfg.out_dir}/{slug}/")
    force_in = input("Refazer etapas já concluídas? [s/N]: ").strip().lower()
    try:
        meta = run_pipeline(idea, cfg, force=force_in.startswith("s"),
                            on_progress=_progress)
    except Exception as exc:  # noqa: BLE001 — TUI exibe erro e volta ao menu
        print(f"\nERRO: {exc}")
        print("Artefatos anteriores foram preservados — tente de novo sem refazer tudo.")
        return
    print(f"\nPronto! Vídeo: {meta['artifacts']['video']} "
          f"({meta['duration_actual']}s em {meta['processing_time_seconds']}s)")


def _list_flow(cfg: CurioConfig) -> None:
    import json
    if not os.path.isdir(cfg.out_dir):
        print("Nenhum vídeo ainda.")
        return
    for entry in sorted(os.listdir(cfg.out_dir)):
        meta_path = os.path.join(cfg.out_dir, entry, "metadata.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
            print(f"- {entry}: {meta.get('title', '?')} ({meta.get('duration_actual', '?')}s)")
        except json.JSONDecodeError:
            print(f"- {entry}: (metadados corrompidos)")


def run(cfg: CurioConfig | None = None) -> int:
    cfg = cfg or CurioConfig.load()
    while True:
        print("\n=== curio — Máquina de Conteúdo Educativo em Vídeo ===")
        print("1) Gerar vídeo a partir de ideia")
        print("2) Listar vídeos")
        print("3) Checar ambiente (doctor)")
        print("4) Sair")
        choice = input("Escolha [1-4]: ").strip()
        if choice == "1":
            _generate_flow(cfg)
        elif choice == "2":
            _list_flow(cfg)
        elif choice == "3":
            from .cli import cmd_doctor
            import argparse
            cmd_doctor(argparse.Namespace(), cfg)
        elif choice == "4":
            print("Até logo!")
            return 0
        else:
            print("Opção inválida.")


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
