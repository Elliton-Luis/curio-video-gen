# G97 — separação entre âncora do tópico e evidência da cena

**Commit de código:** `1fd98d4` (`fix: separate topic anchor from scene evidence`)  
**Estado:** fronteira de scoring corrigida e testes verdes; aquisição real ainda
falha no critério de cobertura. Esta fase não encerra o trabalho de mídia.

## Causa confirmada

A geração M87 pós-G96 forneceu esta sequência:

```text
local SemanticScene
→ attach_video_context
→ anchor_local_topic (global_visual_queries = ["M87"])
→ fill_missing_context
→ VisualPlan/SearchPlan
→ topic_anchor_matches + semantic_relevance
```

`fill_missing_context()` adicionava a entidade ao conjunto de
`representations` e, nos dois ramos de cena pertinentes, também substituía
`global_visual_queries` por **todas** as representações. Para cenas M87, o
resultado era `M87`, `black hole`, `galaxy` no campo usado como âncora global.
Como `topic_anchor_matches()` aceita qualquer âncora desse campo, uma imagem
Pixabay com apenas a tag `black hole` passava o gate de tópico M87.

Havia uma segunda confusão de proveniência: `semantic_relevance()` incluía
representações de fonte `entity_context` e `verified_entity_context` como
prova do que a cena retrata. O próprio identificador adicionado para buscar o
tópico podia contar como evidência local da cena — por exemplo, “M87 Kevlar
helmet” encontrava a representação contextual `M87`.

A regressão agora reproduz ambos os limites: “Black hole illustration” não
passa pelo anchor M87; “M87 Kevlar helmet” passa pelo teste isolado da âncora,
mas falha por ausência de evidência local da cena.

## Mudança

`fill_missing_context()` continua acrescentando representações contextuais e
aliases com proveniência, porém não reescreve `global_visual_queries`. A âncora
criada por `anchor_local_topic()` permanece a fonte do gate global.

Na pontuação, representações adicionadas por `entity_context` e
`verified_entity_context` continuam disponíveis para busca e auditoria, mas não
são contadas como evidência do que a cena mostra. Representações que vieram do
planejamento da cena continuam avaliadas normalmente. Sem mudanças de threshold,
providers, cache, política de reuso ou fallback.

## Arquivos e contratos tocados

- `src/curio/stages/visual_context.py`: enrichment de entidade não promove
  representações a âncoras globais.
- `src/curio/stages/scoring.py`: o score de cena não trata âncoras de entidade
  como representação local.
- `tests/test_visual_topic_anchor.py`: regressão integrada com M87, imagem
  genérica de buraco negro e homônimo “M87 Kevlar helmet”.

O contrato que emerge é: `global_visual_queries` prova somente o assunto global
que o planner já ancorou; representação produzida para a cena prova o que a
cena retrata; uma representação inserida apenas para contexto de entidade não
substitui nenhuma dessas provas.

## Validação

- Testes focados de contexto, scoring, enriquecimento e query concepts: **70
  passaram**.
- Suíte completa após o patch: **1021 passaram em 185,79 s**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- Commit de código: `1fd98d4`.

## Replay real pós-G97

Execução real `from-script` do roteiro M87, sem chaves LLM, diretórios isolados,
sem cache de mídia prévio. A afirmação factual de 2019 permaneceu sem grounding.

| Medida | Resultado |
|---|---:|
| Cenas | 4 |
| Cenas com mídia real | 1 |
| Cenas sintéticas | 3 |
| Assets reais selecionados | 2, ambos na cena 1 |
| Assets reais únicos por ID/hash | 2 |
| Reusos de asset | 0 |
| Queries lógicas executadas | 16 (4 por cena) |
| Candidatos da auditoria | 80 |
| Mantidos na shortlist | 6 |
| Rejeições | 68 por âncora global; 8 por regra técnica |
| Downloads / cache hits | 3 / 3 |
| Bytes baixados | 410.087 B |
| Retries / timeouts | 0 / 0 |
| Tempo de mídia / execução | 19,07 s / 70,75 s |

Requests por provider: NASA 5 (4 search + 1 metadata), Pixabay 4, Wikimedia
4, Unsplash 4, Met 16 e AIC 16. Met respondeu HTTP 410 e AIC HTTP 500; Pexels
não tinha chave e foi omitido. O total media foi 80 candidatos, dos quais 6
mantidos e 76 rejeitados; os 3 downloads incluem uma imagem Spitzer que falhou
na validação de resolução/legibilidade. O vídeo final contém a imagem do EHT
em duas entradas com IDs distintos, visualmente quase iguais.

### Auditoria por cena

| Cena | Representações | Queries executadas | Resultado e motivo |
|---|---|---|---|
| 1 — M87 e buraco negro supermassivo | M87 (contexto), black hole, galaxy | `black hole M87`; variantes `black hole painting M87`, `black hole engraving M87`, `black hole artifact M87` | Wikimedia `102736603`, imagem polarizada do EHT, score 100 por M87 + black hole no título/descrição. Também selecionou `170480594`, essencialmente a mesma imagem. `galaxy M87` e variantes não executadas por orçamento. |
| 2 — rede EHT e imagem de 2019 da sombra | M87 (contexto), black hole, event horizon | As mesmas quatro consultas de black hole | Sintético “spotlight — black hole”. O crop “Black hole - Messier 87” falhou a âncora textual M87; a representação `event horizon` e suas variantes não foram consultadas por `scene_candidate_budget`. |
| 3 — disco de acreção, campos magnéticos e jato | M87 (contexto), black hole, galaxy | As mesmas quatro consultas de black hole | Sintético “spotlight — galaxy”. O candidato “M87 jet” foi rejeitado por ausência de evidência local: o planner local perdeu `accretion disk`, `magnetic fields` e `jet`. As queries `galaxy` também ficaram sem execução. |
| 4 — lente gravitacional | M87 (contexto), black hole | As mesmas quatro consultas de black hole | Sintético “Card — black hole”. A representação `gravitational lensing`, ausente do plano local, não foi produzida; tópico e fallback `night sky`/`stars` não foram consultados. |

Inspecionei visualmente ambos os assets Wikimedia selecionados: têm composição
quase idêntica. Portanto 2 assets por ID/hash não equivalem a duas imagens
editorialmente distintas.

## Gargalo seguinte confirmado

O replay permite apontar uma parada anterior ao scoring: em
`SceneCandidateCollector.collect()`, `max_candidates=20` conta os resultados
que passam pelo gate técnico, antes de `evaluate_specific()` aplicar relevância
de cena/tópico. Após esse teto, queries seguintes recebem
`unexecuted_reason="scene_candidate_budget"`. Como consequência, o sistema
usa até 20 slots com resultados tecnicamente elegíveis mas semanticamente
rejeitados e pode sintetizar sem consultar a próxima representação concreta.

Esse comportamento explica as queries ausentes por cena nesta execução. A
correção seguinte precisa manter orçamento explícito e evitar busca ilimitada,
mas não pode tratar candidatos que serão rejeitados editorialmente como prova
de que a árvore de consultas se esgotou. O ownership de aquisição, avaliação e
seleção deve continuar separado. A fase seguinte é G98: tornar a continuação
condicional ao resultado semântico e à evidência de query, com regressão que
prove que `event horizon`/representação seguinte é executada após apenas
candidatos contextualmente irrelevantes.

## Limites e estado do plano

G97 removeu um vazamento de contexto que permitia imagens genéricas dominarem
um tópico. O replay mostra o custo de exigir prova correta antes de haver um
plano de cena forte e de o coletor interromper a busca cedo: cobertura real
caiu para 1/4. Isso é falha de aquisição, não sucesso de relevância, e não será
contabilizado como conclusão.

Pendências já evidentes para fases seguintes:

1. G98 — parar o orçamento técnico bruto de encerrar a exploração antes da
   avaliação semântica/da representação seguinte.
2. G99 — preservar `accretion disk`, `jet`, `gravitational lensing` e outros
   conceitos explícitos no contrato local sem criar léxico gigante.
3. Planejar aliases canônicos com proveniência para equivalências como `M87` /
   `Messier 87`, sem confiar em substring nem em tradução inventada.
4. Reexecutar M87 e dois domínios diferentes, comparar assets únicos,
   repetição perceptual, sintéticos, cobertura da busca e tempo.

O estado integral do plano e do restante do sistema está no
[relatório consolidado](20261005-relatorio-completo-estado-do-trabalho.md).
