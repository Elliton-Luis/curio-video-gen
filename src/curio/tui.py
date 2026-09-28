"""TUI visual em terminal (stdlib, sem dependências).

Organizada por OBJETIVO, não por comando técnico:
- "Quero um vídeo pronto" → narração IA, sai com MP4 final.
- "Quero narrar eu mesmo" → assistente em 2 passos, deixando explícito que
  o vídeo final SÓ existe depois do passo 2 (finalize com sua voz).
- "Ajuda" explica os fluxos, arquivos e o que fazer em cada etapa.
"""

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


def _pause(c: dict[str, str]) -> None:
    _ask(f"\n{c['dim']}Enter para voltar ao menu...{c['reset']}")


def _ask_duration(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    """Duração aproximada do vídeo (roteiro, cenas e verificação acompanham)."""
    raw = _ask("Duração aproximada em segundos [30/45/60, padrão 45]: ").strip()
    if not raw:
        return cfg
    try:
        seconds = float(raw.replace(",", "."))
    except ValueError:
        print("Valor inválido — usando 45s.")
        return cfg
    seconds = min(120, max(15, seconds))
    import dataclasses
    print(f"Duração-alvo: {seconds:.0f}s (aproximada).")
    return dataclasses.replace(cfg, duration_target=seconds)


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


def _project_status(cfg: CurioConfig, slug: str) -> tuple[str, dict]:
    """Retorna (situação legível, metadata)."""
    meta_path = os.path.join(cfg.out_dir, slug, "metadata.json")
    if not os.path.isfile(meta_path):
        return "não encontrado", {}
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except json.JSONDecodeError:
        return "metadados corrompidos", {}
    mode = meta.get("narration", "ai")
    if mode == "human-pending":
        return "aguardando sua voz (sem vídeo final ainda)", meta
    if mode == "human":
        return "vídeo final com SUA voz", meta
    return "vídeo final pronto (voz de IA)", meta


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
    audio/                    narração da IA ou a SUA voz + transcrição
    metadata.json             tudo sobre o projeto (capítulos, licenças, tempos)

DICAS:
    - Reexecutar sem --force reaproveita o já pronto (rápido e sem custo).
    - Legendas vêm de timestamps reais (voz de IA ou transcrição da sua).
    - Sem internet: voz local simples; sem chave NVIDIA: roteiros locais.
"""


def _help_flow(c: dict[str, str]) -> None:
    print(f"\n{c['bold']}AJUDA{c['reset']}\n")
    print(HELP_TEXT)


# ------------------------------------------------------- fluxo A (IA)

def _ai_flow(c: dict[str, str], cfg: CurioConfig,
             idea: str | None = None, slug: str | None = None,
             force: bool = False) -> None:
    print(f"\n{c['bold']}VÍDEO PRONTO — voz de IA, você sai com o MP4 final.{c['reset']}")
    if idea is None:
        idea = _ask("Ideia do vídeo (ex.: De onde veio a palavra salário?): ").strip()
        if not idea:
            print("Ideia vazia — voltando ao menu.")
            return
        slug = slugify(idea)
        print(f"Pasta do projeto: {cfg.out_dir}/{slug}/")
        cfg = _ask_duration(c, cfg)
        force = _ask("Refazer etapas já concluídas? [s/N]: ").strip().lower().startswith("s")
    try:
        meta = run_pipeline(idea, cfg, slug=slug, force=force,
                            narration="ai", on_progress=_progress)
    except Exception as exc:  # noqa: BLE001 — TUI exibe erro e volta ao menu
        print(f"\n{c['red']}ERRO: {exc}{c['reset']}")
        print("O que já estava pronto foi preservado — tente de novo.")
        return
    print(f"\n{c['green']}Pronto!{c['reset']} Vídeo final: {meta['artifacts']['video']} "
          f"({meta['duration_actual']}s em {meta['processing_time_seconds']}s)")
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
    slug = slugify(idea)
    print(f"Pasta do projeto: {cfg.out_dir}/{slug}/")
    cfg = _ask_duration(c, cfg)
    try:
        meta = run_pipeline(idea, cfg, slug=slug, force=False,
                            narration="human", on_progress=_progress)
    except Exception as exc:  # noqa: BLE001
        print(f"\n{c['red']}ERRO: {exc}{c['reset']}")
        print("O que já estava pronto foi preservado — tente de novo.")
        return None
    print(f"\n{c['green']}Base pronta!{c['reset']} (repare: ainda NÃO há vídeo final)")
    print(f"  1. Assista e leia: {meta['artifacts']['teleprompter']}")
    print(f"  2. Grave sua voz (~{meta['duration_actual']}s) com qualquer gravador")
    print(f"  3. Volte aqui → opção 'Passo 2: finalizar com minha voz'")
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
                                on_progress=_final_progress)
    except Exception as exc:  # noqa: BLE001
        print(f"\n{c['red']}ERRO: {exc}{c['reset']}")
        return
    print(f"\n{c['green']}Pronto!{c['reset']} Vídeo final: {meta['artifacts']['video']} "
          f"({meta['duration_actual']}s)")
    for w in meta.get("finalize_warnings", []):
        print(f"{c['yellow']}AVISO: {w}{c['reset']}")
    _show_verify(c, meta["artifacts"]["video"], meta["artifacts"].get(
        "subtitles", os.path.join(cfg.out_dir, slug, "subtitles", "subs.srt")),
        cfg)


def _human_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    slug = _human_step1(c, cfg)
    if slug is None:
        return
    if _ask("\nJá tem o áudio gravado e quer finalizar AGORA? [s/N]: "
            ).strip().lower().startswith("s"):
        _human_step2(c, cfg, slug=slug)
    else:
        print("Sem pressa: quando gravar, volte → 'Passo 2: finalizar com minha voz'.")


# ------------------------------------------------------- projetos

def _list_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    if not os.path.isdir(cfg.out_dir):
        print("Nenhum projeto ainda — comece pela opção 1 ou 2.")
        return
    rows = 0
    for entry in sorted(os.listdir(cfg.out_dir)):
        status, meta = _project_status(cfg, entry)
        if not meta and status == "não encontrado":
            continue
        rows += 1
        mark = (c["yellow"] + "○" if "aguardando" in status
                else c["green"] + "●")
        print(f"{mark}{c['reset']} {c['cyan']}{entry}{c['reset']}: {status}")
    if not rows:
        print("Nenhum projeto ainda — comece pela opção 1 ou 2.")


def _verify_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    slug = _ask("Projeto (slug da pasta em output/): ").strip()
    if not slug:
        return
    status, _meta = _project_status(cfg, slug)
    if "aguardando sua voz" in status:
        print(f"'{slug}' ainda não tem vídeo final — finalize primeiro "
              f"(opção 'Passo 2: finalizar com minha voz').")
        return
    paths = video_paths(cfg.out_dir, slug)
    if not os.path.isfile(paths.final_mp4):
        print(f"{c['red']}Projeto '{slug}': {status}; sem MP4 final.{c['reset']}")
        return
    _show_verify(c, paths.final_mp4, paths.subs_srt, cfg)


# ------------------------------------------------------- menu

def run(cfg: CurioConfig | None = None) -> int:
    cfg = cfg or CurioConfig.load()
    c = _colors()
    try:
        while True:
            _clear()
            _banner(c)
            print(f"{c['dim']}O que você quer fazer?{c['reset']}")
            print(f"\n  {c['bold']}QUERO UM VÍDEO PRONTO (voz de IA){c['reset']}")
            print(f"  {c['bold']}1){c['reset']} Criar vídeo com voz de IA")
            print(f"\n  {c['bold']}QUERO NARRAR EU MESMO (2 passos){c['reset']}")
            print(f"  {c['bold']}2){c['reset']} Passo 1: preparar base (silencioso + teleprompter)")
            print(f"  {c['bold']}3){c['reset']} Passo 2: finalizar com minha voz")
            print(f"\n  {c['bold']}MEUS PROJETOS{c['reset']}")
            print(f"  {c['bold']}4){c['reset']} Listar projetos (com situação)")
            print(f"  {c['bold']}5){c['reset']} Verificar um vídeo")
            print(f"\n  {c['bold']}AJUDA E SISTEMA{c['reset']}")
            print(f"  {c['bold']}6){c['reset']} Como funciona (ajuda)")
            print(f"  {c['bold']}7){c['reset']} Teste rápido")
            print(f"  {c['bold']}8){c['reset']} Checar ambiente (doctor)")
            print(f"  {c['bold']}9){c['reset']} Sair")
            choice = _ask(f"\n{c['bold']}Escolha [1-9]:{c['reset']} ").strip()
            if choice == "1":
                _ai_flow(c, cfg)
            elif choice == "2":
                _human_flow(c, cfg)
            elif choice == "3":
                _human_step2(c, cfg)
            elif choice == "4":
                _list_flow(c, cfg)
            elif choice == "5":
                _verify_flow(c, cfg)
            elif choice == "6":
                _help_flow(c)
            elif choice == "7":
                _quick_test_flow(c, cfg)
            elif choice == "8":
                from .cli import cmd_doctor
                cmd_doctor(argparse.Namespace(), cfg)
            elif choice == "9":
                print("Até logo!")
                return 0
            else:
                print("Opção inválida.")
            _pause(c)
    except _TUIExit:
        print("\nAté logo!")
        return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
