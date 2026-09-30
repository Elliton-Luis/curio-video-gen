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
import os

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


def scene_rows(chapters, media_scenes: list[dict], base: str) -> list[dict]:
    """Junta capítulo + mídia + rejeições numa linha por cena."""
    by_scene = {s["chapter_id"]: s for s in media_scenes or []}
    rows = []
    for ch in chapters:
        scene = by_scene.get(ch.id, {})
        assets = list(scene.get("assets") or [])
        chosen = []
        for entry in assets:
            asset = entry.get("asset") or {}
            if not asset.get("local_path"):
                continue
            chosen.append({
                "path": asset["local_path"],
                "rel": _rel(asset["local_path"], base),
                "title": asset.get("title", ""),
                "provider": asset.get("provider", ""),
                "author": asset.get("author", ""),
                "license": asset.get("license", "") or "desconhecida",
                "license_url": asset.get("license_url", ""),
                "score": entry.get("score"),
                "query": entry.get("query", ""),
                "order": entry.get("order", 0),
                "strategy": entry.get("strategy", "image"),
            })
        rows.append({
            "id": ch.id,
            "narration": ch.narration,
            "visual_type": getattr(ch, "visual_type", "literal"),
            "subject": getattr(ch, "subject", ""),
            "entities": list(getattr(ch, "visual_entities", []) or []),
            "forbidden": list(getattr(ch, "forbidden", []) or []),
            "queries": list(getattr(ch, "visual_queries", []) or []),
            "chosen": chosen,
            "rejected": list(scene.get("rejected") or [])[:REJECTED_SHOWN],
            "rejected_total": len(scene.get("rejected") or []),
            "reused_from": scene.get("reused_from"),
            "no_insertion": scene.get("no_insertion", ""),
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


def write_contact_sheet(out_path: str, chapters, media_scenes: list[dict],
                        root: str, slug: str = "", threshold: float = 0.0,
                        layers: list[str] | None = None,
                        genre: str = "") -> str:
    """Gera `review/contact_sheet.html` — uma linha por cena."""
    base = os.path.dirname(os.path.abspath(out_path))
    rows = scene_rows(chapters, media_scenes, base)
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
    parts = [f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revisão — {html.escape(slug or "projeto")}</title><style>{css}</style>
</head><body>
<header><h1>Revisão visual — {html.escape(slug or "projeto")}</h1>
{linha_genero}
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

def dry_run_text(chapters, media_scenes: list[dict], threshold: float = 0.0,
                 layers: list[str] | None = None, clip_device: str = "",
                 genre: str = "") -> str:
    """Relatório de texto da decisão, por cena. Sem HTML, sem download."""
    layers = layers or ["base"]
    out: list[str] = []
    g = genre_banner(genre)
    if g:
        out.append(f"Gênero: {g}")
    for r in scene_rows(chapters, media_scenes, "."):
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
