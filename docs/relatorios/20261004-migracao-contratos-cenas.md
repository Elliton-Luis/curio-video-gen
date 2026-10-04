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

## Próxima fronteira

O pipeline ainda cria `Chapter` dentro de enrichment e os consumidores de
timeline, áudio, subtitles, render e ferramentas ainda leem `chapters.json`.
A migração continua por consumidor, preservando o formato externo até esses
limites usarem contratos tipados próprios. Cache de aquisição de mídia permanece
independente do cache semântico e não escolhe mídia por si só.
