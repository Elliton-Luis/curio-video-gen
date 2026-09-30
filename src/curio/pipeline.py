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
import hashlib
import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from . import ffmpeg as ff
from .audio import selection as audio_selection
from .audio.library import audio_seed
from .config import CurioConfig
from .media import download_asset, get_providers
from .media.providers import MediaAsset, MediaError, classify_rights
from .metrics import RunMetrics, backfill_from_metadata
from .slug import slugify, slugify_with_timestamp
from .stages import render as render_stage
from .stages import nvidia as nvidia_stage
from .stages import research as research_stage
from .stages import scenes as scenes_stage
from .stages import editorial as editorial_stage
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


def _scene_label(ch: Chapter) -> str:
    """Rótulo curto da cena para o registro de procedência.

    Prefere o assunto declarado pela IA (`subject`); sem ele, cai para as
    entidades visuais e, não havendo nenhuma, para o número da cena. É o
    que o autor lê no relatório para saber do que se trata.
    """
    partes = []
    for campo in ("subject", "visual_type"):
        val = str(getattr(ch, campo, "") or "").strip()
        if campo == "subject" and val:
            partes.append(val)
    ents = [str(e).strip() for e in (getattr(ch, "visual_entities", []) or [])
            if str(e).strip()]
    if not partes and ents:
        partes = ents[:2]
    if not partes:
        return f"cena {ch.id}"
    return f"cena {ch.id} · " + " / ".join(partes)[:70]


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


def _title_fontfile(cfg: CurioConfig, genre_key: str = "") -> str | None:
    """A fonte do título queimado, para este gênero.

    Sem gênero, é a fonte de exibição de sempre — o vídeo de quem não
    pediu nada não pode mudar de cara. Com gênero, é o papel `title` do
    perfil, resolvido: em `people` e `history` isso é uma serifada de
    leitura, e é a primeira coisa que separa "livro" de "post" num
    vídeo de 8 segundos que abre o quadro.

    O fallback entra sem consulta: se Minion Pro não está instalado, o
    título sai na serifada genérica da máquina, e isso é o combinado. O
    que não pode é voltar para a sans pesada e chamar isso de identidade.
    A fonte de exibição continua reservada às legendas, onde a
    legibilidade manda e o estilo não.
    """
    from .stages import typography as typo_stage
    if not genre_key:
        return subs_stage.ensure_display_font(cfg.cache_dir)[2]
    r = typo_stage.resolve(typo_stage.ROLE_TITLE, genre_key,
                           (cfg.typography or {}).get(genre_key))
    if r.path:
        return r.path
    return subs_stage.ensure_display_font(cfg.cache_dir)[2]


def _typography_report(cfg: CurioConfig, genre_key: str = "") -> dict:
    """O que a tipografia RESOLVEU, papel a papel, para o metadata.json.

    Sem isto, a única forma de saber com que fonte o vídeo saiu é
    rerenderizar e comparar. E há um caso em que isso não basta: uma
    família que responde em itálico mas não em reto, ou um par que o
    módulo escolheu por coerência em vez de por preferência. O autor
    precisa ler "quote: pedido Minion Pro Italic, respondeu Utopia
    Italic" no arquivo do próprio projeto, do mesmo jeito que lê as
    fontes da pesquisa.

    Só entra no metadata quando há gênero: sem ele a resposta é sempre a
    fonte de exibição, e um bloco de treze papéis com o mesmo valor
    dentro de todo projeto antigo é ruído.
    """
    from .stages import typography as typo_stage
    if not genre_key:
        return {}
    return typo_stage.for_genre(
        genre_key, (cfg.typography or {}).get(genre_key)).report()


def _build_silent(chapters: list[Chapter], media_scenes: list[dict], idea: str,
                   durations: list[float], paths: VideoPaths,
                   cfg: CurioConfig, out_path: str,
                   transitions: list[float] | None = None) -> str:
    assets = {s["chapter_id"]: s["asset"] for s in media_scenes}
    segs = []
    for i, (ch, dur) in enumerate(zip(chapters, durations)):
        segs.append(_scene_segment(ch, assets.get(ch.id), idea, round(dur, 1),
                                   paths, cfg, variant=i))
    return (render_stage.concat_with_transitions(segs, out_path, cfg, transitions)
            if transitions else render_stage.concat_copy(segs, out_path, cfg))


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
                         cfg: CurioConfig, out_path: str,
                         transitions: list[float] | None = None) -> str:
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
    return (render_stage.concat_with_transitions(segs, out_path, cfg, transitions)
            if transitions else render_stage.concat_copy(segs, out_path, cfg))


def _genre_transitions(chapters: list[Chapter], genre: str,
                       mode: str = "auto") -> list[float]:
    """Cross-dissolve por gênero e papel de cena; cortes dramáticos são secos."""
    if mode == "none" or not genre or len(chapters) < 2:
        return [0.0] * max(0, len(chapters) - 1)
    defaults = {"people": 0.34, "history": 0.25, "etymology": 0.16,
                "mythology": 0.40, "mystery": 0.38, "science": 0.16}
    base = defaults.get(genre, 0.20)
    result = []
    for chapter in chapters[1:]:
        text = (chapter.narration or "").lower()
        if any(k in text for k in ("morreu", "invadiu", "destruiu", "assassinado",
                                   "eclodiu", "de repente")):
            duration = 0.04  # dissolve de 1 frame: corte editorial seco
        elif any(k in text for k in ("na verdade", "descobriu", "revelou",
                                     "pela primeira vez", "mas foi")):
            duration = min(0.55, base + 0.18)
        elif chapter.text_role == "quote" or chapter.visual_type in (
                "typographic", "historical_art"):
            duration = min(0.55, base + 0.12)
        else:
            duration = base
        result.append(duration)
    return result


def _transition_signature(chapters: list[Chapter], genre: str, mode: str,
                           visual_identity: dict | None = None) -> str:
    transitions = _genre_transitions(chapters, genre, mode)
    payload = {"genre": genre, "mode": mode, "durations": transitions,
               "visual_identity": visual_identity or {},
               "scenes": [(c.id, c.visual_type, c.text_role, c.start, c.end)
                          for c in chapters]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


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


def _audio_events(visual_timeline: list[dict]) -> list[dict]:
    return [img["sfx"] for t in visual_timeline for img in t.get("images", [])
            if isinstance(img.get("sfx"), dict)]


def _final_audio_fade(genre: str, transitions: str = "auto") -> float:
    if transitions == "none" or not genre:
        return 0.0
    return {"people": 0.8, "history": 0.65, "etymology": 0.35,
            "mythology": 0.75, "mystery": 0.7, "science": 0.3}.get(genre, 0.0)


def _transition_mode(cfg: CurioConfig) -> str:
    """Audio ausente em projetos antigos preserva cuts e render legado."""
    active = bool(getattr(cfg, "audio_enabled", False)) or cfg.music_mode != "auto"
    return cfg.music_transitions if active else "none"


def _mark_audio_used(cfg: CurioConfig, plan: dict) -> None:
    try:
        audio_selection.mark_used(
            cfg.audio_library_dir, plan.get("music_asset"),
            plan.get("sfx_assets") or [])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"AVISO: não foi possível atualizar uso da biblioteca de áudio: {exc}",
              file=sys.stderr)


def _apply_audio_request(cfg: CurioConfig, audio: dict | None) -> None:
    """Reaplica a escolha gravada no projeto (especialmente human-pending)."""
    if not isinstance(audio, dict):
        return
    cfg.audio_enabled = True
    music = audio.get("music") if isinstance(audio.get("music"), dict) else {}
    if music.get("mode") in ("auto", "none", "manual"):
        cfg.music_mode = music["mode"]
    if music.get("gain_db") is not None:
        cfg.music_gain_db = max(-40, min(-15, int(music["gain_db"])))
    if music.get("ducking") is not None:
        cfg.music_ducking = bool(music["ducking"])
    track = music.get("track") if isinstance(music.get("track"), dict) else {}
    if cfg.music_mode == "manual" and track.get("path"):
        cfg.music_file = str(track["path"])
    transitions = audio.get("transitions")
    if isinstance(transitions, dict) and transitions.get("mode") in ("auto", "none"):
        cfg.music_transitions = transitions["mode"]


def _print_grounding_warning(grounding: dict) -> str:
    """O aviso de grounding: afirmação, trecho, causa e fontes avaliadas.

    Antes saía "2 dado(s) do roteiro sem correspondência nas fontes: 135,
    393". 135 e 393 são números, não identificadores: com dezenas de
    números no texto, o aviso não levava ninguém a lugar nenhum — e era
    justamente o aviso que ninguém podia descartar, porque ele aponta
    onde o roteiro pode estar inventando.

    Sai a afirmação, onde ela está no texto, por que ela provavelmente não
    bate e quais fontes foram conferidas. O gate não muda nada disso: a
    contagem e a cobertura são as mesmas de antes, porque quem decide o que
    é verificável é `verify_grounding`, não a frase.

    O corpo sai no stderr e a frase de uma linha volta para `warnings`, que
    é o que vai para o metadata.json. Existe como função separada do fluxo
    para poder ser testada e reaproveitada — não há segunda versão dela.
    """
    n = len(grounding["unverified"])
    det = grounding.get("unverified_display") or []
    msg = (f"{n} {'afirmações' if n > 1 else 'afirmação'} do roteiro sem "
           f"correspondência nas fontes")
    print(f"AVISO: {msg}:", file=sys.stderr)
    for d in det[:8]:
        print(f"  - {d['fact']}: \"{d['claim']}\"", file=sys.stderr)
        print(f"      possível causa: {d['cause']}", file=sys.stderr)
    mais = len(det) - 8
    if mais > 0:
        print(f"  ... e {mais} {'outras' if mais > 1 else 'outra'}. "
              f"Ver o relatório completo.", file=sys.stderr)
    print(f"  Fontes avaliadas: "
          f"{', '.join(grounding.get('sources_checked', [])[:6])}",
          file=sys.stderr)
    print("  Consulte sources/FONTES.md para as fontes relacionadas.",
          file=sys.stderr)
    return msg


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
                 visual_overlap: float | None = None,
                 genre: str | None = None) -> dict:
    started = time.monotonic()
    stage_times: dict[str, float] = {}
    warnings: list[str] = []
    stages = STAGES_HUMAN if narration == "human" else STAGES_AI
    script_mode = provided_script is not None
    max_images = max(1, min(5, int(max_images or 1)))
    # Gênero: parâmetro explícito > config. Sem chave, `perfil` é None e
    # nada abaixo muda de comportamento — é a compatibilidade com os
    # projetos anteriores ao recurso.
    genre_key = (genre if genre is not None else cfg.genre) or ""
    perfil = editorial_stage.get(genre_key)
    pacing = perfil.pacing if perfil is not None else None
    alvo_cena = pacing.target_scene_seconds if pacing is not None else 9.0
    # Tratamento da legenda: caixa alta, relevo, destaque por palavra. É
    # apresentação e mora no perfil TIPOGRÁFICO, não no editorial — a
    # fonte de exibição continua a mesma por legibilidade, e a
    # sincronia não é tocada. `None` sem gênero = comportamento antigo.
    from .stages import typography as _typo_stage
    cap_style = _typo_stage.profile_for(genre_key).captions
    # `None` de propósito: sem gênero, scenes_for_* usa o teto legado e o
    # vídeo de quem não pediu nada sai com o mesmo nº de cenas de sempre.
    teto_cena = pacing.max_scenes if pacing is not None else None
    genre_directive = editorial_stage.script_directive(perfil)
    scene_directive = editorial_stage.scene_directive(perfil)
    if perfil is not None:
        print(f"Gênero: {perfil.label} — pacing {alvo_cena:g}s/cena, "
              f"até {teto_cena} cenas, "
              f"forma visual {', '.join(perfil.visual.preferred_forms) or '—'}")
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
    if not cfg.audio_enabled and cfg.music_mode == "auto":
        try:
            previous_project = _read_json(paths.metadata_json)
        except (OSError, ValueError, json.JSONDecodeError):
            previous_project = {}
        if previous_project.get("audio"):
            _apply_audio_request(cfg, previous_project["audio"])
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
    research = research_stage.research_topic(
        idea, cfg.language, max_sources=cfg.research_max_sources,
        metrics=metrics, timeout=cfg.research_timeout, cfg=cfg,
        genre=genre_key)
    research_sources = list(research)
    research_target = getattr(research, "target", None)
    research_rejected = list(getattr(research, "rejected", []))
    research_queries = list(getattr(research, "tried_queries", []))
    research_status = ("confirmed" if len(research_sources) >= 2
                       else "partial")
    for rs in research_sources:
        sources.add_claim(
            claim=rs.title, title=rs.title, url=rs.url,
            evidence=rs.snippet[:300], status=research_status,
            notes=f"RAG web ({rs.origin})")
    _write_json(paths.research_json, {
        "idea": idea,
        # A entidade-alvo fica no arquivo: sem ela não há como auditar,
        # depois, por que uma fonte sobre "Serra Gaúcha" entrou num vídeo
        # sobre um santo do século VI.
        "target_entity": (research_target.to_dict()
                          if research_target is not None else None),
        "queries": research_queries,
        "sources": [rs.to_dict() for rs in research_sources],
        "rejected": [{"title": s.title, "url": s.url, "reason": m,
                      "detail": d} for s, m, d in research_rejected],
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
        # A entidade JÁ foi resolvida na etapa de pesquisa; o roteiro
        # recebia só a frase da ideia e perdia o nome canônico, as formas
        # alternativas e as armadilhas de homônimo. Nenhuma segunda
        # resolução acontece aqui: é o mesmo objeto.
        from .stages import entity as entity_stage
        script_text, script_source = script_stage.generate_script(
            idea, cfg, metrics, research=research_pack,
            genre_directive=genre_directive,
            entity_context=entity_stage.script_context(
                research_target, cfg.language))
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
        warnings.append(_print_grounding_warning(grounding))
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
            n = visual_stage.scenes_for_script(script_text, cfg, genre_key)
        elif cfg.duration_target <= 0:
            # Automático: o roteiro (não a meta) define as cenas — e o
            # pacing do gênero entra no cálculo do tamanho de cada cena.
            n = scenes_stage.scenes_for_length(len(script_text.split()),
                                               alvo_cena, teto_cena)
        else:
            n = scenes_stage.scenes_for_duration(cfg.duration_target,
                                                 alvo_cena, teto_cena)
        try:
            chapters, scenes_source = scenes_stage.build_chapters(
                script_text, cfg, n_scenes=n, metrics=metrics,
                genre=genre_key, target_seconds=alvo_cena,
                genre_directive=scene_directive, max_scenes=teto_cena)
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
                chapters, cfg, max_images, metrics, genre=genre_key)
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
    credits: list[str] = []
    # Rótulo curto do assunto de cada cena, para o título do registro:
    # "cena 3 · rolo de papel térmico [pixabay_12345]" diz do que se trata;
    # "cena 3 [pixabay_12345]" só diz onde.
    rotulos = {c.id: _scene_label(c) for c in chapters}
    for scene in media_scenes:
        rotulo = rotulos.get(scene["chapter_id"], f"cena {scene['chapter_id']}")
        for entry in scene.get("assets") or []:
            asset = entry.get("asset") or {}
            if not asset.get("local_path"):
                continue
            rights = asset.get("rights_status", "") or classify_rights(
                asset.get("license", ""), asset.get("provider", ""))
            asset["rights_status"] = rights
            # O título do registro passa a ser a cena + o id da imagem.
            # Antes era a tag crua do provedor ("4k wallpaper hd thermal
            # printer technology"), que não diz do que se trata nem localiza
            # a imagem. A tag original continua em `asset["title"]`.
            registro_titulo = sources_stage.media_record_title(
                scene_label=rotulo,
                provider=asset.get("provider", ""),
                asset_id=asset.get("asset_id", ""),
                fallback=str(asset.get("title", ""))[:80])
            sources.add_media(
                title=registro_titulo,
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
                scene=f"cena {scene['chapter_id']}",
                asset_id=asset.get("asset_id", ""))
            # Crédito pronto quando a licença exige atribuição: CC BY/SA
            # permitem editar mas obrigam a citar, e o classificador de
            # direitos responde a "posso editar", não a "tenho que citar".
            if sources_stage.requires_attribution(asset.get("license", "")):
                credito = sources_stage.credit_line(
                    author=asset.get("author", ""),
                    title=asset.get("title", ""),
                    license_text=asset.get("license", ""),
                    source_url=asset.get("source_url", ""),
                    license_url=asset.get("license_url", ""))
                if credito not in credits:
                    credits.append(credito)
                if asset.get("author", "").strip() == "":
                    nota = (f"cena {scene['chapter_id']}: "
                            f"'{asset.get('title', '')[:50]}' tem licença que "
                            f"exige atribuição mas o acervo não informou o autor "
                            f"({asset.get('license')}) — confira em "
                            f"{asset.get('license_url') or asset.get('source_url') or 'sem link'}")
                    if nota not in media_rights_notes:
                        media_rights_notes.append(nota)
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
                           insert_budget=insert_budget,
                           genre_key=genre_key,
                           transition_mode=_transition_mode(cfg),
                           genre_profile=editorial_stage.summary(perfil),
                           video_title=video_title,
                           title_source=title_source)

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
    # O TRATAMENTO da legenda vem do perfil tipográfico, não do editorial:
    # caixa alta e relevo são apresentação, e a fonte de exibição já está
    # garantida por legibilidade. Um vídeo sem gênero recebe `None` e sai
    # exatamente como antes.
    cue_count = subs_stage.write_subtitles(
        script_text, audio_duration, paths.subs_srt, paths.subs_ass,
        cfg.width, cfg.height, cfg.sub_font_size, cfg.sub_margin_v,
        words=words if tts_info["provider"] == "edge-tts" else None,
        cache_dir=cfg.cache_dir,
        max_words=(pacing.caption_max_words if pacing is not None
                   else subs_stage.MAX_WORDS_PER_CUE),
        highlight=(pacing.caption_highlight if pacing is not None else "word"),
        **({"upper": cap_style.upper, "karaoke": cap_style.karaoke,
            "outline": cap_style.outline, "shadow": cap_style.shadow}
           if cap_style is not None else {}))
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
    try:
        previous_meta = _read_json(paths.metadata_json)
    except (OSError, ValueError, json.JSONDecodeError):
        previous_meta = {}
    previous_audio = previous_meta.get("audio") or {}
    transition_mode = _transition_mode(cfg)
    transition_sig = _transition_signature(
        chapters, genre_key, transition_mode,
        {"insertions": insert_budget,
         "insert_style": cfg.visual_insert_style,
         "insert_gain_db": cfg.visual_insert_gain_db,
         "visual_sfx": cfg.visual_sfx})
    legacy_audio_cache = not cfg.audio_enabled and not previous_audio
    transition_dirty = (
        previous_meta.get("visual_transition_signature") != transition_sig
        and not (legacy_audio_cache and transition_mode == "none"))
    events = _audio_events(visual_timeline)
    audio_plan = audio_selection.resolve_audio(
        cfg, genre_key,
        audio_seed(slug, video_title or idea, script_text),
        video_title or idea, script_text, events, previous_audio)
    warnings.extend(audio_plan["warnings"])
    new_audio_meta = audio_plan["metadata"]
    audio_cache_matches = (
        previous_audio.get("signature") == new_audio_meta.get("signature")
        or legacy_audio_cache)
    if (not force and not subs_changed and not transition_dirty and
            audio_cache_matches and
            os.path.isfile(paths.final_mp4)):
        video_duration = ff.probe_duration(paths.final_mp4)
        render_info = {"backend": "cache", "encoder": "cache",
                       "duration": video_duration, "path": paths.final_mp4}
        sfx_path = (previous_meta.get("artifacts") or {}).get("sfx")
    else:
        silent = paths.silent_mp4
        if force or transition_dirty or not os.path.isfile(silent):
            transitions = _genre_transitions(
                chapters, genre_key, transition_mode)
            if visual_timeline:
                _build_silent_visual(chapters, visual_timeline, idea, paths,
                                     cfg, silent, transitions=transitions)
            else:
                _build_silent(chapters, media_scenes, idea, durations, paths,
                              cfg, silent, transitions=transitions)
        narration_wav = paths.narration_wav
        sfx_path = (_sfx_track_for(visual_timeline, total, paths)
                    if visual_timeline and cfg.visual_sfx else None)
        if sfx_path:
            narration_wav = _narration_with_sfx(paths.narration_wav, sfx_path,
                                                total, paths)
        music_asset = audio_plan.get("music_asset")
        music_path = str(music_asset.get("path")) if music_asset else None
        final_fade = _final_audio_fade(genre_key, transition_mode)
        render_info = render_stage.burn_final(
            silent, paths.subs_ass, narration_wav, paths.final_mp4,
            cfg, total, title=video_title,
            title_fontfile=_title_fontfile(cfg, genre_key),
            music_path=music_path, music_gain_db=cfg.music_gain_db,
            music_ducking=cfg.music_ducking, final_fade=final_fade)
        video_duration = render_info["duration"]
        _mark_audio_used(cfg, audio_plan)
    stage_times["render"] = round(time.monotonic() - t0, 2)
    emit(6, "Montando vídeo", "OK")

    metadata = _base_metadata(idea, slug, cfg, script_text, script_source,
                              chapters, scenes_source, media_scenes, warnings,
                              stage_times, started)
    metadata.update({
        "genre": genre_key,
        "genre_profile": editorial_stage.summary(perfil),
        "typography": _typography_report(cfg, genre_key),
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
        "audio": new_audio_meta,
        "visual_transition_signature": transition_sig,
        "visual_transitions": {
            "genre": genre_key,
            "mode": transition_mode,
            "boundary_durations": _genre_transitions(
                chapters, genre_key, transition_mode),
            "final_fade": _final_audio_fade(genre_key, transition_mode),
        },
        "sources": {
            "claims": len(sources.claims),
            "media": len(sources.media),
            "report": paths.sources_report,
            "blocked_media": sum(1 for m in sources.media
                                 if m.rights_status == "blocked"),
            # Créditos prontos: só entra o que a licença exige de fato.
            "credits": credits,
        },
        "research": {
            "sources": len(research_sources),
            "status": research_status,
            "titles": [rs.title for rs in research_sources],
            "grounding": grounding,
            "target_entity": (research_target.to_dict()
                              if research_target is not None else None),
            "rejected": [{"title": s.title, "reason": m}
                         for s, m, _d in research_rejected],
        },
        # Como cada cena foi visualizada e por que as outras não foram.
        # `sem_visual` é a única métrica que é problema: diagrama e cartão
        # contam como visual, não como falha.
        "visual_report": metrics.media_visual_report(len(chapters)),
        # Por provedor: candidatos achados × downloads tentados ×
        # 403. Responde a pergunta que o log de "download falhou" deixava
        # em aberto — o provedor está vazio ou está baixando mal?
        "provider_downloads": metrics.media_download_report(),
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
            **({"music": audio_plan["music_asset"]["path"]}
               if audio_plan.get("music_asset") else {}),
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
                               media_notes=media_rights_notes, credits=credits)
    # Folha de contato: o autor revisa o vídeo em ~1 min sem assistir.
    if media_scenes:
        from .stages import review as review_stage
        review_stage.write_contact_sheet(
            paths.contact_sheet, chapters, media_scenes, paths.root, slug,
            threshold=scoring_stage.threshold(), genre=genre_key,
            typography=_typography_report(cfg, genre_key))
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
                insert_budget: int = 0, genre_key: str = "",
                transition_mode: str = "auto",
                genre_profile: dict | None = None,
                video_title: str = "", title_source: str = "") -> dict:
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
    audio_events = _audio_events(visual_timeline)
    try:
        previous_meta = _read_json(paths.metadata_json)
    except (OSError, ValueError, json.JSONDecodeError):
        previous_meta = {}
    audio_plan = audio_selection.resolve_audio(
        cfg, genre_key,
        audio_seed(slug, video_title or idea, script_text),
        video_title or idea, script_text, audio_events,
        previous_meta.get("audio_request") or previous_meta.get("audio"))
    warnings.extend(audio_plan["warnings"])
    stage_times["timeline"] = round(time.monotonic() - t0, 2)
    emit(4, "Estimando timeline", "OK")

    # [5/6] Vídeo silencioso
    t0 = time.monotonic()
    emit(5, "Montando silencioso")
    if visual_timeline:
        _build_silent_visual(chapters, visual_timeline, idea, paths, cfg,
                             paths.silent_mp4, transitions=_genre_transitions(
                                 chapters, genre_key, transition_mode))
    else:
        durations = [c.end - c.start for c in chapters]
        _build_silent(chapters, media_scenes, idea, durations, paths, cfg,
                      paths.silent_mp4, transitions=_genre_transitions(
                          chapters, genre_key, transition_mode))
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
        "genre": genre_key,
        "audio_request": audio_plan["metadata"],
        "visual_transition_signature": _transition_signature(
            chapters, genre_key, transition_mode,
            {"insertions": insert_budget,
             "insert_style": cfg.visual_insert_style,
             "insert_gain_db": cfg.visual_insert_gain_db,
             "visual_sfx": cfg.visual_sfx}),
        "visual_transitions": {
            "genre": genre_key, "mode": transition_mode,
            "boundary_durations": _genre_transitions(
                chapters, genre_key, transition_mode),
            "final_fade": _final_audio_fade(genre_key, transition_mode),
        },
        "genre_profile": genre_profile or editorial_stage.summary(None),
        "typography": _typography_report(cfg, genre_key),
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
        meta = {}
        idea = slug
    saved_audio = meta.get("audio_request") or meta.get("audio")
    if saved_audio:
        _apply_audio_request(cfg, saved_audio)
    else:
        cfg.audio_enabled = False
        cfg.music_mode = "none"
        cfg.music_transitions = "none"
        cfg.sfx_library_enabled = False
        cfg.music_auto_fill = cfg.sfx_auto_fill = False
    project_genre = str(meta.get("genre") or cfg.genre or "")
    transition_mode = _transition_mode(cfg)

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
    from .stages import editorial as _ed
    _perfil = _ed.get((meta or {}).get("genre", ""))
    _pac = _perfil.pacing if _perfil is not None else None
    cue_count = subs_stage.write_subtitles(
        "", human_dur, paths.subs_srt, paths.subs_ass,
        cfg.width, cfg.height, cfg.sub_font_size, cfg.sub_margin_v,
        words=words, cache_dir=cfg.cache_dir,
        max_words=(_pac.caption_max_words if _pac is not None
                   else subs_stage.MAX_WORDS_PER_CUE),
        highlight=(_pac.caption_highlight if _pac is not None else "word"))
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
                                 cfg, adj, transitions=_genre_transitions(
                                      chapters, project_genre, transition_mode))
        else:
            durations = [c.end - c.start for c in chapters]
            durations[-1] += diff
            _build_silent(chapters, media_scenes, idea, durations, paths,
                           cfg, adj, transitions=_genre_transitions(
                               chapters, project_genre, transition_mode))
        silent = adj
        warnings.append(f"última cena estendida +{diff:.1f}s p/ caber o áudio")
    else:
        warnings.append(f"áudio {abs(diff):.1f}s mais curto — cauda cortada")
    emit("Ajustando visual", "OK")

    emit("Merge final")
    total = round(human_dur + 0.5, 2)
    human_wav = paths.human_wav
    sfx_path = None
    events = _audio_events(visual_timeline or [])
    script_text = _read(paths.script_txt) if os.path.isfile(paths.script_txt) else ""
    video_title = (meta.get("video_title") or "").strip()
    audio_plan = audio_selection.resolve_audio(
        cfg, project_genre, audio_seed(slug, video_title or idea, script_text),
        video_title or idea, script_text, events,
        meta.get("audio") or meta.get("audio_request"))
    warnings.extend(audio_plan["warnings"])
    if visual_timeline and cfg.visual_sfx:
        sfx_path = _sfx_track_for(visual_timeline, total, paths)
        if sfx_path:
            human_wav = _narration_with_sfx(paths.human_wav, sfx_path,
                                            total, paths)
    video_title = video_title or None
    music_asset = audio_plan.get("music_asset")
    render_info = render_stage.burn_final(
        silent, paths.subs_ass, human_wav, paths.final_mp4, cfg, total,
        title=video_title,
        title_fontfile=_title_fontfile(cfg,
                                       project_genre),
        music_path=str(music_asset.get("path")) if music_asset else None,
        music_gain_db=cfg.music_gain_db,
        music_ducking=cfg.music_ducking,
        final_fade=_final_audio_fade(project_genre, transition_mode))
    _mark_audio_used(cfg, audio_plan)
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
        "audio": audio_plan["metadata"],
        "visual_transition_signature": _transition_signature(
            chapters, project_genre, transition_mode,
            {"insertions": cfg.visual_insertions,
             "insert_style": cfg.visual_insert_style,
             "insert_gain_db": cfg.visual_insert_gain_db,
             "visual_sfx": cfg.visual_sfx}),
        "visual_transitions": {
            "genre": project_genre, "mode": transition_mode,
            "boundary_durations": _genre_transitions(
                chapters, project_genre, transition_mode),
            "final_fade": _final_audio_fade(
                project_genre, transition_mode),
        },
        "finalize_warnings": warnings,
        "warnings": sorted(set(meta.get("warnings", []) + warnings)),
        "processing_time_seconds": round(time.monotonic() - started, 2),
    })
    meta.setdefault("artifacts", {})["video"] = paths.final_mp4
    meta["artifacts"]["human_audio"] = paths.human_wav
    meta["artifacts"]["transcription"] = paths.transcription_json
    if sfx_path:
        meta["artifacts"]["sfx"] = sfx_path
    if music_asset:
        meta["artifacts"]["music"] = music_asset["path"]
    _write_json(paths.metadata_json, meta)
    meta["metrics_file"] = metrics.save(meta, {"finalize": round(
        time.monotonic() - started, 2)}, cfg.metrics_dir)
    return meta
