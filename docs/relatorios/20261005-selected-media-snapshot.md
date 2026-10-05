# G68 — snapshots imutáveis de mídia selecionada

**Commit:** `0e62a18 refactor: freeze selected media snapshots`  
**Estado:** implementado e validado; a migração arquitetural geral continua em andamento.

## Causa

`SelectedAsset` e `SceneMediaSelection` eram frozen apenas externamente. Por
dentro, expunham `MediaAsset` mutável e guardavam a projeção original do projeto,
score details, rejeições e reuso em estruturas mutáveis. Consumidores podiam
alterar facts ou criar divergência entre os atributos do contrato e `to_dict()`.
`ReviewMediaPlan` ainda exigia rows dict para rejeições.

## Contrato após G68

O snapshot introduzido em G66 foi movido de `stages/media_contracts.py` para
`media/asset_snapshot.py` e renomeado `MediaAssetSnapshot`. `Candidate`,
`SelectedAsset` e `SceneMediaSelection` agora consomem esse tipo. `MediaAsset`
continua mutable no ciclo de provider/cache/download e para preparação de
assets técnicos.

`selection_result.py` congela recursivamente o row lido, score details,
rejeições e dados de reuso. `to_dict()` devolve uma cópia independente com
dicts/listas e mantém extensões JSON existentes. `ReviewMediaPlan` converte a
seleção por seu row projetado, uma adaptação explícita para o contrato de review.

## Arquivos e regressões

- `src/curio/media/asset_snapshot.py`
- `src/curio/media/selection_result.py`
- `src/curio/stages/media_contracts.py`
- `src/curio/stages/review.py`
- `tests/test_media_contracts.py`
- `tests/test_media_selection.py`

Testes cobrem alterações no row fonte e na projeção, imutabilidade nested de
asset/score/rejected/reuse, round-trip de extensões, reuso, review e render.

## Validação

- Mídia, review, render e consumidores: **70 testes focados passaram**.
- Suíte ampla: **935 passaram, 1 excluído** por HTTP 429 da API real da Wikipédia.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- Sem geração real ou inspeção visual nesta fase.

O formato persistido segue igual; loaders preservam rows originais e adapters
produzem cópias editáveis. Veja o [relatório arquitetural completo](20261005-relatorio-arquitetura-estado-atual.md)
e a [auditoria de pipeline e contratos](../analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md).
