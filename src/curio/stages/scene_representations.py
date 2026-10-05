"""Normalize and validate visual representation data at scene boundaries."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .. import textnorm
from .scene_contract import VisualRepresentation


def _coerce_representations(raw) -> list[VisualRepresentation]:
    """Normalize visual representations without splitting their phrases."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:8]:
        if isinstance(item, Mapping):
            query = str(item.get("query", item.get("visual", item.get("name", ""))) or "").strip()
            if query:
                kind = str(item.get("kind", "related") or "related").lower()
                if _representation_rejection_reason(query, kind):
                    continue
                try:
                    level = int(item.get("level", len(out)) or 0)
                except (TypeError, ValueError):
                    level = len(out)
                out.append(VisualRepresentation(
                    query=query,
                    kind=str(item.get("kind", "related") or "related"),
                    level=max(0, level),
                    source=str(item.get("source", "planner") or "planner"),
                    evidence=str(item.get("evidence", "") or "")))
        else:
            query = str(item or "").strip()
            if query and not _representation_rejection_reason(query, "related"):
                out.append(VisualRepresentation(query=query, level=len(out)))
    return out


def _validate_query_list(raw) -> tuple[list[str], list[dict]]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return [], []
    accepted, rejected = [], []
    for value in raw[:12]:
        query = str(value or "").strip()
        reason = _representation_rejection_reason(query, "related")
        if reason:
            rejected.append({"query": query, "kind": "related", "reason": reason})
        elif query and query.casefold() not in {item.casefold() for item in accepted}:
            accepted.append(query)
    return accepted, rejected


_VISUAL_ORDINALS = {"primeira", "primeiro", "segunda", "segundo", "first",
                    "second", "third", "initial", "next", "former"}
_VISUAL_ABSTRACTIONS = {"gold", "ouro", "power", "elite"}


def _representation_rejection_reason(query: str, kind: str) -> str:
    """Reject isolated narration fragments before they become search anchors."""
    folded = textnorm.fold_phrase(query)
    words = folded.split()
    if len(words) == 1 and folded in _VISUAL_ORDINALS:
        return "isolated_ordinal"
    if len(words) == 1 and folded in _VISUAL_ABSTRACTIONS:
        return "isolated_abstract_or_material"
    if len(words) == 1 and re.search(
            r"(?:avam|ariam|eram|iram|ando|endo|indo|aram|ou|eu|iu)$", folded):
        return "isolated_inflected_verb"
    if len(words) == 1 and kind in {"related", "entity"} and folded in textnorm.VISUAL_STOP_PT:
        return "isolated_stopword"
    return ""


def _rejected_representations(raw) -> list[dict]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    rejected = []
    for item in raw[:20]:
        query = str(item.get("query", item.get("visual", item.get("name", "")))
                    if isinstance(item, dict) else item or "").strip()
        kind = str(item.get("kind", "related") or "related") if isinstance(item, dict) else "related"
        reason = _representation_rejection_reason(query, kind)
        if reason:
            rejected.append({"query": query, "kind": kind, "reason": reason})
    return rejected



def _local_representation_rejections(narration: str) -> list[dict]:
    rejected = []
    for word in re.findall(r"[A-Za-zÀ-ÿ]+", narration):
        normalized = textnorm.fold_phrase(word)
        reason = _representation_rejection_reason(normalized, "related")
        if reason and not any(row["query"] == normalized for row in rejected):
            rejected.append({"query": normalized, "kind": "related", "reason": reason})
    return rejected[:20]

