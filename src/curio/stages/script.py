"""Geração de roteiro (PRD §6).

Ordem: NVIDIA API (se houver chave) → base curada → template local.
Com chave configurada, a NVIDIA é autoritativa e falhas são explícitas
(NvidiaError) — nunca fallback silencioso. Sem chave, custo zero offline.
"""

from __future__ import annotations

import sys

from ..config import CurioConfig
from . import nvidia as nvidia_stage

# ~13,5 caracteres/segundo ≈ ritmo de narração PT-BR confortável.
CHARS_PER_SECOND = 13.5

# Teto de segurança do modo Automático (~5 min): evita conta runaway na
# API sem amputar conteúdo real. NÃO é meta — o roteiro termina quando o
# assunto termina.
AUTO_MAX_CHARS = 4000

# Base curada: cada entrada tem ~600 caracteres (≈45 s) e evita mitos comuns.
CURATED: dict[str, str] = {
    "salario": (
        "A palavra salário vem do latim salarium, ligado a sal, o sal. "
        "Na Roma antiga, o sal era essencial para conservar alimentos, e parte "
        "do pagamento dos soldados envolvia uma quantia para comprá-lo. "
        "Daí a ideia de que o salário teria sido pago em sal. Mas atenção: "
        "os soldados recebiam soldo em moeda; o salarium era um adicional, não o "
        "pagamento inteiro. A história do 'pagamento em sal' é uma simplificação. "
        "O que ficou foi a palavra: até hoje, salário carrega a memória de que "
        "trabalho e sustento andam juntos desde a Roma antiga."
    ),
    "viking-chifre": (
        "Os vikings usavam capacetes com chifres? Não há nenhuma evidência disso. "
        "Nenhum capacete com chifres jamais foi encontrado em sítio arqueológico viking. "
        "Os capacetes reais eram simples, de ferro, ajustados à cabeça — chifres "
        "seriam um estorbo em batalha. O mito nasceu no século dezenove, em fantasias "
        "de ópera e ilustrações românticas que vestiram os nórdicos como bárbaros teatrais. "
        "O cinema só repetiu a fantasia. A lição: nem tudo que parece antigo é histórico; "
        "às vezes é só um figurino que colou."
    ),
}

TOPIC_KEYS: list[tuple[str, str]] = [
    ("salár", "salario"),
    ("salari", "salario"),
    ("viking", "viking-chifre"),
    ("chifre", "viking-chifre"),
    ("nórdic", "viking-chifre"),
    ("nordic", "viking-chifre"),
]


def _match_curated(idea: str) -> str | None:
    lowered = idea.lower()
    for needle, key in TOPIC_KEYS:
        if needle in lowered:
            return CURATED[key]
    return None


# Gancho final padrão (pergunta aberta não respondida + CTA de like).
CLOSER_PT = (" Mas me conta: o que mais você quer saber sobre esse assunto? "
             "Deixe seu like e até o próximo vídeo.")
CLOSER_EN = (" But tell me: what else do you want to know about this? "
             "Leave a like and see you in the next video.")


def _template_script(idea: str, max_chars: int | None, language: str = "pt-BR") -> str:
    topic = idea.strip().rstrip("?.!").strip()
    if str(language or "").lower().startswith("en"):
        text = (
            f"{topic}. It sounds like a simple question, and that is exactly why it is good. "
            f"To answer it, we need to separate what is known from what is merely repeated. "
            f"History keeps fragments: documents, objects, words that changed meaning. "
            f"Each fragment tells a part, but none tells everything alone. "
            f"So the honest answer mixes what is confirmed with what is still debated. "
            f"And perhaps that is the most interesting point: a good question does not end when the video ends. "
            f"It stays in your head, and that is already learning something."
            f"{CLOSER_EN}"
        )
    else:
        text = (
            f"{topic}. Parece uma pergunta simples, e é justamente por isso que ela é boa. "
            f"Para responder, é preciso separar o que se sabe do que só se repete por aí. "
            f"A história registra fragmentos: documentos, objetos, palavras que mudaram de sentido. "
            f"Cada fragmento conta uma parte, mas nenhum conta tudo sozinho. "
            f"Por isso, a resposta honesta mistura o que foi confirmado com o que segue em debate. "
            f"E talvez esse seja o ponto mais interessante: uma boa pergunta não termina quando o vídeo acaba. "
            f"Ela continua na sua cabeça, e isso já é aprender alguma coisa."
            f"{CLOSER_PT}"
        )
    if max_chars is not None and len(text) > max_chars:
        # Corte com dignidade, mas preserva o gancho final sempre.
        closer = CLOSER_EN if str(language or "").lower().startswith("en") else CLOSER_PT
        body = text[: len(text) - len(closer)] if text.endswith(closer) else text
        cut = body[: max(0, max_chars - len(closer))]
        for sep in (". ", "! ", "? "):
            idx = cut.rfind(sep)
            if idx > len(cut) * 0.3:
                cut = cut[: idx + 1].strip()
                break
        else:
            cut = cut.rsplit(" ", 1)[0].rstrip(",;:") + "."
        text = f"{cut}{closer}"
    return text


def generate_script(idea: str, cfg: CurioConfig, metrics=None,
                    research: str | None = None) -> tuple[str, str]:
    """Retorna (roteiro, fonte). Fonte: 'nvidia:...' | 'openrouter:...' | 'gemini:...' | 'groq:...' | 'curated' | 'template'.

    Com duração escolhida, o tamanho é meta (corta com dignidade); no modo
    Automático (duration_target 0), sem corte — só o teto de segurança.
    """
    if not idea or not idea.strip():
        raise ValueError("ideia vazia — informe um texto, ex.: video-gen generate \"...\"")
    auto = cfg.duration_target <= 0
    max_chars = None if auto else int(cfg.duration_target * CHARS_PER_SECOND)

    if nvidia_stage.any_llm_available():
        text, _label = nvidia_stage.generate_script(
            idea, cfg.nvidia_model, cfg.nvidia_base_url,
            cfg.nvidia_timeout, max_chars, metrics,
            or_model=cfg.openrouter_model, or_base_url=cfg.openrouter_base_url,
            extra=cfg.llm_overrides(), language=cfg.language,
            research=research)
        return text, _label

    english = str(cfg.language or "").lower().startswith("en")
    if not english:
        curated = _match_curated(idea)
        if curated and not curated.rstrip().endswith("próximo vídeo."):
            curated = curated.rstrip() + CLOSER_PT
        if curated:
            if auto or max_chars is None or len(curated) <= (max_chars or 0):
                return curated, "curated"
            # Com meta de duração: corta o corpo, mas preserva o gancho final.
            body = curated[: len(curated) - len(CLOSER_PT)]
            cut = body[: max(0, max_chars - len(CLOSER_PT))]
            for sep in (". ", "! ", "? "):
                idx = cut.rfind(sep)
                if idx > len(cut) * 0.3:
                    cut = cut[: idx + 1].strip()
                    break
            else:
                cut = cut.rsplit(" ", 1)[0].rstrip(",;:") + "."
            return f"{cut}{CLOSER_PT}", "curated"

    return _template_script(idea, max_chars, cfg.language), "template"


TITLE_MAX_CHARS = 90  # limite duro de validação (prompt pede ≤55)


def _first_sentence(text: str) -> str:
    import re as _re
    parts = _re.split(r"(?<=[.!?…])\s+", text.strip())
    return next((p for p in parts if p), text.strip()[:TITLE_MAX_CHARS])


def _validate_title(title: str, script_text: str) -> str:
    """Título precisa ser pergunta curta, própria (não cópia da 1ª frase)."""
    from . import scenes as scenes_stage
    t = (title or "").strip().replace("\n", " ")
    t = t.strip("`'\" ")
    if not (12 <= len(t) <= TITLE_MAX_CHARS):
        raise ValueError(f"título fora do tamanho (12–90): {t!r}")
    if not t.endswith("?"):
        raise ValueError(f"título sem '?': {t!r}")
    if any(c in t for c in "*#[]{}"):
        raise ValueError(f"título com formatação: {t!r}")
    if scenes_stage._norm(t) == scenes_stage._norm(_first_sentence(script_text)):
        raise ValueError("título cópia da primeira frase do roteiro")
    return t


def _fallback_title(script_text: str, idea: str) -> str:
    """Sem LLM: a ideia se já for pergunta; senão a ideia verbatim.

    Melhor esforço documentado (source 'fallback'): nunca inventa pergunta
    nova nem reescreve — só reaproveita o que o usuário já escreveu.
    """
    guess = (idea or "").strip()
    if guess.endswith("?") and 12 <= len(guess) <= TITLE_MAX_CHARS:
        return guess
    return guess[:TITLE_MAX_CHARS] or _first_sentence(script_text)[:TITLE_MAX_CHARS]


def generate_title(script_text: str, idea: str, cfg: CurioConfig,
                   metrics=None) -> tuple[str, str]:
    """Gera o título-pergunta do vídeo a partir do roteiro (não da ideia).

    Retorna (título, fonte): 'nvidia:...' | 'openrouter:...' | 'gemini:...' |
    'groq:...' | 'fallback'. O título nunca entra na narração nem nas
    legendas — só metadados e abertura do vídeo.
    """
    if nvidia_stage.any_llm_available():
        try:
            english = str(cfg.language or "").lower().startswith("en")
            system_prompt = (nvidia_stage.TITLE_SYSTEM_PROMPT_EN if english
                             else nvidia_stage.TITLE_SYSTEM_PROMPT)
            user_prompt = (f"Create the title for this script:\n\n{script_text}"
                           if english else
                           f"Crie o título para este roteiro:\n\n{script_text}")
            data, label = nvidia_stage.complete_json(
                system_prompt, user_prompt,
                cfg.nvidia_model, cfg.nvidia_base_url, cfg.nvidia_timeout,
                metrics, or_model=cfg.openrouter_model,
                or_base_url=cfg.openrouter_base_url,
                extra=cfg.llm_overrides())
            return _validate_title(str(data.get("title", "")), script_text), label
        except (nvidia_stage.NvidiaError, ValueError) as exc:
            print(f"AVISO: título IA inválido ({exc}) — usando fallback.",
                  file=sys.stderr)
    return _fallback_title(script_text, idea), "fallback"
