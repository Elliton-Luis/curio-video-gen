# Relatório de arquitetura e estado de migração — Curio

**Data:** 2026-10-05
**Escopo:** auditoria documentada e migrações incrementais até G76.
**Estado:** em andamento; este relatório não certifica a conclusão da
refatoração integral.

## Arquitetura antes das migrações recentes

O Curio já separava fisicamente pesquisa, roteiro, cenas, contexto visual,
planejamento de busca, providers, aquisição, scoring, seleção, áudio, timeline,
render e métricas. A separação em módulos, porém, não garantia contratos
claros: fronteiras ainda passavam mappings e rows persistidas, dados
equivalentes apareciam duplicados, e loaders/consumidores podiam reconstruir
significado ou adaptar formatos sem ownership evidente.

Na cadeia visual, `SemanticScene` carregava representações e queries em
paralelo; `VisualPlan` também duplicava queries. Planejamento/contexto
compartilhavam detalhes internos de scoring/tokenização. Candidatos tipados
eram convertidos para dicionários durante avaliação. Avaliações e decisões de
seleção tinham menos invariantes do que as decisões que representavam. O
coordenador de mídia ainda compunha busca/aquisição com decisões editoriais e
fallbacks, apesar das extrações feitas.

## Fluxo real e arquitetura depois das migrações

Fluxo documentado a partir do código:

```text
CLI/TUI/config
  → pesquisa e fontes
  → roteiro/artefato de script
  → planejamento semântico de cenas + spans de timeline
  → contexto/enrichment semântico
  → VisualPlan
  → SearchPlan/SearchQuery
  → providers e aquisição técnica
  → Candidate + avaliação/rejeições
  → SelectionDecision (real novo, reuso, sintético ou ausência explícita)
  → plano temporal/visual
  → composição de áudio, legendas e render
  → metadata, métricas e artefatos de projeto
```

Os contratos tipados e validados cobrem várias transições semânticas e visuais.
`SemanticScene` contém apenas `representations` como plano de busca runtime; a
query legada é derivada ao serializar ou projetar para `Chapter`. O planejador
de busca emite queries tipadas. Candidatos permanecem tipados na avaliação. A
decisão de seleção valida coerência entre estado, provider, fallback e motivo
de reuso. Cache e artefatos mantêm adaptadores nas fronteiras históricas.

Nem todo o sistema segue esse fluxo sem exceções. A auditoria arquitetural
ligada no README contém inventário de módulos, responsabilidades, dependências,
fontes de verdade, fallbacks, cache, side effects, testes e plano detalhado por
fase. Este relatório resume o estado das migrações, não substitui o inventário.

## Commits estruturais recentes

| Commit | Resultado |
|---|---|
| `36cde9a` | Isolou projeção de compatibilidade de capítulos. |
| `0e206c9` | Fez o lote enriquecido de cenas ser saída de etapa. |
| `3de4f50`, `512efb9` | Isolaram e validaram entrada da etapa de render. |
| `04b3c86` | Centralizou projeção de metadados da execução assistida. |
| `695b5d5` | Moveu standby sem mídia para a etapa de mídia. |
| `67c8a9a` | Centralizou normalização compartilhada de cenas. |
| `a6ab140` | Impôs invariantes entre `SemanticScene` e representações/query persistida. |
| `9236956` | Validou contrato de planejamento visual. |
| `e6369ea` | Centralizou propriedade da tokenização compartilhada. |
| `9e0f725` | Validou `SearchQuery` e `SearchPlan`. |
| `b0f08b4` | Preservou `Candidate` tipado pela avaliação. |
| `8f1634e` | Validou resultados de avaliação de candidatos. |
| `063ee9e` | Documentou rerenders reais e inspeção visual pós-G54. |
| `52fa80b` | Validou estados de `SelectionDecision`. |
| `bbd49bf` | Removeu query duplicada de `VisualPlan`. |
| `31695f3` | Removeu `visual_queries` runtime de `SemanticScene`, preservando projeções legadas (G57). |
| `9f4e627` | Moveu a resolução e anotação de reuso cross-scene para `media_selection.py` (G58). |
| `05dc295` | Registrou no relatório de estado o commit G58. |
| `e652f64` | Fez `fetch_media_multi` retornar `MediaStageResult` e moveu a projeção de rows para a fronteira de persistência (G59). |
| `a7cabe0` | Moveu atualizações de reuse e sua projeção compatível para métodos do contrato `SceneMediaSelection` (G60). |
| `7a568aa` | Agrupou fatos da auditoria por query em `SearchQueryAudit` e centralizou a projeção ordenada por `SearchPlan` em `visual_audit.py` (G61). |
| `a51c06d` | Extraiu coleta e gates técnicos de candidatos por cena para `SceneCandidateCollector` (G62). |
| `73f6e6c` | Validou a decisão visual persistida e centralizou updates de seleção/reuso em `VisualDecision` (G63). |
| `519c1fa` | Substituiu o payload genérico interno por campos nomeados e imutáveis em `VisualDecision`, mantendo adaptadores JSON compatíveis (G64). |
| `28e4799` | Separou o acumulador mutável de auditoria por query do snapshot imutável emitido pela coleta (G65). |
| `8bed5ec` | Fez `Candidate` capturar `ProviderAssetSnapshot` imutável, preservando `MediaAsset` mutável no lifecycle de aquisição (G66). |
| `833df32` | Congelou recursivamente evidência de `CandidateEvaluation` e manteve a projeção para seleção como cópia independente (G67). |
| `0e62a18` | Unificou snapshots de assets e congelou recursivamente rows da seleção, preservando a projeção JSON (G68). |
| `1d1335f` | Manteve `SelectedAsset` tipado em candidatos de reuso cross-scene até decidir o donor (G69). |
| `dd19b24` | Introduziu `RankedSelectionCandidate` e tipou `SelectionPool`; CLIP atualiza evidência imutável e auditoria associa rejeições pós-aquisição por identidade (G70). |
| `d8dace3` | Faz `make_selection_decision` consumir `SelectedAsset` com query, origem e representação tipadas (G71). |
| `ec61c65` | Mantém os assets escolhidos como `SelectedAsset` até a projeção para auditoria e persistência (G72). |
| `7b965a1` | Mantém shortlist e reserva de reuso como `RankedSelectionCandidate` até cada tentativa de aquisição (G73). |
| `57a9a21` | Modela sucesso/falha técnica por candidato como `CandidateAcquisitionOutcome`, com projeções distintas para seleção e auditoria (G74). |
| `c4ef8c5` | Extrai tentativas de aquisição dos candidatos ranqueados para `media_candidate_acquisition.py`; fallback editorial permanece em `visual.py` (G75). |
| `b87ba98` | Unifica download/cache/validação dimensional dos caminhos fresh e reuse por `TechnicalAcquisitionAttempt` (G76). |

Commits anteriores e detalhes de cada fase estão no histórico Git e nos
relatórios listados em `docs/README.md`.

## Contratos e fontes de verdade

- **Semântica de cena:** `SemanticScene`; `representations` é a fonte runtime
  das queries específicas. `visual_queries` é dado serializado derivado e
  campo de compatibilidade em `Chapter`.
- **Contexto global:** `VideoContext`, consumido por planejamento e enrichment;
  aliases verificados e proveniência orientam expansão de busca.
- **Plano visual:** `VisualPlan`; não carrega narração nem duplica queries.
- **Busca:** `SearchPlan`/`SearchQuery`; texto, origem, tipo, variante e nível
  são explícitos. O search planner é o dono da geração.
- **Resultado de provider:** `Candidate` tipado e ligado à busca, contendo
  `ProviderAssetSnapshot`; o objeto técnico `MediaAsset` segue mutável durante
  download/cache e atualizações pós-seleção. Provider normaliza resposta e não
  decide relevância editorial.
- **Avaliação:** `CandidateEvaluation`/`EvaluationBatch`; reporta score e
  rejeições com evidência JSON recursivamente imutável, sem gerar query ou
  decidir fallback editorial. `with_clip_score()` retorna uma avaliação nova;
  `to_selection_entry()` projeta cópia editável.
- **Shortlist ranqueada:** `RankedSelectionCandidate` reúne avaliação aceita e
  snapshot do asset preparado. Score CLIP tem fonte única na evidência da
  avaliação. `SelectionPool` divide somente candidatos tipados entre novos e
  reutilizados; a projeção JSON ocorre na transição ao lifecycle legado de
  aquisição/seleção.
- **Seleção:** `SelectionDecision`; distingue asset novo, reuso, sintético e
  ausência, com motivo/fallback validado. `MediaStageResult`/`SceneMediaSelection`
  expõem `MediaAssetSnapshot` e rows aninhadas imutáveis; `to_dict()` é adapter.
  `SelectedAsset` preserva `query`, `query_source` e `representation`; a
  política que cria `SelectionDecision` recebe esse contrato, não reinterpreta
  row JSON.
- **Auditoria da decisão visual:** `VisualDecision` contém `SelectionDecision`
  tipada, valida campos conhecidos e mantém as extensões legadas na projeção.
- **Auditoria de busca:** `QueryAuditAccumulator` acumula fatos mutáveis dentro da aquisição; `SearchQueryAudit` e a tabela da `SceneCandidateCollection` são snapshots imutáveis, projetados no JSON existente.
- **Tempo:** `TimelineSpan` e contratos temporais; cenas semânticas não devem
  carregar duração ou timestamps de render.
- **Persistência:** `Chapter` e artefatos antigos continuam formato de projeto
  e projeção. Adaptações legadas pertencem às fronteiras.
- **Métricas e estado:** owners e definições globais permanecem parciais; os
  relatórios live e backfill ainda requerem consolidação.

## Arquivos alterados nas fases G57–G74

Implementação G57: `src/curio/stages/scene_contract.py`, `scene_projection.py`,
`scenes.py`, `visual_context.py`, `scoring.py`, `visual_timeline.py`,
`media_rules.py` e `review.py`.

Implementação G58: `src/curio/stages/visual.py` e
`src/curio/stages/media_selection.py`.

Implementação G59: `src/curio/stages/visual.py`,
`src/curio/stages/media_selection.py` e `src/curio/pipeline_visual.py`.

Implementação G60: `src/curio/media/selection_result.py` e
`src/curio/stages/media_selection.py`.

G61 (`7a568aa`): `src/curio/stages/visual.py`,
`src/curio/stages/visual_audit.py` e `tests/test_visual_audit.py`. A mudança
substitui dicts/sets paralelos para fatos de auditoria por query por um registro
`SearchQueryAudit`, e deixa `visual_audit.py` projetar estados na ordem do
`SearchPlan`. O coordenador ainda executa busca/aquisição; G61 não conclui sua
extração.

G62 (`a51c06d`): `src/curio/stages/scene_candidate_search.py`,
`src/curio/stages/candidate_evaluation.py`, `src/curio/stages/visual.py` e
`tests/test_scene_candidate_search.py`. `SceneCandidateCollector` consome
`VisualPlan` e `SearchPlan`, executa queries por providers ordenados,
deduplica, aplica gates técnicos e retorna `SceneCandidateCollection` com
candidatos e rejeições tipados e auditoria por query. A avaliação adiciona
evidência semântica às rejeições sem alterar os gates.

Testes: `tests/test_scene_contract.py`, `test_visual_contracts.py`,
`test_visual_model.py`, `test_visual_context.py`, `test_visual_director.py`,
`test_visual_asset_usage.py`, `test_visual_topic_anchor.py` e
`test_black_hole.py` (G57); `tests/test_media_diag.py` e
`tests/test_media_selection.py` (G58); `tests/test_media_diag.py`,
`tests/test_media_selection.py`, `tests/test_pipeline_integration.py`,
`tests/test_pipeline_visual.py` e `tests/test_standby_flow.py` (G59);
`tests/test_media_selection.py` (G60); `tests/test_visual_audit.py` (G61,
preservando os dois testes anteriores e adicionando três casos);
`tests/test_scene_candidate_search.py` (G62, cinco regressões de contrato).
`tests/test_visual_decision.py` (G63: round-trip, preservação de extensões,
updates imutáveis, tipos dos campos conhecidos e seleção obrigatória; G64:
atributos explícitos, imutabilidade recursiva e rejeição de campos desconhecidos).

G63 (`73f6e6c`): `src/curio/media/visual_decision.py`,
`src/curio/media/selection_result.py`, `src/curio/pipeline_media.py`,
`src/curio/pipeline_visual.py`, `src/curio/stages/media_selection.py`,
`src/curio/stages/visual.py` e `tests/test_visual_decision.py`.

G64 (`519c1fa`): `src/curio/media/visual_decision.py` e
`tests/test_visual_decision.py`.

G65 (`28e4799`): `src/curio/stages/visual_audit.py`,
`src/curio/stages/scene_candidate_search.py`, `tests/test_visual_audit.py` e
`tests/test_scene_candidate_search.py`.

G66 (`8bed5ec`): `src/curio/stages/media_contracts.py` e
`tests/test_media_contracts.py`. G67 (`833df32`) também altera esses dois
arquivos; adiciona freeze/thaw recursivo para a evidência de avaliação.

G68 (`0e62a18`): cria `src/curio/media/asset_snapshot.py`; altera
`src/curio/media/selection_result.py`, `src/curio/stages/media_contracts.py`,
`src/curio/stages/review.py` e os testes `test_media_contracts.py` e
`test_media_selection.py`. G69 (`1d1335f`) altera `src/curio/stages/media_selection.py`
e `tests/test_media_selection.py`.

G75 (`c4ef8c5`): `src/curio/stages/media_candidate_acquisition.py` (novo),
`src/curio/stages/visual.py` e `tests/test_media_selection.py`. O lote
`CandidateAcquisitionBatch` é imutável; o módulo executa tentativas concorrentes,
gates técnicos pós-download e outcomes. `visual.py` mantém a ordem de fallback
fresh → sintético → reuso. A aquisição ainda atualiza métricas/logging e consulta
uso cross-scene para deduplicação; esses owners seguem como dívida registrada.
G76 (`b87ba98`) altera `media_candidate_acquisition.py` e
`tests/test_media_selection.py`. A operação de download/cache e validação de
dimensões agora é compartilhada e emite `TechnicalAcquisitionAttempt`; o
tratamento de rejeições fresh e a decisão de reuse continuam distintos.

Documentação e navegação: `README.md`, `docs/README.md`, a auditoria
`docs/analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md`, este
relatório e os relatórios G57–G70.


## Estado das fases

| Fase | Estado | Trabalho restante relevante |
|---|---|---|
| R — resultado de pesquisa | R1–R2 concluídas segundo a auditoria. | Imutabilidade do resultado e mutadores internos. |
| A — modelo semântico | A1–A4v concluídas; G57 removeu o mirror runtime. | Auditar ownership restante de alias/contexto e manter compatibilidade externa controlada. |
| B — VisualPlan | B1–B4 concluídas no escopo registrado. | Consolidar políticas de gênero e ganchos sintéticos sem contaminação. |
| C — SearchPlan | C1 concluída. | Replays reais para saúde/qualidade de providers. |
| D — candidate/evaluation/selection | D1–D4 concluídas; convergência G parcial. | Fazer fallbacks convergirem e seguir simplificando o coordenador. |
| E — cache/artifact lifecycle | E1–E7 e E6 concluídas conforme auditoria; fase parcial. | Unificar lifecycle e remover boundary de seleção ainda em dicionários. |
| F — métricas/estado | F1–F3 parciais. | Definições canônicas, unknown/null consistente e reconciliação seleção-render. |
| G — simplificação do pipeline | G1, G3–G5 e G7–G76 commitadas; parcial. | `visual.py` ainda possui a política de fallback; acquisition conserva janela/futures, effects de metrics/logging e dedupe por uso global. Coordenadores das demais etapas ainda precisam convergir/remover adapters temporários. |
| H — performance | Pendente. | Medir planejamento, requests/retries, download, dedupe, scoring e fallback antes de otimizar. |
| I — validação e limpeza | Parcial. | Aquisição nova em domínios distintos, pessoa/etimologia, no-LLM, falhas, cache, rerender e inspeção visual. |

Detalhes, arquivos, riscos e critérios por fase estão na auditoria. O estado
indica conclusão parcial, não certificação dos requisitos arquiteturais todos.

## Testes e validação registrados

G57: **249 testes focados passaram**; suíte integral: **913 passaram em
205,78 s**. G58: **60 testes focados passaram**; suíte integral: **913
passaram em 210,52 s**. G59: testes focados de integração, **91 passaram**;
com a regressão direta de produtor tipado, conjunto de contrato/produtor,
**39 passaram**; suíte integral: **914 passaram em 189,20 s**. Em todas as
fases, `python -m compileall -q src tests` e `git diff --check` passaram.
G60: **46 testes focados passaram**; suíte integral: **915 passaram em
187,94 s**. Uma
execução integral de G57 anterior à correção dos testes foi interrompida em
640 passados e não é usada como prova.

G61: **132 testes focados passaram** e a suíte integral passou com **918
testes em 180,48 s**. Após o commit, os 132 focados passaram novamente, junto
com `python -m compileall -q src tests` e `git diff --check`. A suíte integral
foi executada no mesmo conteúdo de implementação antes do commit.
G62: **141 testes focados passaram**, e a suíte integral passou com **923
testes em 184,66 s**. Depois das últimas validações do contrato, 16 testes
focados passaram novamente; compileall e diff check também passaram.
G63: **124 testes focados passaram** e **929 testes passaram** na suíte integral
com `test_standby_sem_imagens` excluído. Esse teste fez request real à API da
Wikipédia e recebeu HTTP 429; na primeira rodada do lote, os outros 109
passaram. `python -m compileall -q src tests` e `git diff --check` passaram.
G64: **31 testes focados passaram**; suíte: **930 passaram, 1 excluído** por
HTTP 429 da API real da Wikipédia. `python -m compileall -q src tests` e
`git diff --check` passaram. Não houve nova geração real nesta fase.
G65: **21 testes focados passaram**; suíte ampla: **932 passaram, 1 excluído**
pelo HTTP 429 da API real da Wikipédia, em 177,87 s. Compileall e diff check
passaram. Não houve geração real nesta fase.
G66: **55 testes focados passaram**; suíte ampla: **933 passaram, 1 excluído**
pelo HTTP 429 da API da Wikipédia, em 177,65 s. Compileall e diff check
passaram. Não houve geração real nesta fase.
G67: **28 testes focados passaram**; suíte ampla: **934 passaram, 1 excluído**
pelo HTTP 429 da API da Wikipédia, em 179,60 s. Compileall e diff check
passaram. Não houve geração real nesta fase.
G68: **70 testes focados passaram**; suíte ampla: **935 passaram, 1 excluído**
pelo HTTP 429 da API da Wikipédia, em 178,39 s. Compileall e diff check
passaram. Não houve geração real nesta fase.
G69: **63 testes focados passaram**; suíte ampla: **936 passaram, 1 excluído**
pelo HTTP 429 da API da Wikipédia, em 178,81 s. Compileall e diff check
passaram. Não houve geração real nesta fase.
G70: **89 testes focados passaram**; a suíte ampla passou com **937 testes e 1
excluído** por HTTP 429 da Wikipédia em 179,65 s; esse gate ocorreu antes da
inclusão do último teste unitário de rejeição de rows untyped, validado na
bateria focada subsequente. Compileall e diff check passaram após esse teste.
Não houve geração real nesta fase.
G71: **88 testes focados passaram**; a suíte ampla passou com **940 testes e 1
excluído** por HTTP 429 da Wikipédia em 179,44 s. Compileall e diff check
passaram. Não houve geração real nesta fase.
G72: bateria de seleção visual, auditoria, integração/pipeline: **99 testes**;
suíte ampla: **940 passaram, 1 excluído** por HTTP 429 da Wikipédia em 179,23 s.
Compileall e diff check passaram; sem geração real.
G73: a mesma bateria de seleção visual/pipeline/auditoria: **99 testes**;
suíte ampla: **940 passaram, 1 excluído** por HTTP 429 da Wikipédia em 178,02 s.
Compileall e diff check passaram; sem geração real.
G74: bateria focada de seleção, auditoria, direção visual e pipeline:
**100 passaram**; suíte ampla: **941 passaram, 1 excluído** por HTTP 429 da
Wikipédia em 172,28 s. Compileall e diff check passaram; sem geração real.
G75: bateria focada: **102 passaram**; suíte ampla: **943 passaram, 1
desmarcado** por HTTP 429 da Wikipédia em **171,12 s**. Compileall e diff check
passaram; sem geração real. Ver [relatório G75](20261005-candidate-media-acquisition.md).
G76: **103 focados**; suíte ampla: **944 passaram, 1 desmarcado** por HTTP 429
da Wikipédia em **171,65 s**. Compileall e diff check passaram; sem geração
real. Ver [relatório G76](20261005-shared-technical-acquisition-attempt.md).

Gates anteriores registrados: G49 908; G50/G51 910; G52 912; G53 913; G54
914; G55/G56 915. A mudança nos totais acompanha alterações do conjunto de
testes; cada relatório de fase contém seu gate correspondente.

## Validação real de mídia disponível

`20261005-pos-g54-validacao.md` registra rerenders de projetos existentes, sem
nova pesquisa, aquisição ou TTS:

- **Mohács:** 3 cenas, 2 IDs reais únicos, 0 reusos e 2 sintéticos, 26,27 s.
  Inspeção encontrou duas fotos modernas do Parlamento de Budapeste escolhidas
  para a batalha; é uma falha editorial aberta.
- **Buracos negros/ciência:** 3 cenas, 3 IDs reais únicos, 0 reusos e 0
  sintéticos, 27,50 s. Assets inspecionados foram distintos e pertinentes.

Esses rerenders validam render/compatibilidade, não aquisição nova nem saúde
atual dos providers. A auditoria registra indisponibilidade de Met/AIC e
timeouts Wikimedia em execuções históricas.

## Incompleto e próximos passos

1. Continuar extraindo responsabilidades do coordenador de mídia em fases
   pequenas, deixando busca, aquisição técnica, avaliação, seleção e fallback
   com owners explícitos.
2. Consolidar estado/cache/metadata/métricas sem converter desconhecido em
   zero e sem tornar cache uma preferência editorial.
3. Medir tempos por etapa antes de mudar paralelismo ou estratégia de busca.
4. Validar aquisição nova em domínios diferentes, falha de LLM/provider,
   rerender e cache; registrar queries, providers, candidatos, IDs únicos,
   reusos, sintéticos, rejeições e duração.
5. Corrigir a seleção editorial inadequada de Mohács na etapa responsável, com
   regressão sem enfraquecer gates semânticos.
6. Remover compatibilidade interna morta somente após migrar consumidores;
   preservar formatos externos que continuam necessários.

G57–G70 passam os gates registrados. Auditoria integral, ownership único de
todas as decisões e validação final permanecem objetivos abertos.

## G61 — ownership da auditoria por query (`7a568aa`)

Antes desta mudança, `visual.py` reunia para cada query resultados, duplicatas,
rejeições, elegibilidade, providers, erros, estado de execução e contadores em
mappings e conjuntos paralelos. A montagem da linha de auditoria também era
responsabilidade do coordenador. Isso tornava possível que a busca continuasse
correta, mas que o relatório divergisse ou perdesse proveniência ao se alterar
um dos acumuladores.

A mudança local introduz `SearchQueryAudit` em
`src/curio/stages/visual_audit.py`, com métodos explícitos para registrar
resultados, erros, duplicatas, rejeições, elegibilidade e queries não
executadas. `search_query_audit_rows()` verifica que há estado para exatamente
as queries do `SearchPlan` e projeta as linhas na ordem do plano. `visual.py`
agora coordena requests e atualiza esses registros, sem os antigos containers
paralelos para os mesmos fatos. `candidate_audit_rows()` continua responsável
pela projeção da auditoria dos candidatos.

Arquivos alterados pelo commit `7a568aa`: `src/curio/stages/visual.py`,
`src/curio/stages/visual_audit.py` e `tests/test_visual_audit.py`. Os testes
adicionados cobrem proveniência por provider, resultados/erros, duplicata,
rejeição e elegibilidade; distinção entre somente duplicatas e query não
executada por orçamento; e rejeição de plano sem estado correspondente. Os
dois testes anteriores de auditoria de candidatos foram preservados.

Esta é uma extração da responsabilidade de acumular e projetar auditoria, não
uma nova política de busca. Não altera queries, ordem de providers, gates,
scoring, seleção, fallback nem comportamento editorial. A busca e aquisição
continuam orquestradas em `visual.py`, portanto esse ownership ainda é
incompleto. Não foi executada nova geração real nesta etapa. Commit:
`7a568aa`.

## G62 — coleta de candidatos por cena (`a51c06d`)

Antes de G62, `_search_scene_with_shortcircuit()` mantinha o estado de queries,
executava a travessia de providers, deduplicava resultados e aplicava gates
técnicos antes de chamar os avaliadores. G62 move essa coleta para
`SceneCandidateCollector` em `scene_candidate_search.py`. A entrada exige
`VisualPlan` e `SearchPlan`; `SceneCandidateCollection` valida cobertura das
queries auditadas, vínculo dos candidatos ao plano e identidade sem duplicatas.
Uma instância mantém orçamento e dedupe entre consultas específicas e a fase
genérica tardia.

O coletor não gera queries, calcula ranking nem escolhe fallback. Ele emite
`CandidateRejection` técnico. `candidate_evaluation.py` acrescenta evidência
semântica apenas para auditoria, sem alterar a decisão do gate. A ordem dos
providers, cache da execução, limites, métricas, reuso, downloads e seleção
foram preservados.

Arquivos do commit: `src/curio/stages/scene_candidate_search.py`,
`src/curio/stages/candidate_evaluation.py`, `src/curio/stages/visual.py` e
`tests/test_scene_candidate_search.py`. Os testes verificam dedupe entre
queries, snapshot da auditoria, orçamento, query fora do plano e rejeição
técnica tipada com evidência projetada. A suíte integral passou com 923 testes;
não houve geração real nesta etapa. `visual.py` segue coordenando avaliação,
downloads/seleção, fallback e montagem final da auditoria; G62 reduziu sua
responsabilidade de aquisição, mas não conclui G.

## G63 — contrato para a decisão visual (`73f6e6c`)

Antes de G63, os caminhos de aquisição normal, fallback tipográfico e mídia
manual construíam dicts `visual_decision`; o registro de mídia os guardava como
dict e os updates de reuso cross-scene e troca manual alteravam campos no
payload diretamente. A fonte tipada existia apenas para a seleção aninhada.

`VisualDecision` envolve um `SelectionDecision` validado, verifica tipos dos
campos de auditoria conhecidos, preserva chaves legadas desconhecidas e
serializa no mesmo schema. `SceneMediaSelection` agora mantém esse contrato em
memória. Reuso cross-scene e swap manual atualizam seleção, fallback e resumo
do asset via `with_selection()`. Produtores normal, sintético e manual constroem
o envelope com `VisualDecision.create()`; métricas projetam explicitamente
para dict no limite externo.

Arquivos: `src/curio/media/visual_decision.py`,
`src/curio/media/selection_result.py`, `src/curio/pipeline_media.py`,
`src/curio/pipeline_visual.py`, `src/curio/stages/media_selection.py`,
`src/curio/stages/visual.py` e `tests/test_visual_decision.py`. Validação:
124 testes focados passaram; 929 testes passaram com o caso externo
`test_standby_sem_imagens` excluído porque a API da Wikipédia respondeu HTTP
429. Compileall e diff check passaram. A primeira execução desse lote também
passou nos demais testes antes de falhar nesse request externo. Não houve nova
geração de vídeo.

Limite registrado ao final de G63: os campos de auditoria eram mappings JSON,
com extensões preservadas por compatibilidade. G64 nomeia os campos conhecidos,
mas cada linha de query/candidato ainda não tem dataclass própria.


## G64 — campos explícitos em `VisualDecision` (`519c1fa`)

G63 havia validado a decisão aninhada e os tipos dos campos conhecidos, mas o
envelope continuava armazenando os fatos conhecidos dentro de um mapping
genérico. Isso mantinha acesso por chave como representação interna e deixava
consumidores dependentes de payload arbitrário.

G64 declara os campos conhecidos como atributos (`topic`, `visual_plan`,
`visual_intent`, entidades, representações, aliases, queries, providers,
candidatos, seleção, fallback e estado/razão de esgotamento). A criação por
produtores rejeita nomes desconhecidos; a leitura legada preserva extensões. A presença é registrada para serializar sem converter campo ausente em `null`.
Mappings e sequências são congelados recursivamente e `to_dict()` gera uma cópia
JSON mutável.

Arquivos: `src/curio/media/visual_decision.py` e
`tests/test_visual_decision.py`. Passaram 31 testes focados e a suíte com 930
passados/1 excluído após HTTP 429 na API real da Wikipédia; compileall e diff
check também passaram. Não houve geração real nesta fase. Query/candidate rows
continuam mappings JSON e a decisão segue projetada no formato persistido
histórico. Commit: `519c1fa`.

## Escopo exato do trabalho de mídia em andamento

G64 não tentava ajustar relevância, thresholds ou providers. O objetivo era
continuar a migração estrutural após as regressões de repetição e queries ruins:
fazer cada fronteira entregar contrato válido e impedir que o coordenador
reconstrua ou altere silenciosamente a decisão de uma etapa anterior.

G61 centralizou o acúmulo/projeção de auditoria por query; G62 isolou coleta de
candidatos, deduplicação e gates técnicos; G63 introduziu `VisualDecision` como
owner da decisão e dos updates de seleção/reuso. A tarefa imediata era remover o
mapping genérico restante desse contrato e nomear os fatos já persistidos, sem
mudar a estratégia de consulta ou seleção editorial. Permanecem incompletos os
contratos individuais de rows de query/candidato, a orquestração ainda
concentrada em `visual.py`, a centralização total de fallback e novas
validações reais de provider/aquisição.

Regressões históricas a preservar e revalidar: país irrelevante em narrativa
histórica (Argentina na Revolução Francesa); Mughal Empire associado a Marco Aurélio; ônibus em buraco negro; queries soltas como `gold`, `formavam` e
`primeira`; contaminação entre gêneros (`laboratory`, `microscope`); repetição
de mapa entre cenas; fallback após falha/JSON inválido/timeout de LLM; cache
antigo ou malformado; dedupe depois de download; rerender sem nova pesquisa; e
indisponibilidade, timeout ou HTTP 429 de providers.

G64 não reexecutou aquisição histórica nem inspecionou assets, portanto não
apresenta contagem atual de cenas/assets como validação da busca. Os resultados
históricos disponíveis e suas limitações estão nos relatórios de execução
listados em `docs/README.md`.


## G65 — snapshot imutável da auditoria por query (`28e4799`)

Antes da mudança, `SceneCandidateCollection` era frozen e a tabela externa de
auditoria era um proxy, mas cada valor continuava sendo um `SearchQueryAudit`
mutável. O consumidor conseguia alterar fatos de provider/resultados após a
aquisição; uma instância construída diretamente também podia reter um mapping
externo mutável. Isso enfraquecia o snapshot entre aquisição e projeção.

G65 separa `QueryAuditAccumulator`, mutável dentro da coleta, de
`SearchQueryAudit`, um snapshot frozen com escalares e tuplas.
`SceneCandidateCollection.__post_init__` copia e congela o mapping fornecido e
valida o tipo dos snapshots. `search_query_audit_rows()` passa a aceitar apenas
estados imutáveis e continua projetando o schema JSON existente.

Arquivos: `src/curio/stages/visual_audit.py`,
`src/curio/stages/scene_candidate_search.py`, `tests/test_visual_audit.py` e
`tests/test_scene_candidate_search.py`. Os testes verificam campos/provider
imutáveis, isolamento do snapshot enquanto o acumulador avança, congelamento da
tabela externa e projeção compatível. Foram 21 testes focados e 932 testes
passaram na suíte ampla, com `test_standby_sem_imagens` excluído por HTTP 429
da API da Wikipédia; compileall e diff check passaram. Não houve geração real nem
mudança na estratégia de busca, providers, gates, scoring, seleção ou fallback.
Commit: `28e4799`.


## G66 — snapshot imutável do resultado do provider (`8bed5ec`)

G65 tornou imutável a tabela de auditoria da coleção, mas a inspeção de seus
outros membros encontrou outro alias mutável: `Candidate` frozen retinha um
`MediaAsset` mutável, incluindo listas editáveis para tags/categorias. Isso
permitia que o objeto original recebido do provider alterasse retrospectivamente
a evidência da coleção. `MediaAsset`, porém, é o modelo do lifecycle de bytes: o
download enriquece dimensão/tamanho/caminho, e a seleção atribui `used_in`;
congelar esse modelo global quebraria essas responsabilidades.

G66 inicialmente criou `ProviderAssetSnapshot`, depois unificado por G68 em
`MediaAssetSnapshot` em `curio.media.asset_snapshot`. `Candidate.__post_init__`
captura esse snapshot ao receber um `MediaAsset`. `to_dict()` preserva os campos/formatos consumidos por
`to_evaluation_input()`; o lifecycle técnico continua usando o `MediaAsset`
original ou uma reconstrução mutável a partir do dict.

Arquivos: `src/curio/stages/media_contracts.py` e
`tests/test_media_contracts.py`. A regressão comprova isolamento contra mudança
de título/tags/caminho local e imutabilidade do snapshot, preservando acesso
compatível à avaliação. **55 testes focados** passaram; a suíte ampla passou com
**933 testes e 1 excluído** por HTTP 429 da API externa. `compileall` e diff check
passaram. Não houve geração real. Commit: `8bed5ec`.


## G67 — evidência imutável da avaliação (`833df32`)

A avaliação era `frozen`, mas retinha `evidence` como `Mapping` arbitrário.
Como o scorer inclui mappings e listas nested, um consumidor podia alterar a
evidência depois da decisão. G67 congela a árvore recursivamente no
`CandidateEvaluation.__post_init__` (mappings para proxies de leitura e
sequências para tuplas). `to_selection_entry()` transforma esse snapshot em
dicts/listas independentes para a etapa seguinte; mutations editoriais locais
não propagam de volta para a avaliação.

Arquivos: `src/curio/stages/media_contracts.py` e
`tests/test_media_contracts.py`. Regressão confirma isolamento quando o mapping
de origem é alterado, impede mutações nested e verifica que a projeção tem a
forma JSON/listas esperada e não compartilha memória. **28 testes focados** e
**934 testes da suíte ampla** passaram; um teste externo foi excluído por HTTP
429 da Wikipédia. Compileall e diff check passaram. Não houve geração real.
Commit: `833df32`.


## G68 — snapshots imutáveis do resultado de seleção (`0e62a18`)

A inspeção dos consumidores mostrou que `SelectedAsset` e `SceneMediaSelection`
eram frozen externamente, mas continham `MediaAsset` mutável, rows persistidas
como dict e dados de score/rejeição/reuso nested mutáveis. Assim, o valor tipado
podia divergir de sua projeção persistida ou mudar por alias. A revisão também
exigia rows dict como formato de entrada.

G68 centraliza o snapshot de G66 em `media/asset_snapshot.py` como
`MediaAssetSnapshot`, usado tanto por `Candidate` quanto por ativos em seleção.
`SelectedAsset` e `SceneMediaSelection` congelam recursivamente score details,
rejected/reuse e row original; `to_dict()` retorna cópia independente em JSON.
A conversão `ReviewMediaPlan.from_media_result()` projeta rejeições explicitamente
para o contrato do review. O ciclo de download segue usando `MediaAsset` mutable.

Arquivos: `src/curio/media/asset_snapshot.py`,
`src/curio/media/selection_result.py`, `src/curio/stages/media_contracts.py`,
`src/curio/stages/review.py`, `tests/test_media_contracts.py` e
`tests/test_media_selection.py`. Os testes cobrem mutations de rows originais e
projetados, aninhamento, reuso, review e render. **70 testes focados** e **935
testes amplos** passaram; um teste foi excluído pelo HTTP 429 recorrente da API
externa. Compileall e diff check passaram; sem geração real. Commit: `0e62a18`.


## G69 — donor cross-scene tipado (`1d1335f`)

`ReuseCandidate` tinha campo `entry: dict`, embora o candidato fosse construído
a partir de um `SelectedAsset` validado e imutável. G69 mantém o objeto tipado
no resultado da elegibilidade e na ordenação do donor. A projeção mutável
`to_dict()` só ocorre após a decisão de qual candidato reutilizar, imediatamente
antes de compor a nova seleção receptora. `ReuseCandidate` rejeita agora payloads
JSON genéricos. Não altera relevância, ranking ou política de reuso.

Arquivos: `src/curio/stages/media_selection.py` e
`tests/test_media_selection.py`. **63 testes focados**, **936 testes amplos** e
um teste excluído por HTTP 429 na API da Wikipédia; compileall e diff check
passaram. Nenhuma geração real.

A dívida adjacente permanece em `SelectionPool` e em `visual.py`: as listas de
candidatos durante CLIP, aquisição de bytes, dedupe por hash e seleção são dicts
editáveis que representam transições de estado. A próxima migração deve
especificar esse lifecycle antes de substituir o formato. Commit: `1d1335f`.


## G70 — shortlist tipada de seleção (`dd19b24`)

G69 havia deixado uma fronteira concreta: após a avaliação, `SelectionPool` e o
passe opcional de CLIP usavam rows mutáveis para carregar score, asset baixado e
estado de reuso. G70 introduz `RankedSelectionCandidate`, que associa
`CandidateEvaluation` a `MediaAssetSnapshot` e mantém esse tipo durante CLIP,
ordenação e separação entre assets novos e reutilizados. `CandidateEvaluation`
é a fonte única do score e da evidência CLIP; `SelectionPool` rejeita entradas
que não sejam candidatos ranqueados tipados. A projeção JSON só ocorre na
fronteira com o restante do lifecycle legado de aquisição/seleção.

A migração revelou que a auditoria pós-download dependia de aliasing acidental:
a row avaliada e a row posteriormente mutada eram o mesmo dict. Ao removê-lo,
uma rejeição por resolução aparecia como `not_selected`. G70 associa a rejeição
de lifecycle à identidade estável do candidato e preserva uma razão de auditoria
explícita, sem compartilhar dicts entre avaliação e seleção. A correção também
registra falha de download como rejeição auditável. Não altera queries, gates,
thresholds, ranking editorial, fórmula CLIP ou política de reuso.

Arquivos: `src/curio/stages/media_contracts.py`,
`src/curio/stages/media_selection.py`, `src/curio/stages/visual.py`,
`src/curio/stages/visual_audit.py` e `tests/test_media_selection.py`.
Regressões cobrem score CLIP e snapshot preparado imutáveis, rejeição de rows
untyped em `SelectionPool` e classificação/auditoria da falha de resolução
pós-download. Passaram **89 testes focados**, `compileall` e `git diff --check`;
a suíte ampla passou com **937 testes em 179,65 s** e um teste externo
desselecionado por HTTP 429 da Wikipédia (o gate integral antecedeu a inclusão
do último teste unitário; a bateria focada posterior passou com 89). Não houve
geração real nem inspeção visual nesta fase.

O escopo alcançado é deliberadamente local. Após `SelectionPool`, o coordenador
projeta os itens para dicts porque o lifecycle subsequente ainda altera
candidate rows durante download, hashes, escolha e fallback. `visual.py` ainda
coordena essas transições; extraí-las exige um contrato de aquisição/resultado
que mantenha estados e auditoria sem recolocar aliasing implícito. A validação
real de providers e qualidade editorial continua pendente. Ver o
[relatório G70](20261005-ranked-selection-candidate-contract.md).


## G71 — decisão construída a partir do asset selecionado (`d8dace3`)

`make_selection_decision` ainda consumia `list[dict]` e relia provider, asset ID,
query e reuse reason para decidir o estado final. Esse era um segundo lugar que
reinterpretava a seleção depois de `SelectedAsset` já validar o row em
`MediaStageResult`. G71 adiciona `query_source` e `representation` ao contrato
`SelectedAsset` e migra a decisão para consumir esse tipo. A seleção normal e a
resolução de reuso cross-scene agora passam o asset selecionado validado; dicts
legados são convertidos por `SelectedAsset.from_dict()` na fronteira do
coordenador. Não muda os estados, razões, fallback ou schema persistido.

Arquivos: `src/curio/media/selection_result.py`,
`src/curio/stages/media_selection.py`, `src/curio/stages/visual.py` e
`tests/test_media_selection.py`. Regressões validam decisão para real/reused/
synthetic/none, rejeição de rows dict na política e propagação de query, origem
e representação. **88 testes focados**, **940 testes amplos** e 1 teste externo
deselecionado por HTTP 429 da Wikipédia passaram; compileall e diff check
passaram. Não houve geração real. Ver o
[relatório G71](20261005-selection-decision-selected-asset.md).

A conversão dos assets escolhidos acontece antes de construir a decisão final,
mas as rows de candidatos continuam existindo até auditoria e serialização. O
próximo lifecycle não resolvido segue sendo download/hash/seleção em
`visual.py`; G71 deixa explícito apenas que a decisão final consome o resultado
tipado, não a row.


## G72 — manter seleção tipada até a projeção (`ec61c65`)

Em G71, o coordenador convertia os rows escolhidos para `SelectedAsset` somente
no instante de criar `SelectionDecision` e continuava tratando `picked` como
dict até então. G72 move a fronteira: cada asset real aprovado, fallback
sintético e reuso tardio passa a entrar em `picked` já como `SelectedAsset`.
Decisão, nível/razão de fallback, deteção de sintético e query da seleção usam o
tipo; `to_dict()` ocorre apenas para `candidate_audit_rows` e o retorno no schema
persistido. O loop pré-seleção continua editando a row transitória porque ainda
acumula fatos de download, hash, order e reuse reason.

Arquivos: `src/curio/stages/visual.py`. Os 99 testes focados cobrindo seleção,
direção visual, pipeline e auditoria passaram; a suíte ampla passou com **940
testes e 1 excluído** por HTTP 429 da Wikipédia em 179,23 s; compileall e diff
check passaram. Não houve geração real. Esta fase reduz o lifecycle mutável dos
selecionados; ainda não extrai do coordenador a aquisição dos candidatos nem
tipa os outcomes de rejeição. Ver o
[relatório G72](20261005-selected-media-through-boundary.md).


## G73 — shortlist tipada até tentativa de aquisição (`7b965a1`)

G70 tipou `SelectionPool`, mas projetava imediatamente `fresh` e `reused` para
rows mutáveis. G73 mantém ambas as listas como `RankedSelectionCandidate` até
cada tentativa de aquisição: o downloader recebe a projeção da asset snapshot e
a row de avaliação é materializada localmente para a tentativa que atualiza
estado técnico. A reserva de reuso também ordena por score tipado e só projeta
a linha no momento de tentar o download.

Arquivos: `src/curio/stages/visual.py`. Bateria focada de seleção, auditoria,
direção visual e pipeline: **99 passaram**. Suíte ampla: **940 passaram, 1
excluído** por HTTP 429 da Wikipédia em **178,02 s**. `compileall` e diff check
passaram; sem geração real. O contrato reduz o alcance da row editável, mas ela
ainda acumula resultado, rejeição e fields finais dentro da tentativa. A próxima
migração deve modelar essas transições para remover a row temporária sem mover
política editorial para o downloader. Ver o
[relatório G73](20261005-ranked-pool-through-acquisition.md).


## G74 — outcomes explícitos da aquisição (`57a9a21`)

Antes de G74, o loop de `visual.py` guardava o resultado da tentativa alterando a
row da avaliação: adicionava rejection reason, asset baixado, aquisição, ordem e
reuse reason. G74 introduz `CandidateAcquisitionOutcome`, congelado, que leva o
`RankedSelectionCandidate` e `MediaAssetSnapshot` e valida quatro estados:
selecionado, falha de download, dimensão inválida e conteúdo duplicado. Sucesso
projeta para `SelectedAsset`; rejeição projeta uma row de auditoria associada à
identity original do candidato. O coordenador não altera a row avaliada para
transportar estes resultados.

A bateria de seleção/direção visual/auditoria/pipeline passou com **100 testes**;
a suíte ampla passou com **941 e 1 excluído** por HTTP 429 externo em **172,28
s**. Compileall e diff check passaram. Arquivos: novo
`src/curio/stages/media_acquisition_contracts.py`, `src/curio/stages/visual.py`
e `tests/test_media_selection.py`. Sem geração real.

G74 não extraiu o loop: `visual.py` segue dono da janela concorrente, retries /
timeouts propagados pela aquisição, metrics, logging e ordenação. O próximo passo
é mover a orquestração para um owner claro que consuma esse contrato, sem colocar
HTTP/FFmpeg no adapter nem mover relevância para acquisition. Ver o
[relatório G74](20261005-candidate-acquisition-outcomes.md).

## G75 — aquisição técnica fora do coordenador visual (`c4ef8c5`)

G75 moveu a tentativa de aquisição dos candidatos fresh e a tentativa tardia
de reuso para `media_candidate_acquisition.py`. A etapa recebe
`RankedSelectionCandidate`, executa janela concorrente e gates técnicos e
retorna `CandidateAcquisitionBatch` com `CandidateAcquisitionOutcome` e avisos
imutáveis. `visual.py` consome o lote para projetar selecionados/rejeições e
continua responsável por tentar o fallback sintético antes de delegar reuso.
Não houve mudança intencional de score, gates, provider, query ou thresholds.

102 testes focados passaram; a suíte ampla passou com 943 e 1 teste externo
desmarcado por HTTP 429 em 171,12 s. Compileall e diff check passaram. Sem
geração real. A extração ainda deixa efeitos de métricas/logging e deduplicação
cross-scene dentro do owner de aquisição; são limites a auditar, não divergências
que esta fase tenha eliminado. Ver o [relatório G75](20261005-candidate-media-acquisition.md).

## G76 — tentativa técnica comum fresh/reuse (`b87ba98`)

G76 unificou download/cache, timeout e validação de dimensões para candidatos
fresh e reutilizados por meio de `TechnicalAcquisitionAttempt` e
`_acquire_and_validate()`. O caminho fresh preserva janela concorrente e
auditoria de falhas; o caminho de reuso continua avançando quando uma tentativa
falha. A ordem editorial e a deduplicação permanecem intactas.

103 testes focados passaram; suíte ampla: 944 passaram e 1 teste externo foi
desmarcado por HTTP 429 em 171,65 s. Compileall e diff check passaram; sem
geração real. A aquisição ainda concentra janela/futures, deduplicação,
metrics/logging e efeitos operacionais. Ver [relatório G76](20261005-shared-technical-acquisition-attempt.md).
