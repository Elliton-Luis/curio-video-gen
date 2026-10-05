# G59 — saída tipada da etapa de mídia — 2026-10-05

## Problema

`visual.fetch_media_multi()` devolvia rows de `media.json` e warnings como
tupla. `pipeline_visual.resolve_media()` reconstruía imediatamente
`MediaStageResult` a partir dessas mesmas rows. Além da conversão redundante,
a validação do contrato ocorria depois que a etapa produtora terminava.

## Mudança

- A aquisição visual retorna `MediaStageResult` validado, com source `provider`
  e warnings incluídos.
- Resolução cross-scene e anotação de reuso recebem e devolvem
  `MediaStageResult`; cada cena alterada é reconstruída pela validação do
  contrato.
- `pipeline_visual` valida o tipo da saída e passa o resultado a persistência e
  métricas sem converter rows novamente.
- Mocks de pipeline, integração e standby devolvem o mesmo contrato que o
  produtor real.
- A projeção para `media.json` permanece no writer/cache, como fronteira
  externa.

## Compatibilidade e limite

O formato de `media.json`, warnings, seleção, reuso e decisões persistidas foi
preservado. `fetch_media_multi` é uma interface interna e mudou de
`(rows, warnings)` para `MediaStageResult`; os consumidores encontrados foram
migrados. `_search_scene_with_shortcircuit` ainda produz row local por cena,
validada ao montar o resultado da etapa. Esse boundary interno continua como
trabalho futuro, não como saída da etapa.

## Arquivos

Código: `src/curio/stages/visual.py`,
`src/curio/stages/media_selection.py`, `src/curio/pipeline_visual.py`.

Testes: `tests/test_media_diag.py`, `tests/test_media_selection.py`,
`tests/test_pipeline_integration.py`, `tests/test_pipeline_visual.py` e
`tests/test_standby_flow.py`.

## Verificação

- Testes focados de integração: **91 passaram**.
- Contrato/produtor tipado: **39 passaram**, incluindo regressão direta para a
  saída de `fetch_media_multi`.
- Suíte completa: **914 passaram em 189,20 s**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
