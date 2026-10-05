# G86 — política explícita da próxima tier visual

**Commit:** `4b0b4e7 refactor: centralize visual fallback order`  
**Problema:** `visual.py` escolhia a próxima ação de fallback por condições
espalhadas entre busca contextual, visual sintético e reuso. A ordem editorial
não tinha um owner puro e testável.  
**Estado:** implementado e validado.

## Mudança

`media_selection.py` agora possui `next_selection_fallback()`, função pura que
retorna `SelectionFallbackAction`: `CONTEXTUAL_SEARCH`, `SYNTHETIC`, `REUSE`,
`NO_ASSET` ou `COMPLETE`. O selector define que novos resultados contextuais
precedem o sintético local; reuso só pode ocorrer depois de uma tentativa
sintética; seleção real parcial é mantida sem preenchimento por repetição ou
synthetic.

`visual.py` continua dono da execução: coleta e avaliação ficam nos mesmos
owners, aquisição permanece técnica e o render não foi alterado. O coordenador
consulta a política e executa a ação retornada. Gates, thresholds, providers,
queries, cache e regras de aquisição/reuso permanecem inalterados.

## Testes e validação

Seis casos tabulares cobrem busca contextual, sintético antes de reuso, ausência
de mídia, preservação de cobertura real parcial e conclusão ao atingir a
quantidade solicitada. Os testes direcionados de seleção, diretor, waterfall e
fallback passaram: **89 testes**. A suíte completa passou com **986 testes em
175,32 s**. Após remover um parâmetro opcional não usado, os direcionados
passaram novamente: **89 testes em 0,57 s**; `compileall` e `git diff --check`
passaram.

## Limites

G86 centraliza a decisão sobre a próxima tier, não extrai todo o fluxo de
seleção da função coordenadora. `visual.py` ainda coordena busca, avaliação,
tentativas, montagem da auditoria e `VisualDecision`. As camadas são explícitas
por módulos, mas ainda não convergem para um único `SelectionPlan` de execução
por cena. Essa parte requer análise e migração própria; não foi implicitamente
resolvida por G86.
