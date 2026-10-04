from curio.stages.visual_contracts import SearchPlan, SearchQuery


def controlled_search_plan(scene_id, queries, generic=()):
    generic = {str(query).casefold() for query in generic}
    return SearchPlan(scene_id, tuple(
        SearchQuery(str(query), source="test_fixture", level=index + 1,
                    generic=str(query).casefold() in generic)
        for index, query in enumerate(queries)))


def patch_search_plan(monkeypatch, visual, queries, generic=()):
    def build(plan, _genre=""):
        items = queries(plan) if callable(queries) else queries
        return controlled_search_plan(plan.scene_id, items, generic)

    monkeypatch.setattr(visual, "build_search_plan", build)


def plan_queries(scene, genre=""):
    from curio.stages.visual_planning import build_visual_plan
    from curio.stages.search_planning import build_search_plan

    semantic_scene = (scene.semantic_scene()
                      if hasattr(scene, "semantic_scene") else scene)
    plan = build_visual_plan(semantic_scene)
    search_plan = build_search_plan(plan, genre)
    return ([item.query for item in search_plan.queries],
            set(search_plan.generic_queries))
