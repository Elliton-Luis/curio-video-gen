# Relatório — Prompts editoriais fora do transporte LLM

- **Data:** 2026-10-02 15:35 (local)
- **Tipo:** relatorio
- **Escopo:** mover prompts de roteiro e título de `nvidia.py` para `prompts.py`
- **Commit(s):** pendente
- **Origem:** `docs/analises/20261002-131932_analise_refatoracao-codigo-morto.md`

## 1. O que foi pedido

Continuar refatoração estrutural. Tirar prompts editoriais do módulo que
faz transporte, credenciais e retry LLM. Preservar conteúdo e comportamento.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `stages/prompts.py` | Prompts de roteiro e título PT/EN | Mantém texto e placeholders existentes. Não faz I/O. |
| `stages/nvidia.py` | Transporte LLM e chamada de roteiro | Importa prompts de roteiro; não contém mais strings editoriais. |
| `stages/script.py` | Orquestração da geração de título | Importa prompt de título diretamente do módulo editorial. |
| `tests/test_*.py` | Contrato do conteúdo do prompt | Testes leem módulo dono, não cliente HTTP. |

Na implementação posterior `3c93b7f`, prompts de cena e entidade também
moveram para este módulo. Schema e lógica de consumo permanecem nos estágios
`scenes.py` e `entity.py`.

## 3. Evidências

- `python3 -m pytest tests/test_script_hook.py tests/test_active_word.py tests/test_shorts60.py tests/test_research.py tests/test_entity_relevance.py tests/test_visual_model.py -q` — **92 passed**.
- `python3 -m pytest tests/ -q` — **720 passed**.
- Busca estática confirma `SCRIPT_SYSTEM_PROMPT` e `TITLE_SYSTEM_PROMPT` definidos em `stages/prompts.py`.

## 4. Status vs PRD §19

Sem mudança de produto nem dependência. Transporte LLM mantém mesmo contrato.

## 5. Limitações

Subetapa da Etapa 3. Ainda faltam extrações graduais de `_run_pipeline`,
`visual.py`, `tui.py` e decomposição do cliente `nvidia.py`. Ver análise
de origem e relatório de continuação ao fim da refatoração.
