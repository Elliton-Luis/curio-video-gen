"""Integração com a NVIDIA API para geração de roteiros (etapa NVIDIA).

- Endpoint OpenAI-compatível: {base_url}/chat/completions
  (padrão: https://integrate.api.nvidia.com/v1).
- Autenticação por API key via ambiente: NVIDIA_API_KEY (única) ou
  NVIDIA_API_KEYS="key1,key2,..." (preparação futura).
- ESCOPO DELIBERADO: múltiplas chaves são ACEITAS na configuração, mas
  rotação, sorteio, fallback e retry entre chaves NÃO estão implementados.
  Usa-se sempre a primeira chave válida. Ver `NvidiaCredentials.rotate`.
- Somente stdlib (urllib). Erros explícitos; a chave nunca aparece em
  mensagens, logs ou metadados.
"""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
DEFAULT_TIMEOUT = 60

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
    "7) escreva como fala natural, nunca como texto acadêmico; "
    "8) proibido introduções genéricas ('Olá pessoal, hoje vamos falar "
    "sobre...', 'Você sabia que' e equivalentes); "
    "9) nunca invente fatos, datas, nomes ou citações para ficar interessante; "
    "se algo for incerto ou disputado, diga com honestidade; "
    "10) sem fontes falsas nem estudos inexistentes. "
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
    """Falha na etapa NVIDIA. Mensagens nunca contêm a API key."""


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


def _http_error_message(status: int, body: str, model: str) -> str:
    snippet = body.strip()[:300]
    if status in (401, 403):
        return (
            "etapa NVIDIA: autenticação rejeitada (HTTP 401/403). "
            "Motivo provável: NVIDIA_API_KEY inválida ou expirada. "
            "Gere outra chave e tente novamente."
        )
    if status == 404:
        return (
            f"etapa NVIDIA: modelo {model!r} não encontrado (HTTP 404). "
            "Motivo provável: NVIDIA_MODEL incorreto ou sem acesso. "
            "Confira o ID exato em https://build.nvidia.com."
        )
    if status == 429:
        return (
            "etapa NVIDIA: limite de requisições excedido (HTTP 429). "
            "Aguarde alguns minutos e tente novamente. "
            "Rotação entre chaves ainda não está implementada."
        )
    if 500 <= status < 600:
        return (
            f"etapa NVIDIA: erro no servidor da NVIDIA (HTTP {status}). "
            f"Detalhe: {snippet}. Tente novamente em instantes."
        )
    return (
        f"etapa NVIDIA: requisição rejeitada (HTTP {status}). "
        f"Detalhe: {snippet}. Verifique modelo e parâmetros."
    )


def _post(messages: list[dict], key: str, model: str, base_url: str,
          timeout: int, max_tokens: int, temperature: float) -> dict:
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
        raise NvidiaError(_http_error_message(exc.code, detail, model)) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise NvidiaError(
            f"etapa NVIDIA: timeout após {timeout}s com o modelo {model}. "
            "Tente novamente."
        ) from exc
    except urllib.error.URLError as exc:
        raise NvidiaError(
            "etapa NVIDIA: falha de conexão com a API. "
            f"Motivo provável: {exc.reason}. Verifique rede e NVIDIA_BASE_URL."
        ) from exc


def _request(idea: str, key: str, model: str, base_url: str,
               timeout: int, max_chars: int, max_tokens: int) -> dict:
    return _post(
        [{"role": "system",
          "content": SCRIPT_SYSTEM_PROMPT.format(max_chars=max_chars)},
         {"role": "user",
          "content": f"Escreva o roteiro de narração para a ideia: {idea}"}],
        key, model, base_url, timeout, max_tokens, 0.7)


def complete_json(system_prompt: str, user_prompt: str, model: str,
                  base_url: str, timeout: int) -> dict:
    """Uma completion que DEVE retornar JSON. Falhas levantam NvidiaError."""
    creds = NvidiaCredentials.from_env()
    key = creds.active_key
    body = _post([{"role": "system", "content": system_prompt},
                  {"role": "user", "content": user_prompt}],
                 key, model, base_url, timeout, 2000, 0.3)
    try:
        text = body["choices"][0]["message"].get("content", "").strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise NvidiaError(
            "etapa NVIDIA: resposta inesperada da API (sem choices/message). "
            "Tente novamente."
        ) from exc
    cleaned = re.sub(r"```(?:json)?", "", text).strip().strip("`")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise NvidiaError(
            "etapa NVIDIA: API não retornou JSON válido para as cenas. "
            "Tente novamente."
        ) from exc


def generate_script(idea: str, creds: NvidiaCredentials, model: str,
                    base_url: str, timeout: int, max_chars: int) -> str:
    """Gera o roteiro via NVIDIA API. Falhas levantam NvidiaError (nunca silêncio)."""
    key = creds.active_key  # levanta se não houver chave
    # Modelos de raciocínio gastam tokens pensando: orçamento folgado e,
    # se truncar (finish_reason=length), UMA escalada antes de desistir.
    body, max_tokens = None, 1500
    for _ in range(2):
        body = _request(idea, key, model, base_url, timeout, max_chars, max_tokens)
        if (body.get("choices") or [{}])[0].get("finish_reason") != "length":
            break
        max_tokens = 3000
    try:
        choice = body["choices"][0]
        text = choice["message"].get("content", "").strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise NvidiaError(
            "etapa NVIDIA: resposta inesperada da API (sem choices/message). "
            "Tente novamente."
        ) from exc
    if choice.get("finish_reason") == "length":
        raise NvidiaError(
            "etapa NVIDIA: resposta truncada mesmo com orçamento estendido. "
            "Tente novamente."
        )
    cleaned = _sanitize(text or "", max_chars)
    if len(cleaned) < 100:
        raise NvidiaError(
            "etapa NVIDIA: API retornou texto inválido para narração "
            "(vazio, curto demais ou só raciocínio). Tente novamente."
        )
    return cleaned


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
