from curio.stages import nvidia, script, subs, visual_beats
from curio.metrics import RunMetrics


def test_visual_beats_cover_duration_without_adding_assets():
    beats = visual_beats.plan(8.4, start=2.0)

    assert len(beats) == 4
    assert beats[0]["start"] == 2.0
    assert beats[-1]["end"] == 10.4
    assert all(1.5 <= beat["end"] - beat["start"] <= 2.5
               for beat in beats)
    assert [beat["motion"] for beat in beats] == [
        "zoom", "pan_left", "pan_right", "reframe"]
    assert visual_beats.average_seconds(beats) == 2.1


def test_metrics_count_beat_pacing_and_asset_reuse():
    metrics = RunMetrics("slug", "idea", "script")
    chapters = [
        type("Chapter", (), {"id": index, "start": index * 4.2,
                              "end": (index + 1) * 4.2})
        for index in range(2)
    ]
    media_scenes = [
        {"chapter_id": index,
         "assets": [{"asset": {"asset_id": "same-asset"}}]}
        for index in range(2)
    ]

    metrics.visual_plan(chapters, media_scenes, visual_beats.BEAT_SECONDS)

    assert metrics.visual_scene_count == 2
    assert metrics.visual_beat_count == 4
    assert metrics.visual_asset_uses == 4
    assert metrics.visual_asset_ids == {"same-asset"}


def test_short_subtitle_cues_keep_case_and_highlight():
    words = [
        {"text": text, "start": index * 0.4, "end": index * 0.4 + 0.3}
        for index, text in enumerate(["São", "Bento", "nasceu", "em", "Núrsia"])
    ]

    cues = subs.cues_from_words(words, max_words=5, upper=False, highlight="none")

    assert all(len(cue[2].split()) <= 5 for cue in cues)
    assert "São" in cues[0][2]
    assert "SÃO" not in cues[0][2]
    assert "\\c" not in cues[0][2]


def test_subtitle_safe_area_and_ass_margin():
    assert subs.safe_subtitle_margin(1920, 100) == 422
    ass = subs.cues_to_ass([(0.0, 1.0, "São Bento")], 1080, 1920,
                           64, 100)

    assert "Default,DejaVu Sans,64" in ass
    assert ",2,120,120,422,1\n" in ass


def test_script_prompts_allow_content_led_45_to_90_seconds():
    for prompt, phrases in (
        (nvidia.SCRIPT_SYSTEM_PROMPT, ("45–90s", "perto de 60s", "Não invente twist")),
        (nvidia.SCRIPT_SYSTEM_PROMPT_EN,
         ("45–90 seconds", "near 60", "Never invent a twist")),
    ):
        for phrase in phrases:
            assert phrase in prompt


def test_local_fallback_closes_without_generic_question_or_cta():
    for language, forbidden in (
        ("pt-BR", ("Deixe seu like", "o que mais você quer saber")),
        ("en-US", ("Leave a like", "what else do you want to know")),
    ):
        text = script._template_script("A ideia", None, language)
        assert not any(phrase.lower() in text.lower() for phrase in forbidden)
