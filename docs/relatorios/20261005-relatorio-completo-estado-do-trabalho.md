# Relatório completo do estado do trabalho — Curio

**Data:** 2026-10-05  
**Escopo:** estado da refatoração arquitetural no repositório até G79.
**Estado:** trabalho incompleto. Este documento registra evidências disponíveis
e não certifica a conclusão da refatoração. O worktree estava limpo após o
commit documental G78 (`885bf72`).

## Resumo do estado

O projeto já tinha módulos separados por etapa, mas ainda havia contratos
internos representados por mappings mutáveis e dados semanticamente duplicados.
As migrações recentes vêm mantendo valores tipados por mais tempo entre
planejamento, busca, avaliação, seleção, aquisição e persistência. G75–G79
extraíram aquisição técnica, unificaram uma tentativa técnica compartilhada,
corrigiram a continuação da busca contextual após falhas de aquisição,
melhoraram a auditoria de queries adiadas e separaram tópico de título em
`from-script`. Cada fase foi commitada e validada incrementalmente. As pendências
de ownership global, simplificação e validação real permanecem.

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

## Estado das fases do plano arquitetural

| Fase | Estado registrado | Pendências principais |
|---|---|---|
| R — resultado de pesquisa | R1–R2 concluídas segundo a auditoria, parcial no todo. | Imutabilidade do resultado e mutadores internos. |
| A — modelo semântico | A4a–A4v concluídas no escopo registrado. | Ownership restante de alias/contexto e compatibilidade externa controlada. |
| B — VisualPlan | B1–B4 concluídas no escopo registrado. | Consolidar políticas de gênero e ganchos sintéticos. |
| C — SearchPlan | C1 concluída. | Replays reais com providers saudáveis e revisão de qualidade. |
| D — candidato/avaliação/seleção | D1–D4 e convergência parcial até G79. | Unificar transições de fallback e simplificar o coordenador. |
| E — cache/artifact lifecycle | Parcial; E1–E7/E6 conforme inventário. | Lifecycle unificado e fronteiras restantes de rows. |
| F — métricas/estado | F1–F3 parciais. | Definições canônicas, `unknown/null` e conciliação seleção-render. |
| G — simplificação do pipeline | Parcial; G1, G3–G5, G7–G79 commitadas. | Separar tópico nos modos AI/TUI/queue; simplificar coordenador e limpar caminhos antigos após migração comprovada. |
| H — performance | Pendente. | Profile por planejamento, request/retry, download, dedupe, scoring e fallback. |
| I — validação/limpeza | Parcial. | Mais temas reais, fallback sem LLM, falhas, cache/rerender e inspeção visual. |

Os status são os registrados na auditoria e no relatório atualizado até G79. Não representam
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
- Validar rerender, cache, falha de LLM/provider e pelo menos dois domínios
  reais, com inspeção visual dos assets vencedores.
- Rodar suíte, compile/check e profile final sobre a revisão final efetivamente
  commitada. Não há evidência de conclusão dessas validações finais.

## Referências de relatórios

- [`Relatório de arquitetura e estado da migração até G79`](20261005-relatorio-arquitetura-estado-atual.md)
- [`Auditoria do pipeline e dos contratos`](../analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md)
- [`Resultados de execuções reais e limitações`](20261004-validacao-arquitetural-execucoes-reais.md)
- [`G74 — resultados tipados de aquisição`](20261005-candidate-acquisition-outcomes.md)
- [`G75 — aquisição de candidatos`](20261005-candidate-media-acquisition.md)
- [`G76 — tentativa técnica compartilhada`](20261005-shared-technical-acquisition-attempt.md)
- [`G77 — busca contextual após falha de aquisição`](20261005-generic-search-after-acquisition-failure.md)
- [`G78 — auditoria de queries adiadas`](20261005-deferred-query-audit-state.md)
- [`G79 — tópico/título e validação real pós-G78`](20261005-topic-title-separation-and-real-runs.md)
- [`Inventário de relatórios do projeto`](../README.md)
