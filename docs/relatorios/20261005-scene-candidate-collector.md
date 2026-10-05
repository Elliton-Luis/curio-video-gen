# G62 — coleta tipada de candidatos por cena

**Commit:** `a51c06d` (`refactor: isolate scene candidate collection`)

Antes de G62, `_search_scene_with_shortcircuit()` fazia a travessia de queries
e providers, deduplicava assets, aplicava gates técnicos e atualizava auditoria
antes de chamar a avaliação de candidatos. Essas responsabilidades de coleta
faziam parte do coordenador que também aplica ranking, aquisição local,
diversidade e fallback.

G62 move a coleta para `SceneCandidateCollector` em
`src/curio/stages/scene_candidate_search.py`. O collector exige `VisualPlan` e
`SearchPlan`, mantém orçamento e identidade únicos por cena entre buscas
específicas e genéricas e devolve `SceneCandidateCollection`. O contrato
confere que toda query planejada possui estado de auditoria, que candidatos e
rejeições pertencem ao plano e que a identidade não aparece duas vezes.

O novo módulo executa queries em providers na ordem já definida, usa o cache
intra-vídeo, atualiza métricas da coleta, deduplica resultados de providers e
aplica `media_rules.asset_gate_reason`. Ele não gera queries, calcula ranking,
seleciona assets ou escolhe fallback. Gates técnicos retornam
`CandidateRejection`; `candidate_evaluation.describe_technical_rejections()`
acrescenta evidência semântica apenas para auditoria, sem mudar o resultado do
gate.

`visual.py` passa a coordenar o plano e as fases: coleta específica,
avaliação, eventual coleta genérica, avaliação, download e seleção. O bloco de
travessia e deduplicação deixou o coordenador. O formato persistido da decisão,
a ordem dos providers, os budgets, o cache, os gates, métricas, scoring,
download e fallback foram preservados.

Arquivos alterados:

- `src/curio/stages/scene_candidate_search.py`
- `src/curio/stages/candidate_evaluation.py`
- `src/curio/stages/visual.py`
- `tests/test_scene_candidate_search.py`

Os cinco testes novos cobrem dedupe entre queries, snapshot independente do
estado de auditoria, queries interrompidas pelo orçamento, query não declarada
no `SearchPlan` e rejeições técnicas tipadas com evidência semântica projetada.

**Validação:** 141 testes focados passaram; suíte integral: 923 testes em
184,66 s. Após o endurecimento final do contrato, mais 16 testes focados
passaram. `python -m compileall -q src tests` e `git diff --check` passaram.
Não houve geração real nesta fase.

**Limite restante:** `visual.py` continua coordenando avaliação por fase,
download da shortlist, seleção, fallback e montagem da decisão persistida.
Cache/metadata e métricas ainda têm fontes parciais conforme o relatório
arquitetural geral.
