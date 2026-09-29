"""Provedores de mídia pública (§4–5).

Abstração mínima: `MediaProvider.search()` retorna candidatos com licença.
Fontes sem chave (Wikimedia, Openverse) sempre ativas; com chave (Pexels)
só quando configurada — nunca quebram o pipeline ausentes.
Todas servem arquivos diretos sem marca d'água (política do Commons;
licença Pexels; Flickr via Openverse = original do autor).
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

USER_AGENT = "curio/0.1 (educational local video tool; no contact)"
TIMEOUT = 30
MAX_BYTES = 25 * 1024 * 1024
MIN_DIMENSION = 1000


@dataclass
class MediaAsset:
    provider: str
    asset_id: str
    title: str = ""
    author: str = ""
    license: str = ""
    source_url: str = ""
    download_url: str = ""
    download_fallback_url: str = ""  # ex.: Openverse `_b` se o `_k` 404/410
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    kind: str = "image"  # image | video (vídeos: etapa futura)
    local_path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MediaAsset":
        return cls(**{k: d.get(k, getattr(cls, k, "")) for k in
                      ("provider", "asset_id")},
                   **{k: d.get(k, "") for k in
                      ("title", "author", "license", "source_url",
                       "download_url", "download_fallback_url", "local_path")},
                   width=int(d.get("width", 0)), height=int(d.get("height", 0)),
                   size_bytes=int(d.get("size_bytes", 0)),
                   kind=str(d.get("kind", "image")))


class MediaError(RuntimeError):
    pass


class MediaProvider:
    name = "base"

    def search(self, query: str, limit: int = 5, metrics=None) -> list[MediaAsset]:
        raise NotImplementedError


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()[:200]


class WikimediaProvider(MediaProvider):
    """Wikimedia Commons: sem chave, licença documentada por arquivo."""

    name = "wikimedia"
    API = "https://commons.wikimedia.org/w/api.php"

    def search(self, query: str, limit: int = 5, metrics=None) -> list[MediaAsset]:
        params = {
            "action": "query", "format": "json",
            "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": "6", "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            # Thumbnails em vez do original: CDN tolerante + tamanho sob
            # controle (o upload de originais sofre 429 com uso repetido).
            "iiurlwidth": "1920",
        }
        req = urllib.request.Request(
            self.API + "?" + urllib.parse.urlencode(params),
            headers={"User-Agent": USER_AGENT})
        data = None
        last: Exception | None = None
        import time as _time
        _time.sleep(1.5)  # cortesia: throttling progressivo derruba o fim da lista
        for attempt in range(5):
            if metrics is not None:
                metrics.media_search(self.name)
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    import json
                    data = json.load(resp)
                break
            except Exception as exc:
                last = exc
                import time
                time.sleep(2 * (attempt + 1))
        if data is None:
            raise MediaError(f"wikimedia: busca falhou ({last})")
        assets = []
        pages = ((data.get("query") or {}).get("pages") or {}).values()
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("thumburl") or info.get("url", "")
            if not url or not re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.I):
                continue
            w, h = int(info.get("width", 0)), int(info.get("height", 0))
            size = int(info.get("size", 0))
            if min(w, h) < MIN_DIMENSION or size > MAX_BYTES or size <= 0:
                continue
            meta = info.get("extmetadata") or {}
            assets.append(MediaAsset(
                provider=self.name,
                asset_id=str(page.get("pageid", "")),
                title=str(page.get("title", "")),
                author=_strip_html((meta.get("Artist") or {}).get("value", "")),
                license=_strip_html((meta.get("LicenseShortName") or {}).get("value", ""))
                or "ver licença na source_url",
                source_url=str(page.get("fullurl") or info.get("descriptionurl", "")),
                download_url=url, width=w, height=h, size_bytes=size,
            ))
        return assets


_OV_LICENSES = {"by": "CC BY", "by-sa": "CC BY-SA", "by-nc": "CC BY-NC",
                 "by-nd": "CC BY-ND", "by-nc-sa": "CC BY-NC-SA",
                 "by-nc-nd": "CC BY-NC-ND", "pdm": "Domínio público",
                 "cc0": "CC0"}


class OpenverseProvider(MediaProvider):
    """Openverse (WordPress): sem chave, CC documentada, filtra `mature`."""

    name = "openverse"
    API = "https://api.openverse.org/v1/images/"

    def search(self, query: str, limit: int = 5, metrics=None) -> list[MediaAsset]:
        params = {"q": query, "page_size": str(limit),
                  "filter_dead": "false", "mature": "false"}
        req = urllib.request.Request(
            self.API + "?" + urllib.parse.urlencode(params),
            headers={"User-Agent": USER_AGENT})
        import time as _time
        _time.sleep(1.0)  # cortesia entre buscas
        if metrics is not None:
            metrics.media_search(self.name)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                import json
                data = json.load(resp)
        except Exception as exc:
            raise MediaError(f"openverse: busca falhou ({exc})") from exc
        assets = []
        for item in (data.get("results") or [])[:limit]:
            if item.get("mature"):
                continue
            url = item.get("url", "")
            if not url or not re.search(r"\.(jpe?g|png|webp)(\?|$|/)",
                                        url, re.I):
                continue
            upgraded = False
            fallback = ""
            if "live.staticflickr.com" in url:
                # Flickr serve `_b` (1024px); `_k` (2048px) existe na maioria
                # das fotos — sem ele quase tudo cai no filtro de resolução.
                # Nem toda foto tem `_k` (410/404): fallback guarda o `_b`.
                new_url = re.sub(r"_[a-z]\.(jpe?g|png)$", r"_k.\1", url)
                if new_url != url:
                    upgraded, fallback, url = True, url, new_url
            w, h = int(item.get("width") or 0), int(item.get("height") or 0)
            # Dims da API descrevem o `_b`; após upgrade o `_k` é ~2× maior.
            if not upgraded and w and h and min(w, h) < 800:
                continue
            lic = item.get("license", "")
            ver = item.get("license_version", "")
            assets.append(MediaAsset(
                provider=self.name,
                asset_id=str(item.get("id", "")),
                title=str(item.get("title", "")),
                author=str(item.get("creator", "")),
                license=f"{_OV_LICENSES.get(lic, lic)} {ver}".strip()
                or "ver licença na source_url",
                source_url=str(item.get("foreign_landing_url", "")),
                download_url=url, download_fallback_url=fallback,
                width=w, height=h,
            ))
        return assets


class PexelsProvider(MediaProvider):
    """Pexels: exige PEXELS_API_KEY (grátis com cadastro). Fotos sem watermark,
    licença Pexels (uso livre, sem atribuição obrigatória)."""

    name = "pexels"
    API = "https://api.pexels.com/v1/search"

    def __init__(self) -> None:
        import os as _os
        key = _os.environ.get("PEXELS_API_KEY", "").strip()
        if not key:
            raise MediaError("pexels: sem PEXELS_API_KEY no ambiente")
        self.key = key

    def search(self, query: str, limit: int = 5, metrics=None) -> list[MediaAsset]:
        params = {"query": query, "per_page": str(limit),
                  "orientation": "portrait"}
        req = urllib.request.Request(
            self.API + "?" + urllib.parse.urlencode(params),
            headers={"User-Agent": USER_AGENT, "Authorization": self.key})
        if metrics is not None:
            metrics.media_search(self.name)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                import json
                data = json.load(resp)
        except Exception as exc:
            raise MediaError(f"pexels: busca falhou ({exc})") from exc
        assets = []
        for photo in (data.get("photos") or [])[:limit]:
            src = photo.get("src") or {}
            url = src.get("large2x") or src.get("large") or src.get("original", "")
            if not url:
                continue
            w, h = int(photo.get("width") or 0), int(photo.get("height") or 0)
            if w and h and min(w, h) < MIN_DIMENSION:
                continue
            assets.append(MediaAsset(
                provider=self.name,
                asset_id=str(photo.get("id", "")),
                title=str(photo.get("alt", "")),
                author=str(photo.get("photographer", "")),
                license="Licença Pexels (uso livre)",
                source_url=str(photo.get("url", "")),
                download_url=url, width=w, height=h,
            ))
        return assets


PROVIDERS: dict[str, type[MediaProvider]] = {
    "wikimedia": WikimediaProvider,
    "openverse": OpenverseProvider,
    "pexels": PexelsProvider,
}


def get_providers(cfg) -> list[MediaProvider]:
    """Instancia os provedores configurados. Desconhecidos/sem chave: aviso."""
    wanted = [p.strip().lower() for p in cfg.media_providers.split(",") if p.strip()]
    if "none" in wanted:
        return []
    found = []
    for name in wanted:
        cls = PROVIDERS.get(name)
        if cls is None:
            print(f"AVISO: provedor de mídia {name!r} desconhecido — ignorado.",
                  file=sys.stderr)
            continue
        try:
            found.append(cls())
        except MediaError as exc:
            print(f"AVISO: {exc} — provedor ignorado.", file=sys.stderr)
    return found


def check_connectivity() -> bool:
    try:
        req = urllib.request.Request(
            WikimediaProvider.API + "?action=query&format=json&meta=siteinfo",
            headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:  # noqa: BLE001 — doctor só informa
        return False
