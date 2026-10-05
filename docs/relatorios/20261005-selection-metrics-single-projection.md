# F9 — Projeção única das métricas de seleção visual

**Commit:** `ed34825 refactor: unify media selection metric projections`  
**Estado:** concluída e validada.  
**Escopo:** contagens de seleção publicadas em `consumption.media` e
`pipeline.visual_report`.

## Problema

`pipeline.visual_report` calculava métricas de seleção por `MediaSelectionStats`,
com base em `MediaMetricsInput`. Em paralelo, `consumption.media.assets`,
`fallbacks` e `reused` contavam diretamente as rows encontradas em `meta.media`.
Assim, o mesmo relatório tinha fontes de verdade diferentes: `assets` incluía
qualquer row com `asset` (inclusive sintético), `fallbacks` contava rows sem
`asset`, e `reused` dependia de `reused_from`. Uma execução sem projeção de
seleção podia ainda publicar zero, embora o estado fosse desconhecido.

## Mudança

`MediaSelectionStats` agora também define `scenes_with_selected_visual` (assets
reais novos/reutilizados mais cenas sintéticas) e publica os totais canônicos
necessários à seleção. `RunMetrics.to_dict()` projeta os campos de
`consumption.media` da mesma instância de stats usada pelo relatório visual. Os
campos canônicos publicados são:

- `scenes_with_real_asset`, `scenes_with_selected_visual`;
- `unique_assets`, `real_asset_occurrences`, `reused_assets`, `reuse_count`,
  `unique_asset_ratio`;
- `scenes_with_new_asset`, `scenes_with_reused_asset`, `synthetic_scenes`;
- `scenes_without_visual`, `scenes_with_unknown_decision`.

Os campos de formato histórico `assets`, `fallbacks` e `reused` continuam no
JSON como aliases explícitos de `scenes_with_selected_visual`,
`scenes_without_visual` e `scenes_with_reused_asset`, respectivamente. Não há
consumidores internos desses nomes além do emissor. Quando a projeção de
seleção ainda não ocorreu, aliases e contagens canônicas ficam `null`; ausência
de evidência não é convertida em zero.

`backfill_from_metadata()` deliberadamente mantém `consumption.media: null`,
pois não possui contadores de consumo da execução original. A nova projeção não
infere requests, downloads ou cache a partir de artefatos persistidos.

## Contrato validado

Uma regressão mistura cinco cenas: asset real novo, reuso de asset real,
sintético, ausência visual explícita e estado desconhecido. Verifica que ambas
as superfícies publicam os mesmos totais, incluindo um asset único em duas
ocorrências, uma cena reutilizada, uma sintética, uma sem visual e uma
desconhecida. Outro teste assegura que as métricas continuem `null` antes da
projeção, mesmo quando `meta.media` contém uma row.

## Validação

- `pytest -q tests/test_media_metric_units.py tests/test_media_artifacts.py tests/test_media_funnel.py`: **26 passaram**.
- `pytest -q`: **999 passaram em 198,62 s**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

## Limites restantes

F9 não completa a fase de métricas. Contadores de requests/retries/cache ainda
possuem contratos e aliases históricos a auditar; faltam backfill histórico
canônico, timers de lifecycle adicionais, perfil por suboperação e conciliação
entre seleção e uso no render. Também não foi feita uma geração real nesta
fase, pois a mudança é apenas projeção do modelo de métricas.
