# Relatório de parada — estado atual do trabalho no Curio

**Data do snapshot:** 2026-10-05  
**Escopo:** estado do repositório após solicitação para interromper implementação e documentar o trabalho realizado.  
**Estado:** incompleto. Este documento registra o que estava commitado e o diff local observado; não certifica a conclusão da refatoração nem da mudança local.

## Resumo executivo

O Curio já tinha módulos separados por etapa, mas os contratos e decisões ainda atravessavam algumas fronteiras como dicionários mutáveis, projeções repetidas e inferências reconstruídas por consumidores. O trabalho recente convergiu partes do fluxo de cenas, busca, avaliação, seleção, aquisição, auditoria e métricas para estruturas tipadas e decisões explícitas. Não foi uma reescrita integral: CLI/TUI, pipeline, providers, cache, fallback sintético, áudio, render e formatos persistidos foram mantidos.

No snapshot, a `HEAD` era `bc011bb docs: record canonical live duration metric`. Havia três arquivos de código/teste modificados sem commit, referentes à fase local G88 descrita abaixo. A suíte completa havia passado com 994 testes antes das validações estritas finais de G88; depois delas, o conjunto focado passou com 99 testes. Uma segunda execução completa estava em andamento no momento do registro e seu resultado não foi confirmado. Portanto, G88 não estava concluída nem commitada.

O pedido de parada foi respeitado para implementação: o trabalho registrado aqui é documental. Nenhum resultado desconhecido da execução completa é apresentado como aprovado.

## Arquitetura antes das migrações recentes

O projeto já separava fisicamente CLI/TUI, pesquisa, roteiro, prompts, planejamento de cenas, contexto visual, providers, scoring, áudio/TTS, legendas, timeline, render, metadata e métricas. Ainda assim, mover código não tinha definido por si só a propriedade de cada decisão. As fragilidades observadas eram:

- fronteiras internas usando mappings/rows mutáveis e listas paralelas;
- tópico, representações, queries, identidade/uso de assets e métricas com dados duplicados ou reconstruídos;
- avaliação, aquisição, seleção e fallback com comunicação parcialmente implícita;
- `visual.py` acumulando coordenação de busca, avaliação, aquisição, fallback e projeção de auditoria;
- métricas live e backfill com fontes e semânticas que precisavam ser conciliadas;
- auditorias cuja proveniência não era inteiramente derivada dos contratos canônicos.

O diretor visual já possuía contexto global e por cena, `representations`, aliases, gates/scoring semânticos, múltiplos providers, deduplicação, prevenção de reuso, CLIP opcional, fallback sintético/local, auditoria e métricas. As migrações preservaram esses componentes e as correções anteriores de relevância/diversidade. Não há evidência neste snapshot de que a arquitetura tenha sido desmontada.

## Arquitetura depois das fases commitadas

Fluxo real resumido, derivado do código e dos relatórios existentes:

```text
CLI/TUI/configuração
  → pesquisa e fontes
  → roteiro/artefato de script
  → cenas semânticas e spans temporais
  → contexto/enrichment semântico
  → VisualPlan
  → SearchPlan/SearchQuery
  → providers e coleta de candidatos
  → CandidateEvaluation/scoring/rejeições
  → shortlist tipada e tentativas de aquisição
  → SelectionDecision (asset novo, reuso, sintético ou ausência)
  → timeline/plano visual
  → áudio, legendas e render
  → metadata, métricas e artefatos persistidos
```

`SemanticScene`, `VisualPlan`, `SearchPlan`/`SearchQuery`, `Candidate`, `CandidateEvaluation`, `SelectionPool`, `SelectedAsset`, `SelectionDecision`, `SceneMediaSelection`, `MediaStageResult`, `VisualDecision`, `StageTiming` e `StageTimings` já expressam contratos para partes importantes do fluxo. Projeções JSON e adaptações legadas permanecem nas fronteiras de compatibilidade/persistência. O código ainda tem conversões e coordenação a remover; isto é uma migração gradual, não a arquitetura final.

## Commits confirmados relevantes

Commits mais recentes observados no histórico, em ordem decrescente:

| Hash | Mensagem/resultado |
|---|---|
| `bc011bb` | `docs: record canonical live duration metric` — relatório da F8. |
| `b0b272e` | `fix: align live metric duration with pipeline` — duração total live alinhada ao elapsed canônico do pipeline. |
| `cf5e8b9` | `docs: record selection provenance ownership` — relatório G87. |
| `412a8b1` | `refactor: centralize selection provenance` — provenance da seleção calculada a partir dos contratos de seleção, planos e auditoria. |
| `c97968d` | `docs: record visual fallback policy phase` — relatório G86. |
| `4b0b4e7` | `refactor: centralize visual fallback order` — política explícita da próxima tier da seleção. |
| `ba7074c` | `docs: record unknown backfill timing semantics` — relatório F7. |
| `254f48f` | `fix: preserve unknown backfill duration` — duração total desconhecida preservada no backfill. |
| `5e86495` | `docs: record immutable stage timings phase` — relatório F6. |
| `11022b2` | `refactor: make stage timings immutable` — coleção imutável de tempos de etapa. |
| `0216dee` | `docs: record shared stage timing contract` — relatório de contrato de elapsed compartilhado. |
| `e534ee3` | `refactor: validate stage elapsed values consistently` — validação uniforme dos elapsed dos estágios. |

O histórico completo anterior, com fases G57–G85, F4–F5 e extrações anteriores, está no Git e nas referências de relatório abaixo. Entre os commits documentados estão `5f3eeb9` (G80), `aa25487` (G81), `1b00689` (G82), `31f6acf` (G83), `bc131b9` (G84), `8ae6616` (G85), `11ac1f3` (F4), além de G57–G79. O inventário consolidado está em [relatório completo até G87/F8](20261005-relatorio-completo-estado-do-trabalho.md) e [estado arquitetural](20261005-relatorio-arquitetura-estado-atual.md).

## Arquivos modificados no snapshot local

As alterações ainda não commitadas observadas eram exatamente:

- `src/curio/stages/visual.py` — remove a montagem inline do payload de auditoria/decisão visual e encaminha os valores ao owner da auditoria;
- `src/curio/stages/visual_audit.py` — adiciona a função construtora descrita na seção G88, com validações e projeção dos campos já persistidos;
- `tests/test_visual_audit.py` — regressão para a construção de decisão/auditoria a partir dos contratos tipados.

O comando `git diff --stat` naquele momento indicava 3 arquivos, 177 inserções e 38 remoções. Nenhum arquivo de produto além desses três estava no diff local reportado. Os documentos preexistentes já registravam até G87/F8; este documento e sua entrada no índice são documentação do snapshot.

## Contratos criados, removidos e ownership

### Contratos/fases já commitados

- **Entrada:** `PipelineInput` obrigatório e validado (G80/G83).
- **Cena:** `SemanticScene` é a representação semântica runtime; queries legadas derivam das `representations` ao projetar para formatos antigos.
- **Planejamento visual e busca:** `VisualPlan` e `SearchPlan` tipados; geração de busca e provenance de representations têm owners definidos nas migrações registradas.
- **Candidatos/avaliação:** `Candidate`, snapshots de provider, avaliações/evidências imutáveis, `RankedSelectionCandidate` e `SelectionPool` preservam dados estruturados até fronteiras de aquisição/seleção.
- **Seleção:** `SelectedAsset`, `SelectionDecision` e `SceneMediaSelection` distinguem asset novo, reuso, sintético ou ausência; regras de fallback e classificação de provenance foram centralizadas parcialmente em `media_selection.py` (G86/G87).
- **Auditoria:** `SearchQueryAudit` e snapshots de coleção estruturam facts de consulta/candidatos. Antes de G88, os projetores consumiam provenance de `VisualPlan`, mas `visual.py` ainda montava o payload final da decisão.
- **Métricas de duração:** `StageTiming`/`StageTimings` imutáveis; duração live usa o elapsed de pipeline como fonte canônica; backfill mantém `null` quando desconhecido.

### G88 local, não commitada

Foi introduzida localmente `build_scene_visual_decision(...)` em `visual_audit.py`. Ela recebe `SelectionDecision`, `SelectionProvenance`, `SemanticScene`, `VisualPlan`, `SearchPlan`, `SceneCandidateCollection`, fatos de avaliação/rejeição e `SelectedAsset`; valida tipos, identidade de cena, correspondência entre queries, consistência entre decisão/provenance/seleção, faixa do threshold e fallback; então projeta os campos de `VisualDecision`.

Não foi criado um novo dataclass/schema persistido e nenhum contrato anterior foi removido. A mudança move a responsabilidade de montagem do payload de `visual.py` para `visual_audit.py`, preservando os campos JSON existentes. Isso não remove a orquestração de busca, coleta, avaliação e aquisição de `visual.py`.

## Testes e validações conhecidos

### Estado mais recente conhecido

- Testes focados após as validações estritas locais de G88: **99 passaram em 0,57 s**.
- `compileall -q src tests` e `git diff --check`: passaram após as alterações G88, conforme o registro da sessão.
- Uma suíte completa antes das últimas validações de entrada de G88: **994 passaram em 186,11 s**.
- Uma segunda suíte completa, já com essas validações finais, havia sido iniciada e estava ativa no snapshot. Resultado final: **não confirmado**.

### Referência anterior por fase

Os registros indicam, entre outros: G80 960 testes; G81 960; G82 962; G83 965; G84 965; G85 966; G86 986; G87 990; F8 993. A suíte completa pré-validação G88 chegou a 994. São resultados daquela revisão/fase, não uma certificação da árvore local atual.

### Limite de cobertura

Não há resultado final registrado para a suíte completa da revisão local G88. Não se deve inferir que os testes atuais cobrem qualidade universal de mídia, disponibilidade de providers, qualidade editorial dos assets ou todos os fallbacks. Os relatórios citados descrevem o escopo e as limitações das gerações reais anteriores.

## Regressões conhecidas e riscos ainda em aberto

Os incidentes que motivaram regressões/documentação incluem:

- Argentina aparecendo em conteúdo sobre Revolução Francesa;
- ônibus em conteúdo de buraco negro;
- Mughal Empire associado a Marco Aurélio;
- repetição do mesmo mapa em quase todas as cenas, seguida por aumento de sintéticos quando a repetição foi evitada;
- queries sem valor visual isoladas, como `gold`, verbos como `formavam` e contaminação de gênero com `laboratory`/`microscope`;
- busca específica que parava após candidato aprovado falhar tecnicamente na aquisição (G77), para a qual o replay determinístico pós-falha continuava pendente nos relatórios;
- falhas externas de LLM/provider, timeouts, 429/JSON inválido e cache/rerender como cenários que ainda precisam de validação final integrada.

Esses são incidentes/requisitos de regressão históricos; este snapshot não confirma que todos estejam reproduzidos na revisão atual nem declara falha nova introduzida por G88. O risco imediato de G88 é simplesmente não ter suíte integral concluída após as validações finais e permanecer sem commit.

## Estado de cada fase do plano arquitetural

Estado conforme o plano e os relatórios existentes, acrescido do snapshot local:

| Fase | Estado | O que falta |
|---|---|---|
| R — resultado de pesquisa | R1–R2 concluídas no escopo da auditoria; fase não integralmente fechada. | Imutabilidade e mutadores internos restantes. |
| A — modelo semântico | A4a–A4v concluídas no escopo registrado. | Ownership restante de alias/contexto e compatibilidade externa controlada. |
| B — `VisualPlan` | B1–B4 concluídas no escopo registrado. | Consolidar políticas de gênero e ganchos sintéticos sem duplicar decisão. |
| C — `SearchPlan` | C1 concluída parcialmente. | Replays reais com providers saudáveis e avaliação de qualidade de busca. |
| D — candidatos/avaliação/seleção | D1–D4 e convergência parcial; G86–G87 commitadas e G88 local. | Simplificar a orquestração remanescente e concluir validação de G88. |
| E — cache/artifact lifecycle | Parcial. | Lifecycle unificado, fronteiras de rows e confirmação de que cache só economiza trabalho, sem ser verdade editorial. |
| F — métricas/estado | F1–F8 parciais. | Definições canônicas para mais métricas, lifecycle timers, profiling por suboperação e conciliação seleção/render. |
| G — simplificação do pipeline | Parcial; G1, G3–G5 e G7–G87 commitadas; G88 em diff. | `visual.py` ainda coordena coleta/avaliação/aquisição e outras decisões/efeitos; remover ownership duplicado, não apenas mover código. |
| H — performance | Pendente. | Profile de planejamento, requests/retries, providers, download, deduplicação, scoring e fallback antes de otimizar. |
| I — validação e limpeza | Parcial. | Dois ou mais domínios reais na revisão final, fallback sem LLM, provider indisponível, cache/rerender e inspeção visual reproduzível. |

## O que exatamente se tentava corrigir na etapa de mídia

O problema imediato da alteração local não era voltar a pesquisar ou trocar thresholds. Era a **propriedade da composição final de auditoria/decisão**: embora a provenance de busca viesse dos planos e a provenance de seleção tivesse sido centralizada em G87, `visual.py` ainda montava manualmente um dicionário extenso com tópico, plano visual, fallback, plano de busca, intenção, entidades, representations, aliases, queries, providers, candidatos, vencedor e campos de exaustão.

Esse arranjo deixava o coordenador da aquisição responsável por projetar e combinar dados pertencentes a `SemanticScene`, `VisualPlan`, `SearchPlan`, `SceneCandidateCollection`, avaliação e seleção. A tentativa G88 era fazer `visual_audit.py` assumir essa projeção usando os valores tipados existentes e rejeitar incoerências entre cenas/planos/asset selecionado. A motivação arquitetural era tornar a decisão rastreável pela sequência:

```text
cena → plano visual → plano/consulta → coleção e auditoria de candidatos
     → avaliação → decisão de seleção → payload persistido de auditoria
```

G88 não alterava a formação das queries, gates, scoring, providers, ordenação, reuso ou política sintética. Ela também não provava melhoria de diversidade/relevância; era uma migração de ownership e validação do payload de auditoria.

## O que ficou incompleto

- G88 não tinha commit e ainda não possuía resultado confirmado da suíte completa na revisão com as últimas validações.
- A refatoração arquitetural ampla permanecia em curso; as fases E–I não estavam fechadas.
- `visual.py` continuava coordenando partes relevantes de coleta, avaliação, aquisição, fallback e observabilidade.
- Permaneciam pendentes a consolidação das fontes únicas para métricas/estado, o profile por suboperação e a validação final de cache/rerender.
- As execuções reais registradas anteriormente não substituem a matriz final solicitada: dois domínios, inspeção visual, providers com falha, fallback sem LLM e métricas reconciliadas na revisão final.
- O resultado da segunda execução completa iniciada durante G88 não foi incorporado a este documento.

## Documentos de referência

- [Relatório completo acumulado até G87/F8](20261005-relatorio-completo-estado-do-trabalho.md) — commits, contratos e validações por fase.
- [Estado arquitetural acumulado](20261005-relatorio-arquitetura-estado-atual.md) — ownership e contratos até G87/F8.
- [Auditoria do pipeline e dos contratos](../analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md) — inventário e plano derivados do código.
- [Validação arquitetural com execuções reais](20261004-validacao-arquitetural-execucoes-reais.md) — execuções e limites observados.
- Relatórios específicos F4–F8 e G75–G87 listados no [índice da documentação](../README.md).
