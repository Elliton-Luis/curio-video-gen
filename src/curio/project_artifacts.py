"""File I/O primitives for artifacts stored inside a Curio project."""

from __future__ import annotations

import json
import os
from typing import Any


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as stream:
        return stream.read()


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: str, data: Any) -> None:
    """Write project JSON, creating its parent directory if needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=1)
