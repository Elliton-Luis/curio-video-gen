# G69 — donor tipado no reuso cross-scene

**Commit:** `1d1335f refactor: carry typed assets through reuse selection`  
**Estado:** implementado e validado; o plano arquitetural integral permanece aberto.

## Problema

`ReuseCandidate` era frozen externamente, mas seu campo `entry` era dict mutável.
O algoritmo criava esse row a partir de `SelectedAsset`, achatava a evidência
validada antes de comparar doadores e reconstruía outro row depois da decisão.

## Alteração

`ReuseCandidate.entry` agora exige `SelectedAsset`, contrato profundamente
imutável introduzido em G68. `resolve_cross_scene_reuse()` conserva a entry
tipada durante o cálculo de relevância e ordenação de doadores. Só depois de
`select_reuse_candidate()` vencer é que a entry é projetada com `to_dict()` e
combinada com a justificativa de reuso da cena receptora.

Não houve mudança no cálculo de relevância, critério de desempate, fallback ou
seleção. Fixtures que construíam `ReuseCandidate` com dict foram migrados para
`SelectedAsset`; o contrato rejeita a forma antiga.

## Arquivos

- `src/curio/stages/media_selection.py`
- `tests/test_media_selection.py`

## Validação

- Reuso, seleção e integrações visuais relacionadas: **63 testes passaram**.
- Suíte ampla: **936 passaram, 1 excluído** por HTTP 429 da API real da Wikipédia.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- Nenhuma geração real nesta fase.

## Pendência relacionada

`SelectionPool` e a orquestração em `visual.py` ainda transportam rows JSON
mutáveis durante ajuste CLIP, download, dedupe pós-download e seleção. Essas
rows representam um lifecycle com transições de estado; a próxima fase precisa
modelar esses estados e donos antes de retirar os dicts. Consulte o
[relatório arquitetural](20261005-relatorio-arquitetura-estado-atual.md) e a
[auditoria de pipeline e contratos](../analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md).
