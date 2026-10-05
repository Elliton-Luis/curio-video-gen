from curio import pipeline, tui
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
        pipeline.research_stage, "research_topic",
        lambda *_args, **_kwargs: ResearchResult(None, []))
    monkeypatch.setattr(pipeline.research_stage, "format_for_prompt",
                        lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        pipeline.research_stage, "verify_grounding",
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
