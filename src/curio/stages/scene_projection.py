"""Compatibility projection for persisted chapter rows.

`Chapter` is the storage/render row used by chapters.json. Semantic planning
lives in :mod:`scene_contract`; this adapter joins semantic meaning with timing
only at persistence and pipeline boundaries.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field

from .scene_contract import (
    VISUAL_TYPES, SemanticScene, TimelineSpan, VideoContext, VisualRepresentation,
)


@dataclass
class Chapter:
    id: int
    narration: str
    duration_estimate: float
    visual_queries: list[str] = field(default_factory=list)
    global_visual_queries: list[str] = field(default_factory=list)
    visual_intent: str = ""
    planning_mode: str = "unknown"
    # --- vocabulário visual (retrocompatível: tudo opcional) ------------
    # `visual_type` informa o tipo de cena; `visual_steps` declara uma
    # sequência que pode virar diagrama. `visual_entities`/`context` dão
    # conceitos, nunca passos ordenados. `forbidden` é a
    # lista de falsos positivos observados para o tema (ex.: "térmico"
    # puxando usina termelétrica). Tudo com default para que um
    # chapters.json antigo continue carregando sem erro.
    visual_type: str = "literal"
    subject: str = ""
    subject_aliases: list[str] = field(default_factory=list)
    visual_entities: list[str] = field(default_factory=list)
    visual_steps: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    # Shared video context and explicit director output. Optional for old
    # chapters.json files; queries are generated from representations first.
    video_context: VideoContext = field(default_factory=VideoContext)
    visual_intent_structured: str = ""
    primary_entity: str = ""
    event: str = ""
    place: str = ""
    period: str = ""
    representations: list[VisualRepresentation] = field(default_factory=list)
    representation_rejections: list[dict] = field(default_factory=list)
    # --- papel tipográfico (retrocompatível: tudo opcional) -------------
    # A cena declara a FUNÇÃO do texto, nunca a fonte: `text_role="quote"`
    # significa "isto é uma citação", e quem decide que em `people` citação
    # é itálico serifado é o perfil, em stages/typography.py. Pedir a fonte
    # aqui quebraria a abstração no instante em que o gênero muda, e trocar
    # de gênero é justamente o que precisa ser barato.
    # Vazio = a cena nao reservou papel; o papel vem da derivacao por conteudo.
    text_role: str = ""
    # "la" quando o texto é latim. O papel `latin` é o que entrega o
    # itálico editorial para a frase em latim, e é o caso que a direção de
    # arte do projeto cita primeiro.
    text_language: str = ""
    start: float = 0.0
    end: float = 0.0

    def __post_init__(self) -> None:
        self.video_context = VideoContext.from_value(self.video_context)
        if self.planning_mode not in {"unknown", "llm", "deterministic"}:
            raise ValueError(f"unknown scene planning_mode: {self.planning_mode}")
        representations = [
            rep for index, value in enumerate(self.representations)
            if (rep := VisualRepresentation.from_value(value, index))]
        known = {rep.query.casefold() for rep in representations}
        queries = self.visual_queries
        if isinstance(queries, str):
            queries = [queries]
        for query in queries or []:
            query = str(query).strip()
            if query and query.casefold() not in known:
                representations.append(VisualRepresentation(
                    query=query, kind="related", level=len(representations),
                    source="declared_scene_query"))
                known.add(query.casefold())
        self.representations = representations
        self.visual_queries = [rep.query for rep in representations]

    def set_visual_queries(self, queries, *, source: str,
                           kind: str = "related", level: int = 0) -> None:
        """Add declared visual anchors and refresh the legacy query mirror."""
        if isinstance(queries, str):
            queries = [queries]
        existing = {rep.query.casefold(): rep for rep in self.representations}
        ordered: list[VisualRepresentation] = []
        seen: set[str] = set()
        for raw in queries or []:
            query = str(raw).strip()
            key = query.casefold()
            if not query or key in seen:
                continue
            seen.add(key)
            rep = existing.get(key)
            ordered.append(rep or VisualRepresentation(
                query=query, kind=kind, level=level, source=source))
        for rep in self.representations:
            if rep.query.casefold() not in seen:
                seen.add(rep.query.casefold())
                ordered.append(rep)
        self.representations = ordered
        self.visual_queries = [rep.query for rep in ordered]

    def to_dict(self) -> dict:
        result = asdict(self)
        result["video_context"] = self.video_context.to_dict()
        result["representations"] = [rep.to_dict() for rep in self.representations]
        result["visual_queries"] = [rep.query for rep in self.representations]
        return result

    def contract_errors(self) -> list[str]:
        """Return structural violations in the persisted compatibility row."""
        errors = []
        if not isinstance(self.narration, str) or not self.narration.strip():
            errors.append("narration_required")
        if self.visual_type not in VISUAL_TYPES:
            errors.append("visual_type_unknown")
        if not isinstance(self.video_context, VideoContext):
            errors.append("video_context_not_normalized")
        if any(not isinstance(rep, VisualRepresentation) for rep in self.representations):
            errors.append("representation_not_normalized")
        return errors

    def require_valid(self) -> "Chapter":
        errors = self.contract_errors()
        if errors:
            raise ValueError(f"scene {self.id} violates contract: {', '.join(errors)}")
        return self

    def semantic_scene(self, source: str = "unknown") -> SemanticScene:
        """Expose meaning downstream without carrying duration or timestamps."""
        representations = tuple(
            rep for index, value in enumerate(self.representations)
            if (rep := VisualRepresentation.from_value(value, index)))
        return SemanticScene(
            id=int(self.id), narration=str(self.narration), source=source,
            planning_mode=self.planning_mode, visual_type=self.visual_type,
            subject=self.subject, subject_aliases=tuple(self.subject_aliases),
            visual_entities=tuple(self.visual_entities),
            visual_steps=tuple(self.visual_steps), context=tuple(self.context),
            forbidden=tuple(self.forbidden),
            video_context=deepcopy(self.video_context),
            visual_intent=self.visual_intent,
            visual_intent_structured=self.visual_intent_structured,
            primary_entity=self.primary_entity, event=self.event,
            place=self.place, period=self.period, text_role=self.text_role,
            text_language=self.text_language,
            representations=representations,
            global_visual_queries=tuple(self.global_visual_queries),
            representation_rejections=tuple(self.representation_rejections),
        )

    def timeline_span(self) -> TimelineSpan:
        """Project only timing into the timeline-owned contract."""
        return TimelineSpan(self.id, self.duration_estimate, self.start, self.end)

    @classmethod
    def from_semantic_scene(cls, scene: SemanticScene, *,
                            timing: TimelineSpan | None = None) -> "Chapter":
        """Project semantic meaning into the timeline/render compatibility row."""
        if timing is not None and timing.scene_id != scene.id:
            raise ValueError("timeline span does not match semantic scene id")
        timing = timing or TimelineSpan(scene.id)
        return cls(
            id=scene.id, narration=scene.narration,
            duration_estimate=timing.duration_estimate,
            start=timing.start, end=timing.end,
            planning_mode=scene.planning_mode, visual_type=scene.visual_type,
            subject=scene.subject, subject_aliases=list(scene.subject_aliases),
            visual_entities=list(scene.visual_entities), context=list(scene.context),
            visual_steps=list(scene.visual_steps),
            forbidden=list(scene.forbidden), video_context=scene.video_context,
            visual_intent=scene.visual_intent,
            visual_intent_structured=scene.visual_intent_structured,
            primary_entity=scene.primary_entity, event=scene.event,
            place=scene.place, period=scene.period,
            representations=list(scene.representations),
            visual_queries=[rep.query for rep in scene.representations],
            global_visual_queries=list(scene.global_visual_queries),
            representation_rejections=list(scene.representation_rejections),
            text_role=scene.text_role, text_language=scene.text_language)

    @classmethod
    def from_dict(cls, d: dict) -> "Chapter":
        from .scene_representations import (
            _coerce_representations, _rejected_representations,
            _validate_query_list,
        )
        from .scene_visual_type import classify_visual_type
        vtype = str(d.get("visual_type", "") or "").strip().lower()
        narration = str(d.get("narration", ""))
        if vtype not in VISUAL_TYPES:
            # chapters.json antigo (sem o campo) ou IA fora do formato:
            # deriva o texto em vez de assumir "literal" às cegas.
            vtype = classify_visual_type(narration) if vtype == "" else "literal"
        from .typography import ROLES
        visual_queries, visual_query_rejections = _validate_query_list(
            d.get("visual_queries", []))
        global_queries, global_query_rejections = _validate_query_list(
            d.get("global_visual_queries", []))
        papel = str(d.get("text_role", "") or "").strip().lower()
        if papel not in ROLES:
            # chapters.json antigo não tem o campo, e a IA às vezes inventa
            # um papel. Papel desconhecido é descartado, e a derivação pelo
            # conteúdo assume — um papel errado renderiza o texto na fonte
            # errada sem nenhuma pista de por quê.
            papel = ""
        planning_mode = str(d.get("planning_mode", "") or "")
        if not planning_mode:
            # Temporary compatibility for chapters written before the field
            # existed; all current producers set the explicit provenance.
            planning_mode = ("deterministic"
                             if str(d.get("visual_intent", "")).startswith(
                                 "local fallback") else "unknown")
        return cls(
            id=int(d.get("id", 0)),
            narration=narration,
            duration_estimate=float(d.get("duration_estimate", 0)),
            visual_queries=visual_queries,
            global_visual_queries=global_queries,
            visual_intent=str(d.get("visual_intent", "")),
            planning_mode=planning_mode,
            visual_type=vtype,
            subject=str(d.get("subject", "") or ""),
            subject_aliases=[str(q) for q in d.get("subject_aliases", [])],
            visual_entities=[str(q) for q in d.get("visual_entities", [])],
            visual_steps=[str(q) for q in d.get("visual_steps", [])],
            context=[str(q) for q in d.get("context", [])],
            forbidden=[str(q) for q in d.get("forbidden", [])],
            video_context=VideoContext.from_value(d.get("video_context", {})),
            visual_intent_structured=str(d.get("visual_intent_structured", "") or ""),
            primary_entity=str(d.get("primary_entity", "") or ""),
            event=str(d.get("event", "") or ""),
            place=str(d.get("place", "") or ""),
            period=str(d.get("period", "") or ""),
            representations=_coerce_representations(d.get("representations", [])),
            representation_rejections=(
                list(d.get("representation_rejections", []) or [])[:20]
                + _rejected_representations(d.get("representations", []))
                + visual_query_rejections + global_query_rejections),
            text_role=papel,
            text_language=str(d.get("text_language", "") or "").strip().lower(),
            start=float(d.get("start", 0.0)),
            end=float(d.get("end", 0.0)),
        )
