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
import time
from copy import deepcopy
from datetime import datetime, timezone

from . import ffmpeg as ff
from .audio import selection as audio_selection
from .audio.library import audio_seed
from .audio import composition as audio_composition
from .config import CurioConfig
from . import pipeline_render as pipeline_render_stage
from . import pipeline_research as pipeline_research_stage
from . import pipeline_scenes as pipeline_scenes_stage
from . import pipeline_media as pipeline_media_stage
from . import pipeline_visual as pipeline_visual_stage
from . import pipeline_media_sources as pipeline_media_sources_stage
from . import pipeline_audio as pipeline_audio_stage
from . import pipeline_timeline as pipeline_timeline_stage
from . import pipeline_metadata as pipeline_metadata_stage
from . import pipeline_finalize as pipeline_finalize_stage
from . import pipeline_human_prep
from . import pipeline_script as pipeline_script_stage
from .metrics import RunMetrics
from .runlog import (RunLog, current_log_path, event as run_event,
                     format_exception, set_stage as set_log_stage)
from .slug import slugify_with_timestamp
from .slug import unique_slug
from . import project_paths
from . import project_artifacts
from .stages import render as render_stage
from .stages import editorial as editorial_stage
from .stages import scoring as scoring_stage
from .stages import sources as sources_stage

STAGES_AI = ["roteiro", "cenas", "mídia", "narração", "legendas", "montagem"]
STAGES_HUMAN = ["roteiro", "cenas", "mídia", "timeline", "silencioso",
                "teleprompter"]


def _resolve_paths(out_dir: str, slug: str | None, idea: str,
                    genre_key: str, force: bool = False,
                    ) -> tuple[str, project_paths.VideoPaths]:
    """Slug final + caminhos, com pasta de gênero e anti-colisão.

    Sem slug explícito, gera `AAAAMMDD_titulo`; com gênero, a pasta é
    `output/<genero>/<slug>`. Em rerun (`force` ou mesma ideia) reutiliza;
    em colisão com outra ideia, sufixa `-2`, `-3`…
    """
    final = slug or slugify_with_timestamp(idea)
    if slug is None and not force:
        # Só o slug AUTOMÁTICO ganha anti-colisão: slug explícito é
        # endereço exato (retomada de cache/standby/rerun depende disso).
        final = unique_slug(out_dir, genre_key, final, idea)
    return final, project_paths.video_paths(out_dir, final, genre_key)


def run_pipeline(idea: str, cfg: CurioConfig, slug: str | None = None,
                 force: bool = False, narration: str = "ai",
                 on_progress=None, provided_script: str | None = None,
                 max_images: int = 1,
                 visual_overlap: float | None = None,
                 genre: str | None = None, on_event=None) -> dict:
    # Per-project audio requests and finalize policy may adjust scalars; never
    # let those adjustments leak into a TUI/queue caller's shared config.
    cfg = deepcopy(cfg)
    genre_key = (genre if genre is not None else cfg.genre) or ""
    run_slug, paths = _resolve_paths(cfg.out_dir, slug, idea, genre_key,
                                     force)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    log_path = os.path.join(paths.root, "logs", f"run-{stamp}.jsonl")
    started = time.monotonic()
    with RunLog(log_path, run_slug, on_event) as runlog:
        run_event("log_ready", f"Log: {log_path}", log_path=log_path)
        try:
            result = _run_pipeline(
                idea, cfg, slug=run_slug, force=force, narration=narration,
                on_progress=on_progress, provided_script=provided_script,
                max_images=max_images, visual_overlap=visual_overlap,
                genre=genre)
        except BaseException as exc:
            if isinstance(exc, pipeline_media_stage.MediaStandby):
                runlog.event("run_standby", "Execução em standby",
                             error_type=type(exc).__name__, reason=str(exc))
                raise
            runlog.event(
                "run_interrupted" if isinstance(exc, KeyboardInterrupt)
                else "run_failed",
                "Execução interrompida" if isinstance(exc, KeyboardInterrupt)
                else "Execução falhou", error_type=type(exc).__name__,
                error=str(exc), traceback=format_exception(exc))
            raise
        runlog.event("run_completed", "Execução concluída",
                     duration_seconds=round(time.monotonic() - started, 2),
                     metrics_file=result.get("metrics_file"),
                     output=result.get("artifacts", {}).get("video")
                     or result.get("artifacts", {}).get("teleprompter"))
        return result


def _run_pipeline(idea: str, cfg: CurioConfig, slug: str | None = None,
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
    if perfil is not None:
        print(f"Gênero: {perfil.label} — pacing {alvo_cena:g}s/cena, "
              f"até {teto_cena} cenas, "
              f"forma visual {', '.join(perfil.visual.preferred_forms) or '—'}")
    overlap_cap = float(cfg.visual_overlap if visual_overlap is None
                        else visual_overlap)
    # Fotos complementares: o orçamento de EXIBIÇÃO é do vídeo (1–2), não da
    # cena. A busca, porém, traz 3 candidatos por cena de propósito: a
    # inserção tem de ser a imagem mais precisa sobre o assunto, e escolher
    # a melhor exige mais de uma opção. Todas as fotos aprovadas podem alternar
    # como fundos; o orçamento de inserções limita somente as sobreposições.
    insert_budget = int(cfg.visual_insertions)
    if insert_budget > 0:
        max_images = 3

    def emit(idx: int, label: str, status: str = "…") -> None:
        stage_key = {"Pesquisando fontes": "research",
                     "Gerando roteiro": "script",
                     "Lendo roteiro pronto": "script",
                     "Interpretando cenas": "scenes",
                     "Buscando mídia": "media",
                     "Gerando narração": "tts",
                     "Sincronizando legendas": "subs",
                     "Montando vídeo": "render",
                     "Estimando timeline": "timeline",
                     "Montando silencioso": "silent",
                     "Gerando teleprompter": "teleprompter"}.get(label)
        stage = stage_key or (stages[idx] if 0 <= idx < len(stages) else label)
        set_log_stage(stage)
        if status == "…":
            run_event("stage_started", label)
        else:
            elapsed = stage_times.get(stage_key) if stage_key else None
            if elapsed is not None and status == "OK":
                status = f"OK ({elapsed:.1f}s)"
            run_event("stage_finished" if status.startswith("OK") else "stage_status",
                      label, status=status, duration_seconds=elapsed)
        if on_progress:
            on_progress(idx, len(stages), label, status)

    slug, paths = _resolve_paths(cfg.out_dir, slug, idea, genre_key,
                                   force)
    if not cfg.audio_enabled and cfg.music_mode == "auto":
        try:
            previous_project = project_artifacts.read_json(paths.metadata_json)
        except (OSError, ValueError, json.JSONDecodeError):
            previous_project = {}
        if previous_project.get("audio"):
            audio_composition.apply_audio_request(cfg, previous_project["audio"])
    metrics = RunMetrics(slug, idea, narration)
    for d in ("script", "audio", "subtitles", "assets", "render",
              "media", "timeline", "teleprompter", "sources"):
        os.makedirs(os.path.join(paths.root, d), exist_ok=True)
    sources = sources_stage.SourceRegistry.load(paths.sources_json)
    sources.slug = slug

    # [0/6] Pesquisa é um estágio. Pipeline só passa dependências e recebe
    # contexto/estado para roteiro, cenas e metadados seguintes.
    research_output = pipeline_research_stage.run_research_stage(
        idea, cfg, paths, metrics, genre_key, warnings, sources, emit,
        project_artifacts.write_json)
    research = research_output.result
    research_sources = research.sources
    research_target = research.target
    research_rejected = research.rejected
    research_etymology = research.etymology
    research_status = research_output.status
    research_pack = research_output.prompt
    stage_times["research"] = research_output.elapsed

    # [1/6] Roteiro e título: transforma inputs pesquisados em artefatos validados.
    emit(1, "Lendo roteiro pronto" if script_mode else "Gerando roteiro")
    script_result = pipeline_script_stage.run_script_stage(
        idea, cfg, paths, metrics, research_prompt=research_pack,
        research_target=research_target, research_sources=research_sources,
        genre_directive=genre_directive, force=force,
        provided_script=provided_script)
    script_artifact, title_artifact = script_result.script, script_result.title
    script_text, script_source = script_artifact.text, script_artifact.source
    video_title, title_source = title_artifact.text, title_artifact.source
    grounding = script_result.grounding
    force_after_script = script_result.force_scenes
    warnings.extend(script_result.warnings)
    stage_times["script"] = script_result.elapsed
    emit(1, "Lendo roteiro pronto" if script_mode else "Gerando roteiro", "OK")

    # [2/6] Cenas
    emit(2, "Interpretando cenas")
    scene_etymology = (research_etymology
                       if perfil and "wiktionary" in perfil.specialized_sources
                       else None)
    scene_result = pipeline_scenes_stage.run_scene_stage(
        script_text, cfg, paths, force=force_after_script,
        script_mode=script_mode, genre=genre_key,
        scene_target_seconds=alvo_cena, max_scenes=teto_cena,
        scene_directive=editorial_stage.scene_directive(perfil), topic=idea,
        target=research_target, research_sources=research_sources,
        research_timeout=cfg.research_timeout, etymology=scene_etymology,
        metrics=metrics, warnings=warnings, write_json=project_artifacts.write_json)
    semantic_scenes = list(scene_result.semantic_scenes)
    timeline_spans = scene_result.timeline_spans
    scenes_source = scene_result.source
    enrichment = scene_result.enrichment
    force_after_script = force_after_script or scene_result.invalidate_media
    stage_times["scenes"] = scene_result.elapsed
    emit(2, "Interpretando cenas", "OK")

    # [3/6] Mídia (manual > cache > provedores; zero imagens = standby)
    media_t0 = time.monotonic()
    manual_dir = pipeline_media_stage.manual_media_dir(paths)
    emit(3, "Buscando mídia")
    media_result = pipeline_visual_stage.resolve_media(
        semantic_scenes, cfg, paths, max_images, genre_key, metrics,
        force_after_script, project_artifacts.write_json)
    media_scenes = media_result.to_rows()
    media_render_plan = pipeline_render_stage.SceneRenderPlan.from_media_result(
        media_result)
    warnings.extend(media_result.warnings)
    provenance = pipeline_media_sources_stage.record_selected_media(
        semantic_scenes, media_result.scenes, sources)
    media_rights_notes = list(provenance.rights_notes)
    credits = list(provenance.credits)
    stage_times["media"] = round(time.monotonic() - media_t0, 2)
    emit(3, "Buscando mídia",
         "AVISO" if media_result.scenes_without_visual else "OK")

    # Sem nenhuma imagem o vídeo NÃO é produzido: standby até fotos manuais.
    if media_result.selected_asset_count == 0:
        pipeline_media_stage.write_manual_readme(manual_dir, slug, len(semantic_scenes))
        sources.save(paths.sources_json)
        sources_stage.write_report(paths.sources_report, sources,
                                   research=research_sources, grounding=grounding)
        project_artifacts.write_json(paths.metadata_json, {
            "slug": slug,
            "idea": idea,
            "status": "standby-no-media",
            "narration": "standby",
            "media_resolution_source": media_result.source,
            "manual_dir": manual_dir,
            "n_scenes": len(semantic_scenes),
            "stage_times": dict(stage_times),
            "warnings": list(warnings),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "execution_log": current_log_path(),
        })
        emit(3, "Buscando mídia", "STANDBY")
        raise pipeline_media_stage.MediaStandby(slug, manual_dir, len(semantic_scenes))

    if narration == "human":
        return pipeline_human_prep.prepare_human_project(
            idea, slug, cfg, paths, script_text, script_source,
            tuple(semantic_scenes), scenes_source, media_result, warnings,
            stage_times, started, emit, metrics,
            script_mode=script_mode, max_images=max_images,
            overlap_cap=overlap_cap,
            insert_budget=insert_budget,
            genre_key=genre_key,
            transition_mode=audio_composition.transition_mode(cfg),
            genre_profile=editorial_stage.summary(perfil),
            scene_context_enrichment=enrichment.to_dict(),
            media_source=media_result.source,
            source_registry=sources,
            research_sources=research_sources,
            grounding=grounding,
            media_rights_notes=media_rights_notes,
            credits=credits,
            video_title=video_title,
            title_source=title_source)

    # [4/6] Narração, alinhamento e legendas são um estágio coeso.
    audio_force = force or script_result.script_changed
    audio_result = pipeline_audio_stage.run_audio_stages(
        script_text, tuple(semantic_scenes), timeline_spans,
        paths, cfg, audio_force, metrics, emit,
        project_artifacts.write_json, pacing=pacing, caption_style=cap_style)
    timeline_spans = audio_result.timeline_spans
    words = audio_result.words
    audio_duration = audio_result.audio_duration
    tts_info = audio_result.tts_info
    timed_source = audio_result.timed_source
    cue_count = audio_result.cue_count
    subs_changed = audio_result.subtitles_changed
    warnings.extend(audio_result.warnings)
    stage_times.update(audio_result.stage_times)

    timeline_result = pipeline_timeline_stage.build_visual_timeline(
        tuple(semantic_scenes), timeline_spans, media_result,
        paths, slug, overlap_cap, cfg.visual_sfx,
        insert_budget, cfg.visual_insert_style, cfg.visual_insert_gain_db,
        max_images > 1, metrics, project_artifacts.write_json)
    visual_timeline = timeline_result.entries

    # [6/6] Montagem dinâmica + final
    t0 = time.monotonic()
    emit(6, "Montando vídeo")
    durations = [max(0.5, span.end - span.start) for span in timeline_spans]
    total = round(audio_duration + 0.8, 2)
    sfx_path = None
    try:
        previous_meta = project_artifacts.read_json(paths.metadata_json)
    except (OSError, ValueError, json.JSONDecodeError):
        previous_meta = {}
    previous_audio = previous_meta.get("audio") or {}
    visual_plan_signature = hashlib.sha256(
        json.dumps(visual_timeline, sort_keys=True).encode()).hexdigest()
    transition_mode = audio_composition.transition_mode(cfg)
    transition_sig = pipeline_render_stage.transition_signature(
        tuple(semantic_scenes), timeline_spans, genre_key, transition_mode,
        {"insertions": insert_budget,
         "insert_style": cfg.visual_insert_style,
         "insert_gain_db": cfg.visual_insert_gain_db,
         "visual_sfx": cfg.visual_sfx})
    legacy_audio_cache = not cfg.audio_enabled and not previous_audio
    transition_dirty = (
        previous_meta.get("visual_transition_signature") != transition_sig
        and not (legacy_audio_cache and transition_mode == "none"))
    transition_dirty = transition_dirty or (
        any(t.get("backgrounds") for t in visual_timeline) and
        previous_meta.get("visual_plan_signature") != visual_plan_signature)
    events = audio_composition.sfx_events(visual_timeline)
    audio_plan = audio_selection.resolve_audio(
        cfg, genre_key,
        audio_seed(slug, video_title or idea, script_text),
        video_title or idea, script_text, events, previous_audio)
    warnings.extend(audio_plan["warnings"])
    new_audio_meta = audio_plan["metadata"]
    credits.extend(new_audio_meta.get("credits", []))
    audio_cache_matches = (
        previous_audio.get("signature") == new_audio_meta.get("signature")
        or legacy_audio_cache)
    if pipeline_render_stage.final_cache_is_current(
            output_exists=os.path.isfile(paths.final_mp4), force=force,
            subtitles_changed=subs_changed,
            transition_dirty=transition_dirty,
            narration_reused=bool(tts_info.get("reused")),
            audio_cache_matches=audio_cache_matches):
        video_duration = ff.probe_duration(paths.final_mp4)
        render_info = {"backend": "cache", "encoder": "cache",
                       "duration": video_duration, "path": paths.final_mp4}
        sfx_path = (previous_meta.get("artifacts") or {}).get("sfx")
    else:
        silent = paths.silent_mp4
        if force or transition_dirty or not os.path.isfile(silent):
            transitions = pipeline_render_stage.genre_transitions(
                tuple(semantic_scenes), genre_key, transition_mode)
            kinds = pipeline_render_stage.genre_transition_kinds(
                tuple(semantic_scenes), genre_key, transition_mode)
            if visual_timeline:
                pipeline_render_stage.build_silent_visual(
                                     tuple(semantic_scenes), timeline_spans,
                                     visual_timeline, idea, paths,
                                     cfg, silent, transitions=transitions,
                                     kinds=kinds)
            else:
                pipeline_render_stage.build_silent(
                              tuple(semantic_scenes), timeline_spans,
                              media_render_plan, idea, paths,
                              cfg, silent, transitions=transitions, kinds=kinds)
        narration_wav = paths.narration_wav
        sfx_path = (audio_composition.sfx_track(visual_timeline, total, paths)
                    if visual_timeline and cfg.visual_sfx else None)
        if sfx_path:
            narration_wav = audio_composition.narration_with_sfx(paths.narration_wav, sfx_path,
                                                total, paths)
        music_asset = audio_plan.get("music_asset")
        music_path = str(music_asset.get("path")) if music_asset else None
        final_fade = audio_composition.final_audio_fade(genre_key, transition_mode)
        render_info = render_stage.burn_final(
            silent, paths.subs_ass, narration_wav, paths.final_mp4,
            cfg, total, title=video_title,
            title_fontfile=pipeline_render_stage.title_fontfile(cfg, genre_key),
            music_path=music_path, music_gain_db=cfg.music_gain_db,
            music_ducking=cfg.music_ducking, final_fade=final_fade)
        video_duration = render_info["duration"]
        audio_composition.mark_audio_used(cfg, audio_plan)
    stage_times["render"] = round(time.monotonic() - t0, 2)
    run_event("result", f"Render: {render_info['backend']} / "
              f"{render_info['encoder']}; {video_duration:.1f}s",
              operation="render", backend=render_info["backend"],
              encoder=render_info["encoder"],
              duration_seconds=round(video_duration, 2))
    emit(6, "Montando vídeo", "OK")

    finalize_started = time.monotonic()
    metadata = pipeline_metadata_stage.build_base_metadata(
        idea, slug, cfg, script_text, script_source,
        tuple(semantic_scenes), timeline_spans, scenes_source, media_scenes,
        warnings, stage_times, metrics, media_result.source, started)
    metadata.update({
        "genre": genre_key,
        "scene_context_enrichment": enrichment.to_dict(),
        "project_dir": os.path.relpath(paths.root, cfg.out_dir),
        "genre_profile": editorial_stage.summary(perfil),
        "typography": pipeline_metadata_stage.typography_report(cfg, genre_key),
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
            "insertions": timeline_result.insertion_count,
            "insert_budget": insert_budget,
            "insert_style": cfg.visual_insert_style,
            "insert_gain_db": cfg.visual_insert_gain_db,
        } if max_images > 1 else None),
        "audio": new_audio_meta,
        "visual_transition_signature": transition_sig,
        "visual_plan_signature": visual_plan_signature,
        "visual_transitions": {
            "genre": genre_key,
            "mode": transition_mode,
            "boundary_durations": pipeline_render_stage.genre_transitions(
                tuple(semantic_scenes), genre_key, transition_mode),
            "final_fade": audio_composition.final_audio_fade(genre_key, transition_mode),
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
            "etymology": (research_etymology.to_dict()
                          if research_etymology is not None else None),
            "grounding": grounding,
            "target_entity": (research_target.to_dict()
                              if research_target is not None else None),
            "rejected": [{"title": s.title, "reason": m}
                         for s, m, _d in research_rejected],
        },
        "artifacts": {
            "script": paths.script_txt,
            "title": paths.title_txt,
            "script_manifest": paths.script_manifest_json,
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
    source_summary = pipeline_media_sources_stage.persist_source_artifacts(
        sources, paths, research=research_sources, grounding=grounding,
        media_notes=media_rights_notes, credits=credits)
    metadata["sources"] = source_summary
    # Folha de contato: o autor revisa o vídeo em ~1 min sem assistir.
    if media_scenes:
        from .stages import review as review_stage
        review_stage.write_contact_sheet(
            paths.contact_sheet, tuple(semantic_scenes), media_scenes,
            paths.root, slug,
            threshold=scoring_stage.threshold(), genre=genre_key,
            typography=pipeline_metadata_stage.typography_report(cfg, genre_key))
    for warning in warnings[:8]:
        run_event("warning", str(warning), operation="pipeline_warning")
    if len(warnings) > 8:
        run_event("warning", f"Mais {len(warnings) - 8} aviso(s) no metadata",
                  operation="pipeline_warning", count=len(warnings) - 8)
    return pipeline_metadata_stage.persist_run_metadata(
        metadata, paths.metadata_json, metrics, stage_times, cfg.metrics_dir,
        project_artifacts.write_json, finalize_started, started)


def run_script_pipeline(script_text: str, cfg: CurioConfig,
                        title: str | None = None, slug: str | None = None,
                        force: bool = False, narration: str = "ai",
                        max_images: int | None = None,
                        on_progress=None, on_event=None) -> dict:
    """Modo roteiro-pronto: organiza mídia sobre um roteiro já existente.

    O texto é usado verbatim como narração/legenda — nunca gerado nem
    reescrito. `title` vira título/metadados; sem ele, usa-se a primeira
    linha do roteiro. `max_images` (1–5, padrão da config) é o nº de fotos
    por cena com sobreposição em álbum.
    """
    text = script_text or ""
    if not text.strip():
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
                        provided_script=text, max_images=max_images,
                        on_event=on_event)




def finalize_project(slug: str, audio_src: str, cfg: CurioConfig,
                     force: bool = False, on_progress=None,
                     on_event=None) -> dict:
    cfg = deepcopy(cfg)
    slug, paths = project_paths.paths_for_slug(cfg.out_dir, slug)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    log_path = os.path.join(paths.root, "logs", f"finalize-{stamp}.jsonl")
    with RunLog(log_path, slug, on_event) as runlog:
        run_event("log_ready", f"Log: {log_path}", log_path=log_path)
        try:
            result = pipeline_finalize_stage.run_finalize(
                slug, audio_src, cfg, paths, force, on_progress)
        except BaseException as exc:
            runlog.event("run_interrupted" if isinstance(exc, KeyboardInterrupt)
                         else "run_failed",
                         "Finalização interrompida" if isinstance(exc, KeyboardInterrupt)
                         else "Finalização falhou",
                         error_type=type(exc).__name__, error=str(exc),
                         traceback=format_exception(exc))
            raise
        runlog.event("run_completed", "Finalização concluída",
                     metrics_file=result.get("metrics_file"),
                     duration_seconds=result.get("duration_actual"))
        return result
