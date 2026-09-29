"""Integração LLM para geração de roteiros e cenas (etapa NVIDIA + fallback).

- Primário: NVIDIA API, endpoint OpenAI-compatível {base_url}/chat/completions
  (padrão: https://integrate.api.nvidia.com/v1), chave via NVIDIA_API_KEY.
- Fallback: OpenRouter, mesmo protocolo ({base_url}/chat/completions,
  padrão: https://openrouter.ai/api/v1), chave via OPENROUTER_API_KEY e
  modelo via OPENROUTER_MODEL (padrão: google/gemini-2.5-flash).
- Robustez: cada provedor tem até 5 tentativas (CURIO_LLM_ATTEMPTS, 1–10)
  com backoff para falhas transitórias (timeout, conexão, HTTP 429/5xx).
  401/403 (chave inválida) e 404 (modelo inexistente) NÃO repetem — falham
  direto com a causa provável. Esgotado o primário, tenta o fallback; sem
  chave de fallback, o erro final explica como habilitá-lo.
- Somente stdlib (urllib). Erros explícitos; chaves nunca aparecem em
  mensagens, logs ou metadados.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
DEFAULT_TIMEOUT = 60

OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "google/gemini-2.5-flash"

# Tentativas por provedor (1ª + retries). Override: CURIO_LLM_ATTEMPTS=3.
DEFAULT_ATTEMPTS = 5
RETRY_BASE_DELAY = 2.0  # backoff: 2s, 4s, 8s, 16s…

# Modelos irmãos da família Nemotron 3 (referência futura — NÃO usados aqui:
# sem fallback/round-robin nesta etapa).
FUTURE_MODELS = {
    "fallback": "nvidia/nemotron-3-super-120b-a12b",
    "scale": "nvidia/nemotron-3.5-lightning-30b-a3b",
}

SCRIPT_SYSTEM_PROMPT = (
    "Você escreve roteiros curtos e envolventes de vídeo educativo em "
    "português do Brasil. O roteiro será lido em voz alta e deve durar cerca "
    "de 45 segundos (no máximo {max_chars} caracteres). Regras de narrativa "
    "(obrigatórias): "
    "1) comece com uma pergunta, afirmação intrigante ou problema; "
    "2) toda pergunta criada deve ser respondida em algum momento; "
    "3) crie novas perguntas ao longo do roteiro para manter a curiosidade; "
    "4) cada parte leva naturalmente à próxima, com progressão — não entregue "
    "tudo de uma vez; "
    "5) priorize o mais interessante e surpreendente; corte o que não ajuda "
    "a história; seja conciso; "
    "6) termine respondendo à ideia principal apresentada no início; "
    "7) escreva como quem conta algo interessante a um amigo, não como quem "
    "lê um artigo: frases faladas e curtas, com ritmo; perguntas retóricas, "
    "comparações simples e pequenas surpresas são bem-vindas; um toque de "
    "personalidade, sem gíria e sem forçar humor; "
    "8) proibido introduções genéricas ('Olá pessoal, hoje vamos falar "
    "sobre...', 'Você sabia que' e equivalentes); "
    "9) nunca invente fatos, datas, nomes ou citações para ficar interessante; "
    "se algo for incerto ou disputado, diga com honestidade; "
    "10) sem fontes falsas nem estudos inexistentes. "
    "11) proibido tom de documentário institucional e conclusões artificiais "
    "('diante disso, podemos concluir', 'é importante ressaltar', 'vale "
    "destacar', moral da história ou resumo acadêmico); feche com a resposta "
    "ou uma observação que aproxime o assunto do espectador. "
    "FORMATO DE SAÍDA (obrigatório): responda SOMENTE com o texto da narração. "
    "PROIBIDO: títulos, 'Cena 1', 'Narrador:', rubricas entre colchetes, "
    "markdown, listas, aspas de diálogo, emojis, preâmbulos como 'Aqui está' "
    "ou qualquer explicação sobre o roteiro. Se precisar raciocinar, faça-o "
    "apenas no raciocínio interno, nunca no texto final. "
    "Princípio editorial: simplificar para tornar acessível, nunca falsificar "
    "para viralizar. O objetivo é o espectador continuar assistindo porque "
    "sempre há uma pergunta sendo respondida e outra surgindo."
)


class NvidiaError(RuntimeError):
    """Falha na etapa LLM. Mensagens nunca contêm API keys."""


class _Skipped(RuntimeError):
    """Provedor pulado (sem chave) — não é falha, só indisponibilidade."""


def max_attempts() -> int:
    """Tentativas por provedor: 5 por padrão (CURIO_LLM_ATTEMPTS sobrescreve)."""
    try:
        return max(1, min(10, int(os.environ.get("CURIO_LLM_ATTEMPTS", "5"))))
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

    def rotate(self) -> str:
        """NÃO IMPLEMENTADO nesta etapa (sem round-robin/sorteio/fallback)."""
        raise NotImplementedError(
            "rotação de chaves NVIDIA ainda não implementada "
            "(usar sempre a primeira chave configurada)."
        )


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


def openrouter_settings() -> tuple[str, str]:
    """Retorna (model, base_url) do fallback (env > padrões)."""
    model = os.environ.get("OPENROUTER_MODEL",
                           OPENROUTER_DEFAULT_MODEL).strip()
    base = os.environ.get("OPENROUTER_BASE_URL",
                          OPENROUTER_DEFAULT_BASE_URL).strip().rstrip("/")
    return model or OPENROUTER_DEFAULT_MODEL, base or OPENROUTER_DEFAULT_BASE_URL


def _http_error_message(status: int, body: str, model: str,
                        provider: str = "NVIDIA",
                        key_hint: str = "NVIDIA_API_KEY") -> str:
    snippet = body.strip()[:300]
    if status in (401, 403):
        return (
            f"etapa {provider}: autenticação rejeitada (HTTP 401/403). "
            f"Motivo provável: {key_hint} inválida ou expirada. "
            "Gere outra chave e tente novamente."
        )
    if status == 404:
        return (
            f"etapa {provider}: modelo {model!r} não encontrado (HTTP 404). "
            f"Motivo provável: modelo incorreto ou sem acesso. "
            + ("Confira o ID exato em https://build.nvidia.com."
               if provider == "NVIDIA" else
               "Confira o ID exato em https://openrouter.ai/models.")
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
               timeout: int, max_tokens: int, temperature: float,
               provider: str, key_hint: str) -> dict:
    """Uma tentativa HTTP. Erro transitório sai marcado (retryable=True)."""
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json",
                  "Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — melhor mensagem parcial que nenhuma
            detail = ""
        err = NvidiaError(_http_error_message(exc.code, detail, model,
                                              provider, key_hint))
        # 401/403/404 são definitivos (repetir não adianta); o resto repete.
        err.retryable = exc.code == 429 or 500 <= exc.code < 600
        raise err from exc
    except (socket.timeout, TimeoutError) as exc:
        err = NvidiaError(
            f"etapa {provider}: timeout após {timeout}s com o modelo {model}."
        )
        err.retryable = True
        raise err from exc
    except urllib.error.URLError as exc:
        err = NvidiaError(
            f"etapa {provider}: falha de conexão com a API. "
            f"Motivo provável: {exc.reason}. Verifique rede e base_url."
        )
        err.retryable = True
        raise err from exc


def _post_with_retries(messages: list[dict], key: str, model: str,
                       base_url: str, timeout: int, max_tokens: int,
                       temperature: float, provider: str,
                       key_hint: str) -> dict:
    """Até N tentativas com backoff para falhas transitórias.

    N = CURIO_LLM_ATTEMPTS (padrão 5). Erro definitivo (401/403/404) ou
    esgotamento levantam o último NvidiaError com o nº de tentativas.
    """
    attempts, last = max_attempts(), None
    for i in range(1, attempts + 1):
        try:
            return _post_once(messages, key, model, base_url, timeout,
                              max_tokens, temperature, provider, key_hint)
        except NvidiaError as exc:
            last = exc
            if not getattr(exc, "retryable", False) or i == attempts:
                if i == attempts and getattr(exc, "retryable", False):
                    last = NvidiaError(
                        f"{exc} (após {attempts} tentativas)")
                raise last
            delay = RETRY_BASE_DELAY * (2 ** (i - 1))
            print(f"[{provider}] tentativa {i}/{attempts} falhou "
                  f"(transitório): {exc} — nova tentativa em {delay:.0f}s…",
                  flush=True)
            time.sleep(delay)
    raise last  # inalcançável (loop sempre retorna ou levanta)


def _provider_attempt(provider: str, messages: list[dict], max_tokens: int,
                      temperature: float, model: str, base_url: str,
                      timeout: int, metrics=None) -> tuple[dict, str]:
    """Uma rodada completa num provedor (com retries). Retorna (body, rótulo).

    `provider` é "nvidia" ou "openrouter" (minúsculo); o rótulo segue o
    formato "provedor:modelo" para proveniência em metadata/métricas.
    """
    display = "OpenRouter" if provider == "openrouter" else "NVIDIA"
    if provider == "openrouter":
        key = OpenRouterCredentials.from_env().active_key  # _Skipped sem chave
        key_hint = "OPENROUTER_API_KEY"
    else:
        key = NvidiaCredentials.from_env().active_key
        key_hint = "NVIDIA_API_KEY"
    body = _post_with_retries(messages, key, model, base_url, timeout,
                              max_tokens, temperature, display, key_hint)
    if metrics is not None:
        metrics.nvidia(f"{provider}:{model}", (body or {}).get("usage"))
    return body, f"{provider}:{model}"


def _chat(messages: list[dict], max_tokens: int, temperature: float,
          model: str, base_url: str, timeout: int,
          or_model: str | None = None, or_base_url: str | None = None,
          metrics=None) -> tuple[dict, str]:
    """Chat com fallback: NVIDIA (retries) → OpenRouter (retries).

    Retorna (body, rótulo-do-provedor). Sem chave OpenRouter, o erro final
    explica como habilitá-lo; com ambas falhando, resume as duas tentativas.
    """
    failures: list[str] = []
    try:
        return _provider_attempt("nvidia", messages, max_tokens, temperature,
                                 model, base_url, timeout, metrics)
    except _Skipped as exc:  # não deve ocorrer (callers exigem chave NVIDIA)
        failures.append(str(exc))
    except NvidiaError as exc:
        failures.append(f"NVIDIA ({model}): {exc}")
    dft_model, dft_base = openrouter_settings()
    try:
        return _provider_attempt("openrouter", messages, max_tokens,
                                 temperature, or_model or dft_model,
                                 or_base_url or dft_base, timeout, metrics)
    except _Skipped as exc:
        failures.append(str(exc))
    except NvidiaError as exc:
        failures.append(f"OpenRouter ({or_model or dft_model}): {exc}")
    raise NvidiaError("LLM indisponível: " + " | ".join(failures))


def _extract_json(text: str) -> dict:
    """Extrai o JSON mesmo com cercas/preâmbulo/epílogo ao redor."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("sem objeto JSON na resposta")
    return json.loads(cleaned[start:end + 1])


def complete_json(system_prompt: str, user_prompt: str, model: str,
                  base_url: str, timeout: int, metrics=None,
                  or_model: str | None = None,
                  or_base_url: str | None = None) -> tuple[dict, str]:
    """Uma completion que DEVE retornar JSON (NVIDIA → fallback OpenRouter).

    Retorna (dados, rótulo "provedor:modelo"). Falhas levantam NvidiaError
    resumindo as tentativas nos dois provedores.
    """
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}]
    max_tokens, body, label = 2000, None, ""
    for _ in range(2):  # roteiros longos (60 s+) estouram 2000 tokens pensando
        body, label = _chat(messages, max_tokens, 0.3, model, base_url,
                            timeout, or_model, or_base_url, metrics)
        if (body.get("choices") or [{}])[0].get("finish_reason") != "length":
            break
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
            f"[{label}] JSON das cenas truncado mesmo com orçamento estendido."
        )
    try:
        return _extract_json(text), label
    except (ValueError, json.JSONDecodeError) as exc:
        raise NvidiaError(
            f"[{label}] API não retornou JSON válido para as cenas."
        ) from exc


def generate_script(idea: str, creds: NvidiaCredentials, model: str,
                    base_url: str, timeout: int, max_chars: int,
                    metrics=None, or_model: str | None = None,
                    or_base_url: str | None = None) -> tuple[str, str]:
    """Gera o roteiro (NVIDIA → fallback OpenRouter). Nunca silêncio.

    Retorna (texto, rótulo "provedor:modelo"). Falhas levantam NvidiaError.
    """
    creds.active_key  # levanta se não houver chave NVIDIA
    messages = [
        {"role": "system",
         "content": SCRIPT_SYSTEM_PROMPT.format(max_chars=max_chars)},
        {"role": "user",
         "content": f"Escreva o roteiro de narração para a ideia: {idea}"},
    ]
    # Modelos de raciocínio gastam tokens pensando: orçamento folgado e,
    # se truncar (finish_reason=length), UMA escalada antes de desistir.
    body, label, max_tokens = None, "", 1500
    for _ in range(2):
        body, label = _chat(messages, max_tokens, 0.7, model, base_url,
                            timeout, or_model, or_base_url, metrics)
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
    cleaned = _sanitize(text or "", max_chars)
    if len(cleaned) < 100:
        raise NvidiaError(
            f"[{label}] API retornou texto inválido para narração "
            "(vazio, curto demais ou só raciocínio)."
        )
    return cleaned, label


def _sanitize(text: str, max_chars: int) -> str:
    # Remove raciocínio vazado, cercas de código e rubricas de roteiro
    # ("Cena 1", "Narrador:", colchetes) — nada disso pode ir para o TTS.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"\[[^\]\n]*\]", "", text)  # [Cena 1: ...], [trilha]...
    text = re.sub(r"(?im)^\s*(narrador|narração|roteiro)\s*:\s*", "", text)
    text = re.sub(r"(?i)^(aqui está[^:]*|roteiro[^:]*|claro!?)\s*:?\s*", "", text.strip())
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
