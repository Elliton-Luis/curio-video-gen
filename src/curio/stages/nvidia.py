"""Integração LLM para geração de roteiros e cenas (etapa multi-provedor).

Chain OpenAI-compatível (`{base_url}/chat/completions`), nesta ordem —
cada um pulado sem chave, tentado com retries quando há chave:
1. NVIDIA (NVIDIA_API_KEY; modelo NVIDIA_MODEL, padrão Nemotron 3 Ultra);
2. OpenRouter (OPENROUTER_API_KEY; OPENROUTER_MODEL, padrão
   google/gemini-2.5-flash);
3. Gemini direto (GEMINI_API_KEY ou GOOGLE_API_KEY; GEMINI_MODEL, padrão
   gemini-2.5-flash; endpoint OpenAI-compatível do Google);
4. Groq (GROQ_API_KEY; GROQ_MODEL, padrão openai/gpt-oss-20b).
- Robustez em rodízio: a NVIDIA falhou 1x, já troca — a rotação
  intercala a NVIDIA entre os fallbacks (N, OpenRouter, N, Gemini, N,
  Groq…), até CURIO_LLM_ATTEMPTS rodadas globais (padrão 6); cada rodada
  pode conter retries HTTP internos com backoff. 401/403 (chave
  inválida) e 404 (modelo inexistente) eliminam o provedor do rodízio na
  hora. No fim, erro com levantamento completo: tentativas, últimos erros
  e chaves ausentes.
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
import urllib.error
import urllib.request

from .. import __version__

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
DEFAULT_TIMEOUT = 60

OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "google/gemini-2.5-flash"

GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"

GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-20b"

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
}
PROVIDER_ORDER = ("nvidia", "openrouter", "gemini", "groq")

# Tentativas TOTAIS no rodízio (CURIO_LLM_ATTEMPTS=8, por ex.). Padrão 6:
# NVIDIA, OpenRouter, NVIDIA, Gemini, NVIDIA, Groq.
DEFAULT_ATTEMPTS = 6
RETRY_BASE_DELAY = 2.0  # backoff: 2s, 4s, 8s… (teto 30s)

# Modelos irmãos da família Nemotron 3 (referência futura — NÃO usados aqui:
# sem fallback/round-robin nesta etapa).
FUTURE_MODELS = {
    "fallback": "nvidia/nemotron-3-super-120b-a12b",
    "scale": "nvidia/nemotron-3.5-lightning-30b-a3b",
}

SCRIPT_SYSTEM_PROMPT = (
    "Você escreve roteiros curtos e envolventes de vídeo educativo em "
    "português do Brasil. O roteiro será lido em voz alta, {duration_clause}. "
    "Regras de narrativa "
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
    "9) GROUNDING OBRIGATÓRIO: toda afirmação factual (datas, nomes, "
    "números, definições, eventos, etimologias) deve vir das FONTES "
    "FORNECIDAS junto ao pedido; é PROIBIDO afirmar qualquer fato ausente "
    "das fontes; se algo for incerto ou não estiver nas fontes, diga a "
    "incerteza com honestidade ou omita — nunca preencha com invenção; "
    "10) sem fontes falsas nem estudos inexistentes; nunca invente fatos, "
    "datas, nomes ou citações para ficar interessante; "
    "11) proibido tom de documentário institucional e conclusões artificiais "
    "('diante disso, podemos concluir', 'é importante ressaltar', 'vale "
    "destacar', moral da história ou resumo acadêmico); feche com a resposta "
    "ou uma observação que aproxime o assunto do espectador. "
    "12) explique conceitos complexos em palavras simples: se mencionar algo "
    "técnico, explique na hora com analogia ou definição direta (ex.: 'se o "
    "ângulo for rasante o suficiente, ou seja, se o ângulo for bem próximo "
    "do chão...'); nunca use jargão sem explicar. "
    "13) SEMPRE encerre assim: depois de responder a ideia principal, faça "
    "UMA pergunta aberta relacionada ao tema mas NÃO respondida no vídeo "
    "(gancho para comentários — ex.: 'mas será que se ele tivesse ido mais "
    "preparado para o frio, teria ganhado?'), e em seguida uma chamada curta "
    "para like ('deixe seu like e até o próximo vídeo'). "
    "FORMATO DE SAÍDA (obrigatório): responda SOMENTE com o texto da narração. "
    "PROIBIDO: títulos, 'Cena 1', 'Narrador:', rubricas entre colchetes, "
    "markdown, listas, aspas de diálogo, emojis, preâmbulos como 'Aqui está' "
    "ou qualquer explicação sobre o roteiro. Se precisar raciocinar, faça-o "
    "apenas no raciocínio interno, nunca no texto final. "
    "Princípio editorial: simplificar para tornar acessível, nunca falsificar "
    "para viralizar. O objetivo é o espectador continuar assistindo porque "
    "sempre há uma pergunta sendo respondida e outra surgindo."
)

TITLE_SYSTEM_PROMPT = (
    "Você cria o título de um vídeo a partir do roteiro educativo já pronto, "
    "em português do Brasil. Responda SOMENTE com JSON válido, sem markdown "
    "nem explicações: {\"title\": \"...\"}. Regras (obrigatórias): "
    "1) o título é SEMPRE uma pergunta terminando com '?'; "
    "2) representa a principal curiosidade que o vídeo responde (NUNCA copie "
    "a primeira frase do roteiro); "
    "3) curto: no máximo 55 caracteres; "
    "4) soa natural falado em voz alta; "
    "5) desperta curiosidade sem clickbait: nada de exagero, mistério falso "
    "ou promessa que o vídeo não cumpre; "
    "6) sem aspas, markdown, emojis, hashtags ou explicações. "
    "Princípio editorial: simplificar para tornar acessível, nunca falsificar "
    "para viralizar."
)

SCRIPT_SYSTEM_PROMPT_EN = (
    "You write short, engaging educational video scripts in American English. "
    "The script will be read aloud, {duration_clause}. "
    "Mandatory storytelling rules: "
    "1) start with an intriguing question, statement or problem; "
    "2) every question you raise must be answered at some point; "
    "3) raise new questions along the way to sustain curiosity; "
    "4) each part leads naturally to the next, with progression — never dump "
    "everything at once; "
    "5) prioritize the most interesting and surprising; cut whatever does not "
    "serve the story; be concise; "
    "6) end by answering the main idea from the beginning; "
    "7) write like someone telling a friend something interesting, not like "
    "reading an article: short spoken sentences with rhythm; rhetorical "
    "questions, simple comparisons and small surprises are welcome; a touch of "
    "personality, no slang, no forced humor; "
    "8) no generic intros ('Hey guys, today we will talk about...', "
    "'Did you know that' and equivalents); "
    "9) MANDATORY GROUNDING: every factual claim (dates, names, numbers, "
    "definitions, events, etymologies) must come from the PROVIDED SOURCES; "
    "it is FORBIDDEN to state any fact absent from the sources; if something "
    "is uncertain or not in the sources, state the uncertainty honestly or "
    "omit it — never fill gaps with invention; "
    "10) no fake sources or nonexistent studies; never invent facts, "
    "dates, names or quotes to sound interesting; "
    "11) no institutional documentary tone and no artificial conclusions; "
    "close with the answer or an observation that brings the topic closer "
    "to the viewer. "
    "12) explain complex concepts in simple words: whenever you mention "
    "something technical, explain it on the spot with an analogy or a direct "
    "definition; never use unexplained jargon. "
    "13) ALWAYS end like this: after answering the main idea, ask ONE open "
    "question related to the topic but NOT answered in the video (comment "
    "hook — e.g.: 'but would he have won if he had been better prepared "
    "for the cold?'), followed by a short like call-to-action ('leave a "
    "like and see you in the next video'). "
    "OUTPUT FORMAT (mandatory): answer ONLY with the narration text. "
    "FORBIDDEN: titles, 'Scene 1', 'Narrator:', bracketed stage directions, "
    "markdown, lists, dialogue quotes, emojis, preambles like 'Here is' "
    "or any explanation about the script. If you need to reason, do it "
    "only in internal reasoning, never in the final text. "
    "Editorial principle: simplify to make accessible, never falsify to "
    "go viral."
)

TITLE_SYSTEM_PROMPT_EN = (
    "You create a video title from an already finished educational script, "
    "in American English. Answer ONLY with valid JSON, no markdown "
    "or explanations: {\"title\": \"...\"}. Mandatory rules: "
    "1) the title is ALWAYS a question ending with '?'; "
    "2) it represents the main curiosity the video answers (NEVER copy "
    "the first sentence of the script); "
    "3) short: at most 55 characters; "
    "4) sounds natural when spoken aloud; "
    "5) sparks curiosity without clickbait: no exaggeration, fake mystery "
    "or promises the video does not keep; "
    "6) no quotes, markdown, emojis, hashtags or explanations."
)


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


CREDENTIALS = {
    "nvidia": NvidiaCredentials,
    "openrouter": OpenRouterCredentials,
    "gemini": GeminiCredentials,
    "groq": GroqCredentials,
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


def openrouter_settings() -> tuple[str, str]:
    """Retorna (model, base_url) do fallback (env > padrões)."""
    return llm_settings("openrouter")


def _http_error_message(status: int, body: str, model: str,
                        provider: str = "NVIDIA",
                        key_hint: str = "NVIDIA_API_KEY",
                        models_url: str | None = None) -> str:
    snippet = body.strip()[:300]
    if provider.lower() == "groq" and 400 <= status < 500:
        api_message = body.strip()[:1200] or "corpo vazio"
        return (f"etapa Groq: API respondeu HTTP {status}. "
                f"Mensagem da API: {api_message}")
    if status in (401, 403):
        return (
            f"etapa {provider}: autenticação rejeitada (HTTP 401/403). "
            f"Motivo provável: {key_hint} inválida ou expirada. "
            "Gere outra chave e tente novamente."
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
               pid: str, json_mode: bool = False) -> dict:
    """Uma tentativa HTTP. Erro transitório sai marcado (retryable=True)."""
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
               "Authorization": "Bearer " + key}
    if pid == "groq":
        # Groq/Cloudflare bloqueia o User-Agent Python-urllib padrão (HTTP 403
        # Cloudflare 1010). Identifique a aplicação sem simular navegador.
        headers["User-Agent"] = f"curio/{__version__} (LLM API client)"
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=payload,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — melhor mensagem parcial que nenhuma
            detail = ""
        if key:
            detail = detail.replace(key, "[REDACTED]")
        err = NvidiaError(_http_error_message(exc.code, detail, model,
                                              display, key_hint,
                                              spec["models_url"]))
        # 401/403/404 são definitivos (repetir não adianta); o resto repete.
        err.retryable = exc.code == 429 or 500 <= exc.code < 600
        err.http_attempts = 1
        raise err from exc
    except (socket.timeout, TimeoutError) as exc:
        prazo = f"após {timeout}s" if timeout is not None else "sem timeout configurado"
        err = NvidiaError(f"etapa {display}: timeout {prazo} com o modelo {model}.")
        err.retryable = True
        err.http_attempts = 1
        # Timeout = provedor lento: não repetir aqui dentro (evita 6×15s
        # no mesmo provedor); o rodízio troca imediatamente de provedor.
        # O fallback resiliente final controla seus próprios 5 retries.
        err.fast_fail = timeout is not None
        raise err from exc
    except urllib.error.URLError as exc:
        err = NvidiaError(
            f"etapa {display}: falha de conexão com a API. "
            f"Motivo provável: {exc.reason}. Verifique rede e base_url."
        )
        err.retryable = True
        err.http_attempts = 1
        raise err from exc
    except OSError as exc:
        # Alguns resets/desconexões HTTP chegam sem serem encapsulados em
        # URLError (por exemplo RemoteDisconnected); também são transitórios.
        err = NvidiaError(
            f"etapa {display}: conexão interrompida pela API. "
            f"Motivo provável: {exc}. Verifique rede e base_url."
        )
        err.retryable = True
        err.http_attempts = 1
        raise err from exc


def _post_with_retries(messages: list[dict], key: str, model: str,
                       base_url: str, timeout: int, max_tokens: int,
                       temperature: float, pid: str, json_mode: bool = False) -> dict:
    """Até N requests HTTP dentro de uma rodada de provider.

    N = `max_attempts()` (padrão 6). Este contador é interno à rodada; `_chat`
    conta rodadas globais separadamente. Erro definitivo, timeout fast-fail ou
    esgotamento propagam `http_attempts` para o levantamento final.
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
            if not getattr(exc, "retryable", False) or i == attempts:
                if i == attempts and getattr(exc, "retryable", False):
                    last = NvidiaError(
                        f"{exc} (após {attempts} tentativas)")
                    last.retryable = True
                    last.retry_exhausted = True
                    last.http_attempts = i
                raise last
            delay = RETRY_BASE_DELAY * (2 ** (i - 1))
            print(f"[{display}] tentativa {i}/{attempts} falhou "
                  f"(transitório): {exc} — nova tentativa em {delay:.0f}s…",
                  flush=True)
            time.sleep(delay)
    raise last  # inalcançável (loop sempre retorna ou levanta)


# Ordem preferida para respostas JSON: modelos rápidos e disciplinados
# (Gemini Flash via OpenRouter) antes do Nemotron 550B — que é lento e
# cospe raciocínio junto, quebrando o parse.
JSON_FIRST_ORDER = ("openrouter", "gemini", "groq", "nvidia")

# Teto por chamada HTTP LLM (s).
#
# Antes era 15 e RÍGIDO: nem .env nem config passavam disso, o que
# significava que um modelo grande e lento no NIM não tinha como ser
# usado — o teto matava a chamada e o rodízio caía no próximo provedor
# sem que ninguém pudesse aumentar o orçamento. O padrão continua 15 e o
# comportamento de hoje é idêntico; o que muda é que o teto agora é
# CONFIGURÁVEL, porque a escolha de valor é de quem opera, e não há
# evidência aqui para escolher por ele.
#
# `[nvidia] timeout_max` no config.toml, ou NVIDIA_TIMEOUT_MAX no .env.
LLM_CALL_TIMEOUT_MAX = 15

# Timeout por PROVEDOR, quando a resposta deste é mais lenta que a dos
# outros. Mesma regra: vazio = o teto global, sem diferença nenhuma. Um
# modelo de 550B parâmetros que precisa de 40 s não vira o problema dos
# provedores rápidos, e um único número para todos obriga a escolher entre
# "um teto alto para todos" e "um teto baixo para todos".
LLM_PROVIDER_TIMEOUT: dict[str, int] = {}

# O QUE ESTE TIMEOUT É, E O QUE ELE NÃO É
#
# Investigation before changing it. A execução de São Jerônimo mostrou
# "[NVIDIA] tentativa 1/6 falhou (timeout): etapa NVIDIA: timeout após 15s
# com o modelo nvidia/nemotron-3-ultra-550b-a55b", seguido de um
# fallback que funcionou. A pergunta era: o modelo é lento demais, ou o
# prazo é curto demais?
#
# O que existe hoje é UM número, e ele é um timeout de SOCKET:
# `urlopen(timeout=...)` vale para o handshake e para cada recv. Isso
# significa que um modelo que leva 40 s mas transmite algo de tempos em
# tempos NÃO é cortado — o que mata é silêncio no socket. O que não
# existe é a separação pedida em três nomes:
#
#   connect timeout  — quanto tempo esperar pelo handshake TLS/API.
#   read timeout     — quanto tempo aceitar silêncio entre pacotes.
#   generation budget — quanto tempo a GERAÇÃO inteira pode levar.
#
# Só o segundo é observável hoje, porque os três viram o mesmo parâmetro.
# Separá-los exigiria trocar a camada HTTP (http.client com timeout
# distinto no socket após o connect, ou uma biblioteca), e essa é uma
# reengenharia de provider — fora do escopo desta tarefa, e sem medição
# que justificasse o risco.
#
# Nenhum valor novo foi escolhido aqui. Não há medição de quanto o
# nemotron-3-ultra leva de verdade nesta máquina, e inventar 90 s seria
# chutar. O que ficou pronto é a MECÂNICA: o teto é configurável e
# pode ser dado por provedor. Quem medir, configura; quem não, o
# comportamento é o de sempre.


def call_timeout_max(configured: int | None = None) -> int:
    """O teto de chamada, na ordem: config, env, padrão.

    Existe para que "aumentar o tempo do modelo lento" seja uma linha de
    configuração em vez de uma edição de código. Nenhuma evidência
    justifica um valor maior que 15, então o padrão é 15.
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


def _rotation(pids: list[str], interleave_nvidia: bool = True):
    """Ordem do rodízio.

    Com interleave (padrão, texto livre): NVIDIA intercalada entre os
    fallbacks — N, OpenRouter, N, Gemini, N, Groq, N, OpenRouter…
    Sem interleave (JSON): ciclo simples na ordem recebida em `pids`.
    Infinito (o budget corta).
    """
    others = [p for p in pids if p != "nvidia"]
    if interleave_nvidia and "nvidia" in pids and others:
        i = 0
        while True:
            yield "nvidia" if i % 2 == 0 else others[(i // 2) % len(others)]
            i += 1
    else:
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
          timeout_max: int | None = None) -> tuple[dict, str]:
    """Chat em rodízio: NVIDIA falha 1x → já troca (intercalado c/ retries).

    Cada rodada vai ao próximo provider da rotação; erro definitivo (401/403/404)
    elimina o provedor do rodízio. Retorna (body, rótulo-do-provedor).
    O budget global conta rodadas; os retries HTTP internos são contabilizados
    à parte. Esgotado o budget, se só NVIDIA restar, usa fallback final sem
    timeout em vez de encerrar com ela ainda viável.

    `prefer` reordena o rodízio sem intercalar a NVIDIA (para JSON).
    O timeout por chamada é limitado ao teto configurado (15 s por
    padrão), e um provedor pode ter teto próprio via
    LLM_PROVIDER_TIMEOUT. Nenhum dos dois muda o comportamento padrão.
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
    for pid in PROVIDER_ORDER[2:]:
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
    nvidia_last_candidate = False
    for pid in _rotation(list(live), interleave_nvidia=not prefer):
        if not live:
            break
        if live == ["nvidia"]:
            return _nvidia_resilient_fallback(
                messages, model, base_url, max_tokens, temperature, json_mode,
                metrics, budget, made, rounds, attempts, last_err, skipped)
        if made >= budget:
            break
        if pid not in live:
            continue  # eliminado do rodízio por erro definitivo
        made += 1
        rounds[pid] = rounds.get(pid, 0) + 1
        om, ob = resolved[pid]
        dft_model, dft_base = llm_settings(pid)
        use_model, use_base = om or dft_model, ob or dft_base
        # O teto deste provedor pode ser maior que o global. A razão de
        # existir é o caso observado: um modelo grande no NIM precisa de
        # mais que 15 s, e aumentar o global obriga a aumentar para
        # todos — inclusive para os provedores rápidos, que passam a
        # esperar mais para falhar. Vazio = usa o global, sem diferença.
        teto_pid = timeout
        if pid in LLM_PROVIDER_TIMEOUT:
            teto_pid = max(timeout, int(LLM_PROVIDER_TIMEOUT[pid]))
        try:
            key = CREDENTIALS[pid].from_env().active_key
            body = _post_with_retries(messages, key, use_model, use_base,
                                      teto_pid, max_tokens, temperature, pid,
                                      json_mode)
        except NvidiaError as exc:
            attempts[pid] = (attempts.get(pid, 0) +
                             max(1, int(getattr(exc, "http_attempts", 1))))
            last_err[pid] = str(exc)
            if not getattr(exc, "retryable", False):
                live.remove(pid)  # definitivo: fora do rodízio
                print(f"[{PROVIDER_SPECS[pid]['display']}] erro definitivo "
                      f"— fora do rodízio: {exc}", flush=True)
            elif getattr(exc, "retry_exhausted", False):
                # O retry interno já consumiu o orçamento HTTP desse provider
                # nesta execução; não reinicia outro bloco 1/6 depois.
                live.remove(pid)
                if pid == "nvidia":
                    nvidia_last_candidate = True
                print(f"[{PROVIDER_SPECS[pid]['display']}] esgotou "
                      f"{getattr(exc, 'http_attempts', 1)} tentativa(s) HTTP "
                      f"nesta rodada.", flush=True)
            elif getattr(exc, "fast_fail", False):
                print(f"[{PROVIDER_SPECS[pid]['display']}] tentativa "
                      f"{made}/{budget} falhou (timeout): {exc} — "
                      f"trocando de provedor já…", flush=True)
                if pid != "nvidia":
                    # Timeout rápido põe os fallbacks no banco nesta execução;
                    # a NVIDIA fica elegível para o modo final sem timeout.
                    live.remove(pid)
            elif made < budget and live:
                delay = min(30.0, RETRY_BASE_DELAY * (2 ** (made - 1)))
                print(f"[{PROVIDER_SPECS[pid]['display']}] tentativa "
                      f"{made}/{budget} falhou (transitório): {exc} — "
                      f"rodízio em {delay:.0f}s…", flush=True)
                time.sleep(delay)
            if live == ["nvidia"]:
                return _nvidia_resilient_fallback(
                    messages, model, base_url, max_tokens, temperature,
                    json_mode, metrics, budget, made, rounds, attempts,
                    last_err, skipped)
            if not live and nvidia_last_candidate:
                return _nvidia_resilient_fallback(
                    messages, model, base_url, max_tokens, temperature,
                    json_mode, metrics, budget, made, rounds, attempts,
                    last_err, skipped)
            continue
        if metrics is not None:
            metrics.nvidia(f"{pid}:{use_model}", (body or {}).get("usage"))
        return body, f"{pid}:{use_model}"
    if live == ["nvidia"] or (not live and nvidia_last_candidate):
        return _nvidia_resilient_fallback(
            messages, model, base_url, max_tokens, temperature, json_mode,
            metrics, budget, made, rounds, attempts, last_err, skipped)
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
        parts.append(f"NVIDIA fallback resiliente: {final_attempts}/5 tentativa(s) "
                     f"sem timeout ({final_outcome or 'interrompido'}); "
                     f"último erro: {last_err.get('nvidia', '?')}")
    parts.extend(skipped)
    if remaining:
        parts.append("Ainda no rodízio sem sucesso: "
                     + ", ".join(PROVIDER_SPECS[p]['display'] for p in remaining))
    parts.append("Defina/renove as chaves no .env "
                 "(NVIDIA_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY, "
                 "GROQ_API_KEY) e confira modelos e rede.")
    return " | ".join(parts)


def _nvidia_resilient_fallback(messages: list[dict], model: str,
                               base_url: str, max_tokens: int,
                               temperature: float, json_mode: bool,
                               metrics, budget: int, made: int,
                               rounds: dict, attempts: dict, last_err: dict,
                               skipped: list[str]) -> tuple[dict, str]:
    """Último caminho: aguarda sem timeout e tenta no máximo cinco vezes."""
    display = PROVIDER_SPECS["nvidia"]["display"]
    print(f"[{display}] último provider viável — fallback resiliente", flush=True)
    key = CREDENTIALS["nvidia"].from_env().active_key
    for i in range(1, 6):
        print(f"[{display}] tentativa {i}/5 — aguardando sem timeout...",
              flush=True)
        try:
            body = _post_once(messages, key, model, base_url, None,
                              max_tokens, temperature, "nvidia", json_mode)
        except NvidiaError as exc:
            last_err["nvidia"] = str(exc)
            if not getattr(exc, "retryable", False):
                print(f"[{display}] erro definitivo no fallback resiliente — "
                      f"encerrando: {exc}", flush=True)
                raise NvidiaError(_survey(
                    budget, made, attempts, last_err, skipped, [], rounds,
                    final_attempts=i, final_outcome="erro definitivo")) from exc
            if i == 5:
                print(f"[{display}] 5 tentativas transitórias falharam; encerrando.",
                      flush=True)
                raise NvidiaError(_survey(
                    budget, made, attempts, last_err, skipped, [], rounds,
                    final_attempts=5, final_outcome="5 falhas transitórias")) from exc
            delay = min(30.0, RETRY_BASE_DELAY * (2 ** (i - 1)))
            print(f"[{display}] falha transitória ({i}/5): {exc} — "
                  f"nova tentativa em {delay:.0f}s…", flush=True)
            time.sleep(delay)
            continue
        if metrics is not None:
            metrics.nvidia(f"nvidia:{model}", (body or {}).get("usage"))
        return body, f"nvidia:{model}"
    raise NvidiaError(_survey(budget, made, attempts, last_err, skipped, [], rounds,
                              final_attempts=5,
                              final_outcome="5 falhas transitórias"))


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
    Usa response_format: json_object e tenta os provedores rápidos
    (OpenRouter/Gemini/Groq) antes da NVIDIA.
    """
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}]
    max_tokens, body, label = 2000, None, ""
    diagnostics = []
    for retry in range(2):  # uma escalada, preservada como limite atual
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
            "no fixed duration: cover the subject with beginning, middle and end, "
            f"no padding and no cutting (technical ceiling of {ceiling} characters)"
        ) if english else (
            "sem duração fixa: complete o assunto com começo, meio e fim, "
            f"sem enrolar nem cortar (teto técnico de {ceiling} caracteres)")
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
                            timeout_max=timeout_max)
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
