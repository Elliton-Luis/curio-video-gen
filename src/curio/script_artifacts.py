"""Persistence contract for editable project script and title artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass

SCHEMA_VERSION = 2


def text_identity(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def input_identity(value: object) -> str:
    """Hash deterministic inputs to a generated project artifact."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    return text_identity(encoded)


@dataclass(frozen=True)
class ScriptArtifactsManifest:
    script_sha256: str
    script_origin: str
    title_sha256: str
    title_origin: str
    title_script_sha256: str | None
    script_input_sha256: str | None = None
    title_input_sha256: str | None = None

    def __post_init__(self) -> None:
        for value in (self.script_sha256, self.title_sha256):
            if not _is_sha256(value):
                raise ValueError("script artifact hashes must be SHA-256")
        if self.title_script_sha256 is not None and not _is_sha256(
                self.title_script_sha256):
            raise ValueError("title source script hash must be SHA-256")
        for value in (self.script_input_sha256, self.title_input_sha256):
            if value is not None and not _is_sha256(value):
                raise ValueError("script input hashes must be SHA-256")
        if not self.script_origin.strip() or not self.title_origin.strip():
            raise ValueError("script and title origins are required")

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "script": {"sha256": self.script_sha256,
                       "origin": self.script_origin,
                       "input_sha256": self.script_input_sha256},
            "title": {"sha256": self.title_sha256,
                      "origin": self.title_origin,
                      "script_sha256": self.title_script_sha256,
                      "input_sha256": self.title_input_sha256},
        }

    @classmethod
    def from_dict(cls, value: object) -> "ScriptArtifactsManifest":
        if not isinstance(value, dict) or value.get("schema_version") not in {1, SCHEMA_VERSION}:
            raise ValueError("unsupported script artifacts manifest")
        script, title = value.get("script"), value.get("title")
        if not isinstance(script, dict) or not isinstance(title, dict):
            raise ValueError("script artifacts manifest entries are required")
        return cls(
            script_sha256=_required_str(script, "sha256"),
            script_origin=_required_str(script, "origin"),
            title_sha256=_required_str(title, "sha256"),
            title_origin=_required_str(title, "origin"),
            title_script_sha256=title.get("script_sha256"),
            script_input_sha256=script.get("input_sha256"),
            title_input_sha256=title.get("input_sha256"))


def read_manifest(path: str) -> ScriptArtifactsManifest | None:
    try:
        with open(path, encoding="utf-8") as stream:
            return ScriptArtifactsManifest.from_dict(json.load(stream))
    except (OSError, ValueError, TypeError, KeyError):
        return None


def write_manifest(path: str, manifest: ScriptArtifactsManifest) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(manifest.to_dict(), stream, ensure_ascii=False, indent=1)
    os.replace(temporary, path)


def _required_str(value: dict, key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"script artifacts manifest {key} is required")
    return item


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
