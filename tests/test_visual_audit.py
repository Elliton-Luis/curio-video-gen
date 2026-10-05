from curio.stages.visual_audit import candidate_audit_rows


def test_candidate_audit_projects_selected_reused_and_rejected_reasons():
    evaluated = [
        {"query": "Ottoman map", "score": 82,
         "asset": {"provider": "wikimedia", "asset_id": "map-1",
                   "title": "Ottoman map", "source_url": "https://example/map"},
         "score_detail": {"topic_relevance": 100, "scene_relevance": 76,
                          "topic_evidence": {"topic": ["Ottoman"]}}},
        {"query": "Janissary portrait", "score": 20, "asset": {
            "provider": "met", "asset_id": "portrait-1", "title": "Portrait"},
         "score_detail": {"semantic_rejection": "scene evidence too weak"}},
    ]
    picked = [{"asset": evaluated[0]["asset"],
               "reuse_reason": "fresh_search_and_synthetic_exhausted"}]

    rows = candidate_audit_rows(
        evaluated, [{"title": "Portrait", "reason": "technical gate"}],
        picked, {"Ottoman map": 2}, min_score=50)

    assert rows[0]["decision"] == "selected"
    assert rows[0]["reason"] == "reused only after fresh searches and local visual exhausted"
    assert rows[0]["query_level"] == 2
    assert rows[1]["decision"] == "rejected"
    assert rows[1]["reason"] == "scene evidence too weak"
    # A rejected item with an already audited title is not duplicated.
    assert [row["title"] for row in rows].count("Portrait") == 1


def test_candidate_audit_marks_below_threshold_without_semantic_reason():
    rows = candidate_audit_rows(
        [{"query": "Ottoman map", "score": 12, "asset": {"title": "Map"}}],
        [], [], {}, min_score=50)

    assert rows == [{
        "title": "Map", "provider": "", "query": "Ottoman map", "query_level": 3,
        "topic_relevance": None, "scene_relevance": None, "score": 12,
        "bonus": 0, "clip_score": None, "creator": "", "source_url": "",
        "date_created": "", "media_type": "image", "metadata_support": 0.0,
        "topic_evidence": {}, "scene_evidence": {}, "decision": "rejected",
        "reason": "score below threshold",
    }]
