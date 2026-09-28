"""Provedores de mídia pública (§4–5).

Abstração mínima: `MediaProvider.search()` retorna candidatos com licença.
Só integra o que funciona sem chave (Wikimedia). Fontes com chave entram
via registro quando houver credencial — nunca quebram o pipeline ausentes.
"""

from __future__ import annotations

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
                       "download_url", "local_path")},
                   width=int(d.get("width", 0)), height=int(d.get("height", 0)),
                   size_bytes=int(d.get("size_bytes", 0)),
                   kind=str(d.get("kind", "image")))


class MediaError(RuntimeError):
    pass


class MediaProvider:
    name = "base"

    def search(self, query: str, limit: int = 5) -> list[MediaAsset]:
        raise NotImplementedError


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()[:200]


class WikimediaProvider(MediaProvider):
    """Wikimedia Commons: sem chave, licença documentada por arquivo."""

    name = "wikimedia"
    API = "https://commons.wikimedia.org/w/api.php"

    def search(self, query: str, limit: int = 5) -> list[MediaAsset]:
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
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    import json
                    data = json.load(resp)
                break
            except Exception as exc:
                last = exc
                import time
                time.sleep(1.5 * (attempt + 1))
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


PROVIDERS: dict[str, type[MediaProvider]] = {
    "wikimedia": WikimediaProvider,
}


def get_providers(cfg) -> list[MediaProvider]:
    """Instancia os provedores configurados. Desconhecidos: aviso, nunca erro."""
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
        found.append(cls())
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
