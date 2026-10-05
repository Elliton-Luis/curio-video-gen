# G85 — auditoria visual deriva provenance do VisualPlan

**Commit:** `8ae6616 refactor: project visual audit from canonical plan`  
**Estado:** concluída e validada; formato de auditoria persistido preservado.

## Causa

Embora `VisualPlan` já fosse a fonte validada das representações, níveis,
classes e aliases de uma cena, `visual.py` reconstruía mapas desses valores
diretamente de `ch.representations` e `ch.video_context`. Isso repetia
normalização no coordenador e permitia que a auditoria consultasse uma segunda
forma dos mesmos fatos. A projeção de fallback também usava esse mapa local.

## Mudança

`search_query_audit_rows()` e `candidate_audit_rows()` agora recebem
`VisualPlan` como fonte única de provenance. As linhas derivam representações,
tipos, níveis e aliases dos valores canônicos do plano. A auditoria de queries
valida que `SearchPlan.scene_id` e `VisualPlan.scene_id` coincidam. `visual.py`
deixou de ler `video_context` e representations para montar os mapas paralelos;
usa `visual_plan.topic`, aliases e representations.

Os dois helpers internos agora exigem `VisualPlan`; assinaturas que aceitavam
mapas independentes foram migradas nos consumidores e testes. Nenhum schema de
projeto ou campo JSON mudou. Não foi criado contrato novo: o contrato existente
passa a ser consumido na fronteira de projeção.

## Arquivos

- `src/curio/stages/visual_audit.py`: audit rows consomem VisualPlan e validam
  vínculo entre planos.
- `src/curio/stages/visual.py`: remove derivação redundante de níveis, tipos e
  aliases.
- `tests/test_visual_audit.py`: migra fixtures para VisualPlan e cobre plano de
  cena incompatível.

## Validação

Testes focados de auditoria, coleta de candidatos, diretor visual e contratos:
**66 passaram em 0,31 s**. Suíte completa: **966 passaram em 197,08 s**.
`python -m compileall -q src tests` e `git diff --check` passaram. Não houve
geração real: G85 alterou apenas a origem de dados da auditoria e preservou o
schema.

## Limite restante

O payload final de `VisualDecision` em `visual.py` ainda combina provenance do
plano com alguns campos lidos diretamente de `SemanticScene`, como intenção,
entidades e representações descartadas. Esse restante exige inventário de
ownership e equivalência de payload antes de mover; G85 não o altera.
