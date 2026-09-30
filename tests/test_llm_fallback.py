"""Rodízio LLM e fallback NVIDIA resiliente quando ela é o último caminho."""

import pytest

from curio.stages import nvidia as N


KEYS = ("NVIDIA_API_KEY", "NVIDIA_API_KEYS", "OPENROUTER_API_KEY", "GEMINI_API_KEY",
        "GOOGLE_API_KEY", "GROQ_API_KEY", "CURIO_LLM_ATTEMPTS",
        "NVIDIA_TIMEOUT_MAX")


def _keys(monkeypatch, *providers):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    env = {"nvidia": "NVIDIA_API_KEY", "openrouter": "OPENROUTER_API_KEY",
           "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}
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
    assert calls == [("nvidia", 15), ("openrouter", 15)]


def test_failed_fallbacks_promote_nvidia_to_five_unbounded_attempts(
        monkeypatch, capsys):
    _keys(monkeypatch, "nvidia", "openrouter", "gemini", "groq")
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

    assert normal_calls == ["nvidia", "openrouter", "nvidia",
                            "gemini", "nvidia", "groq"]
    assert final_timeouts == [None] * 5
    message = str(caught.value)
    assert "6/6 rodada(s) globais" in message
    assert "Gemini: 6 tentativa(s) HTTP em 1 rodada(s)" in message
    assert "NVIDIA fallback resiliente: 5/5" in message
    log = capsys.readouterr().out
    assert "[NVIDIA] último provider viável — fallback resiliente" in log
    assert "[NVIDIA] tentativa 1/5 — aguardando sem timeout..." in log


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
    _keys(monkeypatch, "nvidia", "openrouter", "gemini", "groq")
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
    def reset(*_args, **_kwargs):
        raise ConnectionResetError("peer reset")

    monkeypatch.setattr(N.urllib.request, "urlopen", reset)
    with pytest.raises(N.NvidiaError, match="conexão interrompida") as caught:
        N._post_once([], "key", "model", "https://nvidia.test", None,
                     10, 0.0, "nvidia")
    assert caught.value.retryable is True
    assert getattr(caught.value, "fast_fail", False) is False


def test_post_once_passes_explicit_no_timeout_to_urllib(monkeypatch):
    import io
    import json

    seen = {}

    def fake_open(_request, timeout):
        seen["timeout"] = timeout
        return io.BytesIO(json.dumps(_body()).encode())

    monkeypatch.setattr(N.urllib.request, "urlopen", fake_open)
    result = N._post_once([], "key", "model", "https://nvidia.test", None,
                          10, 0.0, "nvidia")
    assert result["choices"][0]["message"]["content"] == "ok"
    assert seen["timeout"] is None
