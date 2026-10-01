"""Entidade-alvo do tema: quem o vídeo é sobre, e o que NÃO é.

Existe por causa de um caso real. O tema era "Fale da História de São
Bento" — o santo do século VI — e a pesquisa devolveu três fontes
perfeitamente legítimas sobre coisas completamente diferentes:

    Serra Gaúcha            (município)
    Michel Temer             (pessoa)
    Lei dos Sexagenários    (lei)

E o pipeline aceitou as três, porque cada uma delas realmente menciona
"São Bento" ou "Bento". O grounding depois marcou "3 dado(s) conferidos,
todos nas fontes" — e estava certo: o roteiro era fiel às fontes. O
problema nunca foi a fidelidade, foi que as fontes não eram sobre o tema.
Verificar a segunda coisa contra a primeira dá um sistema que se
autovalida em cima do próprio erro.

A lição é que conferência de fidelidade e conferência de pertinência são
coisas diferentes, e só a segunda impede o desvio. Aqui mora a segunda.

A distinção que sustenta o filtro é `discriminant`: a palavra que separa
um referente de outro com o mesmo nome. "São Bento" e "São Bento de
Núrsia" compartilham nome; só a segunda tem "Núrsia" como discriminante.
Uma fonte sobre a Serra Gaúcha cita "São Bento" e não cita "Núrsia" — e é
exatamente aí que ela deixa de ser aceito como falar do santo. Coincidência
de nome próprio não é evidência de que o referente é o mesmo.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata

# Palavras que indicam que o referente é uma pessoa具/divindade/lugar, e
# por isso ambíguos. É aqui que a resolução tem mais trabalho a fazer.
_AMBIGUOUS_HINT = re.compile(
    r"(?i)\b(sobrenome|primeiro nome|homônimo|homónimo|cidade|município|"
    r"municipio|distrito|bairro|estado|rio|serra|vale|santo|santa|profeta|"
    r"rei|rainha|imperador|papa|filme|personagem|livro|álbum|album|"
    r"bairro|estado)\b")

_ENTITY_SYSTEM_PROMPT = (
    "You identify which real-world subject a video request is about, so the "
    "research does not drift to a different subject with the same name. "
    "Answer ONLY with valid JSON, no markdown, no explanation, in this exact "
    "format: {\"target\": \"...\", \"aliases\": [\"...\"], "
    "\"discriminants\": [\"...\"], \"search_queries\": [\"...\"], "
    "\"forbidden\": [\"...\"], \"ambiguous\": true, \"is_entity\": true}. "
    "Rules: "
    "1) target: the full canonical name of the intended subject, in the "
    "language of the request. If the request is about a saint, use the full "
    "form with the distinguishing place or epithet: \"São Bento de Núrsia\", "
    "not \"São Bento\". If it is a person, use the full name. "
    "2) aliases: other names the same subject goes by, 0 to 4, including the "
    "short form. "
    "3) discriminants: the words that PROVE a source is about this subject "
    "rather than a namesake, 0 to 6. For \"São Bento de Núrsia\": "
    "[\"Núrsia\", \"Nursia\", \"Benedito\", \"monge italiano\", \"séc. VI\"] "
    "— NEVER include the shared name itself, because that would accept a "
    "source about any namesake. "
    "4) search_queries: 2 to 4 queries that will find THIS subject on "
    "Wikipedia, in Portuguese, each with the discriminating context: "
    "[\"São Bento de Núrsia\", \"Benedito de Nursia monge\"] "
    "— not the bare name. "
    "5) forbidden: 2 to 5 well-known NAMESPACES of this subject, i.e. other "
    "real things that share the name and would be found by search: for São "
    "Bento de Núrsia [\"São Bento RS\", \"São Bento município\", \"Bento "
    "sobrenome\"]. "
    "6) ambiguous: true when the name alone genuinely refers to more than "
    "one thing and the request does not disambiguate it. "
    "7) is_entity: false when the request is NOT about a proper name and "
    "therefore has no namesake to confuse - \"Why is the ocean salty?\", "
    "\"How does a battery work?\". In that case set target to a short "
    "description of the topic, leave aliases, discriminants and forbidden "
    "empty, and put 2 to 4 distinctive topic words in search_queries. "
    "is_entity true only when the subject really is a named thing with a "
    "specific referent: a person, a place, a work, a saint. "
    "8) NEVER invent discriminants: author, date, work or epithet you are "
    "not sure about. An event like \"War of the Bucket\" takes "
    "discriminants from the request itself (\"Bucket\", \"Bologna, Modena, "
    "1325\" only if stated or certain), never a guessed author or year. "
    "When unsure, leave discriminants EMPTY: an empty list accepts by "
    "name, a guessed one rejects the right source. "
    "9) events and works follow the same full-name rule as saints: "
    "\"War of the Bucket\", not \"War\"; qualifiers in the request "
    "(\"oak\", \"1325\") are context, not part of the canonical title."
)

_ENTITY_SYSTEM_PROMPT_EN = _ENTITY_SYSTEM_PROMPT


def _fold(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in norm
                   if not unicodedata.combining(c)).lower()


def _norm_phrase(phrase: str) -> str:
    """Normaliza uma frase para comparação: sem acento, sem pontuação, espaços
    colapsados. 'São Bento de Núrsia' e 'sao bento de nursia' precisam casar."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", _fold(phrase))).strip()


class TargetEntity:
    """O referente pretendido, e o que distingue ele dos homônimos.

    `discriminants` é o coração: são as palavras que uma fonte precisa
    trazer para ser aceita como falar DESTE sujeito. Vazio significa que
    não há homônimo conhecido, e aí basta a fonte citar o nome.

    `is_entity` separa os dois problemas que a spec chama de "entity
    identity" e "topic relevance". Um tema como "Por que o mar é salgado?"
    não tem entidade nenhuma — não existe outro "Por que o mar é salgado?"
    que confunda a busca. Exigir que a fonte citasse o nome inteiro
    rejeitaria todas elas, o que é o modo de quebrar um tema que funcionava.
    Para esses, o portão mede sobreposição temática; para os com nome
    próprio, mede identidade.
    """

    def __init__(self, name: str = "", aliases: list[str] | None = None,
                 discriminants: list[str] | None = None,
                 search_queries: list[str] | None = None,
                 forbidden: list[str] | None = None,
                 ambiguous: bool = False, source: str = "heuristic",
                 is_entity: bool = True, topic_terms: list[str] | None = None):
        self.name = (name or "").strip()
        self.aliases = [str(a).strip() for a in (aliases or []) if str(a).strip()]
        self.discriminants = [str(d).strip()
                              for d in (discriminants or []) if str(d).strip()]
        self.search_queries = [str(q).strip()
                               for q in (search_queries or []) if str(q).strip()]
        self.forbidden = [str(f).strip()
                          for f in (forbidden or []) if str(f).strip()]
        self.ambiguous = bool(ambiguous)
        self.source = source
        self.is_entity = bool(is_entity)
        self.topic_terms = [str(t).strip().lower()
                            for t in (topic_terms or []) if str(t).strip()]

    # -- comparações --
    def all_names(self) -> list[str]:
        return [n for n in ([self.name] + self.aliases) if n]

    def short_forms(self) -> list[str]:
        """O nome até a primeira partícula: a parte que o homônimo compartilha.

        "São Bento de Núrsia" → "São Bento"; "Alexandre, o Grande" →
        "Alexandre". Sem isto, a fonte de um homônimo era rejeitada logo
        no nome, e o motivo saía "não menciona a entidade" — o que
        esconde justamente a informação útil (é o homônimo que tem o
        mesmo nome). Chegando até o discriminante, o diagnóstico aponta o
        namesake, que é o que o autor precisa ler.
        """
        out: list[str] = []
        for nome in self.all_names():
            partes = re.split(r"[,–—]|\s+(?:de|da|do|das|dos|e|o|a)\s+",
                              nome, maxsplit=1)
            curto = (partes[0] or "").strip(" ,")
            if len(_norm_phrase(curto)) >= 3 and curto not in out:
                out.append(curto)
        return out

    def _fold_text(self, text: str) -> str:
        return _norm_phrase(text)

    def core_terms(self) -> list[str]:
        """Núcleo do nome: palavras significativas, sem partículas.

        "A Guerra do Balde de Carvalho" -> ["guerra", "balde", "carvalho"].
        Serve ao casamento por núcleo: a ordem e os qualificadores podem
        variar ("Guerra do Balde" vs "Guerra do Balde de Carvalho"), mas
        todas as palavras do núcleo precisam estar no título da fonte.
        """
        stop = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os",
                "em", "no", "na", "the", "of"}
        out: list[str] = []
        for tok in _norm_phrase(self.name).split():
            if len(tok) >= 4 and tok not in stop and tok not in out:
                out.append(tok)
        return out

    def nucleus_in_title(self, title: str) -> bool:
        """O núcleo consta do título (qualquer ordem, um qualificador a menos)?

        "Guerra do Balde" passa para alvo "Guerra do Balde de Carvalho"
        (2/3); "Flávio Bolsonaro" não passa (0/3). Um qualificador a
        menos é tolerado porque o pedido costuma trazer contexto que o
        título canônico não tem ("de Carvalho", "de 1325"); dois a
        menos já é outro assunto. Com 1–2 termos no núcleo, exige todos.
        """
        core = self.core_terms()
        if not core:
            return False
        hay = _norm_phrase(title)
        hit = sum(1 for t in core if t in hay)
        if len(core) <= 2:
            return hit == len(core)
        return hit >= len(core) - 1

    def mentions_name(self, text: str) -> bool:
        """O texto cita o sujeito por algum dos seus nomes?"""
        hay = self._fold_text(text)
        for nome in self.all_names() + self.short_forms():
            n = self._fold_text(nome)
            if n and n in hay:
                return True
        return False

    def matched_discriminants(self, text: str) -> list[str]:
        hay = self._fold_text(text)
        achados = []
        for d in self.discriminants:
            n = self._fold_text(d)
            if n and n in hay:
                achados.append(d)
        return achados

    def matched_forbidden(self, text: str) -> list[str]:
        hay = self._fold_text(text)
        return [f for f in self.forbidden if self._fold_text(f) in hay]

    def to_dict(self) -> dict:
        return {"target": self.name, "aliases": self.aliases,
                "discriminants": self.discriminants,
                "search_queries": self.search_queries,
                "forbidden": self.forbidden, "ambiguous": self.ambiguous,
                "is_entity": self.is_entity, "source": self.source}

    def __repr__(self) -> str:
        return (f"TargetEntity({self.name!r}, discriminants="
                f"{self.discriminants!r}, ambiguous={self.ambiguous}, "
                f"source={self.source!r})")


# --- heurística sem LLM ------------------------------------------------

_CAP = re.compile(r"\b(?:de|da|do|dos|das|o|a|e)\b", re.I)


_CONECTORES = {"de", "da", "do", "das", "dos", "e"}


def _capitalized_spans(idea: str) -> list[str]:
    """Blocos de nome próprio no texto, agrupando palavras capitalizadas.

    Por palavras, não por regex: os intervalos de Unicode estouram fácil e
    agrupar "São" + "Bento" + "de" + "Núrsia" num bloco só é o que interessa
    aqui, porque o nome do sujeito vem em pedaços.

        "Fale da História de São Bento"  -> ["História", "São Bento"]
        "História de São Bento"          -> ["História", "São Bento"]
        "De onde veio a palavra salário?"-> []
    """
    texto = re.sub(r"\s+", " ", (idea or "").strip())
    if not texto:
        return []
    blocos: list[str] = []
    atual: list[str] = []

    def _fechar():
        if atual:
            bloco = " ".join(atual).strip()
            if bloco and bloco not in blocos:
                blocos.append(bloco)
        atual.clear()

    for i, palavra in enumerate(texto.split()):
        limpa = re.sub(r"[^\wÀ-ÿ]", "", palavra)
        if not limpa:
            _fechar()
            continue
        capitalizada = limpa[0].isupper()
        if not capitalizada:
            # Conector entre duas capitalizadas ("São Bento de Núrsia")
            # continua o bloco; qualquer outra palavra o fecha.
            if (atual and limpa.lower() in _CONECTORES and i + 1 < len(
                    texto.split())
                    and re.sub(r"[^\wÀ-ÿ]", "",
                               texto.split()[i + 1])[:1].isupper()):
                continue
            _fechar()
            continue
        # Palavra capitalizada que é comum ("História", "Fale", "Como") não
        # faz parte de nome próprio: fecha o bloco em vez de fundi-lo. Sem
        # isso "História de São Bento" virava um bloco só, "História São
        # Bento", e o alvo saía errado.
        if limpa.lower() in _COMUN_INICIAIS:
            _fechar()
            continue
        atual.append(limpa)
    _fechar()
    return blocos


_COMUN_INICIAIS = {
    "fale", "como", "por", "porque", "quando", "onde", "qual", "quais",
    "historia", "história", "de", "do", "da", "a", "o", "e", "o", "quero",
    "quero", "saiba", "descubra", "entenda", "veja", "a historia",
    "the", "how", "why", "what", "when", "where", "who", "talking",
}


# Stopwords de 3 letras: nunca entraram em STOP_PT porque
# `extract_keywords` exige 4+, então ficariam de fora aqui, onde o piso
# é 3. "Por que o mar é salgado?" dava topics ['mar', 'por', 'que', ...].
_STOP_CURTAS = {
    "por", "que", "com", "sem", "uma", "uns", "das", "dos", "seu", "sua",
    "the", "and", "you", "how", "why", "what", "for", "not", "are", "was",
}


def topic_terms_of(idea: str, language: str = "pt-BR") -> list[str]:
    """Palavras que definem o ASSUNTO, para medir pertinência temática.

    Aceita 3 letras, ao contrário de `research.extract_keywords`, que
    existe para montar query de busca e por isso exige 4. A diferença
    importa: "Por que o mar é salgado?" tem como termo central "mar", e
    uma lista que o descarta deixa a fonte do próprio mar sem nenhuma
    palavra em comum com o tema.
    """
    from . import research as _research
    stop = set(_research.STOP_EN if str(language or "").lower().startswith("en")
               else _research.STOP_PT) | _STOP_CURTAS
    freq: dict[str, int] = {}
    for bruto in re.findall(r"[A-Za-zÀ-ÿ]{3,}", idea or ""):
        base = _fold(bruto)
        if base in stop or len(base) < 3:
            continue
        freq[base] = freq.get(base, 0) + 1
    ranked = sorted(freq, key=lambda b: (-freq[b], b))
    return ranked[:4]


def resolve_entity_heuristic(idea: str, language: str = "pt-BR") -> TargetEntity:
    """Sem LLM: extrai o nome próprio mais provável e o toma como alvo.

    Limitação honesta, e ela precisa estar escrita: sem modelo não há como
    saber que "São Bento" é o santo e não o município. O que a heurística
    faz é marcar `ambiguous` quando o nome é curto/genérico e pedir
    para o pipeline avisar, em vez de fingir certeza. É por isso que o
    portão de relevância aceita a fonte por nome quando não há
    discriminante — e por isso que a proteção real vem da resolução.
    """
    blocos = _capitalized_spans(idea)
    alvo = next((b for b in blocos
                 if _norm_phrase(b) and _norm_phrase(b) not in _CAP_ONLY), "")
    if alvo:
        nome = alvo
        curto = len(_norm_phrase(nome).split()) <= 2
        return TargetEntity(
            name=nome, aliases=[], discriminants=[],
            search_queries=[nome, f"{nome} história"], forbidden=[],
            ambiguous=bool(curto and _AMBIGUOUS_HINT.search(idea or "")),
            is_entity=True, source="heuristic")
    # Sem nome próprio: o tema não tem entidade, e o portão passa a medir
    # sobreposição temática em vez de identidade. Colapsar os dois num nome
    # só rejeitaria todas as fontes de "Por que o mar é salgado?".
    return TargetEntity(
        name="", aliases=[], discriminants=[],
        search_queries=[], forbidden=[], ambiguous=False,
        is_entity=False, topic_terms=topic_terms_of(idea, language),
        source="heuristic")


_CAP_ONLY = {"de", "da", "do", "a", "o", "e"}


# --- resolução por LLM -------------------------------------------------

def resolve_entity(idea: str, cfg=None, language: str = "pt-BR",
                   metrics=None) -> TargetEntity:
    """Determina o referente pretendido. LLM quando há chave; heurística não.

    Falha de LLM aqui NÃO é erro fatal: devolve a heurística e segue. O
    que não pode é devolver um alvo inventado.
    """
    if not (idea or "").strip():
        return TargetEntity(name="", source="vazio")
    heuristica = resolve_entity_heuristic(idea, language)
    try:
        from . import nvidia as nvidia_stage
        if not nvidia_stage.any_llm_available() or cfg is None:
            return heuristica
        english = str(language or "").lower().startswith("en")
        system = (_ENTITY_SYSTEM_PROMPT_EN if english
                  else _ENTITY_SYSTEM_PROMPT)
        user = (f"Which subject is this video request about: {idea.strip()}"
                if english else
                f"Sobre qual sujeito é este pedido de vídeo: {idea.strip()}")
        data, _label = nvidia_stage.complete_json(
            system, user, cfg.nvidia_model, cfg.nvidia_base_url,
            cfg.nvidia_timeout, metrics,
            or_model=cfg.openrouter_model,
            or_base_url=cfg.openrouter_base_url,
            extra=cfg.llm_overrides())
        from ..runlog import event as run_event
        run_event("provider", f"Entidade: {_label}", operation="entity",
                  provider=_label.split(":", 1)[0], model=_label.split(":", 1)[-1])
        if not isinstance(data, dict):
            return heuristica
        nome = str(data.get("target", "") or "").strip()
        if not nome:
            return heuristica
        def _lst(k, lim):
            v = data.get(k, [])
            if isinstance(v, str):
                v = [v]
            if not isinstance(v, list):
                return []
            out, seen = [], set()
            for x in v:
                s = str(x).strip()
                if s and s.lower() not in seen:
                    seen.add(s.lower())
                    out.append(s)
            return out[:lim]
        alvo = TargetEntity(
            name=nome,
            aliases=_lst("aliases", 4),
            discriminants=_lst("discriminants", 6),
            search_queries=_lst("search_queries", 4),
            forbidden=_lst("forbidden", 5),
            ambiguous=bool(data.get("ambiguous", False)),
            is_entity=bool(data.get("is_entity", True)),
            topic_terms=_lst("search_queries", 4),
            source="llm")
        if metrics is not None:
            metrics.research_source()  # conta como 1 consulta de pesquisa
        return alvo
    except Exception as exc:  # noqa: BLE001 — heurística cobre
        from ..runlog import event as run_event
        logged = run_event("fallback", f"Entidade: {exc}; usando heurística",
                           operation="entity", fallback="heuristic",
                           error=str(exc))
        if not logged:
            print(f"AVISO: resolução de entidade falhou ({exc}) — usando a "
                  f"heurística; fontes podem ser menos precisas.", file=sys.stderr)
        return heuristica


# --- o portão ----------------------------------------------------------

REASON_OK = "ok"
REASON_ENTITY = "não menciona a entidade-alvo"
REASON_DISCRIMINANT = ("cita a entidade, mas nenhum termo que a distinga "
                       "de um homônimo")
REASON_FORBIDDEN = "fala de um homônimo conhecido do tema"
REASON_OFFTOPIC = "baixa relevância com o tema"


def _head_noun(phrase: str) -> str:
    """O substantivo de um sintagma: a última palavra com letra.

    "Etimologia da palavra salário" -> "salário"; "Cor azul do céu" ->
    "céu"; "por que o céu é azul?" -> "azul". Serve para os dois idiomas
    que o curio fala, onde o substantivo fecha o sintagma. Sintagma curto
    é o que o estágio de entidade sempre devolve, e é por isso que a
    posição é confiável aqui.
    """
    limpo = re.sub(r"[^\w\s]", " ", str(phrase or ""))
    palavras = [p for p in limpo.split() if p]
    return palavras[-1] if palavras else ""


def source_verdict(source, target: TargetEntity) -> tuple[str, str]:
    """Aceita ou rejeita a fonte como fundamento do tema. (motivo, detalhe).

    Dois caminhos, porque são dois problemas:

    * **identidade** (tema com nome próprio): a fonte tem que citar o
      sujeito E trazer um termo que a distinga de um homônimo. Foi o que
      barrou a Serra Gaúcha — ela cita "São Bento" e não traz "Núrsia".
      Coincidência de nome próprio não é evidência de que o referente é o
      mesmo, e a spec pede exatamente isso.

    * **pertinência temática** (tema sem entidade, "por que o mar é
      salgado?"): não há homônimo a confundir, então exigir o nome inteiro
      rejeitaria todas as fontes e o tema deixaria de funcionar. Basta
      sobreposição com os termos do tema.

    `REASON_DISCRIMINANT` prefere uma cena sem fundamentação a um vídeo
    sobre a pessoa errada com cara de fundamentado.
    """
    titulo = str(getattr(source, "title", "") or "")
    trecho = str(getattr(source, "snippet", "") or "")
    texto = f"{titulo} {trecho}"
    if target is None:
        return REASON_OK, ""

    if not target.is_entity:
        termos = list(target.topic_terms)
        if not termos:
            return REASON_OK, ""
        hay = _norm_phrase(texto)
        # Casar a frase inteira era o filtro, e ele não tinha como
        # funcionar: os topic_terms são frases de BUSCA, escritas para
        # achar o artigo, e nenhum artigo se intitula "origem da palavra
        # salário". Com o filtro inteiro, a fonte certa ("Salário", que
        # define a palavra) era rejeitada e um tema de etimologia
        # terminava com zero fontes — o portão virava o defeito.
        #
        # O que separa "Salário" de "Via Salária" e de "Pro-labore" não é
        # a frase: é o substantivo. E o substantivo de um sintagma nominal
        # em português e inglês é a última palavra — o estágio de entidade
        # sempre devolve um sintagma curto, nunca uma frase.
        #
        # E o substantivo é procurado no TÍTULO, não em qualquer parte do
        # texto. "Pro-labore" tem "salário" na descrição ("adiantamento
        # de salário") e isso não faz dele um artigo sobre a palavra
        # salário; o título é o que diz sobre o que o artigo é.
        achados = [t for t in termos
                   if _norm_phrase(t) and _norm_phrase(t) in hay]
        if not achados:
            cabeca = _norm_phrase(_head_noun(target.name))
            if cabeca and cabeca in _norm_phrase(titulo):
                achados = [_head_noun(target.name)]
        if not achados:
            return REASON_OFFTOPIC, ""
        return REASON_OK, ""

    if not target.name:
        return REASON_OK, ""
    proibidos = target.matched_forbidden(texto)
    if proibidos:
        return REASON_FORBIDDEN, ", ".join(proibidos)
    if not target.mentions_name(texto):
        return REASON_ENTITY, ""
    if target.discriminants:
        achados = target.matched_discriminants(texto)
        if not achados:
            return REASON_DISCRIMINANT, ""
    return REASON_OK, ""


def script_context(target: TargetEntity | None,
                   language: str = "pt-BR") -> str:
    """O contexto da ENTIDADE para o prompt do roteiro. Vazio se não houver.

    Este texto não cria informação: ele reformula o que a resolução de
    entidade já produziu, e existe porque essa informação não chegava ao
    gerador de roteiro. A pesquisa sabe que o sujeito é "São Jerônimo de
    Estrídia", que "São Jerônimo" e "Jerônimo" são a mesma pessoa, que
    "Padre da Igreja" e "Vulgata" o identificam, e que "São Jerônimo RS"
    é outra coisa; o roteiro era escrito a partir da frase da ideia e
    quase sempre sem nenhum disso.

    A forma exata do nome NÃO é o que se impõe aqui. O que se impõe é:
    mencione a pessoa pela forma que preserva quem ela é — "São
    Jerônimo", com o título — e alongue quando o contexto pedir. Um
    vídeo sobre o padre da Igreja que abre chamando-o de "Jerônimo" é o
    mesmo vídeo sobre outro assunto, e nenhum aviso sobre homônimo
    conserta isso depois.

    Deliberadamente NÃO há nada aqui sobre linguagem religiosa. A
    direção de arte não pediu devocional, pediu que o contexto não fosse
    apagado; mandar o modelo "inclua linguagem sagrada" produziria
    exatamente o oposto — invenção devocional num vídeo documental.
    """
    if target is None or not (target.name or "").strip():
        return ""
    if not target.is_entity:
        # Sem entidade não há forma canônica a preservar: o bloco não
        # teria nada de específico e só poluiria o prompt.
        return ""
    english = str(language or "").lower().startswith("en")
    nome = target.name
    linhas = []
    if english:
        linhas.append(f"THE SUBJECT OF THIS VIDEO IS: {nome}.")
        if target.aliases:
            linhas.append("It is the same person as: "
                          + ", ".join(target.aliases)
                          + ". You may use a shorter form when the "
                            "narrative calls for it, but keep the form "
                            "that identifies who this is.")
        if target.discriminants:
            linhas.append("Words that identify THIS subject: "
                          + ", ".join(target.discriminants) + ".")
        if target.forbidden:
            linhas.append("NEVER confuse this subject with: "
                          + ", ".join(target.forbidden)
                          + ". Those are different places or people; "
                            "referring to them means the video is about "
                            "the wrong thing.")
    else:
        linhas.append(f"O SUJEITO DESTE VÍDEO É: {nome}.")
        if target.aliases:
            linhas.append(
                "É a mesma pessoa que: " + ", ".join(target.aliases)
                + ". Pode usar uma forma mais curta quando a narração "
                  "pedir, mas conserve a forma que identifica quem é.")
        if target.discriminants:
            linhas.append("Termos que identificam ESTE sujeito: "
                          + ", ".join(target.discriminants) + ".")
        if target.forbidden:
            linhas.append("NUNCA confunda este sujeito com: "
                          + ", ".join(target.forbidden)
                          + ". São outros lugares ou outras pessoas; "
                          "falar deles significa que o vídeo é sobre "
                          "outra coisa.")
    return "\n".join(linhas)


def explain(target: TargetEntity, accepted: list, rejected: list) -> str:
    """Diagnóstico legível da seleção de fontes (para log e relatório)."""
    linhas = ["", "Diagnóstico das fontes:", "=" * 62]
    linhas.append(f"Tema solicitado: {target.name or '(não identificado)'}")
    if target.source == "llm":
        linhas.append(f"Entidade-alvo: {target.name}")
        if target.aliases:
            linhas.append(f"  também chamada: {', '.join(target.aliases)}")
        if target.discriminants:
            linhas.append(f"  termos que a distinguem: "
                          f"{', '.join(target.discriminants)}")
        if target.ambiguous:
            linhas.append("  ⚠ nome ambíguo: o tema não desambigua sozinho")
    else:
        linhas.append("Entidade-alvo: (heurística — sem chave de LLM; "
                      "homônimos podem passar)")
    if accepted:
        linhas.append(f"Fontes aceitas ({len(accepted)}):")
        for s in accepted:
            linhas.append(f"  + {getattr(s, 'title', '?')[:70]}")
    if rejected:
        linhas.append(f"Fontes rejeitadas ({len(rejected)}):")
        for s, motivo, detalhe in rejected:
            extra = f" ({detalhe})" if detalhe else ""
            linhas.append(f"  - {getattr(s, 'title', '?')[:60]}{extra}")
            linhas.append(f"      motivo: {motivo}")
    linhas.append("=" * 62)
    return "\n".join(linhas)
