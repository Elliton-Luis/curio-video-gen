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

## Continuação G44 — stage de render final

A seleção de áudio final, assinatura das transições, decisão de cache do MP4,
construção silenciosa, SFX e render final foram agrupados em
`pipeline_render.run_render_stage`. A entrada exige cenas/spans e o plano de
mídia já resolvidos; `RenderStageResult` retorna as saídas que metadata e
métricas consomem. O coordenador não consulta mais os detalhes internos do
retorno de `audio.selection.resolve_audio`.

Validação focada de render, cache, TTS e pipeline: **33 passaram em 124,46 s**.
A suíte integral e checks finais serão anotados após a rodada completa.

Validação G44: contratos/política de render: 10 passaram; integração de render,
cache, TTS e pipeline: 33 passaram. Suíte integral: **903 passaram em 179,78 s**;
`compileall` e `git diff --check` passaram.

A regressão final valida que render rejeita cenas/spans desalinhados antes de
qualquer leitura de cache ou efeito colateral. Focados: **34 passaram em
118,97 s**. Suíte integral após essa validação: **904 passaram em 185,86 s**;
`compileall` e `git diff --check` passaram.

## Continuação G45 — contrato de entrada do render

`run_render_stage` agora recebe `RenderStageInput`, construído com campos
nomeados. O contrato valida cenas/spans, correspondência do plano de mídia,
timeline visual, duração e tipos dos demais campos antes de acessar cache ou
renderizar. O pipeline coordena o pedido e consome `RenderStageResult`.

Focados de contratos/política: **11 passaram**. Integração de render e suíte
integral após esta mudança serão registradas na validação correspondente.

Validação G45: contrato/política: 11 passaram; pipeline, TTS, render e cache:
34 passaram em 119,48 s. `compileall` e `git diff --check` passaram. A suíte
integral permanece em 904 testes verdes após G44; a validação integral final
será repetida após a série estrutural.

## Continuação G46 — projeção assistida de metadata

A montagem dos campos do JSON assistido saiu de `_run_pipeline` e foi para
`pipeline_metadata.build_assisted_run_metadata`. A função consome os resultados
tipados de pesquisa, roteiro, cenas, áudio, timeline e render. O coordenador
continua responsável pela ordem dos estágios e persistência do registro de
fontes; o schema salvo foi preservado.

Validação focada de metadata, integração e cenas: **15 passaram em 46,72 s**.
A suíte completa será repetida antes do commit.

Validação integral após G46: **904 passaram em 174,16 s**; `compileall` e
`git diff --check` passaram.

## Continuação G47 — estado standby pertence à etapa de mídia

A ramificação sem asset não persiste mais estado dentro do coordenador.
`pipeline_media.prepare_media_standby` valida seleção vazia, escreve instruções
para arquivos manuais, persiste sources/relatório e metadata compatível, e
retorna `MediaStandby` para o coordenador propagar.

Focados de standby, sources e mídia: **11 passaram em 1,84 s**. A suíte
integral será executada antes do commit.

Validação integral após G47: **904 passaram em 176,06 s**; `compileall` e
`git diff --check` passaram.

## Continuação G48 — classificação e validação compartilhadas

`Chapter.from_dict` e `visual_context.py` dependiam de helpers privados em
`scenes.py`. Classificação de tipo visual foi extraída para
`scene_visual_type.py`; normalização/rejeição de representações foi extraída
para `scene_representations.py`. Planner local/LLM, enrichment e projeção
histórica compartilham as mesmas regras sem chamar o módulo planner. O
classificador segue reexportado por `scenes.py` para compatibilidade.

Focados de contratos, planner local/LLM e enrichment: **80 passaram em 0,31 s**.
A suíte completa será executada antes do commit.

Validação integral após G48: **904 passaram em 187,69 s**; `compileall` e
`git diff --check` passaram.
