# G89 — avaliações tipadas até a auditoria visual

**Data:** 2026-10-05  
**Commit:** `087c96e refactor: keep candidate evaluations typed through audit`  
**Estado:** concluída nesta fronteira; rejeições técnicas em rows ainda são dívida conhecida.

## Causa e mudança

`candidate_evaluation.py` já retornava `EvaluationBatch` com `CandidateEvaluation` imutável. Mesmo assim, `visual.py` chamava `to_selection_entry()` para converter aceitos/rejeitados em rows, armazenava esses dicts até o fim da cena e `visual_audit.py` os reinterpretava para reconstruir score, evidência, query, candidate e asset selecionado.

G89 mantém as avaliações como `CandidateEvaluation` até `candidate_audit_rows()`, que agora exige tupla tipada e `SelectedAsset` tipado. `visual.py` usa o próprio contrato para gerar rejeições de score e métricas. `CandidateEvaluation.evidence_dict()` faz o thaw recursivo de evidência congelada no ponto em que ela vira projeção auditável; `to_selection_entry()` compartilha essa projeção.

O schema JSON e as decisões editoriais permanecem iguais. As rows de rejeições técnicas/pós-download ainda são consumidas como dicts, explicitamente fora da mudança desta fase.

## Falha encontrada e correção

A primeira suíte completa encontrou **34 falhas** de integração: a projeção direta de evidência congelada carregava `MappingProxyType` aninhado até `VisualDecision`, cujo adapter histórico usa `deepcopy` e não consegue serializá-lo. A projeção recursiva `evidence_dict()` resolveu a incompatibilidade. Os testes focados foram repetidos após a correção.

## Arquivos

- `src/curio/stages/media_contracts.py` — adiciona projeção explícita da evidência imutável como dict JSON.
- `src/curio/stages/visual.py` — preserva avaliações tipadas no fluxo e constrói rejeições de score a partir do contrato.
- `src/curio/stages/visual_audit.py` — aceita `CandidateEvaluation`/`SelectedAsset` e elimina leitura de dicts de avaliação.
- `tests/test_visual_audit.py` — migra as regressões para contratos reais e rejeita linhas de avaliação sem tipo.

## Validação

- `pytest -q tests/test_black_hole.py tests/test_visual_director.py tests/test_visual_query_concepts.py tests/test_visual_audit.py tests/test_candidate_evaluation.py tests/test_media_contracts.py`: **71 passaram**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- `pytest -q`: **995 passaram em 178,95 s**.

## Limites

G89 remove uma ida e volta de serialização para as avaliações semânticas. `visual.py` ainda coordena as tiers e efeitos de métricas; rows de rejeições técnicas e pós-download continuam na auditoria. Não foi feita geração real, pois a fase não muda busca, ranking nem seleção. Ver também o [relatório completo](20261005-relatorio-completo-estado-do-trabalho.md).
