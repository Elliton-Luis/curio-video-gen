# Relatório de arquitetura e estado de migração — Curio

**Data:** 2026-10-05
**Escopo:** auditoria documentada e migrações incrementais até G58.
**Estado:** em andamento; as fases abaixo não certificam a conclusão da
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
- **Resultado de provider:** `Candidate` tipado e ligado à busca. Provider
  normaliza resposta e não decide relevância editorial.
- **Avaliação:** `CandidateEvaluation`/`EvaluationBatch`; reporta score e
  rejeições, sem gerar query ou decidir fallback editorial.
- **Seleção:** `SelectionDecision`; distingue asset novo, reuso, sintético e
  ausência, com motivo/fallback validado.
- **Tempo:** `TimelineSpan` e contratos temporais; cenas semânticas não devem
  carregar duração ou timestamps de render.
- **Persistência:** `Chapter` e artefatos antigos continuam formato de projeto
  e projeção. Adaptações legadas pertencem às fronteiras.
- **Métricas e estado:** owners e definições globais permanecem parciais; os
  relatórios live e backfill ainda requerem consolidação.

## Arquivos alterados nas fases G57–G59

Implementação G57: `src/curio/stages/scene_contract.py`, `scene_projection.py`,
`scenes.py`, `visual_context.py`, `scoring.py`, `visual_timeline.py`,
`media_rules.py` e `review.py`.

Implementação G58: `src/curio/stages/visual.py` e
`src/curio/stages/media_selection.py`.

Implementação G59: `src/curio/stages/visual.py`,
`src/curio/stages/media_selection.py` e `src/curio/pipeline_visual.py`.

Testes: `tests/test_scene_contract.py`, `test_visual_contracts.py`,
`test_visual_model.py`, `test_visual_context.py`, `test_visual_director.py`,
`test_visual_asset_usage.py`, `test_visual_topic_anchor.py` e
`test_black_hole.py` (G57); `tests/test_media_diag.py` e
`tests/test_media_selection.py` (G58); `tests/test_media_diag.py`,
`tests/test_media_selection.py`, `tests/test_pipeline_integration.py`,
`tests/test_pipeline_visual.py` e `tests/test_standby_flow.py` (G59).

Documentação e navegação: `README.md`, `docs/README.md`, a auditoria
`docs/analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md`, este
relatório e os relatórios G57–G59.

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
| G — simplificação do pipeline | G1, G3–G5 e G7–G59 registradas; parcial. | `visual.py` ainda coordena busca/aquisição; metadata e rows geométricas têm limites por concluir. |
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
fases, `python -m compileall -q src tests` e `git diff --check` passaram. Uma
execução integral de G57 anterior à correção dos testes foi interrompida em
640 passados e não é usada como prova.

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

G57–G59 passam os gates registrados, mas auditoria integral, ownership único de
todas as decisões e validação final permanecem objetivos abertos.
