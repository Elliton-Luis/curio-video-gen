"""Script and title artifact production for one pipeline run."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

from .runlog import event as run_event
from .script_artifacts import (ScriptArtifactsManifest, read_manifest,
                               input_identity, text_identity, write_manifest)
from .stages import entity as entity_stage
from .stages import research as research_stage
from .stages import script as script_stage
from .stages import nvidia as nvidia_stage
from .stages import prompts as prompts_stage
from .stages.subs import strip_list_markers

SCRIPT_POLICY_REVISION = 1
TITLE_POLICY_REVISION = 1
TEMPLATE_POLICY_REVISION = 1


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
                     force, provided_script=None, provided_title=None) -> ScriptStageResult:
    """Produce validated narration/title artifacts and verify grounding."""
    started = time.monotonic()
    script_mode = provided_script is not None
    warnings: list[str] = []
    previous_manifest = read_manifest(paths.script_manifest_json)
    previous_script = (_read(paths.script_txt)
                       if os.path.isfile(paths.script_txt) else None)
    previous_script_hash = (text_identity(previous_script)
                            if previous_script is not None else None)
    generated_input_hash = _script_input_hash(
        idea, cfg, research_prompt, research_target, research_sources,
        genre_directive)
    script_inputs_stale = bool(
        previous_manifest
        and previous_manifest.script_input_sha256 != generated_input_hash
        and previous_manifest.script_origin not in {"provided", "edited", "legacy"})

    if script_mode:
        if not provided_script.strip():
            raise ValueError("roteiro vazio — nada para produzir")
        script = script_stage.ScriptArtifact(provided_script, "provided")
        script_changed = previous_script != script.text
        if script_changed:
            _write(paths.script_txt, script.text)
            if previous_script is not None and not force:
                print("AVISO: roteiro fornecido mudou — refazendo cenas e mídia.",
                      file=sys.stderr)
        script_origin = "provided"
        force_scenes = force or script_changed
        run_event("result", f"Roteiro fornecido: {len(script.text)} caracteres",
                  operation="script", source=script.source,
                  characters=len(script.text))
    elif not force and os.path.isfile(paths.script_txt):
        assert previous_script is not None
        edited = bool(previous_manifest and (
            previous_script_hash != previous_manifest.script_sha256
            or previous_manifest.script_origin == "edited"))
        protected = bool(previous_manifest and previous_manifest.script_origin
                         in {"provided", "legacy"})
        legacy_without_manifest = previous_manifest is None
        cache_inputs_match = bool(
            previous_manifest
            and previous_manifest.script_input_sha256 == generated_input_hash)
        if edited or protected or legacy_without_manifest:
            preserved = (strip_list_markers(previous_script)
                         if legacy_without_manifest else previous_script)
            script = script_stage.ScriptArtifact(
                preserved, "cache" if legacy_without_manifest else "edited")
            script_changed = (preserved != previous_script or bool(
                previous_manifest and
                previous_script_hash != previous_manifest.script_sha256))
            script_origin = ("edited" if edited else
                             "provided" if protected else "legacy")
            if script_changed:
                if legacy_without_manifest:
                    _write(paths.script_txt, preserved)
                    warnings.append("roteiro legado higienizado; cenas e áudio refeitos")
                else:
                    warnings.append("roteiro editado no projeto; cenas e áudio refeitos")
                    run_event("result", "Roteiro editado no projeto; derivados invalidados",
                              operation="script", source="edited")
            if legacy_without_manifest:
                warnings.append(
                    "roteiro legado sem manifesto preservado como entrada editorial")
        elif cache_inputs_match:
            healed = strip_list_markers(previous_script)
            script_changed = healed != previous_script
            script_origin = previous_manifest.script_origin
            if script_changed:
                print("AVISO: roteiro em cache continha numeração de lista — "
                      "marcadores removidos.", file=sys.stderr)
                warnings.append("roteiro em cache higienizado (marcadores de lista)")
                _write(paths.script_txt, healed)
            script = script_stage.ScriptArtifact(healed, "cache")
            run_event("cache", f"Roteiro reutilizado: {len(script.text)} caracteres",
                      artifact="script", characters=len(script.text))
        else:
            script = script_stage.generate_script(
                idea, cfg, metrics, research=research_prompt,
                genre_directive=genre_directive,
                entity_context=entity_stage.script_context(
                    research_target, cfg.language))
            if not isinstance(script, script_stage.ScriptArtifact):
                raise TypeError("generate_script must return ScriptArtifact")
            script_changed = previous_script != script.text
            script_origin = script.source
            _write(paths.script_txt, script.text)
            run_event("provider", f"Roteiro: {script.source}; {len(script.text)} caracteres",
                      operation="script", source=script.source,
                      characters=len(script.text))
        force_scenes = force or script_changed or script_inputs_stale
    else:
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
        script_origin = script.source
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

    script_hash = text_identity(script.text)
    title_inputs_hash = _title_input_hash(script.text, idea, cfg)
    raw_title = _read(paths.title_txt) if os.path.isfile(paths.title_txt) else None
    cached_title = raw_title.strip() if raw_title is not None else ""
    title_hash = text_identity(cached_title) if cached_title else None
    title_edited = bool(not force and previous_manifest and title_hash and (
        title_hash != previous_manifest.title_sha256
        or previous_manifest.title_origin == "edited"))
    title_protected = bool(previous_manifest and previous_manifest.title_origin
                           in {"provided", "legacy"})
    if provided_title is not None:
        title_text = str(provided_title).strip()
        if not title_text:
            raise ValueError("título fornecido não pode ser vazio")
        title = script_stage.TitleArtifact(title_text, "provided")
        _write(paths.title_txt, title.text)
        title_origin = title.source
        title_script_hash = None
    elif title_edited:
        title = script_stage.TitleArtifact(cached_title, "edited")
        title_origin = "edited"
        title_script_hash = None
    elif (not force and cached_title
          and (title_protected or previous_manifest is None)):
        title = script_stage.TitleArtifact(cached_title, "cache")
        title_origin = (previous_manifest.title_origin
                        if previous_manifest else "legacy")
        title_script_hash = None
    elif (not force and cached_title
          and previous_manifest
          and previous_manifest.title_script_sha256 == script_hash
          and previous_manifest.title_input_sha256 == title_inputs_hash):
        title = script_stage.TitleArtifact(cached_title, "cache")
        title_origin = (previous_manifest.title_origin
                        if previous_manifest and title_hash == previous_manifest.title_sha256
                        else "legacy")
        title_script_hash = (previous_manifest.title_script_sha256
                             if previous_manifest and title_origin != "legacy"
                             else None)
    elif not force and os.path.isfile(paths.title_txt):
        title = _generate_title(script.text, idea, cfg, metrics)
        _write(paths.title_txt, title.text)
        title_origin = title.source
        title_script_hash = script_hash
    else:
        title = _generate_title(script.text, idea, cfg, metrics)
        _write(paths.title_txt, title.text)
        title_origin = title.source
        title_script_hash = script_hash
    title_hash = text_identity(title.text)
    manifest = ScriptArtifactsManifest(
        script_sha256=script_hash, script_origin=script_origin,
        title_sha256=title_hash, title_origin=title_origin,
        title_script_sha256=title_script_hash,
        script_input_sha256=(None if script_origin in {"provided", "edited", "legacy"}
                             else generated_input_hash),
        title_input_sha256=(None if title_origin in {"edited", "provided", "legacy"}
                            else title_inputs_hash))
    write_manifest(paths.script_manifest_json, manifest)
    print(f"Título: {title.text} ({title.source})")
    title_event = ("cache" if title.source == "cache" else
                   "result" if title.source == "edited" else "provider")
    run_event(title_event,
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


def _script_input_hash(idea, cfg, research_prompt, research_target,
                       research_sources, genre_directive) -> str:
    """Identity of inputs that can change an automatically generated script."""
    target = (research_target.to_dict() if research_target is not None
              and callable(getattr(research_target, "to_dict", None)) else None)
    sources = [source.to_dict() if callable(getattr(source, "to_dict", None))
               else str(source) for source in research_sources or []]
    llm_routes = {
        "configured": {
            "nvidia": (getattr(cfg, "nvidia_model", ""),
                       getattr(cfg, "nvidia_base_url", ""),
                       getattr(cfg, "nvidia_timeout", None),
                       getattr(cfg, "nvidia_timeout_max", None),
                       getattr(cfg, "nvidia_connect_timeout", None)),
            "openrouter": (getattr(cfg, "openrouter_model", ""),
                           getattr(cfg, "openrouter_base_url", "")),
            "fallbacks": (cfg.llm_overrides() if callable(
                getattr(cfg, "llm_overrides", None)) else {}),
        },
        # Store model/endpoint and provider availability only. Credentials and
        # key values must never enter an artifact signature payload or output.
        "available": tuple(sorted(
            (name, *nvidia_stage.llm_settings(name))
            for name, credential in nvidia_stage.CREDENTIALS.items()
            if credential.from_env().available)),
    }
    return input_identity({
        "revision": SCRIPT_POLICY_REVISION,
        "template_policy_revision": TEMPLATE_POLICY_REVISION,
        "chars_per_second": script_stage.CHARS_PER_SECOND,
        "automatic_max_chars": script_stage.AUTO_MAX_CHARS,
        "template_closers": [script_stage.CLOSER_PT, script_stage.CLOSER_EN],
        "curated_topics": script_stage.TOPIC_KEYS,
        "curated_texts": script_stage.CURATED,
        "idea": idea,
        "language": getattr(cfg, "language", ""),
        "duration_target": getattr(cfg, "duration_target", 0),
        "research_prompt": research_prompt or "",
        "research_target": target,
        "research_sources": sources,
        "genre_directive": genre_directive or "",
        "entity_context": entity_stage.script_context(
            research_target, getattr(cfg, "language", "")),
        "routes": llm_routes,
        "system_prompts": [prompts_stage.SCRIPT_SYSTEM_PROMPT,
                           prompts_stage.SCRIPT_SYSTEM_PROMPT_EN],
    })


def _title_input_hash(script_text, idea, cfg) -> str:
    """Identity of script/title inputs and title generation policy."""
    return input_identity({
        "revision": TITLE_POLICY_REVISION,
        "max_chars": script_stage.TITLE_MAX_CHARS,
        "script_sha256": text_identity(script_text),
        "idea": idea,
        "language": getattr(cfg, "language", ""),
        "routes": {
            "configured": {
            "nvidia": (getattr(cfg, "nvidia_model", ""),
                       getattr(cfg, "nvidia_base_url", ""),
                       getattr(cfg, "nvidia_timeout", None),
                       getattr(cfg, "nvidia_timeout_max", None),
                       getattr(cfg, "nvidia_connect_timeout", None)),
                "openrouter": (getattr(cfg, "openrouter_model", ""),
                               getattr(cfg, "openrouter_base_url", "")),
                "fallbacks": (cfg.llm_overrides() if callable(
                    getattr(cfg, "llm_overrides", None)) else {}),
            },
            "available": tuple(sorted(
                (name, *nvidia_stage.llm_settings(name))
                for name, credential in nvidia_stage.CREDENTIALS.items()
                if credential.from_env().available)),
        },
        "system_prompts": [prompts_stage.TITLE_SYSTEM_PROMPT,
                           prompts_stage.TITLE_SYSTEM_PROMPT_EN],
    })


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
