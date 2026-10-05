"""Pure projection of evaluated visual candidates into the audit schema."""

from __future__ import annotations


def candidate_audit_rows(
    evaluated_entries: list[dict],
    rejected: list[dict],
    picked: list[dict],
    representation_levels: dict[str, int],
    min_score: float,
) -> list[dict]:
    """Project evaluation outcomes without changing selection or candidates."""
    rows = []
    for entry in evaluated_entries:
        detail = entry.get("score_detail", {})
        asset_data = entry.get("asset") or {}
        selected_item = next((item for item in picked
            if (item.get("asset", {}).get("provider"),
                item.get("asset", {}).get("asset_id")) ==
               (asset_data.get("provider"), asset_data.get("asset_id"))), None)
        was_selected = selected_item is not None
        score = entry.get("score", 0)
        semantic_rejection = detail.get("semantic_rejection")
        is_rejected = bool(entry.get("rejection_reason") or semantic_rejection
                           or score < min_score)
        if was_selected:
            reason = ("reused only after fresh searches and local visual exhausted"
                      if selected_item.get("reuse_reason") else
                      "selected by scene relevance, topic relevance, then quality")
            decision = "selected"
        else:
            reason = (entry.get("rejection_reason") or semantic_rejection or
                      ("score below threshold" if score < min_score else
                       "passed gate; ranked below image limit"))
            decision = "rejected" if is_rejected else "not_selected"
        rows.append({
            "title": str(asset_data.get("title", ""))[:160],
            "provider": asset_data.get("provider", ""),
            "query": entry.get("query", ""),
            "query_level": representation_levels.get(
                entry.get("query", ""), 5 if entry.get("generic") else 3),
            "topic_relevance": detail.get("topic_relevance"),
            "scene_relevance": detail.get("scene_relevance"),
            "score": score,
            "bonus": detail.get("bonus", 0),
            "clip_score": entry.get("clip_score"),
            "creator": str(asset_data.get("author", ""))[:120],
            "source_url": str(asset_data.get("source_url", ""))[:300],
            "date_created": asset_data.get("date_created", ""),
            "media_type": asset_data.get("media_type", "image"),
            "metadata_support": detail.get("metadata_support", 0.0),
            "topic_evidence": detail.get("topic_evidence", {}),
            "scene_evidence": detail.get("scene_evidence", {}),
            "decision": decision,
            "reason": reason,
        })

    rows.extend({
        "title": item.get("title", ""),
        "provider": item.get("provider", ""),
        "query": item.get("query", ""),
        "topic_relevance": item.get("topic_relevance"),
        "scene_relevance": item.get("scene_relevance"),
        "creator": str((item.get("asset") or {}).get("author", ""))[:120],
        "source_url": str((item.get("asset") or {}).get("source_url", ""))[:300],
        "date_created": (item.get("asset") or {}).get("date_created", ""),
        "media_type": (item.get("asset") or {}).get("media_type", "image"),
        "decision": "rejected",
        "reason": item.get("reason", ""),
    } for item in rejected if not any(
        row["title"] == item.get("title") for row in rows))
    return rows[:40]
