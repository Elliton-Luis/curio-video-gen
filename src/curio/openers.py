"""Abertura pós-teleprompter: pasta + gravador de áudio (§17, usabilidade).

Após gerar a base humana, abre o gerenciador de arquivos na pasta do
teleprompter e o gravador de áudio — o usuário grava sem caçar arquivos.
Tudo configurável (binários + liga/desliga); sem sessão gráfica ou sem
binário, só avisa. NUNCA falha o pipeline: só retorna mensagens.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def _enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("", "0", "false", "no", "n")


def open_after_teleprompter(cfg, tele_dir: str,
                            force: bool = False) -> list[str]:
    """Abre pasta + gravador. Retorna mensagens p/ exibir. Nunca levanta."""
    msgs: list[str] = []
    try:
        return _do_open(cfg, tele_dir, force, msgs)
    except Exception as exc:  # noqa: BLE001 — abertura é cortesia, não etapa
        return msgs + [f"AVISO: não foi possível abrir apps ({exc})"]


def _do_open(cfg, tele_dir: str, force: bool, msgs: list[str]) -> list[str]:
    if not force and not _enabled(getattr(cfg, "auto_open", True)):
        return ["Abertura automática desligada (CURIO_AUTO_OPEN=0)."]
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return [f"Sem sessão gráfica — arquivos em: {tele_dir}"]
    jobs = [
        ("pasta do teleprompter", getattr(cfg, "file_manager", "dolphin"),
         [tele_dir]),
        ("gravador de áudio", getattr(cfg, "audio_recorder", "audacity"), []),
    ]
    for label, binary, args in jobs:
        if not binary:
            msgs.append(f"{label}: não configurado — abra manualmente.")
            continue
        if shutil.which(binary) is None:
            msgs.append(f"{label}: {binary!r} não encontrado — abra manualmente "
                        f"({tele_dir}).")
            continue
        try:
            subprocess.Popen([binary, *args],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
            msgs.append(f"Abrindo {label} ({binary}).")
        except Exception as exc:
            msgs.append(f"AVISO: {binary!r} não abriu ({exc}) — vá até {tele_dir}.")
    return msgs
