"""TUI visual em terminal (stdlib, sem dependências): gerar, testar e verificar."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import verify as verify_mod
from .config import CurioConfig
from .pipeline import run_pipeline, video_paths
from .slug import slugify

QUICK_TEST_IDEA = "De onde veio a palavra salário?"
QUICK_TEST_SLUG = "teste-rapido"


class _TUIExit(Exception):
    pass


def _colors() -> dict[str, str]:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return {k: "" for k in ("bold", "cyan", "green", "yellow", "red", "dim", "reset")}
    return {
        "bold": "\033[1m", "cyan": "\033[36m", "green": "\033[32m",
        "yellow": "\033[33m", "red": "\033[31m", "dim": "\033[2m",
        "reset": "\033[0m",
    }


def _clear() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def _banner(c: dict[str, str]) -> None:
    print(f"{c['bold']}{c['cyan']}"
          "  ____ _   _ ____  ___ ___  \n"
          " / ___| | | |  _ \\|_ _/ _ \\ \n"
          "| |   | | | | |_) || | | | |\n"
          "| |___| |_| |  _ < | | |_| |\n"
          " \\____|\\___/|_| \\_\\___\\___/ \n"
          f"{c['reset']}{c['dim']}Máquina de Conteúdo Educativo em Vídeo — v0.2{c['reset']}\n")


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise _TUIExit()


def _progress(idx: int, total: int, label: str, status: str) -> None:
    print(f"  [{idx}/{total}] {label}... {status}", flush=True)


def _show_verify(c: dict[str, str], mp4: str, srt: str, cfg: CurioConfig) -> bool:
    print(f"\n{c['bold']}Verificação do vídeo:{c['reset']}")
    rep = verify_mod.verify_video(mp4, srt, cfg.duration_target, cfg.width, cfg.height)
    for chk in rep.checks:
        mark = f"{c['green']}OK   {c['reset']}" if chk.ok else f"{c['red']}FALHA{c['reset']}"
        extra = f" {c['dim']}— {chk.detail}{c['reset']}" if chk.detail else ""
        print(f"[{mark}] {chk.label}{extra}")
    print(f"\n{c['bold']}{rep.passed}/{rep.total} verificações passaram.{c['reset']}")
    return rep.success


def _generate_flow(c: dict[str, str], cfg: CurioConfig,
                   idea: str | None = None, slug: str | None = None,
                   force: bool = False, narration: str = "ai") -> None:
    if idea is None:
        idea = _ask("\nIdeia do vídeo (ex.: De onde veio a palavra salário?): ").strip()
        if not idea:
            print("Ideia vazia — voltando ao menu.")
            return
        slug = slugify(idea)
        print(f"Diretório de saída: {cfg.out_dir}/{slug}/")
        kind = _ask("Narração: [1] IA (Edge TTS) / [2] humana (eu narro) [1]: ").strip()
        narration = "human" if kind == "2" else "ai"
        force = _ask("Refazer etapas já concluídas? [s/N]: ").strip().lower().startswith("s")
    try:
        meta = run_pipeline(idea, cfg, slug=slug, force=force,
                            narration=narration, on_progress=_progress)
    except Exception as exc:  # noqa: BLE001 — TUI exibe erro e volta ao menu
        print(f"\n{c['red']}ERRO: {exc}{c['reset']}")
        print("Artefatos anteriores foram preservados — tente de novo sem refazer tudo.")
        return
    if narration == "human":
        print(f"\n{c['green']}Pronto!{c['reset']} "
              f"Silencioso: {meta['artifacts']['silent']}")
        print(f"Teleprompter: {meta['artifacts']['teleprompter']}")
        print("Grave sua voz assistindo ao teleprompter e use a opção "
              "Finalizar do menu.")
        return
    print(f"\n{c['green']}Pronto!{c['reset']} Vídeo: {meta['artifacts']['video']} "
          f"({meta['duration_actual']}s em {meta['processing_time_seconds']}s)")
    _show_verify(c, meta["artifacts"]["video"], meta["artifacts"]["subtitles"], cfg)


def _quick_test_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    print(f"\n{c['bold']}Teste rápido:{c['reset']} gera o vídeo-exemplo "
          f"{c['yellow']}{QUICK_TEST_IDEA!r}{c['reset']} do zero e verifica tudo.")
    ok = _ask("Continuar? [S/n]: ").strip().lower()
    if ok not in ("", "s", "y", "sim"):
        return
    _generate_flow(c, cfg, idea=QUICK_TEST_IDEA, slug=QUICK_TEST_SLUG, force=True)


def _list_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    if not os.path.isdir(cfg.out_dir):
        print("Nenhum vídeo ainda.")
        return
    for entry in sorted(os.listdir(cfg.out_dir)):
        if not os.path.isfile(os.path.join(cfg.out_dir, entry, "metadata.json")):
            continue
        try:
            with open(os.path.join(cfg.out_dir, entry, "metadata.json"),
                      encoding="utf-8") as fh:
                meta = json.load(fh)
            print(f"- {c['cyan']}{entry}{c['reset']}: {meta.get('title', '?')} "
                  f"({meta.get('duration_actual', '?')}s)")
        except json.JSONDecodeError:
            print(f"- {entry}: (metadados corrompidos)")


def _finalize_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    from .cli import _final_progress
    from .pipeline import finalize_project
    slug = _ask("Slug do projeto (gerado com narração humana): ").strip()
    audio = _ask("Arquivo de áudio com sua voz (wav/mp3): ").strip()
    if not slug or not audio:
        return
    try:
        meta = finalize_project(slug, os.path.expanduser(audio), cfg,
                                on_progress=_final_progress)
    except Exception as exc:  # noqa: BLE001
        print(f"\n{c['red']}ERRO: {exc}{c['reset']}")
        return
    print(f"\n{c['green']}Pronto!{c['reset']} Vídeo: {meta['artifacts']['video']} "
          f"({meta['duration_actual']}s)")
    _show_verify(c, meta["artifacts"]["video"], meta["artifacts"].get(
        "subtitles", os.path.join(cfg.out_dir, slug, "subtitles", "subs.srt")),
        cfg)


def _verify_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    slug = _ask("Slug do vídeo (ex.: teste-rapido): ").strip()
    if not slug:
        return
    paths = video_paths(cfg.out_dir, slug)
    if not os.path.isfile(paths.final_mp4):
        print(f"{c['red']}Vídeo '{slug}' não encontrado em {cfg.out_dir}/{c['reset']}")
        return
    _show_verify(c, paths.final_mp4, paths.subs_srt, cfg)


def run(cfg: CurioConfig | None = None) -> int:
    cfg = cfg or CurioConfig.load()
    c = _colors()
    try:
        while True:
            _clear()
            _banner(c)
            print(f"{c['bold']}1){c['reset']} Gerar vídeo a partir de ideia (com verificação)")
            print(f"{c['bold']}2){c['reset']} Teste rápido (vídeo-exemplo do zero + verificação)")
            print(f"{c['bold']}3){c['reset']} Listar vídeos")
            print(f"{c['bold']}4){c['reset']} Verificar um vídeo")
            print(f"{c['bold']}5){c['reset']} Finalizar narração humana (--audio)")
            print(f"{c['bold']}6){c['reset']} Checar ambiente (doctor)")
            print(f"{c['bold']}7){c['reset']} Sair")
            choice = _ask(f"\n{c['bold']}Escolha [1-7]:{c['reset']} ").strip()
            if choice == "1":
                _generate_flow(c, cfg)
            elif choice == "2":
                _quick_test_flow(c, cfg)
            elif choice == "3":
                _list_flow(c, cfg)
            elif choice == "4":
                _verify_flow(c, cfg)
            elif choice == "5":
                _finalize_flow(c, cfg)
            elif choice == "6":
                from .cli import cmd_doctor
                cmd_doctor(argparse.Namespace(), cfg)
            elif choice == "7":
                print("Até logo!")
                return 0
            else:
                print("Opção inválida.")
            _ask(f"\n{c['dim']}Enter para voltar ao menu...{c['reset']}")
    except _TUIExit:
        print("\nAté logo!")
        return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
