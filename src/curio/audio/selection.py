"""Seleção, identidade de render e diagnóstico de áudio por projeto."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .library import AudioLibrary, AudioLibraryError
from .. import ffmpeg as ff


def _public(asset: dict | None) -> dict | None:
    if not asset:
        return None
    return {k: asset.get(k) for k in (
        "asset_id", "title", "author", "source", "source_url", "license",
        "license_url", "downloaded_at", "duration", "path", "mood", "category",
        "sha256")}


def _same_request(previous: dict, mode: str, genre: str, gain: int,
                  ducking: bool) -> bool:
    return (previous.get("mode") == mode and previous.get("genre") == genre
            and previous.get("gain_db") == gain
            and previous.get("ducking") == ducking)


def resolve_audio(cfg, genre: str, seed: str, title: str, script: str,
                  sfx_events: list[dict], previous: dict | None = None) -> dict:
    """Resolve os arquivos uma vez para a geração; não faz rede salvo opt-in.

    Se o metadata do mesmo projeto já aponta para assets locais válidos e os
    parâmetros não mudaram, mantém a mesma seleção inclusive após `--force`.
    """
    requested_mode = str(getattr(cfg, "music_mode", "auto") or "auto").lower()
    genre = genre or "people"  # identidade de áudio neutra, sem mudar gênero editorial
    enabled = bool(getattr(cfg, "audio_enabled", False)) or requested_mode != "auto"
    mode = requested_mode if enabled else "none"
    if mode not in ("auto", "none", "manual"):
        mode = "auto"
    gain = int(getattr(cfg, "music_gain_db", -21))
    ducking = bool(getattr(cfg, "music_ducking", True))
    previous = previous if isinstance(previous, dict) else {}
    library = AudioLibrary(getattr(cfg, "audio_library_dir", "assets/library"))
    warnings: list[str] = []
    music_asset = None

    old_music = previous.get("music") if isinstance(previous.get("music"), dict) else {}
    old_track = old_music.get("track") if isinstance(old_music.get("track"), dict) else {}
    if mode == "manual":
        manual = os.path.abspath(os.path.expanduser(
            str(getattr(cfg, "music_file", "") or "")))
        if manual and os.path.isfile(manual):
            try:
                duration = ff.probe_duration(manual)
                music_asset = {
                    "asset_id": f"manual:{hashlib.sha256(manual.encode()).hexdigest()[:16]}",
                    "title": Path(manual).name, "author": "", "source": "manual",
                    "source_url": "", "license": "user-supplied; not verified",
                    "license_url": "", "downloaded_at": "", "duration": duration,
                    "path": manual, "mood": [], "category": "music",
                }
            except Exception as exc:
                warnings.append(f"music manual: áudio inválido ({exc}); vídeo sem música")
        else:
            warnings.append("music manual: arquivo não informado ou inexistente; vídeo sem música")
    elif mode == "auto" and genre:
        same_music_request = _same_request(old_music, mode, genre, gain, ducking)
        if (same_music_request and "track" in old_music):
            if (old_track.get("asset_id") and
                    os.path.isfile(str(old_track.get("path") or ""))):
                music_asset = dict(old_track)
        else:
            current = library.count("music", genre)
            minimum = max(0, int(getattr(cfg, "music_min_per_genre", 3)))
            if current < minimum and bool(getattr(cfg, "music_auto_fill", False)):
                try:
                    report = library.update(
                        "music", genre,
                        int(getattr(cfg, "music_target_per_genre", 6)),
                        int(getattr(cfg, "music_max_per_genre", 10)))
                    if report.get("rejected_license"):
                        warnings.append(
                            f"Freesound: {report['rejected_license']} asset(s) ignorados; "
                            "a biblioteca aceita apenas CC0 e CC BY")
                    warnings.extend(
                        f"biblioteca musical {genre}: {err}"
                        for err in report.get("errors", [])[:3])
                except (AudioLibraryError, OSError) as exc:
                    warnings.append(f"biblioteca musical {genre}: autopreenchimento ignorado ({exc})")
            music_asset = library.select("music", genre, seed)
            if not music_asset:
                warnings.append(f"biblioteca musical {genre} vazia; render sem música")

    # SFX musicais baixados substituem apenas eventos já planejados pelo
    # pipeline. Sem asset local, o SFX sintético existente permanece.
    sfx_enabled = (enabled and bool(getattr(cfg, "visual_sfx", True)) and
                   bool(getattr(cfg, "sfx_library_enabled", True)))
    old_sfx = previous.get("sfx") if isinstance(previous.get("sfx"), dict) else {}
    prior_assets = old_sfx.get("assets") or []
    keep_sfx_selection = (_same_request(old_music, mode, genre, gain, ducking)
                           and "assets" in old_sfx
                           and len(prior_assets) == len(sfx_events))
    sfx_assets: list[dict] = []
    if sfx_enabled and genre:
        updated_categories: set[str] = set()
        for index, event in enumerate(sfx_events):
            category = "paper" if event.get("kind") == "swish" else "soft_impact"
            previous_asset = prior_assets[index] if index < len(prior_assets) else {}
            if (_same_request(old_music, mode, genre, gain, ducking)
                    and previous_asset.get("category") == category
                    and os.path.isfile(str(previous_asset.get("path") or ""))):
                asset = dict(previous_asset)
            else:
                if keep_sfx_selection:
                    continue
                minimum = max(0, int(getattr(cfg, "sfx_min_per_category", 2)))
                if (category not in updated_categories and
                        library.count("sfx", genre, category) < minimum and
                        bool(getattr(cfg, "sfx_auto_fill", False))):
                    updated_categories.add(category)
                    try:
                        report = library.update(
                            "sfx", genre,
                            int(getattr(cfg, "sfx_target_per_category", 5)),
                            int(getattr(cfg, "sfx_max_per_category", 8)),
                            category=category)
                        if report.get("rejected_license"):
                            warnings.append(
                                f"Freesound: {report['rejected_license']} asset(s) SFX "
                                "ignorados; apenas CC0 e CC BY são aceitos")
                        warnings.extend(
                            f"biblioteca SFX {genre}/{category}: {err}"
                            for err in report.get("errors", [])[:3])
                    except (AudioLibraryError, OSError) as exc:
                        warnings.append(
                            f"biblioteca SFX {genre}/{category}: autopreenchimento ignorado ({exc})")
                asset = library.select(
                    "sfx", genre, f"{seed}:sfx:{index}", category=category)
            if asset:
                event["path"] = asset["path"]
                event["asset_id"] = asset.get("asset_id")
                event["category"] = category
                sfx_assets.append(_public(asset))

    transition_mode = (str(getattr(cfg, "music_transitions", "auto") or "auto")
                       if enabled else "none")
    audio = {
        "music": {"mode": mode, "genre": genre, "track": _public(music_asset),
                  "gain_db": gain, "ducking": ducking},
        "sfx": {"mode": "library" if sfx_assets else
                ("generated" if sfx_enabled and sfx_events else "none"),
                "assets": sfx_assets},
        "transitions": {"mode": transition_mode},
        "warnings": warnings,
        "credits": [f"{asset.get('title', '')} — {asset.get('author', '')} — "
                    f"{asset.get('license', '')} — {asset.get('source_url', '')}"
                    for asset in [music_asset, *sfx_assets]
                    if asset and asset.get("license") == "CC BY"],
    }
    identity = {
        "mode": mode, "genre": genre,
        "audio_enabled": enabled,
        "music_id": (music_asset or {}).get("asset_id", ""),
        "music_path": (music_asset or {}).get("path", ""),
        "music_mtime": _mtime((music_asset or {}).get("path")),
        "music_content": _content_hash((music_asset or {}).get("path")),
        "gain_db": gain, "ducking": ducking,
        "sfx": [a.get("asset_id") for a in sfx_assets],
        "sfx_mtimes": [_mtime(a.get("path")) for a in sfx_assets],
        "sfx_content": [_content_hash(a.get("path")) for a in sfx_assets],
        "sfx_gain_db": getattr(cfg, "visual_insert_gain_db", -30),
        "sfx_events": [{k: e.get(k) for k in
                        ("kind", "at", "duration", "gain_db", "asset_id")}
                       for e in sfx_events],
        "sfx_enabled": sfx_enabled,
        "transition_mode": transition_mode,
    }
    audio["signature"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {"metadata": audio, "music_asset": music_asset,
            "sfx_assets": sfx_assets, "warnings": warnings}


def _mtime(path: str | None) -> int | None:
    try:
        return os.stat(path).st_mtime_ns if path else None
    except OSError:
        return None


def _content_hash(path: str | None) -> str:
    if not path or not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def mark_used(library_root: str, music_asset: dict | None,
              sfx_assets: list[dict]) -> None:
    """Incrementa contadores só depois de um render que realmente usou assets."""
    lib = AudioLibrary(library_root)
    seen: set[str] = set()
    for item in [music_asset, *(sfx_assets or [])]:
        if not item:
            continue
        aid = str(item.get("asset_id") or "")
        path = str(item.get("path") or "")
        if not aid or not path or aid in seen or item.get("source") == "manual":
            continue
        seen.add(aid)
        p = Path(path)
        meta = p.with_suffix(".json")
        if meta.is_file():
            data = json.loads(meta.read_text(encoding="utf-8"))
            data["use_count"] = max(0, int(data.get("use_count", 0))) + 1
            from .library import _now, _write_json
            data["last_used_at"] = _now()
            _write_json(meta, data)
