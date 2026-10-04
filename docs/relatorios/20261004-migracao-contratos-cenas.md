# Migração incremental dos contratos de cena — 2026-10-04

## Mudanças

O planner LLM, seus reparos estruturais e o fallback local agora produzem e
transformam `SemanticScene` diretamente. A duração e os limites de timeline
viajam em `TimelineSpan`; a conversão para `Chapter` ocorre na fronteira de
persistência compatível e render.

O pipeline agora salva `script/scene-plan.json` (schema 1) como cache canônico
de semântica e spans. Quando encontra somente o `chapters.json` legado, valida
e converte os capítulos, recupera representações locais apenas quando a
recuperação legada se aplica e grava o novo plano. A leitura do plano canônico
ignora divergência de conteúdo no arquivo legado e repara a projeção antes de
devolvê-la a consumidores externos. Um schema canônico desconhecido ou inválido
falha claramente.

`ScenePlanResult` valida provenance, plano não vazio, IDs únicos e
correspondência em ordem entre cenas e spans. `SemanticScene.from_dict`
reconstrói o contrato sem usar `Chapter`.

## Verificação

- Focados de contrato, cache, integração de pipeline e seleção visual: 25
  passaram.
- Suíte completa: 843 passaram em 144,09 s.
- `compileall` e `git diff --check` passaram.
- Não foi executada uma nova geração real nesta subfase. As execuções reais
  anteriores seguem registradas em
  `20261004-validacao-arquitetural-execucoes-reais.md` e antecedem esta
  alteração.

## A4j: enrichment semântico puro

O enrichment deixa de mutar `Chapter`: as transformações de contexto global,
âncoras locais, contexto de entidade e etimologia recebem/devolvem
`SemanticScene`. `scene_enrichment` valida a batch e gera `Chapter` só como
projeção compatível de saída. Uma regressão integral mostrou o antigo `False`
de `fill_missing_context` para entidade sem nome sendo confundido com batch;
esse caminho agora retorna as cenas originais. Após a correção, os focados
passaram (39) e a suíte completa passou com 844 testes em 145,67 s.

`visual_context` e `etymology` agora rejeitam entrada que não seja
`SemanticScene` nas transformações novas. `scene_enrichment` ainda aceita
`Chapter` somente como adaptador dos caches antigos e projeta capítulos ao
final. A semântica não sofre mutação in-place durante enriquecimento.

## A4k: timing fora do planner semântico

`stages/timing.py` alinha `SemanticScene[]` a `TimelineSpan[]` sem alterar as
cenas. `pipeline_audio` retorna spans atualizados para WordBoundary ou fallback
proporcional e grava a visão legada de `timeline.json`; o pipeline só cria
`Chapter` depois desse limite. `SceneStageResult` valida que cenas, spans e
projeção correspondem em ordem. O antigo `scenes.apply_timings` foi removido
depois da migração de seu único consumidor. Focados: 66 passaram; suíte
completa: 847 passaram em 146,75 s.

## Snapshot após A4k (fronteiras migradas em A4l–A4o abaixo)

O pipeline ainda projeta `Chapter` para `chapters.json`, metadata externa,
revisão/folha de contato e consumidores de CLI que carregam projetos. A mídia,
timeline visual, teleprompter e render silencioso já usam contratos semânticos
e temporais separados. A migração continua por consumidor, preservando o
formato externo até esses limites usarem contratos tipados próprios. Cache de
aquisição permanece independente do cache semântico e não escolhe mídia.

## A4l: timeline visual e métricas recebem spans tipados

`build_visual_timeline` e `pipeline_timeline` agora recebem
`SemanticScene[] + TimelineSpan[]`; o tempo visual não é lido do objeto
Chapter. Ordenação de inserções exige `SemanticScene` e usa somente as
representações já declaradas. `retime_visual_timeline` também rejeita IDs
ausentes, duplicados ou fora de ordem, em vez de manter timestamps antigos
silenciosamente. Métricas visuais usam spans e o backfill converte linhas
históricas válidas do metadata, ignorando linhas inválidas como desconhecidas.
O formato `chapters.json` permanece como projeção para render, CLI/TUI e
compatibilidade externa. Focados: 120 passaram; suíte completa: 847 passaram
em 145,29 s; a nova regressão de desalinhamento foi validada isoladamente.
`compileall` e `git diff --check` passaram. Não houve geração real nesta fase.

A fronteira visual de planejamento/timing já não depende de Chapter. Permanecem
consumidores downstream de render, subtitles e ferramentas; também permanece
um adaptador Chapter explícito para operações legadas de replanejamento. A
próxima fase deve migrar esses consumidores antes de remover a projeção.

## A4m: teleprompter consome semântica e spans separados

`build_teleprompter_cues` e `write_teleprompter_ass` recebem agora
`SemanticScene[] + TimelineSpan[]`, validam identidade/ordem e distribuem os
blocos a partir do texto da cena e do span correspondente. `pipeline.py` usa
diretamente esses dados antes de qualquer projeção Chapter para render. O
formato ASS, texto, regras de quebra e avisos de mudança de cena foram
preservados. A regressão cobre rejeição de IDs desalinhados. Focados: 101
passaram; suíte completa: **849 passaram em 145,75 s**; `compileall` e
`git diff --check` passaram. O smoke script não chega aos testes do teleprompter:
falha antes por importar `pipeline._relevance`, removida anteriormente, e usa
`scenes._local_chapters`, também removida. Isso é dívida do script, não falha
da mudança atual.

## A4n: render silencioso recebe semântica e timeline separadas

`pipeline_render` não importa mais `Chapter`. Montagem por mídia e por visual
consome `SemanticScene[] + TimelineSpan[]`; segmentos recebem ID explícito e
duram conforme o span. Política de transição consome somente cenas semânticas,
e sua assinatura combina cenas e spans com validação de IDs. `pipeline.py`
usa os contratos produzidos na geração e no fluxo humano; finalize/rerender
convertem o arquivo Chapter histórico uma vez na entrada. A extensão de áudio
humano maior que a timeline também amplia o span usado no render, inclusive no
caminho sem visual timeline. Focados: 140 passaram; suíte completa: **850
passaram em 145,42 s**; `compileall` e `git diff --check` passaram. Sem nova
geração real nesta fase. O smoke script ainda para antes dos seus checks por
imports internos já removidos (`pipeline._relevance`, `scenes._local_chapters`).

## A4o: resultado de cenas não carrega projeção Chapter

`SceneEnrichmentResult` e `SceneStageResult` agora retornam somente
`SemanticScene[]` e `TimelineSpan[]`; removi a compatibilidade interna que
aceitava Chapter como entrada do enrichment e a duplicação `chapters[]` no
resultado do estágio. `pipeline_scenes` cria Chapter apenas ao persistir a
projeção `chapters.json`. O pipeline principal retém semântica/span em memória;
constrói Chapter depois do áudio somente para metadata, revisão e formato
compatível. Standby usa a quantidade de SemanticScene diretamente. Focados:
40 passaram; suíte completa: **850 passaram em 147,11 s**; compileall e
`git diff --check` passaram. Sem geração real nesta fase.

A fronteira de planejamento/enrichment já não depende de Chapter. Restam
adaptações de leitura/escrita do projeto salvo e metadata.

## A4p: revisão visual consome cenas semânticas

`scene_rows`, folha de contato e dry-run recebem `SemanticScene[]` e usam seus
campos tipados sem recuperar significado via `getattr`. Entrada Chapter falha
com erro de contrato, e IDs semânticos duplicados são rejeitados. Geração passa
as cenas atuais; `cmd_review` adapta o formato Chapter persistido ao carregar o
projeto. Layout, informação exibida, scoring, rejeições e arquivos gerados
permanecem iguais. Focados: 154 passaram; suíte completa: **851 passaram em
146,30 s**; compileall e `git diff --check` passaram. Sem geração real nesta
fase. A leitura e gravação do schema histórico e metadata permanecem como
fronteiras de compatibilidade.

## A4q: rerender usa contrato canônico ao replanejar a timeline visual

`rebuild_visual_timeline` recebe agora `SemanticScene[]` e `TimelineSpan[]`;
seu adaptador Chapter foi removido. A CLI ainda desserializa o projeto salvo
uma vez na entrada e passa os dois contratos ao replanejamento; a ordem manual
de imagens permanece intacta. Focados: 29 passaram; suíte completa: **851
passaram em 145,93 s**; compileall e `git diff --check` passaram. Sem nova
geração real nesta fase.

## A4r: Chapter é projetado no limite de metadata

`_base_metadata` consome `SemanticScene[] + TimelineSpan[]`, valida ordem e
projeta Chapter somente para a chave `chapters` já publicada em metadata.
Geração AI mantém a batch tipada após o áudio e calcula durações pelos spans;
human-pending só projeta na gravação legada de `timeline.json`. Removi
`ScenePlanResult.timeline_chapters`, método sem consumidores cuja documentação
indicava incorretamente que o render usava Chapter. Testes cobrem shape legado,
tempos projetados e erro para IDs desalinhados. Focados: 13 passaram; suíte
completa: **853 passaram em 147,46 s**; compileall e `git diff --check`
passaram. Sem geração real nesta fase.

## A4s: finalize mantém timing em TimelineSpan

`finalize` ainda lê `timeline.json` como Chapter para aceitar projetos salvos,
mas descarta essa projeção após derivar `SemanticScene[] + TimelineSpan[]`.
Extensão da última cena, `retime_visual_timeline` e métricas usam spans; ao
persistir tempos alterados, Chapter é reconstruído apenas para o schema salvo.
O rerender CLI usa seu batch de spans já carregado para métricas. Focados de
finalize/rerender/metadata: 5 passaram; suíte completa antes deste ajuste:
**853 passaram em 147,46 s**; após o ajuste, focados, compileall e
`git diff --check` passaram. Sem geração real nesta fase.

## A4t: aquisição e mídia manual recebem SemanticScene

`fetch_media_multi` e `_resolve_reuse_multi` recebem cenas semânticas tipadas;
`manual_media_scenes` lê campos canônicos diretamente. Os dois limites recusam
Chapter, impedindo extração ou reconstrução tardia da intenção. Removi
`_fetch_media_fallback`, órfão que repetia o comportamento de fallback da
aquisição ativa. Regressões cobrem a rejeição do formato antigo e preservam
seleção manual, mídia real e reuso validado. Focados: 49 passaram; suíte
completa: **855 passaram em 146,30 s**; compileall e `git diff --check`
passaram. Sem geração real nesta fase.

## A4u: resultado da pesquisa é validado na entrada do estágio

`pipeline_research.run_research_stage` declara `ResearchResult` como contrato
de entrada e valida o tipo imediatamente, antes de registrar fontes ou gravar
JSON. O estágio lê diretamente `target`, `rejected`, `tried_queries`,
`weak_warnings`, `facts`, `complementary_queries` e `unresolved_gaps`; removi
defaults de `getattr` que aceitavam resultados parciais e mascaravam produtor
inválido. Os testes de integração que forneciam uma lista de fontes como mock
foram migrados para construir o mesmo `ResearchResult` de produção. Uma nova
regressão prova que retorno incompleto falha antes de qualquer side effect.
Focados de pesquisa/pipeline/TTS/TUI: **50 passaram em 151,64 s**; a suíte
completa passou com **857 testes em 202,95 s**. `compileall` e
`git diff --check` passaram.

## F4: nomes de métricas distinguem seleção real e uso em timeline

As execuções reais mostraram que `visual_report.unique_assets` mede IDs reais
escolhidos, enquanto `pipeline.visual_assets_unique` inclui também cartões
sintéticos presentes na timeline. Os dois valores eram válidos em unidades
diferentes, mas os nomes pareciam contraditórios. Adicionei
`visual_timeline_assets_unique` e
`visual_timeline_assets_reused_across_scenes`, que declaram a unidade; os
campos antigos continuam como aliases para compatibilidade de schema. Uma
regressão compara cenas real/reused/synthetic e prova a distinção. Focados:
`test_media_metric_units.py`, `test_visual_asset_usage.py` e
`test_review_flow.py` — 32 passaram. `compileall` e `git diff --check`
passaram; a suíte integral passou com **858 testes em 197,12 s**.

## V1: cards sintéticos separam intenção de busca e hierarquia de texto

A inspeção do card de ciência mostrou que `visual_entities` de busca eram
desenhadas como uma cadeia explicativa junto à narração, causando colisões.
Cards comuns agora exibem assunto e um trecho de narração; cadeia de entidades
fica exclusiva do tipo tipográfico, onde ela tem significado editorial. O
rodapé usa região própria, limita a duas linhas e indica truncamento com
reticências. A chave de cache do card foi versionada para invalidar PNGs com o
layout antigo. Testes instrumentam `textbbox` real do Pillow e exigem ausência
de colisões tanto para cards científicos como tipográficos. Focados de layout,
tipografia e receipt: **124 passaram**; compileall e `git diff --check`
passaram. A suíte integral passou com **860 testes em 177,31 s**.

## G2a: roteiro e título atravessam o pipeline como artefatos validados

`generate_script` agora produz `ScriptArtifact(text, source)` e
`generate_title` produz `TitleArtifact(text, source)`, ambos imutáveis e
rejeitando texto vazio ou proveniência ausente. O coordenador cria os mesmos
contratos para roteiro fornecido, cache curado e título em cache, valida o tipo
de retorno dos produtores antes de persistir e só extrai strings ao entrar nos
consumidores e formatos atuais. CLI, TUI, fontes do roteiro, conteúdo e schema
de saída permanecem iguais. Os mocks do pipeline foram migrados dos tuples
posicionais para contratos. Focados: **13 passaram em 35,89 s**; a suíte
integral passou com **863 testes em 191,55 s**. `compileall` e
`git diff --check` passaram.
