"""Gêneros como perfis editoriais: seis gramáticas, um pipeline.

A regra que este módulo existe para impor: gênero não é um campo que muda
a frase do prompt. Se "Etimologia" e "História de pessoas" produzissem a
mesma estrutura, o mesmo pacing, as mesmas formas de card e as mesmas
transições, haveria seis etiquetas e um formato só — e tirar o título do
vídeo deixaria claro que são o mesmo produto.

O que diferencia um gênero aqui é parâmetro, não adjetivo:

- **pacing** (segundos por cena, limites, densidade): muda de verdade o
  número de cenas, que é a unidade de ritmo do vídeo inteiro;
- **direção narrativa**: o bloco que entra no prompt do roteiro, com a
  estrutura que aquele gênero de fato prefere;
- **pesquisa**: o que aquele gênero precisa distinguir e perguntar;
- **vocabulário visual**: os `subject`/`entities`/`forbidden` que a cena
  deve declarar para aquele tipo de história;
- **forma visual preferida e escada**: qual medium serve melhor;
- **legendas**: densidade e o que merece destaque;
- **encerramento**: como o vídeo fecha.

Nada aqui é template. Um perfil diz o que PREFERIR e o que EVITAR; a
cena continua decidindo a composição local com o que ela tem. É por isso
que o mesmo tema em dois gêneros não dá duas vezes o mesmo vídeo, e que
nenhum gênero engessa o conteúdo.

Compatibilidade: `genre` vazio (padrão) não seleciona perfil nenhum, e o
pipeline segue exatamente como antes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- pequenas estruturas de diretriz -----------------------------------


@dataclass(frozen=True)
class Pacing:
    """Ritmo, em segundos por cena. É o que muda o vídeo de verdade.

    `target` alimenta o cálculo de nº de cenas; os limites entram no
    replanejamento. `caption_max_words` e `caption_highlight` controlam a
    densidade e o destaque das legendas, que é a segunda coisa que o
    espectador percebe sem ver o título.

    `max_scenes` é o teto de cortes e pertence ao perfil, e não é
    redundante com `target_scene_seconds`. O teto legado é 12; um
    perfil de 7,5 s por cena precisa passar de 12 ou o pacing deixa de
    existir em qualquer roteiro longo — que é o "rótulo que muda o
    texto". Ele só entra em jogo quando há gênero, e o chamador sem
    gênero continua com o teto de sempre.
    """
    target_scene_seconds: float = 9.0
    min_scene_seconds: float = 3.0
    max_scene_seconds: float = 20.0
    max_scenes: int = 12
    information_density: str = "medium"   # low | medium | high
    caption_max_words: int = 5
    caption_highlight: str = "word"        # word | keyword | none


@dataclass(frozen=True)
class ResearchStyle:
    """O que a pesquisa deste gênero precisa perguntar e distinguir."""
    guidance: str = ""
    queries: tuple[str, ...] = ()
    must_distinguish: tuple[str, ...] = ()


@dataclass(frozen=True)
class NarrativeStyle:
    """Direção de roteiro: estrutura preferida e o que evitar."""
    direction: str = ""
    avoid: str = ""


@dataclass(frozen=True)
class VisualStyle:
    """Direção visual da cena e medium preferido."""
    scene_direction: str = ""
    preferred_forms: tuple[str, ...] = ()
    media_hints: tuple[str, ...] = ()
    avoid: str = ""
    # Escada de medium para a cena, do mais adequado ao menos. Vazio usa
    # a escada padrão do `stages.visuals`.
    ladder: tuple[str, ...] = ()
    # Termos que a cena deve declarar como proibidos, além dos da IA.
    forbidden: tuple[str, ...] = ()
    continuity: str = ""
    focus: str = ""


@dataclass(frozen=True)
class GenreAdapter:
    """Contrato declarativo de gênero. Não executa I/O nem renderização.

    Adapter escolhe políticas. Infraestrutura executa pesquisa, LLM, mídia,
    áudio e render. Campos têm defaults para gênero novo não precisar
    implementar comportamento que não usa.
    """
    key: str
    label: str
    description: str
    pacing: Pacing = field(default_factory=Pacing)
    research: ResearchStyle = field(default_factory=ResearchStyle)
    narrative: NarrativeStyle = field(default_factory=NarrativeStyle)
    visual: VisualStyle = field(default_factory=VisualStyle)
    caption: str = ""
    ending: str = ""
    specialized_sources: tuple[str, ...] = ()
    generic_media_queries: tuple[str, ...] = ()
    media_provider_priority: tuple[str, ...] = ()
    visual_context_medium: str = ""
    transition_duration: float = 0.20
    transition_kind: str = "fade"
    music_query: str = "calm ambient"
    music_mood: str = "calm"
    sfx_categories: tuple[str, ...] = ("paper", "soft_impact")
    pacing_note: str = "Moderate and rising, accelerating through the event."


# --- os perfis ---------------------------------------------------------

HISTORY = GenreAdapter(
    key="history",
    label="História geral / Dark History",
    description="Quedas de impérios, batalhas, revoluções, crimes e "
                "desastres contados como narrativa, não como aula.",
    pacing=Pacing(target_scene_seconds=9.0, min_scene_seconds=3.5,
                  max_scene_seconds=18.0, information_density="high",
                  max_scenes=12, caption_max_words=5, caption_highlight="keyword"),
    research=ResearchStyle(
        guidance="Priorize fontes históricas, documentos, arquivos e "
                 "museus. Para cada acontecimento, responda quem, quando, "
                 "onde, o que aconteceu, causas, consequências e contexto.",
        queries=("arquivo histórico", "documento histórico", "crônica",
                 "historiografia", "manuscrito", "museu"),
        must_distinguish=("o que é registro documental e o que é "
                          "atribuição posterior"),
    ),
    narrative=NarrativeStyle(
        direction="Estrutura: gancho, contexto mínimo, situação inicial, "
                  "ruptura, escalada, acontecimento principal, consequência, "
                  "legado. Não entregue tudo em ordem cronológica.",
        avoid="Não transforme em resumo cronológico nem em lista de datas."),
    visual=VisualStyle(
        scene_direction="Fotografia histórica, pintura, mapa, documento, "
                        "gravura, retrato, local real, artefato.",
        preferred_forms=("definition", "enumeration"),
        media_hints=("historical map", "engraving", "sepia photograph",
                     "old document", "battle painting", "archive scan"),
        avoid="Não use foto de banco moderna como se fosse registro de época, "
              "nem paisagem genérica como plano de fundo.",
        forbidden=("modern photograph", "wallpaper", "generic landscape"),
    ),
    caption="Destaque nomes de pessoas, lugares e datas; corte de 5 em 5.",
    ending="Feche no legado ou na consequência que dura até hoje.",
    specialized_sources=("loc", "perseus"),
    generic_media_queries=("church interior", "old library", "ancient manuscript",
                           "museum hall", "historic map", "castle"),
    media_provider_priority=("met", "aic", "wikimedia", "openverse"),
    visual_context_medium="painting",
    transition_duration=0.25, transition_kind="wipeleft",
    music_query="tense ambient", music_mood="tense",
    pacing_note="Moderate and rising, accelerating through the event.",
)

ETYMOLOGY = GenreAdapter(
    key="etymology",
    label="Etimologia e origem de palavras",
    description="De onde veio a palavra e como o significado se transformou.",
    pacing=Pacing(target_scene_seconds=7.5, min_scene_seconds=2.5,
                  max_scene_seconds=13.0, information_density="high",
                  max_scenes=20, caption_max_words=4, caption_highlight="word"),
    research=ResearchStyle(
        guidance="Investigue a língua de origem, as formas antigas, mudanças "
                 "fonéticas e semânticas, os primeiros registros e os "
                 "cognatos. Separe sempre origem documentada de hipótese e "
                 "de etimologia popular.",
        queries=("etimologia", "origem da palavra", "forma antiga",
                 "cognato", "inscrição antiga", "primeiro registro",
                 "etimologia popular falsa"),
        must_distinguish=("origem documentada", "hipótese", "etimologia popular"),
    ),
    narrative=NarrativeStyle(
        direction="Estrutura: a palavra hoje, o estranhamento, a forma antiga, "
                  "a origem, a transformação, o significado intermediário, o "
                  "significado atual.",
        avoid="Não diga que uma etimologia popular é verdade sem marcar que "
              "é popular."),
    visual=VisualStyle(
        scene_direction="Palavra, manuscrito, inscrição, documento antigo, "
                        "dicionário, mapa linguístico, alfabeto, forma antiga "
                        "da palavra. A tipografia é parte da composição, não "
                        "um plano B.",
        preferred_forms=("definition", "spotlight", "contrast"),
        media_hints=("ancient manuscript", "stone inscription", "old dictionary",
                     "handwriting", "lettering", "medieval text"),
        avoid="Não use a linguagem visual de uma biografia: aqui o objeto da "
              "cena é a PALAVRA.",
        ladder=("typographic", "conceptual", "literal"),
        focus=("The subject is usually a WORD, not an object: prefer the word "
               "or its historical form as subject; put its real components "
               "and cultural setting in visual_entities and context."),
    ),
    caption="Destaque a própria palavra a cada menção; corte de 4 em 4.",
    ending="Feche na transformação do sentido, não numa curiosidade solta.",
    specialized_sources=("wiktionary", "logeion", "perseus"),
    generic_media_queries=("ancient manuscript", "stone inscription",
                           "old dictionary", "handwriting", "lettering"),
    visual_context_medium="",
    transition_duration=0.16, transition_kind="smoothleft",
    music_query="calm curious ambient", music_mood="calm",
    pacing_note="Fast and revelatory, with a feeling of discovery.",
)

MYTHOLOGY = GenreAdapter(
    key="mythology",
    label="Mitologia e folclore",
    description="Mitos, lendas e tradições, distinguindo tradição de fato.",
    pacing=Pacing(target_scene_seconds=12.0, min_scene_seconds=5.0,
                  max_scene_seconds=22.0, information_density="medium",
                  max_scenes=12, caption_max_words=6, caption_highlight="keyword"),
    research=ResearchStyle(
        guidance="Priorize textos antigos, registros de tradição, estudos "
                 "acadêmicos e acervos culturais. Quando houver versões "
                 "divergentes, registre-as.",
        queries=("texto antigo", "tradição", "versões do mito", "estudo "
                 "acadêmico", "arte sacra", "arqueologia"),
        must_distinguish=("tradição", "fonte textual", "interpretação moderna"),
    ),
    narrative=NarrativeStyle(
        direction="Estrutura: gancho, mundo, personagem ou entidade, conflito, "
                  "desenvolvimento, clímax, significado.",
        avoid="Não apresente reconstrução moderna como fato histórico."),
    visual=VisualStyle(
        scene_direction="Arte, escultura, pintura, objeto ritual, sítio "
                        "arqueológico, manuscrito, ilustração contextual.",
        preferred_forms=("spotlight", "quote", "definition"),
        media_hints=("ancient relief", "temple sculpture", "mythological "
                     "painting", "archaeological site", "medieval manuscript"),
        avoid="Não aplique efeito de terror a uma tradição que não é de "
              "terror, e não trate ilustração moderna como registro antigo "
              "sem dizer que é ilustração.",
    ),
    caption="Destaque o nome da entidade e da tradição; corte de 6 em 6.",
    ending="Feche no significado que a tradição carrega até hoje.",
    specialized_sources=("perseus", "logeion"),
    generic_media_queries=("church interior", "ancient sculpture", "old manuscript",
                           "museum hall", "temple", "painting"),
    media_provider_priority=("met", "aic", "wikimedia", "openverse"),
    visual_context_medium="painting",
    transition_duration=0.40, transition_kind="slideright",
    music_query="calm ancient ambient", music_mood="calm",
    pacing_note="Atmospheric, with rhythm changes.",
)

MYSTERY = GenreAdapter(
    key="mystery",
    label="Mistérios e casos não resolvidos",
    description="Um caso, suas evidências e o que continua sem resposta.",
    pacing=Pacing(target_scene_seconds=11.0, min_scene_seconds=4.0,
                  max_scene_seconds=19.0, information_density="medium",
                  max_scenes=14, caption_max_words=5, caption_highlight="keyword"),
    research=ResearchStyle(
        guidance="Separe rigorosamente fato documentado, testemunho, "
                 "alegação, hipótese, teoria e ponto não resolvido. Ausência "
                 "de evidência não é evidência.",
        queries=("caso não resolvido", "documento do caso", "investigação",
                 "arquivo policial", "cronologia", "testemunho",
                 "hipótese rejeitada"),
        must_distinguish=("fato documentado", "testemunho", "alegação",
                          "hipótese", "não confirmado"),
    ),
    narrative=NarrativeStyle(
        direction="Estrutura: o mistério, o contexto, os fatos estabelecidos, "
                  "as pistas, as contradições, as hipóteses existentes, o que "
                  "sabemos, o que continua sem resposta.",
        avoid="Não invente resolução e não apresente hipótese como fato."),
    visual=VisualStyle(
        scene_direction="Documento, mapa, fotografia do caso, local, linha "
                        "temporal, diagrama de evidência. Quando mostrar uma "
                        "hipótese, o visual tem de dizer que é hipótese.",
        preferred_forms=("contrast", "enumeration", "definition"),
        media_hints=("case file document", "evidence board", "timeline chart",
                     "archive map", "investigation photo"),
        avoid="Não use imagem que apresente hipótese como fato confirmado.",
        forbidden=("speculative reconstruction presented as fact",),
    ),
    caption="Destaque a palavra do status: fato, hipótese, não confirmado.",
    ending="Feche no que continua aberto, sem resolver por conveniência.",
    specialized_sources=("fbi_wanted",),
    generic_media_queries=("case file document", "evidence board", "archive map",
                           "investigation photo", "police archive"),
    transition_duration=0.38, transition_kind="wipeleft",
    music_query="calm investigative ambient", music_mood="calm",
    pacing_note="Controlled, with pauses before the reveal.",
)

SCIENCE = GenreAdapter(
    key="science",
    label="Ciência e descobertas",
    description="Fenômeno, mecanismo, evidência e o que muda com isso.",
    pacing=Pacing(target_scene_seconds=14.0, min_scene_seconds=6.0,
                  max_scene_seconds=26.0, information_density="medium",
                  max_scenes=9, caption_max_words=6, caption_highlight="keyword"),
    research=ResearchStyle(
        guidance="Priorize artigos, instituições científicas, documentação "
                 "técnica e fontes primárias. Busque o mecanismo, não a "
                 "curiosidade.",
        queries=("mecanismo", "artigo científico", "instituição de pesquisa",
                 "experimento", "medida", "hipótese científica"),
        must_distinguish=("evidência medida", "hipótese", "especulação"),
    ),
    narrative=NarrativeStyle(
        direction="Estrutura: fenômeno ou pergunta, o problema, a observação, "
                  "a descoberta, o mecanismo, a evidência, a implicação. "
                  "Abra pela consequência mais extrema e concreta do fenômeno "
                  "(a última coisa a existir no fim dos tempos), nunca por "
                  "definição de dicionário. Cada conceito estranho "
                  "(horizonte de eventos, singularidade) é explicado na hora, "
                  "em palavras simples, antes de seguir adiante. "
                  "Não acumule curiosidades sem montar o mecanismo.",
        avoid="Não acumule curiosidades sem montar o mecanismo. Não abra com "
              "definição nem deixe conceito estranho sem explicação imediata."),
    visual=VisualStyle(
        scene_direction="Diagrama, experimento, microscopia, gráfico, modelo, "
                        "animação explicativa, fotografia científica. Para "
                        "mecanismo, diagrama tem prioridade sobre foto.",
        preferred_forms=("enumeration", "definition", "contrast"),
        media_hints=("microscope image", "laboratory apparatus", "data chart",
                     "anatomy diagram", "scientific model"),
        avoid="Não faça do vídeo uma sequência de fotos de laboratório sem "
              "função explicativa.",
        ladder=("diagram", "literal", "conceptual"),
    ),
    caption="Destaque termos técnicos e medidas; corte de 6 em 6.",
    ending="Feche na implicação retomando a imagem do gancho já respondida "
           "(a era dos buracos negros responde a 'a última coisa a existir'), "
           "não em 'é muito importante'.",
    specialized_sources=("nasa", "pubmed"),
    generic_media_queries=("laboratory", "microscope", "science", "research",
                           "experiment", "test tube"),
    transition_duration=0.16, transition_kind="slideright",
    music_query="calm minimal ambient", music_mood="calm",
    pacing_note="Slow enough for the viewer to follow the mechanism.",
)

PEOPLE = GenreAdapter(
    key="people",
    label="História de pessoas",
    description="A trajetória de uma pessoa e por que a vida dela importa.",
    pacing=Pacing(target_scene_seconds=13.0, min_scene_seconds=4.0,
                  max_scene_seconds=28.0, information_density="medium",
                  max_scenes=10, caption_max_words=6, caption_highlight="keyword"),
    research=ResearchStyle(
        guidance="Resolva primeiro QUEM é a pessoa — nome ambíguo tem "
                 "homônimos, e a biografia de outro homônimo é um erro de "
                 "fonte, não de roteiro. Depois: origem, contexto, formação, "
                 "acontecimentos decisivos, relações, obras, conflitos, "
                 "mudanças documentadas, morte e legado. Para santos, "
                 "distinga tradição hagiográfica de evidência histórica sem "
                 "descartar o contexto religious.",
        queries=("biografia", "nascimento", "formação", "obras", "legado",
                 "cronologia", "hagiografia", "local da vida", "governo"),
        must_distinguish=("trajetória documentada", "tradição devocional",
                          "atribuição posterior"),
    ),
    narrative=NarrativeStyle(
        direction="Estrutura: gancho humano, quem era, o mundo em que "
               "viveu, a primeira transformação importante, o conflito ou "
               "desafio, a decisão ou obra central, as consequências, o "
               "legado. Adapte à pessoa: uma vida marcada por uma única "
               "descoberta pode concentrar o vídeo nela. Não empilhe "
               "cronologia seca. Quando a história envolver uma instituição "
               "estranha ao espectador (dois imperadores ao mesmo tempo, "
               "adoção como sucessão), explique na hora como funcionava: "
               "quem mandava no quê. Ancore o legado: a posição da pessoa "
               "na história (o último dos bons imperadores) é fato-âncora "
               "e nunca sai do roteiro.",
        avoid="Não reduza a vida a nascimento, estudo, casamento e morte, e "
              "não transforme biografia em hagiografia nem em propaganda. "
              "Não deixe instituição estranha sem explicação."),
    visual=VisualStyle(
        scene_direction="Retrato, pintura, fotografia, escultura, manuscrito, "
                        "lugar onde a pessoa viveu, objeto relacionado, obra "
                        "produzida, mapa da trajetória, documento. Para santos, "
                        "ícones, mosteiros, igrejas e relíquias documentadas "
                        "quando existirem. Em todo vídeo, as imagens precisam "
                        "continuar mostrando A PESSOA (retrato, busto, estátua) "
                        "em várias cenas, não só lugares e objetos: um vídeo "
                        "sobre Marco Aurélio sem o rosto de Marco Aurélio é "
                        "um vídeo errado.",
        preferred_forms=("spotlight", "definition", "enumeration", "quote"),
        media_hints=("portrait painting", "historic photograph", "sculpture",
                     "manuscript page", "monastery", "church interior",
                     "birthplace", "grave memorial"),
        avoid="Não repita a mesma imagem do rosto em cena após cena: "
              "biographical visual continuity é pessoa + época + lugar + obra.",
        forbidden=("modern studio portrait", "celebrity lookalike"),
        continuity=("This is a person's trajectory: across the video visuals "
                    "must move between the PERSON, ERA, PLACES and WORKS, "
                    "not repeat one portrait."),
    ),
    caption="Destaque nome, lugar e data; corte de 6 em 6.",
    ending="Feche no legado: o que da pessoa continua presente.",
    specialized_sources=("wikidata",),
    generic_media_queries=("church interior", "old library", "ancient manuscript",
                           "museum hall", "historic portrait", "monastery"),
    media_provider_priority=("met", "aic", "wikimedia", "openverse"),
    visual_context_medium="painting",
    transition_duration=0.34, transition_kind="slideright",
    music_query="violin classical ambient", music_mood="classical",
    pacing_note="Varied, with decisive moments allowed to breathe and routine "
                 "information compressed.",
)

GENRES: dict[str, GenreAdapter] = {
    p.key: p for p in (HISTORY, ETYMOLOGY, MYTHOLOGY, MYSTERY, SCIENCE, PEOPLE)
}

# Ordem de exibição na TUI: do mais cinematográfico ao mais conceitual.
GENRE_ORDER: tuple[str, ...] = tuple(GENRES)

# Perfil usado quando não há gênero escolhido. NÃO é um gênero: é a
# ausência dele, que preserva o comportamento anterior ao recurso.
DEFAULT_KEY = ""


def get(key: str | None) -> GenreAdapter | None:
    """Perfil do gênero, ou None quando nenhum foi escolhido.

    `None` é o modo compatível: com gênero vazio o pipeline não muda
    nenhuma linha de comportamento.
    """
    return GENRES.get((key or "").strip().lower())


def label(key: str | None) -> str:
    p = get(key)
    return p.label if p else "(padrão — sem gênero)"


def choices() -> list[tuple[str, str]]:
    """(key, label) na ordem de exibição, para o seletor da TUI."""
    return [(k, GENRES[k].label) for k in GENRE_ORDER]


# --- como o perfil fala com cada estágio -------------------------------
# Cada função devolve um bloco de texto PRONTO para injetar. Elas são o
# único ponto de contato entre o perfil e o resto do pipeline: se um dia
# um perfil novo precisar de outra influência, é aqui que entra, sem que
# o pipeline saiba que existe um segundo caminho.


def script_directive(profile: GenreAdapter | None) -> str:
    """Bloco de direção narrativa para o prompt do roteiro."""
    if profile is None:
        return ""
    partes = [f"EDITORIAL GENRE: {profile.label}. "
              f"This video must be recognisably this genre, not a generic "
              f"educational video with a different title."]
    if profile.narrative.direction:
        partes.append("NARRATIVE STRUCTURE — follow it: "
                      + profile.narrative.direction)
    if profile.narrative.avoid:
        partes.append("DO NOT: " + profile.narrative.avoid)
    partes.append(f"PACING: {profile.pacing.information_density} information "
                  f"density, roughly {profile.pacing.target_scene_seconds:g} "
                  f"seconds of narration per scene "
                  f"(between {profile.pacing.min_scene_seconds:g} and "
                  f"{profile.pacing.max_scene_seconds}). "
                  + profile.pacing_note)
    if profile.research.must_distinguish:
        partes.append("You MUST keep these separate in the narration and never "
                      "present one as another: "
                      + ", ".join(profile.research.must_distinguish) + ".")
    if profile.ending:
        partes.append("ENDING: " + profile.ending)
    if profile.caption:
        partes.append("CAPTIONS: " + profile.caption)
    return "\n".join(partes)


def scene_directive(profile: GenreAdapter | None) -> str:
    """Direção visual e de queries que entra no prompt das cenas."""
    if profile is None:
        return ""
    partes = [f"EDITORIAL GENRE: {profile.label}."]
    if profile.visual.scene_direction:
        partes.append("WHAT THE VISUAL MUST SHOW: "
                      + profile.visual.scene_direction)
    if profile.visual.media_hints:
        partes.append("SEARCH TERMS SHOULD RESEMBLE: "
                      + ", ".join(profile.visual.media_hints))
    if profile.visual.avoid:
        partes.append("AVOID IN THE VISUAL: " + profile.visual.avoid)
    if profile.visual.forbidden:
        partes.append("NEVER SHOW: " + ", ".join(profile.visual.forbidden)
                      + ".")
    if profile.visual.continuity:
        partes.append(profile.visual.continuity)
    if profile.visual.focus:
        partes.append(profile.visual.focus)
    return "\n".join(partes)


def summary(profile: GenreAdapter | None) -> dict:
    """Resumo do perfil para metadata e para o dry-run."""
    if profile is None:
        return {"key": "", "label": DEFAULT_KEY, "pacing": {},
                "visual": {}, "research": {}}
    return {
        "key": profile.key,
        "label": profile.label,
        "pacing": {
            "target_scene_seconds": profile.pacing.target_scene_seconds,
            "min_scene_seconds": profile.pacing.min_scene_seconds,
            "max_scene_seconds": profile.pacing.max_scene_seconds,
            "max_scenes": profile.pacing.max_scenes,
            "information_density": profile.pacing.information_density,
            "caption_max_words": profile.pacing.caption_max_words,
            "caption_highlight": profile.pacing.caption_highlight,
        },
        "visual": {
            "preferred_forms": list(profile.visual.preferred_forms),
            "media_hints": list(profile.visual.media_hints),
            "ladder": list(profile.visual.ladder),
            "continuity": profile.visual.continuity,
            "focus": profile.visual.focus,
            "generic_media_queries": list(profile.generic_media_queries),
            "media_provider_priority": list(profile.media_provider_priority),
        },
        "research": {
            "queries": list(profile.research.queries),
            "must_distinguish": list(profile.research.must_distinguish),
            "specialized_sources": list(profile.specialized_sources),
        },
        "audio": {"music_query": profile.music_query,
                  "music_mood": profile.music_mood,
                  "sfx_categories": list(profile.sfx_categories)},
        "transitions": {"duration": profile.transition_duration,
                        "kind": profile.transition_kind},
        "pacing_note": profile.pacing_note,
        "ending": profile.ending,
    }
