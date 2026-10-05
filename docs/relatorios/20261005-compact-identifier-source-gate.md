# G96 — identidade contextual para identificadores compactos

**Commit:** `0cdf81a` (`fix: disambiguate compact entity identifiers`)  
**Estado:** implementação commitada; regressão coberta por teste; geração real pós-correção executada. O gate de entidade melhorou, mas a geração revelou uma falha independente de ancoragem/qualidade visual que permanece aberta.

## Causa confirmada

O artefato da geração M87 em `/tmp/curio-f15-science-output/f15-m87-metrics/sources/research.json` registra o tópico `M87 black hole Event Horizon Telescope`, mas o alvo produzido era `M87`, com `ambiguous=false`, sem aliases e sem discriminantes. O resolver heurístico escolhia o primeiro bloco capitalizado e descartava o contexto. Como `TargetEntity.mentions_name()` faz busca por substring no título e no trecho integral, `Capacete M87` e `Zastava M87` passaram pelo gate de `source_verdict()`.

Há também uma bifurcação anterior no resolver: quando todo o restante do pedido está em minúsculas, a primeira cláusula podia classificar uma frase iniciada por `H1N1`/`B52` como tópico livre antes de tentar reconhecer o identificador. Os testes adicionados reproduzem esse caminho.

## Mudança e contrato

`stages/entity.py` agora reconhece designações alfanuméricas compactas antes do ramo de tópico livre, preserva grupos de contexto que já aparecem no pedido e marca o alvo como ambíguo. Para esse formato, discriminantes vindos do LLM não substituem a evidência do pedido: só os termos contextuais explícitos na entrada autorizam o gate. O planner pode continuar enriquecendo outros campos; os mesmos valores resultantes seguem pelo mesmo `TargetEntity` e pelo mesmo `source_verdict()`.

Um identificador compacto sem contexto fica sem fundamento, em vez de aceitar qualquer título que contenha o código. Uma fonte canônica pode provar a equivalência se declarar o código como alias no começo do próprio texto, por exemplo `Messier 87 (M87; ...)`, e o trecho antes dos parênteses corresponder ao título. `Zastava M87` e `Capacete M87` não satisfazem essa regra. Nenhum threshold foi reduzido, e nenhum tema foi codificado individualmente.

## Evidência de regressão

O gate foi aplicado às três fontes arquivadas da execução M87, sem rede:

| Fonte | Resultado após G96 |
|---|---|
| `Messier 87` — o trecho declara `Messier 87 (M87; ...)` | Aceita por alias canônico explícito |
| `Capacete M87` | Rejeitada: sem discriminante/contexto correspondente |
| `Zastava M87` | Rejeitada: sem discriminante/contexto correspondente |

Os testes também cobrem `H1N1 influenza virus` e `B52 bomber aircraft`, a resolução local e o caminho LLM retornando discriminante vazio ou espúrio. Um teste de integração simula a coleta dos três resultados e confirma que somente a fonte canônica passa.

## Arquivos e validação

- `src/curio/stages/entity.py` — owner da resolução de entidade e do gate de identidade das fontes.
- `tests/test_entity_relevance.py` — regressões de resolução, aceitação e rejeição no fluxo de pesquisa.

Validações na revisão commitada:

- testes focados: **44 passaram** (`test_entity_relevance.py`, `test_research.py`, `test_pipeline_research.py`);
- suíte completa: **1020 passaram em 200,73 s**;
- `python -m compileall -q src tests`: passou;
- `git diff --check`: passou.

## Geração real pós-G96

A geração `g96-m87-context-gate` foi executada de `from-script`, sem chaves de
LLM, com providers reais e diretórios isolados em `/tmp`. O roteiro veio do
artefato local M87. A execução terminou sem erro:

| Medida | Resultado |
|---|---:|
| Cenas | 4 |
| Cenas com mídia real | 4 |
| Assets selecionados | 12 |
| Assets únicos por ID/hash | 12 |
| Reusos | 0 |
| Sintéticos | 0 |
| Queries lógicas | 16 |
| Resultados normalizados | 37 |
| Candidatos avaliados | 88 |
| Duplicatas | 52 |
| Rejeições duras | 8 |
| Rejeições de score | 28 |
| Downloads / bytes | 13 / 3.869.487 B |
| Cache hits | 6 |
| Retries / timeouts | 0 / 0 |
| Tempo da mídia / execução | 22,28 s / 80,21 s |

Providers consultados: NASA (4 buscas e 1 request de metadata), Pixabay (4),
Unsplash (4), Wikimedia (4), Met (16, todas HTTP 410) e AIC (16, todas HTTP
500). Pexels não foi consultado porque não havia chave. O total de requests
por provider reflete execução de queries por fonte; as 16 são queries lógicas,
não o número agregado de tentativas em todos os adapters.

Na pesquisa, `sources/research.json` preservou o alvo M87, os discriminantes
`black hole` e `Event Horizon Telescope`, e a ambiguidade. Três fontes
astronômicas foram aceitas, 51 rejeitadas; não foram aceitos capacete ou rifle
homônimos. A lista aceita inclui material sobre Event Horizon Telescope, o
algoritmo CLEAN e Peter J. Young. A execução não fundamentou a afirmação de
2019 no roteiro.

### Seleções por cena

| Cena | Representações registradas | Queries/evidência dominante | Seleção vencedora | Motivo registrado e ressalva |
|---|---|---|---|---|
| 1 — sistema M87 e buraco negro supermassivo | M87, black hole, galaxy | `black hole M87` e variantes; metadados mencionavam M87 e black hole | Wikimedia `102736603`, imagem polarimétrica do EHT | Score 100, `representation_or_media_variant`; corresponde diretamente ao EHT/M87. |
| 2 — imagem de 2019 da sombra | M87, black hole, event horizon | As mesmas âncoras `black hole M87`; evidência de M87 e black hole | Wikimedia `77925953`, crop de “Black hole - Messier 87” | Score 100; imagem válida, mas composição quase igual à cena 1. |
| 3 — disco de acreção, campos magnéticos e jato | M87, black hole, galaxy | Variantes `black hole M87`; o vencedor só tinha evidência genérica de black hole | Pixabay `2469325` e dois outros resultados genéricos Pixabay | Score 100 apesar de `topic_evidence` vazio no candidato vencedor; as imagens não estabelecem disco/jato de M87. |
| 4 — lente gravitacional | M87, black hole | Incluiu `black hole painting M87`; evidência genérica “black hole” | Unsplash, “An image of a black hole in the sky”, além de alternativas abstratas | Score 100; tema geral, sem evidência de M87 ou lente gravitacional. |

`visual_intent_structured` nas cenas dizia “Topic-level visual for M87; scene
representation unresolved”. As queries globais persistidas incluíram a
representação global e os termos locais de cada cena (por exemplo, M87, black
hole, galaxy). A inspeção do contact sheet com os 12 assets mostrou que IDs e
hashes únicos não evitam composições quase repetidas, e que quatro cenas com
mídia real não equivalem a quatro decisões editoriais específicas.

## Falha visual ainda aberta

O resultado pós-G96 confirma o reparo de homônimos, mas não satisfaz a qualidade
visual. A execução sugere que o candidato pode herdar relevância temática
apenas por corresponder a representação local: houve vencedores com evidência
de tópico vazia, ainda assim score 100. A intenção local também foi reduzida a
representações genéricas de M87/buraco negro/galáxia, sem preservar
`accretion disk`, `magnetic fields`, `jet` ou `gravitational lensing` como
conceitos pesquisáveis.

O próximo diagnóstico previsto era rastrear o caminho real:

```text
local semantic scene → attach_video_context → anchor_local_topic
→ fill_missing_context → VisualPlan/global_visual_queries
→ topic_anchor_matches + semantic_relevance → seleção
```

Uma hipótese específica a confirmar é que `fill_missing_context()` promove
representações locais ao campo `global_visual_queries` ao inserir âncora
contextual. Outra regra a inspecionar é se `semantic_relevance()` transforma
evidência apenas de cena em correspondência de tópico. Essa etapa de inspeção
não foi concluída: são hipóteses de trabalho, não causas comprovadas. Nenhum
patch para essa regressão foi iniciado. A instrução de parada do usuário foi
respeitada; o relatório documenta o ponto exato de retomada.

## Limitações

A aplicação offline às fontes arquivadas e a geração real confirmam a rejeição
dos falsos homônimos para este caso. A correspondência de contexto textual
continua literal após normalização; não traduz descritores. Fontes sem contexto
no trecho e sem declaração explícita de alias permanecem rejeitadas, mesmo que
conhecimento externo as considere corretas. A qualidade factual do roteiro
segue limitada pela afirmação de 2019 sem grounding. A qualidade visual por
cena requer investigação separada conforme acima.
