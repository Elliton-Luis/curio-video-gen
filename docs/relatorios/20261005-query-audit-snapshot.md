# G65 — snapshot imutável da auditoria por query

**Commit:** `28e4799 refactor: freeze per-query audit snapshots`  
**Estado:** implementado e validado; demais fases da refatoração permanecem em andamento.

## Causa

`SceneCandidateCollection` era um dataclass congelado e expunha sua tabela de
auditoria por `MappingProxyType`, mas os valores eram instâncias mutáveis de
`SearchQueryAudit`. Assim, a coleção parecia imutável enquanto os fatos dentro
dela podiam ser reescritos depois da aquisição. Além disso, sua construção
direta podia reter um mapping do chamador que mudaria posteriormente.

## Contrato após G65

`QueryAuditAccumulator` é o estado mutável privado à coleta: recebe contagens,
erros, duplicatas, elegibilidade e queries não executadas. Seu método
`snapshot()` emite `SearchQueryAudit`, dataclass frozen com campos escalares e
tuplas imutáveis para providers e resultados/erros por provider.

`SceneCandidateCollection.__post_init__` valida os snapshots e cria sua própria
cópia `MappingProxyType`, mesmo quando recebe um mapping mutável externo. O
projetor `search_query_audit_rows()` exige snapshots e segue produzindo o
formato de auditoria JSON anterior. Acumulador e contrato de saída têm agora
responsabilidades diferentes e verificáveis.

## Arquivos

- `src/curio/stages/visual_audit.py`
- `src/curio/stages/scene_candidate_search.py`
- `tests/test_visual_audit.py`
- `tests/test_scene_candidate_search.py`

As regressões verificam que snapshots não mudam quando o acumulador recebe mais
resultados, que atributos/provider tuples não podem ser alterados, que a tabela
é copiada e congelada na construção e que a projeção preserva o schema JSON.

## Validação

- Foco em auditoria, coleta, pipeline visual e fontes de mídia: **21 testes passaram**.
- Suíte ampla: **932 passaram, 1 excluído**, `test_standby_sem_imagens`, que
  depende de request à API da Wikipédia e respondeu HTTP 429.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- Nenhuma geração real ou benchmark de aquisição nesta fase.

G65 altera somente a integridade do contrato entre aquisição e consumidores.
Não altera query, provider, gate, scoring, seleção, fallback ou formato salvo.
O [relatório arquitetural completo](20261005-relatorio-arquitetura-estado-atual.md)
e a [auditoria de pipeline e contratos](../analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md)
registram o estado geral e as pendências.
