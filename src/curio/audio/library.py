"""Biblioteca persistente de música e SFX, com preenchimento oficial Freesound.

O uso normal só consulta arquivos locais. Rede só é usada por `update()` ou
quando `auto_fill` foi explicitamente habilitado e a biblioteca está abaixo do
mínimo. Freesound é acessado pela API oficial; só previews CC0/CC BY entram.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .. import ffmpeg as ff
from ..ua import user_agent

API_ROOT = "https://freesound.org/apiv2"
MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aiff", ".aif"}
GENRES = ("people", "history", "etymology", "mythology", "mystery", "science")
SFX_CATEGORIES = ("paper", "soft_impact")

MUSIC_DIRECTIONS = {
    "people": ("ambient piano", "contemplative"),
    "history": ("documentary historical ambient instrumental subtle tension", "documentary"),
    "etymology": ("curious intellectual light minimal instrumental ambient", "curious"),
    "mythology": ("ancient atmospheric literary instrumental ambient", "ancient"),
    "mystery": ("investigative documentary subtle suspense ambient instrumental", "investigative"),
    "science": ("clean modern minimal technical ambient instrumental", "minimal"),
}

SFX_QUERIES = {
    "paper": "paper",
    "soft_impact": "soft impact",
}


class AudioLibraryError(RuntimeError):
    """Erro recuperável de provider/asset audiovisual."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_part(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "")).strip("-_")
    return value[:80] or "unknown"


def _license_kind(value: str) -> str | None:
    """Aceita só CC0 e CC BY; NC, ND, SA e descrições ambíguas são recusadas."""
    text = (value or "").strip().lower().replace(" ", "")
    if text in {"creativecommons0", "cc0"} or \
            "creativecommons.org/publicdomain/zero/" in text:
        return "CC0"
    if text in {"attribution", "ccby", "creativecommonsby"}:
        return "CC BY"
    if re.search(r"creativecommons\.org/licenses/by/(3\.0|4\.0)/?$", text):
        return "CC BY"
    return None


def _license_url(value: str, license_kind: str) -> str:
    if (value or "").startswith(("https://", "http://")):
        return value
    if license_kind == "CC0":
        return "https://creativecommons.org/publicdomain/zero/1.0/"
    return "https://creativecommons.org/licenses/by/3.0/"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class FreesoundAudioSource:
    """Read-only API client; downloads only API-provided preview URLs."""

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or os.environ.get("FREESOUND_API_KEY", "")).strip()
        if not self.api_key:
            raise AudioLibraryError(
                "FREESOUND_API_KEY ausente; configure a chave oficial da API "
                "Freesound para atualizar a biblioteca")

    def _json(self, url: str) -> dict:
        req = urllib.request.Request(
            url, headers={"Authorization": f"Token {self.api_key}",
                          "User-Agent": user_agent()})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise AudioLibraryError(f"Freesound API: {exc}") from exc
        if not isinstance(data, dict):
            raise AudioLibraryError("Freesound API retornou resposta inválida")
        return data

    def search(self, query: str, limit: int = 30) -> list[dict]:
        params = urllib.parse.urlencode({
            "query": query,
            "page_size": max(1, min(int(limit), 50)),
            "fields": "id,name,username,url,license,duration,previews",
            "sort": "downloads_desc",
        })
        result = self._json(f"{API_ROOT}/search/?{params}")
        sounds = result.get("results") or []
        return [s for s in sounds if isinstance(s, dict)]

    def download_preview(self, url: str, path: Path) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not (
                parsed.hostname == "freesound.org" or
                (parsed.hostname or "").endswith(".freesound.org")):
            raise AudioLibraryError("URL de preview não pertence ao Freesound")
        req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".audio-", suffix=".part", dir=path.parent)
        try:
            total = 0
            with os.fdopen(fd, "wb") as out, urllib.request.urlopen(req, timeout=40) as resp:
                length = int(resp.headers.get("Content-Length") or 0)
                if length > MAX_DOWNLOAD_BYTES:
                    raise AudioLibraryError("preview acima do limite de tamanho")
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise AudioLibraryError("preview acima do limite de tamanho")
                    out.write(chunk)
            if not total:
                raise AudioLibraryError("preview vazio")
            os.replace(tmp, path)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AudioLibraryError(f"falha ao baixar preview oficial: {exc}") from exc
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


class AudioLibrary:
    def __init__(self, root: str | os.PathLike, source=None):
        self.root = Path(root).expanduser()
        self.source = source

    def directory(self, kind: str, genre: str, category: str | None = None) -> Path:
        if kind not in ("music", "sfx"):
            raise ValueError("kind precisa ser music ou sfx")
        path = self.root / kind / _safe_part(genre.lower())
        if kind == "sfx" and category:
            if category not in SFX_CATEGORIES:
                raise ValueError(f"categoria SFX inválida: {category}")
            path /= category
        path.mkdir(parents=True, exist_ok=True)
        return path

    def assets(self, kind: str, genre: str, category: str | None = None) -> list[dict]:
        folder = self.directory(kind, genre, category)
        found = []
        for meta_path in sorted(folder.glob("*.json")):
            meta = _read_json(meta_path)
            audio_path = folder / str(meta.get("filename") or "")
            if (audio_path.is_file() and audio_path.suffix.lower() in AUDIO_EXTENSIONS
                    and meta.get("asset_id")):
                meta["path"] = str(audio_path)
                meta["_meta_path"] = str(meta_path)
                found.append(meta)
        return found

    def count(self, kind: str, genre: str, category: str | None = None) -> int:
        return len(self.assets(kind, genre, category))

    def select(self, kind: str, genre: str, seed: str,
               category: str | None = None, mark_used: bool = False) -> dict | None:
        eligible = self.assets(kind, genre, category)
        if not eligible:
            return None
        least = min(max(0, int(a.get("use_count", 0))) for a in eligible)
        tied = [a for a in eligible if max(0, int(a.get("use_count", 0))) == least]
        tie_key = hashlib.sha256(str(seed).encode("utf-8")).digest()
        chosen = tied[int.from_bytes(tie_key[:8], "big") % len(tied)]
        result = dict(chosen)
        result.pop("_meta_path", None)
        if mark_used:
            path = Path(chosen["_meta_path"])
            updated = _read_json(path)
            updated["use_count"] = max(0, int(updated.get("use_count", 0))) + 1
            updated["last_used_at"] = _now()
            _write_json(path, updated)
            result.update(updated)
        return result

    def register(self, kind: str, genre: str, source_asset: dict,
                 category: str | None = None, max_count: int = 10,
                 min_duration: float = 0.0,
                 max_duration: float | None = None) -> dict | None:
        """Valida e cadastra um arquivo já baixado; preserva dedup e metadados."""
        folder = self.directory(kind, genre, category)
        asset_id = str(source_asset.get("asset_id") or "")
        if not asset_id:
            raise AudioLibraryError("asset sem id da fonte")
        existing = self.assets(kind, genre, category)
        if any(a.get("source_asset_id") == asset_id for a in existing):
            return None
        if len(existing) >= max(0, int(max_count)):
            return None
        temp_path = Path(str(source_asset.get("downloaded_path") or ""))
        if not temp_path.is_file() or temp_path.suffix.lower() not in AUDIO_EXTENSIONS:
            raise AudioLibraryError("arquivo de áudio ausente ou formato não suportado")
        try:
            duration = ff.probe_duration(str(temp_path))
        except Exception as exc:
            raise AudioLibraryError(f"arquivo inválido para ffprobe: {exc}") from exc
        if duration < min_duration or (max_duration is not None and duration > max_duration):
            raise AudioLibraryError(f"duração fora dos limites: {duration:.2f}s")
        digest = _sha256(temp_path)
        if any(a.get("sha256") == digest for a in existing):
            return None
        ext = temp_path.suffix.lower()
        stem = _safe_part(f"{source_asset.get('source', 'manual')}-{asset_id}")
        dest = folder / f"{stem}{ext}"
        if dest.exists():
            return None
        os.replace(temp_path, dest)
        metadata = {
            "asset_id": f"{source_asset.get('source', 'manual')}:{asset_id}",
            "source_asset_id": asset_id,
            "title": str(source_asset.get("title") or dest.stem),
            "author": str(source_asset.get("author") or ""),
            "source": str(source_asset.get("source") or "manual"),
            "source_url": str(source_asset.get("source_url") or ""),
            "download_url": str(source_asset.get("download_url") or ""),
            "license": str(source_asset.get("license") or ""),
            "license_url": str(source_asset.get("license_url") or ""),
            "downloaded_at": str(source_asset.get("downloaded_at") or _now()),
            "genres": [genre],
            "mood": list(source_asset.get("mood") or []),
            "category": category or "",
            "duration": round(duration, 3),
            "sha256": digest,
            "filename": dest.name,
            "use_count": 0,
            "last_used_at": "",
        }
        _write_json(dest.with_suffix(".json"), metadata)
        return {**metadata, "path": str(dest)}

    def update(self, kind: str, genre: str, target: int, max_count: int,
               category: str | None = None, source=None) -> dict:
        limit = max(0, min(int(target), int(max_count)))
        existing = self.assets(kind, genre, category)
        before = len(existing)
        missing = max(0, limit - before)
        report = {"kind": kind, "genre": genre, "category": category or "",
                  "before": before, "target": limit, "added": 0,
                  "rejected_license": 0, "license_rejections": [],
                  "duplicates": 0, "errors": []}
        if not missing:
            report["after"] = before
            return report
        source = source or self.source
        if source is None:
            source = FreesoundAudioSource()
        if kind == "music":
            query, mood = MUSIC_DIRECTIONS.get(genre, MUSIC_DIRECTIONS["history"])
            min_duration, max_duration = 20.0, 900.0
        else:
            if category not in SFX_QUERIES:
                raise AudioLibraryError("update SFX exige uma categoria reconhecida")
            query, mood = SFX_QUERIES[category], category
            min_duration, max_duration = 0.08, 12.0

        seen_ids = {str(a.get("source_asset_id")) for a in existing}
        # Uma busca limitada por update: só candidatos necessários + margem de
        # licenças/duplicatas; não varre páginas nem baixa uma coleção inteira.
        candidates = source.search(query, limit=min(50, max(12, missing * 4)))
        folder = self.directory(kind, genre, category)
        for item in candidates:
            if report["added"] >= missing:
                break
            source_id = str(item.get("id") or "")
            if not source_id or source_id in seen_ids:
                report["duplicates"] += 1
                continue
            seen_ids.add(source_id)
            raw_license = str(item.get("license") or "")
            lic = _license_kind(raw_license)
            if not lic:
                report["rejected_license"] += 1
                if len(report["license_rejections"]) < 8:
                    report["license_rejections"].append(
                        f"{source_id}: licença não aceita ({raw_license or 'ausente'}); "
                        "somente CC0 e CC BY são baixadas")
                continue
            reported_duration = float(item.get("duration") or 0)
            if reported_duration and (reported_duration < min_duration or
                                      reported_duration > max_duration):
                report["errors"].append(
                    f"{source_id}: duração fora dos limites informados ({reported_duration:.2f}s)")
                continue
            previews = item.get("previews") or {}
            preview_url = str(previews.get("preview-hq-mp3") or "")
            if not preview_url:
                report["errors"].append(f"{source_id}: sem preview-hq-mp3")
                continue
            ext = Path(urllib.parse.urlparse(preview_url).path).suffix.lower()
            if ext not in AUDIO_EXTENSIONS:
                ext = ".mp3"
            fd, name = tempfile.mkstemp(prefix=".candidate-", suffix=ext, dir=folder)
            os.close(fd)
            candidate_path = Path(name)
            try:
                source.download_preview(preview_url, candidate_path)
                metadata = {
                    "asset_id": source_id,
                    "source": "freesound",
                    "title": str(item.get("name") or ""),
                    "author": str(item.get("username") or ""),
                    "source_url": str(item.get("url") or
                                       f"https://freesound.org/people/{item.get('username','')}/sounds/{source_id}/"),
                    "download_url": preview_url,
                    "license": lic,
                    "license_url": _license_url(raw_license, lic),
                    "downloaded_at": _now(),
                    "mood": [mood],
                    "downloaded_path": str(candidate_path),
                }
                added = self.register(kind, genre, metadata, category,
                                      max_count=max_count,
                                      min_duration=min_duration,
                                      max_duration=max_duration)
                if added:
                    report["added"] += 1
                    seen_ids.add(source_id)
                else:
                    report["duplicates"] += 1
            except Exception as exc:
                report["errors"].append(f"{source_id}: {exc}")
            finally:
                if candidate_path.exists():
                    candidate_path.unlink()
        report["after"] = self.count(kind, genre, category)
        return report


def audio_seed(project_id: str, title: str, script: str) -> str:
    payload = "\0".join((project_id or "", title or "", script or ""))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
