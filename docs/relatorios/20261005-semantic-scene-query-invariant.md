# G49 — invariável entre representações e queries — 2026-10-05

## Problema

`SemanticScene.__post_init__` aceitava mappings de representation e fabricava
representações a partir de `visual_queries`. Um produtor podia omitir o dado
canônico ou enviar os campos em desacordo sem erro; consumidores recebiam um
objeto aparentemente válido, com proveniência inventada no meio do pipeline.

## Mudança

- O contrato runtime exige `VisualRepresentation` e rejeita `visual_queries`
  sem representations ou que não sejam exatamente o espelho ordenado delas.
- O produtor LLM normaliza os objetos do payload na fronteira de produção e
  registra `llm_visual_search_term` quando só vieram termos de busca. O planner
  local materializa representações explicitamente.
- A reparação que une cenas mantém o espelho alinhado às representações unidas.
- `SemanticScene.from_dict` preserva a leitura dos caches query-only antigos,
  convertendo-os explicitamente com `source=declared_scene_query`; se o cache
  trouxer ambos os campos e eles divergirem, a leitura falha.
- Fixtures internas foram migradas para construir o contrato canônico, não
  depender da conversão silenciosa.

## Verificação

Os testes focados de contrato, planners, visual context, fallback e reparo de
cenas passaram (**121**). A suíte completa passou (**908 testes em 195,28 s**).
`python -m compileall -q src tests` e `git diff --check` também passaram.
Uma primeira execução integral, antes da migração de todos os produtores e
fixtures, encontrou 10 falhas em consumidores que ainda entregavam mappings ou
espelhos inconsistentes; esses caminhos foram migrados antes da execução verde.

## Efeito e limite

A construção interna agora acusa divergência no ponto em que nasce, em vez de
repará-la silenciosamente. A compatibilidade query-only permanece restrita ao
loader de JSON legado. A proveniência `llm_visual_search_term` identifica a
origem do termo, mas não certifica sua qualidade semântica; validação de
representações fracas continua pertencendo à fase de planejamento visual.
