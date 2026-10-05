# G56 — fonte única de queries no VisualPlan — 2026-10-05

`VisualPlan` carregava `representations` e `visual_queries` em paralelo, embora
G50 garantisse que eram idênticos. O campo duplicado foi removido do modelo
runtime e `SearchPlanner` agora lê as queries diretamente de cada
representação. A serialização de auditoria preserva a chave `scene_queries`,
calculada a partir da fonte canônica, sem alterar conteúdo ou ordem.

Testes focados de visual planning, contexto, queries, avaliação e fallback
passaram (**36**). A suíte integral passou com **915 testes em 179,50 s**.
`python -m compileall -q src tests` e `git diff --check` foram executados após
a mudança.
