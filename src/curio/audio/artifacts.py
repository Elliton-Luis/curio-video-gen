"""Cache identity for synthesized narration and its word timing artifact."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from dataclasses import dataclass

SCHEMA_VERSION = 1


def tts_input_signature(text: str, provider: str, voice: str, speed: int,
                        target_duration: float, language: str) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "provider": provider,
        "voice": voice,
        "speed": int(speed),
        "target_duration": float(target_duration),
        "language": language,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def words_signature(words: list[dict] | None) -> str | None:
    if words is None:
        return None
    encoded = json.dumps(words, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def legacy_words_match_text(words: list[dict] | None, text: str) -> bool:
    """Prove a pre-manifest transcript belongs to this narration text."""
    if not words:
        return False
    expected = _tokens(text)
    actual = _tokens(" ".join(str(word.get("text", "")) for word in words
                               if isinstance(word, dict)))
    return bool(expected) and actual == expected


def _tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)


@dataclass(frozen=True)
class TTSCacheManifest:
    input_signature: str
    provider: str
    voice: str
    speed: int
    duration: float
    has_word_boundaries: bool
    words_signature: str | None

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "input_signature": self.input_signature,
            "provider": self.provider,
            "voice": self.voice,
            "speed": self.speed,
            "duration": self.duration,
            "has_word_boundaries": self.has_word_boundaries,
            "words_signature": self.words_signature,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "TTSCacheManifest":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported TTS cache schema")
        required = ("input_signature", "provider", "voice", "speed",
                    "duration", "has_word_boundaries")
        if any(key not in value for key in required):
            raise ValueError("incomplete TTS cache manifest")
        if not isinstance(value["has_word_boundaries"], bool):
            raise ValueError("invalid TTS cache word-boundary flag")
        signature = value.get("words_signature")
        if signature is not None and not isinstance(signature, str):
            raise ValueError("invalid TTS cache word signature")
        manifest = cls(
            input_signature=str(value["input_signature"]),
            provider=str(value["provider"]), voice=str(value["voice"]),
            speed=int(value["speed"]), duration=float(value["duration"]),
            has_word_boundaries=value["has_word_boundaries"],
            words_signature=signature)
        if not manifest.input_signature or not manifest.provider or not manifest.voice:
            raise ValueError("incomplete TTS cache identity")
        if not math.isfinite(manifest.duration) or manifest.duration <= 0:
            raise ValueError("invalid TTS cache duration")
        if manifest.has_word_boundaries != (manifest.words_signature is not None):
            raise ValueError("TTS word-boundary metadata disagrees")
        return manifest


def read_tts_manifest(path: str) -> TTSCacheManifest | None:
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            return None
        return TTSCacheManifest.from_dict(value)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def write_tts_manifest(path: str, manifest: TTSCacheManifest) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(manifest.to_dict(), stream, ensure_ascii=False, indent=1)
    os.replace(temporary, path)
