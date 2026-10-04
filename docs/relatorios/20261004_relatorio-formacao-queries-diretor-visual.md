# Relatório: formação de queries e aquisição histórica

Data: 2026-10-04  
Execução real: `history/20261004_visual-query-audit-v5`  
Roteiro: `/tmp/curio-otomano-diversidade.txt`  
Auditoria por cena: `output/history/20261004_visual-query-audit-v5/media/media.json`; execução e contexto: `metadata.json` e `logs/run-20261004-133221-225282.jsonl`.

## Causa encontrada

O fluxo local ainda promovia palavras da narração a queries sem exigir que fossem conceitos visuais. O léxico PT→EN compartilhado transformava “ouro” em `gold`; verbs e ordinais como `formavam`/`primeira` podiam sobreviver em listas de query locais. Quando faltava classificação do gênero, `_generic_queries()` também podia aplicar o conjunto científico (`laboratory`, `microscope`) a cenas históricas. Acrescentar o tópico depois não tornava essas âncoras semanticamente válidas.

O evento era inferido a partir de nomes próprios da frase, sem validar verbo/conectivo, e a cena local não registrava por que descartava termos ruins. O ponto causal está entre narração→intenção/representação e query, antes de providers: a busca recebia tokens, não objetos de acervo.

Agora o fluxo local preserva frases de entidade/evento e classes concretas curtas, valida representações e registra descartes. Não injeta vocabulário científico sem sinal explícito. Queries de representação são ancoradas no tópico/alias confirmado, variam por tipo visual e mantêm a prioridade de providers adequada ao tipo histórico. Candidato fraco, duplicado ou já usado não encerra a exploração. A instrumentação distingue provider error, provider ausente, query não executada, duplicatas e busca totalmente percorrida. Nenhum threshold foi reduzido.

Não traduzimos nomes próprios com dicionário de palavras soltas. Quando não há alias confirmado em contexto/metadata, mantemos o nome da cena e o tópico; essa limitação aparece em nomes locais como `Mehmed Segundo` e deve ser resolvida por metadata de entidade, não por tradução adivinhada.

## Comparação

| Estado | Cenas reais | Assets únicos | Reusos | Sintéticos |
|---|---:|---:|---:|---:|
| Regressão de repetição anterior | 10/11 | 2 | 9 | — |
| Após prevenção de reuso, antes desta correção | 5/11 | 5 | 0 | 6 |
| Execução real desta correção | 9/11 | 9 | 0 | 2 |

Execução de 11 cenas, razão de assets únicos por assets reais de 100%, nenhum reuso e duas cenas sintéticas (#2 e #6). A unicidade foi confirmada por SHA-256 dos arquivos locais. Nove cenas receberam mídia real, mas isso não significa nove escolhas específicas adequadas: a inspeção visual encontrou falsos sucessos em #5, #8 e #9.

## Queries, providers e vencedores por cena

Os dados completos estão em `media.json`, incluindo representações, queries geradas/executadas, provider de cada query, resultados, erros, rejeições, candidatos e motivo de decisão. O resumo abaixo registra a trilha antes de desistir. `not_consulted_after_fresh_match` indica parada após asset novo elegível; não significa que aquela query tenha sido executada.

| Cena | Representações | Queries consultadas / planejadas | Providers | Vencedor e avaliação |
|---:|---|---:|---|---|
| 1 | Anatólia (entity), Império Otomano (empire) | 2/8 | Met, AIC, Wikimedia, NASA | Mapa do Império Otomano 1451–1481; contextual e visualmente pertinente. |
| 2 | Dardanelos, Galípoli | 8/8 | Met, AIC, Wikimedia, NASA | Sintético. A frota russa nos Dardanelos foi rejeitada por conflito de tópico; uma query duplicada foi deduplicada e a árvore avançou para Galípoli. Erros em Met/AIC e mídia instável de Wikimedia impedem declarar ausência. |
| 3 | Battle of Kosovo, Kosovo | 6/8 | Met, AIC, Wikimedia, NASA | Plano da Batalha do Kosovo; evento específico. Wikimedia oscilou durante as primeiras queries. |
| 4 | Siege of Constantinople, Mehmed Segundo | 2/8 | Met, AIC, Wikimedia, NASA | Maquete do cerco de Constantinopla; representação do evento. Pintura de Jean Le Tavernier foi rejeitada por falta de evidência do tópico. |
| 5 | Mehmed Segundo, Constantinople | 8/8 | Met, AIC, Wikimedia, NASA | Imagem orbital moderna de Istambul; falso sucesso visual apesar de topicalidade. Retrato de Bellini foi rejeitado pelo gate de tópico. |
| 6 | Selim Primeiro, Marj Dabiq | 8/8 | Met, AIC, Wikimedia, NASA | Sintético após 8 queries; zero resultados específicos. Erros/timeout de providers significam busca incompleta. |
| 7 | Suleiman Magnífico, Mohács | 8/8 | Met, AIC, Wikimedia, NASA | Miniatura turca da Batalha de Mohács; boa correspondência ao evento. Retratos de Suleiman foram rejeitados como inadequados ao evento narrado. |
| 8 | janízaros (army) | 7/8 | Met, AIC, Wikimedia, NASA | Cronologia de bandeiras otomanas; topical, mas não representa janízaros. Imagens de Rustem Pasha e mapas genéricos foram rejeitados por mismatch de tópico. |
| 9 | Battle of Preveza, Mediterrâneo | 1/8 | Met, AIC, Wikimedia, NASA | Colagem “Ottoman-Spanish War”; relação ampla, não comprova visualmente Preveza. Deve ser tratada como degradada. |
| 10 | Nenhuma representação local concreta | 2/8 | Met, AIC, Wikimedia, NASA | Mapa do Império Otomano c. 1897; contextual, não específico à cena. |
| 11 | Império Otomano, Primeira Guerra Mundial | 1/8 | Met, AIC, Wikimedia, NASA | Mapa do Império Otomano na Ásia em 1914; relação histórica pertinente, mas ampla. |

Queries-chave registradas literalmente em `media.json`: cena 2 percorreu `Dardanelos Ottoman Empire`, variante com `Império Otomano`, `painting`, `engraving`, `artifact` e depois `Galípoli` com contexto; cena 6 tentou `Selim Primeiro` com contexto, `portrait`, `bust`, `painting`, `engraving` e `Marj Dabiq`; cena 7 avançou de retrato/representações de Suleiman para `Mohács Ottoman Empire`; cena 8 tentou `janízaros` com tópico, `army`, `uniform`, `cavalry`, `military engraving` e fallback do tópico. O arquivo da auditoria mostra por query os aliases usados e erros/resultados de cada provider.

Na execução, Met respondeu HTTP 410 e AIC HTTP 500. Wikimedia apresentou timeouts e erros HTTP intermitentes. Pixabay, Pexels e Unsplash não estavam habilitados por falta de chaves. NASA participou da busca histórica e venceu indevidamente a cena 5 com uma imagem de satélite moderna. Portanto as cenas sintéticas não provam inexistência de imagens nos acervos.

## Inspeção visual e trabalho restante

Inspecionei os nove vencedores reais em `/tmp/curio-ottoman-v5.jpg`. O mapa de 1451–1481, o plano de Kosovo, a maquete do cerco e a miniatura de Mohács são visualmente pertinentes. A imagem orbital de Istambul (#5), a cronologia de bandeiras (#8) e a colagem genérica sobre guerra otomano-espanhola (#9) são aquisições fracas apesar de terem passado no scoring atual. Isso aponta para uma lacuna remanescente nos sinais de especificidade/gênero dos candidatos e no uso de NASA em history; nenhum threshold foi baixado para elevar a taxa de mídia.

Antes desta edição, `search_exhausted` confundia fallback sintético com busca completa. Agora a auditoria não marca esgotamento quando há provider error, provider indisponível ou query não executada; fallback passa a informar `synthetic_after_incomplete_search`. Quando uma alternativa nova vence cedo, as queries restantes ficam explícitas como não consultadas após match.

## Regressões e validação

Testes cobrem pessoa, batalha/evento, império, monumento, artefato, ciência e conceito abstrato; descartam `formavam`, `primeira`, `ouro/gold` como âncoras isoladas; impedem vazamento de `laboratory`/`microscope` para history; verificam exploração após candidato contextual fraco e provider error sem falsa alegação de esgotamento. Testes focados: 60 passaram. Suíte completa após a correção final: **789 passaram**.
