# G53 — fronteira de avaliação de candidatos — 2026-10-05

A aquisição já construía `Candidate(asset, SearchQuery, identity)`, mas logo
convertia o valor para dict. `candidate_evaluation` consumia esses dicts e
reconstruía candidatos ao produzir o resultado tipado. Isso fazia a estrutura
canônica desaparecer exatamente na transição para scoring.

Agora aquisição mantém candidatos tipados; `evaluate_specific` e
`evaluate_generic` exigem `Candidate[]`. O adaptador de scoring projeta os
campos necessários para os métodos lexicais atuais e mantém uma associação por
identidade única. `CandidateEvaluation` referencia o mesmo candidato que saiu
da aquisição. A saída dict continua somente no adaptador de seleção legado; a
conversão reversa não usada foi removida.

Testes focados de avaliação, contratos, aquisição e seleção passaram (**64**).
Suíte completa: **913 testes em 192,30 s**. `compileall` e `git diff --check`
foram executados após a mudança.
