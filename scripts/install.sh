#!/usr/bin/env bash
# Instalação de dependências do curio (Linux, custo zero).
set -euo pipefail

echo "=== curio — install ==="

need() { command -v "$1" >/dev/null 2>&1 || { echo "FALTA: $1 ($2)"; MISSING=1; }; }

MISSING=0
need python3 "python3.11+"
need ffmpeg "renderização (PRD §11)"
need ffprobe "vem com o ffmpeg"
need espeak-ng "TTS local pt-br (PRD §8)"

if [ "${MISSING:-0}" -ne 0 ]; then
  echo ""
  echo "Instale o que falta. Exemplos:"
  echo "  Fedora/RHEL: sudo dnf install -y ffmpeg espeak-ng"
  echo "  Ubuntu/Debian: sudo apt install -y ffmpeg espeak-ng"
  echo "  Arch: sudo pacman -S --needed ffmpeg espeak-ng"
  exit 1
fi

# VA-API é opcional: sem GPU o pipeline usa libx264 na CPU.
if [ -e /dev/dri/renderD128 ]; then
  echo "VA-API: dispositivo encontrado ($(ls /dev/dri/renderD* | tr '\n' ' '))"
else
  echo "VA-API: não encontrado — render vai usar CPU (libx264). OK para o MVP."
fi

python3 -m pip install --user -e . 2>/dev/null || {
  echo "pip install -e . falhou (sem rede?); sem problema:"
  echo "use ./scripts/run.sh, que roda com PYTHONPATH=src sem instalar."
  exit 0
}

echo ""
echo "OK. Teste com: video-gen doctor"
