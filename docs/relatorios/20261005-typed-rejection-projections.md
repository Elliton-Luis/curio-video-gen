# G92 — projeções de rejeição derivadas de outcomes tipados

**Data:** 2026-10-05  
**Commit:** `6191b8b refactor: project media rejections from typed outcomes`  
**Estado:** concluída para rejeições de score, gates e aquisição na seleção visual.

## Problema

Após G89–G91, cada classe de resultado já existia tipada, mas `visual.py` ainda
montava dicts para rejeições de score e acumulava rows antes de entregar a
auditoria. `search_query_audit_rows()` contava dicts de rejeição em vez de fatos
canônicos. Isso mantinha uma interpretação da evidência dentro do coordenador.

## Mudança

`visual_audit.candidate_rejection_rows()` projeta `CandidateEvaluation`,
`CandidateRejection` e `CandidateAcquisitionOutcome` no formato compatível
exigido pela seleção persistida. `candidate_rejection_counts()` calcula o total
por query diretamente dos mesmos contratos, e `search_query_audit_rows()` recebe
essa contagem validada. `candidate_audit_rows()` também projeta as três fontes
tipadas; `visual.py` não mantém uma lista intermediária de rejection rows.

As rows `media.json` permanecem no limite de compatibilidade. A mensagem de
fallback continua reportando candidatos rejeitados; as métricas incrementais
continuam sendo atualizadas pelo coordenador sem fabricar rows para isso.

## Arquivos

- `src/curio/stages/visual.py` — remove projeção/armazenamento de rejeições no estado intermediário e delega a projeção final.
- `src/curio/stages/visual_audit.py` — centraliza projeção de rows, contagem por query e auditoria derivada de contratos.
- `tests/test_visual_audit.py` — migra para APIs tipadas e mantém regressões de contagem e saída.

## Validação

- Focados de auditoria, diretor, coleta, buraco negro, avaliação e seleção: **105 passaram**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- `pytest -q`: **997 passaram em 194,65 s**.

## Limites

G92 não muda gates, scoring, escolha editorial nem aquisição. O contrato persistido de `SceneMediaSelection.rejected` continua sendo uma lista de mappings, projetada somente na fronteira. `visual.py` ainda coordena busca por tiers, aquisições, fallback e métricas. Sem geração real, pois a mudança é de ownership e projeção, não de comportamento editorial.
