# Continuação da refatoração arquitetural do Curio

**Registrado:** 2026-10-05  
**Estado:** handoff; nenhuma conclusão arquitetural. A última alteração G98 está no working tree, sem commit e sem suíte completa validada.  
**Fonte principal para retomada:** este documento, junto aos relatórios abaixo. Não depende de ai-memory.

## Objetivo original

Migrar incrementalmente o Curio de um pipeline em que etapas reconstruíam significado umas das outras para transformações explícitas com contratos válidos, donos claros de decisões, proveniência auditável e fallbacks previsíveis. Preservar CLI/TUI, pipeline editorial, providers, cache, formatos externos necessários e as correções de relevância/diversidade já alcançadas. Não fazer big-bang rewrite nem otimizar antes de estabilizar contratos e medir.

## Arquitetura antes → estado atual

**Antes:** o projeto já tinha módulos físicos por etapa, mas a separação não garantia ownership. Mappings e rows persistidas atravessavam fronteiras; semântica, queries e contexto eram reconstruídos em múltiplas etapas; o coordenador visual acumulava aquisição, avaliação, seleção e fallback; candidatos tipados eram projetados cedo; métricas tinham contagens e fontes concorrentes.

**Estado atual:** o fluxo mais explícito é:

```text
CLI/TUI/config → PipelineInput → pesquisa/roteiro → SemanticScene
→ VideoContext/enrichment → VisualPlan → SearchPlan/SearchQuery
→ providers → Candidate/SceneCandidateCollection
→ CandidateEvaluation → SelectionDecision/SceneMediaSelection
→ timeline → áudio/legendas → render → metadata/métricas
```

Várias fronteiras possuem contratos tipados, validação e snapshots imutáveis. Os relatórios arquiteturais registram commits G1–G97 em várias trilhas, mas G não é uma única sequência completa: a convergência do pipeline segue parcial, `visual.py` ainda coordena decisões e existem fronteiras legadas de persistência. F4–F15 melhoraram contratos e projeções de métricas, mas F também não está encerrada. H (profile/performance) está pendente; I (validação real abrangente e limpeza) está parcial.

## Fases e checkpoints

- **R:** R1–R2 registradas como concluídas; mutabilidade de resultados e mutadores internos permanecem para auditoria.
- **A — modelo semântico:** A1–A4v registradas concluídas no escopo auditado; G57 removeu o mirror runtime de queries. Ainda auditar ownership de alias/contexto.
- **B — VisualPlan:** B1–B4 registradas concluídas no escopo; consolidar políticas de gênero e garantir que heurísticas não vazem entre domínios.
- **C — SearchPlan:** C1 concluída; falta validação real ampla de providers e qualidade.
- **D — candidate/evaluation/selection:** D1–D4 concluídas conforme o relatório, com convergência parcial; continuar simplificando o coordenador e convergir fallbacks.
- **E — cache/artifact lifecycle:** E1–E7 registradas, fase parcial. Cache economiza bytes/resultados, mas não deve decidir seleção editorial; falta unificar lifecycle e remover fronteiras internas ainda em dicionários.
- **F — métricas/estado:** F4–F15 commitadas (duração de timeline/etapas, duração desconhecida como null, total live, projeção de seleção, retries, timeout, caches distintos, reconciliação seleção/timeline, proveniência de inputs do renderer e requests de provider). A trilha F anterior/paralela não está toda concluída; faltam lifecycle timers, medição de decodificação/pixels e profile por suboperação. Definições e limitações estão nos relatórios individuais.
- **G — simplificação do pipeline:** G80–G97 e os checkpoints anteriores listados no relatório consolidado estão commitados. Decisões recentes incluem entrada `PipelineInput` estrita (G80–G83), CLIP dentro da avaliação (G84), auditoria proveniente do `VisualPlan` (G85), política explícita de fallback (G86–G87), ownership da decisão e avaliações/rejeições tipadas (G88–G92), prioridade de provider por cena (G93), planos canônicos encaminhados à busca (G94), preservação do nome de evento (G95), identidade contextual compacta (G96) e separação de âncora global/evidência local (G97). **G98 está em andamento e não commitada.** G99 e extrações futuras não iniciadas.
- **H — performance:** pendente; primeiro profile reproduzível, depois otimização justificada.
- **I — validação/limpeza:** parcial; falta aquisição real pós-mudanças em domínios diferentes, inspeção visual maior, falhas/cache/rerender e remoção segura de compatibilidade interna morta.

### Commits/checkpoints principais

- **Último estado estável de código:** `1fd98d4 fix: separate topic anchor from scene evidence` (G97). G96: `0cdf81a fix: disambiguate compact entity identifiers`.
- G95: `3978670`; G94: `60703ae`; G93: `38b892e`; G92–G89: `6191b8b`, `e187697`, `f0a9622`, `087c96e`; G88: `c5424b5`; G87: `412a8b1`; G86: `4b0b4e7`; F15: `b9e6ff1` (documentação/request metrics checkpoints posteriores constam no log).
- F14 incluiu `7bc5c23`, `94119e3`, `8daa29f`; outros F4–F13 estão no relatório consolidado.
- O relatório consolidado G97 informa suíte integral **1021 passed em 185,79 s**, focados **70 passed**, `compileall` e `git diff --check` aprovados naquele commit.
- A interrupção solicitada nesta sessão é o estado mais novo, mas não é um estado validado/estável: teste full suite interrompido depois de **540 passed em 97,48 s**, sem resumo de conclusão. A falha `float(None)` detectada na tentativa anterior foi corrigida localmente; a repetição da suíte foi interrompida pelo usuário. Não inferir que todo o restante passou.

## Contratos e fontes de verdade atuais

- **Entrada:** `PipelineInput` é a fronteira tipada para tópico, roteiro e título editorial; CLI/TUI/queue constroem o contrato. Campos textuais inválidos são rejeitados. A queue ainda adapta o campo persistido legado `idea` ao ler.
- **Cena e intenção semântica:** `SemanticScene` é contrato da cena; `representations` alimenta busca de cena. `VideoContext` guarda contexto global. `global_visual_queries` é âncora global; representação local do planner é evidência da cena. Enrichment de `entity_context` continua pesquisável, mas não deve ser promovido à âncora nem contar como prova do que a cena mostra.
- **Planejamento visual/busca:** `VisualPlan` contém intenção e não duplica queries; `SearchPlan`/`SearchQuery` é dono das consultas prontas. Aquisição não deve reinterpretar narração. Adapters de gênero declaram políticas/dados; não fazem HTTP, LLM, download ou FFmpeg.
- **Provider/candidato/avaliação:** provider normaliza resposta; `Candidate` preserva snapshot e vínculo à query; `CandidateEvaluation`/`EvaluationBatch` carrega scores/evidência/rejeições. Provider não decide relevância; scoring não gera query.
- **Seleção:** `SelectionDecision` explica novo, reuse, sintético ou ausência com motivo/fallback; `SelectedAsset`, `RankedSelectionCandidate` e `SelectionPool` preservam tipos até as fronteiras existentes. Reuso é separado de aquisição nova. `SceneMediaSelection`/`MediaStageResult` formam fronteiras agregadas; `to_dict()` é projeção compatível.
- **Auditoria:** `QueryAuditAccumulator` acumula fatos no processo de busca; snapshots tipados guardam auditoria. `VisualDecision` agrega decisão e proveniência persistida em `media.json`.
- **Cache/persistência:** cache de busca, cache de bytes/assets, projeto persistido e rerender são conceitos distintos. Cache reduz custo, nunca escolhe asset por si só. `Chapter` e JSON são formatos/projeções externas legadas nas suas fronteiras.
- **Tempo/métricas:** contratos de tempo e projeções canônicas avançaram em F; fontes globais e lifecycle ainda parciais. Valores não recuperáveis devem continuar `null/unknown`, não ser inventados como zero.

## Invariantes que não devem ser quebradas

1. Cada decisão semântica tem um dono. SearchPlanner cria query; provider retorna e normaliza; evaluator/scoring decide relevância; seleção decide diversidade/reuso; política explícita decide fallback; renderer apenas renderiza.
2. Aquisição não extrai keyword nem reconstrói significado da narração. Verbo/fragmento isolado não é âncora visual sem justificativa semântica e proveniência.
3. Âncora global do tópico e evidência visual local da cena são dimensões separadas. Enrichment de entidade não pode se passar por planejamento da cena.
4. Não enfraquecer gates para obter cobertura ou diversidade. Exaurir representações/queries/providers razoáveis antes de sintético ou reuse, sem permitir que resultado duplicado ou candidato rejeitado encerre busca.
5. Asset em cache não é escolha editorial. Asset repetido não é aquisição nova; dedupe deve reconhecer identidade estável e, quando possível, hash/conteúdo.
6. Toda escolha/ausência deve ser auditável da cena até plano, representation, query, provider, candidate, score, rejeição/seleção e asset/fallback.
7. Fallback LLM/local deve produzir o mesmo contrato semântico para etapas seguintes; falha de LLM/provider não pode exigir um pipeline de semântica diferente.
8. `SemanticScene` não deve carregar duração de render; alterações visuais não reescrevem roteiro; rerender não inicia pesquisa.
9. Providers e adapters de gênero não executam política editorial ou efeitos de outros layers; regras de um gênero não contaminam outros.
10. Compatibilidade externa necessária permanece nas fronteiras. Não manter caminhos internos duplicados por dependência de testes antigos.
11. Incerto/desconhecido não vira zero fabricado; contagens distintas têm definições distintas (adapter invocation vs tentativa HTTP, busca vs cache bytes etc.).

## Último ponto exato de trabalho: G98

A hipótese confirmada no replay G97 é que `SceneCandidateCollector.collect()` limita candidatos tecnicamente elegíveis antes de o scoring semântico avaliar a shortlist. Com teto 20, candidatos tecnicamente válidos mas irrelevantes podem consumir o orçamento e impedir consultas de próximas representações; essas queries apareciam como `scene_candidate_budget`. O replay M87 pós-G97 executou 4 de 8 queries planejadas por cena.

A tentativa G98 local, ainda **não commitada**, muda o coordenador para coletar e avaliar query a query, liberando do buffer limitado candidatos já avaliados, enquanto mantém identidades e auditoria/dedupe por cena. Também adicionou regressão com cap 1: primeira query retorna imagem irrelevante, segunda retorna gravura de Mohács, e a segunda deve ser consultada/selecionada. Na execução completa interrompida, houve 540 testes passados em 97,48 s; não há resultado final. Um erro de ordenação com `scene_relevance=None` foi observado na rodada anterior e corrigido no working tree via fallback a zero, mas esta correção não passou pela suíte completa concluída.

Arquivos de G98 atualmente modificados:

- `src/curio/stages/scene_candidate_search.py`: novo `release_evaluated()` libera apenas candidatos pendentes avaliados; identidade continua deduplicada.
- `src/curio/stages/visual.py`: busca por query com avaliação intermediária, ordenação de resultados e contagem para eventos/métricas; fix local para `scene_relevance=None`.
- `tests/test_media_funnel.py`: regressão do candidato tecnicamente elegível rejeitado semanticamente não consumir o orçamento de busca.

**Não assumir G98 como correto ou regressivo:** revisar diff, executar testes focados, depois a suíte completa e comparar semântica de métricas/auditoria antes de qualquer commit. Não apagar/reverter o trabalho sem entender.

## Incompleto e problemas conhecidos

- G98 não commitada nem integralmente validada; nenhum replay real pós-G98.
- G97 reduziu cobertura real M87 para 1/4 cenas com mídia; duas entradas selecionadas são visualmente quase iguais apesar de dois IDs únicos; demais três sintéticas. Isso é falha de busca/cobertura, não prova de ausência em acervo.
- G98 tenta resolver a parada do orçamento antes do scoring, mas precisa comprovar que conserva o limite de custo e que avaliação por query não distorce seleção, auditoria, ordering, métrica ou reuse.
- O plano local M87 perdeu conceitos explicitamente úteis (`accretion disk`, `jet`, `gravitational lensing`); intenção por cena e aliases canônicos necessitam auditoria geral, sem patch de tema.
- Grounding factual da afirmação 2019 ainda não foi resolvido.
- Bugs editoriais históricos: gravura de Mohács de outro evento/período; quasi-duplicatas perceptuais não capturadas por hash/ID; histórico anterior de homônimos M87 foi corrigido em G96 e não deve ser reintroduzido.
- `visual.py` continua com muitas responsabilidades de coordenação; ownership total de estado/cache/metadata/métricas é parcial.
- Met/AIC mostraram indisponibilidade em execuções anteriores (HTTP 410/500), algumas outras fontes tiveram timeout/limite; revalidar status em replay.
- Sem profile comparável atualizado; não otimizar busca ruim por paralelismo.

## Próximos passos, nesta ordem

1. Preservar este handoff e inspecionar `git diff` G98, confirmar comportamento de `release_evaluated` contra contrato do coletor.
2. Rodar os testes focados da regressão e coletor, visual director, asset usage, waterfall, museum, funnel e black-hole. Registrar resultados; consertar somente com evidência e em commit lógico, se o usuário retomar a implementação.
3. Rodar suíte completa sem interrupção; então `python -m compileall -q src tests` e `git diff --check`. Não declarar G98 pronta enquanto falhar/incompleta.
4. Fazer commit de código G98 somente com validação limpa; documentar mecanismo, contagens e limitações e atualizar índices de docs conforme convenção.
5. Executar replay real M87 isolado, sem credenciais LLM, anotando por cena queries realmente consultadas, providers, resultados/rejeições, alternativa tentada antes de fallback, IDs e hashes, reuse e sintéticos; inspecionar visualmente assets vencedores. Não tratar IDs diferentes como diversidade editorial comprovada.
6. Corrigir a perda geral de conceitos específicos/aliases sob novo checkpoint, sem hardcode temático e sem enfraquecer gates; regressões para vários domínios.
7. Validar pelo menos mais um domínio real (história/pessoa/etimologia/científico conforme cobertura), depois falhas LLM/provider, cache frio/quente, rerender, métricas e pipeline real.
8. Retomar fases G/E/F restantes: ownership/extrair coordenador só quando responsabilidade múltipla demonstrada; consolidar estado, cache, metadata e métricas; profile H após contratos; limpeza interna; compatibilidade externa.
9. Atualizar relatórios e README/docs index por checkpoint e declarar limites ainda abertos. Não declarar arquitetura completa por suíte verde ou um vídeo bom.

## Testes e validações que existem

- **Último full suite concluído e válido:** no commit G97: 1021 passed em 185,79 s; foco 70 passed; `compileall` e `git diff --check` passaram.
- **G98 antes de interrupção:** teste dirigido mais coletor/visual/enrichment: 51 passed. Depois, execução `PYTHONPATH=src pytest -q` foi interrompida por ordem expressa do usuário em 540 passed / 97,48 s. Não houve falha final reportada nem conclusão; marcar como parcial/interrompida.
- **G98 atual:** fix local para TypeError de `float(None)` após falhas na primeira rodada; a execução interrompida começou depois deste fix. Não se sabe se surgem falhas restantes.
- **Execução real mais recente do registro:** replay M87 pós-G97, sem LLM, 4 cenas; 1 cena com mídia real, 2 IDs reais únicos quase idênticos, 0 reuse, 3 sintéticas, 16 queries lógicas, 80 candidatos auditados, 6 mantidos, 68 rejeitados por âncora e 8 por regra técnica; mídia 19,07 s, execução 70,75 s. Detalhes por cena/providers e limitações em `docs/relatorios/20261005-topic-anchor-scene-evidence.md`. Não houve validação real pós-G98.

## Arquivos para ler primeiro na retomada

1. `AGENTS.md` e este `docs/CONTINUACAO-REFATORACAO.md`.
2. `docs/relatorios/20261005-relatorio-completo-estado-do-trabalho.md` (consolidado até G97/F15).
3. `docs/relatorios/20261005-relatorio-arquitetura-estado-atual.md` (auditoria, fases, contratos, inventário histórico).
4. `docs/relatorios/20261005-topic-anchor-scene-evidence.md` (causa/replay G97 e próximo gargalo).
5. `git status`, `git log`, depois o diff dos três arquivos G98 listados acima.
6. Implementação: `src/curio/stages/visual.py`, `scene_candidate_search.py`, `candidate_evaluation.py`, `scoring.py`, `media_selection.py`, `media_contracts.py`, `visual_audit.py`, `scene_contract.py`, `visual_context.py`.
7. Testes: `tests/test_media_funnel.py`, `test_scene_candidate_search.py`, `test_visual_director.py`, `test_visual_asset_usage.py`, `test_media_waterfall.py`, `test_media_museums.py`, `test_black_hole.py`, `test_visual_topic_anchor.py`.
8. Métricas/cache/provider/pipeline: `src/curio/metrics.py`, `src/curio/media/providers.py`, módulos `src/curio/media/` e `src/curio/pipeline*.py`; veja os relatórios F e replay antes de interpretar métricas.

## Relatórios relacionados

- `docs/relatorios/20261005-relatorio-completo-estado-do-trabalho.md`
- `docs/relatorios/20261005-relatorio-arquitetura-estado-atual.md`
- `docs/relatorios/20261005-topic-anchor-scene-evidence.md`
- Índice histórico: `docs/README.md`
