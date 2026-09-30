"""Identidade tipográfica por gênero: a fonte decide por FUNÇÃO, não global.

Uma fonte só para o vídeo inteiro não produz identidade editorial; produz
uma diferença de glifo. O que faz um vídeo de História de Pessoas parecer
livro em vez de post é a distinção entre a **voz que narra** e a **voz que
cita**: a narração em uma serifada de leitura, a citação em itálico, o
metadado em algo discreto. Por isso a pergunta que este módulo responde é
"que papel tipográfico este texto tem?", e não "qual é a fonte do vídeo?".

O papel é declarado pela CENA (`Chapter.text_role`), nunca a fonte. A cena
diz `quote`; o perfil decide que `quote` em `people` é itálico serifado. Um
autor que escreva `font = "Minion Pro Italic"` na cena quebrou a abstração
na hora em que trocar de gênero, e é exatamente a troca que precisa ser
barata.

## Fontes: nunca assumidas, nunca baixadas

Minion Pro é proprietária e não está em máquina nenhuma por padrão. Este
módulo **não baixa fonte alguma** — nem a proprietária, nem uma OFL de
substituto. Ele pergunta ao fontconfig o que já está instalado e para aí.
A política do projeto já é a mesma para legendas, e a razão é a mesma: uma
fonte que chega durante o render vira uma dependência de rede no meio da
montagem, e uma dependência de rede que falha depois de 40 minutos de
montagem é a pior delas.

O detalhe que faz a diferença aqui é o **itálico**. O fontconfig não falha
quando uma família não tem itálico: ele devolve o regular e continua
funcionando. `fc-match "EB Garamond:italic"` responde `EBGaramond[wght].ttf
|Regular` nesta máquina. Sem checar o estilo resolvido, "Minion Pro Italic"
 cairia em EB Garamond regular e a citação sairia idêntica à narração — a
distinção editorial inteira, que é o ponto do recurso, desapareceria sem
nenhum erro, nenhuma exceção, nenhuma mensagem. Por isso `resolve()`
confere que o estilo devolvido é de fato itálico/oblíquo antes de aceitar,
e cai para a próxima candidata se não for.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field, replace

# --- papéis -------------------------------------------------------------
# O vocabulário é o do papel editorial, não o do peso da fonte. Um papel
# descreve a função do texto na tela; o perfil traduz função em desenho.

ROLE_TITLE = "title"          # o título do vídeo
ROLE_PERSON = "person"        # o nome da pessoa de quem se fala
ROLE_SUBTITLE = "subtitle"    # linha de apoio abaixo do título
ROLE_KICKER = "kicker"        # etiqueta curta acima do título ("ETIMOLOGIA")
ROLE_CAPTION = "caption"      # a legenda da narração
ROLE_QUOTE = "quote"          # frase atribuída, voz de terceiro
ROLE_DOCUMENT = "document"    # texto de documento, inscrição, transcrição
ROLE_LATIN = "latin"          # frase em latim
ROLE_TERM = "term"            # o termo em foco (a palavra, o nome)
ROLE_DATE = "date"            # datas ecronologia
ROLE_LOCATION = "location"    # lugares
ROLE_EMPHASIS = "emphasis"    # palavra destacada dentro de um texto
ROLE_CONCEPT = "concept"      # elemento tipográfico conceitual (cadeia)

ROLES = (ROLE_TITLE, ROLE_PERSON, ROLE_SUBTITLE, ROLE_KICKER, ROLE_CAPTION,
         ROLE_QUOTE, ROLE_DOCUMENT, ROLE_LATIN, ROLE_TERM, ROLE_DATE,
         ROLE_LOCATION, ROLE_EMPHASIS, ROLE_CONCEPT)

# --- intenções ---------------------------------------------------------
# O perfil não mapeia papel → família, e sim papel → INTENÇÃO. É o que
# permite que dois gêneros usem as mesmas intenções com famílias
# diferentes, e que uma citação seja itálico em `people` e semibold em
# `mystery` sem que nada precise saber disso.

INTENT_SERIF = "serif"
INTENT_SERIF_ITALIC = "serif_italic"
INTENT_SANS = "sans"
INTENT_SANS_ITALIC = "sans_italic"
INTENT_MONO = "mono"
INTENT_CONDENSED = "condensed"

INTENTS = (INTENT_SERIF, INTENT_SERIF_ITALIC, INTENT_SANS,
           INTENT_SANS_ITALIC, INTENT_MONO, INTENT_CONDENSED)

# Papéis que a política tipográfica do projeto trata como texto corrido de
# tela. Recebem a fonte de exibição (pesada, sem serifa) por decisão de
# legibilidade, e o perfil tipográfico não pode sobrepor isso: uma legenda
# em itálico serifado é pior que uma legenda feia.
LEGIBILITY_ROLES = frozenset({ROLE_CAPTION})

# --- cadeias genéricas -------------------------------------------------
# Só entram aqui fontes que existem em distribuição Linux de broadly
# (Noto/Liberation/DejaVu). A ordem é por proximidade de semelhança ao
# pretendido, não por preferência estética.

GENERIC_FALLBACK: dict[str, tuple[str, ...]] = {
    # Utopia abre a lista de propósito, e não por gosto de disponibilidade:
    # ela foi desenhada por Robert Slimbach, o MESMO desenhista da Minion
    # Pro. Onde a Minion não está, Utopia é o substituto mais próximo que
    # existe em qualquer distribuição Linux, e é justamente por isso que
    # fica antes das outras.
    INTENT_SERIF: ("Utopia", "EB Garamond", "Noto Serif",
                   "Liberation Serif", "DejaVu Serif"),
    # Sem Utopia aqui: onde a família não tem itálico, aceitar o regular
    # silenciosamente é o defeito que este módulo existe para evitar.
    # Noto e Liberation têm itálico de verdade.
    INTENT_SERIF_ITALIC: ("Utopia", "Noto Serif", "Liberation Serif",
                          "DejaVu Serif"),
    INTENT_SANS: ("Noto Sans", "Liberation Sans", "DejaVu Sans"),
    INTENT_SANS_ITALIC: ("Noto Sans", "Liberation Sans", "DejaVu Sans"),
    INTENT_MONO: ("Noto Sans Mono", "Liberation Mono", "DejaVu Sans Mono"),
    INTENT_CONDENSED: ("Noto Sans Condensed", "Liberation Sans Narrow",
                       "DejaVu Sans Condensed", "Noto Sans"),
}

# Nenhuma lista de "famílias pouco confiáveis" é necessária: quando o
# nome pedido não volta na família resolvida, `fc_resolve` recusa, e o
# fontconfig substituiu. Era tentador filtrar "Liberation Sans Narrow"
# aqui, mas o filtro seria uma segunda opinion, mais fraca, do que o
# teste real.

# Estilos que contam como inclinado de verdade. `Oblique` é o nome que o
# DejaVu dá ao itálico; é um rosto real, não uma simulação.
_SLANT_STYLES = ("italic", "oblique", "slanted")

# "Minion Pro Italic" e "Liberation Serif Italic" são como as pessoas
# escrevem o nome de um itálico, e é assim que a Adobe e o Office os
# nomeiam. O fontconfig, porém, quer `família:italic`, e tratar o nome
# inteiro como família devolve silêncio: a fonte existe, a resolução não
# acha, e o resultado é a fonte do sistema para o papel mais importante
# do recurso. Então o token de estilo é separado antes de perguntar.
_STYLE_SUFFIXES = ("italic", "oblique", "slanted")


def split_style(name: str) -> tuple[str, bool]:
    """("Minion Pro Italic", True) · ("EB Garamond", False)"""
    partes = str(name or "").strip().split()
    if partes and partes[-1].lower() in _STYLE_SUFFIXES and len(partes) > 1:
        return " ".join(partes[:-1]), True
    return str(name or "").strip(), False


@dataclass(frozen=True)
class TypographyProfile:
    """A direção tipográfica de um gênero.

    `families` guarda a preferência por INTENÇÃO, e `roles` diz qual
    intenção serve cada papel. Separar as duas coisas é o que dá
    configurabilidade sem duplicação: trocar `primary` muda todos os
    papéis serifados de uma vez, que é o que se espera de "trocar a
    fonte do gênero".
    """

    key: str
    label: str
    families: dict[str, str] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    # Multiplicadores de corpo por papel. Não é vaidade: a mesma frase em
    # itálico serifado ocupa menos linha que em sans pesada, e um cartão
    # de citação com o corpo do título estoura o quadro.
    scale: dict[str, float] = field(default_factory=dict)
    direction: str = ""
    # A família veio do config? Então é escolha de quem usa, e a escolha
    # vale mesmo sem itálico: o par automático existe para consertar a
    # NOSSA preferência, não para desobedecer à DELE.
    pinned: bool = False

    def intent_for(self, role: str) -> str:
        return self.roles.get(role, INTENT_SANS)

    def family_for(self, intent: str) -> str:
        return self.families.get(intent, "")

    def size_for(self, role: str, base: int) -> int:
        return max(8, int(round(base * self.scale.get(role, 1.0))))


# As seis identidades. `editorial.py` é a fonte da verdade dos gêneros e
# não é reescrito aqui: o dicionário abaixo é indexado pelas mesmas
# chaves, e `test_todo_genero_tem_perfil` falha se um gênero novo não
# tiver direção tipográfica.

PEOPLE = TypographyProfile(
    key="people",
    label="História de pessoas",
    # Minion Pro é a referência pedida: serifada de texto, humanista, de
    # livro de biografia. A Italic é a voz documental — citação, documento,
    # latim, inscrição — e nunca a narração.
    families={INTENT_SERIF: "Minion Pro",
              INTENT_SERIF_ITALIC: "Minion Pro Italic",
              INTENT_SANS: "Inter",
              INTENT_MONO: "Source Code Pro"},
    roles={ROLE_TITLE: INTENT_SERIF,
           ROLE_PERSON: INTENT_SERIF,
           ROLE_SUBTITLE: INTENT_SERIF,
           ROLE_KICKER: INTENT_SANS,
           ROLE_CAPTION: INTENT_SANS,
           ROLE_QUOTE: INTENT_SERIF_ITALIC,
           ROLE_DOCUMENT: INTENT_SERIF_ITALIC,
           ROLE_LATIN: INTENT_SERIF_ITALIC,
           ROLE_TERM: INTENT_SERIF,
           ROLE_DATE: INTENT_SANS,
           ROLE_LOCATION: INTENT_SANS,
           ROLE_EMPHASIS: INTENT_SERIF,
           ROLE_CONCEPT: INTENT_SERIF},
    scale={ROLE_TITLE: 1.06, ROLE_PERSON: 1.0, ROLE_QUOTE: 0.94,
           ROLE_DOCUMENT: 0.9, ROLE_LATIN: 0.94, ROLE_CAPTION: 1.0,
           ROLE_KICKER: 0.62, ROLE_DATE: 0.72, ROLE_LOCATION: 0.72},
    direction="Livro de biografia. Serifada de leitura para a voz que "
              "narra; itálico serifado reservado para a voz que cita.")

HISTORY = TypographyProfile(
    key="history",
    label="História geral",
    families={INTENT_SERIF: "Minion Pro",
              INTENT_SERIF_ITALIC: "Minion Pro Italic",
              INTENT_SANS: "Inter",
              INTENT_MONO: "Source Code Pro"},
    roles={ROLE_TITLE: INTENT_SERIF, ROLE_PERSON: INTENT_SERIF,
           ROLE_SUBTITLE: INTENT_SERIF, ROLE_KICKER: INTENT_SANS,
           ROLE_CAPTION: INTENT_SANS, ROLE_QUOTE: INTENT_SERIF_ITALIC,
           ROLE_DOCUMENT: INTENT_SERIF_ITALIC,
           ROLE_LATIN: INTENT_SERIF_ITALIC, ROLE_TERM: INTENT_SERIF,
           ROLE_DATE: INTENT_SANS, ROLE_LOCATION: INTENT_SANS,
           ROLE_EMPHASIS: INTENT_SERIF, ROLE_CONCEPT: INTENT_SERIF},
    scale={ROLE_TITLE: 1.1, ROLE_QUOTE: 0.94, ROLE_KICKER: 0.6,
           ROLE_DATE: 0.7, ROLE_LOCATION: 0.7},
    direction="Documental e histórico, com título mais forte. Itálico para "
              "documento e citação. Nada de estética de rede social.")

ETYMOLOGY = TypographyProfile(
    key="etymology",
    label="Etimologia",
    # Aqui a tipografia É o conteúdo: a transformação da palavra é
    # mostrada, não contada. Por isso o itálico carrega a forma antiga e
    # o termo fica no corpo de destaque.
    families={INTENT_SERIF: "EB Garamond",
              INTENT_SERIF_ITALIC: "EB Garamond Italic",
              INTENT_SANS: "Inter",
              INTENT_MONO: "Source Code Pro"},
    roles={ROLE_TITLE: INTENT_SERIF, ROLE_PERSON: INTENT_SERIF,
           ROLE_SUBTITLE: INTENT_SERIF_ITALIC, ROLE_KICKER: INTENT_SANS,
           ROLE_CAPTION: INTENT_SANS, ROLE_QUOTE: INTENT_SERIF_ITALIC,
           ROLE_DOCUMENT: INTENT_SERIF_ITALIC,
           ROLE_LATIN: INTENT_SERIF_ITALIC, ROLE_TERM: INTENT_SERIF,
           ROLE_DATE: INTENT_SANS, ROLE_LOCATION: INTENT_SANS,
           ROLE_EMPHASIS: INTENT_SERIF, ROLE_CONCEPT: INTENT_SERIF},
    scale={ROLE_TERM: 1.18, ROLE_CONCEPT: 1.12, ROLE_TITLE: 1.04,
           ROLE_QUOTE: 0.96, ROLE_KICKER: 0.6},
    direction="A palavra é o gráfico. Termo no corpo de destaque, forma "
              "antiga em itálico, a seta de transformação como elemento "
              "tipográfico e não como seta desenhada.")

MYSTERY = TypographyProfile(
    key="mystery",
    label="Mistérios e casos",
    # Documento, não romance. Sans condensada carrega a sensação de
    # laudo/arquivo e deixa as quatro camadas de certeza legíveis.
    families={INTENT_SERIF: "Source Serif Pro",
              INTENT_SERIF_ITALIC: "Source Serif Pro Italic",
              INTENT_SANS: "Roboto Condensed",
              INTENT_SANS_ITALIC: "Roboto Condensed",
              INTENT_MONO: "IBM Plex Mono",
              INTENT_CONDENSED: "Roboto Condensed"},
    roles={ROLE_TITLE: INTENT_SANS, ROLE_PERSON: INTENT_SANS,
           ROLE_SUBTITLE: INTENT_SANS, ROLE_KICKER: INTENT_MONO,
           ROLE_CAPTION: INTENT_SANS, ROLE_QUOTE: INTENT_SERIF_ITALIC,
           ROLE_DOCUMENT: INTENT_MONO, ROLE_LATIN: INTENT_SERIF_ITALIC,
           ROLE_TERM: INTENT_SANS, ROLE_DATE: INTENT_MONO,
           ROLE_LOCATION: INTENT_MONO, ROLE_EMPHASIS: INTENT_SANS,
           ROLE_CONCEPT: INTENT_CONDENSED},
    scale={ROLE_KICKER: 0.66, ROLE_DATE: 0.74, ROLE_LOCATION: 0.74,
           ROLE_QUOTE: 0.96, ROLE_TITLE: 1.04},
    direction="Arquivo. Sans condensada; mono para data, lugar e "
              "identificador, para separar fato de testemunho na tela.")

MYTHOLOGY = TypographyProfile(
    key="mythology",
    label="Mitologia e folclore",
    families={INTENT_SERIF: "Adobe Caslon Pro",
              INTENT_SERIF_ITALIC: "Adobe Caslon Pro Italic",
              INTENT_SANS: "Inter",
              INTENT_MONO: "Source Code Pro"},
    roles={ROLE_TITLE: INTENT_SERIF, ROLE_PERSON: INTENT_SERIF_ITALIC,
           ROLE_SUBTITLE: INTENT_SERIF, ROLE_KICKER: INTENT_SERIF_ITALIC,
           ROLE_CAPTION: INTENT_SANS, ROLE_QUOTE: INTENT_SERIF_ITALIC,
           ROLE_DOCUMENT: INTENT_SERIF_ITALIC,
           ROLE_LATIN: INTENT_SERIF_ITALIC, ROLE_TERM: INTENT_SERIF,
           ROLE_DATE: INTENT_SANS, ROLE_LOCATION: INTENT_SANS,
           ROLE_EMPHASIS: INTENT_SERIF, ROLE_CONCEPT: INTENT_SERIF},
    scale={ROLE_PERSON: 1.08, ROLE_KICKER: 0.68, ROLE_QUOTE: 0.96,
           ROLE_TITLE: 1.05},
    direction="Tradição. Serifada literária; itálico para o nome do mito e "
              "para a tradição citada. Ornamento com moderação.")

SCIENCE = TypographyProfile(
    key="science",
    label="Ciência e descobertas",
    # Sem ornamento. A hierarquia vem do tamanho e do espaço, e números e
    # unidades precisam de uma fonte que alinhe dígito a dígito.
    families={INTENT_SERIF: "Noto Serif",
              INTENT_SERIF_ITALIC: "Noto Serif",
              INTENT_SANS: "Inter",
              INTENT_SANS_ITALIC: "Inter",
              INTENT_MONO: "JetBrains Mono"},
    roles={ROLE_TITLE: INTENT_SANS, ROLE_PERSON: INTENT_SANS,
           ROLE_SUBTITLE: INTENT_SANS, ROLE_KICKER: INTENT_SANS,
           ROLE_CAPTION: INTENT_SANS, ROLE_QUOTE: INTENT_SERIF_ITALIC,
           ROLE_DOCUMENT: INTENT_MONO, ROLE_LATIN: INTENT_SERIF_ITALIC,
           ROLE_TERM: INTENT_SANS, ROLE_DATE: INTENT_MONO,
           ROLE_LOCATION: INTENT_SANS, ROLE_EMPHASIS: INTENT_SANS,
           ROLE_CONCEPT: INTENT_SANS},
    scale={ROLE_TERM: 1.1, ROLE_TITLE: 1.02, ROLE_KICKER: 0.6,
           ROLE_DATE: 0.76},
    direction="Técnica. Sans limpa, hierarquia por tamanho e espaço, "
              "mono para medida e unidade. Nada de ornamento.")

# Sem gênero escolhido: a fonte de exibição que o projeto já usava. Não é
# um perfil editorial, é o absence de um — e precisa resolver para o mesmo
# arquivo que `find_font_bold()` devolve, senão um vídeo sem gênero muda
# de aparência.
DEFAULT = TypographyProfile(
    key="", label="Sem gênero",
    families={INTENT_SERIF: "", INTENT_SERIF_ITALIC: "",
              INTENT_SANS: "", INTENT_MONO: ""},
    roles={r: INTENT_SANS for r in ROLES},
    direction="Sem gênero: a fonte de exibição legível de sempre.")


PROFILES: dict[str, TypographyProfile] = {p.key: p for p in
                                           (PEOPLE, HISTORY, ETYMOLOGY,
                                            MYSTERY, MYTHOLOGY, SCIENCE)}


def profile_for(genre: str = "", overrides: dict | None = None
                ) -> TypographyProfile:
    """O perfil do gênero, com as trocas do usuário aplicadas por cima.

    `overrides` é a tabela `[typography.<gênero>]` do config.toml.

    Aceita família por INTENÇÃO — `primary`/`serif`, `italic`, `sans`,
    `mono`, `condensed`, e `fallback` como atalho para a serifada — e, para
    o caso raro, família por PAPEL em `[typography.<gênero>.roles]`. Trocar
    `primary` muda de uma vez todos os papéis serifados, que é o que se
    espera de "trocar a fonte deste gênero".
    """
    base = PROFILES.get(str(genre or "").strip().lower(), DEFAULT)
    if not overrides:
        return base
    fam = dict(base.families)
    roles = dict(base.roles)

    por_intencao = {"primary": INTENT_SERIF, "serif": INTENT_SERIF,
                    "italic": INTENT_SERIF_ITALIC, "sans": INTENT_SANS,
                    "mono": INTENT_MONO, "condensed": INTENT_CONDENSED}
    for chave, valor in overrides.items():
        chave = str(chave).strip()
        valor = str(valor or "").strip()
        if not valor or chave == "roles":
            continue
        if chave == "fallback":
            fam[INTENT_SERIF] = valor
        elif chave in por_intencao:
            fam[por_intencao[chave]] = valor
        elif chave in ROLES:
            roles[chave] = valor
        # Chave desconhecida é ignorada de propósito: erro de digitação em
        # config não pode virar fonte inventada.

    # `sans` cobre também o itálico sanserifado, senão trocar a sans
    # deixaria a citação em itálico de uma família que não é a do vídeo.
    if "sans" in overrides:
        fam[INTENT_SANS_ITALIC] = str(overrides["sans"]).strip()

    sub = overrides.get("roles")
    if isinstance(sub, dict):
        for papel, familia in sub.items():
            papel = str(papel).strip()
            familia = str(familia or "").strip()
            if papel in ROLES and familia:
                fam[f"role:{papel}"] = familia
    pinado = bool(fam != base.families)
    return replace(base, families=fam, roles=roles, pinned=pinado)


# --- resolução de fonte ------------------------------------------------

@dataclass(frozen=True)
class ResolvedFont:
    """O que o renderizador vai usar de fato, e o que ele queria usar."""

    family: str
    path: str | None
    italic: bool
    requested: str
    is_fallback: bool
    intent: str = ""

    @property
    def used_requested(self) -> bool:
        return not self.is_fallback

    def describe(self) -> str:
        marca = "" if not self.is_fallback else f" (fallback de {self.requested})"
        return f"{self.family}{'/itálico' if self.italic else ''}{marca}"


def _fc_resolve(family: str, want_italic: bool) -> tuple[str, str, bool] | None:
    """(família, caminho, é-itálico-de-verdade) via fontconfig. None se não há.

    Três checagens, e as três importam:

    1. o fontconfig substitui em silêncio — `fc-match "Minion Pro"` devolve
       Noto Sans. Exigimos que o nome pedido volte na família resolvida,
       senão ele não achou a fonte e sim outra qualquer;
    2. `:italic` num que não tem itálico devolve o REGULAR. Conferimos o
       estilo resolvido, e rejeitamos o regular quando o itálico foi pedido;
    3. família ausente do fontconfig não é motivo de erro aqui: é motivo
       de tentar a próxima candidata.

    O nome pode vir como a pessoa escreve — "Minion Pro Italic" — e aí o
    token de estilo vira a consulta `família:italic`.
    """
    familia, itálico_pedido = split_style(family)
    itálico_pedido = want_italic or itálico_pedido
    if not familia:
        return None
    try:
        proc = subprocess.run(
            ["fc-match", f"{familia}:italic" if itálico_pedido else familia,
             "--format=%{family}|%{file}|%{style}\n"],
            capture_output=True, text=True, timeout=15, check=False)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or "|" not in proc.stdout:
        return None
    partes = proc.stdout.strip().split("|")
    if len(partes) < 3:
        return None
    achada, caminho, estilo = partes[0], partes[1], partes[2]
    if familia.strip().lower() not in achada.lower():
        return None
    if not caminho or not os.path.isfile(caminho):
        return None
    inclinada = any(s in estilo.lower() for s in _SLANT_STYLES)
    if itálico_pedido and not inclinada:
        return None
    return achada, caminho, inclinada


_CACHE: dict[tuple[str, bool], tuple[str, str, bool] | None] = {}
_PAIR_CACHE: dict[tuple, str] = {}


def clear_cache() -> None:
    """Esvazia a resolução memorizada.

    A memória é global de propósito — resolver o mesmo papel duas vezes
    num vídeo não pode custar dois `fc-match` — mas quem muda o ambiente
    (fonte instalada, fontconfig indisponível) precisa de uma forma de
    mandar o módulo olhar de novo. Sem esta função, uma falha transitória
    fica na memória como se fosse definitiva, e a próxima fonte instalada
    continua invisível.

    Limpa também a decisão de PAR, que é derivada da resolução: deixar
    uma delas sobreviver a um `fc-match` reexecutado é o tipo de estado
    que faz um teste passar e o vídeo sair errado.
    """
    _CACHE.clear()
    _PAIR_CACHE.clear()


def _fc_cached(family: str, want_italic: bool):
    # A chave usa a forma já separada, para "X Italic" com e sem o token
    # não pagarem duas consultas ao fontconfig.
    familia, _ = split_style(family)
    chave = (familia, want_italic)
    if chave not in _CACHE:
        _CACHE[chave] = _fc_resolve(familia, want_italic)
    return _CACHE[chave]


def _legacy_path():
    """O arquivo que o projeto já usava, para o caminho sem perfil."""
    from .. import ffmpeg as ff
    return ff.find_font_bold()


def _candidates(profile: TypographyProfile, intent: str, role: str
                ) -> list[tuple[str, bool]]:
    """Cadeia de famílias a tentar, na ordem, com a Preferida primeiro.

    O primeiro item é o que o perfil pede; o resto é genérico por
    intenção. Uma entrada por papel (config `roles`) tem precedência
    sobre a da intenção, porque quem configura isso sabe o que quer.
    """
    want_italic = intent in (INTENT_SERIF_ITALIC, INTENT_SANS_ITALIC)
    especifico = profile.families.get(f"role:{role}", "").strip()
    if especifico:
        # Preferência, não sentence: se a família que o usuário apontou
        # para este papel não existir na máquina, o papel continua
        # resolvendo pela cadeia da intenção. Cair direto na fonte do
        # sistema aqui significaria que um `roles.quote` com um nome
        # errado apaga a serifa da citação, que é o oposto do que um
        # override de configuração deveria fazer.
        fila = [(especifico, want_italic)]
    else:
        fila = [(profile.family_for(intent).strip(), want_italic)] \
            if profile.family_for(intent).strip() else []
    if want_italic:
        # O itálico irmão da família que a voz principal JÁ RESOLVEU. Sem
        # isto, um título em EB Garamond e uma citação em Noto Serif são
        # duas famílias diferentes: a diferença existe, mas parece
        # acidente em vez de desenho, porque EB Garamond é uma old-style
        # e Noto Serif uma transitional.
        base_intent = (INTENT_SERIF if intent == INTENT_SERIF_ITALIC
                       else INTENT_SANS)
        familia_resolvida = _first_resolved(profile, base_intent)
        if familia_resolvida:
            irmao = f"{familia_resolvida} Italic"
            if not any(n == irmao for n, _ in fila):
                fila.append((irmao, True))
    for nome in GENERIC_FALLBACK.get(intent, ()):
        fila.append((nome, want_italic))
    return fila


def _tem_ambos(nome: str) -> str:
    """A família tem os dois rostos, e qual é o nome dela. "" se não tem.

    É o que separa "acho uma serifada" de "acho um PAR de serifada". Uma
    família sem itálico resolve a narração e obriga a citação a mudar de
    família, e um texto que muda de família entre o título e a citação lê
    como dois vídeos colados, não como um.
    """
    if not nome:
        return ""
    reto = _fc_cached(nome, False)
    if reto is None:
        return ""
    inclinado = _fc_cached(nome, True)
    return reto[0] if inclinado is not None else ""


def _first_resolved(profile: TypographyProfile, intent: str) -> str:
    """A primeira família da cadeia que existe de fato nesta máquina."""
    base = INTENT_SERIF if intent == INTENT_SERIF_ITALIC else intent
    for nome, itálico in _chain(profile, base):
        achado = _fc_cached(nome, itálico)
        if achado is not None:
            return achado[0]
    return ""


def _chain(profile: TypographyProfile, intent: str) -> list[tuple[str, bool]]:
    """Preferida + genérica, na ordem, para uma intenção não-itálica."""
    want_italic = intent in (INTENT_SERIF_ITALIC, INTENT_SANS_ITALIC)
    fila = []
    preferida = profile.family_for(intent).strip()
    if preferida:
        fila.append((preferida, want_italic))
    for nome in GENERIC_FALLBACK.get(intent, ()):
        fila.append((nome, want_italic))
    return fila



def resolve(role: str = ROLE_TITLE, genre: str = "",
            overrides: dict | None = None) -> ResolvedFont:
    """A fonte deste PAPEL neste gênero, com fallback que preserva a função.

    Devolve sempre algo. A última opção é a fonte de exibição que o
    projeto usava antes da tipografia existir, para que a montagem nunca
    quebre por falta de fonte — mas ela é marcada como fallback, e o
    `doctor` avisa, porque um vídeo que saiu com a fonte errada e sem
    aviso é pior do que um vídeo que não saiu.
    """
    profile = profile_for(genre, overrides)
    role = str(role or ROLE_TITLE).strip().lower() or ROLE_TITLE
    if role not in ROLES:
        role = ROLE_TITLE
    # Legibilidade não é negociável: o papel de legenda ignora a
    # intenção do perfil e fica na fonte de exibição, mesmo que o perfil
    # peça serifada.
    intent = (INTENT_SANS if role in LEGIBILITY_ROLES
              else profile.intent_for(role))
    par = _par_de_bolso(profile, intent)
    if par:
        # O gênero decidiu descer para um PAR. Título e citação usam a
        # mesma família, e a citação usa o itálico DELA. Filtrar
        # candidatos um a um em vez de trocar a cadeia inteira é o que
        # produzia "citação: fonte do sistema": o filtro pulava a
        # família certa por não ser a preferida do perfil, que é justamente
        # a família que não existe.
        wants = intent in (INTENT_SERIF_ITALIC, INTENT_SANS_ITALIC)
        fila = [(par, wants)]
        if wants:
            fila.append((f"{par} Italic", True))
        for nome in GENERIC_FALLBACK.get(intent, ()):
            fila.append((nome, wants))
    else:
        fila = _candidates(profile, intent, role)
    for familia, itálico in fila:
        achado = _fc_cached(familia, itálico)
        if achado is None:
            continue
        achada, caminho, inclinada = achado
        preferida = profile.family_for(intent).strip()
        # A comparação ignora o token de estilo. Pedir "Minion Pro
        # Italic" e receber o rosto itálico da Minion Pro É a fonte pedida
        # respondendo — marcar isso como fallback faria o doctor reclamar
        # de uma máquina que tem exatamente o que foi pedido.
        base_pedida = split_style(preferida or familia)[0]
        return ResolvedFont(family=achada, path=caminho, italic=inclinada,
                            requested=preferida or familia,
                            is_fallback=bool(base_pedida)
                            and achada.lower() != base_pedida.lower(),
                            intent=intent)
    legado = _legacy_path()
    return ResolvedFont(family="(fonte do sistema)", path=legado,
                        italic=False, requested=profile.family_for(intent),
                        is_fallback=True, intent=intent)


def _par_de_bolso(profile: TypographyProfile, intent: str) -> str:
    """A família que este gênero deve usar como PAR, ou "" se tanto faz.

    Existe por causa de uma assimetria feia. A Minion Pro não está em
    quase máquina nenhuma, e a primeira serifada da cadeia genérica
    (EB Garamond) também não tem itálico em parte das instalações. O
    resultado ingênuo é: título em EB Garamond, citação em Noto Serif.
    Duas famílias, uma old-style e uma transitional, no mesmo vídeo. A
    diferença existe, mas parece acidente em vez de desenho.

    Quando a família PREFERIDA do perfil não existe — e só nesse caso —
    procuramos a primeira da cadeia que tenha os dois rostos, e o gênero
    inteiro desce para ela. A função editorial fica preservada
    (serifada, com itálico) e a coerência volta. Se a preferida existe,
    ela manda, mesmo sem itálico: quem pediu Minion Pro pediu Minion Pro.

    A escolha é da família inteira, não do papel, por isso a letra do
    gênero decide e não o `title` que deu nome a esta função.
    """
    if intent not in (INTENT_SERIF, INTENT_SERIF_ITALIC, INTENT_SANS,
                      INTENT_SANS_ITALIC):
        return ""
    base = (INTENT_SERIF if intent == INTENT_SERIF_ITALIC
            else INTENT_SANS if intent == INTENT_SANS_ITALIC else intent)
    preferida = profile.family_for(base).strip()
    if not preferida:
        return ""
    chave = (profile.key, base, tuple(sorted(profile.families.items())),
             profile.pinned)
    if chave in _PAIR_CACHE:
        return _PAIR_CACHE[chave]
    par = ""
    achada = _fc_cached(preferida, False)
    if profile.pinned:
        par = ""            # escolha de quem usa: vale mesmo sem itálico
    elif achada is not None and _fc_cached(preferida, True) is not None:
        par = ""            # a preferida existe e tem os dois rostos
    else:
        # A preferida não existe, ou existe sem itálico. Nos dois casos o
        # gênero inteiro desce para a primeira da cadeia com par
        # completo, senão o título fica numa família e a citação em
        # outra — que é a incoerência que o autor viu.
        for nome, _it in _chain(profile, base):
            achado = _tem_ambos(nome)
            if achado:
                par = achado
                break
    _PAIR_CACHE[chave] = par
    return par



class Typography:
    """Handle de tipografia para o renderizador.

    O renderizador pergunta por um PAPEL e recebe fonte, caminho e corpo.
    Ele nunca vê nome de família vindo da cena, e nunca escolhe fonte.
    """

    def __init__(self, genre: str = "", overrides: dict | None = None):
        self.genre = str(genre or "")
        self.overrides = overrides or {}
        self.profile = profile_for(self.genre, self.overrides)
        self._cache: dict[tuple[str, bool], ResolvedFont] = {}

    def font(self, role: str = ROLE_TITLE) -> ResolvedFont:
        """A fonte resolvida deste papel, memoizada por instância."""
        chave = str(role)
        if chave not in self._cache:
            self._cache[chave] = resolve(chave, self.genre, self.overrides)
        return self._cache[chave]

    def size(self, role: str, base: int) -> int:
        return self.profile.size_for(str(role or ROLE_TITLE), base)

    def pil(self, role: str = ROLE_TITLE, size: int = 48):
        """A fonte PIL deste papel. Degrada para a do PIL, nunca levanta."""
        from PIL import ImageFont
        r = resolve(role, self.genre, self.overrides)
        if r.path:
            try:
                return ImageFont.truetype(r.path, self.size(role, size))
            except Exception:  # noqa: BLE001 — fonte nunca é fatal
                pass
        try:
            return ImageFont.load_default(size=self.size(role, size))
        except Exception:  # noqa: BLE001
            return ImageFont.load_default()

    def ass(self, role: str = ROLE_CAPTION) -> tuple[str, int, str | None]:
        """(família ASS, bold, arquivo) — o contrato que `subs` já usa."""
        r = resolve(role, self.genre, self.overrides)
        if role in LEGIBILITY_ROLES:
            from .subs import ensure_display_font
            return ensure_display_font()
        return r.family, 0, r.path

    def fontfile(self, role: str = ROLE_TITLE) -> str | None:
        r = resolve(role, self.genre, self.overrides)
        return r.path or _legacy_path()

    def report(self) -> dict:
        """O que foi resolvido, papel a papel. Vai para o metadata."""
        out = {"key": self.profile.key, "label": self.profile.label,
               "direction": self.profile.direction, "roles": {}}
        for papel in ROLES:
            r = resolve(papel, self.genre, self.overrides)
            out["roles"][papel] = {
                "intent": r.intent,
                "family": r.family,
                "italic": r.italic,
                "requested": r.requested,
                "fallback": r.is_fallback,
            }
        return out


def for_genre(genre: str = "", overrides: dict | None = None) -> Typography:
    """Ponto de entrada único. O resto do código usa este nome."""
    return Typography(genre, overrides)
