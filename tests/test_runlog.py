"""Log persistente desde startup, falha, interrupção e redação de segredos."""

import json
from pathlib import Path

import pytest

from curio.config import CurioConfig
from curio import pipeline
from curio.runlog import RunLog, event, safe_text, set_stage


def _records(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def test_run_log_exists_before_work_and_survives_failure_without_metrics(
        tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        log_files = list((tmp_path / "broken" / "logs").glob("*.jsonl"))
        assert len(log_files) == 1
        assert _records(log_files[0])[0]["event"] == "run_started"
        set_stage("media")
        event("error", "provider request failed", provider="wikimedia")
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(pipeline, "_run_pipeline", fail)
    with pytest.raises(RuntimeError, match="fixture failure"):
        pipeline.run_pipeline("idea", CurioConfig(out_dir=str(tmp_path)),
                              slug="broken")
    logs = list((tmp_path / "broken" / "logs").glob("*.jsonl"))
    rows = _records(logs[0])
    assert rows[-2]["stage"] == "media"
    assert rows[-1]["event"] == "run_failed"
    assert rows[-1]["details"]["traceback"]
    assert not list((tmp_path / "metrics").glob("*.json"))


def test_interruption_flushes_interrupted_record(tmp_path, monkeypatch):
    def interrupt(*args, **kwargs):
        set_stage("tts")
        event("provider", "TTS: edge-tts / pt-BR-AntonioNeural")
        raise KeyboardInterrupt()

    monkeypatch.setattr(pipeline, "_run_pipeline", interrupt)
    with pytest.raises(KeyboardInterrupt):
        pipeline.run_pipeline("idea", CurioConfig(out_dir=str(tmp_path)),
                              slug="interrupted")
    log = next((tmp_path / "interrupted" / "logs").glob("*.jsonl"))
    rows = _records(log)
    assert rows[-2]["stage"] == "tts"
    assert rows[-1]["event"] == "run_interrupted"


def test_success_creates_log_and_callback_only_receives_short_events(
        tmp_path, monkeypatch):
    seen = []

    def succeed(*args, **kwargs):
        event("provider", "Groq / openai/gpt-oss-20b", prompt="must not log")
        return {"artifacts": {"video": "video.mp4"}}

    monkeypatch.setattr(pipeline, "_run_pipeline", succeed)
    result = pipeline.run_pipeline(
        "idea", CurioConfig(out_dir=str(tmp_path)), slug="ok",
        on_event=seen.append)
    log = next((tmp_path / "ok" / "logs").glob("*.jsonl"))
    rows = _records(log)
    assert result["artifacts"]["video"] == "video.mp4"
    assert rows[0]["event"] == "run_started"
    assert rows[-1]["event"] == "run_completed"
    assert any(row["event"] == "provider" for row in rows)
    assert "prompt" not in json.dumps(rows)
    assert any(row["event"] == "log_ready" for row in seen)


def test_secret_redaction_covers_environment_bearer_and_query(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "private-api-key-value")
    raw = ("Bearer private-api-key-value "
           "https://example.test/?X-Amz-Signature=signed-value")
    assert "private-api-key-value" not in safe_text(raw)
    assert "signed-value" not in safe_text(raw)
    log_path = tmp_path / "secret.jsonl"
    with RunLog(log_path, "secret") as log:
        log.event("error", raw)
    assert "private-api-key-value" not in log_path.read_text()
    assert "signed-value" not in log_path.read_text()


def test_tui_event_view_stays_short(capsys):
    from curio.tui import _run_event
    _run_event({"event": "provider", "message": "Groq / gpt-oss-20b",
                "details": {"prompt": "private full prompt"}})
    output = capsys.readouterr().out
    assert "Groq / gpt-oss-20b" in output
    assert "private full prompt" not in output
    assert '"details"' not in output


def test_media_provider_thread_keeps_run_log_context(tmp_path):
    from curio.stages.media_search import search_with_timeout

    class Provider:
        name = "fixture"

        def search(self, query, limit, metrics):
            event("retry", "provider retry from worker")
            return []

    path = tmp_path / "thread.jsonl"
    with RunLog(path, "thread"):
        search_with_timeout(Provider(), "query", 2)
    assert any(row["event"] == "retry" for row in _records(path))


def test_media_search_timeout_returns_without_waiting_for_worker():
    import threading
    import time
    from curio.stages.media_search import search_with_timeout
    from curio.media.providers import MediaError

    release = threading.Event()

    class SlowProvider:
        name = "slow-fixture"

        def search(self, query, limit, metrics):
            release.wait(2)
            return []

    started = time.monotonic()
    try:
        search_with_timeout(SlowProvider(), "query", 0.02)
        assert False, "timed-out provider returned before release"
    except MediaError as exc:
        assert "busca timeout" in str(exc)
    assert time.monotonic() - started < 0.5
    release.set()  # let bounded executor worker exit cleanly
