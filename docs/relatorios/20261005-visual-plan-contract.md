# G50 — contrato do plano visual — 2026-10-05

`build_visual_plan` ainda re-normalizava `representations` e aceitava objetos
genéricos. Isso permitia ao consumidor esconder producers que não haviam
entregado `SemanticScene`. O planner agora exige esse contrato; para
compatibilidade explícita, um `Chapter` pode atravessar sua própria projeção
`semantic_scene()`. Não há extração ou conserto de representation nessa etapa.

`VisualPlan` valida id positivo, aliases/representations normalizados e a
igualdade ordenada entre `visual_queries` e as queries canônicas das
representations. A regra evita que o próximo stage receba duas intenções de
busca concorrentes.

Após converter as fixtures restantes de `SimpleNamespace` para
`SemanticScene`, os testes focados de contrato/planning/contexto/media/museus/
fallback passaram (**48**). A suíte completa passou com **910 testes em
176,74 s**. `compileall` e `git diff --check` foram executados após o ajuste
final.

Limite: `VisualPlan` ainda mantém `visual_queries` como espelho compatível de
`representations`; o contrato agora impede divergência. Remover o campo exige
migrar seus consumidores/serialização em fase separada.
