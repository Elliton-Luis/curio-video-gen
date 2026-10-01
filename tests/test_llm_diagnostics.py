"""Configuração Groq e diagnóstico observável de JSON para cenas."""

import io
import json
import urllib.error

import pytest

from curio.config import CurioConfig
from curio.stages import nvidia as N


def _response(content, finish, completion_tokens):
    return {
        "choices": [{"message": {"content": content},
                     "finish_reason": finish}],
        "usage": {"completion_tokens": completion_tokens},
    }


def test_lightning_id_uses_existing_nim_catalog_entry():
    cfg = CurioConfig()
    cfg.nvidia_model = N.FUTURE_MODELS["scale"]
    assert cfg.nvidia_model == "nvidia/nemotron-3.5-lightning-30b-a3b"
    # O diagnóstico é temporário: o default persistente não é trocado.
    assert CurioConfig().nvidia_model == "nvidia/nemotron-3-ultra-550b-a55b"


def test_groq_defaults_are_official_and_use_gpt_oss_20b(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    cfg = CurioConfig()
    model, base = N.llm_settings("groq")
    assert cfg.groq_model == model == "openai/gpt-oss-20b"
    assert cfg.groq_base_url == base == "https://api.groq.com/openai/v1"


def test_groq_success_remains_a_normal_member_of_provider_rotation(monkeypatch):
    from curio.stages import nvidia as N
    for key in ("NVIDIA_API_KEY", "NVIDIA_API_KEYS", "OPENROUTER_API_KEY",
                "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key in ("NVIDIA_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY",
                "GROQ_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    monkeypatch.setenv("CURIO_LLM_ATTEMPTS", "6")
    calls = []

    def fake_post(_messages, _key, _model, _url, _timeout, *_args):
        pid = _args[-2]
        calls.append(pid)
        if pid == "groq":
            return {"choices": [{"message": {"content": "groq answer"}}]}
        error = N.NvidiaError(f"{pid} unavailable")
        error.retryable = pid == "nvidia"
        error.fast_fail = pid == "nvidia"
        raise error

    monkeypatch.setattr(N, "_post_with_retries", fake_post)
    body, label = N._chat([], 128, 0.0, "nv-model", "https://nvidia.test",
                          15, "or-model", "https://openrouter.test",
                          extra={"gemini": ("gemini-model", "https://gemini.test"),
                                 "groq": ("openai/gpt-oss-20b",
                                          "https://api.groq.com/openai/v1")})
    assert calls == ["nvidia", "openrouter", "nvidia", "gemini", "nvidia", "groq"]
    assert label == "groq:openai/gpt-oss-20b"
    assert body["choices"][0]["message"]["content"] == "groq answer"


def test_groq_request_has_openai_endpoint_bearer_model_and_app_user_agent(
        monkeypatch):
    seen = {}

    def fake_open(req, timeout):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data)
        seen["timeout"] = timeout
        return io.BytesIO(json.dumps(_response('{"ok":true}', "stop", 8)).encode())

    monkeypatch.setattr(N.urllib.request, "urlopen", fake_open)
    body = N._post_once(
        [{"role": "user", "content": "Return JSON."}], "fake-secret",
        "openai/gpt-oss-20b", "https://api.groq.com/openai/v1", 15,
        2000, 0.3, "groq", json_mode=True)
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer fake-secret"
    assert seen["headers"]["User-agent"].startswith("curio/")
    assert "python-urllib" not in seen["headers"]["User-agent"]
    assert seen["body"]["model"] == "openai/gpt-oss-20b"
    assert seen["body"]["max_tokens"] == 2000
    assert seen["body"]["temperature"] == 0.3
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["reasoning_effort"] == "low"
    assert body["choices"][0]["finish_reason"] == "stop"


def test_groq_http_403_preserves_api_message_without_calling_it_bad_key(
        monkeypatch):
    def forbidden(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 403, "Forbidden", {},
            io.BytesIO((b'{"detail":"' + b'x' * 400 +
                        b'","error_name":"browser_signature_banned",'
                        b'"message":"blocked user agent"}')))

    monkeypatch.setattr(N.urllib.request, "urlopen", forbidden)
    with pytest.raises(N.NvidiaError) as caught:
        N._post_once([], "fake-secret", "openai/gpt-oss-20b",
                     "https://api.groq.com/openai/v1", 15,
                     2000, 0.3, "groq")
    message = str(caught.value)
    assert "HTTP 403" in message
    assert "browser_signature_banned" in message
    assert "blocked user agent" in message
    assert "fake-secret" not in message
    assert "chave inválida" not in message


def test_complete_json_records_finish_reason_budget_usage_and_response_size(
        monkeypatch, capsys):
    calls = []
    replies = [
        _response('{"scenes":[', "length", 2000),
        _response('{"scenes":[', "length", 4000),
    ]

    def fake_chat(_messages, max_tokens, *_args, **_kwargs):
        calls.append(max_tokens)
        return replies[len(calls) - 1], "nvidia:lightning"

    monkeypatch.setattr(N, "_chat", fake_chat)
    with pytest.raises(N.NvidiaError) as caught:
        N.complete_json("sys", "user", "lightning", "https://nim", 15)
    assert calls == [2000, 4000]
    message = str(caught.value)
    assert "finish_reason=length" in message
    assert "max_tokens=2000" in message and "max_tokens=4000" in message
    assert "completion_tokens=2000" in message and "completion_tokens=4000" in message
    assert "response_bytes=11" in message
    log = capsys.readouterr().err
    assert "max_tokens=2000" in log and "orçamento estendido" in log
    assert "tentativa estendida solicitada: max_tokens=4000" in log


def test_complete_json_distinguishes_invalid_json_from_truncation(monkeypatch):
    calls = []

    def fake_chat(_messages, max_tokens, *_args, **_kwargs):
        calls.append(max_tokens)
        return _response('{"scenes":', "stop", 123), "groq:gpt-oss-20b"

    monkeypatch.setattr(N, "_chat", fake_chat)
    with pytest.raises(N.NvidiaError) as caught:
        N.complete_json("sys", "user", "openai/gpt-oss-20b", "https://groq", 15)
    assert calls == [2000]
    message = str(caught.value)
    assert "não retornou JSON válido" in message
    assert "finish_reason=stop" in message
    assert "completion_tokens=123" in message
    assert "response_bytes=10" in message
    assert "truncado mesmo" not in message
