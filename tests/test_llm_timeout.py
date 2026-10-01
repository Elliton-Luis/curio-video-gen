"""Timeout de chamada do LLM: conexão separada de resposta/processamento.

A execução de São Jerônimo mostrou "[NVIDIA] tentativa 1/6 falhou
(timeout)" com 15 s, seguido de um fallback que funcionou. Um 550B no
NIM não conclui em 15 s: o padrão de resposta/processamento agora é
120 s, e a conexão/handshake tem teto próprio e curto (10 s) — rede ou
endpoint falham rápido sem consumir o orçamento de geração.
"""

import itertools


# --- o teto: investigado antes de mexer ---------------------------

def test_o_teto_padrao_agora_e_120(monkeypatch):
    """Um 550B no NIM não conclui em 15 s: padrão folgado, ainda configurável."""
    from curio.stages import nvidia as N
    monkeypatch.delenv("NVIDIA_TIMEOUT_MAX", raising=False)
    assert N.call_timeout_max() == 120
    assert N.LLM_CALL_TIMEOUT_MAX == 120


def test_o_teto_agora_e_configuravel(monkeypatch):
    """O 15 era rígido: nem .env nem config o ultrapassavam.

    Significava que um modelo grande e lento no NIM não tinha como
    funcionar — a chamada era morta e o rodízio caía no próximo sem
    ninguém poder aumentar o orçamento.
    """
    from curio.stages import nvidia as N
    monkeypatch.delenv("NVIDIA_TIMEOUT_MAX", raising=False)
    assert N.call_timeout_max(90) == 90
    monkeypatch.setenv("NVIDIA_TIMEOUT_MAX", "120")
    assert N.call_timeout_max() == 120
    # config manda no env
    assert N.call_timeout_max(90) == 90


def test_teto_invalido_cai_no_padrao(monkeypatch):
    from curio.stages import nvidia as N
    monkeypatch.setenv("NVIDIA_TIMEOUT_MAX", "lixo")
    assert N.call_timeout_max() == 120
    assert N.call_timeout_max(0) == 120
    assert N.call_timeout_max(-5) == 120


def test_config_carrega_o_teto(tmp_path, monkeypatch):
    from curio.config import CurioConfig
    monkeypatch.delenv("NVIDIA_TIMEOUT_MAX", raising=False)
    p = tmp_path / "config.toml"
    p.write_text('[nvidia]\ntimeout = 30\ntimeout_max = 90\n', encoding="utf-8")
    cfg = CurioConfig.load(str(p))
    assert cfg.nvidia_timeout == 30
    assert cfg.nvidia_timeout_max == 90


def test_env_carrega_o_teto(tmp_path, monkeypatch):
    from curio.config import CurioConfig
    p = tmp_path / "config.toml"
    p.write_text('genre = "people"\n', encoding="utf-8")
    monkeypatch.setenv("NVIDIA_TIMEOUT_MAX", "75")
    assert CurioConfig.load(str(p)).nvidia_timeout_max == 75


def test_teto_por_provedor_vazio_nao_muda_nada():
    """Vazio = usa o global. Nenhuma diferença no comportamento atual."""
    from curio.stages import nvidia as N
    assert N.LLM_PROVIDER_TIMEOUT == {}


def test_o_rodizio_nao_muda():
    """A rotação segue a preferência Groq, NVIDIA, depois fallbacks."""
    from curio.stages import nvidia as N
    # `_rotation` é um gerador INFINITO de propósito (o budget é quem
    # corta). Materializar com list() trava o teste — daí o islice.
    primeiros = list(itertools.islice(
        N._rotation(["groq", "nvidia", "openrouter"]), 5))
    assert primeiros == ["groq", "nvidia", "openrouter", "groq", "nvidia"]


def test_teto_nvidia_configurado_nao_limita_resposta(monkeypatch):
    """Timeout configurado permanece legado; requests NVIDIA esperam sem teto."""
    from curio.stages import nvidia as N
    monkeypatch.delenv("NVIDIA_TIMEOUT_MAX", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k2")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    vistos = {}

    def fake_post(messages, key, model, base_url, timeout, max_tokens,
                  temperature, pid, json_mode=False):
        vistos[pid] = timeout
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(N, "_post_with_retries", fake_post)
    body, label = N._chat([{"role": "user", "content": "oi"}], 100, 0.0,
                          "m", "https://x", timeout=120, timeout_max=90)
    assert label.startswith("nvidia")
    assert vistos["nvidia"] is None


def test_nvidia_ignora_teto_padrao_de_resposta(monkeypatch):
    """NVIDIA recebe None em vez do teto global padrão."""
    from curio.stages import nvidia as N
    monkeypatch.delenv("NVIDIA_TIMEOUT_MAX", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k2")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    vistos = {}

    def fake_post(messages, key, model, base_url, timeout, max_tokens,
                  temperature, pid, json_mode=False):
        vistos[pid] = timeout
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(N, "_post_with_retries", fake_post)
    N._chat([{"role": "user", "content": "oi"}], 100, 0.0, "m", "https://x",
            timeout=120)
    assert vistos["nvidia"] is None


def test_timeout_especifico_nvidia_nao_corta_espera_infinita(monkeypatch):
    """Um limite NVIDIA legado não substitui espera ilimitada."""
    from curio.stages import nvidia as N
    monkeypatch.delenv("NVIDIA_TIMEOUT_MAX", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k2")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setitem(N.LLM_PROVIDER_TIMEOUT, "nvidia", 150)
    vistos = {}

    def fake_post(messages, key, model, base_url, timeout, max_tokens,
                  temperature, pid, json_mode=False):
        vistos.setdefault(pid, timeout)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(N, "_post_with_retries", fake_post)
    N._chat([{"role": "user", "content": "oi"}], 100, 0.0, "m", "https://x",
            timeout=120)
    assert vistos["nvidia"] is None


def test_timeout_ainda_cai_no_rodizio():
    """O fast_fail de timeout se mantém: provedor lento não bloqueia."""
    from curio.stages import nvidia as N
    err = N.NvidiaError("timeout de resposta/processamento")
    err.retryable = True
    err.fast_fail = True
    assert err.fast_fail is True and err.retryable is True


def test_connect_timeout_padrao_e_10_e_configuravel(monkeypatch):
    """Handshake curto e separado do orçamento de geração."""
    from curio.stages import nvidia as N
    monkeypatch.delenv("NVIDIA_CONNECT_TIMEOUT", raising=False)
    assert N.llm_connect_timeout() == 10
    assert N.CONNECT_TIMEOUT_DEFAULT == 10
    assert N.llm_connect_timeout(25) == 25
    monkeypatch.setenv("NVIDIA_CONNECT_TIMEOUT", "7")
    assert N.llm_connect_timeout() == 7
    monkeypatch.setenv("NVIDIA_CONNECT_TIMEOUT", "lixo")
    assert N.llm_connect_timeout() == 10


def test_config_carrega_connect_timeout(tmp_path, monkeypatch):
    from curio.config import CurioConfig
    monkeypatch.delenv("NVIDIA_CONNECT_TIMEOUT", raising=False)
    p = tmp_path / "config.toml"
    p.write_text('[nvidia]\nconnect_timeout = 8\n', encoding="utf-8")
    assert CurioConfig.load(str(p)).nvidia_connect_timeout == 8
    monkeypatch.setenv("NVIDIA_CONNECT_TIMEOUT", "6")
    assert CurioConfig.load(str(p)).nvidia_connect_timeout == 6
