# Relatório — Separar geração de áudio e legendas do pipeline

- **Data:** 2026-10-02 18:08 (UTC)
- **Tipo:** relatorio
- **Escopo:** mover TTS, alinhamento temporal e geração de legendas para estágio coeso
- **Commit(s):** pendente
- **Origem:** `docs/relatorios/20261002-170000_relatorio_separacao-etapas-render.md`

## 1. O que foi pedido

Reduzir `_run_pipeline`: pipeline deve orquestrar; execução detalhada de
áudio e legenda deve ficar em estágio próprio.

## 2. O que foi feito

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `pipeline_audio.py` | TTS, cache, WordBoundary/WPM, costura temporal e legendas | `run_audio_stages` recebe dependências necessárias e devolve `AudioStageResult`; sem acesso a todo pipeline. |
| `pipeline.py` | Orquestração | Chama estágio único e usa seu resultado para timeline visual/render. Remove implementação detalhada do fluxo AI. |

Sem mudança no fluxo humano/finalize. Cache, autocura de áudio parcial,
fallback proporcional, alinhamento e mudança de legenda que invalida MP4
permanecem iguais.

## 3. Evidências

- `python3 -m pytest tests/test_pipeline_integration.py tests/test_audio_render.py tests/test_tts_coverage.py -q` — 26 passed.
- `python3 -m pytest tests/ -q` — **728 passed**.
- `_run_pipeline`: 774 para ~694 linhas; bloco TTS/alinhamento/legendas agora vive em módulo próprio.

## 4. Status vs PRD §19

Sem mudança de produto, dependência ou artefato.

## 5. Limitações

`_run_pipeline` ainda orquestra cache e decisões de vários estágios; fila/TUI
de projetos e transporte LLM também permanecem grandes. Extrações seguintes
devem respeitar fronteiras de estado e preservar cache.
