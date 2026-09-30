"""Provedores de mídia pública (§4–5).

Abstração mínima: `MediaProvider.search()` retorna candidatos com licença.
Fontes sem chave (Wikimedia, Openverse, NASA) sempre ativas; com chave
(Pexels, Unsplash) só quando configurada — nunca quebram o pipeline
ausentes. Todo asset carrega `license` (texto) + `license_url` (página
onde conferir) + `source_url` (página da obra) + `download_url` (arquivo).
Licenças NoDerivatives (ND) são recusadas em `license_ok`: vídeo é obra
derivada por construção (crop, zoom, legenda queimada).
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
    license_url: str = ""  # página onde conferir a licença do arquivo
    source_url: str = ""  # página da obra (antes do uso)
    download_url: str = ""  # arquivo direto (antes do uso)
    download_fallback_url: str = ""  # ex.: Openverse `_b` se o `_k` 404/410
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    kind: str = "image"  # image | video (vídeos: etapa futura)
    local_path: str = ""  # arquivo baixado (após o uso/download)
    used_in: str = ""  # onde entrou no vídeo (ex.: "cena 3")
    rights_status: str = ""  # clear | verify | blocked (ver classify_rights)

    def __post_init__(self) -> None:
        if not self.rights_status:
            self.rights_status = classify_rights(self.license, self.provider)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MediaAsset":
        return cls(**{k: d.get(k, getattr(cls, k, "")) for k in
                      ("provider", "asset_id")},
                   **{k: d.get(k, "") for k in
                      ("title", "author", "license", "license_url",
                       "source_url", "download_url", "download_fallback_url",
                       "local_path", "used_in", "rights_status")},
                   width=int(d.get("width", 0)), height=int(d.get("height", 0)),
                   size_bytes=int(d.get("size_bytes", 0)),
                   kind=str(d.get("kind", "image")))


def license_ok(license_text: str) -> bool:
    """Licença permite uso em vídeo? Recusa NoDerivatives (ND).

    Crop, zoom, pan e legenda queimada são derivações — arquivo ND não
    pode entrar, mesmo com atribuição. NC (não-comercial) passa com o
    texto registrado (o usuário decide sobre monetização).
    """
    t = (license_text or "").upper()
    if re.search(r"\b\w*-ND\b|\bND\b|NODERIVS?|NO-?DERIV", t):
        return False
    return True


# Licenças sabidamente livres p/ vídeo (usar, editar, queimar legenda).
_CLEAR_LICENSE_HINTS = (
    "DOMINIO PUBLICO", "PUBLIC DOMAIN", "CC0",
    "CC BY", "CC BY-SA", "PIXABAY", "PEXELS", "UNSPLASH",
    "ORIGINAL (GERADO", "MANUAL DO US",
)


def _norm_lic(text: str) -> str:
    """Maiúsculas sem acento p/ comparar licenças (ex.: DOMÍNIO→DOMINIO)."""
    import unicodedata
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in norm if not unicodedata.combining(c)).upper()


def classify_rights(license_text: str, provider: str = "") -> str:
    """Classifica o risco de copyright: 'clear' | 'verify' | 'blocked'.

    - blocked: ND ou "todos os direitos reservados"/© sem concessão livre
      → nunca entra no vídeo;
    - verify: desconhecida, vazia ou NC (não-comercial) → entra, mas é
      sinalizada em warnings + métricas p/ conferência manual;
    - clear: domínio público, CC-BY/SA, licenças dos bancos e arquivos
      manuais/sintéticos (responsabilidade/origem própria).
    """
    t = (license_text or "").upper()
    if (re.search(r"\b\w*-ND\b|\bND\b|NODERIVS?|NO-?DERIV", t)
            or re.search(r"ALL RIGHTS RESERVED|TODOS OS DIREITOS RESERVADOS|©|\(C\)", t)):
        return "blocked"
    if str(provider or "").lower() in ("manual", "synth"):
        return "clear"
    if re.search(r"\b\w*-NC\b|\bNC\b", t):
        return "verify"
    if any(h in _norm_lic(t) for h in _CLEAR_LICENSE_HINTS):
        return "clear"
    return "verify"


class MediaError(RuntimeError):
    pass


class MediaProvider:
    name = "base"

    def search(self, query: str, limit: int = 5, metrics=None) -> list[MediaAsset]:
        raise NotImplementedError


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()[:200]


PIXABAY_LICENSE_URL = "https://pixabay.com/service/license-summary/"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
UNSPLASH_LICENSE_URL = "https://unsplash.com/license"


def _http_get_json(url: str, headers: dict | None = None,
                   timeout: int = TIMEOUT):
    """GET JSON com User-Agent do projeto. Erros viram MediaError com código."""
    import json
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise MediaError(
            f"busca falhou (HTTP {exc.code}: {exc.reason})") from exc
    except Exception as exc:
        raise MediaError(f"busca falhou ({exc})") from exc


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
            page_url = str(page.get("fullurl") or info.get("descriptionurl", ""))
            lic = (_strip_html((meta.get("LicenseShortName") or {}).get("value", ""))
                   or "ver licença na source_url")
            if not license_ok(lic):
                continue  # ND: incompatível com edição de vídeo
            assets.append(MediaAsset(
                provider=self.name,
                asset_id=str(page.get("pageid", "")),
                title=str(page.get("title", "")),
                author=_strip_html((meta.get("Artist") or {}).get("value", "")),
                license=lic,
                license_url=page_url,  # a página do arquivo documenta a licença
                source_url=page_url,
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
            lic_text = (f"{_OV_LICENSES.get(lic, lic)} {ver}".strip()
                        or "ver licença na source_url")
            if not license_ok(lic_text):
                continue  # ND: incompatível com edição de vídeo
            page_url = str(item.get("foreign_landing_url", ""))
            assets.append(MediaAsset(
                provider=self.name,
                asset_id=str(item.get("id", "")),
                title=str(item.get("title", "")),
                author=str(item.get("creator", "")),
                license=lic_text,
                license_url=page_url,
                source_url=page_url,
                download_url=url, download_fallback_url=fallback,
                width=w, height=h,
            ))
        return assets


class PixabayProvider(MediaProvider):
    """Pixabay: exige PIXABAY_API_KEY (grátis com cadastro). Fotos e
    ilustrações sem marca d'água, licença Pixabay (uso livre).

    Usa User-Agent de navegador: o Cloudflare do Pixabay barra UAs de
    bot (erro 1010) mesmo com chave válida.
    """

    name = "pixabay"
    API = "https://pixabay.com/api/"
    BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

    def __init__(self) -> None:
        import os as _os
        key = _os.environ.get("PIXABAY_API_KEY", "").strip()
        if not key:
            raise MediaError("pixabay: sem PIXABAY_API_KEY no ambiente")
        self.key = key

    def search(self, query: str, limit: int = 5, metrics=None) -> list[MediaAsset]:
        params = {
            "key": self.key,
            "q": query,
            "image_type": "photo",
            # Pixabay exige per_page entre 3 e 200 (fora disso dá 400).
            "per_page": str(max(3, min(limit, 20))),
            "safesearch": "true",
        }
        req = urllib.request.Request(
            self.API + "?" + urllib.parse.urlencode(params),
            headers={"User-Agent": self.BROWSER_UA})
        if metrics is not None:
            metrics.media_search(self.name)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                import json
                data = json.load(resp)
        except Exception as exc:
            raise MediaError(f"pixabay: busca falhou ({exc})") from exc
        assets = []
        for item in (data.get("hits") or [])[:limit]:
            url = item.get("largeImageURL") or item.get("webformatURL", "")
            if not url or not re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.I):
                continue
            w, h = int(item.get("imageWidth") or 0), int(item.get("imageHeight") or 0)
            if w and h and min(w, h) < MIN_DIMENSION:
                continue
            assets.append(MediaAsset(
                provider=self.name,
                asset_id=str(item.get("id", "")),
                title=str(item.get("tags", "")),
                author=str(item.get("user", "")),
                license="Licença Pixabay (uso livre)",
                license_url=PIXABAY_LICENSE_URL,
                source_url=str(item.get("pageURL", "")),
                download_url=url, width=w, height=h,
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
                license_url=PEXELS_LICENSE_URL,
                source_url=str(photo.get("url", "")),
                download_url=url, width=w, height=h,
            ))
        return assets


class UnsplashProvider(MediaProvider):
    """Unsplash: exige UNSPLASH_ACCESS_KEY (grátis com cadastro; cota demo).

    Fotos sem marca d'água, Licença Unsplash (uso livre, inclusive
    comercial; atribuição apreciada, não obrigatória).
    """

    name = "unsplash"
    API = "https://api.unsplash.com/search/photos"

    def __init__(self) -> None:
        import os as _os
        key = _os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
        if not key:
            raise MediaError("unsplash: sem UNSPLASH_ACCESS_KEY no ambiente")
        self.key = key

    def search(self, query: str, limit: int = 5, metrics=None) -> list[MediaAsset]:
        params = {
            "query": query,
            "per_page": str(min(limit, 20)),
            "orientation": "portrait",
            "content_filter": "high",
        }
        url = self.API + "?" + urllib.parse.urlencode(params)
        if metrics is not None:
            metrics.media_search(self.name)
        try:
            data = _http_get_json(
                url, {"Authorization": f"Client-ID {self.key}"})
        except MediaError as exc:
            raise MediaError(f"unsplash: {exc}") from exc
        assets = []
        for photo in (data.get("results") or [])[:limit]:
            raw = ((photo.get("urls") or {}).get("raw", ""))
            if not raw:
                continue
            # raw via imgix: largura controlada (CDN tolerante, sem 429).
            sep = "&" if "?" in raw else "?"
            url = f"{raw}{sep}w=1920&q=80&fm=jpg"
            w, h = int(photo.get("width") or 0), int(photo.get("height") or 0)
            if w and h and min(w, h) < MIN_DIMENSION:
                continue
            user = photo.get("user") or {}
            links = photo.get("links") or {}
            assets.append(MediaAsset(
                provider=self.name,
                asset_id=str(photo.get("id", "")),
                title=str(photo.get("alt_description")
                          or photo.get("description") or photo.get("slug", "")),
                author=str(user.get("name", "")),
                license="Licença Unsplash (uso livre)",
                license_url=UNSPLASH_LICENSE_URL,
                source_url=str(links.get("html", "")),
                download_url=url, width=w, height=h,
            ))
        return assets


_NASA_CENTERS_PUBLIC_DOMAIN = {
    "NASA", "JPL", "GSFC", "JSC", "KSC", "MSFC", "ARC", "LARC",
    "GRC", "AFRC", "SSC", "HQ",
}


class NASAProvider(MediaProvider):
    """NASA Image and Video Library: sem chave, acervo público da NASA.

    Licença: conteúdo NASA é em regra domínio público (obra do governo
    federal dos EUA); cada arquivo carrega o link da página de detalhe
    para conferência (`license_url`). Sem dimensões na API — a validação
    de resolução acontece após o download (sonda ffprobe).
    """

    name = "nasa"
    API = "https://images-api.nasa.gov/search"

    def search(self, query: str, limit: int = 5, metrics=None) -> list[MediaAsset]:
        params = {"q": query, "media_type": "image",
                  "page_size": str(min(limit, 20))}
        url = self.API + "?" + urllib.parse.urlencode(params)
        if metrics is not None:
            metrics.media_search(self.name)
        try:
            data = _http_get_json(url)
        except MediaError as exc:
            raise MediaError(f"nasa: {exc}") from exc
        assets = []
        for item in ((data.get("collection") or {}).get("items") or []):
            info = (item.get("data") or [{}])[0]
            nasa_id = str(info.get("nasa_id", "")).strip()
            if not nasa_id:
                continue
            file_url = self._pick_file(item.get("href", ""))
            if not file_url:
                continue
            center = str(info.get("center", "")).strip().upper()
            if center in _NASA_CENTERS_PUBLIC_DOMAIN:
                lic = "Domínio público (NASA)"
            else:
                lic = (f"ver licença na source_url"
                       + (f" ({center})" if center else ""))
            detail = f"https://images.nasa.gov/details-{nasa_id}"
            keywords = [str(k) for k in (info.get("keywords") or [])[:5]]
            # Títulos NASA são IDs (ex.: "GRC-2005-C-01237"): anexa as
            # keywords para o gate de relevância consulta↔título funcionar.
            title = str(info.get("title", ""))
            if keywords:
                title = f"{title} ({', '.join(keywords)})"
            assets.append(MediaAsset(
                provider=self.name,
                asset_id=nasa_id,
                title=title,
                author=str(info.get("secondary_creator")
                           or info.get("photographer") or center),
                license=lic,
                license_url=detail,
                source_url=detail,
                download_url=file_url, width=0, height=0,
            ))
            if len(assets) >= limit:
                break
        return assets

    @staticmethod
    def _pick_file(manifest_url: str) -> str:
        """Escolhe um JPG do manifesto do item (evita TIFF original gigante)."""
        if not manifest_url:
            return ""
        try:
            files = _http_get_json(manifest_url)
        except MediaError:
            return ""
        if not isinstance(files, list):
            return ""
        jpgs = [f for f in files
                if isinstance(f, str) and re.search(r"\.jpe?g(\?|$)", f, re.I)]
        if not jpgs:
            return ""
        for hint in ("~large", "~medium", "~small", "~thumb"):
            for f in jpgs:
                if hint in f:
                    return f
        return jpgs[0]


PROVIDERS: dict[str, type[MediaProvider]] = {
    "pixabay": PixabayProvider,
    "unsplash": UnsplashProvider,
    "pexels": PexelsProvider,
    "nasa": NASAProvider,
    "wikimedia": WikimediaProvider,
    "openverse": OpenverseProvider,
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
