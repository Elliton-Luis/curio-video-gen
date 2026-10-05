# G54 — invariantes do resultado de avaliação — 2026-10-05

Com G53, os candidatos permanecem tipados até o evaluator, mas seus tipos de
resultado não garantiam validade local. Agora `Candidate` exige `MediaAsset`,
`SearchQuery` e identidade; `CandidateEvaluation` valida candidato, score
finito em 0–100, evidência estruturada, ordem não negativa e relação coerente
entre aceitação e motivo; `EvaluationBatch` exige tuplas tipadas, partições
corretas e identidades disjuntas.

Testes focados de contrato, avaliação, aquisição e seleção passaram (**57**).
Suíte completa: **914 testes em 190,63 s**. `compileall` e `git diff --check`
foram executados após a mudança. Não houve alteração de ranking ou threshold.
