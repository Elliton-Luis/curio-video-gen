# F8 — fonte única da duração total live

**Commit:** `b0b272e fix: align live metric duration with pipeline`  
**Problema:** metadata registrava `processing_time_seconds` medido pelo
pipeline, enquanto `metrics.json.time.total_seconds` recalculava o tempo pelo
relógio próprio de `RunMetrics`. Os números podiam divergir apesar de
representarem o mesmo total da execução.  
**Estado:** implementado e validado.

## Contrato

Para uma execução live com `processing_time_seconds` numérico, finito e não
negativo, esse campo é a fonte canônica de `time.total_seconds`. O collector
continua usando seu relógio como fallback para chamadas diretas ou metadados
legados sem duração válida. Zero explícito é aceito como valor observado; zero
não é introduzido para representar ausência.

F7 permanece responsável pelo backfill: quando a duração total não existe nos
metadados antigos, o resultado continua `null`; a duração temporária medida
durante a execução do backfill não é promovida a duração histórica.

## Testes e validação

Testes novos fixam a duração pipeline em 0 e 12,5 segundos e verificam o
fallback do collector quando o campo está ausente. Focados em métricas,
metadata e backfill: **24 passaram**. Suíte completa: **993 passaram em
186,00 s**. Após ajuste de whitespace, módulo de métricas: **11 passaram**;
`compileall` e `git diff --check` passaram.

## Limites

`processing_time_seconds` é a duração da execução do pipeline, medida antes da
gravação final do próprio relatório de métricas. O pequeno custo posterior de
serialização não é contado. Essa definição é agora consistente entre metadata
e a métrica publicada; não substitui profiling por suboperação da fase H.
