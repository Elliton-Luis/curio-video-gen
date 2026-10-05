# G72 — manter seleção tipada até a projeção

**Commit:** `ec61c65` (`refactor: keep selected media typed to serialization`)
**Estado:** concluída; a aquisição pré-seleção permanece em `visual.py`.

## Problema

Após G71, `visual.py` ainda guardava os assets aprovados, sintéticos e
reutilizados em `picked: list[dict]`. O tipo `SelectedAsset` era criado em uma
cópia temporária apenas para `make_selection_decision()`. Isso deixava o
resultado escolhido mutável durante o restante da composição e duplicava a
projeção entre candidato e decisão.

## Mudança

Cada asset é convertido para `SelectedAsset` no momento em que passa a integrar
o resultado da cena: após aquisição e gates, após render sintético ou após o
fallback tardio de reuso. `picked` permanece tipado durante a decisão, cálculo
do nível/razão de fallback, detecção de sintético e escolha da query vencedora.

A projeção `to_dict()` ocorre na fronteira necessária para construir linhas de
auditoria de candidatos e no objeto de retorno compatível com o schema de
`media.json`. Ordem, campos persistidos, fallback, métricas, seleção e política
de reuse continuam iguais.

## Arquivos

- `src/curio/stages/visual.py`

## Validação

- **99 testes focados** de seleção, direção visual, auditoria, aquisição e
  integração de pipeline passaram.
- Suíte ampla: **940 passaram, 1 deselecionado** após HTTP 429 da API real da
  Wikipédia, em **179,23 s**.
- `python -m compileall -q src tests` e `git diff --check` passaram.
- Sem geração real ou inspeção visual nesta fase.

## Limite

Antes de ser selecionado, cada candidato ainda é representado por um dict
transitório no coordenador. O loop pré-seleção reúne download/cache, validação
técnica, hash, reason de rejeição, ordem e uso/reuso; essas transições seguem
sem um resultado tipado único e `visual.py` ainda é owner de sua composição.
A próxima fase deve modelar os outcomes por candidato antes de mover qualquer
política para outro módulo.
