# Relatório — Separar planejamento visual e render do pipeline

- **Data:** 2026-10-02 17:00 (local)
- **Tipo:** relatorio
- **Escopo:** mover timeline/SFX, preparação de segmentos e estágio de pesquisa para módulos com dono claro
- **Commit(s):** pendente
- **Origem:** análise `20261002-131932_analise_refatoracao-codigo-morto.md`

## 1. O que foi pedido

Continuar refatoração incremental. `visual.py` não deve misturar busca com
timeline; `pipeline.py` deve delegar detalhes de estágios.

## 2. O que foi feito

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `stages/visual_timeline.py` | Inserções, ordem base/inserção, geometria, beats, SFX e retiming | Recebe assets selecionados; não busca nem baixa mídia. |
| `stages/visual.py` | Busca, ranking, aquisição e composição da timeline | Mantém `build_visual_timeline` como integração entre mídia e plano. Remove funções de timeline puras. |
| `pipeline_render.py` | Cache/geração de segmentos silenciosos, concatenação e política de transição | Recebe dados prontos; infraestrutura FFmpeg permanece em `stages/render.py`. |
| `pipeline_research.py` | Orquestra pesquisa, registro de fontes e persistência `research.json` | Recebe callbacks da pipeline; devolve `ResearchStageResult`. |
| `pipeline.py` | Orquestra fases e conserva o contrato público | Pesquisa delegada para `pipeline_research`; montagem silenciosa para `pipeline_render`. |
| `tui_terminal.py` | Teclado, menu, cores, entrada e navegador de caminho | TUI de fluxos consome primitives; stdlib only. |

Funções movidas foram removidas do módulo anterior; consumidores e testes
agora importam o dono correto. Sem wrapper antigo coexistente.

## 3. Evidências

- `python3 -m pytest tests/test_insertions.py tests/test_visual_asset_usage.py tests/test_visual_context.py tests/test_review_flow.py -q` — 67 passed após extração visual.
- `python3 -m pytest tests/test_pipeline_integration.py tests/test_tui_script_input.py tests/test_review_flow.py -q` — 25 passed após extração de pesquisa/render.
- `python3 -m pytest tests/ -q` — **727 passed**.
- `visual.py`: 1.646 para 1.235 linhas; `visual_timeline.py`: 268 linhas; `pipeline_render.py`: 149 linhas; `pipeline_research.py`: 103 linhas.

## 4. Status vs PRD §19

Nenhuma etapa de produto mudou. Áudio e vídeo preservam caminho e metadata.

## 5. Limitações e próxima etapa

Naquele commit, `_run_pipeline` ainda tinha ~774 linhas de orquestração.
Relatório posterior `20261002-180859_relatorio_estagio-audio-pipeline.md`
extraiu TTS, alinhamento e legendas. Fila/TUI de
fluxos ainda vive em `tui.py`; transporte/provider chain ainda vive em
`nvidia.py`. Esses módulos exigem extração de fronteira com estado e
testes, não movimento mecânico. Etapa 5 de performance segue em relatório
separado.
