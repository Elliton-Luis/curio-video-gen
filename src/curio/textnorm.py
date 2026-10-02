"""A camada de comparação textual: normalizar, tokenizar, stopwords, léxico.

Este módulo existe porque a comparação de texto espalhada pelo projeto
divergiu. Havia sete cópias de "minúsculas sem acento" (`fold` em `scoring`,
`media_rules`, `entity`, `etymology`; `strip_acc` em `research`, `visual`;
`_norm` em `scenes`), três listas de stopword que já não concordavam entre
si e dois glossários idênticos de termos de busca. Divergência assim é um
bug silencioso: um termo para de casar num estágio e continua casando em
outro, e ninguém sabe qual é o certo.

A responsabilidade é deliberadamente estreita: **comparar texto**. Nada
aqui busca, decide mídia, monta prompt ou fala com rede. O que um
resultado significa (uma foto serve? uma fonte é do tema?) é decisão de
`scoring` e de `media_rules`, e não entra neste arquivo.

Vocabulário PT→EN e marcadores de tópico espacial moram aqui pelo mesmo
motivo: são dado linguístico compartilhado, e a alternativa era cada
estágio manter a sua cópia — que é como a divergência nasce.
"""

from __future__ import annotations

import re
import unicodedata

# --- normalização ------------------------------------------------------

def fold(text: str) -> str:
    """Minúsculas sem acento. A forma canônica de comparação."""
    norm = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def tokens(text: str, min_len: int = 3) -> list[str]:
    """Palavras úteis de um texto: sem acento, sem ruído de 1-2 letras.

    Separa por QUALQUER caractere não-alfanumérico, não só por espaço.
    Isso não é detalhe: títulos do Wikimedia chegam como "File:Saint
    Francis in Ecstasy.jpg" e, separando só por espaço, o "Saint" virava
    "file:saint" e nunca casava. Ou seja: todo título de acervo perdia a
    PRIMEIRA palavra — justamente nos provedores sem chave que guardam a
    arte de domínio público.
    """
    return [t for t in re.split(r"[^0-9a-z]+", fold(text)) if len(t) >= min_len]


def fold_phrase(text: str) -> str:
    """Frase normalizada: minúsculas, sem acento, só letras/números/espaço."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", fold(text))).strip()


# --- stopwords ---------------------------------------------------------

# Stopword da pesquisa (>=4 letras, para montar query) unida à stopword
# visual (>=3 letras, para escolher substantivo de cena). A união é segura
# nos dois sentidos: a pesquisa nunca casa 3 letras porque o regex exige
# quatro, e todas as 3 letras da lista visual eram stopword de verdade
# (nesta, embora, essas) — mantê-las separadas só produzia divergência.
STOP_PT = {
    "para", "como", "mais", "muito", "isso", "esse", "esta", "este", "aquele",
    "aquela", "foram", "eram", "sido", "entre", "sobre", "quando", "onde",
    "qual", "quais", "todo", "toda", "todos", "todas", "cada", "muita",
    "muitas", "muitos", "pouco", "pouca", "mesmo", "mesma", "outro", "outra",
    "outros", "outras", "depois", "antes", "durante", "sempre", "nunca",
    "também", "através", "porque", "porém", "entretanto", "portanto",
    "então", "assim", "aqui", "agora", "hoje", "ainda", "coisa",
    "algo", "alguém", "ninguém", "tudo", "nada", "seja", "sejam", "pode",
    "podem", "deve", "devem", "fazer", "fez", "fazem", "seria", "seriam",
    "tinha", "tinham", "esteve", "sendo", "teria", "teriam",
    "semper", "pois", "qualquer", "tanto", "quanto", "desde", "até",
    "meio", "grande", "pequeno", "novo", "velho", "primeiro", "último",
    "embora", "essa", "essas", "esses", "dessa", "desse", "nesta", "neste",
    "fato", "verdade", "mentira", "realmente", "anos",
    "você", "eles", "elas", "nós", "isto", "aquilo",
    "meu", "minha", "seu", "sua", "nosso", "nossa",
}

STOP_EN = {
    "what", "why", "how", "when", "where", "who", "which", "that",
    "this", "with", "from", "into", "about", "really", "does", "happen",
    "when", "your", "there", "their", "they", "them", "then", "than",
    "also", "just", "like", "more", "most", "very", "much", "many",
    "some", "such", "only", "over", "under", "between", "through",
}

# Stopword visual histórica: mantém apenas os termos usados por `visual.py`
# antes da centralização. A pesquisa usa STOP_PT (união), mas nomes de cena
# e substantivos de busca não devem perder palavras novas por efeito lateral.
_RESEARCH_ONLY_PT = {
    "anos", "aquilo", "elas", "eles", "fato", "isto", "mentira", "meu",
    "minha", "nossa", "nosso", "nós", "realmente", "seu", "sua",
    "verdade", "você",
}
VISUAL_STOP_PT = STOP_PT - _RESEARCH_ONLY_PT

# Stopwords de 3 letras. Ficam à parte porque não entram em STOP_PT: a
# pesquisa exige 4+ caracteres, e o extrator de termos do estágio de
# entidade aceita 3. Sem esta lista, "Por que o mar é salgado?" dava
# topics ['mar', 'por', 'que', ...].
STOP_SHORT = {
    "por", "que", "com", "sem", "uma", "uns", "das", "dos", "seu", "sua",
    "the", "and", "you", "how", "why", "what", "for", "not", "are", "was",
}


def stopwords(language: str = "pt-BR") -> set[str]:
    return STOP_EN if str(language or "").lower().startswith("en") else STOP_PT


# --- consultas ---------------------------------------------------------

_QUERY_STOP = {"the", "and", "with", "from", "into", "para", "uma"}


def query_terms(query: str) -> list[str]:
    """Palavras úteis de uma consulta de busca (>2 letras, sem stopword).

    Relevância lexical entre consulta e título: um termo casa quando
    aparece no título do candidato. É o que separa "quer dizer" (tema
    certo) de qualquer coisa que carregue a palavra.
    """
    return [t.lower() for t in str(query or "").replace(",", " ").split()
            if len(t) > 2 and t.lower() not in _QUERY_STOP]


# --- tópico espacial ---------------------------------------------------

# Sinais (já sem acento/minúsculas) de que o tema é espaço/astronomia.
# Vive aqui, e não em cada estágio, porque "buraco negro" precisa ser
# reconhecido pela busca, pelo gate de imagem e pelo classificador de
# cena ao mesmo tempo: três listas eventualmente divergem, e a divergência
# custa um vídeo de buraco negro ilustrado com tubo de ensaio.
SPACE_MARKERS = (
    "buraco negro", "buracos negros", "black hole", "corpo negro",
    "horizonte de eventos", "event horizon",
    "galaxia", "galaxias", "galaxy", "galaxies",
    "nebulosa", "nebula", "quasar", "supermassivo",
    "universo", "universe", "cosmos", "espaco-tempo",
    "gravidade", "gravitacional", "gravitacao", "gravity",
    "relatividade", "relativity", "singularidade", "singularity",
    "astronomia", "astronomico", "astronomica", "astronomy",
    "constelacao", "constellation", "orbita", "orbit",
    "hawking", "kelvin", "ano-luz",
)


def is_space_topic(text: str) -> bool:
    """O texto é sobre espaço/astronomia? Sem rede, sem LLM, sem acento."""
    hay = fold(text)
    return any(m in hay for m in SPACE_MARKERS)


# --- léxico PT→EN ------------------------------------------------------
# Os bancos de mídia respondem melhor em inglês, e as cenas locais não
# trazem consulta quando não há chave de LLM. O dicionário traduz os
# substantivos visuais que aparecem com frequência suficiente para valer o
# mapeamento — não é dicionário de português, é léxico de busca visual.

PT_LEXICON: dict[str, str] = {
    "roma": "rome", "romano": "roman", "romanos": "roman", "imperio": "empire",
    "imperador": "emperor", "legiao": "roman legion", "legioes": "roman legion",
    "soldado": "soldier", "exercito": "army", "guerra": "war",
    "batalha": "battle", "fronteira": "frontier", "barbaro": "barbarian",
    "barbaros": "barbarians", "guarda": "guard", "capacete": "helmet",
    "espada": "sword", "escudo": "shield", "moeda": "coin", "salario": "salary",
    "dinheiro": "money", "pagamento": "payment", "comercio": "trade",
    "mercado": "market", "sal": "salt", "pao": "bread", "vinho": "wine",
    "comida": "food", "igreja": "church", "templo": "temple", "castelo": "castle",
    "piramide": "pyramid", "estatua": "statue", "pintura": "painting",
    "retrato": "portrait", "mapa": "map", "livro": "book", "carta": "letter",
    "documento": "document", "fotografia": "photograph", "cerebro": "brain",
    "mente": "mind", "cabeca": "head", "mao": "hand", "corpo": "body",
    "doenca": "disease", "peste": "plague", "medico": "doctor", "hospital": "hospital",
    "cidade": "city", "rua": "street", "casa": "house", "aldeia": "village",
    "campo": "field", "colheita": "harvest", "mar": "sea", "navio": "ship",
    "rio": "river", "montanha": "mountain", "arvore": "tree", "flor": "flower",
    "floresta": "forest", "deserto": "desert", "ceu": "sky", "sol": "sun",
    "lua": "moon", "estrela": "star", "terra": "earth", "fogo": "fire",
    "agua": "water", "pedra": "stone", "ouro": "gold", "prata": "silver",
    "ferro": "iron", "cobre": "copper", "bronze": "bronze", "cavalo": "horse",
    "cao": "dog", "cachorro": "dog", "gato": "cat", "passaro": "bird",
    "peixe": "fish", "homem": "man", "mulher": "woman", "crianca": "child",
    "criancas": "children", "povo": "people", "multidao": "crowd", "rei": "king",
    "rainha": "queen", "campones": "peasant", "trabalho": "work",
    "trabalhador": "worker", "escola": "school", "teatro": "theater",
    "musica": "music", "danca": "dance", "festa": "festival", "religiao": "religion",
    "deus": "god", "mito": "myth", "lenda": "legend", "historia": "history",
    "antigo": "ancient", "ruina": "ruins", "ruinas": "ruins", "muralha": "wall",
    "ponte": "bridge", "estrada": "road", "trem": "train", "carro": "car",
    "aviao": "airplane", "fabrica": "factory", "maquina": "machine",
    "ciencia": "science", "laboratorio": "laboratory", "experimento": "experiment",
    "planeta": "planet", "planetas": "planets", "satelite": "satellite",
    "telescopio": "telescope", "observatorio": "observatory",
    "galaxia": "galaxy", "galaxias": "galaxies",
    "universo": "universe", "cosmos": "cosmos", "espaco": "space",
    "espacial": "space", "astronomia": "astronomy",
    "astronomico": "astronomy", "astronomica": "astronomy",
    "astrofisica": "astrophysics", "astrofisico": "astrophysics",
    "buraco": "black hole", "buracos": "black hole",
    "negro": "black hole", "negros": "black hole",
    "nebulosa": "nebula", "nebulosas": "nebulae",
    "quasar": "quasar", "quasares": "quasars",
    "singularidade": "singularity", "horizonte": "event horizon",
    "gravidade": "gravity", "gravitacional": "gravity",
    "gravitacao": "gravity", "relatividade": "relativity",
    "orbita": "orbit", "orbitas": "orbits", "eclipse": "eclipse",
    "constelacao": "constellation", "luz": "light",
    "sombra": "shadow", "massa": "mass", "massas": "masses",
    "denso": "dense", "densa": "dense", "radiacao": "radiation",
    "temperatura": "temperature", "kelvin": "kelvin",
    "fisica": "physics", "quantica": "quantum", "quantico": "quantum",
    "teoria": "theory", "estrelas": "stars",
    "estelar": "stellar", "estelares": "stellar",
    "livraria": "bookstore", "biblioteca": "library", "escrita": "writing",
    "palavra": "word", "lingua": "language", "numero": "number", "tempo": "time",
    "inverno": "winter", "verao": "summer", "chuva": "rain", "neve": "snow",
    "vulcao": "volcano", "terremoto": "earthquake",
    "porto": "harbor", "farol": "lighthouse", "ilha": "island", "praia": "beach",
    "jardim": "garden", "parque": "park", "loja": "shop",
    "padaria": "bakery", "cozinha": "kitchen", "mesa": "table", "cadeira": "chair",
    "janela": "window", "porta": "door", "chave": "key", "relogio": "clock",
    "espelho": "mirror", "vela": "candle", "faca": "knife", "panela": "pot",
    "prato": "plate", "copo": "glass", "garrafa": "bottle", "cesta": "basket",
    "roupa": "clothes", "sapato": "shoe", "chapeu": "hat", "coroa": "crown",
    "anel": "ring", "colar": "necklace", "joia": "jewel", "tesouro": "treasure",
    "tumba": "tomb", "mumia": "mummy", "fossil": "fossil", "dinossauro": "dinosaur",
    "esqueleto": "skeleton", "crânio": "skull", "cranio": "skull",
    "sangue": "blood", "coração": "heart", "coracao": "heart", "olho": "eye",
    "rosto": "face", "maos": "hands", "pes": "feet", "nacao": "nation",
    "bandeira": "flag", "governo": "government", "eleicao": "election",
    "protesto": "protest", "revolucao": "revolution", "independencia": "independence",
    "escravidao": "slavery", "colonia": "colony", "reino": "kingdom",
    "republica": "republic", "senado": "senate", "lei": "law", "justica": "justice",
    "prisao": "prison", "crime": "crime", "pirata": "pirate", "viking": "viking",
    "nordico": "norse", "egito": "egypt", "grecia": "greece", "grego": "greek",
    "troia": "troy", "atenas": "athens", "esparta": "sparta", "gladiador": "gladiator",
    "coliseu": "colosseum", "aqueduto": "aqueduct", "foro": "forum",
    "cesar": "caesar", "augusto": "augustus", "nero": "nero",
    "constantinopla": "constantinople", "bizancio": "byzantium",
    "idade": "age", "seculo": "century", "medieval": "medieval",
    "renascimento": "renaissance", "iluminismo": "enlightenment",
    "industrial": "industrial", "moderno": "modern", "contemporaneo": "contemporary",
    "provincia": "province", "imposto": "tax", "tributo": "tribute",
    "germanico": "germanic", "mosaico": "mosaic", "invasao": "invasion",
    "queda": "fall", "crise": "crisis", "corrupcao": "corruption",
    "sucessao": "succession", "inflacao": "inflation", "muralhas": "walls",
    "pretoriana": "praetorian guard", "reforma": "reform", "senador": "senator",
    "tribuno": "tribune", "consul": "consul", "ditador": "dictator",
    "escravo": "slave", "gladiadores": "gladiators", "circo": "circus",
    "anfiteatro": "amphitheater", "termas": "baths", "vila": "villa",
    "palacio": "palace",
}


def translate(word: str) -> str | None:
    """Verte PT→EN, tentando singular (plurais -s/-es) antes de desistir."""
    base = fold(word)
    hit = PT_LEXICON.get(base)
    if hit:
        return hit
    for cand in (base[:-1] if base.endswith("s") else "",
                 base[:-2] if base.endswith("es") else ""):
        if cand and cand in PT_LEXICON:
            return PT_LEXICON[cand]
    return None
