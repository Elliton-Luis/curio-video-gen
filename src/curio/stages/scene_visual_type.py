"""Deterministic scene visual-type classification shared across boundaries."""

from __future__ import annotations

from .. import textnorm


# Sinais de que a cena explica um PROCESSO, não uma coisa. Uma foto de
# laboratório não mostra "o calor altera o corante" — mostra um frasco.
# Reconhecer isso é o que evita a foto genérica no lugar do diagrama.
_MECHANISM_HINTS_PT = (
    "como funciona", "como faz", "por que funciona", "o que acontece quando",
    "acontece quando", "passo a passo", "etapas", "processo",
    "se transforma", "reage", "reação", "reacao", "muda de cor", "altera",
    "mistura", "combina com", "por dentro", "por baixo dos panos",
    "mecanismo", "funciona porque", "o truque",
)
_MECHANISM_HINTS_EN = (
    "how does", "how it works", "what happens", "step by step", "process",
    "reaction", "reacts", "transforms", "converts", "breaks down",
    "mechanism", "the trick", "inside",
)
# Sinais de que a cena é histórica/religiosa/mítica: pede arte, não foto.
_HISTORICAL_HINTS = (
    "século", "seculo", "d. de", "antes de cristo", "depois de cristo",
    "império", "imperio", "rei ", "rainha ", "papa", "santo", "santa",
    "igreja", "deus", "deusa", "mito", "lenda", "profeta", "igrejo",
    "antiguidade", "idade média", "idade media", "renascimento",
    "séc.", "sec.", "century", "king ", "queen ", "saint", "church",
    "temple", "myth", "legend", "prophet", "empire", "ancient", "medieval",
    # Ordens, cargos e edifícios religiosos: é o que separa "sobre um
    # santo" de "sobre um gato". Nomes próprios isolados não são sinal
    # (todo mundo tem nome), então a lista é de institutions e cargos.
    "ordem dos", "franciscan", "dominicano", "jesuít", "jesuit", "monge",
    "monastery", "mosteiro", "convento", "abade", "bispo", "cardeal",
    "catedral", "basílica", "basilica", "apóstolo", "apostolo", "evangelho",
    "bíblia", "biblia", "oratório", "santuário", "santuario", "capela",
    "nascido em", "nasceu em", "viveu em", "morreu em",
    "batalha", "battle", "cerco", "siege", "revolução", "revolution",
    "guerra", "war", "conquista", "conquest", "frota", "fleet",
    "janízaro", "janizaro", "janissary", "janissaries", "exército",
    "exercito", "army", "cavalaria", "cavalry",
)
# Sinais de que a cena é melhor dita com palavras e não com imagem.
_TYPOGRAPHIC_HINTS = (
    "quer dizer", "significa", "significado", "vem do latim", "vem do",
    "etimologia", "etimológica", "etimologicamente", "chama-se", "chamava",
    "o termo", "a palavra", "definicao", "definição", "etimolog",
    "significa literalmente", "means", "derived from", "etymology",
    "word comes from", "literally",
)




def classify_visual_type(narration: str) -> str:
    """Tipo de visual que serve à cena, sem depender da IA.

    Ordem importa: mecanismo e histórico são específicos e vencem; o
    textual é o mais forte sinal de "isto é uma etimologia"; o resto é
    literal. É a rede de segurança para quando não há chave de LLM — sem
    ela, tudo vira "literal" e o vídeo inteiro vira banco de imagem.
    """
    text = (narration or "").lower()
    if not text.strip():
        return "literal"
    if any(h in text for h in _TYPOGRAPHIC_HINTS):
        return "typographic"
    if textnorm.is_space_topic(text):
        return "literal"
    if any(h in text for h in _MECHANISM_HINTS_PT + _MECHANISM_HINTS_EN):
        return "mechanism"
    if any(h in text for h in _HISTORICAL_HINTS):
        return "historical_art"
    return "literal"

