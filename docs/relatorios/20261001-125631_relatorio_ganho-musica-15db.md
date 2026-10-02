# Relatório — Ganho musical em −15 dB

- **Data:** 2026-10-01 12:56 (-03:00)
- **Tipo:** relatorio
- **Escopo:** aumentar ganho de música e sons de inserção mantendo faixa permitida e ducking.
- **Commit(s):** pendente
- **Origem:** pedido para elevar música de fundo e sons de insert.

## 1. O que foi pedido

Aumentar um pouco mais música e sons de inserção porque ainda estavam baixos.

## 2. O que foi feito e como

| Arquivo/área | Responsabilidade | Decisão |
|---|---|---|
| `src/curio/config.py`, `config.toml`, `config.example.toml`, `src/curio/audio/selection.py`, `src/curio/stages/render.py` | Música | Default agora `-15 dB` (limite superior já permitido). Ducking permanece ligado. |
| `src/curio/config.py`, `config.example.toml`, `src/curio/pipeline.py`, `src/curio/stages/visual.py`, `src/curio/audio/selection.py` | Inserts | Ganho sobe de `-24 dB` para `-21 dB`. SFX fica em horário sincronizado ao insert. |
| `src/curio/tui.py`, `README.md` | Configuração | Ajuda descreve ganho como audível. |
| `tests/test_audio_render.py`, `tests/test_insertions.py`, `tests/test_audio_library.py` | Regressão | Verificam defaults, volume de render e identidade de seleção com ganho distinto. |

## 3. Evidências e validações

- Doctor: `[OK] Áudio — music=auto, transitions=auto, gain=-15dB, ducking=True`.
- `python -m pytest -q -p no:cacheprovider tests/test_audio_render.py tests/test_insertions.py tests/test_audio_library.py`: **70 passed** antes de atualizar expectativa de default; após correção, repetição: **70 passed**.
- Geração real anterior com gain `-15 dB` confirmou faixa CC BY, ducking e render. Este ajuste mantém `-15 dB`; sem nova geração/API. Insert usa `-21 dB`; regressão verifica esse valor.
- Um primeiro teste focused falhou porque teste de identidade reutilizava `-18 dB`, agora igual ao novo default. Fix: usar `-20 dB` como variante. Repetição passou.

## 4. Status vs PRD §19

Não há PRD disponível. Mudança preserva faixa válida `-40..-15 dB`, mantém ducking e eleva insert sem alterar frequência/cadência de eventos.

## 5. Limitações

`-15 dB` é máximo aceito; ganho acima disso não é permitido. Mix ainda varia por masterização da faixa e nível de voz; TUI/config permitem reduzir ganho.
