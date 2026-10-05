# G58 — ownership do reuso entre cenas — 2026-10-05

## Problema

`visual.py` ainda continha a resolução tardia de reuso cross-scene e a
anotação de assets repetidos entre cenas, apesar de `media_selection.py` ser o
módulo responsável pela política de seleção e reuso. Isso deixava uma decisão
de seleção escondida no coordenador do pipeline visual.

## Mudança

- Movidas `_resolve_reuse_multi` e `_annotate_reuse` para
  `media_selection.resolve_cross_scene_reuse` e `media_selection.annotate_reuse`.
- `visual.py` agora apenas chama as funções durante a composição do resultado.
- Testes migrados para chamar o módulo dono; nenhum shim privado foi mantido.
- Identidade continua usando a função canônica de `media.identity`.
- Seleção ainda exige evidência de tópico e cena; prioridade, justificativas,
  aviso em stderr e campos de saída permanecem iguais.

## Contrato e limite

Esta foi uma transferência de ownership, sem mudança da política editorial ou
do schema persistido. `media_selection` atualiza `SelectionDecision` nos casos
de reuso. A validação de evidência semântica ainda chama
`scoring.semantic_relevance`; unificar essa avaliação com o fluxo tipado de
`CandidateEvaluation` é uma questão arquitetural separada, não alterada nesta
fase.

## Arquivos

- Código: `src/curio/stages/visual.py` e
  `src/curio/stages/media_selection.py`.
- Testes: `tests/test_media_diag.py` e `tests/test_media_selection.py`.
- Documentação: README, índice de docs, auditoria arquitetural e relatório de
  estado completo.

## Verificação

- Testes focados de seleção, reuso, métricas e standby: **60 passaram**.
- Suíte completa: **913 passaram em 210,52 s**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

A primeira execução focada apontou um teste ainda acoplado ao helper privado
de `visual.py`; o teste foi migrado e a nova execução focada e integral passou.
