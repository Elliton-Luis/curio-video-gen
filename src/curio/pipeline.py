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
from .media.providers import classify_rights, get_providers
from .media.artifacts import (media_selection_signature,
                              selection_cache_is_current, write_manifest)
from . import pipeline_render as pipeline_render_stage
from . import pipeline_research as pipeline_research_stage
from . import pipeline_media as pipeline_media_stage
from . import pipeline_audio as pipeline_audio_stage
from .metrics import RunMetrics
from .runlog import (RunLog, current_log_path, event as run_event,
                     format_exception, set_stage as set_log_stage)
from .slug import slugify_with_timestamp
from .slug import find_project_root, project_dir, unique_slug
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
from .stages import sources as sources_stage
from .stages import visual as visual_stage
from .stages import visual_timeline as visual_timeline_stage
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
    media_manifest_json: str
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


def video_paths(out_dir: str, slug: str, genre: str = "") -> VideoPaths:
    root = project_dir(out_dir, genre, slug)
    return VideoPaths(
        root=root,
        script_txt=os.path.join(root, "script", "script.txt"),
        chapters_json=os.path.join(root, "script", "chapters.json"),
        title_txt=os.path.join(root, "script", "title.txt"),
        media_json=os.path.join(root, "media", "media.json"),
        media_manifest_json=os.path.join(root, "media", "media-selection.json"),
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
    chapters = [Chapter.from_dict(d) for d in _read_json(paths.chapters_json)]
    for chapter in chapters:
        chapter.require_valid()
    return chapters


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


def _write_visual_timeline(chapters: list[Chapter], media_scenes: list[dict],
                           paths: VideoPaths, slug: str,
                           overlap_cap: float, sfx: bool,
                           insertions: int | None = None,
                           insert_style: str = "drop_in",
                           insert_gain_db: int = -15) -> list[dict]:
    vt = visual_stage.build_visual_timeline(
        chapters, media_scenes, overlap_cap, seed=slug, sfx=sfx,
        insertions=insertions, insert_style=insert_style,
        insert_gain_db=insert_gain_db)
    _write_json(paths.visual_json, vt)
    print(f"Timeline visual: {visual_timeline_stage.visual_summary(vt)}")
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
        cfg.music_gain_db = max(-40, min(-3, int(music["gain_db"])))
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
        "execution_log": current_log_path(),
        "processing_time_seconds": round(time.monotonic() - started, 2),
        "stage_times": stage_times,
        "pipeline_version": "scenes-0.2",
    }


def _resolve_paths(out_dir: str, slug: str | None, idea: str,
                    genre_key: str, force: bool = False,
                    ) -> tuple[str, VideoPaths]:
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
    return final, video_paths(out_dir, final, genre_key)


def run_pipeline(idea: str, cfg: CurioConfig, slug: str | None = None,
                 force: bool = False, narration: str = "ai",
                 on_progress=None, provided_script: str | None = None,
                 max_images: int = 1,
                 visual_overlap: float | None = None,
                 genre: str | None = None, on_event=None) -> dict:
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

    # [0/6] Pesquisa é um estágio. Pipeline só passa dependências e recebe
    # contexto/estado para roteiro, cenas e metadados seguintes.
    research_output = pipeline_research_stage.run_research_stage(
        idea, cfg, paths, metrics, genre_key, warnings, sources, emit,
        _write_json)
    research = research_output.result
    research_sources = research_output.sources
    research_target = research_output.target
    research_rejected = research_output.rejected
    research_queries = research_output.queries
    research_etymology = research_output.etymology
    research_status = research_output.status
    research_pack = research_output.prompt
    stage_times["research"] = research_output.elapsed

    # [1/6] Roteiro (modo roteiro-pronto: usa o texto verbatim, nunca gera)
    t0 = time.monotonic()
    emit(1, "Lendo roteiro pronto" if script_mode else "Gerando roteiro")
    force_after_script = force
    if script_mode:
        assert provided_script is not None
        script_text = provided_script
        if not script_text.strip():
            raise ValueError("roteiro vazio — nada para produzir")
        script_source = "provided"
        run_event("result", f"Roteiro fornecido: {len(script_text)} caracteres",
                  operation="script", source=script_source,
                  characters=len(script_text))
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
        run_event("cache", f"Roteiro reutilizado: {len(script_text)} caracteres",
                  artifact="script", characters=len(script_text))
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
        run_event("provider", f"Roteiro: {script_source}; {len(script_text)} caracteres",
                  operation="script", source=script_source,
                  characters=len(script_text))
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
        run_event("warning", f"Grounding: {len(grounding['unverified'])} "
                  "afirmação(ões) não verificadas", operation="grounding",
                  unverified=len(grounding["unverified"]))
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
    run_event("cache" if title_source == "cache" else "provider",
              f"Título: {title_source}", operation="title",
              source=title_source, characters=len(video_title))

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
            scene_directive_eff = scene_directive
            if (perfil and "wiktionary" in perfil.specialized_sources
                    and research_etymology is not None
                    and len(getattr(research_etymology, "chain", []) or []) >= 2):
                # A cadeia etimológica entra no prompt das cenas para que as
                # entidades visuais usem as formas reais (candidatus,
                # candidus) e o cenário cultural (Roma, toga) — nunca cópia
                # do verbete, só os termos.
                from .stages import etymology as etymology_stage
                chain = research_etymology
                bloco = (f"\n\nCADEIA ETIMOLÓGICA (use as formas como "
                         f"entidades visuais e o cenário como contexto): "
                         f"{chain.chain_text()}")
                if chain.visual_context:
                    bloco += " | cenário: " + ", ".join(chain.visual_context)
                scene_directive_eff = (scene_directive_eff or "") + bloco
            chapters, scenes_source = scenes_stage.build_chapters(
                script_text, cfg, n_scenes=n, metrics=metrics,
                genre=genre_key, target_seconds=alvo_cena,
                genre_directive=scene_directive_eff, max_scenes=teto_cena)
        except nvidia_stage.NvidiaError as exc:
            # Scene planning is optional after the script exists in both
            # automatic and ready-script modes. Preserve exact narration.
            logged = run_event(
                "fallback", f"Cenas: chain LLM falhou; divisão local ({exc})",
                operation="scenes", fallback="local", error=str(exc))
            if not logged:
                print(f"AVISO: chain LLM de cenas indisponível ({exc}) — "
                      "seguindo com divisão local.", file=sys.stderr)
            warnings.append(f"cenas locais (chain LLM indisponível: {exc})")
            chapters = scenes_stage._local_chapters(script_text, n)
            scenes_source = "local"
        if script_mode:
            visual_stage.validate_preserved(script_text, chapters)
        _write_json(paths.chapters_json, [c.to_dict() for c in chapters])
    scene_event = ("provider" if scenes_source not in ("local", "cache")
                   else "fallback" if scenes_source == "local" else "cache")
    from .stages.visual_context import (anchor_local_topic,
                                       attach_video_context,
                                       fill_missing_context)
    local_scenes = (scenes_source == "local" or
                    any(str(ch.visual_intent or "").startswith("local fallback")
                        for ch in chapters))
    if scenes_source == "cache" and not local_scenes:
        try:
            local_scenes = (_read_json(paths.metadata_json).get("scenes_source")
                            == "local")
        except (OSError, ValueError, json.JSONDecodeError):
            local_scenes = False
    if local_scenes:
        # Cached local chapters predate the explicit `local fallback` marker.
        # Tag them before anchoring so scoring applies the same hard topic gate.
        for chapter in chapters:
            if not str(chapter.visual_intent or "").startswith("local fallback"):
                chapter.visual_intent = ("local fallback: cached "
                                          + str(chapter.visual_intent or "")).strip()
    if attach_video_context(chapters, idea, research_target):
        force_after_script = True
        _write_json(paths.chapters_json, [chapter.to_dict() for chapter in chapters])
    if local_scenes and anchor_local_topic(chapters, idea, research_target):
        force_after_script = True
        _write_json(paths.chapters_json, [chapter.to_dict() for chapter in chapters])
        run_event("result", "Cenas locais ancoradas no tema do vídeo",
                  operation="scenes", source=scenes_source,
                  topic_queries=chapters[0].global_visual_queries if chapters else [])
    if fill_missing_context(chapters, research_target, genre_key,
                            research_sources, cfg.research_timeout):
        force_after_script = True  # mídia em cache precisa refletir o novo contexto
        _write_json(paths.chapters_json, [c.to_dict() for c in chapters])
        run_event("result", "Contexto visual recuperado da entidade pesquisada",
                  operation="scenes", source=scenes_source)
    if (perfil and "wiktionary" in perfil.specialized_sources
            and research_etymology is not None):
        from .stages import etymology as etymology_stage
        if etymology_stage.enrich_chapters(chapters, research_etymology):
            force_after_script = True
            _write_json(paths.chapters_json, [c.to_dict() for c in chapters])
            run_event("result", "Cenas enriquecidas com a cadeia etimológica",
                      operation="scenes", source=scenes_source,
                      word=getattr(research_etymology, "word", ""))
    run_event(scene_event, f"Cenas: {scenes_source}; {len(chapters)} cena(s)",
              operation="scenes", source=scenes_source,
              scenes=len(chapters))
    stage_times["scenes"] = round(time.monotonic() - t0, 2)
    emit(2, "Interpretando cenas", "OK")

    # [3/6] Mídia (manual > cache > provedores; zero imagens = standby)
    t0 = time.monotonic()
    emit(3, "Buscando mídia")
    manual_dir = pipeline_media_stage.manual_media_dir(paths)
    media_scenes = None
    manual = pipeline_media_stage.manual_media_scenes(chapters, manual_dir)
    available_providers = [provider.name for provider in get_providers(cfg)]
    media_signature = media_selection_signature(
        chapters, genre_key, max_images, available_providers,
        scoring_stage.threshold())
    if manual is not None:
        media_scenes = manual
        msg = (f"mídia manual: {len({e['asset']['local_path'] for s in manual for e in s.get('assets') or []})} "
               f"foto(s) de {manual_dir}")
        warnings.append(msg)
        print(f"Mídia manual: usando fotos de {manual_dir}.", file=sys.stderr)
        run_event("cache", f"Mídia manual: {len(manual)} cena(s)",
                  operation="media", source="manual", scenes=len(manual))
        _write_json(paths.media_json, media_scenes)
    if media_scenes is None and not force_after_script and os.path.isfile(paths.media_json):
        try:
            saved = _read_json(paths.media_json)
            expected_scene_ids = [chapter.id for chapter in chapters]
            chapter_ok = ([s["chapter_id"] for s in saved] ==
                          expected_scene_ids) and selection_cache_is_current(
                              saved, paths.media_manifest_json, media_signature,
                              expected_scene_ids) and all(
                isinstance(s.get("visual_decision"), dict)
                for s in saved
                if (s.get("asset") or {}).get("provider") != "manual")
            files_ok = True
            for s in saved:
                chapter = next((ch for ch in chapters if ch.id == s["chapter_id"]), None)
                if chapter is None:
                    files_ok = False
                    break
                blocked = visual_stage.media_rules.scene_blocklist(chapter)
                if any(visual_stage.media_rules.rejection_reason(
                        entry.get("asset") or {}, blocked) for entry in s.get("assets", [])
                       if (entry.get("asset") or {}).get("provider") != "synth"):
                    files_ok = False  # Old cached homonyms must pass current identity rules.
                    break
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
                run_event("cache", "Mídia reutilizada do cache",
                          operation="media", scenes=len(saved))
        except (json.JSONDecodeError, KeyError):
            media_scenes = None
    if media_scenes is None:
        media_scenes, media_warnings = visual_stage.fetch_media_multi(
            chapters, cfg, max_images, metrics, genre=genre_key)
        warnings.extend(media_warnings)
        _write_json(paths.media_json, media_scenes)
        if any(scene.get("asset") or scene.get("assets") for scene in media_scenes):
            write_manifest(paths.media_manifest_json, media_scenes, media_signature)
        elif os.path.isfile(paths.media_manifest_json):
            os.unlink(paths.media_manifest_json)
        if media_warnings:
            for warning in media_warnings[:8]:
                run_event("warning", str(warning), operation="media")
    for scene in media_scenes:
        if metrics and scene.get("visual_decision"):
            metrics.media_record_scene_decision(
                int(scene.get("chapter_id", 0)), scene["visual_decision"])
        entries = scene.get("assets") or []
        asset = scene.get("asset") or {}
        synth = asset.get("provider") == "synth"
        run_event(
            "fallback" if synth else "result",
            f"Mídia cena {scene.get('chapter_id')}: "
            f"{len(entries)} asset(s); "
            f"{'visual sintético' if synth else asset.get('provider', 'sem asset')}",
            operation="media", scene=scene.get("chapter_id"),
            candidates=len(entries), provider=asset.get("provider", ""),
            fallback=synth,
            rejected=len(scene.get("rejected") or []))
    real_media_count = sum(
        1 for scene in media_scenes
        if (scene.get("asset") or {}).get("provider") != "synth")
    run_event("result", f"Mídia: {real_media_count}/{len(media_scenes)} cena(s) com asset real; "
              f"{len(media_scenes) - real_media_count} sintético(s)",
              operation="media", real_assets=real_media_count,
              synthetic_scenes=len(media_scenes) - real_media_count,
              downloads=metrics.media_downloads,
              cache_hits=metrics.media_cache_hits)
    # Registra procedência das mídias no registro de fontes do projeto:
    # links ANTES do uso (página, arquivo, licença) + local APÓS o uso.
    # `media_rights_notes` alimenta o relatório: licença incerta não passa
    # em silêncio — ela vira aviso explícito na pasta de informações.
    media_rights_notes: list[str] = []
    credits: list[str] = []
    # Rótulo curto do assunto de cada cena, para o título do registro:
    # "cena 3 · rolo de papel térmico [pixabay_12345]" diz do que se trata;
    # "cena 3 [pixabay_12345]" só diz onde.
    rotulos = {c.id: pipeline_media_stage.scene_label(c) for c in chapters}
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
    if pipeline_media_stage.count_assets(media_scenes) == 0:
        pipeline_media_stage.write_manual_readme(manual_dir, slug, len(chapters))
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
            "execution_log": current_log_path(),
        })
        emit(3, "Buscando mídia", "STANDBY")
        raise pipeline_media_stage.MediaStandby(slug, manual_dir, len(chapters))

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

    # [4/6] Narração, alinhamento e legendas são um estágio coeso.
    audio_result = pipeline_audio_stage.run_audio_stages(
        script_text, chapters, paths, cfg, force, metrics, warnings, emit,
        _write_json, stage_times, pacing=pacing, caption_style=cap_style)
    chapters = audio_result.chapters
    words = audio_result.words
    audio_duration = audio_result.audio_duration
    tts_info = audio_result.tts_info
    timed_source = audio_result.timed_source
    cue_count = audio_result.cue_count
    subs_changed = audio_result.subtitles_changed
    stage_times.update(audio_result.stage_times)

    # Pipeline orquestra timeline visual; visual stage só recebe dados prontos.
    from .stages.visual_beats import BEAT_SECONDS
    visual_timeline = (_write_visual_timeline(
        chapters, media_scenes, paths, slug, overlap_cap, cfg.visual_sfx,
        insertions=insert_budget, insert_style=cfg.visual_insert_style,
        insert_gain_db=cfg.visual_insert_gain_db)
        if max_images > 1 else [])
    metrics.visual_plan(chapters, media_scenes, BEAT_SECONDS, visual_timeline)
    if visual_timeline:
        print(f"Inserções: {count_insertions(visual_timeline)} foto(s) "
              f"complementar(es) caindo sobre o fundo "
              f"(estilo {cfg.visual_insert_style}).")

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
    visual_plan_signature = hashlib.sha256(
        json.dumps(visual_timeline, sort_keys=True).encode()).hexdigest()
    transition_mode = _transition_mode(cfg)
    transition_sig = pipeline_render_stage.transition_signature(
        chapters, genre_key, transition_mode,
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
    events = _audio_events(visual_timeline)
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
            transitions = pipeline_render_stage.genre_transitions(
                chapters, genre_key, transition_mode)
            kinds = pipeline_render_stage.genre_transition_kinds(
                chapters, genre_key, transition_mode)
            if visual_timeline:
                pipeline_render_stage.build_silent_visual(chapters, visual_timeline, idea, paths,
                                     cfg, silent, transitions=transitions,
                                     kinds=kinds)
            else:
                pipeline_render_stage.build_silent(chapters, media_scenes, idea, durations, paths,
                              cfg, silent, transitions=transitions, kinds=kinds)
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
    run_event("result", f"Render: {render_info['backend']} / "
              f"{render_info['encoder']}; {video_duration:.1f}s",
              operation="render", backend=render_info["backend"],
              encoder=render_info["encoder"],
              duration_seconds=round(video_duration, 2))
    emit(6, "Montando vídeo", "OK")

    metadata = _base_metadata(idea, slug, cfg, script_text, script_source,
                              chapters, scenes_source, media_scenes, warnings,
                              stage_times, started)
    metadata.update({
        "genre": genre_key,
        "project_dir": os.path.relpath(paths.root, cfg.out_dir),
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
        "visual_plan_signature": visual_plan_signature,
        "visual_transitions": {
            "genre": genre_key,
            "mode": transition_mode,
            "boundary_durations": pipeline_render_stage.genre_transitions(
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
            "etymology": (research_etymology.to_dict()
                          if research_etymology is not None else None),
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
    for warning in warnings[:8]:
        run_event("warning", str(warning), operation="pipeline_warning")
    if len(warnings) > 8:
        run_event("warning", f"Mais {len(warnings) - 8} aviso(s) no metadata",
                  operation="pipeline_warning", count=len(warnings) - 8)
    metadata["stage_times"] = stage_times
    metadata["metrics_file"] = metrics.save(metadata, stage_times,
                                            cfg.metrics_dir)
    return metadata


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
    from .stages.visual_beats import BEAT_SECONDS
    _write_json(paths.timeline_json, [c.to_dict() for c in chapters])
    visual_timeline = (_write_visual_timeline(
        chapters, media_scenes, paths, slug, overlap_cap, cfg.visual_sfx,
        insertions=insert_budget, insert_style=cfg.visual_insert_style,
        insert_gain_db=cfg.visual_insert_gain_db)
        if max_images > 1 else [])
    metrics.visual_plan(chapters, media_scenes, BEAT_SECONDS, visual_timeline)
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
        pipeline_render_stage.build_silent_visual(chapters, visual_timeline, idea, paths, cfg,
                             paths.silent_mp4, transitions=pipeline_render_stage.genre_transitions(
                                 chapters, genre_key, transition_mode),
                             kinds=pipeline_render_stage.genre_transition_kinds(
                                 chapters, genre_key, transition_mode))
    else:
        durations = [c.end - c.start for c in chapters]
        pipeline_render_stage.build_silent(chapters, media_scenes, idea, durations, paths, cfg,
                      paths.silent_mp4, transitions=pipeline_render_stage.genre_transitions(
                          chapters, genre_key, transition_mode),
                      kinds=pipeline_render_stage.genre_transition_kinds(
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
        "project_dir": os.path.relpath(paths.root, cfg.out_dir),
        "audio_request": audio_plan["metadata"],
        "visual_transition_signature": pipeline_render_stage.transition_signature(
            chapters, genre_key, transition_mode,
            {"insertions": insert_budget,
             "insert_style": cfg.visual_insert_style,
             "insert_gain_db": cfg.visual_insert_gain_db,
             "visual_sfx": cfg.visual_sfx}),
        "visual_transitions": {
            "genre": genre_key, "mode": transition_mode,
            "boundary_durations": pipeline_render_stage.genre_transitions(
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


def _paths_for_slug(out_dir: str, slug: str) -> tuple[str, VideoPaths]:
    """Caminhos de um projeto existente, no layout novo ou legado.

    Aceita `output/<genero>/<slug>` e `output/<slug>`; sem achar,
    levanta FileNotFoundError dizendo onde procurou.
    """
    root = None
    if "/" in slug:
        genre_part, _, slug = slug.partition("/")
        cand = project_dir(out_dir, genre_part, slug)
        if os.path.isdir(cand):
            root = cand
    else:
        root = find_project_root(out_dir, slug)
    if root is None:
        raise FileNotFoundError(
            f"projeto '{slug}' não encontrado em {out_dir}/ "
            f"(nem em {out_dir}/<genero>/{slug}).")
    genre = ""
    if os.path.dirname(root) != out_dir:
        genre = os.path.basename(os.path.dirname(root))
    return slug, video_paths(out_dir, slug, genre)


def iter_projects(out_dir: str) -> list[tuple[str, str]]:
    """Projetos com metadata.json: [(ref, root)].

    `ref` é `slug` (layout plano legado) ou `<genero>/<slug>` (novo);
    aceito de volta por `_paths_for_slug` e pelos comandos `--slug`.
    """
    found: list[tuple[str, str]] = []
    try:
        entries = sorted(os.listdir(out_dir))
    except OSError:
        return found
    for entry in entries:
        full = os.path.join(out_dir, entry)
        if not os.path.isdir(full):
            continue
        if os.path.isfile(os.path.join(full, "metadata.json")):
            found.append((entry, full))
            continue
        try:
            subs = sorted(os.listdir(full))
        except OSError:
            continue
        for sub in subs:
            sub_full = os.path.join(full, sub)
            if (os.path.isdir(sub_full) and os.path.isfile(
                    os.path.join(sub_full, "metadata.json"))):
                found.append((f"{entry}/{sub}", sub_full))
    return found


def finalize_project(slug: str, audio_src: str, cfg: CurioConfig,
                     force: bool = False, on_progress=None,
                     on_event=None) -> dict:
    slug, paths = _paths_for_slug(cfg.out_dir, slug)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    log_path = os.path.join(paths.root, "logs", f"finalize-{stamp}.jsonl")
    with RunLog(log_path, slug, on_event) as runlog:
        run_event("log_ready", f"Log: {log_path}", log_path=log_path)
        try:
            result = _finalize_project(slug, audio_src, cfg, force, on_progress)
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


def _finalize_project(slug: str, audio_src: str, cfg: CurioConfig,
                      force: bool = False, on_progress=None) -> dict:
    """Une áudio humano ao vídeo silencioso: transcreve, legenda, merge."""
    started = time.monotonic()
    slug, paths = _paths_for_slug(cfg.out_dir, slug)
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

    chapters = [Chapter.from_dict(row) for row in _read_json(paths.timeline_json)]
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

    progress_started: dict[str, float] = {}

    def emit(label: str, status: str = "…") -> None:
        set_log_stage(label)
        if status == "…":
            progress_started[label] = time.monotonic()
            run_event("stage_started", label)
        else:
            elapsed = round(time.monotonic() - progress_started.pop(label,
                                                                     time.monotonic()), 2)
            if status == "OK":
                status = f"OK ({elapsed:.1f}s)"
            run_event("stage_finished", label, status=status,
                      duration_seconds=elapsed)
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
    run_event("provider" if metrics.whisper_calls else "cache",
              f"Transcrição: {'faster-whisper/' + cfg.whisper_model if metrics.whisper_calls else 'cache'}; "
              f"{len(words)} palavra(s)", operation="transcription",
              model=cfg.whisper_model, words=len(words),
              cache=not bool(metrics.whisper_calls))
    emit("Transcrevendo", "OK")

    emit("Legendando")
    from .stages import editorial as _ed
    _perfil = _ed.get((meta or {}).get("genre", ""))
    _pac = _perfil.pacing if _perfil is not None else None
    cue_count = subs_stage.write_subtitles(
        "", human_dur, paths.subs_srt, paths.subs_ass,
        cfg.width, cfg.height, cfg.sub_font_size,
        subs_stage.safe_subtitle_margin(cfg.height, cfg.sub_margin_v),
        words=words, cache_dir=cfg.cache_dir,
        max_words=min(5, _pac.caption_max_words if _pac is not None else 5),
        highlight="word", upper=False, karaoke=True)
    run_event("result", f"Legendas: {cue_count} cue(s)",
              operation="subtitles", cues=cue_count)
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
            visual_timeline = visual_timeline_stage.retime_visual_timeline(
                visual_timeline, chapters)
            _write_json(paths.visual_json, visual_timeline)
            pipeline_render_stage.build_silent_visual(chapters, visual_timeline, idea, paths,
                                 cfg, adj, transitions=pipeline_render_stage.genre_transitions(
                                      chapters, project_genre, transition_mode),
                                 kinds=pipeline_render_stage.genre_transition_kinds(
                                      chapters, project_genre, transition_mode))
        else:
            durations = [c.end - c.start for c in chapters]
            durations[-1] += diff
            pipeline_render_stage.build_silent(chapters, media_scenes, idea, durations, paths,
                           cfg, adj, transitions=pipeline_render_stage.genre_transitions(
                               chapters, project_genre, transition_mode),
                           kinds=pipeline_render_stage.genre_transition_kinds(
                               chapters, project_genre, transition_mode))
        silent = adj
        warnings.append(f"última cena estendida +{diff:.1f}s p/ caber o áudio")
    else:
        warnings.append(f"áudio {abs(diff):.1f}s mais curto — cauda cortada")
    emit("Ajustando visual", "OK")

    emit("Merge final")
    total = round(human_dur + 0.5, 2)
    from .stages.visual_beats import BEAT_SECONDS
    metrics.visual_plan(chapters, media_scenes, BEAT_SECONDS, visual_timeline,
                        rendered_duration=total)
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
    run_event("result", f"Render: {render_info['backend']} / "
              f"{render_info['encoder']}; {render_info['duration']:.1f}s",
              operation="render", backend=render_info["backend"],
              encoder=render_info["encoder"],
              duration_seconds=round(render_info["duration"], 2))
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
        "visual_transition_signature": pipeline_render_stage.transition_signature(
            chapters, project_genre, transition_mode,
            {"insertions": cfg.visual_insertions,
             "insert_style": cfg.visual_insert_style,
             "insert_gain_db": cfg.visual_insert_gain_db,
             "visual_sfx": cfg.visual_sfx}),
        "visual_transitions": {
            "genre": project_genre, "mode": transition_mode,
            "boundary_durations": pipeline_render_stage.genre_transitions(
                chapters, project_genre, transition_mode),
            "final_fade": _final_audio_fade(
                project_genre, transition_mode),
        },
        "finalize_warnings": warnings,
        "warnings": sorted(set(meta.get("warnings", []) + warnings)),
        "processing_time_seconds": round(time.monotonic() - started, 2),
        "execution_log": current_log_path(),
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
