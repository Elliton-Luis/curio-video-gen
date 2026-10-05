# G76 — tentativa técnica compartilhada de aquisição

**Commit:** `b87ba98` (`refactor: share technical media acquisition attempts`)

**Estado:** concluída e testada; a migração arquitetural geral segue em andamento.

## Causa

Após G75, a aquisição fresh e a tentativa de reuso tardio tinham caminhos
separados para baixar (ou reconhecer cache), aguardar timeout e validar as
dimensões do arquivo. Falhas de download viravam rejeições auditadas no caminho
fresh e eram simplesmente ignoradas no caminho de reuso. A duplicação tornava
possível divergir o tratamento técnico entre os dois caminhos.

## Mudança

`_acquire_and_validate()` passou a ser o owner comum da tentativa técnica. Ela
aceita `RankedSelectionCandidate` e um future opcional (usado pela janela
concorrente fresh) e devolve `TechnicalAcquisitionAttempt`, um resultado
imutável contendo snapshot do asset, estado (`ready`, `download_failed` ou
`invalid_dimensions`), origem cache/download e erro quando aplicável.

Fresh continua transformando falhas em outcomes e linhas de auditoria; reuse
continua ignorando tentativas técnicas malsucedidas e procurando o próximo
candidato. A política editorial, o hash/deduplicação, os providers e a sequência
fresh → sintético → reuse não mudaram. A mudança não remove os efeitos de
metrics/logging que ficam no módulo de aquisição.

## Arquivos

- `src/curio/stages/media_candidate_acquisition.py`: introduz o resultado
  técnico compartilhado e usa a mesma operação nos dois caminhos.
- `tests/test_media_selection.py`: cobre falha de download e origem cache pelo
  contrato compartilhado.

## Validação

- **103 testes focados** em seleção, direção visual, uso de assets, auditoria,
  busca de candidatos e integração/pipeline.
- **944 testes passaram; 1 foi desmarcado** por HTTP 429 da API real da
  Wikipédia, em **171,65 s** (`pytest -q -k 'not standby_sem_imagens'`).
- `python -m compileall -q src tests` e `git diff --check` passaram após o
  ajuste final; os mesmos 103 testes focados passaram depois desse ajuste.
- Nenhuma geração real foi executada nesta fase.

## Limite

G76 unifica a transição técnica, mas o módulo ainda coordena janela/futures,
deduplicação por hash, consulta de uso cross-scene e efeitos operacionais.
Seleção editorial e ordem de fallback continuam em `visual.py`. Isso reduz uma
duplicação concreta sem declarar a aquisição ou a arquitetura de mídia
totalmente concluídas.
