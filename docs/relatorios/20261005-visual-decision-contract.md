# G63 — contrato da decisão visual persistida

**Commit:** `73f6e6c` (`refactor: validate visual decision audit`)

## Causa

`visual_decision` tinha `SelectionDecision` tipada dentro de um dict, mas o
envelope ao redor era montado e alterado por caminhos diferentes. Geração
normal, fallback tipográfico e mídia manual produziam estruturas paralelas.
Reuso cross-scene e troca manual reescreviam diretamente campos desse payload.
Assim, o resultado de mídia validava a seleção, mas não o audit associado.

## Mudança

`VisualDecision` em `src/curio/media/visual_decision.py` envolve a seleção
tipada, valida tipos dos campos conhecidos (`topic`, planos, listas de
queries/candidatos, `selected`, `fallback` e estado de busca) e serializa no
schema de projeto existente. Campos legados desconhecidos e campos conhecidos
omitidos são preservados; `to_dict()` faz a projeção externa.

`SceneMediaSelection.visual_audit` agora é `VisualDecision`. O parser valida o
envelope uma vez e obtém a seleção pelo contrato. Updates de reuse cross-scene
usam `with_selection()` em vez de alterar o dict persistido. O swap manual e os
produtores normal, tipográfico e manual também usam o contrato; métricas
convertem explicitamente para dict no limite de saída.

## Arquivos e testes

- `src/curio/media/visual_decision.py`
- `src/curio/media/selection_result.py`
- `src/curio/pipeline_media.py`
- `src/curio/pipeline_visual.py`
- `src/curio/stages/media_selection.py`
- `src/curio/stages/visual.py`
- `tests/test_visual_decision.py`

Os testes cobrem round-trip com extension legado, atualização sem mutar a
instância anterior, tipos de campos conhecidos e seleção obrigatória. A suíte
focada dos caminhos integrados teve **124 aprovações**. A suíte ampla teve
**929 aprovações, com `test_standby_sem_imagens` excluído**. Esse caso faz
request real à Wikipédia e recebeu HTTP 429 na tentativa. `compileall` e
`git diff --check` passaram; a primeira tentativa do lote também passou nos
outros testes antes dessa falha externa. Não houve geração real de vídeo.

## Compatibilidade e limites

O formato salvo permanece JSON. Campos desconhecidos sobrevivem round-trip e
o renderer/CLI continuam recebendo dicts. O contrato valida o envelope e a
seleção, mas os rows individuais de queries e candidatos continuam mappings;
essa dívida está registrada como limite, não como migração concluída.
