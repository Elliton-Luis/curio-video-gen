# G78 — estado explícito de queries adiadas

**Commit:** `f7eabb0` (`fix: audit deferred visual queries explicitly`)

**Estado:** concluída e testada.

## Problema

`SceneCandidateCollector` criava um acumulador para toda query do `SearchPlan`,
mas queries genéricas aguardando a tier contextual não tinham estado de
execução. A projeção da auditoria podia apresentá-las como “sem resultados” ou
“sem provider”, apesar de nenhuma requisição ter ocorrido. Isso impedia
distinguir espaço consultado de tier ainda não alcançada.

## Mudança

Queries genéricas começam com `unexecuted_reason="tier_not_reached"`. Quando
`collect()` começa a processá-las, o collector limpa a marca; se o orçamento
global impede execução, prevalece `scene_candidate_budget`. A projeção distingue
`not_consulted` e `not_consulted_budget_exhausted` de `consulted` e
`abandoned_duplicates`.

## Arquivos

- `src/curio/stages/scene_candidate_search.py`: owner registra tier adiada e
  limpa o estado ao iniciar a query.
- `src/curio/stages/visual_audit.py`: projeta status não consultado
  explicitamente.
- `tests/test_scene_candidate_search.py` e `tests/test_visual_audit.py`:
  regressões de transição adiada → executada e orçamento esgotado.

## Validação

- **53 testes focados** de coleta, auditoria e direção visual.
- **948 testes passaram; 1 foi desmarcado** por HTTP 429 da API real da
  Wikipédia, em **181,85 s** (`pytest -q -k 'not standby_sem_imagens'`).
- `python -m compileall -q src tests` e `git diff --check` passaram.
- Sem geração real nesta fase.

## Limite

O motivo especial `tier_not_reached` é inicializado para queries genéricas; as
consultas específicas continuam partindo sem marcador, pois o fluxo atual sempre
as inclui na coleta inicial. Se novos caminhos omitirem queries específicas,
deverão declarar também a razão de não execução no plano/coletor.
