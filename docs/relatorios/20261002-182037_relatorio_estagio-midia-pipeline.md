# Relatório — Separar aquisição e standby de mídia

- **Data:** 2026-10-02 18:20 (UTC)
- **Tipo:** relatorio
- **Escopo:** mover busca legacy, mídia manual, labels e standby para `pipeline_media.py`
- **Commit(s):** pendente
- **Origem:** análise `20261002-131932_analise_refatoracao-codigo-morto.md`

## 1. O que foi pedido

Continuar a redução de `pipeline.py`: mídia, arquivos manuais e standby
pertencem ao estágio de mídia; pipeline deve coordenar.

## 2. O que foi feito

| Arquivo | Responsabilidade |
|---|---|
| `pipeline_media.py` | Busca de um asset, relevância legacy, reuse, pasta/README manual, ffprobe de uploads, labels e contagem de assets. Define `MediaStandby`. |
| `pipeline.py` | Seleciona implementação single/multi, agrega resultado, registra direitos e decide standby. |
| `cli.py`, `queue.py` | Importam `MediaStandby` de seu dono; sem reexport/wrapper antigo. |
| testes standby | Importam utilitários do módulo de mídia. |

Gate legacy mantém as decisões antigas de seleção: score lexical >0 e
bloqueio de direitos; não recebe o gate multi-imagem (mudaria seleção).

## 3. Evidências

- `python3 -m pytest tests/test_media_standby.py tests/test_standby_flow.py tests/test_media_waterfall.py tests/test_pipeline_integration.py -q` — 29 passed.
- Imports de `curio.pipeline`, `curio.pipeline_media`, `curio.cli` e `curio.queue` — OK.
- `pipeline.py`: 1.769 para 1.543 linhas nesta subetapa; media helpers residem em arquivo dedicado.

## 4. Status vs PRD §19

Sem mudança em formato de saída, seleção manual ou fallback.

## 5. Limitações

`_run_pipeline` segue como orquestrador principal e ainda coordena etapas e
metadata. As funções coesas de pesquisa, mídia, áudio, render e timeline já
saíram; restante exige contrato de estado explícito antes de mover.
