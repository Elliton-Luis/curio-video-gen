"""Orquestração do pipeline (PRD §4, §15, §16, §19).

Fluxo A (narração IA): roteiro → cenas → mídia → narração → legendas → montagem.
Fluxo B (narração humana): roteiro → cenas → mídia → timeline → silencioso
→ teleprompter; depois `finalize_project` com o áudio humano.
Tudo cacheável por artefato; cena sem mídia reusa a mais próxima, mas
ZERO imagens no vídeo = standby (MediaStandby): o usuário deposita fotos
em `assets/manual/` e roda o generate de novo para continuar.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from . import ffmpeg as ff
from .config import CurioConfig
from .media import download_asset, get_providers
from .media.providers import MediaAsset, MediaError, classify_rights
from .metrics import RunMetrics, backfill_from_metadata
from .slug import slugify, slugify_with_timestamp
from .stages import render as render_stage
from .stages import nvidia as nvidia_stage
from .stages import research as research_stage
from .stages import scenes as scenes_stage
from .stages import scoring as scoring_stage
from .stages import script as script_stage
from .stages import subs as subs_stage
from .stages import teleprompter as tele_stage
from .stages import transcribe as transcribe_stage
from .stages import tts as tts_stage
from .stages import sources as sources_stage
from .stages import visual as visual_stage
from .stages.scenes import Chapter

STAGES_AI = ["roteiro", "cenas", "mídia", "narração", "legendas", "montagem"]
STAGES_HUMAN = ["roteiro", "cenas", "mídia", "timeline", "silencioso",
                "teleprompter"]


@dataclass
class VideoPaths:
    root: str
    script_txt: str
    chapters_json: str
    title_txt: str
    media_json: str
    sources_json: str
    sources_report: str
    contact_sheet: str
    narration_wav: str
    words_json: str
    research_json: str
    timeline_json: str
    visual_json: str
    subs_srt: str
    subs_ass: str
    tele_ass: str
    tele_mp4: str
    silent_mp4: str
    human_wav: str
    transcription_json: str
    final_mp4: str
    metadata_json: str


def video_paths(out_dir: str, slug: str) -> VideoPaths:
    root = os.path.join(out_dir, slug)
    return VideoPaths(
        root=root,
        script_txt=os.path.join(root, "script", "script.txt"),
        chapters_json=os.path.join(root, "script", "chapters.json"),
        title_txt=os.path.join(root, "script", "title.txt"),
        media_json=os.path.join(root, "media", "media.json"),
        sources_json=os.path.join(root, "sources", "sources.json"),
        sources_report=os.path.join(root, "sources", "FONTES.md"),
        contact_sheet=os.path.join(root, "review", "contact_sheet.html"),
        narration_wav=os.path.join(root, "audio", "narration.wav"),
        words_json=os.path.join(root, "audio", "words.json"),
        research_json=os.path.join(root, "sources", "research.json"),
        timeline_json=os.path.join(root, "timeline", "timeline.json"),
        visual_json=os.path.join(root, "timeline", "visual_timeline.json"),
        subs_srt=os.path.join(root, "subtitles", "subs.srt"),
        subs_ass=os.path.join(root, "subtitles", "subs.ass"),
        tele_ass=os.path.join(root, "teleprompter", "teleprompter.ass"),
        tele_mp4=os.path.join(root, "teleprompter", "teleprompter.mp4"),
        silent_mp4=os.path.join(root, "render", "silent.mp4"),
        human_wav=os.path.join(root, "audio", "human.wav"),
        transcription_json=os.path.join(root, "audio", "transcription.json"),
        final_mp4=os.path.join(root, "render", "final.mp4"),
        metadata_json=os.path.join(root, "metadata.json"),
    )


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, data) -> None:
    # Diretório defensivo: nada apaga output/, mas limpeza externa
    # concorrente não deve derrubar o run com FileNotFoundError.
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def _load_chapters(paths: VideoPaths) -> list[Chapter]:
    return [Chapter.from_dict(d) for d in _read_json(paths.chapters_json)]


def _query_terms(query: str) -> list[str]:
    stop = {"the", "and", "with", "from", "into", "para", "uma", "para"}
    return [t.lower() for t in query.replace(",", " ").split()
            if len(t) > 2 and t.lower() not in stop]


def _relevance(query: str, asset: MediaAsset) -> int:
    haystack = f"{asset.title}".lower()
    return sum(1 for term in _query_terms(query) if term in haystack)


def _fetch_media(chapters: list[Chapter], cfg: CurioConfig,
                 paths: VideoPaths, metrics=None) -> tuple[list[dict], list[str]]:
    """Busca e baixa um asset por cena. Falha vira fallback com aviso."""
    providers = get_providers(cfg)
    search_memo: dict[tuple[str, str], list] = {}
    scenes, warnings = [], []
    for ch in chapters:
        # Candidatos de todas as consultas, ordenados por relevância
        # (sobreposição consulta↔título) — evita associações falsas.
        ranked: list[tuple[int, str, MediaAsset]] = []
        seen = set()
        for query in ch.visual_queries:
            for prov in providers:
                memo_key = (prov.name, query)
                if memo_key not in search_memo:
                    try:
                        search_memo[memo_key] = prov.search(query, metrics=metrics)
                    except MediaError as exc:
                        print(f"AVISO: {exc} — tentando próxima fonte.",
                              file=sys.stderr)
                        search_memo[memo_key] = []
                for cand in search_memo[memo_key]:
                    if cand.asset_id in seen:
                        continue
                    seen.add(cand.asset_id)
                    ranked.append((_relevance(query, cand), query, cand))
        ranked.sort(key=lambda r: -r[0])
        # Gate de relevância: escore 0 = título sem nada da consulta
        # (ex.: foto aleatória) — fallback honesto em vez de associação falsa.
        ranked = [r for r in ranked if r[0] > 0]
        # Gate de direitos: nunca baixa ativo com licença bloqueada
        # ("todos os direitos reservados", NoDerivatives). O verificador
        # também roda depois do download, quando a dims é conferida.
        blocked = [r for r in ranked
                   if classify_rights(r[2].license or "", r[2].provider)
                   == "blocked"]
        for _score, _q, cand in blocked:
            msg = (f"cena {ch.id}: '{cand.title[:50]}' descartado — licença "
                   f"bloqueada ({cand.license or 'sem licença'})")
            warnings.append(msg)
            print(f"AVISO: {msg}", file=sys.stderr)
        ranked = [r for r in ranked
                  if classify_rights(r[2].license or "", r[2].provider)
                  != "blocked"]
        asset = None
        for _score, _q, cand in ranked:
            try:
                asset = download_asset(cand, cfg.cache_dir, metrics)
                break
            except MediaError as exc:
                print(f"AVISO: {exc} — tentando próximo asset.",
                      file=sys.stderr)
        if asset is None:
            msg = (f"cena {ch.id}: sem mídia relevante "
                   f"({', '.join(ch.visual_queries) or 'sem consultas'}) — fallback")
            warnings.append(msg)
            print(f"AVISO: {msg}", file=sys.stderr)
        scenes.append({"chapter_id": ch.id,
                       "asset": asset.to_dict() if asset else None,
                       "reused_from": None})
    _resolve_reuse(scenes)
    return scenes, warnings


def _resolve_reuse(scenes: list[dict]) -> None:
    """Garantia de imagem do início ao fim: cena sem asset reusa a imagem
    relevante mais próxima (com outro movimento Ken Burns) antes de cair no
    gradiente. Só o gradiente resta se NENHUMA cena tiver mídia."""
    have = [s for s in scenes if s["asset"]]
    if not have:
        return
    for s in scenes:
        if s["asset"] is not None:
            continue
        cid = s["chapter_id"]
        nearest = min(have, key=lambda h: (abs(h["chapter_id"] - cid),
                                           0 if h["chapter_id"] < cid else 1))
        s["asset"] = nearest["asset"]
        s["reused_from"] = nearest["chapter_id"]
        print(f"AVISO: cena {cid} reusa imagem da cena "
              f"{nearest['chapter_id']} (sem mídia própria).", file=sys.stderr)


class MediaStandby(RuntimeError):
    """Nenhuma imagem para o vídeo: projeto em standby até fotos manuais.

    Atributos: slug, manual_dir, n_scenes. O usuário coloca fotos em
    `manual_dir` e roda o generate de novo (sem --force) para continuar.
    """

    def __init__(self, slug: str, manual_dir: str, n_scenes: int):
        self.slug = slug
        self.manual_dir = manual_dir
        self.n_scenes = n_scenes
        super().__init__(
            f"projeto '{slug}' em STANDBY: nenhuma imagem encontrada para "
            f"{n_scenes} cena(s). Coloque fotos (.jpg/.png/.webp) em "
            f"{manual_dir} e rode o generate de novo para continuar o vídeo."
        )


MANUAL_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def manual_media_dir(paths: VideoPaths) -> str:
    """Pasta onde o usuário deposita fotos manuais quando há standby."""
    return os.path.join(paths.root, "assets", "manual")


def _manual_readme(manual_dir: str, slug: str, n_scenes: int) -> None:
    os.makedirs(manual_dir, exist_ok=True)
    readme = os.path.join(manual_dir, "COMO_USAR.txt")
    if os.path.isfile(readme):
        return
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(
            f"Projeto '{slug}' em STANDBY: nenhuma imagem automática.\n"
            f"1) Coloque fotos aqui (.jpg/.jpeg/.png/.webp) — "
            f"ideal: 1 por cena ({n_scenes} cenas).\n"
            f"2) Nomes em ordem alfabética definem a ordem das cenas "
            f"(ex.: 01-abertura.jpg, 02-meio.jpg).\n"
            f"3) Rode o generate de novo (sem --force) para continuar.\n"
            f"Com menos fotos que cenas, as fotos rodiziam entre as cenas.\n"
        )


def _probe_image_dims(path: str) -> tuple[int, int]:
    """Dimensões via ffprobe; (0, 0) se indisponível (nunca fatal)."""
    try:
        proc = ff.run([ff.FFPROBE, "-v", "error", "-select_streams", "v:0",
                       "-show_entries", "stream=width,height",
                       "-of", "csv=p=0", path])
        if proc.returncode == 0:
            parts = proc.stdout.strip().split(",")
            return int(parts[0]), int(parts[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0, 0


def _manual_media_scenes(chapters: list[Chapter],
                         manual_dir: str) -> list[dict] | None:
    """Monta media_scenes a partir de fotos manuais (None se vazia).

    Arquivos em ordem alfabética; rodízio entre cenas se houver menos
    fotos que cenas. `reused_from` marca de qual cena a foto veio.
    """
    if not os.path.isdir(manual_dir):
        return None
    files = sorted(f for f in os.listdir(manual_dir)
                   if f.lower().endswith(MANUAL_IMAGE_EXTS)
                   and os.path.isfile(os.path.join(manual_dir, f)))
    if not files:
        return None
    scenes = []
    for i, ch in enumerate(chapters):
        fname = files[i % len(files)]
        donor = chapters[i % len(files)].id
        local = os.path.join(manual_dir, fname)
        stem = os.path.splitext(fname)[0]
        w, h = _probe_image_dims(local)
        asset = {
            "provider": "manual",
            "asset_id": f"manual-{stem}",
            "title": stem.replace("-", " ").replace("_", " "),
            "author": "",
            "license": "manual do usuário",
            "license_url": "",
            "source_url": "",
            "download_url": "",
            "download_fallback_url": "",
            "width": w,
            "height": h,
            "size_bytes": os.path.getsize(local),
            "kind": "image",
            "local_path": local,
            "used_in": f"cena {ch.id}",
        }
        scenes.append({"chapter_id": ch.id,
                        "asset": asset,
                        "assets": [{"asset": asset, "query": "manual",
                                    "relevance": 100, "order": 0}],
                        "reused_from": None if donor == ch.id else donor})
    return scenes


def _count_assets(media_scenes: list[dict]) -> int:
    """Total de cenas com ao menos uma imagem (formato singular ou multi)."""
    n = 0
    for s in media_scenes or []:
        if s.get("asset") is not None:
            n += 1
            continue
        if any((e.get("asset") or {}).get("local_path")
               for e in s.get("assets") or []):
            n += 1
    return n


def _scene_segment(ch: Chapter, asset_dict: dict | None, idea: str,
                   duration: float, paths: VideoPaths, cfg: CurioConfig,
                   variant: int) -> str:
    seg = os.path.join(paths.root, "render", "segments",
                       f"scene{ch.id}_{duration:.1f}s.mp4")
    if os.path.isfile(seg):
        return seg
    os.makedirs(os.path.dirname(seg), exist_ok=True)
    if asset_dict and asset_dict.get("local_path"):
        local = asset_dict["local_path"]
        if asset_dict.get("kind") == "video":
            return render_stage.render_video_segment(local, duration, seg, cfg)
        if os.path.isfile(local):
            return render_stage.render_image_segment(local, duration, seg,
                                                     cfg, variant)
    return render_stage.render_fallback_segment(
        duration, seg, cfg, render_stage._wrap_title(idea))


def _build_silent(chapters: list[Chapter], media_scenes: list[dict], idea: str,
                   durations: list[float], paths: VideoPaths,
                   cfg: CurioConfig, out_path: str) -> str:
    assets = {s["chapter_id"]: s["asset"] for s in media_scenes}
    segs = []
    for i, (ch, dur) in enumerate(zip(chapters, durations)):
        segs.append(_scene_segment(ch, assets.get(ch.id), idea, round(dur, 1),
                                   paths, cfg, variant=i))
    return render_stage.concat_copy(segs, out_path)


def _visual_segment(trecho: dict, idea: str, duration: float,
                    paths: VideoPaths, cfg: CurioConfig,
                    variant: int) -> str:
    """Um segmento do modo roteiro-pronto: colagem se houver 2+ fotos."""
    images = [dict(img) for img in trecho.get("images", [])]
    images = [im for im in images
              if im.get("local_path") and os.path.isfile(im["local_path"])]
    seg = os.path.join(paths.root, "render", "segments",
                       f"scene{trecho['chapter_id']}_visual_{duration:.1f}s.mp4")
    if os.path.isfile(seg):
        return seg
    os.makedirs(os.path.dirname(seg), exist_ok=True)
    if len(images) >= 2:
        return render_stage.render_collage_segment(images, duration, seg,
                                                   cfg, variant)
    asset = images[0] if images else None
    return _scene_segment(
        Chapter(id=trecho["chapter_id"], narration=trecho.get("narration", ""),
                duration_estimate=duration),
        {"local_path": asset["local_path"],
         "kind": asset.get("kind", "image")} if asset else None,
        idea, duration, paths, cfg, variant)


def _build_silent_visual(chapters: list[Chapter], visual_timeline: list[dict],
                         idea: str, paths: VideoPaths,
                         cfg: CurioConfig, out_path: str) -> str:
    trechos = {t["chapter_id"]: t for t in visual_timeline}
    segs = []
    for i, ch in enumerate(chapters):
        t = trechos.get(ch.id, {})
        dur = round(max(0.5, ch.end - ch.start), 1)
        segs.append(_visual_segment(
            {"chapter_id": ch.id, "narration": ch.narration,
             "images": t.get("images", [])} if t else
            {"chapter_id": ch.id, "narration": ch.narration, "images": []},
            idea, dur, paths, cfg, variant=i))
    return render_stage.concat_copy(segs, out_path)


def _write_visual_timeline(chapters: list[Chapter], media_scenes: list[dict],
                           paths: VideoPaths, slug: str,
                           overlap_cap: float, sfx: bool,
                           insertions: int | None = None,
                           insert_style: str = "drop_in",
                           insert_gain_db: int = -30) -> list[dict]:
    vt = visual_stage.build_visual_timeline(
        chapters, media_scenes, overlap_cap, seed=slug, sfx=sfx,
        insertions=insertions, insert_style=insert_style,
        insert_gain_db=insert_gain_db)
    _write_json(paths.visual_json, vt)
    print(f"Timeline visual: {visual_stage.visual_summary(vt)}")
    return vt


def count_insertions(visual_timeline: list[dict]) -> int:
    """Fotos complementares do vídeo (as que caem por cima do fundo)."""
    return sum(1 for t in visual_timeline for im in t.get("images", [])
               if im.get("order", 0) > 0)


def _sfx_track_for(visual_timeline: list[dict], total: float,
                   paths: VideoPaths) -> str | None:
    """Gera audio/sfx.wav a partir dos eventos da timeline (ou None)."""
    events = [img["sfx"] for t in visual_timeline for img in t.get("images", [])
              if isinstance(img.get("sfx"), dict)]
    if not events:
        return None
    out = os.path.join(paths.root, "audio", "sfx.wav")
    return render_stage.build_sfx_track(events, total, out)


def _narration_with_sfx(wav_path: str, sfx_path: str | None, total: float,
                        paths: VideoPaths) -> str:
    """Mistura o SFX na narração (sem tocar seu volume) ou devolve o original."""
    if not sfx_path:
        return wav_path
    out = os.path.join(paths.root, "audio", "mixed.wav")
    return render_stage.mix_sfx(wav_path, sfx_path, out, total)


def _base_metadata(idea: str, slug: str, cfg: CurioConfig, script_text: str,
                   script_source: str, chapters: list[Chapter],
                   scenes_source: str, media_scenes: list[dict],
                   warnings: list[str], stage_times: dict,
                   started: float) -> dict:
    return {
        "title": idea.strip(),
        "input": idea,
        "slug": slug,
        "duration_target": cfg.duration_target,
        "script_source": script_source,
        "script_chars": len(script_text),
        "scenes_source": scenes_source,
        "chapters": [c.to_dict() for c in chapters],
        "media": media_scenes,
        "warnings": warnings,
        "width": cfg.width,
        "height": cfg.height,
        "fps": cfg.fps,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_time_seconds": round(time.monotonic() - started, 2),
        "stage_times": stage_times,
        "pipeline_version": "scenes-0.2",
    }


def run_pipeline(idea: str, cfg: CurioConfig, slug: str | None = None,
                 force: bool = False, narration: str = "ai",
                 on_progress=None, provided_script: str | None = None,
                 max_images: int = 1,
                 visual_overlap: float | None = None) -> dict:
    started = time.monotonic()
    stage_times: dict[str, float] = {}
    warnings: list[str] = []
    stages = STAGES_HUMAN if narration == "human" else STAGES_AI
    script_mode = provided_script is not None
    max_images = max(1, min(5, int(max_images or 1)))
    overlap_cap = float(cfg.visual_overlap if visual_overlap is None
                        else visual_overlap)
    # Fotos complementares: o orçamento de EXIBIÇÃO é do vídeo (1–2), não da
    # cena. A busca, porém, traz 3 candidatos por cena de propósito: a
    # inserção tem de ser a imagem mais precisa sobre o assunto, e escolher
    # a melhor exige mais de uma opção. A exibição continua em 2 (fundo +
    # uma complementar): o terceiro candidato existe só para a comparação.
    insert_budget = int(cfg.visual_insertions)
    if insert_budget > 0:
        max_images = 3

    def emit(idx: int, label: str, status: str = "…") -> None:
        if on_progress:
            on_progress(idx, len(stages), label, status)

    slug = slug or slugify_with_timestamp(idea)
    paths = video_paths(cfg.out_dir, slug)
    metrics = RunMetrics(slug, idea, narration)
    for d in ("script", "audio", "subtitles", "assets", "render",
              "media", "timeline", "teleprompter", "sources"):
        os.makedirs(os.path.join(paths.root, d), exist_ok=True)
    sources = sources_stage.SourceRegistry.load(paths.sources_json)
    sources.slug = slug

    # [0/6] Pesquisa web (RAG): todo texto exige ≥1 fonte real.
    # Roda antes de qualquer roteiro — inclusive roteiro-pronto (as fontes
    # vão p/ o registry mesmo sem alterar o texto do usuário). Falha
    # explícita se nada for encontrado: nunca roteiro "só IA".
    t0 = time.monotonic()
    emit(0, "Pesquisando fontes")
    research_sources = research_stage.research_topic(
        idea, cfg.language, max_sources=cfg.research_max_sources,
        metrics=metrics, timeout=cfg.research_timeout)
    research_status = ("confirmed" if len(research_sources) >= 2
                       else "partial")
    for rs in research_sources:
        sources.add_claim(
            claim=rs.title, title=rs.title, url=rs.url,
            evidence=rs.snippet[:300], status=research_status,
            notes=f"RAG web ({rs.origin})")
    _write_json(paths.research_json, {
        "idea": idea,
        "queries": research_stage.extract_keywords(idea, cfg.language),
        "sources": [rs.to_dict() for rs in research_sources],
    })
    research_pack = research_stage.format_for_prompt(research_sources,
                                                     cfg.language)
    print(f"Fontes: {len(research_sources)} "
          f"({', '.join(rs.title[:40] for rs in research_sources)})")
    stage_times["research"] = round(time.monotonic() - t0, 2)
    emit(0, "Pesquisando fontes", "OK")

    # [1/6] Roteiro (modo roteiro-pronto: usa o texto verbatim, nunca gera)
    t0 = time.monotonic()
    emit(1, "Lendo roteiro pronto" if script_mode else "Gerando roteiro")
    force_after_script = force
    if script_mode:
        assert provided_script is not None
        script_text = provided_script.strip()
        if not script_text:
            raise ValueError("roteiro vazio — nada para produzir")
        script_source = "provided"
        cached = _read(paths.script_txt) if os.path.isfile(paths.script_txt) else None
        if cached != script_text:
            with open(paths.script_txt, "w", encoding="utf-8") as fh:
                fh.write(script_text)
            if cached is not None and not force:
                print("AVISO: roteiro fornecido mudou — refazendo cenas e mídia.",
                      file=sys.stderr)
                force_after_script = True
    elif not force and os.path.isfile(paths.script_txt):
        # Autocura: roteiros gerados antes da blindagem podem conter
        # marcadores de lista ("0) ", "1. "...). Remove só os marcadores
        # (sem truncar/re-escrever) para que qualquer etapa refeita use
        # texto limpo; áudio/cenas em cache seguem intactos e alinhados.
        raw_cached = _read(paths.script_txt)
        healed = subs_stage.strip_list_markers(raw_cached)
        if healed != raw_cached:
            print("AVISO: roteiro em cache continha numeração de lista — "
                  "marcadores removidos.", file=sys.stderr)
            warnings.append("roteiro em cache higienizado (marcadores de lista)")
            with open(paths.script_txt, "w", encoding="utf-8") as fh:
                fh.write(healed)
        script_text, script_source = healed, "cache"
    else:
        script_text, script_source = script_stage.generate_script(
            idea, cfg, metrics, research=research_pack)
        with open(paths.script_txt, "w", encoding="utf-8") as fh:
            fh.write(script_text)
    stage_times["script"] = round(time.monotonic() - t0, 2)
    emit(1, "Lendo roteiro pronto" if script_mode else "Gerando roteiro", "OK")

    # Conferência anti-invenção: os números do roteiro são comparados com o
    # que a pesquisa trouxe. O que não bate fica registrado como não
    # verificado no relatório de fontes — não some do texto (a decisão é do
    # autor), mas não se apresenta como confirmado.
    grounding = research_stage.verify_grounding(script_text, research_sources,
                                                cfg.language)
    if grounding["unverified"]:
        msg = (f"{len(grounding['unverified'])} dado(s) do roteiro sem "
               f"correspondência nas fontes: "
               f"{', '.join(grounding['unverified'][:6])}")
        warnings.append(msg)
        print(f"AVISO: {msg} — ver sources/FONTES.md", file=sys.stderr)
    elif grounding["checked"]:
        print(f"Fundamentação: {grounding['checked']} dado(s) conferidos, "
              f"todos nas fontes.")

    # Título-pergunta (IA a partir do roteiro; nunca entra na narração).
    if not force_after_script and os.path.isfile(paths.title_txt):
        video_title, title_source = _read(paths.title_txt).strip(), "cache"
        if not video_title:
            video_title, title_source = script_stage.generate_title(
                script_text, idea, cfg, metrics)
            with open(paths.title_txt, "w", encoding="utf-8") as fh:
                fh.write(video_title)
    else:
        video_title, title_source = script_stage.generate_title(
            script_text, idea, cfg, metrics)
        with open(paths.title_txt, "w", encoding="utf-8") as fh:
            fh.write(video_title)
    print(f"Título: {video_title} ({title_source})")

    # [2/6] Cenas
    t0 = time.monotonic()
    emit(2, "Interpretando cenas")
    if not force_after_script and os.path.isfile(paths.chapters_json):
        chapters = _load_chapters(paths)
        scenes_source = "cache"
        if script_mode:
            visual_stage.validate_preserved(script_text, chapters)
    else:
        if script_mode:
            n = visual_stage.scenes_for_script(script_text, cfg)
        elif cfg.duration_target <= 0:
            # Automático: o roteiro (não a meta) define as cenas.
            n = scenes_stage.scenes_for_length(len(script_text.split()))
        else:
            n = scenes_stage.scenes_for_duration(cfg.duration_target)
        try:
            chapters, scenes_source = scenes_stage.build_chapters(
                script_text, cfg, n_scenes=n, metrics=metrics)
        except nvidia_stage.NvidiaError as exc:
            if not script_mode:
                raise
            # Modo roteiro-pronto: sem API, a divisão local basta — ela
            # agrupa frases literais e sempre preserva a narração.
            print(f"AVISO: {exc} — usando divisão local.", file=sys.stderr)
            warnings.append(f"cenas locais (NVIDIA indisponível: {exc})")
            chapters = scenes_stage._local_chapters(script_text, n)
            scenes_source = "local"
        if script_mode:
            visual_stage.validate_preserved(script_text, chapters)
        _write_json(paths.chapters_json, [c.to_dict() for c in chapters])
    stage_times["scenes"] = round(time.monotonic() - t0, 2)
    emit(2, "Interpretando cenas", "OK")

    # [3/6] Mídia (manual > cache > provedores; zero imagens = standby)
    t0 = time.monotonic()
    emit(3, "Buscando mídia")
    manual_dir = manual_media_dir(paths)
    media_scenes = None
    manual = _manual_media_scenes(chapters, manual_dir)
    if manual is not None:
        media_scenes = manual
        msg = (f"mídia manual: {len({e['asset']['local_path'] for s in manual for e in s.get('assets') or []})} "
               f"foto(s) de {manual_dir}")
        warnings.append(msg)
        print(f"Mídia manual: usando fotos de {manual_dir}.", file=sys.stderr)
        _write_json(paths.media_json, media_scenes)
    if media_scenes is None and not force_after_script and os.path.isfile(paths.media_json):
        try:
            saved = _read_json(paths.media_json)
            chapter_ok = ([s["chapter_id"] for s in saved] ==
                          [c.id for c in chapters])
            files_ok = True
            for s in saved:
                first = s.get("asset")
                if first is not None and not os.path.isfile(
                        first.get("local_path", "")):
                    files_ok = False
                    break
                if max_images > 1:
                    if "assets" not in s:
                        files_ok = False
                        break
                    for im in s.get("assets", []):
                        asset = im.get("asset", {})
                        if not os.path.isfile(asset.get("local_path", "")):
                            files_ok = False
                            break
            if chapter_ok and files_ok:
                media_scenes = saved
        except (json.JSONDecodeError, KeyError):
            media_scenes = None
    if media_scenes is None:
        if max_images > 1:
            media_scenes, media_warnings = visual_stage.fetch_media_multi(
                chapters, cfg, max_images, metrics)
        else:
            media_scenes, media_warnings = _fetch_media(chapters, cfg, paths,
                                                       metrics)
        warnings.extend(media_warnings)
        _write_json(paths.media_json, media_scenes)
    # Registra procedência das mídias no registro de fontes do projeto:
    # links ANTES do uso (página, arquivo, licença) + local APÓS o uso.
    # `media_rights_notes` alimenta o relatório: licença incerta não passa
    # em silêncio — ela vira aviso explícito na pasta de informações.
    media_rights_notes: list[str] = []
    for scene in media_scenes:
        for entry in scene.get("assets") or []:
            asset = entry.get("asset") or {}
            if not asset.get("local_path"):
                continue
            rights = asset.get("rights_status", "") or classify_rights(
                asset.get("license", ""), asset.get("provider", ""))
            asset["rights_status"] = rights
            sources.add_media(
                title=asset.get("title", ""),
                origin_url=asset.get("source_url", ""),
                file_url=asset.get("download_url", ""),
                provider=asset.get("provider", ""),
                author=asset.get("author", ""),
                license=asset.get("license", ""),
                license_url=asset.get("license_url", ""),
                local_path=asset.get("local_path", ""),
                used_in=f"cena {scene['chapter_id']}",
                rights_status=rights,
                query=entry.get("query", ""),
                scene=f"cena {scene['chapter_id']}")
            if rights == "verify":
                note = (f"Cena {scene['chapter_id']}: "
                        f"'{asset.get('title', '')[:60]}' entrou no vídeo com "
                        f"licença a conferir "
                        f"({asset.get('provider', '')}: "
                        f"{asset.get('license') or 'desconhecida'}) — confira "
                        f"em {asset.get('license_url') or asset.get('source_url') or 'sem link'}")
                if note not in media_rights_notes:
                    media_rights_notes.append(note)
    stage_times["media"] = round(time.monotonic() - t0, 2)
    emit(3, "Buscando mídia",
         "AVISO" if any(s["asset"] is None for s in media_scenes) else "OK")

    # Sem nenhuma imagem o vídeo NÃO é produzido: standby até fotos manuais.
    if _count_assets(media_scenes) == 0:
        _manual_readme(manual_dir, slug, len(chapters))
        sources.save(paths.sources_json)
        sources_stage.write_report(paths.sources_report, sources,
                                   research=research_sources, grounding=grounding)
        _write_json(paths.metadata_json, {
            "slug": slug,
            "idea": idea,
            "status": "standby-no-media",
            "narration": "standby",
            "manual_dir": manual_dir,
            "n_scenes": len(chapters),
            "stage_times": dict(stage_times),
            "warnings": list(warnings),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        emit(3, "Buscando mídia", "STANDBY")
        raise MediaStandby(slug, manual_dir, len(chapters))

    if narration == "human":
        return _human_prep(idea, slug, cfg, paths, script_text, script_source,
                           chapters, scenes_source, media_scenes, warnings,
                           stage_times, started, emit, metrics,
                           script_mode=script_mode, max_images=max_images,
                           overlap_cap=overlap_cap,
                           insert_budget=insert_budget)

    # [4/6] Narração (IA) — timestamps reais via WordBoundary
    t0 = time.monotonic()
    emit(4, "Gerando narração")
    words = None
    if (not force and os.path.isfile(paths.narration_wav)
            and os.path.isfile(paths.words_json)):
        audio_duration = ff.probe_duration(paths.narration_wav)
        words = _read_json(paths.words_json)
        if not tts_stage.tts_coverage_ok(words, script_text):
            # Autocura: cache de uma síntese parcial (stream interrompido).
            # Re-sintetiza em vez de produzir vídeo curto.
            print(f"AVISO: narração em cache cobre só "
                  f"{len(words or [])}/{len(script_text.split())} palavras — "
                  "sintetizando de novo.", file=sys.stderr)
            warnings.append("narração parcial em cache — refeita")
            words = None
        else:
            tts_info = {"provider": cfg.tts_provider, "voice": cfg.tts_voice,
                        "speed": cfg.tts_speed, "reused": True}
    if words is None:
        res = tts_stage.synthesize(script_text, paths.narration_wav,
                                   cfg.tts_provider, cfg.tts_voice,
                                   cfg.tts_speed, cfg.duration_target,
                                   words_path=paths.words_json, metrics=metrics,
                                   language=cfg.language)
        audio_duration = res.duration
        words = res.words
        tts_info = {"provider": res.provider, "voice": res.voice,
                    "speed": res.speed, "reused": False}
    stage_times["tts"] = round(time.monotonic() - t0, 2)
    emit(4, "Gerando narração", "OK")

    # Timeline real: capítulos alinhados aos boundaries (sem offset artificial)
    try:
        chapters = scenes_stage.apply_timings(chapters, words or [])
        timed_source = "wordboundary"
    except (ValueError, IndexError) as exc:
        print(f"AVISO: {exc} — timeline proporcional.", file=sys.stderr)
        warnings.append(f"timeline proporcional ({exc})")
        cursor = (words[0]["start"] if words else 0.15) if words else 0.15
        total_w = sum(len(c.narration.split()) for c in chapters) or 1
        for ch in chapters:
            share = audio_duration * len(ch.narration.split()) / total_w
            ch.start, ch.end = cursor, cursor + share
            cursor = ch.end
        timed_source = "proporcional"
    # Costura: pausas entre falas pertencem às cenas (nada de buraco visual);
    # último capítulo cobre até o fim do áudio.
    chapters[0].start = 0.0
    for prev, nxt in zip(chapters, chapters[1:]):
        mid = round((prev.end + nxt.start) / 2, 3)
        prev.end = nxt.start = mid
    chapters[-1].end = round(audio_duration, 3)
    _write_json(paths.timeline_json, [c.to_dict() for c in chapters])
    visual_timeline = (_write_visual_timeline(
        chapters, media_scenes, paths, slug, overlap_cap, cfg.visual_sfx,
        insertions=insert_budget, insert_style=cfg.visual_insert_style,
        insert_gain_db=cfg.visual_insert_gain_db)
        if max_images > 1 else [])
    if visual_timeline:
        print(f"Inserções: {count_insertions(visual_timeline)} foto(s) "
              f"complementar(es) caindo sobre o fundo "
              f"(estilo {cfg.visual_insert_style}).")

    # [5/6] Legendas (reais quando há boundaries). Sempre regeneradas:
    # é barato, determinístico (roteiro+áudio em cache) e autocura legendas
    # antigas geradas antes das blindagens de sanitização.
    t0 = time.monotonic()
    emit(5, "Sincronizando legendas")
    prev_ass = _read(paths.subs_ass) if os.path.isfile(paths.subs_ass) else ""
    cue_count = subs_stage.write_subtitles(
        script_text, audio_duration, paths.subs_srt, paths.subs_ass,
        cfg.width, cfg.height, cfg.sub_font_size, cfg.sub_margin_v,
        words=words if tts_info["provider"] == "edge-tts" else None,
        cache_dir=cfg.cache_dir)
    subs_changed = _read(paths.subs_ass) != prev_ass
    if subs_changed and not force and os.path.isfile(paths.final_mp4):
        print("AVISO: texto das legendas mudou — refazendo o MP4 final "
              "para acompanhar.", file=sys.stderr)
        warnings.append("legendas atualizadas (rebuild do final.mp4)")
    stage_times["subs"] = round(time.monotonic() - t0, 2)
    emit(5, "Sincronizando legendas", "OK")

    # [6/6] Montagem dinâmica + final
    t0 = time.monotonic()
    emit(6, "Montando vídeo")
    durations = [max(0.5, c.end - c.start) for c in chapters]
    total = round(audio_duration + 0.8, 2)
    sfx_path = None
    if not force and not subs_changed and os.path.isfile(paths.final_mp4):
        video_duration = ff.probe_duration(paths.final_mp4)
        render_info = {"backend": "cache", "encoder": "cache",
                       "duration": video_duration, "path": paths.final_mp4}
        cached_sfx = os.path.join(paths.root, "audio", "sfx.wav")
        if visual_timeline and os.path.isfile(cached_sfx):
            sfx_path = cached_sfx
    else:
        silent = paths.silent_mp4
        if force or not os.path.isfile(silent):
            if visual_timeline:
                _build_silent_visual(chapters, visual_timeline, idea, paths,
                                     cfg, silent)
            else:
                _build_silent(chapters, media_scenes, idea, durations, paths,
                              cfg, silent)
        narration_wav = paths.narration_wav
        sfx_path = (_sfx_track_for(visual_timeline, total, paths)
                    if visual_timeline and cfg.visual_sfx else None)
        if sfx_path:
            narration_wav = _narration_with_sfx(paths.narration_wav, sfx_path,
                                                total, paths)
        title_fontfile = subs_stage.ensure_display_font(cfg.cache_dir)[2]
        render_info = render_stage.burn_final(
            silent, paths.subs_ass, narration_wav, paths.final_mp4,
            cfg, total, title=video_title, title_fontfile=title_fontfile)
        video_duration = render_info["duration"]
    stage_times["render"] = round(time.monotonic() - t0, 2)
    emit(6, "Montando vídeo", "OK")

    metadata = _base_metadata(idea, slug, cfg, script_text, script_source,
                              chapters, scenes_source, media_scenes, warnings,
                              stage_times, started)
    metadata.update({
        "narration": "ai",
        "mode": "script" if script_mode else "idea",
        "video_title": video_title,
        "title_source": title_source,
        "timeline_source": timed_source,
        "duration_actual": round(video_duration, 2),
        "audio_duration": round(audio_duration, 2),
        "subtitle_cues": cue_count,
        "subtitle_source": ("wordboundary" if words and
                            tts_info["provider"] == "edge-tts"
                            else "proporcional"),
        "tts_provider": tts_info["provider"],
        "tts_voice": tts_info["voice"],
        "tts_speed": tts_info["speed"],
        "tts_reused": tts_info["reused"],
        "render_backend": render_info["backend"],
        "render_encoder": render_info["encoder"],
        "visual": ({
            "max_images": max_images,
            "overlap_cap": overlap_cap,
            "sfx": bool(sfx_path),
            "insertions": count_insertions(visual_timeline),
            "insert_budget": insert_budget,
            "insert_style": cfg.visual_insert_style,
            "insert_gain_db": cfg.visual_insert_gain_db,
        } if max_images > 1 else None),
        "sources": {
            "claims": len(sources.claims),
            "media": len(sources.media),
            "report": paths.sources_report,
            "blocked_media": sum(1 for m in sources.media
                                 if m.rights_status == "blocked"),
        },
        "research": {
            "sources": len(research_sources),
            "status": research_status,
            "titles": [rs.title for rs in research_sources],
            "grounding": grounding,
        },
        # Como cada cena foi visualizada e por que as outras não foram.
        # `sem_visual` é a única métrica que é problema: diagrama e cartão
        # contam como visual, não como falha.
        "visual_report": metrics.media_visual_report(len(chapters)),
        "artifacts": {
            "script": paths.script_txt,
            "title": paths.title_txt,
            "research": paths.research_json,
            "chapters": paths.chapters_json,
            "media": paths.media_json,
            "audio": paths.narration_wav,
            "words": paths.words_json,
            "timeline": paths.timeline_json,
            **({"visual_timeline": paths.visual_json}
               if max_images > 1 else {}),
            **({"sfx": sfx_path} if sfx_path else {}),
            "subtitles": paths.subs_srt,
            "subtitles_ass": paths.subs_ass,
            "silent": paths.silent_mp4,
            "video": paths.final_mp4,
        },
    })
    _write_json(paths.metadata_json, metadata)
    sources.save(paths.sources_json)
    # Pasta de informações: o mesmo conteúdo do sources.json em texto claro,
    # com as fontes do texto E as imagens com seus direitos autorais.
    sources_stage.write_report(paths.sources_report, sources,
                               research=research_sources, grounding=grounding,
                               media_notes=media_rights_notes)
    # Folha de contato: o autor revisa o vídeo em ~1 min sem assistir.
    if media_scenes:
        from .stages import review as review_stage
        review_stage.write_contact_sheet(
            paths.contact_sheet, chapters, media_scenes, paths.root, slug,
            threshold=scoring_stage.threshold())
    stage_times["finalize"] = 0.0
    metadata["stage_times"] = stage_times
    metadata["metrics_file"] = metrics.save(metadata, stage_times,
                                            cfg.metrics_dir)
    return metadata


def run_script_pipeline(script_text: str, cfg: CurioConfig,
                        title: str | None = None, slug: str | None = None,
                        force: bool = False, narration: str = "ai",
                        max_images: int | None = None,
                        on_progress=None) -> dict:
    """Modo roteiro-pronto: organiza mídia sobre um roteiro já existente.

    O texto é usado verbatim como narração/legenda — nunca gerado nem
    reescrito. `title` vira título/metadados; sem ele, usa-se a primeira
    linha do roteiro. `max_images` (1–5, padrão da config) é o nº de fotos
    por cena com sobreposição em álbum.
    """
    text = (script_text or "").strip()
    if not text:
        raise ValueError("roteiro vazio — nada para produzir")
    if title is None:
        first_line = next((ln.strip() for ln in text.splitlines()
                           if ln.strip()), text[:90])
        title = first_line[:90]
    slug = slug or slugify_with_timestamp(title)
    if max_images is None:
        max_images = cfg.visual_max_images
    return run_pipeline(title, cfg, slug=slug, force=force,
                        narration=narration, on_progress=on_progress,
                        provided_script=text, max_images=max_images)


def _human_prep(idea: str, slug: str, cfg: CurioConfig, paths: VideoPaths,
                script_text: str, script_source: str, chapters: list[Chapter],
                scenes_source: str, media_scenes: list[dict],
                warnings: list[str], stage_times: dict, started: float,
                emit, metrics, script_mode: bool = False,
                max_images: int = 1, overlap_cap: float = 0.9,
                insert_budget: int = 0) -> dict:
    # [4/6] Timeline estimada por WPM (só para leitura — nunca sincronia final)
    t0 = time.monotonic()
    emit(4, "Estimando timeline")
    cursor = 0.0
    for ch in chapters:
        ch.duration_estimate = scenes_stage.estimate_duration(
            ch.narration, cfg.teleprompter_wpm)
        ch.start, ch.end = cursor, cursor + ch.duration_estimate
        cursor = ch.end
    estimated_total = round(cursor, 2)
    _write_json(paths.timeline_json, [c.to_dict() for c in chapters])
    visual_timeline = (_write_visual_timeline(
        chapters, media_scenes, paths, slug, overlap_cap, cfg.visual_sfx,
        insertions=insert_budget, insert_style=cfg.visual_insert_style,
        insert_gain_db=cfg.visual_insert_gain_db)
        if max_images > 1 else [])
    stage_times["timeline"] = round(time.monotonic() - t0, 2)
    emit(4, "Estimando timeline", "OK")

    # [5/6] Vídeo silencioso
    t0 = time.monotonic()
    emit(5, "Montando silencioso")
    if visual_timeline:
        _build_silent_visual(chapters, visual_timeline, idea, paths, cfg,
                             paths.silent_mp4)
    else:
        durations = [c.end - c.start for c in chapters]
        _build_silent(chapters, media_scenes, idea, durations, paths, cfg,
                      paths.silent_mp4)
    stage_times["silent"] = round(time.monotonic() - t0, 2)
    emit(5, "Montando silencioso", "OK")

    # [6/6] Teleprompter (texto grande sobre cópia do silencioso)
    t0 = time.monotonic()
    emit(6, "Gerando teleprompter")
    tele_cues = tele_stage.write_teleprompter_ass(
        chapters, paths.tele_ass, cfg.width, cfg.height)
    tele_info = render_stage.burn_final(
        paths.silent_mp4, paths.tele_ass, None, paths.tele_mp4,
        cfg, estimated_total)
    stage_times["teleprompter"] = round(time.monotonic() - t0, 2)
    emit(6, "Gerando teleprompter", "OK")

    metadata = _base_metadata(idea, slug, cfg, script_text, script_source,
                              chapters, scenes_source, media_scenes, warnings,
                              stage_times, started)
    metadata.update({
        "narration": "human-pending",
        "mode": "script" if script_mode else "idea",
        "video_title": video_title,
        "title_source": title_source,
        "duration_actual": estimated_total,
        "teleprompter_wpm": cfg.teleprompter_wpm,
        "teleprompter_cues": tele_cues,
        "visual": ({
            "max_images": max_images,
            "overlap_cap": overlap_cap,
        } if max_images > 1 else None),
        "artifacts": {
            "script": paths.script_txt,
            "title": paths.title_txt,
            "chapters": paths.chapters_json,
            "media": paths.media_json,
            "timeline": paths.timeline_json,
            **({"visual_timeline": paths.visual_json}
               if max_images > 1 else {}),
            "silent": paths.silent_mp4,
            "teleprompter": paths.tele_mp4,
            "teleprompter_ass": paths.tele_ass,
        },
    })
    _write_json(paths.metadata_json, metadata)
    metadata["stage_times"] = stage_times
    metadata["metrics_file"] = metrics.save(metadata, stage_times,
                                            cfg.metrics_dir)
    return metadata


def _probe_streams(path: str) -> list[dict]:
    import json as _json
    proc = ff.run([ff.FFPROBE, "-v", "error", "-show_entries",
                   "stream=codec_type,duration", "-of", "json", path])
    if proc.returncode != 0:
        raise ff.FFMpegError(f"ffprobe falhou em {path}: {proc.stderr.strip()}")
    return (_json.loads(proc.stdout).get("streams") or [])


def finalize_project(slug: str, audio_src: str, cfg: CurioConfig,
                     force: bool = False, on_progress=None) -> dict:
    """Une áudio humano ao vídeo silencioso: transcreve, legenda, merge."""
    started = time.monotonic()
    paths = video_paths(cfg.out_dir, slug)
    metrics = RunMetrics(slug, audio_src, "human-finalize")
    for need in (paths.chapters_json, paths.timeline_json, paths.media_json,
                 paths.silent_mp4):
        if not os.path.isfile(need):
            raise FileNotFoundError(
                f"projeto '{slug}' incompleto ({need} ausente). "
                "Rode `generate --narration human` primeiro.")
    if not os.path.isfile(audio_src):
        raise FileNotFoundError(f"áudio não encontrado: {audio_src}")
    if not any(s.get("codec_type") == "audio" for s in _probe_streams(audio_src)):
        raise ValueError(f"arquivo sem trilha de áudio: {audio_src}")

    chapters = _load_chapters(paths)
    media_scenes = _read_json(paths.media_json)
    try:
        meta = _read_json(paths.metadata_json)
        idea = meta.get("input", slug)
    except (json.JSONDecodeError, FileNotFoundError):
        idea = slug

    def emit(label: str, status: str = "…") -> None:
        if on_progress:
            on_progress(label, status)

    emit("Validando áudio")
    shutil.copy(audio_src, paths.human_wav) if (
        force or not os.path.isfile(paths.human_wav)) else None
    human_dur = ff.probe_duration(paths.human_wav)
    silent_dur = ff.probe_duration(paths.silent_mp4)
    warnings = []
    ratio = human_dur / silent_dur if silent_dur > 0 else 1.0
    if ratio > 2.0 or ratio < 0.5:
        msg = (f"áudio humano ({human_dur:.1f}s) muito diferente do "
               f"silencioso ({silent_dur:.1f}s)")
        warnings.append(msg)
        print(f"AVISO: {msg}", file=sys.stderr)
    emit("Validando áudio", "OK")

    emit("Transcrevendo")
    if force or not os.path.isfile(paths.transcription_json):
        whisper_lang = "en" if str(cfg.language or "").lower().startswith("en") else "pt"
        words = transcribe_stage.transcribe(paths.human_wav,
                                            cfg.whisper_model, metrics=metrics,
                                            language=whisper_lang)
        _write_json(paths.transcription_json, words)
    else:
        words = _read_json(paths.transcription_json)
    emit("Transcrevendo", "OK")

    emit("Legendando")
    cue_count = subs_stage.write_subtitles(
        "", human_dur, paths.subs_srt, paths.subs_ass,
        cfg.width, cfg.height, cfg.sub_font_size, cfg.sub_margin_v,
        words=words, cache_dir=cfg.cache_dir)
    emit("Legendando", "OK")

    emit("Ajustando visual")
    diff = human_dur - silent_dur
    silent = paths.silent_mp4
    visual_timeline = None
    if os.path.isfile(paths.visual_json):
        try:
            visual_timeline = _read_json(paths.visual_json)
        except json.JSONDecodeError:
            visual_timeline = None
    if abs(diff) <= 0.3:
        pass  # compatível: reusa o silencioso
    elif diff > 0:
        # Áudio mais longo: estende a ÚLTIMA cena (nunca corta a fala).
        adj = os.path.join(paths.root, "render", "silent_adj.mp4")
        if visual_timeline:
            chapters[-1].end = round(chapters[-1].end + diff, 3)
            _write_json(paths.timeline_json,
                        [c.to_dict() for c in chapters])
            visual_timeline = visual_stage.retime_visual_timeline(
                visual_timeline, chapters)
            _write_json(paths.visual_json, visual_timeline)
            _build_silent_visual(chapters, visual_timeline, idea, paths,
                                 cfg, adj)
        else:
            durations = [c.end - c.start for c in chapters]
            durations[-1] += diff
            _build_silent(chapters, media_scenes, idea, durations, paths,
                          cfg, adj)
        silent = adj
        warnings.append(f"última cena estendida +{diff:.1f}s p/ caber o áudio")
    else:
        warnings.append(f"áudio {abs(diff):.1f}s mais curto — cauda cortada")
    emit("Ajustando visual", "OK")

    emit("Merge final")
    total = round(human_dur + 0.5, 2)
    human_wav = paths.human_wav
    sfx_path = None
    if visual_timeline and cfg.visual_sfx:
        sfx_path = _sfx_track_for(visual_timeline, total, paths)
        if sfx_path:
            human_wav = _narration_with_sfx(paths.human_wav, sfx_path,
                                            total, paths)
    try:
        _meta_prev = _read_json(paths.metadata_json)
    except (json.JSONDecodeError, FileNotFoundError):
        _meta_prev = {}
    video_title = (_meta_prev.get("video_title") or "").strip() or None
    title_fontfile = subs_stage.ensure_display_font(cfg.cache_dir)[2]
    render_info = render_stage.burn_final(
        silent, paths.subs_ass, human_wav, paths.final_mp4, cfg, total,
        title=video_title, title_fontfile=title_fontfile)
    emit("Merge final", "OK")

    try:
        meta = _read_json(paths.metadata_json)
    except (json.JSONDecodeError, FileNotFoundError):
        meta = {}
    meta.update({
        "narration": "human",
        "duration_actual": round(render_info["duration"], 2),
        "audio_duration": round(human_dur, 2),
        "subtitle_cues": cue_count,
        "subtitle_source": "whisper",
        "transcription_model": f"faster-whisper/{cfg.whisper_model}",
        "finalize_warnings": warnings,
        "warnings": sorted(set(meta.get("warnings", []) + warnings)),
        "processing_time_seconds": round(time.monotonic() - started, 2),
    })
    meta.setdefault("artifacts", {})["video"] = paths.final_mp4
    meta["artifacts"]["human_audio"] = paths.human_wav
    meta["artifacts"]["transcription"] = paths.transcription_json
    if sfx_path:
        meta["artifacts"]["sfx"] = sfx_path
    _write_json(paths.metadata_json, meta)
    meta["metrics_file"] = metrics.save(meta, {"finalize": round(
        time.monotonic() - started, 2)}, cfg.metrics_dir)
    return meta
