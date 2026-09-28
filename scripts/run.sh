#!/usr/bin/env bash
# Atalho de execução sem instalação: ./scripts/run.sh generate "ideia..."
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
# Carrega .env local (gitignored) sem sobrescrever o que já está exportado:
# variável de ambiente explícita sempre vence o .env.
if [ -f "$ROOT/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    case "$key" in ''|*[!A-Za-z0-9_]* ) continue ;; esac
    if [ -z "${!key+x}" ]; then
      export "$key=${line#*=}"
    fi
  done < "$ROOT/.env"
fi
exec python3 -m curio "$@"
