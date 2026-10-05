from curio import pipeline, tui
from curio.cli import build_parser
from curio.config import CurioConfig
from curio.project_paths import video_paths
from curio.stages.research import ResearchResult


SCRIPT = "  Primeira linha: ação!\n\n  Segunda linha?  \n"


def test_multiline_reader_preserves_paragraphs_whitespace_and_accents(monkeypatch):
    entries = iter([
        "  Primeira linha: ação!",
        "",
        "  Segunda linha?  ",
        "",
        tui.SCRIPT_INPUT_TERMINATOR,
    ])
    monkeypatch.setattr(tui, "_ask", lambda _prompt: next(entries))

    result = tui._read_multiline_script()

    assert result == SCRIPT


def test_script_flow_pastes_text_and_hands_it_to_pipeline(monkeypatch, capsys):
    cfg = CurioConfig()
    prompts = iter(["2", ""])
    captured = {}

    monkeypatch.setattr(tui, "_read_multiline_script", lambda: SCRIPT)
    monkeypatch.setattr(tui, "_ask", lambda _prompt: next(prompts))
    monkeypatch.setattr(tui, "_ask_duration", lambda _colors, current: current)

    def fake_pipeline(idea, _cfg, **kwargs):
        captured["idea"] = idea
        captured.update(kwargs)
        return {"duration_actual": 42.0,
                "artifacts": {"teleprompter": "teleprompter.mp4"}}

    monkeypatch.setattr(pipeline, "run_pipeline", fake_pipeline)
    tui._script_flow(tui._colors(), cfg)

    assert captured["provided_script"] == SCRIPT
    assert captured["narration"] == "human"
    output = capsys.readouterr().out
    assert f"Roteiro recebido: {len(SCRIPT)} caracteres" in output
    assert "Arquivo .txt com o roteiro" not in output
    assert "só as fotos mudam" not in output


def test_pipeline_persists_supplied_script_verbatim_and_skips_script_generation(
        monkeypatch, tmp_path):
    cfg = CurioConfig()
    cfg.out_dir = str(tmp_path / "output")

    class StopAfterScript(Exception):
        pass

    monkeypatch.setattr(
        pipeline.pipeline_research_stage.research_stage, "research_topic",
        lambda *_args, **_kwargs: ResearchResult(None, []))
    monkeypatch.setattr(pipeline.pipeline_research_stage.research_stage, "format_for_prompt",
                        lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        pipeline.pipeline_research_stage.research_stage, "verify_grounding",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(StopAfterScript()))
    monkeypatch.setattr(
        pipeline.pipeline_script_stage.script_stage, "generate_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("provided script must skip script generation")))

    try:
        pipeline.run_script_pipeline(
            SCRIPT, cfg, title="Título de teste", slug="teste-roteiro-colado")
    except StopAfterScript:
        pass
    else:
        raise AssertionError("test did not reach the post-script pipeline stage")

    paths = video_paths(cfg.out_dir, "teste-roteiro-colado")
    with open(paths.script_txt, encoding="utf-8") as stream:
        assert stream.read() == SCRIPT


def test_explicit_topic_flows_to_research_and_scene_context(
        monkeypatch, tmp_path):
    cfg = CurioConfig()
    cfg.out_dir = str(tmp_path / "output")
    seen = {}

    class StopAfterScene(Exception):
        pass

    def research(idea, *_args, **_kwargs):
        seen["research_topic"] = idea
        return ResearchResult(None, [])

    def scenes(*_args, **kwargs):
        seen["scene_topic"] = kwargs["topic"]
        raise StopAfterScene

    monkeypatch.setattr(
        pipeline.pipeline_research_stage.research_stage, "research_topic", research)
    monkeypatch.setattr(
        pipeline.pipeline_research_stage.research_stage, "format_for_prompt",
        lambda *_args, **_kwargs: "")
    monkeypatch.setattr(pipeline.pipeline_scenes_stage, "run_scene_stage", scenes)

    try:
        pipeline.run_script_pipeline(
            SCRIPT, cfg, title="Black holes — field notes", topic="Black holes",
            slug="separate-topic-title")
    except StopAfterScene:
        pass
    else:
        raise AssertionError("test did not reach scene planning")

    assert seen == {"research_topic": "Black holes", "scene_topic": "Black holes"}
    paths = video_paths(cfg.out_dir, "separate-topic-title")
    with open(paths.title_txt, encoding="utf-8") as stream:
        assert stream.read() == "Black holes — field notes"


def test_from_script_separates_research_topic_from_display_title(monkeypatch):
    cfg = CurioConfig()
    captured = {}

    def fake_run_pipeline(idea, _cfg, **kwargs):
        captured["topic"] = idea
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(pipeline, "run_pipeline", fake_run_pipeline)

    result = pipeline.run_script_pipeline(
        SCRIPT, cfg, title="Black holes — field notes", topic="Black holes",
        slug="black-holes")

    assert result == {"ok": True}
    assert captured["topic"] == "Black holes"
    assert captured["display_title"] == "Black holes — field notes"
    assert captured["provided_script"] == SCRIPT


def test_from_script_defaults_topic_to_title_for_compatibility(monkeypatch):
    cfg = CurioConfig()
    captured = {}

    monkeypatch.setattr(
        pipeline, "run_pipeline",
        lambda idea, _cfg, **kwargs: captured.update(topic=idea, **kwargs) or {})

    pipeline.run_script_pipeline(SCRIPT, cfg, title="Topic title", slug="legacy")

    assert captured["topic"] == "Topic title"
    assert captured["display_title"] == "Topic title"


def test_from_script_cli_exposes_topic_separately_from_title():
    args = build_parser().parse_args([
        "from-script", "script.txt", "--title", "Display title",
        "--topic", "Research subject",
    ])

    assert args.title == "Display title"
    assert args.topic == "Research subject"
