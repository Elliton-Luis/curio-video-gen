"""Entrada, teclado, caixas e menus da TUI. Stdlib only."""

from __future__ import annotations

import os
import sys


class TUIExit(Exception):
    """Saída limpa por EOF, Ctrl+C ou comando de voltar."""


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise TUIExit()


def colors() -> dict[str, str]:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return {k: "" for k in ("bold", "cyan", "green", "yellow", "red", "dim", "reset")}
    return {"bold": "\033[1m", "cyan": "\033[36m", "green": "\033[32m",
            "yellow": "\033[33m", "red": "\033[31m", "dim": "\033[2m",
            "reset": "\033[0m"}


def clear() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def banner(c: dict[str, str]) -> None:
    print(f"{c['bold']}{c['cyan']}"
          "  ____ _   _ ____  ___ ___  \n"
          " / ___| | | |  _ \\|_ _/ _ \\ \n"
          "| |   | | | | |_) || | | | |\n"
          "| |___| |_| |  _ < | | |_| |\n"
          " \\____|\\___/|_| \\_\\___\\___/ \n"
          f"{c['reset']}{c['dim']}Máquina de Conteúdo Educativo em Vídeo — v0.2{c['reset']}\n")


def pause(c: dict[str, str]) -> None:
    ask(f"\n{c['dim']}Enter para voltar...{c['reset']}")


def interactive_supported() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def read_key() -> str:
    """Lê uma tecla: up/down/enter/esc/q ou caractere."""
    import tty
    import termios
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            if seq == "[A":
                return "up"
            if seq == "[B":
                return "down"
            return "esc"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            raise TUIExit()
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def wrap_text(text: str, width: int) -> list[str]:
    """Quebra linhas que cabem na caixa de menu."""
    lines, current = [], ""
    for word in str(text or "").split():
        if len(current) + len(word) + 1 > width and current:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def _render_menu(c: dict[str, str], title: str, options: list[str],
                 selected: int, status: list[str] | None = None,
                 details: list[str] | None = None, fit_labels: bool = False,
                 footer: str = "↑↓ navegar   Enter selecionar   Q sair   Esc voltar") -> None:
    clear()
    width = 46
    if fit_labels:
        width = max(width, len(title) + 4,
                    max((len(label) + 7 for label in options), default=0),
                    len(footer) + 2)
        width = min(width, 100)
    print(f"{c['dim']}╭{'─' * width}╮{c['reset']}")
    print(f"{c['dim']}│{c['reset']} {c['bold']}{c['cyan']}CURIO{c['reset']}"
          f"{' ' * (width - 7)}{c['dim']}│{c['reset']}")
    if title:
        print(f"{c['dim']}│{c['reset']} {c['dim']}{title}{c['reset']}"
              f"{' ' * max(1, width - len(title) - 1)}{c['dim']}│{c['reset']}")
    print(f"{c['dim']}│{' ' * width}│{c['reset']}")
    for i, label in enumerate(options):
        mark = "›" if i == selected else " "
        line = f"  {mark} {label}"
        color = c['bold'] + c['yellow'] if i == selected else c['dim']
        print(f"{c['dim']}│{c['reset']}{color}{line}"
              f"{' ' * max(1, width - len(line))}{c['reset']}{c['dim']}│{c['reset']}")
    if details:
        print(f"{c['dim']}│{' ' * width}│{c['reset']}")
        for i, detail in enumerate(details):
            color = c["cyan"] if i == len(details) - 1 else c["dim"]
            for wrapped in wrap_text(detail, width - 4):
                line = f"   {wrapped}"
                print(f"{c['dim']}│{c['reset']}{color}{line}{c['reset']}"
                      f"{' ' * max(1, width - len(line))}{c['dim']}│{c['reset']}")
    if status:
        print(f"{c['dim']}│{' ' * width}│{c['reset']}")
        for line in status[:4]:
            line = line[:width - 1]
            print(f"{c['dim']}│{c['reset']} {c['dim']}{line}{c['reset']}"
                  f"{' ' * max(1, width - len(line) - 1)}{c['dim']}│{c['reset']}")
    print(f"{c['dim']}│{' ' * width}│{c['reset']}")
    print(f"{c['dim']}│{c['reset']} {c['dim']}{footer}{c['reset']}"
          f"{' ' * max(1, width - len(footer) - 1)}{c['dim']}│{c['reset']}")
    print(f"{c['dim']}╰{'─' * width}╯{c['reset']}")


def select_option(c: dict[str, str], title: str, options: list[str],
                  status: list[str] | None = None, selected: int = 0,
                  details_for=None, fit_labels: bool = False,
                  footer: str = "↑↓ navegar   Enter selecionar   Q sair   Esc voltar") -> int | None:
    """Menu teclado com fallback numerado fora de TTY."""
    if not options:
        return None
    if not interactive_supported():
        clear()
        banner(c)
        if title:
            print(f"\n{c['bold']}{title}{c['reset']}")
        if status:
            for line in status:
                print(f"{c['dim']}{line}{c['reset']}")
        for i, label in enumerate(options, 1):
            print(f"  {c['bold']}{i}){c['reset']} {label}")
        if details_for:
            for line in details_for(max(0, min(selected, len(options) - 1))):
                print(f"  {c['dim']}{line}{c['reset']}")
        raw = ask(f"\n{c['bold']}Escolha [1-{len(options)}] (0 volta):{c['reset']} ").strip()
        if raw in ("0", "q", "Q", ""):
            return None
        try:
            index = int(raw) - 1
        except ValueError:
            return None
        return index if 0 <= index < len(options) else None
    selected = max(0, min(selected, len(options) - 1))
    while True:
        details = details_for(selected) if details_for else None
        _render_menu(c, title, options, selected, status, details,
                     fit_labels=fit_labels, footer=footer)
        try:
            key = read_key()
        except TUIExit:
            raise
        except Exception:
            return None
        if key in ("up", "k"):
            selected = (selected - 1) % len(options)
        elif key in ("down", "j"):
            selected = (selected + 1) % len(options)
        elif key == "enter":
            return selected
        elif key in ("q", "Q", "esc"):
            return None


def browse_path(c: dict[str, str], start: str, title: str = "Escolher local",
                dirs_only: bool = False) -> str | None:
    """Navegador local simples; devolve caminho escolhido ou None."""
    current = os.path.abspath(os.path.expanduser(start or "."))
    while True:
        try:
            entries = sorted(os.listdir(current))
        except OSError:
            entries = []
        options = [".. (subir um nível)"]
        for entry in entries:
            full = os.path.join(current, entry)
            if os.path.isdir(full):
                options.append(f"{entry}/")
            elif not dirs_only:
                options.append(entry)
        options.extend(["✔ Usar esta pasta" if dirs_only else "✔ Usar este local",
                        "Cancelar"])
        index = select_option(c, f"{title} — {current}", options,
                              status=[f"{len(entries)} itens em {current}"])
        if index is None:
            return None
        if index == 0:
            current = os.path.dirname(current) or "/"
        elif index == len(options) - 1:
            return None
        elif index == len(options) - 2:
            return current
        else:
            selected = entries[index - 1]
            full = os.path.join(current, selected)
            if os.path.isdir(full):
                current = full
            else:
                return full
