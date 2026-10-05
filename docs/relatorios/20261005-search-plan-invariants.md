# G52 — invariantes do plano de busca — 2026-10-05

`SearchQuery` e `SearchPlan` cruzam o limite entre planejamento e aquisição,
mas não validavam campos nem estrutura. Queries vazias/sem provenance ou
duplicadas podiam ser encaminhadas ao provider sem acusar o produtor.

Agora a query exige texto, origem, variante, nível inteiro positivo e flag
genérica booleana; o plano exige id positivo, tupla de `SearchQuery` e textos
únicos sem distinção de maiúsculas. Um plano sem queries continua válido para
cenas resolvidas sem pesquisa. Nenhum dado é traduzido, completado ou reparado.

Testes focados de contrato, avaliação, busca e contexto passaram (**33**).
Suíte integral: **912 testes em 178,62 s**. `compileall` e `git diff --check`
foram executados após a edição.
