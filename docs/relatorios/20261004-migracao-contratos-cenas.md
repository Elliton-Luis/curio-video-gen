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

## Próxima fronteira

O pipeline ainda projeta `Chapter` para consumers de subtitles, render e
ferramentas que leem `chapters.json`. A migração continua por consumidor,
preservando o formato externo até esses limites usarem contratos tipados
próprios. Cache de aquisição de mídia permanece independente do cache
semântico e não escolhe mídia por si só.

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
