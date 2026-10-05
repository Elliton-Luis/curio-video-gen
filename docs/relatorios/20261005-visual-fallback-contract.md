# G39 — plano explícito de fallback visual

## Causa arquitetural

O caminho de aquisição chamava `visuals.visual_for_scene`, que combinava
política, inferência sobre campos incompletos da cena e render. Uma rota
paralela detectava `mechanistic` e construía um diagrama térmico usando as
queries de busca como rótulo. `visual_entities` e `context` podiam ser tratados
como se fossem etapas ordenadas, embora descrevessem somente conceitos. Isso
fazia o fallback rever o significado e a intenção visual depois do plano de
busca.

## Mudança

`build_visual_fallback_plan(VisualPlan, narration, genre, state)` agora resolve
assunto, proveniência, estratégia, forma, texto e motivo. `render_fallback_plan`
apenas despacha o plano para o renderer de baixo nível. O plano é registrado na
auditoria da cena. Cenas tipográficas e fallback após busca esgotada usam a
mesma fronteira.

`visual_steps` foi adicionado aos contratos de cena/serialização. Só uma lista
explicitamente declarada nessa ordem permite diagrama. Representações, entidades
e contexto não são promovidos a uma sequência causal. A rota de tira de teste
que construía o assunto a partir das queries foi removida do fluxo de mídia.
O cache de imagem sintética continua identificando todo texto visível.

## Compatibilidade e risco

CLI, TUI, pipeline, providers, seleção de mídia e cache de bytes permanecem sem
alteração. O comportamento editorial muda apenas onde o mecanismo não declara
etapas: a cena recebe uma forma tipográfica contextual em vez de um diagrama
inferido. Capítulos antigos carregam `visual_steps=[]`, valor que conserva o
contrato sem inventar etapas.

## Validação

- Testes focados de fallback, diretor, contratos e tipografia: **195 passaram**.
- Suíte integral no estado final commitado: **942 passaram em 179,13 s**.
- `compileall` e `git diff --check`: aprovados.
- Render sintético M87 inspecionado manualmente: o título usa `M87*`, a legenda
  reproduz a narração e o layout não afirma uma cadeia causal. Esta é uma
  validação de fallback isolada, não uma nova aquisição real com providers.

## Pendências arquiteturais

Ainda há consumidores internos de `visual_for_scene`, `choose_form` e
`strategies_for` nos testes de layout/estratégia. O caminho de produção de
aquisição já usa `VisualFallbackPlan`; a remoção dessas APIs deve ocorrer numa
fase própria depois de migrar os testes de comportamento para contratos e
renderers. A validação real em múltiplos temas continua sendo necessária para
fechar a migração arquitetural completa.
