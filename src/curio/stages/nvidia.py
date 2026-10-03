"""Integração LLM para geração de roteiros e cenas (etapa multi-provedor).

Chain OpenAI-compatível (`{base_url}/chat/completions`), nesta ordem —
cada um pulado sem chave, tentado com retries quando há chave:
1. Groq;
2. NVIDIA;
3. OpenRouter;
4. Mistral;
5. Gemini.
- Rodízio intercalado para texto livre; JSON segue ordem preferencial.
  Erros definitivos removem provider; HTTP 429 tem retry curto e timeout é
  sempre finito. Falha de planejamento visual preserva narração localmente.
- Somente stdlib (urllib). Erros explícitos; chaves nunca aparecem em
  mensagens, logs ou metadados.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
import urllib.parse
from email.utils import parsedate_to_datetime

from .. import __version__
from .prompts import SCRIPT_SYSTEM_PROMPT, SCRIPT_SYSTEM_PROMPT_EN

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"
DEFAULT_TIMEOUT = 60

OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"

GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-20b"

MISTRAL_DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
MISTRAL_DEFAULT_MODEL = "mistral-small-latest"

# Chain de provedores (ordem fixa): id → exibição, envs de chave (1ª
# existente vence), envs de modelo/base, padrões e ajuda p/ HTTP 404.
PROVIDER_SPECS = {
    "nvidia": {
        "display": "NVIDIA",
        "key_envs": ("NVIDIA_API_KEY", "NVIDIA_API_KEYS"),
        "model_env": "NVIDIA_MODEL",
        "base_env": "NVIDIA_BASE_URL",
        "default_model": DEFAULT_MODEL,
        "default_base": DEFAULT_BASE_URL,
        "models_url": "https://build.nvidia.com",
    },
    "openrouter": {
        "display": "OpenRouter",
        "key_envs": ("OPENROUTER_API_KEY",),
        "model_env": "OPENROUTER_MODEL",
        "base_env": "OPENROUTER_BASE_URL",
        "default_model": OPENROUTER_DEFAULT_MODEL,
        "default_base": OPENROUTER_DEFAULT_BASE_URL,
        "models_url": "https://openrouter.ai/models",
    },
    "gemini": {
        "display": "Gemini",
        "key_envs": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "model_env": "GEMINI_MODEL",
        "base_env": "GEMINI_BASE_URL",
        "default_model": GEMINI_DEFAULT_MODEL,
        "default_base": GEMINI_DEFAULT_BASE_URL,
        "models_url": "https://ai.google.dev/models",
    },
    "groq": {
        "display": "Groq",
        "key_envs": ("GROQ_API_KEY",),
        "model_env": "GROQ_MODEL",
        "base_env": "GROQ_BASE_URL",
        "default_model": GROQ_DEFAULT_MODEL,
        "default_base": GROQ_DEFAULT_BASE_URL,
        "models_url": "https://console.groq.com/docs/models",
    },
    "mistral": {
        "display": "Mistral",
        "key_envs": ("MISTRAL_API_KEY",),
        "model_env": "MISTRAL_MODEL",
        "base_env": "MISTRAL_BASE_URL",
        "default_model": MISTRAL_DEFAULT_MODEL,
        "default_base": MISTRAL_DEFAULT_BASE_URL,
        "models_url": "https://docs.mistral.ai/getting-started/models/models_overview/",
    },
}
PROVIDER_ORDER = ("groq", "nvidia", "openrouter", "mistral", "gemini")

# Tentativas totais no rodízio (`CURIO_LLM_ATTEMPTS`). Padrão 6.
DEFAULT_ATTEMPTS = 6
RETRY_BASE_DELAY = 2.0  # backoff: 2s, 4s, 8s… (teto 30s)
RATE_LIMIT_MAX_ATTEMPTS = 2
RATE_LIMIT_MAX_WAIT = 5.0

# Modelos irmãos da família Nemotron 3 (referência futura — NÃO usados aqui:
# sem fallback/round-robin nesta etapa).
FUTURE_MODELS = {
    "fallback": "nvidia/nemotron-3-super-120b-a12b",
    "scale": "nvidia/nemotron-3.5-lightning-30b-a3b",
}

class NvidiaError(RuntimeError):
    """Falha na etapa LLM. Mensagens nunca contêm API keys."""


class _Skipped(RuntimeError):
    """Provedor pulado (sem chave) — não é falha, só indisponibilidade."""


def max_attempts() -> int:
    """Rodadas globais de provider: 6 por padrão (CURIO_LLM_ATTEMPTS)."""
    try:
        return max(1, min(12, int(os.environ.get("CURIO_LLM_ATTEMPTS", "6"))))
    except ValueError:
        return DEFAULT_ATTEMPTS


class NvidiaCredentials:
    """Portador das chaves NVIDIA.

    Aceita 1..N chaves apenas como PREPARAÇÃO para o futuro. Nesta etapa,
    `active_key` retorna sempre a primeira chave — sem rotação, sem sorteio,
    sem retry entre chaves, sem chamadas paralelas.
    """

    def __init__(self, keys: list[str]):
        self.keys = tuple(k.strip() for k in keys if k and k.strip())

    @classmethod
    def from_env(cls) -> "NvidiaCredentials":
        raw_multi = os.environ.get("NVIDIA_API_KEYS", "")
        keys = [k for k in raw_multi.split(",") if k.strip()]
        single = os.environ.get("NVIDIA_API_KEY", "").strip()
        if single and single not in keys:
            keys.append(single)
        return cls(keys)

    @property
    def available(self) -> bool:
        return len(self.keys) > 0

    @property
    def count(self) -> int:
        return len(self.keys)

    @property
    def active_key(self) -> str:
        if not self.keys:
            raise NvidiaError(
                "etapa NVIDIA: nenhuma chave configurada. "
                "Defina NVIDIA_API_KEY (ou NVIDIA_API_KEYS) — veja .env.example. "
                "Sem chave, o pipeline usa o gerador local de roteiros."
            )
        return self.keys[0]


class OpenRouterCredentials:
    """Chave do fallback OpenRouter (OPENROUTER_API_KEY, única)."""

    def __init__(self, key: str = ""):
        self.key = (key or "").strip()

    @classmethod
    def from_env(cls) -> "OpenRouterCredentials":
        return cls(os.environ.get("OPENROUTER_API_KEY", ""))

    @property
    def available(self) -> bool:
        return bool(self.key)

    @property
    def active_key(self) -> str:
        if not self.key:
            raise _Skipped(
                "OpenRouter pulado (sem OPENROUTER_API_KEY no ambiente). "
                "Defina a chave no .env para ter fallback automático "
                "quando a NVIDIA falhar — veja .env.example."
            )
        return self.key


class _SingleKeyCredentials:
    """Base p/ provedores de chave única (mensagem de pulo padronizada)."""

    provider = ""
    key_envs: tuple = ()

    def __init__(self, key: str = ""):
        self.key = (key or "").strip()

    @classmethod
    def from_env(cls):
        found = ""
        for env in cls.key_envs:
            if os.environ.get(env, "").strip():
                found = os.environ[env].strip()
                break
        return cls(found)

    @property
    def available(self) -> bool:
        return bool(self.key)

    @property
    def active_key(self) -> str:
        if not self.key:
            spec = PROVIDER_SPECS[self.provider]
            raise _Skipped(
                f"{spec['display']} pulado (sem {spec['key_envs'][0]} "
                "no ambiente). Defina a chave no .env — veja .env.example."
            )
        return self.key


class GeminiCredentials(_SingleKeyCredentials):
    """Chave do Gemini direto (GEMINI_API_KEY ou GOOGLE_API_KEY)."""

    provider = "gemini"
    key_envs = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


class GroqCredentials(_SingleKeyCredentials):
    """Chave do Groq (GROQ_API_KEY)."""

    provider = "groq"
    key_envs = ("GROQ_API_KEY",)


class MistralCredentials(_SingleKeyCredentials):
    """Chave do Mistral (MISTRAL_API_KEY)."""

    provider = "mistral"
    key_envs = ("MISTRAL_API_KEY",)


CREDENTIALS = {
    "nvidia": NvidiaCredentials,
    "openrouter": OpenRouterCredentials,
    "gemini": GeminiCredentials,
    "groq": GroqCredentials,
    "mistral": MistralCredentials,
}


def any_llm_available() -> bool:
    """Há ao menos um provedor LLM com chave (qualquer um do chain)."""
    return any(cls.from_env().available for cls in CREDENTIALS.values())


def llm_settings(provider: str) -> tuple[str, str]:
    """Retorna (model, base_url) do provedor (env > padrões)."""
    spec = PROVIDER_SPECS[provider]
    model = os.environ.get(spec["model_env"], spec["default_model"]).strip()
    base = os.environ.get(spec["base_env"], spec["default_base"]).strip().rstrip("/")
    return model or spec["default_model"], base or spec["default_base"]


def _http_error_message(status: int, body: str, model: str,
                        provider: str = "NVIDIA",
                        key_hint: str = "NVIDIA_API_KEY",
                        models_url: str | None = None) -> str:
    snippet = body.strip()[:300]
    if provider.lower() in ("groq", "mistral") and 400 <= status < 500:
        api_message = body.strip()[:1200] or "corpo vazio"
        return (f"etapa {provider}: API respondeu HTTP {status}. "
                f"Mensagem da API: {api_message}")
    if status in (401, 403):
        detail = f" Mensagem da API: {body.strip()[:1200]}" if body.strip() else ""
        return (
            f"etapa {provider}: acesso rejeitado (HTTP {status}). "
            f"Verifique {key_hint}, permissões, modelo e endpoint.{detail}"
        )
    if status == 404:
        hint = (f"Confira o ID exato em {models_url}."
                if models_url else "Confira o ID exato do modelo.")
        return (
            f"etapa {provider}: modelo {model!r} não encontrado (HTTP 404). "
            f"Motivo provável: modelo incorreto ou sem acesso. {hint}"
        )
    if status == 429:
        return (
            f"etapa {provider}: limite de requisições excedido (HTTP 429). "
            "Aguarde alguns minutos e tente novamente. "
            "Rotação entre chaves ainda não está implementada."
        )
    if 500 <= status < 600:
        return (
            f"etapa {provider}: erro no servidor (HTTP {status}). "
            f"Detalhe: {snippet}. Tente novamente em instantes."
        )
    return (
        f"etapa {provider}: requisição rejeitada (HTTP {status}). "
        f"Detalhe: {snippet}. Verifique modelo e parâmetros."
    )


def _post_once(messages: list[dict], key: str, model: str, base_url: str,
               timeout: int | None, max_tokens: int, temperature: float,
               pid: str, json_mode: bool = False,
               connect_timeout: int | None = None) -> dict:
    """Uma tentativa HTTP. Erro transitório sai marcado (retryable=True).

    Conexão e resposta têm orçamentos separados: o handshake usa
    `connect_timeout` (padrão 10 s); o envio+resposta usa `timeout`
    (orçamento total de resposta/processamento; sempre finito).
    """
    import http.client
    spec = PROVIDER_SPECS[pid]
    display, key_hint = spec["display"], spec["key_envs"][0]
    payload_dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if pid == "groq" and model.startswith("openai/gpt-oss-"):
        # Groq GPT-OSS gastou os 2000 tokens padrão quase todos em reasoning
        # (1998 tokens no teste real) e retornou finish_reason=length sem
        # conteúdo. Low reasoning effort conserva o orçamento para a resposta.
        payload_dict["reasoning_effort"] = "low"
    if json_mode:
        payload_dict["response_format"] = {"type": "json_object"}
    payload = json.dumps(payload_dict).encode()
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + key,
               "Content-Length": str(len(payload))}
    if pid == "groq":
        # Groq/Cloudflare bloqueia o User-Agent Python-urllib padrão (HTTP 403
        # Cloudflare 1010). Identifique a aplicação sem simular navegador.
        headers["User-Agent"] = f"curio/{__version__} (LLM API client)"
    else:
        headers["User-Agent"] = f"curio/{__version__} (LLM API client)"
    try:
        ctimeout = llm_connect_timeout(connect_timeout)
    except Exception:  # noqa: BLE001 — nunca derruba a chamada
        ctimeout = CONNECT_TIMEOUT_DEFAULT
    total = call_timeout_max(timeout)
    parts = urllib.parse.urlsplit(base_url.rstrip("/") + "/chat/completions")
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = parts.path or "/chat/completions"
    if parts.query:
        path += "?" + parts.query
    conn_cls = (http.client.HTTPSConnection if parts.scheme == "https"
                else http.client.HTTPConnection)
    conn = conn_cls(host, port, timeout=ctimeout)
    start = time.monotonic()
    try:
        conn.connect()
    except (socket.timeout, TimeoutError) as exc:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — limpeza best-effort
            pass
        err = NvidiaError(
            f"etapa {display}: conexão/handshake excedeu {ctimeout}s "
            f"com {host} (rede ou endpoint; o orçamento de geração nem "
            f"foi consumido).")
        err.retryable = True
        err.http_attempts = 1
        err.fast_fail = True
        raise err from exc
    except OSError as exc:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — limpeza best-effort
            pass
        err = NvidiaError(
            f"etapa {display}: conexão interrompida pela API. "
            f"Motivo provável: {exc}. Verifique rede e base_url."
        )
        err.retryable = True
        err.http_attempts = 1
        raise err from exc
    # Handshake OK: o socket passa a tolerar até o orçamento TOTAL
    # (modelo lento que transmite aos poucos não é cortado no meio).
    try:
        conn.sock.settimeout(total)
    except (OSError, AttributeError):
        pass
    try:
        conn.request("POST", path, body=payload, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        # Leitura em chunks com teto total: silêncio além do orçamento
        # vira timeout de resposta/processamento, não de conexão.
        chunks: list[bytes] = []
        deadline = start + total
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"orçamento total de {total}s excedido lendo a resposta")
            try:
                piece = resp.read(65536)
            except (socket.timeout, TimeoutError) as exc:
                raise TimeoutError(str(exc) or "silêncio na resposta") from exc
            if not piece:
                break
            chunks.append(piece)
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"orçamento total de {total}s excedido lendo a resposta")
        raw = b"".join(chunks)
    except (socket.timeout, TimeoutError) as exc:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — limpeza best-effort
            pass
        prazo = f"{total}s de resposta/processamento"
        err = NvidiaError(
            f"etapa {display}: timeout de resposta/processamento "
            f"({prazo}) com o modelo {model} — conexão OK, o modelo "
            f"não concluiu a tempo. Detalhe: {exc}.")
        err.retryable = True
        err.http_attempts = 1
        # Resposta lenta: não repetir internamente; chain troca de provider.
        err.fast_fail = total is not None
        raise err from exc
    except (http.client.HTTPException, OSError) as exc:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — limpeza best-effort
            pass
        err = NvidiaError(
            f"etapa {display}: conexão interrompida pela API. "
            f"Motivo provável: {exc}. Verifique rede e base_url."
        )
        err.retryable = True
        err.http_attempts = 1
        raise err from exc
    try:
        conn.close()
    except Exception:  # noqa: BLE001 — limpeza best-effort
        pass
    if status >= 400:
        try:
            detail = raw.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — melhor mensagem parcial que nenhuma
            detail = ""
        if key:
            detail = detail.replace(key, "[REDACTED]")
        err = NvidiaError(_http_error_message(status, detail, model,
                                              display, key_hint,
                                              spec["models_url"]))
        err.http_status = status
        # 4xx, exceto 429, são definitivos; 429/5xx seguem retries internos.
        err.retryable = status == 429 or 500 <= status < 600
        err.http_attempts = 1
        if status == 429:
            err.retry_after = _retry_after_seconds(resp, detail)
        raise err
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        err = NvidiaError(
            f"etapa {display}: resposta não-JSON da API "
            f"({len(raw)} bytes).")
        err.retryable = True
        err.http_attempts = 1
        raise err from exc
    return body


def _retry_after_seconds(response, detail: str) -> float | None:
    """Read Retry-After header or Groq's textual wait hint."""
    raw = ""
    getheader = getattr(response, "getheader", None)
    if callable(getheader):
        try:
            raw = str(getheader("Retry-After") or "").strip()
        except Exception:  # noqa: BLE001 — diagnostic metadata is optional
            raw = ""
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(raw).timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                pass
    match = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|seconds?)",
                      str(detail or ""), re.I)
    if not match:
        return None
    delay = float(match.group(1))
    return delay / 1000.0 if match.group(2).lower() in ("ms", "millisecond", "milliseconds") else delay


def _post_with_retries(messages: list[dict], key: str, model: str,
                       base_url: str, timeout: int | None, max_tokens: int,
                       temperature: float, pid: str, json_mode: bool = False) -> dict:
    """Até N requests HTTP dentro de uma rodada de provider.

    N = `max_attempts()` (padrão 6), exceto HTTP 429: no máximo duas tentativas
    curtas por provider, respeitando Retry-After até RATE_LIMIT_MAX_WAIT. Este
    contador é interno à rodada; `_chat` conta rodadas globais separadamente.
    """
    display = PROVIDER_SPECS[pid]["display"]
    attempts, last = max_attempts(), None
    for i in range(1, attempts + 1):
        try:
            return _post_once(messages, key, model, base_url, timeout,
                              max_tokens, temperature, pid, json_mode)
        except NvidiaError as exc:
            last = exc
            exc.http_attempts = i
            if getattr(exc, "fast_fail", False):
                raise last  # timeout: troca de provedor já, sem retry interno
            rate_limited = getattr(exc, "http_status", None) == 429
            attempt_limit = RATE_LIMIT_MAX_ATTEMPTS if rate_limited else attempts
            retry_after = getattr(exc, "retry_after", None)
            if rate_limited and retry_after is not None and retry_after > RATE_LIMIT_MAX_WAIT:
                exc.retry_exhausted = True
                raise last
            if not getattr(exc, "retryable", False) or i >= attempt_limit:
                if i >= attempt_limit and getattr(exc, "retryable", False):
                    last = NvidiaError(
                        f"{exc} (após {attempt_limit} tentativas)")
                    last.retryable = True
                    last.retry_exhausted = True
                    last.http_attempts = i
                    if rate_limited:
                        last.http_status = 429
                        last.retry_after = retry_after
                raise last
            delay = (min(RATE_LIMIT_MAX_WAIT, max(0.0, retry_after))
                     if rate_limited and retry_after is not None else
                     min(30.0, RETRY_BASE_DELAY * (2 ** (i - 1))))
            from ..runlog import event as run_event
            logged = run_event(
                "retry", f"{display}: tentativa {i}/{attempt_limit}; "
                f"{exc}; nova tentativa em {delay:.2f}s",
                provider=display, model=model, attempt=i,
                attempts=attempt_limit, delay_seconds=delay, error=str(exc))
            if not logged:
                print(f"[{display}] tentativa {i}/{attempt_limit} falhou "
                      f"(transitório): {exc} — nova tentativa em {delay:.2f}s…",
                      flush=True)
            time.sleep(delay)
    raise last  # inalcançável (loop sempre retorna ou levanta)


JSON_FIRST_ORDER = PROVIDER_ORDER

# Teto padrão por chamada HTTP LLM (s) — espera de RESPOSTA/processamento.
#
# Era 15 e RÍGIDO: um modelo grande e lento no NIM não tinha como ser
# usado. Agora o padrão é 120 e continua CONFIGURÁVEL (`[nvidia]
# timeout_max` ou NVIDIA_TIMEOUT_MAX): quem medir, ajusta; quem não,
# usa o padrão folgado em vez de cair no fallback à toa.
#
# `[nvidia] timeout_max` no config.toml, ou NVIDIA_TIMEOUT_MAX no .env.
LLM_CALL_TIMEOUT_MAX = 120

# Espera de CONEXÃO/handshake TLS por chamada (s) — SEPARADA da espera
# de resposta/processamento. Se o host não atende em 10 s, é rede ou
# endpoint errado, não modelo lento: falhar rápido aqui não consome o
# orçamento de geração. `[nvidia] connect_timeout` ou
# NVIDIA_CONNECT_TIMEOUT sobrescrevem.
CONNECT_TIMEOUT_DEFAULT = 10

# Timeout por PROVEDOR, quando a resposta deste é mais lenta que a dos
# outros. Mesma regra: vazio = o teto global, sem diferença nenhuma. Um
# modelo de 550B parâmetros que precisa de 40 s não vira o problema dos
# provedores rápidos, e um único número para todos obriga a escolher entre
# "um teto alto para todos" e "um teto baixo para todos".
LLM_PROVIDER_TIMEOUT: dict[str, int] = {}

# O QUE ESTES TIMEOUTS SÃO (separados de verdade)
#
#   connect timeout  — handshake TCP+TLS com o host da API (padrão 10 s).
#     Estoura aqui = rede/endpoint, não modelo lento. Falha rápido e o
#     rodízio troca de provedor sem gastar o orçamento de geração.
#   resposta/processamento — orçamento TOTAL da chamada (padrão 120 s),
#     do request ao body completo. Um 550B que transmite de tempos em
#     tempos NÃO é cortado no meio: o socket tolera cada recv até o
#     orçamento total, e só o silêncio além do total mata a chamada.
#
# Implementação stdlib (http.client): conecta com o timeout curto,
# depois eleva o timeout do socket para o orçamento total antes de
# enviar/ler. As mensagens distinguem "conexão/handshake" de
# "resposta/processamento" para o diagnóstico não misturar os dois.


def llm_connect_timeout(configured: int | None = None) -> int:
    """A espera de conexão, na ordem: config, env, padrão (10 s)."""
    if configured is not None:
        try:
            v = int(configured)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    env = os.environ.get("NVIDIA_CONNECT_TIMEOUT", "").strip()
    if env:
        try:
            v = int(env)
            if v > 0:
                return v
        except ValueError:
            pass
    return CONNECT_TIMEOUT_DEFAULT


def call_timeout_max(configured: int | None = None) -> int:
    """O teto de resposta/processamento, na ordem: config, env, padrão.

    Existe para que "aumentar o tempo do modelo lento" seja uma linha de
    configuração em vez de uma edição de código. O padrão é 120 s: um
    550B no NIM não conclui em 15 s.
    """
    if configured is not None:
        try:
            v = int(configured)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    env = os.environ.get("NVIDIA_TIMEOUT_MAX", "").strip()
    if env:
        try:
            v = int(env)
            if v > 0:
                return v
        except ValueError:
            pass
    return LLM_CALL_TIMEOUT_MAX


def _rotation(pids: list[str]):
    """Cycle providers in their declared preference order; budget limits rounds."""
    i = 0
    while True:
        yield pids[i % len(pids)]
        i += 1


def _order_live(live: list[str], prefer: tuple[str, ...] | None) -> list[str]:
    """Reordena provedores ativos pela preferência (estável p/ o resto)."""
    if not prefer:
        return list(live)
    rank = {pid: i for i, pid in enumerate(prefer)}
    return sorted(live, key=lambda p: rank.get(p, len(rank)))


def _chat(messages: list[dict], max_tokens: int, temperature: float,
           model: str, base_url: str, timeout: int,
           or_model: str | None = None, or_base_url: str | None = None,
           metrics=None, extra: dict | None = None, json_mode: bool = False,
           prefer: tuple[str, ...] | None = None,
           timeout_max: int | None = None,
           response_validator=None) -> tuple[dict, str]:
    """Chat em ordem de preferência: Groq, NVIDIA, OpenRouter, Mistral, Gemini.

    Cada rodada vai ao próximo provider; erros definitivos e timeouts finitos
    removem o provider do rodízio. Retorna (body, label). O budget global conta
    rodadas; retries HTTP internos são contabilizados à parte.

    `prefer` reordena providers, sem interleaving. Handshake e resposta têm
    orçamentos finitos para todos os providers.
    """
    try:
        timeout = max(1, min(int(timeout), call_timeout_max(timeout_max)))
    except (TypeError, ValueError):
        timeout = call_timeout_max(None)
    extra = extra or {}
    resolved: dict[str, tuple[str, str]] = {
        "nvidia": (model, base_url),
        "openrouter": (or_model, or_base_url),
    }
    for pid in PROVIDER_ORDER:
        if pid in resolved:
            continue
        resolved[pid] = extra.get(pid, (None, None))
    live = [pid for pid in PROVIDER_ORDER
            if CREDENTIALS[pid].from_env().available]
    live = _order_live(live, prefer)
    skipped = [f"{PROVIDER_SPECS[pid]['display']} pulado "
               f"(sem {PROVIDER_SPECS[pid]['key_envs'][0]})"
               for pid in PROVIDER_ORDER if pid not in live]
    if not live:
        raise NvidiaError(
            "LLM indisponível (nenhuma chave): " + " | ".join(skipped) + ". "
            "Defina ao menos uma no .env — veja .env.example.")
    budget, made = max_attempts(), 0
    rounds: dict[str, int] = {}
    attempts: dict[str, int] = {}
    last_err: dict[str, str] = {}
    for pid in _rotation(list(live)):
        if not live:
            break
        if live == ["nvidia"]:
            return _nvidia_final_attempt(
                messages, model, base_url, max_tokens, temperature, json_mode,
                timeout, metrics, budget, made, rounds, attempts, last_err, skipped)
        if made >= budget:
            break
        if pid not in live:
            continue  # eliminado do rodízio por erro definitivo
        made += 1
        rounds[pid] = rounds.get(pid, 0) + 1
        om, ob = resolved[pid]
        dft_model, dft_base = llm_settings(pid)
        use_model, use_base = om or dft_model, ob or dft_base
        teto_pid = timeout
        if pid != "nvidia" and pid in LLM_PROVIDER_TIMEOUT:
            teto_pid = max(timeout, int(LLM_PROVIDER_TIMEOUT[pid]))
        try:
            key = CREDENTIALS[pid].from_env().active_key
            body = _post_with_retries(messages, key, use_model, use_base,
                                      teto_pid, max_tokens, temperature, pid,
                                      json_mode)
            if metrics is not None:
                metrics.nvidia(f"{pid}:{use_model}", (body or {}).get("usage"))
            from ..runlog import event as run_event
            run_event("provider", f"Provider: {PROVIDER_SPECS[pid]['display']} / {use_model}",
                      provider=pid, model=use_model,
                      usage=(body or {}).get("usage"))
            if response_validator is not None:
                issue = response_validator(body)
                if issue:
                    error = NvidiaError(f"[{pid}:{use_model}] {issue}")
                    error.retryable = False
                    raise error
        except NvidiaError as exc:
            attempts[pid] = (attempts.get(pid, 0) +
                             max(1, int(getattr(exc, "http_attempts", 1))))
            last_err[pid] = str(exc)
            nvidia_bad_request = (pid == "nvidia"
                                  and getattr(exc, "http_status", None) == 400)
            if nvidia_bad_request:
                exc.retryable = False
            from ..runlog import event as run_event
            logged = run_event("fallback", f"{PROVIDER_SPECS[pid]['display']}: "
                               f"{exc}; tentando próximo provider",
                               provider=pid, model=resolved[pid][0],
                               retryable=getattr(exc, "retryable", False),
                               ignored_for_run=nvidia_bad_request,
                               http_status=getattr(exc, "http_status", None),
                               error=str(exc))
            if not getattr(exc, "retryable", False):
                live.remove(pid)  # definitivo: fora do rodízio
                if not logged:
                    print(f"[{PROVIDER_SPECS[pid]['display']}] erro definitivo "
                          f"— fora do rodízio: {exc}", flush=True)
            elif getattr(exc, "retry_exhausted", False):
                # Internal HTTP budget spent; do not start another retry block.
                live.remove(pid)
                if not logged:
                    print(f"[{PROVIDER_SPECS[pid]['display']}] esgotou "
                          f"{getattr(exc, 'http_attempts', 1)} tentativa(s) HTTP "
                          f"nesta rodada.", flush=True)
            elif getattr(exc, "fast_fail", False):
                if not logged:
                    print(f"[{PROVIDER_SPECS[pid]['display']}] tentativa "
                          f"{made}/{budget} falhou (timeout): {exc} — "
                          f"trocando de provedor já…", flush=True)
                live.remove(pid)
            elif made < budget and live:
                delay = min(30.0, RETRY_BASE_DELAY * (2 ** (made - 1)))
                if not logged:
                    print(f"[{PROVIDER_SPECS[pid]['display']}] tentativa "
                          f"{made}/{budget} falhou (transitório): {exc} — "
                          f"rodízio em {delay:.0f}s…", flush=True)
                time.sleep(delay)
            if live == ["nvidia"]:
                return _nvidia_final_attempt(
                    messages, model, base_url, max_tokens, temperature,
                    json_mode, timeout, metrics, budget, made, rounds,
                    attempts, last_err, skipped)
            continue
        return body, f"{pid}:{use_model}"
    if live == ["nvidia"]:
        return _nvidia_final_attempt(
            messages, model, base_url, max_tokens, temperature, json_mode,
            timeout, metrics, budget, made, rounds, attempts, last_err, skipped)
    raise NvidiaError(_survey(budget, made, attempts, last_err,
                              skipped, live, rounds))


def _survey(budget: int, made: int, attempts: dict, last_err: dict,
            skipped: list[str], remaining: list[str], rounds: dict | None = None,
            final_attempts: int = 0, final_outcome: str = "") -> str:
    """Levantamento final; separa rodadas do rodízio de requests HTTP."""
    rounds = rounds or {}
    parts = [f"LLM indisponível após {made}/{budget} rodada(s) globais"]
    for pid in PROVIDER_ORDER:
        spec = PROVIDER_SPECS[pid]
        if pid in attempts:
            parts.append(f"{spec['display']}: {attempts[pid]} tentativa(s) HTTP "
                         f"em {rounds.get(pid, 0)} rodada(s), "
                         f"último erro: {last_err.get(pid, '?')}")
    if final_attempts:
        parts.append(f"NVIDIA última tentativa: {final_attempts}/1 "
                     f"com timeout finito ({final_outcome or 'interrompido'}); "
                     f"último erro: {last_err.get('nvidia', '?')}")
    parts.extend(skipped)
    if remaining:
        parts.append("Ainda no rodízio sem sucesso: "
                     + ", ".join(PROVIDER_SPECS[p]['display'] for p in remaining))
    parts.append("Defina/renove as chaves no .env "
                 "(NVIDIA_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY, "
                 "GROQ_API_KEY) e confira modelos e rede.")
    return " | ".join(parts)


def _nvidia_final_attempt(messages: list[dict], model: str,
                          base_url: str, max_tokens: int,
                          temperature: float, json_mode: bool,
                          timeout: int,
                          metrics, budget: int, made: int,
                          rounds: dict, attempts: dict, last_err: dict,
                          skipped: list[str]) -> tuple[dict, str]:
    """Último caminho: uma tentativa NVIDIA limitada pelo timeout configurado."""
    display = PROVIDER_SPECS["nvidia"]["display"]
    from ..runlog import event as run_event
    limit = max(1, min(int(timeout), call_timeout_max(None)))
    run_event("fallback", "NVIDIA: última tentativa com timeout finito",
              provider="nvidia", model=model, timeout_seconds=limit,
              max_attempts=1)
    # RunLog-bound TUI suppresses several provider prints. Always show this
    # long-wait boundary so the operator knows fallback is active and bounded.
    print(f"[{display}] última tentativa limitada a {limit}s; "
          "falha de cenas usa divisão local.", file=sys.stderr, flush=True)
    key = CREDENTIALS["nvidia"].from_env().active_key
    try:
        body = _post_once(messages, key, model, base_url, limit,
                          max_tokens, temperature, "nvidia", json_mode)
    except NvidiaError as exc:
        last_err["nvidia"] = str(exc)
        raise NvidiaError(_survey(
            budget, made, attempts, last_err, skipped, [], rounds,
            final_attempts=1,
            final_outcome=("erro definitivo" if not getattr(exc, "retryable", False)
                           else f"timeout/transitório em {limit}s"))) from exc
    if metrics is not None:
        metrics.nvidia(f"nvidia:{model}", (body or {}).get("usage"))
    run_event("provider", f"Provider: NVIDIA / {model}",
              provider="nvidia", model=model,
              usage=(body or {}).get("usage"), fallback_attempt=1)
    return body, f"nvidia:{model}"


def _extract_json(text: str) -> dict:
    """Extrai o JSON mesmo com cercas/preâmbulo/epílogo ao redor."""
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip().strip("`").strip()
    # 1) o texto inteiro já é JSON (caso do response_format: json_object)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    # 2) heurística legado: do primeiro `{` ao último `}`
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("sem objeto JSON na resposta")
    return json.loads(cleaned[start:end + 1])


def _json_completion_diagnostic(body: dict, requested: int) -> dict:
    choice = (body.get("choices") or [{}])[0] if isinstance(body, dict) else {}
    message = choice.get("message") or {}
    content = message.get("content") or ""
    usage = body.get("usage") or {}
    return {
        "finish_reason": choice.get("finish_reason", "unavailable"),
        "max_tokens": requested,
        "completion_tokens": usage.get("completion_tokens", "unavailable"),
        "response_chars": len(content),
        "response_bytes": len(content.encode("utf-8")),
    }


def _format_json_diagnostics(items: list[dict]) -> str:
    return "; ".join(
        "finish_reason={finish_reason}, max_tokens={max_tokens}, "
        "completion_tokens={completion_tokens}, response_chars={response_chars}, "
        "response_bytes={response_bytes}".format(**item)
        for item in items)


def complete_json(system_prompt: str, user_prompt: str, model: str,
                  base_url: str, timeout: int, metrics=None,
                  or_model: str | None = None,
                  or_base_url: str | None = None,
                  extra: dict | None = None) -> tuple[dict, str]:
    """Uma completion que DEVE retornar JSON (chain com retries por provedor).

    Retorna (dados, rótulo "provedor:modelo"). Falhas levantam NvidiaError
    resumindo pulos e tentativas no chain.
    Usa response_format: json_object e segue ordem preferencial global.
    """
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}]
    max_tokens, body, label = 2000, None, ""
    diagnostics = []
    for retry in range(2):  # uma escalada, preservada como limite atual
        if retry:
            print(f"[cenas JSON] tentativa estendida solicitada: "
                  f"max_tokens={max_tokens}", file=sys.stderr)
        body, label = _chat(messages, max_tokens, 0.3, model, base_url,
                            timeout, or_model, or_base_url, metrics, extra,
                            json_mode=True, prefer=JSON_FIRST_ORDER)
        diagnostic = _json_completion_diagnostic(body, max_tokens)
        diagnostics.append(diagnostic)
        if diagnostic["finish_reason"] != "length":
            break
        print(f"[{label}] cenas JSON truncadas: "
              f"finish_reason=length, max_tokens={max_tokens}, "
              f"completion_tokens={diagnostic['completion_tokens']}, "
              f"response_bytes={diagnostic['response_bytes']}; "
              "tentando uma vez com orçamento estendido.", file=sys.stderr)
        max_tokens = 4000
    try:
        choice = body["choices"][0]
        text = choice["message"].get("content", "").strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise NvidiaError(
            f"[{label}] resposta inesperada da API (sem choices/message)."
        ) from exc
    if choice.get("finish_reason") == "length":
        raise NvidiaError(
            f"[{label}] JSON das cenas truncado mesmo com orçamento estendido; "
            f"tentativas: {_format_json_diagnostics(diagnostics)}."
        )
    try:
        return _extract_json(text), label
    except (ValueError, json.JSONDecodeError) as exc:
        raise NvidiaError(
            f"[{label}] API não retornou JSON válido para as cenas; "
            f"resposta: {_format_json_diagnostics(diagnostics)}; "
            f"parse: {exc}."
        ) from exc


def generate_script(idea: str, model: str,
                    base_url: str, timeout: int, max_chars: int | None,
                    metrics=None, or_model: str | None = None,
                    or_base_url: str | None = None,
                    extra: dict | None = None,
                    language: str = "pt-BR",
                    research: str | None = None,
                    genre_directive: str | None = None,
                    entity_context: str | None = None,
                    timeout_max: int | None = None) -> tuple[str, str]:
    """Gera o roteiro (chain com retries por provedor). Nunca silêncio.

    `max_chars=None` = Automático: duração livre, sem corte (só o teto de
    segurança). Com número, é meta de tamanho — nunca corta ideia no meio.
    Exige ao menos uma chave LLM (qualquer uma do chain). Retorna (texto,
    rótulo "provedor:modelo"). Falhas levantam NvidiaError.
    """
    from .script import AUTO_MAX_CHARS
    if not any_llm_available():
        raise NvidiaError(
            "etapa LLM: nenhuma chave configurada. Defina ao menos uma: "
            "NVIDIA_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY ou "
            "GROQ_API_KEY — veja .env.example. Sem chave, o pipeline usa "
            "o gerador local de roteiros."
        )
    auto = max_chars is None
    ceiling = AUTO_MAX_CHARS if auto else max_chars
    english = str(language or "").lower().startswith("en")
    if auto:
        duration_clause = (
            "automatic content-led duration, usually 45 to 90 seconds and near "
            "60 when the subject allows; finish the full explanation, no padding "
            f"or hard cut (technical ceiling {ceiling} characters)"
        ) if english else (
            "duração automática definida pelo conteúdo, geralmente 45 a 90 "
            "segundos e perto de 60 quando o tema permitir; conclua a explicação, "
            f"sem enrolar nem corte seco (teto técnico de {ceiling} caracteres)")
    else:
        duration_clause = (
            f"about {ceiling / 13.5:.0f} seconds long "
            f"(at most {ceiling} characters; target, never a hard cut)"
        ) if english else (
            f"com duração aproximada de {ceiling / 13.5:.0f} segundos "
            f"(no máximo {ceiling} caracteres; meta, não corte seco)")
    system_prompt = (SCRIPT_SYSTEM_PROMPT_EN if english else SCRIPT_SYSTEM_PROMPT)
    user_prompt = (
        f"Write the narration script for this idea: {idea}"
        if english else
        f"Escreva o roteiro de narração para a ideia: {idea}"
    )
    if (genre_directive or "").strip():
        # O gênero entra como DIREÇÃO, no fim: a voz continua sendo a do
        # system prompt (que é a que garante a prosa falada) e o bloco do
        # gênero decide estrutura, ritmo e o que não fazer.
        system_prompt = system_prompt + "\n\n" + genre_directive.strip()
    if (entity_context or "").strip():
        # QUEM é o sujeito, antes do QUE dizer. Este bloco vem da
        # resolução de entidade e não inventa nada: é o nome canônico,
        # as formas alternativas, os termos que identificam a pessoa e as
        # armadilhas de homônimo. Sem ele, o roteiro é escrito a partir da
        # frase da ideia, e um padre da Igreja vira "Jerônimo" no primeiro
        # parágrafo.
        user_prompt += "\n\n" + entity_context.strip()
    if (research or "").strip():
        # RAG: fatos reais entram no pedido; o system prompt já proíbe
        # afirmar qualquer fato fora deles.
        user_prompt += "\n\n" + research.strip()
    messages = [
        {"role": "system",
         "content": system_prompt.format(duration_clause=duration_clause)},
        {"role": "user", "content": user_prompt},
    ]
    # Modelos de raciocínio gastam tokens pensando: orçamento folgado e,
    # se truncar (finish_reason=length), UMA escalada antes de desistir.
    body, label, max_tokens = None, "", 1500
    for _ in range(2):
        body, label = _chat(messages, max_tokens, 0.7, model, base_url,
                            timeout, or_model, or_base_url, metrics, extra,
                            timeout_max=timeout_max,
                            response_validator=lambda response: (
                                _script_response_issue(response, ceiling)))
        if (body.get("choices") or [{}])[0].get("finish_reason") != "length":
            break
        max_tokens = 3000
    try:
        choice = body["choices"][0]
        text = choice["message"].get("content", "").strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise NvidiaError(
            f"[{label}] resposta inesperada da API (sem choices/message)."
        ) from exc
    if choice.get("finish_reason") == "length":
        raise NvidiaError(
            f"[{label}] resposta truncada mesmo com orçamento estendido."
        )
    cleaned = _sanitize(text or "", ceiling)
    if len(cleaned) < 100:
        raise NvidiaError(
            f"[{label}] API retornou texto inválido para narração "
            "(vazio, curto demais ou só raciocínio)."
        )
    return cleaned, label


def _sanitize(text: str, max_chars: int) -> str:
    # Remove raciocínio vazado, cercas de código e rubricas de roteiro
    # ("Cena 1", "Narrador:", colchetes) — nada disso pode ir para o TTS.
    text = re.sub(r"think.*?end", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"\[[^\]\n]*\]", "", text)  # [Cena 1: ...], [trilha]...
    text = re.sub(r"(?im)^\s*(narrador|narração|roteiro|narrator|script)\s*:\s*", "", text)
    text = re.sub(r"(?i)^(aqui está[^:]*|roteiro[^:]*|claro!?|here is[^:]*|here's[^:]*|sure!?|of course!?)\s*:?\s*", "", text.strip())
    # Remove marcadores de lista numerada ("0) ", "0), ", "1. ", ...) —
    # mesma blindagem das legendas, aplicada já na fonte (roteiro/TTS).
    from .subs import strip_list_markers as _strip_markers
    text = _strip_markers(text)
    text = text.replace("*", "").replace("#", "").replace('"', "")
    text = re.sub(r"\s+", " ", text).strip().strip("`' ")
    if len(text) <= max_chars:
        return text
    # Corta com dignidade: última fronteira de frase dentro do limite,
    # senão última palavra completa.
    cut = text[:max_chars]
    for sep in (". ", "! ", "? ", "... "):
        idx = cut.rfind(sep)
        if idx > max_chars * 0.5:
            return cut[: idx + 1].strip()
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "."


def _script_response_issue(body: dict, ceiling: int) -> str | None:
    """Reject unusably short narration inside provider rotation, without logging text."""
    choices = body.get("choices") if isinstance(body, dict) else None
    choice = choices[0] if choices else {}
    message = choice.get("message") if isinstance(choice, dict) else None
    if not isinstance(message, dict):
        message = {}
    content = message.get("content") or ""
    cleaned = _sanitize(str(content), ceiling)
    if len(cleaned) >= 100:
        return None
    reasoning = (message.get("reasoning_content") or message.get("reasoning")
                 or message.get("analysis") or "")
    usage = body.get("usage") or {}
    return ("API respondeu com narração inválida; tentando próximo provider "
            f"(finish_reason={choice.get('finish_reason', 'indisponível')}, "
            f"content_chars={len(str(content))}, sanitized_chars={len(cleaned)}, "
            f"reasoning_chars={len(str(reasoning))}, "
            f"completion_tokens={usage.get('completion_tokens', 'indisponível')}).")
