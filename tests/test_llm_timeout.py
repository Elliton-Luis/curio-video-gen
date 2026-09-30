"""Timeout de chamada do LLM: o que ele é, e o que ele deixou de ser.

A execução de São Jerônimo mostrou "[NVIDIA] tentativa 1/6 falhou
(timeout): etapa NVIDIA: timeout após 15s", seguido de um fallback que
funcionou. A pergunta era se o modelo era lento demais ou o prazo curto
demais, e a resposta foi: com um timeout de socket, um modelo de 550B que
transmite algo de tempos em tempos NÃO é cortado — o que mata é silêncio
no socket. Separo. O que mudou é que o teto deixou de ser rígido.
"""

import itertools


# --- o teto: investigado antes de mexer ---------------------------

def test_o_teto_padrao_continua_15(monkeypatch):
    """Nada muda para quem não configura nada."""
    from curio.stages import nvidia as N
    monkeypatch.delenv("NVIDIA_TIMEOUT_MAX", raising=False)
    assert N.call_timeout_max() == 15
    assert N.LLM_CALL_TIMEOUT_MAX == 15


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
    assert N.call_timeout_max() == 15
    assert N.call_timeout_max(0) == 15
    assert N.call_timeout_max(-5) == 15


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
    """A ordem e o corte de provedor são sacredos nesta tarefa."""
    from curio.stages import nvidia as N
    # `_rotation` é um gerador INFINITO de propósito (o budget é quem
    # corta). Materializar com list() trava o teste — daí o islice.
    primeiros = list(itertools.islice(
        N._rotation(["nvidia", "openrouter", "gemini"], True), 5))
    assert primeiros == ["nvidia", "openrouter", "nvidia", "gemini", "nvidia"]


def test_o_teto_configurado_chega_na_chamada(monkeypatch):
    """O número não fica só num helper: é o timeout da chamada HTTP.

    Sem isto, `call_timeout_max` podia resolver 90 e `_chat` continuar
    passando 15 — o teste passaria e o caso real continuaria caindo no
    fallback, que é exatamente o que a execução de São Jerônimo mostrou.
    """
    from curio.stages import nvidia as N
    monkeypatch.delenv("NVIDIA_TIMEOUT_MAX", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
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
    assert vistos["nvidia"] == 90


def test_teto_padrao_ainda_limita_a_15(monkeypatch):
    """Sem configurar nada, a chamada continua indo com 15."""
    from curio.stages import nvidia as N
    monkeypatch.delenv("NVIDIA_TIMEOUT_MAX", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
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
    assert vistos["nvidia"] == 15


def test_teto_por_provedor_so_muda_este_provedor(monkeypatch):
    """Um modelo lento na NIM não obriga os provedores rápidos a esperar."""
    from curio.stages import nvidia as N
    monkeypatch.delenv("NVIDIA_TIMEOUT_MAX", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k2")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setitem(N.LLM_PROVIDER_TIMEOUT, "nvidia", 90)
    vistos = {}

    def fake_post(messages, key, model, base_url, timeout, max_tokens,
                  temperature, pid, json_mode=False):
        vistos.setdefault(pid, timeout)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(N, "_post_with_retries", fake_post)
    N._chat([{"role": "user", "content": "oi"}], 100, 0.0, "m", "https://x",
            timeout=120)
    assert vistos["nvidia"] == 90


def test_timeout_ainda_cai_no_rodizio():
    """O fast_fail de timeout se mantém: provedor lento não bloqueia."""
    from curio.stages import nvidia as N
    err = N.NvidiaError("timeout após 15s")
    err.retryable = True
    err.fast_fail = True
    assert err.fast_fail is True and err.retryable is True
