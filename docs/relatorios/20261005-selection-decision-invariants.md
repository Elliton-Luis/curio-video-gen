# G55 — invariantes de decisão de seleção — 2026-10-05

`SelectionDecision` podia registrar combinações contraditórias: reuse sem
justificativa, synthetic com provider real, fallback ausente e provider synth
classificado como real. O contrato runtime agora exige fallback declarado,
asset/provider em seleção concluída, motivo obrigatório para reuso, e
consistência entre status e provider. Reuso de asset sintético é classificado
como `reused`, mantendo `provider=synth` e contando seu uso corretamente.
Score precisa ser finito e ficar entre 0 e 100.

O loader de decisões persistidas adapta explicitamente decisões antigas sem
`fallback_level` para `unknown`; esse marcador não é produzido por novas
seleções e não inventa um nível histórico. Teste de metadata comprova esse
backfill. Testes focados de seleção, artifacts e métricas passaram (**36**).
Suíte completa: **915 testes em 172,91 s**. `compileall` e `git diff --check`
foram executados após a mudança.
