# F4 — duração explícita do estágio de timeline visual

**Commit:** `11ac1f3 refactor: include visual timeline in stage timings`  
**Estado:** concluída e validada.

## Causa

`pipeline_timeline.build_visual_timeline()` realiza validação e alinhamento de
cenas, converte a seleção para input de métricas, constrói e persiste a
timeline de inserções e atualiza métricas de assets/beats. Porém,
`VisualTimelineResult` não carregava duração, e `pipeline.py` deixava essa
etapa fora de `stage_times`. Assim, as métricas do pipeline não permitiam
atribuir seu custo de forma separada.

## Mudança

`VisualTimelineResult` agora inclui `elapsed`, validado como número finito e
não negativo. O estágio mede seu tempo do início da validação até a projeção
final das métricas, incluindo quando os overlays estão desativados. O
coordenador registra esse valor como `stage_times["visual_timeline"]`.

É uma nova chave aditiva em `stage_times`; nenhuma chave existente ou unidade
foi alterada. Isso melhora a observabilidade, mas ainda não constitui um profile
comparativo por suboperação nem uma otimização de performance.

## Arquivos

- `src/curio/pipeline_timeline.py`: adiciona e valida a duração no resultado.
- `src/curio/pipeline.py`: agrega a duração sob `visual_timeline`.
- `tests/test_pipeline_timeline.py`: duração determinística e rejeição de
  resultado inválido.

## Validação

Testes focados de timeline, integração do pipeline e metadata: **16 passaram**.
Teste do contrato de timeline repetido isoladamente: **4 passaram**.
Suíte completa: **967 passaram em 191,41 s**. `python -m compileall -q src
tests` e `git diff --check` passaram.

## Limites restantes de métricas

F4 só cobre o tempo do estágio da timeline visual. Continuam pendentes os
timers de lifecycle que ainda não são produzidos pelos resultados dos estágios,
profile comparativo para pesquisa/acquisition/render e reconciliação mais
ampla de métricas de seleção com o que entrou efetivamente no render. Nenhuma
execução real foi feita nesta fase.
