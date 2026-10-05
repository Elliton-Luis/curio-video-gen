# G67 — evidência imutável da avaliação de candidatos

**Commit:** `833df32 refactor: freeze candidate evaluation evidence`  
**Estado:** implementado e validado; o plano arquitetural integral permanece em andamento.

## Problema

`CandidateEvaluation` era um dataclass `frozen`, mas `evidence` apenas precisava
ser um `Mapping`. O scoring real produz evidência com mappings/listas aninhados,
como `topic_evidence`, `scene_evidence`, termos encontrados e camadas. O objeto
congelado podia manter referências mutáveis ao resultado do scorer, permitindo
que consumidores alterassem fatos já avaliados.

## Contrato após G67

Na entrada, mappings são copiados recursivamente para proxies read-only e
listas/tuplas viram tuplas. Valores escalares são copiados. A avaliação mantém
essa evidência imutável durante o ciclo de seleção.

`to_selection_entry()` é o adapter explícito para o formato de trabalho que a
seleção ainda precisa editar: converte mappings para dicts e tuplas para listas,
retornando cópia independente. Alterar `score_detail` dessa projeção não altera
a evidência avaliada.

## Arquivos e regressão

- `src/curio/stages/media_contracts.py`
- `tests/test_media_contracts.py`

A regressão altera o mapping de origem e conteúdo nested depois da construção,
verifica que a avaliação mantém os fatos originais, tenta alterar mapping/tupla
congelados e modifica a projeção independente para confirmar o isolamento.

## Validação

- Contratos, scoring, seleção, coleta e consumidores visuais: **28 testes passaram**.
- Suíte ampla: **934 passaram, 1 excluído** por HTTP 429 na API real da Wikipédia.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- Nenhuma geração real nesta fase.

Não muda score, gates, queries, provider, seleção, fallback nem formato
persistido. Consulte também o [relatório arquitetural completo](20261005-relatorio-arquitetura-estado-atual.md)
e a [auditoria de pipeline/contratos](../analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md).
