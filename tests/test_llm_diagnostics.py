"""Configuração Groq e diagnóstico observável de JSON para cenas."""

import json

import pytest

from curio.config import CurioConfig
from curio.stages import nvidia as N


def _response(content, finish, completion_tokens):
    return {
        "choices": [{"message": {"content": content},
                     "finish_reason": finish}],
        "usage": {"completion_tokens": completion_tokens},
    }


class _FakeResp:
    def __init__(self, status, payload: bytes):
        self.status = status
        self._payload = payload

    def read(self, _n):
        if self._payload:
            out, self._payload = self._payload, b""
            return out
        return b""


class _FakeConn:
    """http.client falso: captura request, devolve status+payload fixos."""
    last = None

    def __init__(self, host, port, timeout=None, *, status=200, payload=b""):
        self.host, self.port, self.timeout = host, port, timeout
        self._status, self._payload = status, payload
        self.request_args = None
        type(self).last = self

    def connect(self):
        pass

    @property
    def sock(self):
        outer = self

        class S:
            def settimeout(self, _v):
                pass

        return S()

    def request(self, method, path, body=None, headers=None):
        self.request_args = (method, path, body, dict(headers or {}))

    def getresponse(self):
        return _FakeResp(self._status, self._payload)

    def close(self):
        pass


def _install_conn(monkeypatch, status=200, payload=b""):
    def factory(host, port, timeout=None):
        return _FakeConn(host, port, timeout, status=status, payload=payload)

    import http.client
    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    monkeypatch.setattr(http.client, "HTTPConnection", factory)
    _FakeConn.last = None
    return _FakeConn


def test_lightning_id_uses_existing_nim_catalog_entry():
    cfg = CurioConfig()
    cfg.nvidia_model = N.FUTURE_MODELS["scale"]
    assert cfg.nvidia_model == "nvidia/nemotron-3.5-lightning-30b-a3b"
    # O diagnóstico é temporário: o default persistente não é trocado.
    assert CurioConfig().nvidia_model == "meta/llama-3.3-70b-instruct"


def test_groq_defaults_are_official_and_use_gpt_oss_20b(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    cfg = CurioConfig()
    model, base = N.llm_settings("groq")
    assert cfg.groq_model == model == "openai/gpt-oss-20b"
    assert cfg.groq_base_url == base == "https://api.groq.com/openai/v1"


def test_mistral_uses_openai_compatible_endpoint_and_settings(monkeypatch):
    monkeypatch.delenv("MISTRAL_MODEL", raising=False)
    monkeypatch.delenv("MISTRAL_BASE_URL", raising=False)
    cfg = CurioConfig()
    assert cfg.mistral_model == N.llm_settings("mistral")[0] == "mistral-small-latest"
    assert cfg.mistral_base_url == N.llm_settings("mistral")[1] == "https://api.mistral.ai/v1"


def test_default_provider_order_and_requested_models():
    cfg = CurioConfig()
    assert N.PROVIDER_ORDER == ("nvidia", "groq", "openrouter", "mistral", "gemini")
    assert cfg.nvidia_model == "meta/llama-3.3-70b-instruct"
    assert cfg.groq_model == "openai/gpt-oss-20b"
    assert cfg.openrouter_model == "meta-llama/llama-3.3-70b-instruct:free"
    assert cfg.mistral_model == "mistral-small-latest"
    assert cfg.gemini_model == "gemini-2.5-flash"


def test_mistral_request_uses_openai_chat_contract(monkeypatch):
    fake = _install_conn(
        monkeypatch, payload=json.dumps(
            _response('{"ok":true}', "stop", 8)).encode())
    N._post_once([{"role": "user", "content": "Return JSON."}],
                 "fake-secret", "mistral-small-latest",
                 "https://api.mistral.ai/v1", 15, 128, 0.0, "mistral",
                 json_mode=True)
    method, path, body, headers = fake.last.request_args
    assert path == "/v1/chat/completions"
    assert headers["Authorization"] == "Bearer fake-secret"
    payload = json.loads(body)
    assert payload["model"] == "mistral-small-latest"
    assert payload["response_format"] == {"type": "json_object"}


def test_mistral_429_preserves_api_message_and_redacts_key(monkeypatch):
    fake = _install_conn(
        monkeypatch, status=429,
        payload=b'{"message":"Rate limit exceeded: secret-key"}')
    with pytest.raises(N.NvidiaError) as caught:
        N._post_once([], "secret-key", "mistral-small-latest",
                     "https://api.mistral.ai/v1", 15, 128, 0.0, "mistral")
    assert "HTTP 429" in str(caught.value)
    assert "Rate limit exceeded" in str(caught.value)
    assert "secret-key" not in str(caught.value)


def test_groq_success_remains_a_normal_member_of_provider_rotation(monkeypatch):
    from curio.stages import nvidia as N
    for key in ("NVIDIA_API_KEY", "NVIDIA_API_KEYS", "OPENROUTER_API_KEY",
                "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
                "MISTRAL_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key in ("NVIDIA_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY",
                "GROQ_API_KEY", "MISTRAL_API_KEY"):
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
    assert calls == ["nvidia", "groq"]
    assert label == "groq:openai/gpt-oss-20b"
    assert body["choices"][0]["message"]["content"] == "groq answer"


def test_groq_request_has_openai_endpoint_bearer_model_and_app_user_agent(
        monkeypatch):
    fake = _install_conn(
        monkeypatch, payload=json.dumps(
            _response('{"ok":true}', "stop", 8)).encode())
    body = N._post_once(
        [{"role": "user", "content": "Return JSON."}], "fake-secret",
        "openai/gpt-oss-20b", "https://api.groq.com/openai/v1", 15,
        2000, 0.3, "groq", json_mode=True)
    method, path, raw, headers = fake.last.request_args
    assert fake.last.host == "api.groq.com"
    assert path == "/openai/v1/chat/completions"
    assert headers["Authorization"] == "Bearer fake-secret"
    assert headers["User-Agent"].startswith("curio/")
    assert "python-urllib" not in headers["User-Agent"]
    payload = json.loads(raw)
    assert payload["model"] == "openai/gpt-oss-20b"
    assert payload["max_tokens"] == 2000
    assert payload["temperature"] == 0.3
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["reasoning_effort"] == "low"
    assert body["choices"][0]["finish_reason"] == "stop"


def test_groq_http_403_preserves_api_message_without_calling_it_bad_key(
        monkeypatch):
    fake = _install_conn(
        monkeypatch, status=403,
        payload=(b'{"detail":"' + b'x' * 400 +
                 b'","error_name":"browser_signature_banned",'
                 b'"message":"blocked user agent"}'))
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
