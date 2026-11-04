#!/usr/bin/env bash
# Instalação de dependências do curio (Linux, custo zero).
set -euo pipefail

echo "=== curio — install ==="

need() { command -v "$1" >/dev/null 2>&1 || { echo "FALTA: $1 ($2)"; MISSING=1; }; }

MISSING=0
need python3 "python3.11+"
need ffmpeg "renderização (PRD §11)"
need ffprobe "vem com o ffmpeg"

if [ "${MISSING:-0}" -ne 0 ]; then
  echo ""
  echo "Instale o que falta. Exemplos:"
  echo "  Fedora/RHEL: sudo dnf install -y ffmpeg"
  echo "  Ubuntu/Debian: sudo apt install -y ffmpeg"
  echo "  Arch: sudo pacman -S --needed ffmpeg"
  exit 1
fi

# VA-API é opcional: sem GPU o pipeline usa libx264 na CPU.
if [ -e /dev/dri/renderD128 ]; then
  echo "VA-API: dispositivo encontrado ($(ls /dev/dri/renderD* | tr '\n' ' '))"
else
  echo "VA-API: não encontrado — render vai usar CPU (libx264). OK para o MVP."
fi

python3 -c "import edge_tts" 2>/dev/null && echo "edge-tts: pacote Python OK (voz neural)" || {
  echo "edge-tts: instalando pacote Python (voz neural gratuita, sem login)..."
  python3 -m pip install --user edge-tts || echo "edge-tts: falhou (sem rede?) — a narração tentará Piper remoto; produção falha se nenhuma voz neural responder."
}

if command -v espeak-ng >/dev/null 2>&1; then
  echo "espeak-ng: disponível somente para pré-avaliação"
else
  echo "espeak-ng: opcional, ausente (TTS de produção usa vozes neurais)"
fi

python3 -c "import faster_whisper" 2>/dev/null && echo "faster-whisper: OK (transcrição local)" || {
  echo "faster-whisper: instalando (transcrição local p/ narração humana)..."
  python3 -m pip install --user faster-whisper || echo "faster-whisper: falhou (sem rede?) — finalize indisponível."
}

python3 -m pip install --user -e . 2>/dev/null || {
  echo "pip install -e . falhou (sem rede?); sem problema:"
  echo "use ./scripts/run.sh, que roda com PYTHONPATH=src sem instalar."
  exit 0
}

echo ""
echo "OK. Teste com: video-gen doctor"
