# G87 — ownership da provenance de seleção

**Commit:** `412a8b1 refactor: centralize selection provenance`  
**Problema:** `visual.py` inferia localmente se a busca havia esgotado, qual
motivo explicar e que nível de fallback atribuir à seleção. Isso fazia o
coordenador reinterpretar `SearchPlan`, auditoria por query e asset escolhido.
**Estado:** implementado e validado.

## Contrato novo

`SelectionProvenance` é um snapshot imutável com `search_exhausted`,
`search_exhaustion_reason` e `fallback_level`. `describe_selection_provenance()`
é dono dessa classificação em `media_selection.py` e recebe:

- `SelectedAsset` tipados;
- `VisualPlan` e `SearchPlan` da mesma cena;
- estados `SearchQueryAudit` para exatamente as queries do plano.

Planos divergentes ou auditoria incompleta/incompatível falham no boundary. A
função classifica busca nova, reuso, sintético após busca completa/incompleta,
query não executada e provider indisponível. `visual.py` usa a provenance
retornada para construir `VisualDecision`; o schema persistido continua igual.

## Responsabilidade antes/depois

Antes, o coordenador inspecionava campos de `picked`, comparava a query com as
representações e percorria os estados da auditoria para compor três campos da
decisão. Agora `media_selection.py` detém a regra de classificação e valida a
coerência dos inputs. `visual.py` ainda coordena busca, avaliação, aquisição e
montagem de outros campos da auditoria; G87 não extrai o coordenador inteiro.

## Testes e validação

Regressões cobrem asset real específico, fallback sintético com provider em
timeout, reuso após busca completa, ausência com query não executada, plano de
outra cena e auditoria que não corresponde ao SearchPlan. Testes direcionados
de seleção, diretor, auditoria e waterfall: **98 passaram**. Suíte completa:
**990 passaram em 194,98 s**. `compileall` e `git diff --check` passaram.

Nenhuma busca real foi necessária: a mudança transferiu a classificação para
um owner, sem alterar queries, providers, gates, seleção, fallback executado ou
serialização. Os testes de pipeline verificam a projeção final existente.

## Limites restantes

`visual.py` continua uma orquestração substancial. A próxima extração deve
reduzir uma decisão efetiva da função, manter contratos tipados e demonstrar
transições equivalentes no output e na auditoria; não basta mover blocos de
código sem alterar ownership.
