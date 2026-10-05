# G74 — resultados tipados de aquisição de candidatos

**Commit:** `57a9a21` (`refactor: model candidate acquisition outcomes`)
**Estado:** concluída; a orquestração do loop ainda está no coordenador visual.

## Problema

O loop de aquisição atualizava `entry: dict` para comunicar resultado: falha de
download, dimensão inválida, duplicate hash, asset após download, origem cache/
download, ordem e reuse reason. A mesma row também representava avaliação e
proveniência inicial. Isso deixava rejeição e sucesso dependendo de mutações
ad hoc no coordenador.

## Mudança

`CandidateAcquisitionOutcome` é um contrato frozen ligado a
`RankedSelectionCandidate` e `MediaAssetSnapshot`, com estados explícitos:

- `selected`, que exige origem, ordem e identidade de conteúdo;
- `download_failed`;
- `invalid_dimensions`, com origem e estágio técnico;
- `duplicate_content`, com identidade SHA-256.

Os estados de rejeição exigem motivo e etapa, e não aceitam fields de seleção.
`to_selected_asset()` projeta um sucesso para `SelectedAsset`; `to_rejection_row()`
projeta identity/query/provider/motivo para a auditoria. `visual.py` passa a usar
o contrato para aquisição nova e para o reuso tardio. A row de avaliação deixa
de receber mutações de lifecycle.

## Arquivos

- `src/curio/stages/media_acquisition_contracts.py` (novo)
- `src/curio/stages/visual.py`
- `tests/test_media_selection.py`

## Validação

- **100 testes focados** em seleção, auditoria, direção visual e pipeline.
- **941 passaram, 1 deselecionado** por HTTP 429 da API real da Wikipédia, em
  **172,28 s**.
- `python -m compileall -q src tests` e `git diff --check` passaram.
- Nenhuma geração real nesta fase.

## Limite e próxima fronteira

`visual.py` ainda coordena janela concorrente, consumo de futures, efeitos de
metrics/logging e política de continuar/fallback. G74 define o output por
candidato, mas não moveu esse loop. A próxima extração deve ter um owner de
seleção/aquisição que consome `RankedSelectionCandidate`, usa o service técnico
de `media_acquisition` e devolve outcomes tipados; nenhum adapter/provider deve
adquirir bytes ou decidir relevância editorial.
