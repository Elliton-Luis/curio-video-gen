"""Geração de roteiro (PRD §6).

MVP: gerador local de custo zero com base curada + template honesto.
Nenhuma afirmação é inventada para viralizar (princípio editorial, §2).
LLM opcional e isolado: só ativa com CURIO_LLM_API_KEY configurada.
"""

from __future__ import annotations

import json
import re
import urllib.request

from ..config import CurioConfig

# ~13,5 caracteres/segundo ≈ ritmo de narração PT-BR confortável.
CHARS_PER_SECOND = 13.5

SYSTEM_PROMPT = (
    "Você escreve roteiros curtos de vídeo educativo em PT-BR. Regras: "
    "texto corrido para narração, sem markdown, sem 'Você sabia que', "
    "sem clickbait, sem inventar fatos; se algo for incerto, diga que é incerto. "
    "Estrutura: apresentação rápida, desenvolvimento, conclusão. "
    "Responda com no máximo {max_chars} caracteres."
)

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


def _template_script(idea: str, max_chars: int) -> str:
    topic = idea.strip().rstrip("?.!").strip()
    text = (
        f"{topic}. Parece uma pergunta simples, e é justamente por isso que ela é boa. "
        f"Para responder, é preciso separar o que se sabe do que só se repete por aí. "
        f"A história registra fragmentos: documentos, objetos, palavras que mudaram de sentido. "
        f"Cada fragmento conta uma parte, mas nenhum conta tudo sozinho. "
        f"Por isso, a resposta honesta mistura o que foi confirmado com o que segue em debate. "
        f"E talvez esse seja o ponto mais interessante: uma boa pergunta não termina quando o vídeo acaba. "
        f"Ela continua na sua cabeça, e isso já é aprender alguma coisa."
    )
    if len(text) > max_chars:
        text = text[: max_chars - 1].rsplit(" ", 1)[0] + "."
    return text


def _llm_script(idea: str, cfg: CurioConfig, max_chars: int) -> str | None:
    if not (cfg.llm_api_key and cfg.llm_base_url and cfg.llm_model):
        return None
    payload = json.dumps({
        "model": cfg.llm_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.format(max_chars=max_chars)},
            {"role": "user", "content": f"Escreva o roteiro para a ideia: {idea}"},
        ],
        "temperature": 0.7,
        "max_tokens": 400,
    }).encode()
    req = urllib.request.Request(
        cfg.llm_base_url.rstrip("/") + "/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg.llm_api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.load(resp)
        text = body["choices"][0]["message"]["content"].strip()
    except Exception:
        return None
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars] if len(text) > max_chars else text


def generate_script(idea: str, cfg: CurioConfig) -> tuple[str, str]:
    """Retorna (roteiro, fonte). Fonte: 'curated:...' | 'llm:...' | 'template'."""
    if not idea or not idea.strip():
        raise ValueError("ideia vazia — informe um texto, ex.: video-gen generate \"...\"")
    max_chars = int(cfg.duration_target * CHARS_PER_SECOND)

    curated = _match_curated(idea)
    if curated:
        return (curated[:max_chars], "curated")

    llm_text = _llm_script(idea, cfg, max_chars)
    if llm_text:
        return llm_text, f"llm:{cfg.llm_model}"

    return _template_script(idea, max_chars), "template"
