"""Visual intent and topic/scene evidence must survive planning and fallback."""

from types import SimpleNamespace

import pytest

from curio.config import CurioConfig
from curio.media.providers import MediaAsset
from curio.stages import media_acquisition, media_search, scenes, scoring, visual
from curio.stages.visual_context import attach_video_context
from tests.test_support.search_plan import patch_search_plan, plan_queries


def _chapter(topic, event, entity, representation):
    return scenes.Chapter(
        1, "A cena descreve o evento.", 5,
        visual_queries=[representation],
        visual_intent_structured=f"Show {representation}",
        subject=entity, primary_entity=entity, event=event,
        representations=[{"query": representation, "kind": "event", "level": 1}],
        video_context={"topic": topic, "primary_entities": [entity],
                       "secondary_entities": [], "events": [event],
                       "places": [], "aliases": [], "period": ""})


def test_media_acquisition_rejects_chapter_at_semantic_boundary():
    chapter = scenes.Chapter(id=1, narration="A cena descreve o evento.",
                             duration_estimate=5)
    with pytest.raises(TypeError, match="SemanticScene"):
        visual.fetch_media_multi([chapter], None)


@pytest.mark.parametrize("topic,scene,entity,representation,distractor", [
    ("French Revolution", "Storming of the Bastille", "Bastille",
     "Storming of the Bastille 1789", "French bulldog"),
    ("Roman Empire", "Marcomannic Wars", "Marcus Aurelius",
     "Marcus Aurelius Marcomannic Wars", "Roman souvenir product"),
    ("Mercury planet", "Mercury surface", "Mercury planet",
     "Mercury planet surface", "Mercury automobile"),
    ("Java programming language", "Java bytecode", "Java language",
     "Java programming language bytecode", "Java island coffee"),
    ("mass physics", "gravitational mass", "mass in physics",
     "mass physics gravitational field", "Mass station bus"),
    ("Marcus Aurelius", "Roman emperor", "Marcus Aurelius",
     "Marcus Aurelius equestrian statue", "Fabio Aurelio footballer"),
])
def test_complete_phrase_evidence_separates_ambiguous_referents(
        topic, scene, entity, representation, distractor):
    ch = _chapter(topic, scene, entity, representation)
    good = scoring.semantic_relevance({"title": representation}, ch)
    bad = scoring.semantic_relevance({"title": distractor}, ch)
    assert good["topic_relevance"] == 100
    assert good["scene_relevance"] == 100
    assert bad["topic_relevance"] == 0
    assert bad["scene_relevance"] == 0


def test_new_doppler_topic_needs_no_project_lexicon_entry():
    from curio.textnorm import PT_LEXICON, PT_TOPIC_PHRASES
    assert "doppler" not in PT_LEXICON
    assert "doppler effect" not in PT_TOPIC_PHRASES


def test_used_contextual_asset_does_not_stop_scene_representation_search(
        monkeypatch, tmp_path):
    assets = {
        "map": MediaAsset(provider="fixture", asset_id="map", title="Ottoman Empire map",
                           download_url="https://fixture.test/map.jpg", license="CC0",
                           width=2400, height=1800),
        "event-a": MediaAsset(provider="fixture", asset_id="event-a",
                               title="Ottoman Empire Siege of Constantinople 1453",
                               download_url="https://fixture.test/a.jpg", license="CC0",
                               width=2400, height=1800),
        "event-b": MediaAsset(provider="fixture", asset_id="event-b",
                               title="Ottoman Empire Battle of Mohacs 1526",
                               download_url="https://fixture.test/b.jpg", license="CC0",
                               width=2400, height=1800),
    }

    class Provider:
        name = "fixture"
        def search(self, query, *args, **kwargs):
            specific = "event-a" if "Constantinople" in query else (
                "event-b" if "Mohacs" in query else None)
            return [assets["map"], *([assets[specific]] if specific else [])]

    chapters = [
        _chapter("Ottoman Empire", "Siege of Constantinople", "Constantinople",
                 "Siege of Constantinople 1453"),
        _chapter("Ottoman Empire", "Battle of Mohacs", "Mohacs",
                 "Battle of Mohacs 1526"),
    ]
    for chapter in chapters:
        chapter.set_visual_queries(
            [chapter.representations[0]["query"]], source="test_fixture")
        chapter.narration = chapter.event
    patch_search_plan(monkeypatch, visual, lambda plan: [
        "Ottoman Empire map", plan.representations[0].query])
    monkeypatch.setattr(media_acquisition, "downloaded_dimensions_valid", lambda *_: True)
    for candidate in assets.values():
        candidate.local_path = str(tmp_path / f"{candidate.asset_id}.jpg")
        (tmp_path / f"{candidate.asset_id}.jpg").write_bytes(
            candidate.asset_id.encode())
    uses = {}
    selected = []
    for chapter in chapters:
        result, _ = visual._search_scene_with_shortcircuit(
            chapter, [Provider()], CurioConfig(), 1, None, str(tmp_path),
            asset_uses=uses)
        selected.append(result[0]["asset"]["asset_id"])
    assert selected == ["event-a", "event-b"]


def test_no_fresh_candidate_uses_local_synthetic_before_reuse(monkeypatch, tmp_path):
    asset = MediaAsset(provider="fixture", asset_id="only", title="Ottoman Empire map",
                       download_url="https://fixture.test/map.jpg", license="CC0",
                       width=2400, height=1800,
                       local_path=str(tmp_path / "only.jpg"))
    (tmp_path / "only.jpg").write_bytes(b"image")

    class Provider:
        name = "fixture"
        def search(self, *_args, **_kwargs):
            return [asset]

    chapter = _chapter("Ottoman Empire", "Unpictured event", "Ottoman Empire",
                       "Ottoman Empire map")
    chapter.id = 2
    patch_search_plan(monkeypatch, visual, ["Ottoman Empire map"])
    monkeypatch.setattr(media_acquisition, "downloaded_dimensions_valid", lambda *_: True)
    synth = MediaAsset(provider="synth", asset_id="local", title="Local visual",
                       local_path="", width=1200, height=900)
    monkeypatch.setattr("curio.stages.visuals.render_fallback_plan",
                        lambda *args: synth)
    from curio.media.identity import asset_identity
    uses = {asset_identity(asset.to_dict()): 1}
    result, _ = visual._search_scene_with_shortcircuit(
        chapter, [Provider()], CurioConfig(), 1, None, str(tmp_path),
        asset_uses=uses)
    assert result[0]["asset"]["provider"] == "synth"

    monkeypatch.setattr("curio.stages.visuals.render_fallback_plan",
                        lambda *args: None)
    result, _ = visual._search_scene_with_shortcircuit(
        chapter, [Provider()], CurioConfig(), 1, None, str(tmp_path),
        asset_uses=uses)
    assert result[0]["asset"]["asset_id"] == "only"
    assert result[0]["assets"][0]["reuse_reason"] == (
        "fresh_search_and_synthetic_exhausted")


@pytest.mark.parametrize("topic,event,entity,representation,old_title", [
    ("French Revolution", "Storming of the Bastille", "Bastille",
     "Storming of the Bastille 1789", "File:Dog walker - Buenos Aires.jpg"),
    ("Marcus Aurelius", "Marcomannic Wars", "Marcus Aurelius",
     "Marcus Aurelius Marcomannic Wars",
     "File:Mughal Empire under Emperor Akbar the Great.jpg"),
    ("black hole", "event horizon", "black hole",
     "black hole event horizon illustration", "Mass station bus terminal"),
    ("Nikola Tesla", "alternating current", "Nikola Tesla",
     "Nikola Tesla alternating current motor", "File:Ponte das Correntes.jpg"),
])
def test_old_false_positive_titles_now_fail_semantic_gate(
        topic, event, entity, representation, old_title):
    chapter = _chapter(topic, event, entity, representation)
    details = scoring.base_score({"title": old_title}, chapter)
    assert details["score"] == 0
    assert details["semantic_rejection"] == "no topic evidence"


@pytest.mark.parametrize("old_subject,title,new_context", [
    ("dog", "File:Dog walker - Buenos Aires.jpg",
     ("French Revolution", "Storming of the Bastille", "Bastille",
      "Storming of the Bastille 1789")),
    ("mass", "Mass station bus terminal",
     ("black hole", "event horizon", "black hole",
      "black hole event horizon illustration")),
    ("empire", "Mughal Empire under Emperor Akbar",
     ("Marcus Aurelius", "Marcomannic Wars", "Marcus Aurelius",
      "Marcus Aurelius Marcomannic Wars")),
])
def test_replay_measured_false_positives_before_and_after(
        old_subject, title, new_context):
    legacy = SimpleNamespace(subject=old_subject, visual_queries=[],
                             visual_entities=[], context=[], narration="")
    old_score = scoring.base_score({"title": title}, legacy)["score"]
    topic, event, entity, representation = new_context
    current = _chapter(topic, event, entity, representation)
    new_score = scoring.base_score({"title": title}, current)
    assert old_score >= scoring.threshold()
    assert new_score["score"] == 0


def test_provider_metadata_is_audited_but_creator_cannot_prove_scene():
    chapter = _chapter("French Revolution", "Storming of the Bastille",
                       "Bastille", "Storming of the Bastille 1789")
    creator_only = scoring.semantic_relevance({
        "title": "Untitled artwork", "author": "Storming of the Bastille",
        "provider": "wikimedia", "source_url": "https://commons.wikimedia.org/item",
    }, chapter)
    assert creator_only["topic_relevance"] == 0
    supported = scoring.semantic_relevance({
        "title": "Untitled artwork", "description": "Storming of the Bastille 1789",
        "author": "Artist Name", "provider": "wikimedia",
        "source_url": "https://commons.wikimedia.org/item",
        "date_created": "1789", "media_type": "engraving",
    }, chapter)
    assert supported["scene_relevance"] == 90
    assert supported["scene_evidence"]["Storming of the Bastille 1789"] == ["description"]
    assert supported["provider"] == "wikimedia"
    assert supported["creator"] == "Artist Name"
    assert supported["source_url"].startswith("https://")


def test_original_language_representation_accepts_correct_archive_title():
    chapter = _chapter("French Revolution", "Storming of the Bastille",
                       "Bastille", "Storming of the Bastille 1789")
    chapter.representations.append({"query": "Prise de la Bastille",
                                    "kind": "event_alias", "level": 2})
    info = scoring.base_score(
        {"title": "File:Prise de la Bastille clean.jpg"}, chapter)
    assert info["topic_relevance"] == 100
    assert info["scene_relevance"] == 100
    assert info["score"] >= scoring.threshold()


def test_topic_description_alone_does_not_claim_exact_scene_depiction():
    chapter = _chapter("Mercury planet", "Mercury surface", "Mercury planet",
                       "Mercury planet surface map")
    chapter.representations.append({"query": "Mercury planet MESSENGER",
                                    "kind": "mission_artifact", "level": 2})
    candidate = {"title": "KSC-04pd1531", "description":
                 "MESSENGER (Mercury Surface, Space Environment) mission",
                 "media_type": "image"}
    detail = scoring.semantic_relevance(candidate, chapter)
    assert detail["topic_relevance"] == 90
    assert detail["scene_relevance"] == 35
    assert detail["scene_matches"] == ["contextual representation:mission"]


def test_specific_mapping_ranks_above_mission_poster_fallback():
    chapter = _chapter("Mercury planet", "Mercury surface", "Mercury planet",
                       "Mercury planet surface map")
    chapter.representations.append({"query": "Mercury planet MESSENGER",
                                    "kind": "mission_artifact", "level": 2})
    mapping = scoring.semantic_relevance({
        "title": "Mapping Potassium (Mercury, MESSENGER)",
        "description": "The instrument measured elemental composition of Mercury surface materials.",
    }, chapter)
    mission_poster = scoring.semantic_relevance({
        "title": "KSC-04pd1531",
        "description": "MESSENGER (Mercury Surface, Space Environment) mission",
    }, chapter)
    assert mapping["scene_relevance"] == 50
    assert mission_poster["scene_relevance"] == 35
    assert mapping["scene_relevance"] > mission_poster["scene_relevance"]


def test_topic_context_and_representation_survive_local_planner_fallback():
    scene = scenes.build_local_semantic_scenes(
        "A Bastilha foi tomada. O evento mudou Paris.", 2).semantic_scenes[0]
    scene = attach_video_context((scene,), "Guerra dos Cem Anos")[0]
    queries, _ = plan_queries(scene, "history")
    assert queries[0] == "Guerra dos Cem Anos"
    assert "Guerra dos Cem Anos Guerra dos Cem Anos" not in queries
    assert "Guerra dos Cem Anos" in queries
    assert scene.video_context["topic"] == "Guerra dos Cem Anos"


def test_structured_plan_never_adds_narration_keywords_to_queries():
    chapter = _chapter("Doppler effect", "frequency shift", "Doppler effect",
                       "Doppler effect wave diagram")
    chapter.narration = "Narration describes Doppler frequency changing."
    queries, _ = plan_queries(chapter, "science")
    assert "Doppler effect wave diagram" in queries
    assert "narration" not in queries
    assert "describes" not in queries
    assert "frequency" not in queries


def test_repair_scene_count_merges_without_losing_narration_or_representations():
    first = scenes.SemanticScene(
        1, "Primeira frase.", subject="same subject",
        representations=({"query": "first event", "level": 1},))
    second = scenes.SemanticScene(
        2, "Segunda frase.", subject="same subject",
        representations=({"query": "second event", "level": 1},))
    third = scenes.SemanticScene(3, "Terceira frase.")
    planned = [first, second, third]
    assert scenes._repair_scene_count(planned, 2)
    assert len(planned) == 2
    assert " ".join(scene.narration for scene in planned) == \
        "Primeira frase. Segunda frase. Terceira frase."
    assert {r.query for r in planned[0].representations} == {
        "first event", "second event"}
    assert [scene.id for scene in planned] == [1, 2]


def test_scene_count_completion_splits_only_shared_declared_anchor():
    scene = scenes.SemanticScene(
        1, "Marcus Aurelius crossed the Danube. Marcus Aurelius led the army.",
        subject="Marcus Aurelius", primary_entity="Marcus Aurelius",
        representations=({"query": "Marcus Aurelius", "level": 1},))
    planned = [scene]
    assert scenes._repair_scene_count(planned, 2)
    assert len(planned) == 2
    assert all(item.primary_entity == "Marcus Aurelius" for item in planned)


def test_planner_near_match_repairs_source_spans_then_repairs_excess_count(monkeypatch):
    script = ("Parisian citizens stormed the Bastille. "
              "The king lost control of the capital. "
              "The revolution changed France.")
    payload = {"video_context": {"topic": "French Revolution",
                                 "events": ["Storming of the Bastille"]},
               "scenes": [
                   {"narration": "Citizens attacked the Bastille.",
                    "subject": "Bastille", "event": "Storming of the Bastille",
                    "representations": [{"query": "Storming of the Bastille 1789",
                                          "kind": "event", "level": 1}]},
                   {"narration": "The king lost capital control.",
                    "subject": "French Revolution",
                    "representations": [{"query": "French Revolution outcomes",
                                          "kind": "event", "level": 2}]},
                   {"narration": "The revolution changed France.",
                    "subject": "French Revolution",
                    "representations": [{"query": "French Revolution outcomes",
                                          "kind": "event", "level": 2}]},
               ]}
    monkeypatch.setattr(scenes.nvidia_stage, "any_llm_available", lambda: True)
    monkeypatch.setattr(scenes.nvidia_stage, "complete_json",
                        lambda *_args, **_kwargs: (payload, "test:model"))
    plan = scenes.build_semantic_scenes(
        script, CurioConfig(), n_scenes=2)
    chapters = plan.semantic_scenes
    assert plan.source == "test"
    assert len(chapters) == 2
    assert " ".join(ch.narration for ch in chapters) == script
    assert chapters[0].video_context["topic"] == "French Revolution"
    assert chapters[0].representations
    assert chapters[0].visual_queries


def test_scene_funnel_rejects_topic_only_distractor_and_records_reason(
        tmp_path, monkeypatch):
    from curio.metrics import RunMetrics

    ch = _chapter("French Revolution", "Storming of the Bastille", "Bastille",
                  "Storming of the Bastille 1789")
    candidates = [
        MediaAsset("wikimedia", "dog", title="French bulldog portrait",
                   download_url="https://cdn.test/dog.jpg", width=1920, height=1280,
                   license="CC BY 4.0"),
        MediaAsset("wikimedia", "event", title="Storming of the Bastille 1789",
                   download_url="https://cdn.test/event.jpg", width=1920, height=1280,
                   license="CC BY 4.0"),
    ]

    class Provider:
        name = "wikimedia"

        def search(self, *_args, **_kwargs):
            return candidates

    local = tmp_path / "candidate.jpg"
    local.write_bytes(b"x" * 20000)

    def download(asset, *_args, **_kwargs):
        asset.local_path = str(local)
        return asset

    monkeypatch.setattr(media_acquisition, "download_asset", download)
    monkeypatch.setattr(media_acquisition, "downloaded_dimensions_valid", lambda _asset: True)
    monkeypatch.setattr(media_search, "SEARCH_TIMEOUT", 2)
    cfg = SimpleNamespace(cache_dir=str(tmp_path), language="en-US")
    metric = RunMetrics("session", "topic", "narration")
    result, _ = visual._search_scene_with_shortcircuit(
        ch, [Provider()], cfg, 1, metric, str(tmp_path))
    scene = result[0]
    assert scene["asset"]["asset_id"] == "event"
    assert scene["visual_decision"]["topic"] == "French Revolution"
    assert scene["visual_decision"]["selected"]["scene_relevance"] == 100
    assert any(c["title"] == "French bulldog portrait"
               and c["decision"] == "rejected"
               for c in scene["visual_decision"]["candidates"])


def test_zero_score_threshold_never_bypasses_semantic_rejection(tmp_path, monkeypatch):
    ch = _chapter("French Revolution", "Storming of the Bastille", "Bastille",
                  "Storming of the Bastille 1789")
    candidate = MediaAsset("wikimedia", "dog", title="French bulldog portrait",
                           download_url="https://cdn.test/dog.jpg", width=1920,
                           height=1280, license="CC BY 4.0")

    class Provider:
        name = "wikimedia"

        def search(self, *_args, **_kwargs):
            return [candidate]

    monkeypatch.setenv("CURIO_MEDIA_SCORE_MIN", "0")
    result, _ = visual._search_scene_with_shortcircuit(
        ch, [Provider()], SimpleNamespace(cache_dir=str(tmp_path), language="en-US"),
        1, None, str(tmp_path))
    assert result[0]["asset"]["provider"] == "synth"
    assert any(item["title"] == "French bulldog portrait"
               and item["reason"] == "no topic evidence"
               for item in result[0]["visual_decision"]["candidates"])


def test_post_download_resolution_failure_is_audited_and_falls_back_safely(
        tmp_path, monkeypatch):
    ch = _chapter("Mercury planet", "Mercury surface", "Mercury planet",
                  "Mercury planet surface map")
    ch.representations.append({"query": "Mercury planet MESSENGER",
                               "kind": "mission_artifact", "level": 2})
    assets = [
        MediaAsset("nasa", "poster", title="KSC-04pd1531",
                   description="MESSENGER (Mercury Surface, Space Environment) mission",
                   download_url="https://cdn.test/poster.jpg", width=1920, height=1280,
                   license="Domínio público (NASA)"),
        MediaAsset("nasa", "map", title="Mapping Potassium (Mercury, MESSENGER)",
                   description="Mercury surface materials, abundance map",
                   download_url="https://cdn.test/map.jpg", width=1920, height=1280,
                   license="Domínio público (NASA)"),
    ]

    class Provider:
        name = "nasa"

        def search(self, *_args, **_kwargs):
            return assets

    def download(asset, *_args, **_kwargs):
        path = tmp_path / f"{asset.asset_id}.jpg"
        path.write_bytes(b"x" * 20000)
        asset.local_path = str(path)
        return asset

    monkeypatch.setattr(media_acquisition, "download_asset", download)
    monkeypatch.setattr(media_acquisition, "downloaded_dimensions_valid",
                        lambda asset: asset.asset_id != "map")
    output, _ = visual._search_scene_with_shortcircuit(
        ch, [Provider()], SimpleNamespace(cache_dir=str(tmp_path), language="en-US"),
        1, None, str(tmp_path))
    scene = output[0]
    assert scene["asset"]["asset_id"] == "poster"
    map_audit = next(x for x in scene["visual_decision"]["candidates"]
                     if x["title"].startswith("Mapping Potassium"))
    assert map_audit["decision"] == "rejected"
    assert map_audit["reason"] == "resolution/legibility after download"


@pytest.mark.parametrize("topic,event,entity,representation,distractor", [
    ("Julius Caesar", "Crossing of the Rubicon", "Julius Caesar",
     "Julius Caesar crossing the Rubicon", "Julius Caesar salad product"),
    ("Marcus Aurelius", "Marcomannic Wars", "Marcus Aurelius",
     "Marcus Aurelius during the Marcomannic Wars", "Fabio Aurelio footballer"),
    ("black hole", "event horizon", "black hole",
     "black hole event horizon illustration", "bus station mass platform"),
    ("Mercury planet", "Mercury surface", "Mercury planet",
     "Mercury planet surface map", "Mercury automobile"),
    ("Doppler effect", "frequency shift", "Doppler effect",
     "Doppler effect wave diagram", "Doppler radar detector product"),
])
def test_end_to_end_funnel_for_known_ambiguous_and_new_topics(
        tmp_path, monkeypatch, topic, event, entity, representation, distractor):
    from curio.metrics import RunMetrics

    ch = _chapter(topic, event, entity, representation)
    ch.planning_mode = "deterministic"
    ch.global_visual_queries = [topic]
    candidates = [
        MediaAsset("wikimedia", "wrong", title=distractor,
                   download_url="https://cdn.test/wrong.jpg", width=1920, height=1280,
                   license="CC BY 4.0"),
        MediaAsset("wikimedia", "right", title=representation,
                   download_url="https://cdn.test/right.jpg", width=1920, height=1280,
                   license="CC BY 4.0"),
    ]

    class Provider:
        name = "wikimedia"

        def search(self, *_args, **_kwargs):
            return candidates

    local = tmp_path / "shortlist.jpg"
    local.write_bytes(b"x" * 20000)
    monkeypatch.setattr(media_acquisition, "download_asset",
                        lambda asset, *_args, **_kwargs: _set_local(asset, local))
    monkeypatch.setattr(media_acquisition, "downloaded_dimensions_valid", lambda _asset: True)
    cfg = SimpleNamespace(cache_dir=str(tmp_path), language="en-US")
    scenes_out, _ = visual._search_scene_with_shortcircuit(
        ch, [Provider()], cfg, 1, RunMetrics("session", topic, "narration"),
        str(tmp_path))
    scene = scenes_out[0]
    assert scene["asset"]["asset_id"] == "right", topic
    assert any(item["title"] == distractor and item["decision"] == "rejected"
               for item in scene["visual_decision"]["candidates"]), topic


def _set_local(asset, path):
    asset.local_path = str(path)
    return asset


def test_clip_cpu_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("CURIO_CLIP_ENABLED", "true")
    monkeypatch.delenv("CURIO_CLIP_DEVICE", raising=False)
    monkeypatch.delenv("CURIO_CLIP_ALLOW_CPU", raising=False)
    monkeypatch.setattr(scoring, "clip_device", lambda: "cpu")
    assert scoring.clip_cpu_allowed() is False
    monkeypatch.setenv("CURIO_CLIP_DEVICE", "cpu")
    assert scoring.clip_cpu_allowed() is True


def test_clip_only_reranks_approved_shortlist(tmp_path, monkeypatch):
    from curio.metrics import RunMetrics

    ch = _chapter("French Revolution", "Storming of the Bastille", "Bastille",
                  "Storming of the Bastille 1789")
    candidates = [
        MediaAsset("wikimedia", "lower", title="Storming of the Bastille 1789 engraving",
                   download_url="https://cdn.test/lower.jpg", width=1920, height=1280,
                   license="CC BY 4.0"),
        MediaAsset("wikimedia", "higher", title="Storming of the Bastille 1789 painting",
                   download_url="https://cdn.test/higher.jpg", width=1920, height=1280,
                   license="CC BY 4.0"),
        MediaAsset("wikimedia", "wrong", title="French bulldog portrait",
                   download_url="https://cdn.test/wrong.jpg", width=1920, height=1280,
                   license="CC BY 4.0"),
    ]

    class Provider:
        name = "wikimedia"

        def search(self, *_args, **_kwargs):
            return candidates

    def download(asset, *_args, **_kwargs):
        path = tmp_path / f"{asset.asset_id}.jpg"
        path.write_bytes(b"x" * 20000)
        asset.local_path = str(path)
        return asset

    monkeypatch.setattr(media_acquisition, "download_asset", download)
    monkeypatch.setattr(media_acquisition, "downloaded_dimensions_valid", lambda _asset: True)
    monkeypatch.setattr(scoring, "clip_enabled", lambda _cfg=None: True)
    monkeypatch.setattr(scoring, "clip_status", lambda _cfg=None: "habilitada (device=cpu)")
    monkeypatch.setattr(scoring, "clip_device", lambda _cfg=None: "cpu")
    monkeypatch.setattr(scoring, "clip_score_image",
                        lambda path, _ch, _cfg=None: .9 if path.endswith("higher.jpg") else -.2)
    metrics = RunMetrics("s", "French Revolution", "narration")
    output, _ = visual._search_scene_with_shortcircuit(
        ch, [Provider()], SimpleNamespace(cache_dir=str(tmp_path), language="en-US"),
        1, metrics, str(tmp_path))
    assert output[0]["asset"]["asset_id"] == "higher"
    assert output[0]["visual_decision"]["candidates"]
    assert metrics.media_layers_used["clip"] == 1


def test_optional_clip_encoder_scores_shortlisted_image_without_real_model(
        tmp_path, monkeypatch):
    from contextlib import nullcontext
    import sys
    import types

    class Result:
        def item(self):
            return 0.42

    class Tensor:
        @property
        def T(self):
            return self

        def unsqueeze(self, *_args):
            return self

        def to(self, *_args):
            return self

        def norm(self, **_kwargs):
            return self

        def __itruediv__(self, _other):
            return self

        def __matmul__(self, _other):
            return Result()

    class Model:
        def eval(self):
            pass

        def encode_image(self, _image):
            return Tensor()

        def encode_text(self, _text):
            return Tensor()

    from PIL import Image
    image_path = tmp_path / "shortlist.jpg"
    Image.new("RGB", (8, 8), "red").save(image_path)
    fake_torch = types.SimpleNamespace(inference_mode=nullcontext)
    fake_open_clip = types.SimpleNamespace(
        create_model_and_transforms=lambda *_a, **_k: (Model(), None, lambda _image: Tensor()),
        get_tokenizer=lambda _name: lambda _texts: Tensor())
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "open_clip", fake_open_clip)
    monkeypatch.setattr(scoring, "clip_enabled", lambda _cfg=None: True)
    monkeypatch.setattr(scoring, "clip_device", lambda _cfg=None: "cpu")
    monkeypatch.setattr(scoring, "clip_cpu_allowed", lambda _cfg=None: True)
    monkeypatch.setattr(scoring, "_CLIP_RUNTIME", None)
    ch = _chapter("Doppler effect", "frequency shift", "Doppler effect",
                  "Doppler effect wave diagram")
    assert scoring.clip_score_image(str(image_path), ch,
                                    SimpleNamespace(visual_clip_enabled=True)) == .42
