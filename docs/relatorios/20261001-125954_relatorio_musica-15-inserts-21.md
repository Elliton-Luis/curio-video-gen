# Relatório — Música −15 dB e inserts −21 dB

- **Data:** 2026-10-01 12:59 (-03:00)
- **Tipo:** relatorio
- **Escopo:** elevar cama musical e sons de inserção dentro das faixas de áudio existentes.
- **Commit(s):** `588bd93` (`fix: raise default music and insert levels`)
- **Origem:** pedido para tornar música de fundo e sons de inserts mais audíveis.

## 1. O que foi pedido

Elevar música de fundo e sons de inserção porque ainda estavam baixos.

## 2. O que foi feito e como

| Arquivo/área | Responsabilidade | Alteração |
|---|---|---|
| `src/curio/config.py`, `config.toml`, `config.example.toml`, `src/curio/audio/selection.py`, `src/curio/stages/render.py` | Música | Default −18 → −15 dB, máximo já permitido. Ducking e fades intactos. |
| `src/curio/config.py`, `config.example.toml`, `src/curio/pipeline.py`, `src/curio/stages/visual.py`, `src/curio/audio/selection.py` | Inserts | Ganho −24 → −21 dB. SFX mantém instante e duração. |
| `src/curio/tui.py`, `README.md` | Configuração visível | Ajuda descreve ganhos como audíveis. |
| `tests/test_audio_render.py`, `tests/test_insertions.py`, `tests/test_audio_library.py` | Regressão | Verificam ganho final, ganho dos inserts, default e assinatura do mix. |

## 3. Evidências e validações

- `./scripts/run.sh doctor`: música `auto`, transições `auto`, ganho `-15dB`, ducking ligado.
- Geração real anterior usou faixa CC BY em `-15 dB`, transições `auto` e render `av1_vaapi`.
- `python -m pytest -q -p no:cacheprovider tests/test_audio_render.py tests/test_insertions.py tests/test_audio_library.py`: **70 passed**.
- `git diff --check`: passou.

## 4. Status vs PRD §19

Não há PRD no repositório. Faixas continuam `music=-40..-15 dB` e `insert=-45..-12 dB`; ducking continua ativo.

## 5. Limitações

Ganho −15 dB já atinge limite máximo configurado. Ajustes maiores exigem mudança explícita de faixa e avaliação contra clipping/voz. Não alterei compressor, limiter ou SFX sintéticos.
