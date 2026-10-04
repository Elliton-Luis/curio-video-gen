"""Script and title artifact production for one pipeline run."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

from .runlog import event as run_event
from .stages import entity as entity_stage
from .stages import research as research_stage
from .stages import script as script_stage
from .stages.subs import strip_list_markers


@dataclass(frozen=True)
class ScriptStageResult:
    script: script_stage.ScriptArtifact
    title: script_stage.TitleArtifact
    grounding: dict
    script_changed: bool
    force_scenes: bool
    warnings: tuple[str, ...]
    elapsed: float


def run_script_stage(idea, cfg, paths, metrics, *, research_prompt,
                     research_target, research_sources, genre_directive,
                     force, provided_script=None) -> ScriptStageResult:
    """Produce validated narration/title artifacts and verify grounding."""
    started = time.monotonic()
    script_mode = provided_script is not None
    warnings: list[str] = []
    force_scenes = force
    script_changed = False

    if script_mode:
        if not provided_script.strip():
            raise ValueError("roteiro vazio — nada para produzir")
        script = script_stage.ScriptArtifact(provided_script, "provided")
        cached = _read(paths.script_txt) if os.path.isfile(paths.script_txt) else None
        script_changed = cached != script.text
        if cached != script.text:
            _write(paths.script_txt, script.text)
            if cached is not None and not force:
                print("AVISO: roteiro fornecido mudou — refazendo cenas e mídia.",
                      file=sys.stderr)
        force_scenes = force or script_changed
        run_event("result", f"Roteiro fornecido: {len(script.text)} caracteres",
                  operation="script", source=script.source,
                  characters=len(script.text))
    elif not force and os.path.isfile(paths.script_txt):
        raw_cached = _read(paths.script_txt)
        healed = strip_list_markers(raw_cached)
        script_changed = healed != raw_cached
        force_scenes = force or script_changed
        if healed != raw_cached:
            print("AVISO: roteiro em cache continha numeração de lista — "
                  "marcadores removidos.", file=sys.stderr)
            warnings.append("roteiro em cache higienizado (marcadores de lista)")
            _write(paths.script_txt, healed)
        script = script_stage.ScriptArtifact(healed, "cache")
        run_event("cache", f"Roteiro reutilizado: {len(script.text)} caracteres",
                  artifact="script", characters=len(script.text))
    else:
        previous_script = (_read(paths.script_txt)
                           if os.path.isfile(paths.script_txt) else None)
        script = script_stage.generate_script(
            idea, cfg, metrics, research=research_prompt,
            genre_directive=genre_directive,
            entity_context=entity_stage.script_context(
                research_target, cfg.language))
        if not isinstance(script, script_stage.ScriptArtifact):
            raise TypeError("generate_script must return ScriptArtifact")
        run_event("provider", f"Roteiro: {script.source}; {len(script.text)} caracteres",
                  operation="script", source=script.source,
                  characters=len(script.text))
        script_changed = previous_script != script.text
        force_scenes = force or script_changed
        _write(paths.script_txt, script.text)

    grounding = research_stage.verify_grounding(
        script.text, research_sources, cfg.language)
    if grounding["unverified"]:
        warnings.append(_print_grounding_warning(grounding))
        run_event("warning", f"Grounding: {len(grounding['unverified'])} "
                  "afirmação(ões) não verificadas", operation="grounding",
                  unverified=len(grounding["unverified"]))
    elif grounding["checked"]:
        print(f"Fundamentação: {grounding['checked']} dado(s) conferidos, "
              "todos nas fontes.")

    if not force_scenes and os.path.isfile(paths.title_txt):
        cached_title = _read(paths.title_txt).strip()
        if cached_title:
            title = script_stage.TitleArtifact(cached_title, "cache")
        else:
            title = _generate_title(script.text, idea, cfg, metrics)
            _write(paths.title_txt, title.text)
    else:
        title = _generate_title(script.text, idea, cfg, metrics)
        _write(paths.title_txt, title.text)
    print(f"Título: {title.text} ({title.source})")
    run_event("cache" if title.source == "cache" else "provider",
              f"Título: {title.source}", operation="title",
              source=title.source, characters=len(title.text))

    return ScriptStageResult(
        script=script, title=title, grounding=grounding,
        script_changed=script_changed, force_scenes=force_scenes,
        warnings=tuple(warnings),
        elapsed=round(time.monotonic() - started, 2))


def _generate_title(script_text, idea, cfg, metrics):
    title = script_stage.generate_title(script_text, idea, cfg, metrics)
    if not isinstance(title, script_stage.TitleArtifact):
        raise TypeError("generate_title must return TitleArtifact")
    return title


def _read(path):
    with open(path, encoding="utf-8") as stream:
        return stream.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(text)


def _print_grounding_warning(grounding):
    n = len(grounding["unverified"])
    details = grounding.get("unverified_display") or []
    msg = (f"{n} {'afirmações' if n > 1 else 'afirmação'} do roteiro sem "
           "correspondência nas fontes")
    print(f"AVISO: {msg}:", file=sys.stderr)
    for detail in details[:8]:
        print(f"  - {detail['fact']}: \"{detail['claim']}\"", file=sys.stderr)
        print(f"      possível causa: {detail['cause']}", file=sys.stderr)
    more = len(details) - 8
    if more > 0:
        print(f"  ... e {more} {'outras' if more > 1 else 'outra'}. "
              "Ver o relatório completo.", file=sys.stderr)
    print(f"  Fontes avaliadas: "
          f"{', '.join(grounding.get('sources_checked', [])[:6])}",
          file=sys.stderr)
    print("  Consulte sources/FONTES.md para as fontes relacionadas.",
          file=sys.stderr)
    return msg
