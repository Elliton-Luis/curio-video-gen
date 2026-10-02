# Relatório — Separar terminal e navegação da TUI

- **Data:** 2026-10-02 16:30 (local)
- **Tipo:** relatorio
- **Escopo:** mover entrada, teclado, menu e browser de caminho para módulo terminal
- **Commit(s):** `4b106d9 refactor: separate terminal mechanics from TUI flows`
- **Origem:** `docs/analises/20261002-131932_analise_refatoracao-codigo-morto.md`

## 1. O que foi pedido

Continuar quebra gradual de módulos grandes. Separar implementação de
terminal dos fluxos de negócio da TUI, sem alterar comportamento.

## 2. O que foi feito

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `curio/tui_terminal.py` | stdin, cores, teclado, menu, quebra visual e browser de caminho | Stdlib only; `TUIExit` representa EOF/Ctrl+C limpo. |
| `curio/tui.py` | Fluxos de vídeo, projeto, fila, configuração e limpeza | Importa primitives do terminal; mantém confirmação destrutiva e política dos fluxos. |
| `tests/test_tui_genre.py` | Navegação por teclado e layout | Testa renderer e teclado no módulo que os possui. |

## 3. Evidências

- `python3 -m pytest tests/test_tui_genre.py tests/test_tui_script_input.py -q` — 7 passed.
- `python3 -m pytest tests/ -q` — **721 passed**.

## 4. Status vs PRD §19

Sem mudança de fluxo de produto ou dependência. TUI continua stdlib only.

## 5. Limitações

TUI ainda contém fluxos de negócio e permanece grande. Próxima extração
deve mover coesões reais (projetos, filas, configuração), não criar
wrappers. `_run_pipeline`, `visual.py` e client LLM também aguardam quebra.
