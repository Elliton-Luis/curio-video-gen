#!/usr/bin/env bash
# Atalho de execução sem instalação: ./scripts/run.sh generate "ideia..."
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
# Carrega segredos locais (.env gitignored) se existir.
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
exec python3 -m curio "$@"
