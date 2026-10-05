# G51 — dono compartilhado da tokenização — 2026-10-05

`search_planning` e `visual_context` usavam `scoring._tokens`; a função privada
do scoring era apenas um alias de `textnorm.tokens`. Assim, dois produtores de
decisões anteriores dependiam do avaliador de candidatos, embora a regra
compartilhada já tivesse um owner neutro.

Os dois consumidores agora usam `textnorm.tokens` diretamente. A pontuação
continua com seu alias local para os cálculos internos; não houve mudança de
normalização, ranking, queries ou conteúdo editorial. A inspeção de imports
confirma que esses dois módulos não dependem mais de `scoring`.

Testes focados de query planning, contexto, tópicos e busca visual passaram
(**44**); suíte completa: **910 testes em 185,81 s**. `compileall` e
`git diff --check` passaram após esta alteração.
