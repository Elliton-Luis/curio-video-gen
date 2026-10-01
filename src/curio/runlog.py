"""Log estruturado por execução. Stdlib, JSONL, flush após cada evento."""

from __future__ import annotations

import contextvars
import json
import os
import re
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_CURRENT: contextvars.ContextVar["RunLog | None"] = contextvars.ContextVar(
    "curio_run_log", default=None)
_SECRET_NAME = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.I)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_QUERY_SECRET = re.compile(
    r"(?i)([?&][^=&]*(?:key|token|secret|signature|credential|authorization)"
    r"[^=&]*=)[^&#\s]+")
_ASSIGN_SECRET = re.compile(
    r"(?i)((?:api[_-]?key|token|secret|password|authorization|credential)\s*[=:]\s*)"
    r"[^\s,;]+")
_PRIVATE_FIELD = re.compile(
    r"(?:prompt|response|payload|messages|api.?key|token|secret|password|authorization|credential)",
    re.I)


def safe_text(value: object) -> str:
    """Remove environment secrets and common credential forms."""
    text = str(value)
    for name, secret in os.environ.items():
        if _SECRET_NAME.search(name) and secret and len(secret) >= 4:
            for part in secret.split(","):
                if len(part) >= 4:
                    text = text.replace(part, "[REDACTED]")
    text = _BEARER.sub(r"\1[REDACTED]", text)
    text = _QUERY_SECRET.sub(r"\1[REDACTED]", text)
    text = _ASSIGN_SECRET.sub(r"\1[REDACTED]", text)
    return text[:4000]


def safe_value(value):
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, dict):
        return {safe_text(k): safe_value(v) for k, v in value.items()
                if not _PRIVATE_FIELD.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [safe_value(item) for item in value]
    return value


class RunLog:
    def __init__(self, path: str | Path, slug: str, on_event=None):
        self.path = Path(path)
        self.slug = slug
        self.run_id = uuid4().hex[:12]
        self.on_event = on_event
        self.stage = "startup"
        self._lock = threading.Lock()
        self._file = None
        self._token = None

    def __enter__(self) -> "RunLog":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("x", encoding="utf-8")
        self._token = _CURRENT.set(self)
        self.event("run_started", "Execução iniciada", slug=self.slug)
        return self

    def set_stage(self, stage: str) -> None:
        self.stage = stage

    def event(self, event: str, message: str, **details) -> bool:
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "slug": self.slug,
            "stage": self.stage,
            "event": event,
            "message": safe_text(message),
            "details": safe_value(details),
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            if self._file is not None:
                self._file.write(line + "\n")
                self._file.flush()
            if self.on_event is not None:
                try:
                    self.on_event(record)
                except Exception:
                    pass
        return True

    def __exit__(self, exc_type, exc, tb):
        if self._token is not None:
            _CURRENT.reset(self._token)
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None
        return False


def event(event: str, message: str, **details) -> bool:
    current = _CURRENT.get()
    if current is not None:
        return current.event(event, message, **details)
    return False


def active() -> bool:
    return _CURRENT.get() is not None


def format_exception(exc: BaseException) -> str:
    return safe_text("".join(traceback.format_exception(exc)))


def set_stage(stage: str) -> None:
    current = _CURRENT.get()
    if current is not None:
        current.set_stage(stage)


def current_log_path() -> str | None:
    current = _CURRENT.get()
    return str(current.path) if current is not None else None
