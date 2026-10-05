# G90 — rejeições técnicas tipadas até a auditoria

**Data:** 2026-10-05  
**Commit:** `f0a9622 refactor: preserve typed technical rejections`  
**Estado:** concluída nesta fronteira; resultados de aquisição ainda são projetados em rows no coordenador.

## Problema

`SceneCandidateCollection` já guardava `CandidateRejection`, mas
`describe_technical_rejections()` os convertia imediatamente em dicts e mesclava
proveniência semântica. `visual.py` lia esses rows para métricas, remoção de
duplicatas e auditoria, e a seleção persistida precisava recebê-los novamente
como mappings.

## Mudança

`CandidateRejection` agora carrega evidência semântica congelada e valida seus
campos. `describe_technical_rejections()` enriquece a rejeição tipada sem
serializar. `visual.py` mantém as rejeições técnicas tipadas durante a busca e
projeta-as quando compõe a seleção/auditoria final. `visual_audit.py` deriva
linhas de candidato e totais por query a partir do valor tipado; o formato JSON
persistido continua igual.

Rejeições por score já são mantidas como `CandidateEvaluation` após G89.
Rejeições pós-download ainda são rows via `CandidateAcquisitionOutcome` nesta
fronteira; essa é uma migração possível seguinte, não parte de G90. Métricas e
gates semânticos/técnicos foram preservados.

## Arquivos

- `src/curio/stages/media_contracts.py` — evidência congelada e projeção JSON em `CandidateRejection`.
- `src/curio/stages/candidate_evaluation.py` — enriquece rejeições sem convertê-las para dict.
- `src/curio/stages/visual.py` — conserva rejeições técnicas tipadas durante o fluxo e projeta no limite de saída.
- `src/curio/stages/visual_audit.py` — auditoria consome rejeições tipadas e preserva saída existente.
- `tests/test_scene_candidate_search.py`, `tests/test_visual_audit.py` — regressões para o contrato tipado e sua projeção.

## Validação

- Focados (`test_scene_candidate_search`, `test_visual_audit`, `test_visual_director`, `test_black_hole`): **65 passaram**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- `pytest -q`: **996 passaram em 179,78 s**.

## Limites

G90 não altera busca, score, seleção ou fallback. Rejeições pós-download permanecem convertidas por `to_rejection_row()` antes da projeção final, e `visual.py` continua coordenando tentativas/fallbacks e efeitos de métricas. Não houve geração real porque a mudança afeta ownership da evidência de auditoria, não comportamento editorial.
