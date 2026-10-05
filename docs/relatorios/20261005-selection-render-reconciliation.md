# F13 — reconciliação de assets selecionados com a timeline visual

**Commit:** `50ba36d refactor: reconcile selected assets with visual timeline`  
**Estado:** concluída e validada.  
**Escopo:** relação entre `MediaStageResult` e a timeline visual persistida.

## Problema

As métricas já contavam identidades selecionadas e identidades atribuídas aos
beats, porém não mostravam se assets selecionados ficavam fora da timeline ou
se a timeline carregava IDs que não constavam na seleção. Além disso, o
backfill passava uma lista vazia quando o arquivo de timeline não existia; isso
parecia uma observação real e podia transformar uma estimativa em contagem de
assets não utilizados.

## Mudança e contrato

`visual_plan()` marca a origem da timeline como `persisted` quando recebeu a
lista observada; sem ela, `visual_timeline_source` é
`estimated_from_selection`. `pipeline.selection_render_reconciliation` compara
as identidades selecionadas e as presentes nos beats e publica:

- selecionados, renderizados e presentes em ambos;
- selecionados sem uso na timeline;
- IDs da timeline ausentes na seleção;
- cobertura única dos assets selecionados.

O diff inclui assets reais e sintéticos, pois mede identidade/uso visual, não
aquisição real. Se a seleção ou timeline não foi observada, `observed` é falso
e os valores ficam `null`. Backfill agora passa `None` quando o artefato não
existe ou não pôde ser lido, sem converter desconhecido em timeline vazia.

## Regressões e validação

Um teste mistura dois assets selecionados com uma timeline que usa um deles e
inclui um ID estrangeiro; valida interseção, perda, divergência e cobertura.
Outro teste deixa a timeline ausente e exige resultado desconhecido. Um
terceiro cobre o caminho de backfill sem arquivo visual.

- `pytest -q tests/test_media_metric_units.py tests/test_media_artifacts.py tests/test_visual_asset_usage.py`: **41 passaram**.
- `pytest -q`: **1006 passaram em 192,03 s**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

## Limites restantes

`visual_asset_ids` segue a interpretação atual de visibilidade dos beats e
imagens; não é uma inspeção dos frames renderizados após FFmpeg. A fase mede
identidade planejada/atribuída, não comprova decodificação, duração efetiva em
frame, oclusão nem qualidade visual. Backfill não inventa o timeline perdido.
