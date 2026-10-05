"""Project layout and artifact paths shared by generation interfaces."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .slug import find_project_root, project_dir


@dataclass
class VideoPaths:
    root: str
    script_txt: str
    script_manifest_json: str
    chapters_json: str
    scene_plan_json: str
    scene_plan_manifest_json: str
    title_txt: str
    media_json: str
    media_manifest_json: str
    sources_json: str
    sources_report: str
    contact_sheet: str
    narration_wav: str
    words_json: str
    tts_manifest_json: str
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
        script_manifest_json=os.path.join(root, "script", "artifacts.json"),
        chapters_json=os.path.join(root, "script", "chapters.json"),
        scene_plan_json=os.path.join(root, "script", "scene-plan.json"),
        scene_plan_manifest_json=os.path.join(
            root, "script", "scene-plan-manifest.json"),
        title_txt=os.path.join(root, "script", "title.txt"),
        media_json=os.path.join(root, "media", "media.json"),
        media_manifest_json=os.path.join(root, "media", "media-selection.json"),
        sources_json=os.path.join(root, "sources", "sources.json"),
        sources_report=os.path.join(root, "sources", "FONTES.md"),
        contact_sheet=os.path.join(root, "review", "contact_sheet.html"),
        narration_wav=os.path.join(root, "audio", "narration.wav"),
        words_json=os.path.join(root, "audio", "words.json"),
        tts_manifest_json=os.path.join(root, "audio", "tts-manifest.json"),
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


def paths_for_slug(out_dir: str, slug: str) -> tuple[str, VideoPaths]:
    """Resolve a project reference in the current or legacy output layout."""
    root = None
    if "/" in slug:
        genre_part, _, slug = slug.partition("/")
        candidate = project_dir(out_dir, genre_part, slug)
        if os.path.isdir(candidate):
            root = candidate
    else:
        root = find_project_root(out_dir, slug)
    if root is None:
        raise FileNotFoundError(
            f"projeto '{slug}' não encontrado em {out_dir}/ "
            f"(nem em {out_dir}/<genero>/{slug}).")
    genre = os.path.basename(os.path.dirname(root)) if \
        os.path.dirname(root) != out_dir else ""
    return slug, video_paths(out_dir, slug, genre)


def iter_projects(out_dir: str) -> list[tuple[str, str]]:
    """Return projects with metadata as `(reference, root)` pairs."""
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
