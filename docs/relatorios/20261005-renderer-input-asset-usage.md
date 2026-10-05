# F14 — proveniência dos assets do segmento visual

**Commits:** `7bc5c23 refactor: record visual assets passed to renderer` and
`94119e3 refactor: distinguish reused render segments`  
**Estado:** concluída e validada.  
**Escopo:** timeline visual ou plano primário → filtros de caminho → segmento
visual silencioso.

## Problema

F13 comparava a seleção com a timeline planejada, mas `_visual_segment()`
filtrava silenciosamente entradas cujo `local_path` não existia. Sem outro
registro, uma imagem selecionada podia desaparecer antes de `render.py`, que
então criava um fallback. O caminho legado `build_silent()` também podia gerar
fallback sem registrar essa substituição.

## Contrato e mudança

`media.render_usage` introduz `VisualRenderSceneUsage` e `VisualRenderUsage`.
Ambos os construtores de vídeo silencioso retornam o contrato tipado. Por cena,
ele registra IDs solicitados, IDs associados ao segmento, IDs sem arquivo,
IDs omitidos e se o segmento usou fallback. `RenderStageResult`
preserva a proveniência até o pipeline; preparação humana, finalize e rerender
projetam o mesmo resultado em `pipeline.visual_render_usage`.

`segment_reused` distingue os inputs de segmentos recuperados do cache daqueles
submetidos a nova codificação. Quando o estágio reutiliza o MP4 silencioso/final
sem reconstruir segmentos, `visual_render_usage` permanece `null`, pois não
houve observação dos inputs nesta execução.
`RenderAsset.identity` usa a identidade estável de mídia para alinhar a
proveniência com selection/timeline e manter o cache de segmentos dependente
também dos bytes locais (tamanho e mtime).

## Evidência local recente e performance

Foram inspecionadas somente as 20 métricas mais recentes. Todas são de
`teste-integracao` ou `proj-review`, registram zero queries lógicas e nenhum
provider request/search adapter call. Elas validam finalize/rerender e cache,
mas não servem como baseline de aquisição real nem permitem atribuir gargalo a
provider, retry, download ou scoring. Portanto esta fase não conclui o profile
de performance; é necessário obter uma execução real de aquisição representada
por métricas atuais.

## Regressões e validação

Testes cobrem timeline com um caminho válido e outro ausente, fallback quando
nenhum arquivo existe e o caminho legado com plano primário. Também verificam
que o collector persiste somente o contrato tipado recebido.

- Testes focados (`test_pipeline_render_contracts.py`,
  `test_visual_asset_usage.py`, `test_review_flow.py`,
  `test_media_metric_units.py`): **62 passaram**.
- Suíte completa: **1009 passaram em 192,11 s**.
- `python -m compileall -q src tests` e `git diff --check`: passaram.

## Limites restantes

O relatório confirma arquivos com caminho existente encaminhados para as
funções de render. Não prova que FFmpeg decodificou cada input ou que os pixels
apareceram no MP4. Ainda não há inspeção visual automática do artefato final.
O cache de segmento pode reutilizar vídeo antigo sem relatar IDs nesta
execução, então o resultado fica unknown nesse caso.
