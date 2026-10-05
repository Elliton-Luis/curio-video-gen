"""Revisão humana: folha de contato e dry-run.

Duas saídas, um objetivo: o autor precisa ver, em ~1 minuto, o que cada
cena recebeu, por quê, e o que foi descartado. Sem isso, "a cena ficou sem
foto" e "a cena recebeu a imagem errada" são indistinguíveis.

A folha de contato é HTML estático de propósito: um arquivo, sem
servidor, sem JavaScript de aplicação. Abre com duplo clique e mostra,
por cena, o texto, o visual final, a nota, o provedor, a licença e os
motivos das principais rejeições.

O dry-run responde a pergunta que ninguém consegue responder de outro
jeito: "por que essa imagem entrou?". Ele imprime a decisão por cena sem
baixar o arquivo final e sem renderizar.
"""

from __future__ import annotations

import html
import math
import os
from dataclasses import dataclass

from ..media.selection_result import MediaStageResult
from .scene_contract import SemanticScene

# Quantas rejeições mostrar por cena. Mais que isso vira mural e esconde o
# que importa; o relatório completo continua no media.json.
REJECTED_SHOWN = 4

_TYPE_LABEL = {
    "literal": "literal",
    "mechanism": "mecanismo",
    "historical_art": "arte histórica",
    "conceptual": "conceitual",
    "typographic": "tipográfico",
}

_STRATEGY_LABEL = {
    "image": "fotografia",
    "art": "arte de domínio público",
    "card": "cartão tipográfico",
    "diagram": "diagrama",
}


@dataclass(frozen=True)
class ReviewAsset:
    path: str
    title: str
    provider: str
    author: str
    license: str
    license_url: str
    score: float | int | None
    query: str
    order: int
    strategy: str

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) for value in (
                self.path, self.title, self.provider, self.author, self.license,
                self.license_url, self.query, self.strategy)):
            raise TypeError("review asset text fields must be strings")
        if self.score is not None and (
                isinstance(self.score, bool)
                or not isinstance(self.score, (int, float))
                or not math.isfinite(self.score)):
            raise ValueError("review asset score must be finite or null")
        if isinstance(self.order, bool) or not isinstance(self.order, int) \
                or self.order < 0:
            raise ValueError("review asset order must be non-negative")


@dataclass(frozen=True)
class ReviewSceneMedia:
    scene_id: int
    chosen: tuple[ReviewAsset, ...]
    rejected: tuple[dict, ...]
    reused_from: int | None
    no_insertion: str

    def __post_init__(self) -> None:
        if isinstance(self.scene_id, bool) or not isinstance(self.scene_id, int) \
                or self.scene_id <= 0:
            raise ValueError("review scene id must be positive")
        if not isinstance(self.chosen, tuple) or any(
                not isinstance(asset, ReviewAsset) for asset in self.chosen):
            raise TypeError("review scene chosen assets must be typed values")
        if not isinstance(self.rejected, tuple) or any(
                not isinstance(item, dict) for item in self.rejected):
            raise TypeError("review scene rejections must be objects")
        if self.reused_from is not None and (
                isinstance(self.reused_from, bool)
                or not isinstance(self.reused_from, int)
                or self.reused_from <= 0):
            raise ValueError("review reuse donor must be positive")
        if not isinstance(self.no_insertion, str):
            raise TypeError("review no_insertion reason must be a string")


@dataclass(frozen=True)
class ReviewMediaPlan:
    scenes: tuple[ReviewSceneMedia, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scenes, tuple) or any(
                not isinstance(scene, ReviewSceneMedia) for scene in self.scenes):
            raise TypeError("review media requires ReviewSceneMedia values")
        ids = tuple(scene.scene_id for scene in self.scenes)
        if len(ids) != len(set(ids)):
            raise ValueError("review media scene ids must be unique")

    @classmethod
    def from_media_result(cls, result: MediaStageResult) -> "ReviewMediaPlan":
        if not isinstance(result, MediaStageResult):
            raise TypeError("review requires a MediaStageResult")
        return cls(tuple(ReviewSceneMedia(
            scene.scene_id,
            tuple(ReviewAsset(
                entry.asset.local_path, entry.asset.title, entry.asset.provider,
                entry.asset.author,
                entry.asset.license or "desconhecida",
                entry.asset.license_url, entry.score, entry.query, entry.order,
                entry.strategy or "image")
                  for entry in scene.assets),
            scene.rejected, scene.reused_from, "")
            for scene in result.scenes))

    @classmethod
    def from_persisted_rows(cls, rows: object) -> "ReviewMediaPlan":
        """Adapt the persisted project format while allowing older asset metadata."""
        if not isinstance(rows, list):
            raise TypeError("persisted review media must be a list")
        return cls(tuple(_review_scene_from_selection(row) for row in rows))


def _review_scene_from_selection(row: object) -> ReviewSceneMedia:
    if not isinstance(row, dict):
        raise TypeError("review media scene must be an object")
    scene_id = row.get("chapter_id")
    if isinstance(scene_id, bool) or not isinstance(scene_id, int) or scene_id <= 0:
        raise ValueError("review scene id must be a positive integer")
    entries = row.get("assets", [])
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise TypeError("review assets must be a list")
    chosen = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("review asset entry must be an object")
        asset = entry.get("asset") or {}
        if not isinstance(asset, dict):
            raise TypeError("review asset metadata must be an object")
        path = asset.get("local_path", "") or ""
        if not isinstance(path, str):
            raise TypeError("review asset path must be a string")
        score = entry.get("score")
        if score is not None and (isinstance(score, bool)
                                  or not isinstance(score, (int, float))):
            raise TypeError("review asset score must be numeric or null")
        order = entry.get("order", 0)
        if isinstance(order, bool) or not isinstance(order, int) or order < 0:
            raise ValueError("review asset order must be non-negative")
        text_fields = {
            "title": asset.get("title", "") or "",
            "provider": asset.get("provider", "") or "",
            "author": asset.get("author", "") or "",
            "license": asset.get("license", "") or "desconhecida",
            "license_url": asset.get("license_url", "") or "",
            "query": entry.get("query", "") or "",
            "strategy": entry.get("strategy", "image") or "image",
        }
        if any(not isinstance(value, str) for value in text_fields.values()):
            raise TypeError("review asset display fields must be strings")
        chosen.append(ReviewAsset(path, text_fields["title"],
                                  text_fields["provider"], text_fields["author"],
                                  text_fields["license"], text_fields["license_url"],
                                  score, text_fields["query"], order,
                                  text_fields["strategy"]))
    rejected = row.get("rejected", [])
    if rejected is None:
        rejected = []
    if not isinstance(rejected, list) or any(not isinstance(item, dict)
                                             for item in rejected):
        raise TypeError("review rejections must be a list of objects")
    reused_from = row.get("reused_from")
    if reused_from is not None and (isinstance(reused_from, bool)
                                    or not isinstance(reused_from, int)
                                    or reused_from <= 0):
        raise ValueError("review reuse donor must be a positive scene id")
    no_insertion = row.get("no_insertion", "") or ""
    if not isinstance(no_insertion, str):
        raise TypeError("review no_insertion reason must be a string")
    return ReviewSceneMedia(scene_id, tuple(chosen), tuple(rejected),
                            reused_from, no_insertion)


def _rel(path: str, base: str) -> str:
    """Caminho relativo ao DIRECTÓRIO DA FOLHA, não ao projeto.

    A folha vive em `review/`, as imagens em `media/`. Relativo ao projeto
    (`media/img0.png`) o navegador resolveria a partir de `review/` e
    mostraria imagem quebrada. Tem de ser `../media/img0.png`.
    """
    if not path:
        return ""
    try:
        return os.path.relpath(os.path.abspath(path), os.path.abspath(base))
    except ValueError:
        return path


def _score_badge(score) -> str:
    try:
        val = float(score)
    except (TypeError, ValueError):
        return '<span class="s na">—</span>'
    if val >= 60:
        cls = "hi"
    elif val >= 34:
        cls = "mid"
    else:
        cls = "lo"
    return f'<span class="s {cls}">{val:.0f}</span>'


def scene_rows(semantic_scenes: tuple[SemanticScene, ...],
               media_plan: ReviewMediaPlan, base: str) -> list[dict]:
    """Junta semântica + mídia + rejeições numa linha por cena."""
    if any(not isinstance(scene, SemanticScene) for scene in semantic_scenes):
        raise TypeError("review requires SemanticScene values")
    if not isinstance(media_plan, ReviewMediaPlan):
        raise TypeError("review requires a ReviewMediaPlan")
    scene_ids = tuple(scene.id for scene in semantic_scenes)
    if not scene_ids or len(scene_ids) != len(set(scene_ids)):
        raise ValueError("review requires unique semantic scenes")
    by_scene = {scene.scene_id: scene for scene in media_plan.scenes}
    rows = []
    for semantic_scene in semantic_scenes:
        scene = by_scene.get(semantic_scene.id)
        chosen = []
        for asset in scene.chosen if scene else ():
            if not asset.path:
                continue
            chosen.append({
                "path": asset.path,
                "rel": _rel(asset.path, base),
                "title": asset.title,
                "provider": asset.provider,
                "author": asset.author,
                "license": asset.license,
                "license_url": asset.license_url,
                "score": asset.score,
                "query": asset.query,
                "order": asset.order,
                "strategy": asset.strategy,
            })
        rows.append({
            "id": semantic_scene.id,
            "narration": semantic_scene.narration,
            "visual_type": semantic_scene.visual_type,
            "subject": semantic_scene.subject,
            "entities": list(semantic_scene.visual_entities),
            "forbidden": list(semantic_scene.forbidden),
            "queries": [rep.query for rep in semantic_scene.representations],
            "chosen": chosen,
            "rejected": list(scene.rejected[:REJECTED_SHOWN]) if scene else [],
            "rejected_total": len(scene.rejected) if scene else 0,
            "reused_from": scene.reused_from if scene else None,
            "no_insertion": scene.no_insertion if scene else "",
        })
    return rows


def genre_banner(genre: str = "") -> str:
    """Linha do gênero para a revisão. Vazia sem gênero — sem ruído.

    A folha de contato e o dry-run são onde se decide se o vídeo ficou
    bom; o pacing e a densidade de legenda precisam aparecer ali, e não
    só no metadata.json, porque a diferença entre duas categorias é
    justamente o número de cortes e o tamanho da legenda.
    """
    from . import editorial as _editorial
    perfil = _editorial.get(genre or "")
    if perfil is None:
        return ""
    p = perfil.pacing
    return (f"{perfil.label} — {p.target_scene_seconds:g}s/cena, até "
            f"{p.max_scenes} cenas, legenda {p.caption_max_words} palavras, "
            f"destaque {p.caption_highlight}")


def typography_banner(genre: str = "", overrides: dict | None = None) -> str:
    """A tipografia que este vídeo vai usar, por papel. Vazia sem gênero.

    A folha de contato é onde o autor decide se o vídeo ficou bom, e a
    tipografia é exatamente o que não se julga vendo a miniatura: uma
    citação em itálico serifado e a mesma frase em sans pesada são a mesma
    frase. O relatório diz também o que RESPONDEU, que é a informação que
    o metadata esconde de quem não abre o JSON.
    """
    from . import typography as _typo
    if not _typo.profile_for(genre or "").key:
        return ""
    linhas = []
    for papel, nome in ((_typo.ROLE_TITLE, "título"),
                        (_typo.ROLE_QUOTE, "citação"),
                        (_typo.ROLE_CAPTION, "legenda")):
        r = _typo.resolve(papel, genre, overrides)
        if papel in _typo.LEGIBILITY_ROLES:
            familia, _b, _p = _typo.for_genre(genre, overrides).ass(papel)
        else:
            familia = r.family + (" itálico" if r.italic else "")
        marca = "" if not r.is_fallback else f" (pediu {r.requested})"
        linhas.append(f"{nome}: {familia}{marca}")
    return " · ".join(linhas)


def _typography_from_report(report: dict | None) -> str:
    """Lê a tipografia já gravada no metadata.json. Vazia se não houver."""
    if not isinstance(report, dict):
        return ""
    papeis = report.get("roles")
    if not isinstance(papeis, dict):
        return ""
    partes = []
    for papel, nome in (("title", "título"), ("quote", "citação"),
                        ("caption", "legenda")):
        r = papeis.get(papel) or {}
        if not r.get("family"):
            continue
        partes.append(f"{nome}: {r['family']}"
                      + (" itálico" if r.get("italic") else ""))
    return " · ".join(partes)


def write_contact_sheet(out_path: str,
                        semantic_scenes: tuple[SemanticScene, ...],
                        media_plan: ReviewMediaPlan,
                        root: str, slug: str = "", threshold: float = 0.0,
                        layers: list[str] | None = None,
                        genre: str = "",
                        typography: dict | None = None) -> str:
    """Gera `review/contact_sheet.html` — uma linha por cena."""
    base = os.path.dirname(os.path.abspath(out_path))
    rows = scene_rows(semantic_scenes, media_plan, base)
    layers = layers or ["base"]
    sem_foto = [r for r in rows if not r["chosen"]]
    geradas = [r for r in rows
               if r["chosen"] and r["chosen"][0]["provider"] == "synth"]

    css = """
    :root{--bg:#0f1117;--card:#181c26;--line:#2a3040;--ink:#eef1f7;
          --soft:#9aa4bb;--hi:#5ad18a;--mid:#f0c04a;--lo:#e8735a;--acc:#56b6ff}
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--ink);
         font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
    header{padding:20px 28px;border-bottom:1px solid var(--line);
           position:sticky;top:0;background:var(--bg);z-index:2}
    h1{margin:0 0 6px;font-size:20px}
    .genre{color:var(--acc);font-size:13px;margin:0 0 6px}
    .genre+.genre{color:var(--soft);font-weight:400}
    .sum{color:var(--soft);font-size:13px}
    .sum b{color:var(--ink)}
    main{padding:20px 28px 60px;display:grid;gap:16px;max-width:1180px}
    .sc{background:var(--card);border:1px solid var(--line);border-radius:12px;
        padding:16px 18px;display:grid;grid-template-columns:150px 1fr;gap:18px}
    .shot{width:150px;border-radius:8px;overflow:hidden;background:#0a0c11;
          aspect-ratio:9/16;display:flex;align-items:center;justify-content:center;
          border:1px solid var(--line)}
    .shot img{width:100%;height:100%;object-fit:cover;display:block}
    .none{color:var(--lo);font-size:12px;text-align:center;padding:8px}
    h2{margin:0 0 8px;font-size:15px;display:flex;gap:10px;align-items:center;
       flex-wrap:wrap}
    .tag{font-size:11px;padding:2px 8px;border-radius:999px;
         background:#222839;color:var(--soft);border:1px solid var(--line)}
    .tag.t{background:#1b2a3f;color:var(--acc);border-color:#2b4363}
    .nar{color:#cdd5e6;margin:0 0 10px}
    dl{margin:0;display:grid;grid-template-columns:96px 1fr;gap:3px 12px;
        font-size:13px}
    dt{color:var(--soft)}
    dd{margin:0;color:#dfe5f2}
    .s{font-weight:700;padding:1px 7px;border-radius:5px}
    .s.hi{color:var(--hi)}.s.mid{color:var(--mid)}.s.lo{color:var(--lo)}
    .s.na{color:var(--soft)}
    ul.rej{margin:8px 0 0;padding-left:18px;font-size:12.5px;color:#b9c2d6}
    ul.rej li{margin:2px 0}
    ul.rej b{color:var(--lo);font-weight:600}
    .lic{font-size:12px;color:var(--soft);margin-top:4px}
    a{color:var(--acc)}
    .warn{color:var(--mid)}
    """

    g = genre_banner(genre)
    linha_genero = (f'<div class="genre">{html.escape(g)}</div>' if g else "")
    # A folha prefere o que está GRAVADO no metadata: é o que o vídeo
    # realmente usou. Divergir entre o gravado e o resolvido agora é
    # sinal de que o vídeo foi montado com outra fonte, e esconder isso
    # na revisão seria o pior lugar para esconder.
    ty = _typography_from_report(typography)
    if not ty:
        ty = typography_banner(genre)
    linha_typo = (f'<div class="genre">{html.escape(ty)}</div>' if ty else "")
    parts = [f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revisão — {html.escape(slug or "projeto")}</title><style>{css}</style>
</head><body>
<header><h1>Revisão visual — {html.escape(slug or "projeto")}</h1>
{linha_genero}{linha_typo}
<div class="sum">{len(rows)} cena(s) · <b>{len(rows) - len(sem_foto)}</b> com
visual · <b>{len(geradas)}</b> geradas por código
· mínimo de nota {threshold:.0f} · camadas: {html.escape(", ".join(layers))}
· {len(sem_foto)} cena(s) sem visual</div></header><main>"""]

    for r in rows:
        shots = []
        for c in r["chosen"][:2]:
            tag = ('<span class="tag t">'
                   f'{html.escape(_STRATEGY_LABEL.get(c["strategy"], c["strategy"]))}'
                   '</span>')
            shots.append(f"""
<div class="shot"><img src="{html.escape(c['rel'])}" alt="{html.escape(c['title'])}"
 loading="lazy"></div>
<dl><dt>nota</dt><dd>{_score_badge(c['score'])}</dd>
<dt>provedor</dt><dd>{html.escape(c['provider'] or '—')}</dd>
<dt>consulta</dt><dd>{html.escape(c['query'] or '—')}</dd>
<dt>arquivo</dt><dd>{html.escape(c['title'][:80])}</dd>
<dt>licença</dt><dd>{tag}</dd></dl>
<div class="lic">{html.escape(c['license'])}
{f' · {html.escape(c["author"])}' if c['author'] else ''}
{f' · <a href="{html.escape(c["license_url"])}">conferir</a>' if c['license_url'] else ''}
</div>""")
        if not shots:
            shots.append('<div class="shot"><div class="none">sem visual</div></div>')

        rej = ""
        if r["rejected"]:
            itens = "".join(
                f"<li><b>{html.escape(str(x.get('reason', 'motivo')))}</b> — "
                f"{html.escape(str(x.get('title', ''))[:70])}</li>"
                for x in r["rejected"])
            extra = (f" (+{r['rejected_total'] - len(r['rejected'])} outras)"
                     if r["rejected_total"] > len(r["rejected"]) else "")
            rej = f'<ul class="rej">{itens}{extra}</ul>'

        notas = []
        if r["forbidden"]:
            notas.append(f"proibidos: {', '.join(r['forbidden'])}")
        if r["no_insertion"]:
            notas.append(f'<span class="warn">{html.escape(str(r["no_insertion"]))}</span>')
        if r["reused_from"]:
            notas.append(f"reusa imagem da cena {r['reused_from']}")
        extra_notas = f'<div class="lic">{" · ".join(notas)}</div>' if notas else ""

        partes = f"""
<section class="sc">
{''.join(shots)}
<div>
<h2>Cena {r['id']}
<span class="tag t">{html.escape(_TYPE_LABEL.get(r['visual_type'], r['visual_type']))}</span>
{('<span class="tag">assunto: ' + html.escape(r['subject']) + '</span>') if r['subject'] else ''}
</h2>
<p class="nar">{html.escape(r['narration'][:300])}</p>
<dl><dt>consultas</dt><dd>{html.escape(", ".join(r['queries']) or '—')}</dd>
<dt>entidades</dt><dd>{html.escape(", ".join(r['entities']) or '—')}</dd></dl>
{extra_notas}{rej}
</div></section>"""
        parts.append(partes)

    parts.append("</main></body></html>")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("".join(parts))
    return out_path


# --- dry-run -----------------------------------------------------------

def dry_run_text(semantic_scenes: tuple[SemanticScene, ...],
                 media_plan: ReviewMediaPlan, threshold: float = 0.0,
                 layers: list[str] | None = None, clip_device: str = "",
                 genre: str = "",
                 typography: dict | None = None) -> str:
    """Relatório de texto da decisão, por cena. Sem HTML, sem download."""
    layers = layers or ["base"]
    out: list[str] = []
    g = genre_banner(genre)
    if g:
        out.append(f"Gênero: {g}")
    ty = _typography_from_report(typography) or typography_banner(genre)
    if ty:
        out.append(f"Tipografia: {ty}")
    for r in scene_rows(semantic_scenes, media_plan, "."):
        out.append(f"\nCena {r['id']}  [{r['visual_type']}]")
        out.append(f"  texto      : {r['narration'][:150]}")
        if r["subject"]:
            out.append(f"  assunto    : {r['subject']}")
        if r["entities"]:
            out.append(f"  a mostrar  : {', '.join(r['entities'])}")
        if r["queries"]:
            out.append(f"  consultas  : {', '.join(r['queries'])}")
        if r["forbidden"]:
            out.append(f"  proibidos  : {', '.join(r['forbidden'])}")
        if r["chosen"]:
            c = r["chosen"][0]
            out.append(f" chosen  : {c['strategy']} — {c['title'][:70]}")
            out.append(f"  nota       : {c['score']} (mínimo {threshold:.0f})")
            out.append(f"  provedor   : {c['provider']} | {c['license']}")
        else:
            out.append("  escolhido  : NENHUM")
        esc = " + ".join(layers)
        if clip_device:
            esc += f" (dispositivo: {clip_device})"
        out.append(f"  scoring    : {esc}")
        for x in r["rejected"]:
            out.append(f"  descartado : {x.get('reason', '')} — "
                       f"{str(x.get('title', ''))[:60]}")
        if r["rejected_total"] > len(r["rejected"]):
            out.append(f"  (+{r['rejected_total'] - len(r['rejected'])} "
                       f"descartados não listados)")
    return "\n".join(out)
