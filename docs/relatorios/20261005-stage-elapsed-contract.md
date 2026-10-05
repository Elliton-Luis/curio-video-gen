# F5 — contrato comum para duração de estágios

**Commit:** `e534ee3 refactor: validate stage elapsed values consistently`  
**Estado:** concluída e validada.

## Causa

Os resultados dos estágios validavam durações de modo inconsistente: pesquisa,
roteiro e cenas aceitavam qualquer valor; render chamava `math.isfinite` sem
validar primeiro o tipo; áudio e timeline repetiam parcialmente as próprias
regras. Booleanos podiam ser confundidos com inteiros, e `NaN`/infinito podiam
chegar ao metadata por contratos sem validação.

## Mudança

`stage_timing.validate_stage_elapsed(value, owner)` centraliza a definição:
duração em segundos deve ser numérica, finita e não negativa; booleanos não são
números válidos para esse contrato. Os resultados de research, script, cenas,
render e timeline usam a função. O resultado de research agora também é frozen;
seu payload `ResearchResult` segue mutável no owner da pesquisa. `AudioStageResult`
aplica a mesma definição aos valores nomeados de `stage_times` e preserva sua
projeção como mapping para o pipeline.

Tempos válidos permanecem em segundos e sem mudança de valor observável; nenhum
JSON ou nome de estágio foi alterado. Entradas inválidas falham na construção
do resultado, antes de serem propagadas para metadata.

## Arquivos

- `src/curio/stage_timing.py`: regra comum para duração de estágio.
- `src/curio/pipeline_research.py`, `pipeline_script.py`, `pipeline_scenes.py`,
  `pipeline_audio.py`, `pipeline_render.py` e `pipeline_timeline.py`: adotam a
  validação compartilhada.
- `tests/test_stage_timing.py` e `tests/test_pipeline_render_contracts.py`:
  regressões para tipos e valores inválidos.

## Validação

Testes focados de resultados e contratos de research/script/scenes/audio,
render e timeline: **48 passaram em 0,24 s**. `python -m compileall -q src
tests` e `git diff --check` passaram. Suíte completa: **977 passaram em
191,23 s**. Não houve execução real; F5 mudou somente invariantes de duração.

## Limites restantes

O contrato não cria os timers ausentes, não instrumenta requests HTTP por
tentativa e não fornece profile por suboperação. A etapa de timeline visual já
recebe duração em F4; lifecycle timers e reconciliação seleção-render seguem
pendentes.
