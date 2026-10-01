"""Rodízio LLM e fallback NVIDIA resiliente quando ela é o último caminho."""

import pytest

from curio.stages import nvidia as N


KEYS = ("NVIDIA_API_KEY", "NVIDIA_API_KEYS", "OPENROUTER_API_KEY", "GEMINI_API_KEY",
        "GOOGLE_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY", "CURIO_LLM_ATTEMPTS",
        "NVIDIA_TIMEOUT_MAX", "NVIDIA_CONNECT_TIMEOUT")


def _keys(monkeypatch, *providers):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    env = {"nvidia": "NVIDIA_API_KEY", "openrouter": "OPENROUTER_API_KEY",
           "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY",
           "mistral": "MISTRAL_API_KEY"}
    for provider in providers:
        monkeypatch.setenv(env[provider], f"test-{provider}")
    monkeypatch.setenv("CURIO_LLM_ATTEMPTS", "6")


def _error(message: str, *, retryable: bool, fast_fail: bool = False,
           exhausted: bool = False, http_attempts: int = 1):
    exc = N.NvidiaError(message)
    exc.retryable = retryable
    exc.fast_fail = fast_fail
    exc.retry_exhausted = exhausted
    exc.http_attempts = http_attempts
    return exc


def _body(text="ok"):
    return {"choices": [{"message": {"content": text},
                         "finish_reason": "stop"}]}


def _chat():
    return N._chat([{"role": "user", "content": "test"}], 100, 0.0,
                   "nvidia-model", "https://nvidia.test/v1", 15,
                   "or-model", "https://openrouter.test/v1")


def test_nvidia_timeout_keeps_normal_rotation_when_fallback_exists(monkeypatch):
    _keys(monkeypatch, "nvidia", "openrouter")
    calls = []

    def fake_post(_messages, _key, _model, _url, timeout, *_args):
        pid = _args[-2]
        calls.append((pid, timeout))
        if pid == "nvidia":
            raise _error("socket timed out", retryable=True, fast_fail=True)
        return _body("from OpenRouter")

    monkeypatch.setattr(N, "_post_with_retries", fake_post)
    body, label = _chat()
    assert label.startswith("openrouter:")
    assert body["choices"][0]["message"]["content"] == "from OpenRouter"
    assert calls == [("nvidia", None), ("openrouter", 15)]


def test_groq_runs_first_nvidia_second_without_timeout_and_400_skips_it(
        monkeypatch):
    _keys(monkeypatch, "groq", "nvidia", "openrouter")
    calls = []

    def fake_post(_messages, _key, _model, _url, timeout, *_args):
        provider = _args[-2]
        calls.append((provider, timeout))
        if provider == "groq":
            raise _error("Groq timed out", retryable=True, fast_fail=True)
        if provider == "nvidia":
            error = _error("NVIDIA HTTP 400", retryable=False)
            error.http_status = 400
            raise error
        return _body("OpenRouter response")

    monkeypatch.setattr(N, "_post_with_retries", fake_post)
    body, label = _chat()

    assert calls == [("groq", 15), ("nvidia", None), ("openrouter", 15)]
    assert label.startswith("openrouter:")
    assert body["choices"][0]["message"]["content"] == "OpenRouter response"


def test_invalid_narration_response_falls_through_to_next_provider(monkeypatch):
    _keys(monkeypatch, "groq", "openrouter")
    calls = []

    def fake_post(_messages, _key, _model, _url, _timeout, *_args):
        provider = _args[-2]
        calls.append(provider)
        if provider == "groq":
            return _body("")
        return _body("A useful narration with enough content. " * 5)

    monkeypatch.setattr(N, "_post_with_retries", fake_post)
    validator = lambda body: (
        "invalid narration" if len(body["choices"][0]["message"]["content"]) < 100
        else None)

    body, label = N._chat(
        [{"role": "user", "content": "script"}], 100, 0.0,
        "nvidia-model", "https://nvidia.test/v1", 15,
        "or-model", "https://openrouter.test/v1",
        response_validator=validator)

    assert calls == ["groq", "openrouter"]
    assert label.startswith("openrouter:")
    assert len(body["choices"][0]["message"]["content"]) >= 100


def test_invalid_narration_diagnostic_reports_sizes_not_response_text():
    issue = N._script_response_issue({
        "choices": [{"finish_reason": "stop", "message": {
            "content": "private response text", "reasoning_content": "thinking"}}],
        "usage": {"completion_tokens": 12},
    }, 12000)

    assert "finish_reason=stop" in issue
    assert "content_chars=21" in issue
    assert "reasoning_chars=8" in issue
    assert "completion_tokens=12" in issue
    assert "private response text" not in issue


def test_run_log_records_provider_timeout_and_successful_fallback(
        monkeypatch, tmp_path):
    from curio.runlog import RunLog
    _keys(monkeypatch, "nvidia", "openrouter")

    def fake_retries(_messages, _key, _model, _url, _timeout, *_args):
        provider = _args[-2]
        if provider == "nvidia":
            raise _error("socket timeout", retryable=True, fast_fail=True)
        return _body("fallback succeeded")

    monkeypatch.setattr(N, "_post_with_retries", fake_retries)
    path = tmp_path / "fallback.jsonl"
    with RunLog(path, "fallback"):
        body, label = _chat()
    assert label.startswith("openrouter:")
    assert body["choices"][0]["message"]["content"] == "fallback succeeded"
    import json
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert any(e["event"] == "fallback" and "timeout" in e["message"]
               for e in events)
    assert any(e["event"] == "provider" and "OpenRouter" in e["message"]
               for e in events)


def test_provider_order_ends_with_unlimited_nvidia_fallback_when_alone(
        monkeypatch, capsys):
    _keys(monkeypatch, "nvidia", "openrouter", "gemini", "groq", "mistral")
    monkeypatch.setattr(N.time, "sleep", lambda _delay: None)
    normal_calls = []
    final_timeouts = []

    def fake_retries(_messages, _key, _model, _url, timeout, *_args):
        pid = _args[-2]
        normal_calls.append(pid)
        if pid == "nvidia":
            raise _error("normal NVIDIA timeout", retryable=True, fast_fail=True)
        if pid == "openrouter":
            raise _error("HTTP 402 no credits", retryable=False)
        if pid == "gemini":
            # Simula um retry interno 429 esgotado: seis HTTP requests dentro
            # de uma rodada global, contabilizados como seis, não como dois.
            raise _error("HTTP 429 exhausted", retryable=True,
                         exhausted=True, http_attempts=6)
        raise _error("HTTP 401 invalid key", retryable=False)

    def fake_once(_messages, _key, _model, _url, timeout, *_args):
        final_timeouts.append(timeout)
        raise _error("HTTP 503 unavailable", retryable=True)

    monkeypatch.setattr(N, "_post_with_retries", fake_retries)
    monkeypatch.setattr(N, "_post_once", fake_once)
    with pytest.raises(N.NvidiaError) as caught:
        _chat()

    assert normal_calls == ["groq", "nvidia", "openrouter", "mistral",
                            "gemini"]
    assert final_timeouts == [None] * 5
    message = str(caught.value)
    assert "5/6 rodada(s) globais" in message
    assert "Mistral: 1 tentativa(s) HTTP em 1 rodada(s)" in message
    assert "NVIDIA fallback resiliente: 5/5" in message
    log = capsys.readouterr().out
    assert "[NVIDIA] último provider viável — fallback resiliente" in log


def test_nvidia_success_on_final_attempt_returns_pipeline_result(monkeypatch):
    _keys(monkeypatch, "nvidia")
    monkeypatch.setattr(N.time, "sleep", lambda _delay: None)
    calls = []

    def fake_once(_messages, _key, _model, _url, timeout, *_args):
        calls.append(timeout)
        if len(calls) < 5:
            raise _error("HTTP 503 busy", retryable=True)
        return _body("NVIDIA recovered")

    monkeypatch.setattr(N, "_post_once", fake_once)
    body, label = _chat()
    assert calls == [None] * 5
    assert body["choices"][0]["message"]["content"] == "NVIDIA recovered"
    assert label.startswith("nvidia:")


def test_nvidia_503_exhaustion_stays_available_for_final_fallback(monkeypatch):
    _keys(monkeypatch, "nvidia", "openrouter", "gemini", "groq", "mistral")
    monkeypatch.setattr(N.time, "sleep", lambda _delay: None)
    calls = []

    def fake_retries(_messages, _key, _model, _url, timeout, *_args):
        pid = _args[-2]
        calls.append(("normal", pid, timeout))
        if pid == "nvidia":
            raise _error("HTTP 503 exhausted", retryable=True,
                         exhausted=True, http_attempts=6)
        if pid == "openrouter":
            raise _error("HTTP 402 no credits", retryable=False)
        if pid == "gemini":
            raise _error("HTTP 429 exhausted", retryable=True,
                         exhausted=True, http_attempts=6)
        raise _error("HTTP 401 invalid key", retryable=False)

    def fake_once(_messages, _key, _model, _url, timeout, *_args):
        calls.append(("final", "nvidia", timeout))
        return _body("NVIDIA recovered after 503")

    monkeypatch.setattr(N, "_post_with_retries", fake_retries)
    monkeypatch.setattr(N, "_post_once", fake_once)
    body, label = _chat()
    assert label.startswith("nvidia:")
    assert body["choices"][0]["message"]["content"] == "NVIDIA recovered after 503"
    assert calls[-1] == ("final", "nvidia", None)


def test_five_transient_failures_end_last_resort(monkeypatch, capsys):
    _keys(monkeypatch, "nvidia")
    monkeypatch.setattr(N.time, "sleep", lambda _delay: None)
    calls = []

    def fake_once(_messages, _key, _model, _url, timeout, *_args):
        calls.append(timeout)
        raise _error("HTTP 503 busy", retryable=True)

    monkeypatch.setattr(N, "_post_once", fake_once)
    with pytest.raises(N.NvidiaError) as caught:
        _chat()
    assert calls == [None] * 5
    assert "NVIDIA fallback resiliente: 5/5" in str(caught.value)
    assert "5 falhas transitórias" in str(caught.value)
    assert "5 tentativas transitórias falharam" in capsys.readouterr().out


def test_definitive_nvidia_error_stops_last_resort_immediately(monkeypatch,
                                                                capsys):
    _keys(monkeypatch, "nvidia")
    calls = []

    def fake_once(_messages, _key, _model, _url, timeout, *_args):
        calls.append(timeout)
        raise _error("HTTP 401 unauthorized", retryable=False)

    monkeypatch.setattr(N, "_post_once", fake_once)
    with pytest.raises(N.NvidiaError) as caught:
        _chat()
    assert calls == [None]
    assert "erro definitivo" in str(caught.value)
    assert "erro definitivo no fallback resiliente" in capsys.readouterr().out


def test_internal_http_retries_report_exact_count_to_global_survey(monkeypatch):
    _keys(monkeypatch, "nvidia")
    monkeypatch.setenv("CURIO_LLM_ATTEMPTS", "3")
    monkeypatch.setattr(N.time, "sleep", lambda _delay: None)
    calls = []

    def fake_once(*_args):
        calls.append(1)
        raise _error("HTTP 503 busy", retryable=True)

    monkeypatch.setattr(N, "_post_once", fake_once)
    with pytest.raises(N.NvidiaError) as caught:
        N._post_with_retries([], "key", "model", "https://nvidia.test",
                             15, 10, 0.0, "nvidia")
    assert len(calls) == 3
    assert caught.value.http_attempts == 3
    assert caught.value.retry_exhausted is True


def test_unwrapped_network_reset_is_transient_in_last_resort(monkeypatch):
    import http.client
    from curio.stages import nvidia as N

    class BoomConn:
        def __init__(self, *a, **k):
            pass

        def connect(self):
            raise ConnectionResetError("peer reset")

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPSConnection", BoomConn)
    monkeypatch.setattr(http.client, "HTTPConnection", BoomConn)
    with pytest.raises(N.NvidiaError, match="conexão interrompida") as caught:
        N._post_once([], "key", "model", "https://nvidia.test", None,
                     10, 0.0, "nvidia")
    assert caught.value.retryable is True
    assert getattr(caught.value, "fast_fail", False) is False


def test_connect_timeout_usado_no_handshake_e_total_na_resposta(monkeypatch):
    import http.client
    from curio.stages import nvidia as N

    seen = {}

    class FakeSock:
        def settimeout(self, v):
            seen.setdefault("sock_timeouts", []).append(v)

    class FakeResp:
        status = 200

        def read(self, _n):
            return b""

    class FakeConn:
        def __init__(self, host, port, timeout=None):
            seen["connect_timeout"] = timeout

        def connect(self):
            pass

        @property
        def sock(self):
            return FakeSock()

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return FakeResp()

        def close(self):
            pass

    class FakeBody:
        pass

    import json as _json

    class FakeConn2(FakeConn):
        def getresponse(self):
            class R:
                status = 200

                def read(self, _n):
                    if not hasattr(self, "done"):
                        self.done = True
                        return _json.dumps(
                            {"choices": [{"message": {"content": "ok"}}]}
                        ).encode()
                    return b""
            return R()

    monkeypatch.setattr(http.client, "HTTPSConnection", FakeConn2)
    monkeypatch.setattr(http.client, "HTTPConnection", FakeConn2)
    monkeypatch.setenv("NVIDIA_CONNECT_TIMEOUT", "7")
    result = N._post_once([], "key", "model", "https://nvidia.test", 120,
                          10, 0.0, "nvidia")
    assert result["choices"][0]["message"]["content"] == "ok"
    assert seen["connect_timeout"] == 7
    assert 120 in seen["sock_timeouts"]


def test_post_once_passes_explicit_no_timeout_to_total(monkeypatch):
    import http.client
    import json
    from curio.stages import nvidia as N

    seen = {}

    class FakeConn:
        def __init__(self, *a, **k):
            pass

        def connect(self):
            pass

        @property
        def sock(self):
            outer = self

            class S:
                def settimeout(self, v):
                    seen["sock_timeout"] = v
                    outer.saw = v

            return S()

        def request(self, *a, **k):
            pass

        def getresponse(self):
            class R:
                status = 200

                def read(self, _n):
                    if not hasattr(self, "done"):
                        self.done = True
                        return json.dumps(
                            {"choices": [{"message": {"content": "ok"}}]}
                        ).encode()
                    return b""

            return R()

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPSConnection", FakeConn)
    monkeypatch.setattr(http.client, "HTTPConnection", FakeConn)
    result = N._post_once([], "key", "model", "https://nvidia.test", None,
                          10, 0.0, "nvidia")
    assert result["choices"][0]["message"]["content"] == "ok"
    assert seen["sock_timeout"] is None
