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

## Continuação G40

Os seletores `visual_for_scene`, `choose_form`, `strategies_for`, o estado
antigo e `VisualStyle.ladder` foram removidos após confirmar que não havia
consumidor de produção. Testes migraram para decisões do `VisualFallbackPlan`
ou renderizadores de baixo nível. `render_form` aceita somente um plano e
deduz seu formato do próprio contrato. Datas, citações, lados de contraste
e termos tipográficos não são extraídos da narração; eles chegam explícitos.

Os testes focados de contratos, mídia, tipografia e gênero passaram: **257**.
A suíte integral no estado final passou: **902 testes em 177,45 s**.
`compileall`, `git diff --check` e busca por referências dos
seletores removidos também passaram.

A redução de 942 para 902 casos vem da substituição de testes que chamavam
heurísticas internas sem uso em produção por testes dos contratos e dos
renderers. Validação real em múltiplos temas continua necessária para fechar a
migração arquitetural completa.

Após G40, uma segunda inspeção M87 mostrou o título da representação aprovada
`black hole event horizon`, mantendo a narração da cena e sem decidir no
renderer. O replay visual foi local; não mediu providers nem aquisição real.

## Continuação G41 — decisão e métrica alinhadas

O caminho tipográfico curto registrava `strategy=form`, mas anotava `card` em
`assets`, `visual_decision.fallback`, eventos e contadores; seu nível também
dizia `synthetic_after_exhaustion`, embora não houvesse busca. G41 faz todos
esses campos derivarem do mesmo `VisualFallbackPlan`: estratégia `form`, nível
`synthetic_without_search` e motivo do plano. O método de métrica agora registra
um asset sintético genérico; o JSON novo emite `synthetic_assets`. Mantive
`synth_diagrams` no artefato como alias de compatibilidade externa.

Validação focada G41: 16 testes de fallback, métricas e seleção passaram.
Suíte integral depois das alterações: **903 testes em 178,91 s**; compileall e
`git diff --check` também passaram. Esta fase muda apenas coerência interna de
auditoria/métricas; não exige uma chamada nova a provider para validar, e não
altera os bytes do asset sintético.
