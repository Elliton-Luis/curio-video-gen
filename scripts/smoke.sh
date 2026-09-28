#!/usr/bin/env bash
# Teste de fumaça offline: valida a lógica sem rede, sem API e sem custo.
# Rode antes de depurar qualquer falha do pipeline: ./scripts/smoke.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src"
exec python3 - "$@" <<'EOF'
import sys

passed, failed = 0, []

def check(name, cond):
    global passed
    if cond:
        passed += 1
        print(f"[OK] {name}")
    else:
        failed.append(name)
        print(f"[FALHA] {name}")

from curio.stages import nvidia as N
from curio.stages import scenes as S
from curio.stages import subs as subs
from curio.pipeline import _relevance
from curio.media.providers import MediaAsset

# 1. Extração de JSON tolerante (a causa do erro das cenas)
check("json puro", N._extract_json('{"a": 1}') == {"a": 1})
check("json com cercas", N._extract_json('```json\n{"a": 1}\n```') == {"a": 1})
check("json com preâmbulo/epílogo",
      N._extract_json('Claro! Aqui vai:\n{"a": [1, 2]}\nEspero que ajude.') == {"a": [1, 2]})
try:
    N._extract_json('{"a": 1,')
    check("json truncado rejeitado", False)
except ValueError:
    check("json truncado rejeitado", True)
try:
    N._extract_json('só texto, sem json')
    check("sem json rejeitado", False)
except ValueError:
    check("sem json rejeitado", True)

# 2. Cenas: contagem por duração + validação literal
check("3 cenas p/ 30s", S.scenes_for_duration(30) == 3)
check("5 cenas p/ 45s", S.scenes_for_duration(45) == 5)
check("7 cenas p/ 60s", S.scenes_for_duration(60) == 7)
ch = S._local_chapters("Primeira frase. Segunda frase! Terceira?", 2)
check("divisão local cobre o roteiro",
      " ".join(c.narration for c in ch) == "Primeira frase. Segunda frase! Terceira?")
check("estimativa minima 2.5s", all(c.duration_estimate >= 2.5 for c in ch))

# 3. Legendas a partir de timestamps reais
words = [{"text": t, "start": i * 0.5, "end": i * 0.5 + 0.4}
         for i, t in enumerate("o gato comeu o rato .".split())]
cues = subs.cues_from_words(words)
check("agrupa sem offset artificial", abs(cues[0][0] - 0.0) < 1e-9)
check("blocos curtos", all(len(c[2].split()) <= 5 for c in cues))

# 4. Gate de relevância da mídia
a = MediaAsset(provider="w", asset_id="1", title="USMC-050408 marine photo")
check("título sem nada da consulta zera", _relevance("worker salt wages", a) == 0)
b = MediaAsset(provider="w", asset_id="2", title="Ancient Roman salt coin")
check("título relevante pontua", _relevance("roman salt coin", b) >= 2)

print(f"\n{passed} passaram, {len(failed)} falharam.")
sys.exit(1 if failed else 0)
EOF
