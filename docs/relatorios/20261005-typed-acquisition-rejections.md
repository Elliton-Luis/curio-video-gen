# G91 — outcomes de aquisição tipados até a auditoria

**Data:** 2026-10-05  
**Commit:** `e187697 refactor: preserve typed acquisition rejections`  
**Estado:** concluída para o fluxo de seleção por cena.

## Mudança

`visual.py` convertia `CandidateAcquisitionOutcome` rejeitados em dicts logo após cada tentativa, embora o contrato já carregasse candidato, asset pós-download, identidade, estágio e motivo. G91 mantém esses outcomes em tupla/lista tipada durante as tiers; `visual_audit.py` projeta as rows para auditoria de candidatos e contagem por query. A projeção para `SceneMediaSelection.rejected` ocorre no limite de saída da cena.

O schema e os textos/motivos persistidos foram preservados. Outcomes selecionados continuam virando `SelectedAsset`; gates, aquisição, seleção e fallback não mudaram. Rejeições score/technical e outcomes pós-download chegam à auditoria tipados; os dicts de score rejection ainda são necessários para a row de rejeição legada exibida na seleção de cena.

## Arquivos

- `src/curio/stages/visual.py` — acumula outcomes tipados e os projeta apenas na fronteira da seleção.
- `src/curio/stages/visual_audit.py` — consome outcomes rejeitados tipados para auditoria/query totals.
- `tests/test_visual_audit.py` — cobre projeção de falha de aquisição tipada.

## Validação

- Focados de auditoria visual, diretor, seleção e avaliação: **90 passaram**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- `pytest -q`: **997 passaram em 195,03 s**.

## Limites

G91 remove a conversão antecipada, não toda row persistida: `media.json` continua formato externo e `SceneMediaSelection.rejected` ainda contém mappings compatíveis. `visual.py` continua coordenando a ordem das tiers e fallback. Nenhuma geração real foi feita, pois a mudança preserva a decisão editorial e a aquisição.
