# G42 — fronteira da projeção de capítulos

`stages/scenes.py` combinava o planner com `Chapter`, modelo do formato
histórico `chapters.json`. A classe mantinha serialização, conversões entre
semântica e timeline e normalização de registros legados. Isso fazia pipeline,
CLI e testes importarem o formato persistido do planner.

A classe e a conversão `Chapter → SemanticScene` foram movidas para `stages/scene_projection.py`; o contrato semântico não conhece mais a projeção legada. Imports internos usam o
novo módulo. `stages.scenes.Chapter` segue como reexport para consumidores
externos que ainda importam o caminho antigo. O planner mantém seus helpers de
normalização; a projeção os chama somente ao desserializar o formato histórico,
na fronteira de compatibilidade. Não houve mudança no schema gravado nem no
comportamento editorial.

Validação focada: `test_scene_contract.py`, `test_visual_contracts.py`,
`test_visual_query_concepts.py` e `test_pipeline_integration.py`: 39 passaram
em 36,68 s após mover a conversão semântica. Suíte integral: **903 passaram
em 178,20 s**. `compileall`,
`git diff --check` e verificação do reexport de compatibilidade passaram; não
restam imports internos de `Chapter` pelo caminho `stages.scenes`.

## Continuação G43 — saída enriquecida sem duplicação

`SceneStageResult` duplicava as cenas já contidas em `SceneEnrichmentResult`.
Removi a cópia: o pipeline consome um único batch enriquecido para mídia e
metadata, e o estágio valida o alinhamento entre esse batch e os spans. O
contrato rejeita tipos de saída incompatíveis; fixtures agora usam o resultado
real do enrichment.

Validação G43: testes focados de estágio, integração, enrichment e contrato: 27
passaram em 36,65 s. Suíte integral: **903 passaram em 183,70 s**;
`compileall` e `git diff --check` passaram.
