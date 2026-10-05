# Relatório completo do estado do trabalho — Curio

**Data:** 2026-10-05  
**Escopo:** estado da refatoração arquitetural até G95 e métricas até F15.
**Estado:** trabalho incompleto. G80–G95 e F4–F15 foram testados e commitados; fases
posteriores e validações reais finais seguem pendentes. Este documento não
certifica a conclusão da refatoração.

**Estado do worktree no momento deste registro:** a renomeação de
`passed_asset_ids` para `segment_asset_ids` foi commitada em `8daa29f`. Ela
altera `src/curio/media/render_usage.py`, `src/curio/pipeline_render.py` e
`tests/test_pipeline_render_contracts.py`. Os testes focados passaram (62); a
suíte completa passou com 1009 testes após a mudança. Este relatório registra
o fechamento documental dessa alteração.

> **Atualização:** F6–F14 (`11022b2`, `254f48f`, `b0b272e`, `ed34825`, `1054c8a`, `4ee2506`, `9d86d4e`, `50ba36d`, `7bc5c23`, `94119e3`, `8daa29f`) e G86–G95
> (`4b0b4e7`, `412a8b1`, `c5424b5`, `087c96e`, `f0a9622`, `e187697`, `6191b8b`, `38b892e`, `60703ae`, `3978670`) foram
> implementadas e commitadas. Validações e limites constam neste relatório e nos
> [relatórios F6](20261005-stage-timings-immutable-contract.md) e
> [F7](20261005-backfill-unknown-total-duration.md). A refatoração ampla
> continua incompleta.

> **Atualização de investigação (sem implementação):** após esse registro, foi
> rastreada a divergência das métricas de requests dos providers Met e AIC.
> Nenhum arquivo de código foi alterado nesta investigação e nenhum teste novo
> foi executado. A implementação posterior dessa investigação consta em F15
> abaixo.

> **Atualização I1:** um rerender de projeto científico real preservou os
> hashes da seleção persistida, registrou zero requests/queries e passou
> `verify` 8/8. Detalhes e limites estão em
> [I1](20261005-rerender-runtime-no-search.md).

> **Atualização I2:** aquisição nova real de M87 após F15 produziu 4 assets
> únicos, validou 9 requests NASA de metadata e manteve 0 reusos/sintéticos.
> A inspeção encontrou duas imagens quase duplicadas e fontes factuais
> homônimas irrelevantes; ver [I2](20261005-ciencia-real-pos-f15.md).

> **Estado consolidado após I2:** este é o relatório de referência atualizado
> até o commit `b8eeab0` (`docs: record post-F15 science acquisition`). O
> worktree estava limpo antes desta atualização documental. Após I2, iniciou-se
> uma investigação somente de leitura sobre fontes factuais homônimas de M87
> (“Capacete M87” e “Zastava M87”). Foram localizados os módulos envolvidos na
> pesquisa (`research.py`, `research_sources.py`, `entity.py` e
> `pipeline_research.py`), mas a causa exata não foi confirmada. Nenhum código
> foi alterado nem teste executado para essa investigação.

## Estado exato do trabalho retomado

O último commit documental antes desta atualização é `b8eeab0`. O último
commit de implementação é `b9e6ff1` (`fix: count provider API
request attempts`), fase F15; os registros documentais posteriores são
`8420ab4`, `c519528`, I1 e I2. O último commit de
implementação sucede G95 `3978670`, G94 `60703ae`, G93 `38b892e` e a
proveniência até render `8daa29f`.

O projeto está executável e as migrações já commitadas passaram suas suítes
conforme registradas por fase. O resultado integral mais recente documentado é
**1014 testes aprovados em 182,23 s**, mais `compileall` e `git diff --check`,
após F15. I1 não altera código: rerender real e `verify` passaram como
validação runtime separada, sem nova suíte.

### O que estava sendo investigado na etapa de mídia

O objetivo imediato era explicar uma inconsistência observada no replay G95:
`consumption.media.provider_search_calls` incluía chamadas aos providers Met e
AIC, enquanto `provider_requests`/`requests_per_provider` não mostrava esses
providers. A investigação foi de leitura do código e localizou a causa nos
contadores em `src/curio/media/providers.py`:

- `RunMetrics.media_provider_search()` conta uma invocação do adapter e seu
  tempo total, incluindo retries/backoff. `media_search()` conta uma tentativa
  de request de rede; essas métricas representam unidades diferentes por
  definição documentada em `src/curio/metrics.py`.
- Wikimedia e a maior parte dos providers incrementam `media_search()` antes
  das tentativas de request. Met e AIC, em contraste, chamam
  `_http_get_json()` primeiro e só incrementam `media_search()` depois de uma
  resposta bem-sucedida. Assim, a falha da request inicial não aparece em
  `provider_requests` embora a invocação e o tempo do adapter apareçam.
- Met também consulta `/objects/{id}` para cada ID retornado pela busca, sem
  incrementar `media_search()` nessas chamadas. Logo, mesmo o caso de sucesso
  não conta todas as tentativas HTTP do fluxo Met. AIC faz uma request de busca
  e também incrementa somente depois do sucesso.
- `_http_get_json()` normaliza exceções em `MediaError`, mas não possui acesso
  ao nome do provider nem às métricas. A contagem atual é feita manualmente nos
  adapters, o que permite omissões como essas.

A discrepância não significa que `provider_search_calls` e `provider_requests`
devam ter o mesmo valor: uma chamada de adapter pode conter zero, uma ou várias
requests. O problema é que o contador chamado de tentativas de request não
contabiliza tentativas que falham em Met/AIC e omite requests secundárias do
Met. A correção F15 foi implementada: todos esses GETs agora contam antes da
tentativa, e o total tem breakdown `search`/ `metadata`/ `unknown`.
Requests auxiliares NASA e requests Unsplash também usam a mesma fronteira.
O detalhamento segue descrito em
[`20261005-provider-request-metric-boundary.md`](20261005-provider-request-metric-boundary.md).

Depois de I2, a investigação de fontes homônimas pretendia rastrear a
recuperação e aceitação de fontes factuais para explicar por que títulos com
“M87” bastaram para aceitar páginas sobre capacete e rifle, além de uma
afirmação de 2019 sem grounding. A análise ainda não chegou à função causal:
foram identificados os módulos a ler, mas não houve confirmação da causa,
alteração de código ou teste. Essa pendência pertence à pesquisa factual e não
foi corrigida pela F15, que trata exclusivamente da contagem de requests HTTP
de mídia.

### Estado das fases e pendências

Concluído e commitado: G80–G95, F4–F15 e fases anteriores detalhadas neste
documento. Mais recentemente, G93 corrigiu a precedência global inadequada de
providers entre cenas; G94 fez a busca consumir os mesmos planos canônicos da
cena; G95 corrigiu a seleção heurística de entidade inglesa que reduzia
`Battle of Mohacs 1526` a `Battle`; F15 centralizou a contagem das requests
de API que antes eram omitidas por Met/AIC.

Em aberto no momento da parada: validar em geração real a decomposição de
requests por operação e provider após F15. A investigação e correção do defeito
Met/AIC já estão concluídas e commitadas.

Não concluído: extração do coordenador editorial ainda concentrado em
`visual.py`; ownership global de estado/cache/metadata; simplificação dos
caminhos compatíveis internos restantes; profile comparável de performance;
execuções reais finais em pelo menos dois domínios após as últimas mudanças;
validação de rerender após troca manual de asset, cache frio, falha combinada
de providers e fallback LLM;
inspeção editorial e de quase-duplicatas em amostra adequada; fechamento de
documentação e fases posteriores do plano arquitetural. Estes pontos são
pendências, não trabalho que tenha sido concluído por passar a suíte.

### Regressões conhecidas ainda abertas

- No replay histórico pós-G95, uma cena sobre Mohács (1526) recebeu uma gravura
  de outra batalha otomana, datada de 1687. Relevância de tópico passou, mas a
  correspondência do evento/período falhou editorialmente. Não foi alterado
  threshold nem corrigido esse caso.
- A geração científica de M87 selecionou três IDs e hashes distintos, mas duas
  imagens têm composição quase igual; deduplicação binária não detecta
  duplicidade perceptual/editorial. A repetição visual foi reproduzida na
  aquisição pós-F15: as cenas 1 e 2 são composições quase idênticas.
- A pesquisa factual pós-F15 de M87 aceitou fontes homônimas irrelevantes
  (“Capacete M87” e “Zastava M87”) e deixou sem grounding uma afirmação sobre
  2019. É uma regressão no retrieval/qualificação de fontes ainda sem correção.
- O vídeo histórico G95 ainda terminou com uma cena sintética (3/4 mídia real),
  embora tenha melhorado do baseline anterior. Não se demonstrou esgotamento
  suficiente de mídia específica em todos os casos.
- A divergência dos contadores Met/AIC acima afeta a interpretação dos requests
  observados em runs anteriores a F15. A geração pós-F15 confirmou o agregado
  e o breakdown `search`; lookups `metadata` foram confirmados por sondagem
  NASA, enquanto Met continuou indisponível (HTTP 410).
- `visual.py` continua coordenando muitas decisões e efeitos. A extração das
  funções técnicas de aquisição não concluiu a separação de responsabilidades
  editoriais.

### Execuções reais pós-G95 registradas

| Tema/run | Cenas | Reais | Reais únicos | Reusos | Sintéticos | Buscas/tempo de mídia |
|---|---:|---:|---:|---:|---:|---|
| Batalha de Mohács, sem LLM | 4 | 3 | 3 | 0 | 1 | 26 queries lógicas; 66,43 s |
| M87, sem LLM | 3 | 3 | 3 por ID/hash | 0 | 0 | 18 queries lógicas; 27,68 s |
| Batalha de Mohács, F15 | 4 | 4 | 4 | 0 | 0 | 31 queries lógicas; mídia 81,98 s; total 148,89 s |
| M87, I2 pós-F15 | 4 | 4 | 4 por ID/hash | 0 | 0 | 30 queries lógicas; mídia 38,33 s; total 76,00 s |

Os detalhes por cena, fontes, seleção e inspeção visual de Mohács constam em
[`20261005-english-entity-connectors-and-real-runs.md`](20261005-english-entity-connectors-and-real-runs.md).
M87 pós-F15, incluindo requests por provider/operação e as regressões
visuais/factuais, está em [I2](20261005-ciencia-real-pos-f15.md).
Essas medições são execuções pontuais; não constituem profile pareado nem
validação final da arquitetura. No caso M87, a composição quase duplicada
mostra o limite de contar apenas identidade binária.

## F15 — contagem de requests no limite de provider (`b9e6ff1`)

F15 corrige a omissão de tentativas HTTP que falham antes de uma resposta Met ou
AIC e inclui os lookups de objetos Met e manifests de metadata NASA no total de
requests. O contrato mantém `provider_search_calls` por invocação do adapter e
`provider_requests` por tentativa HTTP; o breakdown identifica `search`,
`metadata` e `unknown`. O campo `searches` permanece alias agregado por
compatibilidade. A suíte completa passou com **1014 testes em 182,23 s**,
focados com 40 testes, além de compileall e diff check. A validação real
posterior gerou 4 assets Wikimedia únicos, sem reuse nem sintético; 31 requests
search por provider para 31 queries lógicas. Met respondeu HTTP 410 e AIC HTTP
500; sondagem NASA Apollo 11 registrou uma busca e um request metadata. Os
quatro vencedores foram inspecionados visualmente; o diorama moderno é uma
ressalva editorial. Ver
[`20261005-provider-request-metric-boundary.md`](20261005-provider-request-metric-boundary.md)
para queries, providers e limites por cena.

## Resumo do estado

O projeto já tinha módulos separados por etapa, mas ainda havia contratos
internos representados por mappings mutáveis e dados semanticamente duplicados.
As migrações recentes vêm mantendo valores tipados por mais tempo entre
planejamento, busca, avaliação, seleção, aquisição e persistência. G75–G79
extraíram aquisição técnica, unificaram uma tentativa técnica compartilhada,
corrigiram a continuação da busca contextual após falhas de aquisição,
melhoraram a auditoria de queries adiadas e separaram tópico de título em
`from-script`. G80 tornou a entrada explícita e G81 removeu uma transição row
entre a seleção de cena e o agregador de mídia. Cada fase foi commitada e
validada incrementalmente. As pendências de ownership global, simplificação e
validação real permanecem.

## Arquitetura antes das migrações recentes

O Curio já separava fisicamente CLI/TUI, pesquisa, roteiro, planejamento de
cenas, contexto visual, providers, scoring, áudio, timeline, render e métricas.
Essa separação de arquivos ainda deixava responsabilidades acopladas:

- contratos entre etapas frequentemente eram `dict`, rows serializadas ou
  listas paralelas;
- representações e queries apareciam em mais de um campo runtime;
- consumidores reconstruíam ou completavam significado de dados incompletos;
- avaliação, seleção, aquisição e fallback se comunicavam por mutações em
  mappings;
- métricas e auditoria nem sempre tinham uma definição/fonte canônica;
- `visual.py` coordenava busca, ranking, aquisição, reuso, fallback e efeitos
  de métricas/logging.

O fluxo de mídia já tinha contexto global e intenção visual por cena,
representações, aliases, SearchPlan, providers múltiplos, deduplicação,
gates/scoring, prevenção de reuso, fallback sintético e auditoria. Os problemas
históricos de repetição e de buscas ruins expuseram a necessidade de tornar
contratos e proveniência mais explícitos, sem substituir esses componentes.

## Arquitetura e fluxo depois das migrações commitadas

Fluxo derivado do código e dos relatórios de validação:

```text
CLI/TUI/configuração
  → pesquisa/fontes
  → roteiro e artefato de script
  → cenas semânticas e spans temporais
  → contexto/enrichment semântico
  → VisualPlan
  → SearchPlan/SearchQuery
  → providers e coleta de candidatos
  → avaliação/scoring e rejeições
  → shortlist tipada e tentativas de aquisição
  → SelectionDecision (novo, reuso, sintético ou ausência explícita)
  → timeline/plano visual
  → áudio, legendas e render
  → metadata, métricas e artefatos persistidos
```

As fronteiras de cena, plano visual, plano de busca, coleta/auditoria de
candidatos, avaliação, decisão visual, snapshots de assets e seleção possuem
contratos tipados em partes substanciais desse caminho. Rows JSON e formatos
legados continuam como projeções/adapters em fronteiras de persistência e
compatibilidade. A migração ainda não removeu todas as transições intermediárias
para dicts, em particular dentro do lifecycle técnico de aquisição.

O relatório de auditoria arquitetural é o inventário mais amplo do sistema e
contém mapa de módulos, responsabilidades, dependências, fontes de verdade,
fallbacks, cache, side effects, testes e plano por fase:
[`20261004-auditoria-arquitetura-pipeline-e-contratos.md`](../analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md).
O estado acumulado por G74 está em
[`20261005-relatorio-arquitetura-estado-atual.md`](20261005-relatorio-arquitetura-estado-atual.md).

## Commits recentes

Os commits abaixo são as fases recentes de contratos tipados no caminho de
seleção. O histórico Git contém as fases anteriores e é a fonte completa dos
hashes e diffs.

| Commit | Resultado |
|---|---|
| `dd19b24` | Introduz `RankedSelectionCandidate` e `SelectionPool` tipado; preserva evidência CLIP e associação de rejeições por identidade. |
| `76809b4` | Documenta a migração do candidato ranqueado. |
| `d8dace3` | Faz a decisão de seleção consumir `SelectedAsset` tipado. |
| `d0acf73` | Documenta a decisão baseada em asset selecionado. |
| `ec61c65` | Mantém os assets escolhidos tipados até a projeção/serialização. |
| `ab2e7ea` | Documenta a fronteira de mídia selecionada tipada. |
| `7b965a1` | Mantém shortlist nova e reserva de reuso como candidatos ranqueados tipados durante seleção. |
| `f8e7fb9` | Documenta a fronteira tipada de candidatos. |
| `57a9a21` | Introduz resultados tipados de sucesso/falha de aquisição por candidato. |
| `a5d36ed` | Documenta os resultados tipados de aquisição. |
| `c4ef8c5` | Extrai tentativas de aquisição dos candidatos ranqueados para `media_candidate_acquisition.py`; fallback editorial permanece em `visual.py` (G75). |
| `1649f49` | Documenta a extração G75. |
| `b87ba98` | Compartilha download/cache/validação dimensional dos caminhos fresh e reuse via `TechnicalAcquisitionAttempt` (G76). |
| `57a767b` | Documenta a tentativa técnica compartilhada G76. |
| `111995f` | Continua a busca contextual planejada quando candidatos específicos passam scoring, mas falham na aquisição (G77). |
| `11a7fff` | Documenta a busca contextual após falha de aquisição. |
| `f7eabb0` | Audita queries contextuais adiadas e diferencia adiamento, consulta e orçamento esgotado (G78). |
| `885bf72` | Documenta a auditoria G78. |
| `58f0aea` | Separa tópico e título editorial no fluxo `from-script` (G79). |
| `900d4ca` | Registra a separação tópico/título e os resultados de execuções reais pós-G78. |
| `5f3eeb9` | Torna `PipelineInput` obrigatório e migra CLI/TUI/queue e consumidores de teste (G80). |
| `aa25487` | Mantém `SceneMediaSelection` tipado entre seletor por cena e agregador do estágio de mídia (G81). |
| `1b00689` | Faz `SceneMediaSelection.from_components` criar nova seleção de `SelectedAsset` e `VisualDecision` tipados (G82). |
| `31f6acf` | Rejeita tipos inválidos nos campos de `PipelineInput` (G83). |
| `bc131b9` | Move aplicação da camada CLIP e reranqueamento para `candidate_evaluation.py` (G84). |
| `8ae6616` | Faz auditoria de query/candidato consumir provenance do `VisualPlan` e rejeitar plano de cena divergente (G85). |
| `11ac1f3` | Mede a etapa de timeline visual em `VisualTimelineResult` e agrega duração explícita nos stage times (F4). |
| `e534ee3` | Compartilha a validação de durações nos resultados de etapa (F5). |
| `11022b2` | Substitui o acumulador mutável por `StageTimings` imutável; dict fica na projeção persistida (F6). |
| `254f48f` | Mantém duração total desconhecida como `null` em backfill sem valor total explícito (F7). |
| `4b0b4e7` | Centraliza a decisão pura da próxima tier da seleção visual em `media_selection.py` (G86). |
| `412a8b1` | Faz `media_selection.py` classificar exaustão, motivo e fallback a partir de plans e auditoria tipados (G87). |
| `c5424b5` | Move montagem e validação do payload `VisualDecision` para `visual_audit.py` (G88). |
| `087c96e` | Mantém `CandidateEvaluation` tipada até a projeção da auditoria visual (G89). |
| `f0a9622` | Preserva `CandidateRejection` tipada até a projeção da auditoria (G90). |
| `e187697` | Mantém resultados de aquisição rejeitados tipados até a auditoria (G91). |
| `6191b8b` | Projeta rejeições e totais de query diretamente de outcomes tipados (G92). |
| `b0b272e` | Faz a métrica live de duração total consumir o elapsed canônico do pipeline (F8). |
| `ed34825` | Projeta os totais de seleção em `consumption.media` a partir da mesma estatística tipada de `visual_report` (F9). |
| `1054c8a` | Classifica retries de mídia por operação e provider, mantendo o total agregado (F10). |
| `4ee2506` | Separa expiração real de busca de bloqueio de provider por rate limit/acesso negado (F11). |
| `9d86d4e` | Distingue cache de bytes e cache de resultados de busca no schema de métricas (F12). |
| `50ba36d` | Compara assets selecionados com a timeline e preserva reconciliação unknown no backfill (F13). |
| `7bc5c23` | Registra paths dos assets associados aos segmentos e fallback por cena (F14). |
| `94119e3` | Marca segmento visual reutilizado do cache, sem afirmar nova codificação (F14). |
| `8daa29f` | Nomeia identidades dos assets associados ao segmento sem afirmar que foram decodificados pelo FFmpeg (F14). |
| `38b892e` | Aplica prioridade de providers por cena a partir do `VisualPlan` individual (G93). |
| `60703ae` | Passa à busca os mesmos `VisualPlan` e `SearchPlan` usados no preparo por cena (G94). |
| `3978670` | Preserva nomes próprios ingleses com conectores na resolução heurística sem LLM (G95). |


As fases anteriores G57–G69 e as migrações anteriores de pesquisa, áudio,
render, metadata e cenas estão enumeradas no relatório de estado e no histórico
Git. Não se deve interpretar a tabela acima como histórico completo do projeto.

## Arquivos e contratos alterados/criados/removidos

### Fases G57–G69

O inventário de arquivos por fase consta em
[`20261005-relatorio-arquitetura-estado-atual.md`](20261005-relatorio-arquitetura-estado-atual.md).
Em resumo, houve alterações em contratos e consumidores de cenas, projeção,
contexto visual, scoring, timeline, regras de mídia, seleção, auditoria,
coleta de candidatos, snapshots e decisões, além dos testes correspondentes.
G57 removeu o mirror runtime de queries de `SemanticScene`; a query legada
passou a ser projeção. G58–G62 separaram resultado da etapa de mídia,
seleção/reuso, auditoria por query e coleta por cena. G63–G69 validaram a
decisão visual, congelaram evidências/snapshots e mantiveram seleção de assets
tipada durante reuso cross-scene.

### G70–G74

- `src/curio/stages/media_contracts.py`: avaliação e evidências imutáveis,
  snapshots e contratos de candidatos ranqueados.
- `src/curio/media/asset_snapshot.py` e
  `src/curio/media/selection_result.py`: identidade/snapshot de asset e
  resultado tipado de seleção.
- `src/curio/media/visual_decision.py`: decisão visual validada, com projeções
  compatíveis.
- `src/curio/stages/media_selection.py`: políticas/atualizações de reuso e
  decisão consumindo valores tipados.
- `src/curio/stages/visual_audit.py` e
  `src/curio/stages/scene_candidate_search.py`: snapshots/auditoria e coleta
  explícita por query/cena.
- `src/curio/stages/visual.py`: adaptado progressivamente para esses contratos;
  ainda dono do fluxo de aquisição até G74.
- Testes relacionados: `tests/test_media_contracts.py`,
  `tests/test_media_selection.py`, `tests/test_visual_decision.py`,
  `tests/test_visual_audit.py` e `tests/test_scene_candidate_search.py`, além
  dos testes de pipeline/direção visual listados no relatório de estado.

Contratos que passaram a existir ou ganharam invariantes explícitos incluem
`ProviderAssetSnapshot`, `Candidate`, `CandidateEvaluation`, `EvaluationBatch`,
`RankedSelectionCandidate`, `SelectionPool`, `SelectedAsset`,
`CandidateAcquisitionOutcome`, `SearchQueryAudit`, `SceneCandidateCollection`,
`MediaAssetSnapshot`, `SelectionDecision`, `SceneMediaSelection`,
`MediaStageResult` e `VisualDecision`.

Não houve remoção total de compatibilidade externa necessária. Foram removidos
espelhos runtime duplicados de queries em cenas/planos em fases anteriores; a
serialização legada foi mantida como projeção. Compatibilidade interna e
adapters ainda existem onde a migração não terminou.

### G75–G78: aquisição, continuação da busca e auditoria

G75 criou `src/curio/stages/media_candidate_acquisition.py` e moveu para esse
módulo a execução concorrente de tentativas técnicas nos candidatos ranqueados.
O lote `CandidateAcquisitionBatch` contém outcomes imutáveis; `visual.py`
continua dono da ordem editorial fresh → sintético → reuso. Métricas/logging e
consulta de uso cross-scene ainda atravessam fronteiras e seguem como dívida.

G76 introduziu `TechnicalAcquisitionAttempt` para compartilhar download/cache e
validação dimensional entre aquisição fresh e reuse. A classificação editorial
dos resultados continua distinta.

G77 corrigiu uma parada prematura: se candidatos específicos passam scoring,
mas falham no download/validação, a tier contextual/genérica planejada agora
pode ser consultada para preencher vagas, usando os mesmos gates e mantendo a
ordem da seleção. Isso corrige a transição de busca após falha técnica; não
demonstra que todos os providers estejam saudáveis nem que a cobertura real seja
suficiente.

G78 marca explicitamente queries contextuais ainda não executadas como
`not_consulted`, distinguindo-as de consultas sem resultados ou bloqueadas por
orçamento. Ainda há uma limitação documentada: a razão detalhada cobre as
queries contextuais adiadas; queries específicas são sempre iniciadas pelo
fluxo atual.

### G79: tópico e título de roteiro pronto

Uma geração real revelou que `run_script_pipeline()` passava o mesmo texto
como assunto de pesquisa e título editorial. G79 adicionou `--topic` para
separar esse assunto do `--title`; o pipeline usa o tópico em pesquisa e cenas,
e preserva o título informado como `TitleArtifact(provided)`. Sem `--topic`, o
título continua servindo como assunto para compatibilidade. A migração cobre
somente `from-script`; AI/TUI/queue ainda compartilham `idea` como string.
Validação real e limitações estão no relatório dedicado G79.

## Testes e validações atuais registradas

G70: 937 testes passaram e 1 teste foi desmarcado devido a HTTP 429 externo;
depois, 89 testes focados passaram. G71: 940 passaram, 1 desmarcado, suíte em
179,44 s; 88 focados. G72: 940 passaram, 1 desmarcado, em 179,23 s; 99
focados. G73: 940 passaram, 1 desmarcado, em 178,02 s; 99 focados. G74: 100
focados passaram; na suíte ampla, 941 passaram e 1 foi desmarcado após HTTP
429 da API real da Wikipédia, em 172,28 s. G75 teve 102 focados e suíte ampla
com 943 passando/1 desmarcado; G76 teve 103 focados e 944/1; G77 teve 90
focados e 946/1; G78 teve 53 focados e 948/1; G79 teve 36 focados e 953/1 na
suíte ampla. Em G75–G79 também passaram
`python -m compileall -q src tests` e `git diff --check`.

Esses números refletem execuções separadas por fase, não uma única execução
após todas as mudanças. O teste excluído depende da API real da Wikipédia; as
falhas/deseleções externas deixam esses caminhos de rede sem prova determinística.

## Regressões e problemas conhecidos

- **Busca histórica e qualidade editorial:** geração real após G48 mostrou
  falso positivo para a Batalha de Mohács (imagem moderna do Parlamento Húngaro
  aceita por evidência territorial ampla), além de providers indisponíveis.
  O caso está descrito em
  [`20261004-validacao-arquitetural-execucoes-reais.md`](20261004-validacao-arquitetural-execucoes-reais.md).
- **Cobertura/saúde de providers:** no vídeo otomano medido anteriormente,
  Met respondeu HTTP 410, AIC HTTP 500 e Wikimedia teve timeouts; a cobertura
  resultou em sintéticos. Isso não prova que inexistam imagens nos acervos.
- **Dados de performance:** há medições reais pontuais, mas não um profile
  comparável completo por componente sob condições iguais. A etapa de mídia
  otomana foi observada em 361,77 s numa validação anterior, com busca/retries
  como suspeitos dominantes; não se atribuiu causalidade precisa.
- **Métricas:** houve correções pontuais de timings, mas ownership e definições
  canônicas globais continuam parciais; zero em métricas históricas pode ser
  dado ausente, não duração real.
- **Provas e2e restantes:** falha simultânea de LLM e provider, fallback local
  com o mesmo contrato, cache de decisão, rerender após mudança de seleção e
  maior amostra de inspeção visual precisam de validação adicional.
- **Aquisição:** G75 extraiu a orquestração técnica e G76 compartilhou o
  download/validação. O coordenador ainda concentra decisões editoriais e
  efeitos de métricas/logging; a extração não encerrou esse ownership.
- **Busca após falha técnica:** G77 cobre a regressão em que candidatos
  específicos passam scoring e falham na aquisição. Continua faltando validar
  em geração real com providers saudáveis e demonstrar queries executadas até
  esgotamento razoável.
- **Auditoria de query:** G78 distingue tier contextual adiada da consulta
  efetiva; reasons equivalentes para queries específicas não executadas não
  fazem parte do comportamento atual porque elas são iniciadas pelo fluxo.
- **Fonte de tópico:** G79 elimina a ambiguidade título/assunto somente em
  `from-script`. AI, TUI e queue continuam usando a mesma string `idea` para
  pesquisa, contexto e outras decisões do pipeline.
- **Entrada do pipeline:** G80 exige `PipelineInput` e rejeita `str` no
  entrypoint. O formato persistido da queue ainda chama o campo de tópico de
  `idea`; a conversão acontece na fronteira da queue.

## F6 — coleção imutável de tempos de etapa (`11022b2`)

F6 substitui a agregação mutável de tempos de etapa por `StageTimings`, uma
coleção de `StageTiming` imutável, validada e sem nomes duplicados. O pipeline,
áudio, preparação humana, standby e finalize consomem o contrato. `pipeline_metadata`
projeta um snapshot dict na fronteira para o schema persistido e para
`metrics.save()`; métricas históricas continuam em dict. O formato externo não
muda.

O teste de finalize humano encontrou duas gravações de `finalize`: no produtor e
na persistência. A coleção passou a ser construída vazia pelo produtor, e
`persist_run_metadata()` ficou como único owner dessa medição. A suíte completa
passou com **978 testes em 200,91 s**. Depois de acrescentar validação de tipo
em preparação humana, foram repetidos os testes de integração, metadata e
timing: **22 passaram em 36,48 s**. Compileall e `git diff --check` passaram.
Detalhes e a ressalva sobre a ordem das verificações estão no relatório F6.

F6 fecha o acumulador mutável comum. F9 unifica a projeção dos totais de seleção
entre `consumption.media` e `visual_report`; os três nomes históricos permanecem
aliases explícitos. F10 separa retries de busca e download sem alterar os
campos agregados; F11 evita contar bloqueio de provider como timeout. A fase de
F13 compara seleção com a timeline planejada; F14 observa os assets que passam
os filtros de caminho no renderer. A fase de métricas continua parcial:
definições canônicas globais para requests/timing, backfill de contadores
históricos, timers adicionais, profile por suboperação e confirmação dos frames
após render seguem pendentes. Ver
[relatório F9](20261005-selection-metrics-single-projection.md) e
[relatório F13](20261005-selection-render-reconciliation.md),
[relatório F14](20261005-renderer-input-asset-usage.md).

## Trabalho de mídia: escopo e ponto exato

As fases de mídia desta refatoração não estão tentando introduzir uma nova
política editorial ou afrouxar os gates. O objetivo arquitetural é tornar
explícitas as transições já existentes — plano visual e de busca, coleta de
candidatos, avaliação, aquisição técnica, seleção/reuso, fallback e projeção —
para que a busca continue após falha técnica e cada decisão possa ser auditada.
O objetivo funcional anterior que motivou essa arquitetura era impedir que um
único asset dominasse cenas distintas e garantir que o sistema explore queries
semânticas adequadas antes de recorrer a sintéticos ou reuso.

O trabalho commitado relevante inclui G75 (extração das tentativas de aquisição
técnica), G76 (compartilhamento de download/cache/validação), G77 (continuação
da busca contextual quando aquisição falha), G78 (estado auditável de queries
contextuais adiadas), G84 (ownership do reranqueamento CLIP na avaliação) e G85
(proveniência da auditoria a partir do `VisualPlan`). Isso não equivale a uma
validação real final da cobertura e da qualidade visual. Persistem os riscos
descritos acima: providers externos podem estar indisponíveis, busca pode
esgotar candidatos utilizáveis e o coordenador `visual.py` ainda mantém parte
da orquestração editorial, fallback e efeitos de observabilidade.

Historicamente, o trabalho estava em F14 quando foi registrado o snapshot
anterior. Depois, G95 corrigiu o alvo heurístico inglês e F15 corrigiu as
contagens de requests de API. O commit `8daa29f` renomeou
`passed_asset_ids` para `segment_asset_ids`: esse contrato prova associação
do arquivo ao segmento, mas não que o FFmpeg decodificou cada input nem que
seus pixels aparecem no MP4. F15 não altera essa limitação do renderer.

## Estado das fases do plano arquitetural

| Fase | Estado registrado | Pendências principais |
|---|---|---|
| R — resultado de pesquisa | R1–R2 concluídas segundo a auditoria, parcial no todo. | Imutabilidade do resultado e mutadores internos. |
| A — modelo semântico | A4a–A4v concluídas no escopo registrado. | Ownership restante de alias/contexto e compatibilidade externa controlada. |
| B — VisualPlan | B1–B4 concluídas no escopo registrado. | Consolidar políticas de gênero e ganchos sintéticos. |
| C — SearchPlan | C1 concluída. | Replays reais com providers saudáveis e revisão de qualidade. |
| D — candidato/avaliação/seleção | D1–D4 e convergência parcial até G80. | Unificar transições de fallback e simplificar o coordenador. |
| E — cache/artifact lifecycle | Parcial; E1–E7/E6 conforme inventário. | Lifecycle unificado e fronteiras restantes de rows. |
| F — métricas/estado | F1–F15 parciais. | Contagem de requests foi confirmada em geração e sondagem; lifecycle timers, profile de performance e validação dos frames após FFmpeg permanecem incompletos. |
| G — simplificação do pipeline | Parcial; G1, G3–G5 e G7–G95 commitadas. | `visual.py` ainda coordena coleta, avaliação, aquisição e fallback; fronteiras persistidas ainda usam mappings por compatibilidade. A execução histórica ainda mostra falsos positivos de período. |
| H — performance | Pendente. | Profile por planejamento, request/retry, download, dedupe, scoring e fallback. |
| I — validação/limpeza | Parcial. | Há Mohács e M87 reais pós-F15, fallback local sem LLM e rerender real sem nova busca. Faltam falhas combinadas, rerender após troca manual/cache frio e inspeção editorial maior; M87 mostrou quase duplicatas e fontes homônimas. |

Os status são os registrados na auditoria e neste relatório até G95/F15. Não representam
aceite final dos objetivos amplos.

## O que estava sendo tentado corrigir na etapa de mídia

O problema arquitetural que levou às fases recentes era o acoplamento entre
busca editorial e aquisição técnica. G74 substituiu mutações implícitas em
`dict` por `CandidateAcquisitionOutcome`. G75 moveu as tentativas concorrentes
para `media_candidate_acquisition.py`; G76 unificou a operação técnica
compartilhada. A transição passou a ser:

```text
RankedSelectionCandidate
  → tentativa técnica de aquisição
  → CandidateAcquisitionOutcome
  → SelectedAsset ou row de rejeição/auditoria
```

Depois, G77 corrigiu a parada prematura quando a busca específica retorna
candidato elegível que falha durante aquisição: a tier contextual planejada
continua antes dos fallbacks posteriores. G78 tornou visível quando essa tier
foi adiada. Os gates, a política de reuso, os providers existentes e a ausência
de chamadas pagas/LLM por cena foram preservados. G79 também separou tópico de
título em `from-script`; o relatório dedicado registra replays reais e
limitações. O replay determinístico G77 após falha de aquisição continua pendente.

## Incompleto para considerar a refatoração encerrada

- Terminar as fases E–I conforme critérios da auditoria, incluindo ownership
  canônico para métricas/estado e simplificação dos coordenadores.
- Resolver e testar os falsos positivos semânticos históricos sem reduzir
  thresholds nem esconder falhas de provider.
- Repetir geração real histórica com providers saudáveis e executar replay
  determinístico que exercite G77 após falha técnica, reportando a auditoria
  por query, candidatos, decisões e fallback de cada cena.
- Completar validação real de aquisição em dois domínios após F15; o rerender
  de ciência já foi provado em I1, mas faltam troca manual seguida de rerender,
  cache frio, falhas combinadas de LLM/provider e inspeção de uma amostra
  editorial maior.
- Rodar suíte, compile/check e profile final sobre a revisão final efetivamente
  commitada. Não há evidência de conclusão dessas validações finais.

## Estado após G83

G80 (`5f3eeb9`) tornou `PipelineInput` obrigatório para `run_pipeline` e
`_run_pipeline`. CLI/TUI/queue e `run_script_pipeline` convertem suas entradas
na fronteira. Chamadas Python com `str` ou com os parâmetros removidos
`provided_script`/`display_title` são incompatíveis por decisão arquitetural;
comandos, conteúdo de projetos e schema persistido da queue foram preservados.
G81 (`aa25487`) fez o seletor por cena devolver `SceneMediaSelection` e o
agregador montar `MediaStageResult` sem serializar/recarregar rows entre essas
funções. G82 (`1b00689`) moveu para `SceneMediaSelection.from_components` a
montagem de novas seleções, consumindo `SelectedAsset` e `VisualDecision`
tipados. `from_dict` e `_row` seguem para leitura/round-trip legado;
`media.json` segue inalterado. O worktree de código está limpo.
G83 (`31f6acf`) endureceu o contrato de entrada: campos não textuais agora
falham na validação em vez de serem convertidos implicitamente.

### Testes atuais

G80 teve **64 testes focados** e **960 testes na suíte completa** em 196,40 s.
G81 teve **160 testes focados** e **960 testes na suíte completa** em 187,17 s.
G82 teve **126 testes focados** e **962 testes na suíte completa** em 175,45 s.
G83 teve **25 testes focados** e **965 testes na suíte completa** em 192,60 s.
As quatro fases passaram `python -m compileall -q src tests` e
`git diff --check`. Não houve geração real: G80 altera entrada e G81/G82 mudam
somente contratos internos de seleção; G83 restringe tipos de entrada. As
provas reais de mídia de G79 seguem nos relatórios daquela fase.

### Escopo da correção da etapa de mídia

G80 não altera query, provider, scoring, seleção, fallback nem aquisição. A
causa tratada nesta fase era a ambiguidade do valor de entrada: após G79, apenas
`from-script` separava assunto de título, enquanto AI/TUI/queue entregavam
`idea` como string. O contrato novo torna explícito que esse texto é `topic`,
e carrega roteiro e título em campos próprios. Isso melhora a atribuição de
responsabilidade e permite ao core não reinterpretar o formato de entrada; não
prova maior cobertura de mídia nem resolve os resultados reais históricos.

Os dados reais G79 permanecem: o replay otomano teve 11 cenas, 1 asset real
único e 10 sintéticos, com providers Met/AIC/NASA respondendo com erros ou
poucos resultados; o replay de buraco negro com NASA apenas teve 3 cenas
sintéticas e nenhuma candidata. Consulte
[`G79 — tópico/título e execuções reais`](20261005-topic-title-separation-and-real-runs.md).

G81 não alterou busca nem escolha editorial. Corrigiu uma fronteira: a seleção
por cena era serializada em row e revalidada pelo agregador imediatamente.
Agora o helper retorna `SceneMediaSelection` e o agregador cria
`MediaStageResult` diretamente. Parte da decisão ainda é montada em campos row
antes de `SceneMediaSelection.from_dict`; essa dívida está no relatório G81.

G82 remove a montagem dessa row do seletor novo: ele passa assets e decisão
tipados para `from_components`, que centraliza a projeção. A fábrica ainda usa
validação do contrato e `_row` preserva round-trip; auditorias aninhadas seguem
em mappings. Consulte o relatório G82.

G84 extraiu `apply_clip_layer()` de `visual.py` para
`candidate_evaluation.py`, mantendo download e cache delegados à aquisição.
G85 fez os projetores de auditoria consumirem `VisualPlan`, removendo a
reconstrução paralela de levels, kinds e aliases no coordenador e validando
que os planos pertençam à mesma cena. O formato persistido foi preservado.
F4 mede o estágio de timeline visual e registra `stage_times["visual_timeline"]`;
isso fecha apenas um dos timers ausentes.

## G84 — camada CLIP na avaliação de candidatos (`bc131b9`)

Antes, a função local
`apply_clip` dentro de `_search_scene_with_shortcircuit()` em `visual.py`
misturava preparação/download técnico de imagem, validação dimensional,
execução do score CLIP, atualização imutável da avaliação ranqueada,
ordenação da shortlist e métricas da camada. A mudança moveu essa operação para
`apply_clip_layer()` em `candidate_evaluation.py`; `visual.py` passa as listas
de candidatos específicos e contextuais para essa função. O comportamento e os
limites atuais foram copiados sem intenção de mudar thresholds ou política
editorial.

Arquivos modificados no worktree: `src/curio/stages/candidate_evaluation.py`
e `src/curio/stages/visual.py`. Não há arquivos criados/removidos nem contrato
persistido novo nesta tentativa. A responsabilidade de scoring/avaliação fica
mais próxima do módulo que já atualiza `CandidateEvaluation`; download/cache
continuam usando `media_acquisition`, e `visual.py` continua coordenando tiers,
shortlists, fallback e seleção.

Validação já observada: os testes focados
`test_visual_director.py`, `test_media_selection.py`,
`test_media_waterfall.py`, `test_media_museums.py`, `test_media_funnel.py`,
`test_visual_query_concepts.py` e `test_candidate_evaluation.py` passaram:
104 testes em 0,69 s. `compileall` e `git diff --check` passaram antes da
suíte completa. A execução completa de `pytest -q` terminou com **965 testes
passando em 195,46 s**, já incluindo a mudança G84. Nenhuma geração real foi
executada para G84, pois a fase moveu ownership sem alterar a política ou o
comportamento da busca.

## Estado de versionamento no momento deste relatório

Commit de implementação: `bc131b9 refactor: move clip reranking into candidate
evaluation`. O commit `87827f3` registrou o estado anterior em que G84 estava
sem commit; este relatório corrige aquele registro. A alteração está
commitada e a suíte passou, mas isso não certifica a conclusão da refatoração
arquitetural ampla.

## G85 — auditoria visual deriva provenance do VisualPlan (`8ae6616`)

Antes, `visual.py` remontava níveis e tipos de representação de `ch` e buscava
aliases em `video_context`, apesar de esses fatos já pertencerem a `VisualPlan`.
`search_query_audit_rows()` e `candidate_audit_rows()` agora recebem esse plano
validado; a primeira também rejeita plano de busca e visual de cenas diferentes.
Os mesmos campos da auditoria persistida são projetados, sem schema change.

Foram alterados `visual.py`, `visual_audit.py` e `tests/test_visual_audit.py`.
**66 focados** passaram; a suíte completa passou com **966 testes em 197,08 s**.
Compileall e diff check passaram. Não houve geração real porque a mudança
somente moveu a fonte de dados da auditoria. Ver
[relatório G85](20261005-visual-audit-from-visual-plan.md).

## G86 — política explícita da próxima tier de mídia (`4b0b4e7`)

`media_selection.next_selection_fallback()` tornou explícitas as decisões de
continuar a busca contextual, usar visual sintético, considerar reuso ou
encerrar a seleção. `visual.py` executa a ação retornada; gates e comportamento
editorial permanecem. 89 focados passaram; a suíte completa passou com 986
testes. A extração não remove o restante da orquestração de `visual.py`. Ver
[relatório G86](20261005-selection-fallback-policy.md).

## G87 — ownership da provenance de seleção (`412a8b1`)

`describe_selection_provenance()` em `media_selection.py` deriva motivo de
exaustão e nível de fallback a partir de `SelectedAsset`, `VisualPlan`,
`SearchPlan` e auditoria completa por query. O coordenador deixa de reinterpretar
esses dados. Não há mudança no schema de `media.json`. 98 focados e 990 testes
completos passaram. Ver
[relatório G87](20261005-selection-provenance-owner.md).

## F8 — duração total live com fonte única (`b0b272e`)

`RunMetrics.to_dict()` publica `processing_time_seconds` como
`time.total_seconds` quando o valor é válido; o relógio do collector atende
somente chamadas diretas/legadas sem esse campo. Testes cobrem zero medido,
duração positiva, fallback e backfill unknown. 24 focados e 993 completos
passaram. Ver [relatório F8](20261005-live-metric-total-duration.md).

## G88 — ownership da montagem da decisão visual (`c5424b5`)

`visual_audit.build_scene_visual_decision()` recebe os contratos tipados da cena,
dos planos, da coleta e da seleção; valida suas identidades e coerência antes de
projetar `VisualDecision`. `visual.py` deixa de montar inline o payload de
auditoria. O schema persistido e a política editorial ficam iguais. A suíte
focada passou com 9 testes e a completa com 994 testes em 185,22 s; compileall
e diff check passaram. Ainda restam rows de candidatos/rejeições nessa fronteira
e a orquestração de busca/aquisição em `visual.py`. Ver
[relatório G88](20261005-visual-decision-audit-owner.md).

## G89 — avaliações tipadas até a auditoria (`087c96e`)

`CandidateEvaluation` e `SelectedAsset` agora permanecem tipados até
`candidate_audit_rows()`. As conversões em rows foram removidas do caminho de
avaliações e score rejections; `evidence_dict()` descongela evidência apenas na
projeção. A primeira suíte integral desta fase encontrou 34 falhas porque
`MappingProxyType` aninhado não passa pelo `deepcopy` de `VisualDecision`; o
thaw recursivo explícito corrigiu a fronteira. Depois da correção: 71 testes
focados, 995 completos em 178,95 s, compileall e diff check aprovados. Rows de
rejeição técnica ainda permanecem. Consulte
[relatório G89](20261005-typed-candidate-evaluation-audit.md).

## G90 — rejeições técnicas tipadas até a auditoria (`f0a9622`)

`CandidateRejection` carrega evidência semântica congelada. O enriquecimento não
serializa mais os resultados e `visual.py` mantém esses valores tipados até a
projeção final. Os testes focados passaram (65), assim como compileall/diff
check; a suíte completa passou com 996 testes em 179,78 s. A auditoria e o
formato persistido mantêm os campos anteriores. `CandidateAcquisitionOutcome`
ainda vira row antes da auditoria; `visual.py` ainda coordena aquisição e
fallback. Ver [relatório G90](20261005-typed-technical-rejections.md).

## G91 — outcomes de aquisição tipados até a auditoria (`e187697`)

`CandidateAcquisitionOutcome` rejeitado permanece tipado durante as tiers e só
vira row na auditoria e na fronteira de saída de `SceneMediaSelection`. Isso
preserva identidade/motivo de download, dimensão e duplicata sem antecipar a
serialização. Os focados passaram com 90; suíte completa: 997 em 195,03 s;
compileall e diff check passaram. O schema externo segue com mappings. Veja
[relatório G91](20261005-typed-acquisition-rejections.md).

## G92 — projeções de rejeição derivadas de outcomes tipados (`6191b8b`)

`visual.py` deixou de fabricar e acumular rejection rows como estado
intermediário. `visual_audit` projeta rows de persistência e calcula contagens
por query a partir de avaliações, rejeições técnicas e outcomes de aquisição
tipados. Os focados passaram com 105, suíte completa com 997 em 194,65 s,
compileall e diff check passaram. A lista persistida ainda é mapping na
fronteira externa. Ver [relatório G92](20261005-typed-rejection-projections.md).

## G93 — prioridade de providers por cena (`38b892e`)

`fetch_media_multi()` achatava as listas retornadas por
`ordered_providers(cfg, scene_plan, genre)` em uma ordem global com deduplicação.
Por isso, a primeira cena que mencionava um provider fixava sua posição para
todas as cenas seguintes; por exemplo, a prioridade de museus de uma cena
histórica podia colocar Met antes de NASA numa cena espacial. A ordenação agora
é calculada dentro do loop de cada cena e somente essa lista é enviada à busca
da cena. Isso mantém `media_provider_policy` como dono da regra de ordenação e
`visual.py` como consumidor do plano específico. Queries, gates, scoring,
aquisição, diversidade, fallback e cache não mudaram.

Arquivos alterados: `src/curio/stages/visual.py` e
`tests/test_pipeline_visual.py`. A regressão usa uma cena histórica seguida de
uma espacial e inspeciona a ordem entregue a cada busca. **82 focados** e
**1010 testes completos em 190,57 s** passaram; compileall e diff check
passaram. Não houve geração real, então disponibilidade, latência e qualidade
editorial de providers atuais continuam pendentes. Ver
[relatório G93](20261005-provider-priority-per-scene.md).

## G94 — planos canônicos encaminhados à busca (`60703ae`)

Depois de G93, a prioridade de provider era calculada com um plano, enquanto
`_search_scene_with_shortcircuit()` reconstruía outro plano para fazer as
queries. G94 moveu a construção dos dois planos para o loop por cena e passa
`VisualPlan` e `SearchPlan` ao consumidor. A busca valida seus tipos e rejeita
planos de outra cena. O mesmo VisualPlan alimenta política de provider e query
planning; o timer `media_query_generation_time` continua cobrindo ambos.
Fixtures de teste que chamavam o helper foram atualizadas para fornecer os
contratos explicitamente.

Arquivos: `src/curio/stages/visual.py`,
`tests/test_support/media_scene_search.py` e `tests/test_pipeline_visual.py`.
138 focados, **1011 testes completos em 189,64 s**, compileall e diff check
passaram. Sem geração real nesta fase. Ver
[relatório G94](20261005-canonical-scene-search-plans.md).

## G95 — nome de evento preservado no fallback local (`3978670`)

O replay `g94-mohacs-local`, com as chaves LLM vazias no processo, persistiu
`target_entity.target=Battle`; as três fontes aceitas eram o artigo genérico
“Battle”, “Battle of Battle Hill” e “Battle Royale”. `_capitalized_spans()`
separava o conector `of` e fazia a palavra inicial ganhar como entidade. G95
passou a preservar conectores ingleses em blocos de nomes compostos e removeu o
regex `_CAP`, comprovadamente sem consumidores.

O replay `g95-mohacs-local`, com o mesmo roteiro e fallback local, resolveu
`Battle of Mohacs`, selecionou fontes específicas e deixou o grounding sem
alerta. Assets: 3 reais únicos em 4 cenas, zero reusos e um sintético; mídia
66,43 s, total 105,75 s. A inspeção identificou uma gravura de batalha otomana
de 1687 colocada numa cena sobre 1526, então a especificidade de período ainda
falha. Antes da mudança, foram 2 reais (um mapa correto e um monumento de
Leipzig incorreto), 2 sintéticos, 61,67 s de mídia e 100,52 s totais.

O replay científico `g94-m87-local` cobriu 3/3 cenas com IDs/hashes únicos e
zero reuso/sintético, mas inspeção mostra duas imagens do M87 de composição
quase igual. Ambas as execuções tiveram `nvidia.calls=0`. No relatório de G95
estão os paths dos assets, queries, contagens e detalhes dos dois replays.
Métricas também mostraram `provider_search_calls` incluindo Met/AIC e
`provider_requests` omitindo esses nomes; definição canônica de requests ainda
precisa de fase própria. O replay não certifica aquisição histórica resolvida.

17 focados depois da remoção do regex morto; suíte completa: **1012 em 175,13
s**; compileall e diff check aprovados. Ver
[relatório G95](20261005-english-entity-connectors-and-real-runs.md).

## F9 — projeção única das métricas de seleção (`ed34825`)

`consumption.media` agora projeta contagens de asset real, único, reutilizado,
sintético, ausente e desconhecido a partir do mesmo `MediaSelectionStats`
consumido por `visual_report`. `assets`, `fallbacks` e `reused` permanecem como
aliases do formato anterior. Sem projeção da seleção, os valores ficam `null`;
rows de metadata não são usadas para inferir zeros. **26 testes focados e 999
testes completos em 198,62 s** passaram; compileall e diff check passaram. Ver
[relatório F9](20261005-selection-metrics-single-projection.md).

## F10 — retries classificados por operação (`1054c8a`)

Retries de Wikimedia durante a busca são registrados como `search`; retries ao
baixar bytes no cache são `download`. `retries` e `retries_by_provider` mantêm o
total agregado compatível, enquanto `retries_by_operation` e
`retries_by_provider_operation` expõem o breakdown. Chamadas sem proveniência
continuam visíveis em `unknown`. 34 focados e 999 testes completos em 187,91 s,
compileall e diff check passaram. Ver
[relatório F10](20261005-media-retry-operation-metrics.md).

## F11 — timeout separado de bloqueio de provider (`4ee2506`)

Somente espera realmente expirada incrementa `timeouts`, com breakdown em
`timeouts_by_provider`. `401/403` ficam em `disabled_providers` como
`access_denied`; `429` como `rate_limited`. Focos: 20 passaram; suíte completa:
**1002 em 190,17 s**; compileall e diff check passaram. Ver
[relatório F11](20261005-media-timeout-error-separation.md).

## F12 — unidades explícitas de cache (`9d86d4e`)

`download_cache_hits` e `download_cache_misses` medem o cache de bytes; `shared_search_cache_hits`
mede resultados de provider reutilizados durante a geração. `cache_hits` e
`cache_misses` mantêm os valores do primeiro par como aliases compatíveis.
21 focados e **1003 completos em 178,60 s**, compileall e diff check passaram.
Ver [relatório F12](20261005-media-cache-metric-units.md).

## F13 — reconciliação de seleção e timeline (`50ba36d`)

`selection_render_reconciliation` mede a interseção, assets selecionados sem uso
na timeline, IDs da timeline ausentes na seleção e cobertura por identidade.
O campo só é observado com seleção e timeline conhecidas; backfill sem arquivo
recebe `None`, não uma lista vazia que gere falso zero. 41 focados e **1006
testes completos em 192,03 s** passaram; compileall e diff check passaram. A
métrica confirma planejamento visual, não a presença dos pixels no vídeo final.
Ver [relatório F13](20261005-selection-render-reconciliation.md).

## F14 — proveniência dos assets de segmento (`7bc5c23`, `94119e3`, `8daa29f`)

`VisualRenderUsage` carrega o resultado silencioso e `VisualRenderSceneUsage`
lista IDs solicitados, assets associados ao segmento, paths ausentes, omitidos,
fallback por cena e se o segmento foi reutilizado do cache, tanto no render por
timeline quanto no plano primário legado.
O contrato segue `RenderStageResult` até métricas; rerender/finalize e geração
humana registram a mesma estrutura. 62 focados e **1009 completos em 192,11 s**
passaram; compileall e diff check passaram.

Somente as 20 métricas mais recentes foram inspecionadas: todas são de
`teste-integracao`/`proj-review`, sem queries nem requests a providers. Elas não
servem de baseline de aquisição para H. Os detalhes e limite (não comprova
decodificação/frame) estão no [relatório F14](20261005-renderer-input-asset-usage.md).

## F4 — duração explícita da timeline visual (`11ac1f3`)

`VisualTimelineResult` inclui duração validada, medida desde o início do estágio
até a atualização das métricas. `pipeline.py` agrega essa duração como
`stage_times["visual_timeline"]`. Isso acrescenta observabilidade de uma etapa
sem alterar timers existentes. Focados: **16 passaram**; suíte integral:
**967 passaram em 191,41 s**. Compileall e diff check passaram. Não houve
geração real. F4 não conclui os lifecycle timers ou profile requerido na Fase H;
ver [relatório F4](20261005-visual-timeline-stage-timing.md).

## F5 — contrato compartilhado de elapsed (`e534ee3`)

Os resultados de research, script, scenes, audio, render e timeline agora usam
`validate_stage_elapsed`: segundos numéricos finitos e não negativos, com
booleanos rejeitados. Resultados anteriores tinham validações inconsistentes,
e alguns aceitavam elapsed sem validação. Valores válidos e chaves serializadas
permanecem iguais. Arquivos alterados: novo `src/curio/stage_timing.py`, seis
coordenadores/resultados de estágio e testes de contrato. **48 focados**
passaram; suíte completa: **977 em 191,23 s**; compileall e diff check
passaram. Não houve geração real. Consulte
[relatório F5](20261005-stage-elapsed-contract.md).

## Referências de relatórios

- [`Relatório de arquitetura e estado da migração até G85`](20261005-relatorio-arquitetura-estado-atual.md)
- [`Auditoria do pipeline e dos contratos`](../analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md)
- [`Resultados de execuções reais e limitações`](20261004-validacao-arquitetural-execucoes-reais.md)
- [`G74 — resultados tipados de aquisição`](20261005-candidate-acquisition-outcomes.md)
- [`G75 — aquisição de candidatos`](20261005-candidate-media-acquisition.md)
- [`G76 — tentativa técnica compartilhada`](20261005-shared-technical-acquisition-attempt.md)
- [`G77 — busca contextual após falha de aquisição`](20261005-generic-search-after-acquisition-failure.md)
- [`G78 — auditoria de queries adiadas`](20261005-deferred-query-audit-state.md)
- [`G79 — tópico/título e validação real pós-G78`](20261005-topic-title-separation-and-real-runs.md)
- [`G80 — contrato explícito de entrada do pipeline`](20261005-pipeline-input-contract.md)
- [`G81 — seleção tipada por cena`](20261005-scene-selection-typed-boundary.md)
- [`G82 — seleção criada de componentes tipados`](20261005-scene-selection-from-components.md)
- [`G83 — tipos estritos no contrato de entrada`](20261005-pipeline-input-strict-types.md)
- [`G84 — camada CLIP na avaliação de candidatos`](20261005-clip-layer-candidate-evaluation.md)
- [`G85 — auditoria visual baseada no VisualPlan`](20261005-visual-audit-from-visual-plan.md)
- [`G86 — política explícita da próxima tier de mídia`](20261005-selection-fallback-policy.md)
- [`G87 — ownership da provenance de seleção`](20261005-selection-provenance-owner.md)
- [`G88 — ownership da decisão visual`](20261005-visual-decision-audit-owner.md)
- [`G89 — avaliações tipadas na auditoria`](20261005-typed-candidate-evaluation-audit.md)
- [`G90 — rejeições técnicas tipadas`](20261005-typed-technical-rejections.md)
- [`G91 — outcomes de aquisição tipados`](20261005-typed-acquisition-rejections.md)
- [`G92 — projeções de rejeição tipadas`](20261005-typed-rejection-projections.md)
- [`G93 — prioridade de providers por cena`](20261005-provider-priority-per-scene.md)
- [`G94 — planos canônicos na busca por cena`](20261005-canonical-scene-search-plans.md)
- [`G95 — conectores ingleses e execuções reais`](20261005-english-entity-connectors-and-real-runs.md)
- [`F4 — duração do estágio de timeline visual`](20261005-visual-timeline-stage-timing.md)
- [`F5 — contrato compartilhado de duração de estágio`](20261005-stage-elapsed-contract.md)
- [`F6 — coleção imutável de tempos de etapa`](20261005-stage-timings-immutable-contract.md)
- [`F7 — duração desconhecida no backfill`](20261005-backfill-unknown-total-duration.md)
- [`F8 — fonte única da duração total live`](20261005-live-metric-total-duration.md)
- [`F9 — projeção única das métricas de seleção`](20261005-selection-metrics-single-projection.md)
- [`F10 — retries por operação`](20261005-media-retry-operation-metrics.md)
- [`F11 — timeout e falhas de provider`](20261005-media-timeout-error-separation.md)
- [`F12 — unidades explícitas de cache`](20261005-media-cache-metric-units.md)
- [`F13 — reconciliação seleção e timeline`](20261005-selection-render-reconciliation.md)
- [`F14 — assets dos segmentos visuais`](20261005-renderer-input-asset-usage.md)
- [`F15 — requests no limite de provider`](20261005-provider-request-metric-boundary.md)
- [`I1 — rerender real sem nova busca`](20261005-rerender-runtime-no-search.md)
- [`I2 — aquisição científica real pós-F15`](20261005-ciencia-real-pos-f15.md)
- [`Inventário de relatórios do projeto`](../README.md)
