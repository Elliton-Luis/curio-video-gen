# G61 — ownership da auditoria por query visual

**Estado:** implementado no working tree; ainda sem commit.
**Escopo:** acumulação e projeção dos dados de auditoria por `SearchQuery`.

## Problema observado

`visual.py` mantinha fatos da auditoria distribuídos em dicts e sets paralelos:
contagem de resultados, providers, duplicatas, queries abandonadas e queries
não executadas. O mesmo coordenador também montava as linhas de auditoria.
Essa duplicação de estado criava risco de divergência entre execução de busca
e explicação gravada para cada cena.

## Mudança local

`SearchQueryAudit`, em `src/curio/stages/visual_audit.py`, reúne resultados,
duplicatas, rejeições, elegibilidade, providers, resultados por provider,
erros, indisponibilidade e motivo de não execução para uma query. Métodos
explícitos atualizam esses fatos. `search_query_audit_rows()` verifica que o
estado corresponde exatamente às queries do `SearchPlan` e projeta as rows
na ordem desse plano.

`visual.py` continua coordenando requests e alimentando os registros. A
mudança não transfere geração de query, execução de provider, relevância,
seleção ou fallback. Não muda gates, ordenação de providers nem política
editorial. `candidate_audit_rows()` segue projetando os resultados da
avaliação de candidatos.

## Arquivos

- `src/curio/stages/visual.py`
- `src/curio/stages/visual_audit.py`
- `tests/test_visual_audit.py`

Os dois testes existentes de projeção de auditoria de candidatos foram
preservados. Foram adicionados três testes para proveniência e fatos por query,
queries só com duplicatas/fora do orçamento e ausência de estado para query
planejada.

## Validação observada

- Testes focados: 132 passaram.
- Suíte integral: 918 passaram em 180,48 s.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- Geração real: não executada nesta etapa.
- Commit: nenhum; resultado refere-se ao working tree.

## Limite restante

O estado e a projeção da auditoria têm owner explícito, mas o coordenador ainda
combina execução de busca e aquisição com outras responsabilidades. Esta
mudança é um passo de simplificação; não conclui a refatoração do pipeline nem
a validação arquitetural final.
