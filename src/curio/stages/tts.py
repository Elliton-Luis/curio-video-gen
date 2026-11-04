"""Narração via TTS com provedores intercambiáveis (PRD §8).

Produção usa vozes neurais: Edge TTS e, como fallback, Piper hospedado pelo
TTS.ai. eSpeak só pode ser selecionado em pré-avaliação explícita.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .. import ffmpeg as ff

DEFAULT_EDGE_VOICE = "pt-BR-AntonioNeural"  # masculina, PT-BR

# Cobertura mínima exigida: fração das palavras do roteiro com timestamps.
# Divergências legítimas (tokenização edge vs split) ficam <1%; síntese
# parcial interrompida cai para ~15% — o gate separa os dois regimes.
TTS_MIN_COVERAGE = 0.90
# Tentativas da voz neural antes do fallback local (causa é transitória).
TTS_EDGE_ATTEMPTS = 3

# NOTA: pausas SSML (<break>) foram avaliadas e descartadas — com entrada
# SSML o Edge retorna boundaries dos TOKENS DO MARKUP (speak, voice, break…),
# inutilizando os timestamps. Texto puro + WordBoundary dá palavras reais.


class TTSError(RuntimeError):
    pass


@dataclass
class TTSResult:
    path: str
    duration: float
    provider: str
    voice: str
    speed: int
    words: list[dict] | None = None  # [{text, start, end}] timestamps reais


def available_providers() -> list[str]:
    found = []
    if shutil.which("espeak-ng"):
        found.append("espeak-ng")
    if shutil.which("piper"):
        found.append("piper")
    try:
        __import__("edge_tts")
        found.append("edge-tts")
    except ImportError:
        pass
    found.append("tts.ai")
    return found


def _estimate_wpm(text: str, duration: float) -> int:
    words = len(text.split())
    return round(words / max(duration, 0.1) * 60)


def tts_coverage_ok(words: list[dict] | None, text: str) -> bool:
    """Os timestamps cobrem o roteiro? (gate pós-síntese e do cache).

    Síntese parcial (stream interrompido) retorna fração pequena das
    palavras sem erro — sem este gate o pipeline produziria um vídeo
    curto em silêncio parcial.
    """
    expected = len((text or "").split())
    if expected <= 0 or not words:
        return False
    return len(words) / expected >= TTS_MIN_COVERAGE


def _check_edge_result(words: list[dict], duration: float,
                       text: str, voice: str) -> None:
    """Valida síntese edge-tts completa; levanta TTSError se parcial."""
    if not tts_coverage_ok(words, text):
        raise TTSError(
            f"edge-tts retornou narração parcial (voz={voice!r}): "
            f"{len(words or [])}/{len(text.split())} palavras — "
            "o serviço interrompeu o stream.")
    if words and duration < words[-1]["end"] - 2.0:
        raise TTSError(
            f"edge-tts retornou áudio inconsistente (voz={voice!r}): "
            f"áudio {duration:.1f}s < última palavra {words[-1]['end']:.1f}s.")


def _synth_edge(text: str, wav_path: str, voice: str, rate: str,
                words_path: str | None = None, metrics=None) -> list[dict]:
    """Voz neural via Edge (grátis, sem login). Requer pacote + internet.

    Texto puro + boundary=WordBoundary: captura timestamps reais por palavra
    (offsets em ticks de 100ns → segundos). Retorna a lista de palavras.
    """
    try:
        import edge_tts
    except ImportError as exc:
        raise TTSError(
            "pacote edge-tts não instalado. Rode `scripts/install.sh` "
            "ou `pip install edge-tts`."
        ) from exc
    import asyncio

    if voice in ("pt-br", "pt-BR", ""):
        voice = DEFAULT_EDGE_VOICE
    mp3_path = wav_path + ".edge.mp3"

    words: list[dict] = []
    audio_parts: list[bytes] = []

    async def _stream() -> None:
        async for chunk in edge_tts.Communicate(
                text, voice, rate=rate, boundary="WordBoundary").stream():
            if chunk.get("type") == "WordBoundary":
                wtext = (chunk.get("text") or "").strip()
                if wtext:
                    words.append({
                        "text": wtext,
                        "start": round((chunk.get("offset") or 0) / 10_000_000, 3),
                        "end": round(((chunk.get("offset") or 0)
                                      + (chunk.get("duration") or 0)) / 10_000_000, 3),
                    })
            elif chunk.get("type") == "audio":
                audio_parts.append(chunk.get("data") or b"")

    try:
        asyncio.run(_stream())
    except Exception as exc:
        raise TTSError(f"edge-tts falhou (voz={voice!r}): {exc}") from exc
    if not audio_parts:
        raise TTSError(f"edge-tts não retornou áudio (voz={voice!r}).")
    if metrics is not None:
        metrics.tts("edge-tts", len(text))
    with open(mp3_path, "wb") as fh:
        for part in audio_parts:
            fh.write(part)
    proc = ff.run([ff.FFMPEG, "-y", "-v", "error", "-i", mp3_path,
                   "-ar", "48000", "-ac", "2", wav_path])
    os.remove(mp3_path)
    if proc.returncode != 0:
        raise TTSError(
            f"conversão do áudio edge-tts falhou: {proc.stderr.strip()}")
    if words_path:
        import json
        with open(words_path, "w", encoding="utf-8") as fh:
            json.dump(words, fh, ensure_ascii=False, indent=1)
    return words


def _synth_espeak(text: str, wav_path: str, voice: str, speed: int,
                  metrics=None) -> None:
    txt_path = wav_path + ".txt"
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    proc = subprocess.run(
        ["espeak-ng", "-v", voice, "-s", str(speed), "-w", wav_path, "-f", txt_path],
        capture_output=True, text=True,
    )
    os.remove(txt_path)
    if metrics is not None:
        metrics.tts("espeak-ng", len(text))
    if proc.returncode != 0:
        raise TTSError(
            f"espeak-ng falhou (voz={voice!r}): {proc.stderr.strip() or proc.stdout.strip()}. "
            "Rode `video-gen doctor`."
        )


def synthesize(text: str, wav_path: str, provider: str, voice: str,
               speed: int, target_duration: float,
               words_path: str | None = None, metrics=None,
               language: str = "pt-BR", preview: bool = False) -> TTSResult:
    if provider not in ("edge-tts", "espeak-ng", "auto", "tts.ai"):
        raise TTSError(
            f"provedor TTS {provider!r} desconhecido "
            f"(disponíveis: {available_providers() or ['nenhum']})."
        )
    ff.require_tools()
    if provider == "espeak-ng":
        if not preview:
            raise TTSError(
                "eSpeak é permitido apenas em pré-avaliação. "
                "Defina CURIO_TTS_PREVIEW=1 para usá-lo explicitamente."
            )
        return _synthesize_espeak(
            text, wav_path, "en-us" if language.startswith("en") else "pt-br",
            speed, target_duration, metrics)

    if provider == "tts.ai":
        order = ("tts.ai", "edge-tts")
    else:
        order = ("edge-tts", "tts.ai")
    if not language.lower().startswith("pt"):
        order = tuple(name for name in order if name != "tts.ai")

    errors: list[str] = []
    for index, name in enumerate(order):
        try:
            if name == "edge-tts":
                edge_voice = voice
                if edge_voice in ("pt-br", "pt-BR", "en-us", "en-US", ""):
                    edge_voice = ("en-US-GuyNeural" if language.startswith("en")
                                  else DEFAULT_EDGE_VOICE)
                elif "_" in edge_voice or edge_voice.endswith(("-low", "-medium", "-high")):
                    # A Piper voice identifier is not an Edge voice name.
                    edge_voice = ("en-US-GuyNeural" if language.startswith("en")
                                  else DEFAULT_EDGE_VOICE)
                last_error: TTSError | None = None
                for attempt in range(1, TTS_EDGE_ATTEMPTS + 1):
                    try:
                        return _synthesize_edge(text, wav_path, edge_voice,
                                                target_duration, words_path,
                                                metrics)
                    except TTSError as exc:
                        last_error = exc
                        if attempt < TTS_EDGE_ATTEMPTS:
                            from ..runlog import event as run_event
                            run_event(
                                "retry", f"Edge TTS: tentativa {attempt}/"
                                f"{TTS_EDGE_ATTEMPTS}; {exc}", operation="tts",
                                provider="edge-tts", attempt=attempt,
                                attempts=TTS_EDGE_ATTEMPTS, error=str(exc))
                            time.sleep(2 * attempt)
                assert last_error is not None
                raise last_error

            piper_voice = voice
            if piper_voice in ("pt-br", "pt-BR", "en-us", "en-US", "") \
                    or piper_voice.lower().endswith("neural"):
                piper_voice = "pt_BR-faber-medium"
            return _synthesize_ttsai(text, wav_path, piper_voice, speed, metrics)
        except TTSError as exc:
            errors.append(f"{name}: {exc}")
            if index < len(order) - 1:
                from ..runlog import event as run_event
                run_event("fallback", f"{name} indisponível; tentando {order[index + 1]}",
                          operation="tts", fallback=order[index + 1],
                          provider=name, error=str(exc))

    if preview and shutil.which("espeak-ng"):
        from ..runlog import event as run_event
        run_event("fallback", "Provedores neurais indisponíveis; eSpeak em pré-avaliação",
                  operation="tts", fallback="espeak-ng", preview=True)
        return _synthesize_espeak(
            text, wav_path, "en-us" if language.startswith("en") else "pt-br",
            speed, target_duration, metrics)
    detail = " | ".join(errors) or "nenhum provedor neural disponível"
    suffix = " eSpeak não será usado em um render final." if not preview else ""
    raise TTSError(f"Falharam os provedores de voz neural: {detail}.{suffix}")


def _synthesize_ttsai(text: str, wav_path: str, voice: str, speed: int,
                      metrics=None) -> TTSResult:
    """Anonymous hosted TTS.ai API; never falls back to local synthesis."""
    voice = voice if voice not in ("pt-br", "pt-BR", "") else "pt_BR-faber-medium"
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > 480:
            cut = sentence.rfind(" ", 0, 480)
            if cut < 1:
                cut = 480
            part, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if current:
                chunks.append(current)
                current = ""
            chunks.append(part)
        if sentence and len(current) + len(sentence) + bool(current) <= 480:
            current = f"{current} {sentence}".strip()
        elif sentence:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    if not chunks:
        raise TTSError("tts.ai recebeu texto vazio.")

    def request(url: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json", "User-Agent": "Curio/1.0"}
        api_key = os.environ.get("TTS_AI_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, data=data,
                                    headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                reset = exc.headers.get("X-RateLimit-Reset", "")
                suffix = f"; limite reinicia em {reset}" if reset else ""
                raise TTSError(
                    "tts.ai atingiu o limite de uso; configure TTS_AI_API_KEY "
                    f"para ampliar a cota{suffix}.") from exc
            raise TTSError(f"tts.ai API falhou: {exc}") from exc
        except Exception as exc:
            raise TTSError(f"tts.ai API falhou: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix="curio-ttsai-") as temp:
        wav_parts = []
        for index, chunk in enumerate(chunks):
            result = request("https://api.tts.ai/v1/tts/", {
                "model": "piper", "text": chunk, "voice": voice,
                "language": "pt", "format": "mp3",
                "speed": max(0.75, min(1.25, speed / 170)),
            })
            job = result.get("uuid") or result.get("id")
            if not job:
                raise TTSError("tts.ai não retornou identificador do áudio.")
            audio_url = None
            for _ in range(60):
                status = request(f"https://api.tts.ai/v1/speech/results/?uuid={job}")
                if status.get("status") in ("completed", "success", "done"):
                    audio_url = status.get("url") or status.get("audio_url") or status.get("result")
                    break
                if status.get("status") in ("failed", "error"):
                    raise TTSError(f"tts.ai falhou na parte {index + 1}.")
                time.sleep(2)
            if not isinstance(audio_url, str) or not audio_url.startswith("https://"):
                raise TTSError("tts.ai não concluiu a geração do áudio.")
            mp3 = os.path.join(temp, f"part-{index:03}.mp3")
            wav = os.path.join(temp, f"part-{index:03}.wav")
            try:
                urllib.request.urlretrieve(audio_url, mp3)
            except Exception as exc:
                raise TTSError(f"download tts.ai falhou: {exc}") from exc
            proc = ff.run([ff.FFMPEG, "-y", "-v", "error", "-i", mp3,
                           "-ar", "48000", "-ac", "2", wav])
            if proc.returncode:
                raise TTSError("áudio retornado por tts.ai é inválido.")
            wav_parts.append(wav)
        concat = os.path.join(temp, "concat.txt")
        with open(concat, "w", encoding="utf-8") as fh:
            for wav in wav_parts:
                fh.write(f"file '{wav}'\n")
        proc = ff.run([ff.FFMPEG, "-y", "-v", "error", "-f", "concat",
                       "-safe", "0", "-i", concat, "-ar", "48000", "-ac", "2", wav_path])
        if proc.returncode:
            raise TTSError("não foi possível unir áudios gerados por tts.ai.")
    duration = ff.probe_duration(wav_path)
    if duration <= 0:
        raise TTSError("tts.ai gerou áudio vazio.")
    if metrics is not None:
        metrics.tts("tts.ai", len(text))
    return TTSResult(wav_path, duration, "tts.ai", voice,
                     _estimate_wpm(text, duration), None)


def _synthesize_edge(text: str, wav_path: str, voice: str,
                     target_duration: float,
                     words_path: str | None = None, metrics=None) -> TTSResult:
    # Velocidade 1.25x: áudio mais rápido, vídeo acompanha automaticamente.
    words = _synth_edge(text, wav_path, voice, "+25%", words_path, metrics)
    duration = ff.probe_duration(wav_path)
    # Gate anti-corte: stream parcial não pode virar vídeo curto em silêncio.
    _check_edge_result(words, duration, text, voice)

    return TTSResult(path=wav_path, duration=duration, provider="edge-tts",
                     voice=voice, speed=_estimate_wpm(text, duration),
                     words=words)


def _synthesize_espeak(text: str, wav_path: str, voice: str,
                       speed: int, target_duration: float,
                       metrics=None) -> TTSResult:
    # Idem: sem segunda passada acelerada — ritmo natural, sem corte.
    _synth_espeak(text, wav_path, voice, speed, metrics)
    duration = ff.probe_duration(wav_path)

    return TTSResult(path=wav_path, duration=duration,
                     provider="espeak-ng", voice=voice, speed=speed)
