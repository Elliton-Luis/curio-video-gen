# Relatório completo do estado do trabalho — Curio

**Data:** 2026-10-05  
**Escopo:** estado da refatoração arquitetural no repositório, incluindo a
fronteira de aquisição de mídia em andamento.  
**Estado:** trabalho incompleto. Este documento registra evidências disponíveis
e não certifica a conclusão da refatoração.

## Resumo do estado

O projeto já tinha módulos separados por etapa, mas ainda havia contratos
internos representados por mappings mutáveis e dados semanticamente duplicados.
As migrações recentes vêm mantendo valores tipados por mais tempo entre
planejamento, busca, avaliação, seleção e persistência. Até G74, essas mudanças
foram commitadas e validadas incrementalmente. A aquisição técnica ainda era
orquestrada em `visual.py`.

Na tentativa seguinte, começou-se a extrair esse loop para
`src/curio/stages/media_candidate_acquisition.py`. O arquivo aparece no
worktree como não rastreado, sem commit e sem validação registrada. Portanto,
essa extração não é uma fase concluída. O estado Git observado ao preparar este
relatório contém apenas esse arquivo não rastreado; não há outras alterações
locais reportadas por `git status --short`.

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

### Tentativa não concluída após G74

`src/curio/stages/media_candidate_acquisition.py` está presente como arquivo
não rastreado. A intenção era extrair de `visual.py` as tentativas concorrentes
de aquisição dos candidatos ranqueados e o fallback de reuso tardio, fazendo a
nova etapa devolver um lote de `CandidateAcquisitionOutcome` tipados. O
coordenador visual continuaria decidindo a sequência editorial (asset novo,
fallback sintético e, por último, reuso), e `media_acquisition` continuaria
responsável pelos detalhes técnicos de cache/download.

Essa tentativa não tem commit, não aparece nos relatórios de fase concluída e
não possui resultados de testes associados. Não há contrato de módulo
`CandidateAcquisitionBatch` certificado. O arquivo pendente não foi incluído
como parte concluída da arquitetura nem teve suas alterações desfeitas.

## Testes e validações atuais registradas

G70: 937 testes passaram e 1 teste foi desmarcado devido a HTTP 429 externo;
depois, 89 testes focados passaram. G71: 940 passaram, 1 desmarcado, suíte em
179,44 s; 88 focados. G72: 940 passaram, 1 desmarcado, em 179,23 s; 99
focados. G73: 940 passaram, 1 desmarcado, em 178,02 s; 99 focados. G74: 100
focados passaram; na suíte ampla, 941 passaram e 1 foi desmarcado após HTTP
429 da API real da Wikipédia, em 172,28 s. Para as fases commitadas também
foram registrados `python -m compileall -q src tests` e `git diff --check`
passando.

Esses números refletem a validação disponível de cada fase, não uma única
execução atual de toda a suíte depois de qualquer código não commitado. A
tentativa G75 (arquivo não rastreado) não foi validada. As falhas/deseleções
dependentes de rede não demonstram defeito do contrato, mas deixam esse caminho
externo sem prova determinística.

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
- **Aquisição:** G74 tipou o resultado por candidato, mas não extraiu a
  orquestração concorrente. O arquivo não rastreado da tentativa seguinte não
  pode ser considerado correção comprovada.

## Estado das fases do plano arquitetural

| Fase | Estado registrado | Pendências principais |
|---|---|---|
| R — resultado de pesquisa | R1–R2 concluídas segundo a auditoria, parcial no todo. | Imutabilidade do resultado e mutadores internos. |
| A — modelo semântico | A4a–A4v concluídas no escopo registrado. | Ownership restante de alias/contexto e compatibilidade externa controlada. |
| B — VisualPlan | B1–B4 concluídas no escopo registrado. | Consolidar políticas de gênero e ganchos sintéticos. |
| C — SearchPlan | C1 concluída. | Replays reais com providers saudáveis e revisão de qualidade. |
| D — candidato/avaliação/seleção | D1–D4 e partes da convergência concluídas até G74. | Unificar transições de fallback e simplificar o coordenador. |
| E — cache/artifact lifecycle | Parcial; E1–E7/E6 conforme inventário. | Lifecycle unificado e fronteiras restantes de rows. |
| F — métricas/estado | F1–F3 parciais. | Definições canônicas, `unknown/null` e conciliação seleção-render. |
| G — simplificação do pipeline | Parcial; G1, G3–G5, G7–G74 commitadas. | Extrair loop de aquisição; limpar caminhos antigos após migração comprovada. |
| H — performance | Pendente. | Profile por planejamento, request/retry, download, dedupe, scoring e fallback. |
| I — validação/limpeza | Parcial. | Mais temas reais, fallback sem LLM, falhas, cache/rerender e inspeção visual. |

Os status são os registrados na auditoria e no relatório G74. Não representam
aceite final dos objetivos amplos.

## O que estava sendo tentado corrigir na etapa de mídia

O trabalho imediatamente anterior ao pedido de relatório era uma extração de
responsabilidade, não uma alteração de relevância ou de critérios editoriais.
Em G74, o coordenador ainda mutava `dict` de candidato durante download para
anotar falhas, dimensões inválidas, hash duplicado, identidade final, ordem de
seleção e motivo de reuso. G74 substituiu esse canal implícito por
`CandidateAcquisitionOutcome`, ligado ao candidato ranqueado e ao snapshot do
asset, com projeções separadas para seleção e rejeição/auditoria.

A próxima tentativa pretendia mover o loop de downloads concorrentes e
tratamento técnico para `media_candidate_acquisition.py`, retornando resultados
tipados a `visual.py`. O objetivo era tornar explícita a transição:

```text
RankedSelectionCandidate
  → tentativa técnica de aquisição
  → CandidateAcquisitionOutcome
  → SelectedAsset ou row de rejeição/auditoria
```

O coordenador manteria a ordem de decisão editorial já acordada: buscar asset
novo elegível por representações/providers, tentar fallback sintético adequado
e considerar asset anterior somente como último fallback. A extração não deveria
afrouxar gates, tornar o sintético dominante, mudar providers, reescrever
queries nem introduzir serviços pagos/LLM por cena. A tentativa parou antes da
integração, execução dos testes e commit; portanto não há resultado “depois” para
essa extração.

## Incompleto para considerar a refatoração encerrada

- Validar ou descartar a extração pendente em uma etapa futura explicitamente
  retomada; a tentativa atual não foi integrada nem testada.
- Terminar as fases E–I conforme critérios da auditoria, incluindo ownership
  canônico para métricas/estado e simplificação dos coordenadores.
- Resolver e testar os falsos positivos semânticos históricos sem reduzir
  thresholds nem esconder falhas de provider.
- Executar geração real histórica após recuperação/controle da saúde de
  providers, reportando queries, providers, resultados, rejeições, winners,
  únicos, reusos, sintéticos e esgotamento da busca por cena.
- Validar rerender, cache, falha de LLM/provider e pelo menos dois domínios
  reais, com inspeção visual dos assets vencedores.
- Rodar suíte, compile/check e profile final sobre a revisão final efetivamente
  commitada. Não há evidência de conclusão dessas validações finais.

## Referências de relatórios

- [`Relatório de arquitetura e estado da migração até G74`](20261005-relatorio-arquitetura-estado-atual.md)
- [`Auditoria do pipeline e dos contratos`](../analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md)
- [`Resultados de execuções reais e limitações`](20261004-validacao-arquitetural-execucoes-reais.md)
- [`G74 — resultados tipados de aquisição`](20261005-candidate-acquisition-outcomes.md)
- [`Inventário de relatórios do projeto`](../README.md)
