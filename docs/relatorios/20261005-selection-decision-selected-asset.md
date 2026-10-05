# G71 — construir SelectionDecision a partir de SelectedAsset

**Commit:** `d8dace3` (`refactor: build selection decisions from selected assets`)
**Estado:** concluída; a projeção de mídia para persistência continua na fronteira.

## Problema

`make_selection_decision()` recebia uma lista de dicts e voltava a ler provider,
asset ID, query, query source, representation, score e reuse reason. A decisão
final dependia assim de um schema de row que já havia sido validado em
`SelectedAsset` e `SceneMediaSelection`.

## Mudança

`SelectedAsset` agora expõe `query_source` e `representation` junto a `query`,
asset, score e reuse reason. `make_selection_decision()` exige `SelectedAsset`
e usa seus campos validados para definir estado e proveniência. A aquisição
visual e o reuso cross-scene adaptam suas rows para esse contrato antes de
criar a decisão. Rows dict deixam de ser aceitas diretamente pela política de
decisão.

Os estados e suas razões, as regras de fallback, os gates editoriais e o JSON
persistido permanecem os mesmos.

## Arquivos

- `src/curio/media/selection_result.py`
- `src/curio/stages/media_selection.py`
- `src/curio/stages/visual.py`
- `tests/test_media_selection.py`

## Validação

- **88 testes focados passaram** para seleção, contratos, direção visual,
  integração de pipeline e auditoria.
- **940 testes passaram**, com 1 teste externo deselecionado após HTTP 429 da
  API real da Wikipédia; duração 179,44 s.
- `python -m compileall -q src tests` e `git diff --check` passaram.
- Nenhuma geração real executada.

## Limite

`visual.py` ainda opera com rows mutáveis durante download, validação de
resolução, deduplicação por hash, fallback e composição da auditoria. A próxima
migração deve modelar esse lifecycle sem mover política editorial para o
acquisition técnico nem duplicar o contrato `SelectedAsset`.
