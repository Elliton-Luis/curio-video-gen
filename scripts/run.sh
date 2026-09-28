#!/usr/bin/env bash
# Atalho de execução sem instalação: ./scripts/run.sh generate "ideia..."
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m curio "$@"
