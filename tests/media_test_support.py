"""Explicit media-selection fixtures for MediaStageResult contract tests."""

from copy import deepcopy

from curio.stages.media_selection import SelectionDecision


def with_selection(row: dict) -> dict:
    """Attach a truthful minimal decision to a persisted media fixture."""
    result = deepcopy(row)
    scene_id = result["chapter_id"]
    asset = result.get("asset")
    if not isinstance(asset, dict):
        asset = None
    provider = str((asset or {}).get("provider", ""))
    status = "synthetic" if provider == "synth" else "real" if asset else "none"
    decision = SelectionDecision(
        scene_id=scene_id, status=status,
        asset_id=str((asset or {}).get("asset_id", "")), provider=provider,
        fallback_level="fixture",
        reason="fixture selected an asset" if asset else "fixture has no asset",
    ).to_dict()
    audit = result.get("visual_decision")
    audit = deepcopy(audit) if isinstance(audit, dict) else {}
    audit["selection"] = decision
    result["visual_decision"] = audit
    return result
