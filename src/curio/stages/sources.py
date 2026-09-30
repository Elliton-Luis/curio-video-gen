"""Verificação de fatos com fontes confiáveis (persistidas no projeto).

Antes de tratar uma afirmação como válida para o roteiro, é preciso que ela
tenha suporte em fonte confiável. Este módulo gerencia o registro de fontes
de um projeto, salvo em `output/<slug>/sources/sources.json`, com:

- claims: afirmações factuais verificadas (com status de evidência);
- media_sources: procedência das mídias (imagem/vídeo) utilizadas.

As fontes acompanham o projeto durante todo o ciclo de vida: reabrir o
projeto mostra as fontes anteriores, e novas pesquisas são adicionadas sem
apagar o histórico. URLs nunca são geradas a partir da memória do modelo —
só são salvas as URLs retornadas pela pesquisa.

Status de evidência:
  confirmed  — confirmado por ≥1 fonte confiável (idealmente ≥2
               independentes);
  partial    — confirmado em parte ou por uma única fonte;
  contested  — fontes confiáveis divergem (registra a divergência);
  unverified — sem fonte confiável; não deve virar fato no roteiro.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

EVIDENCE_STATUS = ("confirmed", "partial", "contested", "unverified")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class Source:
    """Uma fonte que sustenta uma afirmação factual."""
    claim: str
    title: str
    url: str
    consulted_at: str = ""
    author: str = ""
    date: str = ""
    evidence: str = ""
    status: str = "confirmed"
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Source":
        allowed = {k: d.get(k, "") for k in
                   ("claim", "title", "url", "consulted_at", "author",
                    "date", "evidence", "status", "notes")}
        if allowed["status"] not in EVIDENCE_STATUS:
            allowed["status"] = "unverified"
        return cls(**allowed)


@dataclass
class MediaSource:
    """Procedência de uma mídia (imagem/vídeo) utilizada no projeto.

    Guarda o link ANTES do uso (origin_url = página da obra, file_url =
    arquivo direto, license_url = onde conferir a licença) e o local
    APÓS o uso (local_path) mais onde entrou no vídeo (used_in).
    """
    title: str
    origin_url: str = ""
    file_url: str = ""
    provider: str = ""
    author: str = ""
    license: str = ""
    license_url: str = ""
    local_path: str = ""
    used_in: str = ""
    rights_status: str = ""  # clear | verify | blocked
    query: str = ""
    scene: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MediaSource":
        return cls(**{k: d.get(k, "") for k in
                      ("title", "origin_url", "file_url", "provider",
                       "author", "license", "license_url", "local_path",
                       "used_in", "rights_status", "query", "scene")})


@dataclass
class SourceRegistry:
    """Registro de fontes de um projeto. Persiste como JSON no projeto."""
    slug: str
    claims: list[Source] = field(default_factory=list)
    media: list[MediaSource] = field(default_factory=list)

    def add_claim(self, claim: str, title: str, url: str, evidence: str,
                  author: str = "", date: str = "", status: str = "confirmed",
                  notes: str = "") -> Source:
        """Adiciona (ou reutiliza) fonte de afirmação factual.

        Se a mesma URL+claim já existir, reusa (sem duplicar).
        """
        for src in self.claims:
            if src.url == url and src.claim == claim:
                return src
        src = Source(claim=claim, title=title, url=url, evidence=evidence,
                     author=author, date=date, status=status,
                     notes=notes, consulted_at=_now())
        self.claims.append(src)
        return src

    def add_media(self, title: str, origin_url: str, file_url: str,
                  provider: str, author: str = "", license: str = "",
                  query: str = "", scene: str = "",
                  license_url: str = "", local_path: str = "",
                  used_in: str = "", rights_status: str = "") -> MediaSource:
        """Registra procedência de mídia. Reutiliza se (title, origin_url)
        já estiver registrada (completa os campos de uso se vazios)."""
        for src in self.media:
            if src.title == title and src.origin_url == origin_url:
                if not src.local_path and local_path:
                    src.local_path = local_path
                if not src.used_in and used_in:
                    src.used_in = used_in
                if not src.license_url and license_url:
                    src.license_url = license_url
                if not src.rights_status and rights_status:
                    src.rights_status = rights_status
                return src
        src = MediaSource(title=title, origin_url=origin_url,
                          file_url=file_url, provider=provider, author=author,
                          license=license, license_url=license_url,
                          local_path=local_path, used_in=used_in,
                          rights_status=rights_status,
                          query=query, scene=scene)
        self.media.append(src)
        return src

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "claims": [c.to_dict() for c in self.claims],
            "media": [m.to_dict() for m in self.media],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourceRegistry":
        return cls(
            slug=str(d.get("slug", "")),
            claims=[Source.from_dict(c) for c in d.get("claims", [])],
            media=[MediaSource.from_dict(m) for m in d.get("media", [])],
        )

    def save(self, path: str) -> None:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path: str) -> "SourceRegistry":
        """Carrega registro existente (ou vazio se inexistente/corrompido)."""
        if not os.path.isfile(path):
            return cls(slug="")
        try:
            with open(path, encoding="utf-8") as fh:
                reg = cls.from_dict(json.load(fh))
            return reg
        except (json.JSONDecodeError, KeyError, TypeError):
            return cls(slug="")
