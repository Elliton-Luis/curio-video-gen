# curio — Máquina de Conteúdo Educativo em Vídeo

> Conteúdo curto que respeita a inteligência do espectador.

Ferramenta local (Linux, CLI + TUI) que transforma **uma ideia textual** em um
**vídeo vertical de ~45 s** com roteiro, narração em PT-BR, legendas queimadas
e MP4 final — tudo com **custo próximo de zero** (TTS local + FFmpeg).

O mapa do fluxo executado, contratos atuais, fontes de verdade e plano de
migração arquitetural estão em
[Auditoria da arquitetura e contratos](docs/analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md).
O relatório distingue a baseline inicial do estado revisto após as migrações;
descrições marcadas como baseline são históricas, não o fluxo atual.
No checkout atual, scene-plan e seleção de mídia têm manifestos de input e
resultados de cena validam a coerência de asset/decision antes de seguir para
timeline, fontes e render; rows persistidos ainda mantêm o schema de projeto.
`run_pipeline` e `finalize_project` isolam a configuração mutável por execução,
para preferências de áudio lidas do projeto não alterarem o estado da TUI/queue.
No gate de 2026-10-04, a suíte completa passou com 888 testes após migrar a
asserção de metadata para o módulo que agora é dono da projeção; `compileall`
e `git diff --check` também passaram. Esse resultado não encerra as fases
arquiteturais ainda parciais descritas na auditoria.
No gate seguinte, o enrichment passou a usar o alvo de pesquisa como tópico
canônico e o SearchPlanner deixou de usar aliases sem provenance verificada;
889 testes passaram. A validação histórica não encontrou candidato adequado
e terminou sintética, enquanto removeu o falso positivo do Parlamento moderno.
O relatório compara as duas execuções e registra que providers falharam; busca
histórica continua aberta.
O selector e os relatórios agora priorizam SHA-256 de assets locais, usando URL
ou ID enquanto o download não existe; duplicatas encontradas depois do download
são rejeitadas antes de completar a shortlist. O gate integral após essa fase
passou com 891 testes. A validação M87 v3 encontrou duas imagens únicas e uma
cena sintética, mas não a fotografia observacional específica de M87; o
relatório registra essa limitação e o gargalo de research/provider.
O layout e a resolução de projetos agora têm dono em `project_paths.py`; CLI,
TUI e pipeline compartilham `VideoPaths` frozen para projetos legados e
`genre/slug`. A suíte após essa migração passou com 892 testes. `finalize` e
geração ainda compartilham o coordenador `pipeline.py`; a auditoria registra
essa próxima fronteira de extração. As políticas e efeitos de composição de
áudio foram extraídos para `audio/composition.py`, usados pelo pipeline e CLI;
a extração de finalize depende agora desse módulo em vez de helpers privados
do coordenador. O gate integral após essa fronteira ficou em 892 testes
(186,96 s), com compileall e diff check aprovados.
Leitura de texto/JSON e escrita JSON dos projetos também foram centralizadas em
`project_artifacts.py` e os helpers duplicados do pipeline foram removidos;
após essa fase, 892 testes passaram em 195,38 s.
O workflow de áudio humano agora está em `pipeline_finalize.py`; a API
`finalize_project` continua no coordenador como boundary de config, paths e
RunLog. `pipeline.py` caiu de 1.054 para 739 linhas. Gate integral: 892 testes
passaram em 173,98 s; após remover o wrapper interno sem consumidores, 25
testes focados passaram em 150,41 s.
O tratamento de roteiro fornecido também saiu de `stages/visual.py` para
`stages/script_input.py`, que agora é o owner da leitura literal, contagem por
pacing e validação da divisão. A suíte após essa fase passou com 892 testes
em 195,33 s.
O builder de beats, inserções, backgrounds e SFX foi movido de `visual.py`
para `visual_timeline.py`; o rebuild não importa mais aquisição de mídia. A
suíte após essa mudança passou com 892 testes em 178,13 s.
O fallback de reuso entre cenas agora mantém `asset` e `SelectionDecision`
coerentes e carrega somente o candidato validado para a cena. A regressão
passou junto aos 893 testes da suíte (197,53 s).
A auditoria de candidatos também deixou de repetir cinco chaves idênticas no
schema; waterfall/funnel/diretor passaram com 55 testes e a checagem AST
confirmou que `visual.py` não tem chaves literais duplicadas.
O late reuse agora delega a ordenação de doadores a `media_selection` usando
evidência semântica já calculada; 894 testes passaram na suíte integral. A
coordenação dos dois caminhos de reuse e da aquisição/fallback ainda está
registrada como trabalho arquitetural restante.
A projeção das decisões de candidatos foi separada para `visual_audit.py`;
59 testes focados e 896 testes integrais passaram. `visual.py` ainda agrega
aquisição, seleção e fallback, em migração incremental.
A prioridade por cena agora pertence a `media_provider_policy.py` e consome
`VisualPlan` já pronto; os providers históricos/científicos mantiveram a ordem
anterior. Após essa fase, 896 testes passaram na suíte integral.
O workflow de preparação com narração humana agora pertence a
`pipeline_human_prep.py`; a integração humana e a suíte completa passaram
(896 testes). `pipeline.py` ainda coordena a geração assistida.

A migração incremental começou pelos contratos semânticos compartilhados de
cena, contexto e representação visual; o relatório acompanha as fases já
concluídas e as fronteiras ainda em transição. O carregamento de capítulos
históricos os normaliza para os tipos atuais e valida a narração antes de
entregar os dados às etapas seguintes. Antes da aquisição, cada cena recebe
um `VisualPlan` sem narração; um `SearchPlanner` puro gera queries com
proveniência por representação, alias e variação, preservadas na auditoria de
mídia. Resultados dos providers entram como `Candidate` associado à query de
origem antes de deduplicação e dos gates técnicos; `candidate_evaluation.py`
produz avaliações tipadas com score, evidência e motivo de rejeição.
`media_selection.py` separa candidatos novos de reusos adiados sem reescrever
scores e emite uma `SelectionDecision` para visual real, reutilizado, sintético
ou ausente, sempre com motivo e nível de fallback.
O cache global guarda bytes baixados; respostas de busca são compartilhadas
apenas durante uma geração. A seleção do projeto tem manifesto versionado em
`media/media-selection.json`, ligado às entradas semânticas, gênero, quantidade
de imagens, modo de planejamento, providers disponíveis e threshold. Um `media.json` adquirido sem
manifesto compatível é pesquisado novamente; escolhas manuais continuam
preservadas. O cache é validado como `MediaStageResult` antes do uso; row
malformado é auditado e causa nova aquisição. `rerender` só consome a seleção
registrada e não pesquisa mídia.
As métricas de seleção usam uma projeção canônica em
`media/selection_metrics.py`: `MediaMetricsInput` é a entrada validada para
`visual_plan`, criada diretamente do `MediaStageResult` ao vivo ou por adaptador
explícito do formato persistido no finalize/backfill. Beats/duração continuam
sendo medidas distintas da quantidade de assets atribuídos às cenas. Backfills
sem `media` e cenas sem decisão recuperável preservam valores como desconhecidos
(`null`/`unknown`) em vez de inventar zeros.
`visual_report.unique_assets` conta IDs reais selecionados; o relatório de
pipeline nomeia separadamente `visual_timeline_assets_unique` (reais e
sintéticos usados na timeline) e
`visual_timeline_assets_reused_across_scenes`. Os antigos
`visual_assets_unique`/`visual_assets_reused` permanecem aliases de schema para
projetos/consumidores existentes.
Cards sintéticos comuns exibem assunto e trecho de narração sem converter
entidades de busca em cadeia explicativa; somente cenas tipográficas desenham
cadeias declaradas. Uma versão própria na chave do cache descarta PNGs com o
layout anterior.
`metadata.json` usa o mesmo construtor de relatório para geração humana e
assistida: ambos persistem `visual_report`, `provider_downloads` e a proveniência
do enriquecimento semântico quando disponível.
`pipeline_research` valida estrutura/tipos de fontes, rejeições, queries, fatos,
gaps e etimologia antes de registrar ou persistir saída; retorno parcial ou
malformado falha no limite do estágio sem side effects.
O `SearchPlanner` prioriza representações de cena sobre contexto amplo, evita
repetir meio/tópico nas consultas e só inclui fallback de mapa em contexto
histórico. Um candidato bem pontuado não encerra a busca antes de passar por
download e validação técnica.
`stages/media_acquisition.py` é dono do cache/download de bytes, origem da
aquisição e validação de dimensões reais; ele recebe `MediaAsset` e não conhece
intenção ou seleção editorial. `visual.py` continua coordenando busca e seleção.
`stages/media_search.py` executa queries e entrega `ProviderSearchResult(query, provider, assets, error, cache_hit)`
tipado em ordem de prioridade; erros e timeouts permanecem visíveis para a
auditoria, e o módulo não conhece cena, relevância nem fallback editorial.
O fallback local agora usa `VisualFallbackPlan`: a política seleciona estratégia,
forma e representação aprovada antes do desenho; o renderer apenas consome o
plano. `visual_steps` é o único campo que autoriza diagrama, preservando ordem
declarada; entidades e contexto não são reinterpretados como causalidade.
O plano e sua origem ficam na auditoria por cena.
O renderer não infere data, citação, contraste ou termos tipográficos: esses
valores chegam explícitos no plano. A escada antiga `visuals.LADDERS` e os
seletores `choose_form`/`visual_for_scene` foram removidos após migrar seus
testes para os contratos; adapters declaram formas preferidas sem uma segunda
política paralela de medium.
O fallback tipográfico registra a mesma estratégia (`form`) no resultado,
na auditoria, no evento e nas métricas, com nível explícito
`synthetic_without_search`. Métricas canônicas chamam o total de
`synthetic_assets`; o campo histórico `synth_diagrams` segue no JSON como
alias de leitura compatível.
As regressões arquiteturais mais recentes corrigem a promoção indevida de
`Buracos` como entidade em títulos descritivos e fazem a busca continuar após
detectar que um candidato aparentemente novo tem bytes já usados. A suíte
integral histórica daquele relatório tem 909 testes aprovados. As migrações
incrementais atuais estão no relatório abaixo; G38 passou com 939 testes em
174,69 s. G39–G40 migraram fallback e renderer para planos explícitos; os
relatórios registram testes e validação de cada fase.
G42–G49 continuam a migração de fronteiras: projection, saída tipada de cenas,
render, metadata, standby, normalização compartilhada e contrato estrito entre
representações visuais e suas queries, e G50 torna a projeção visual consumidora
estrita da cena canônica; ver auditoria arquitetural e relatórios recentes em
`docs/README.md`. G51 também removeu a dependência do planejador de busca e do
contexto visual em helpers privados do scoring, mantendo tokenização em
`textnorm`.
G52 valida `SearchQuery` e `SearchPlan` antes de a aquisição receber queries:
proveniência obrigatória, níveis válidos e ausência de duplicatas.
G53 mantém `Candidate` tipado da aquisição à avaliação e elimina sua conversão
de ida e volta antes de produzir `CandidateEvaluation`.
G54 valida score, motivo e partições aceito/rejeitado antes da seleção.
G55 valida consistência entre estado final, provider, fallback e justificativa
de reuso em `SelectionDecision`.
G56 remove o mirror redundante de queries de `VisualPlan`; a auditoria salva
continua expondo `scene_queries` derivadas das representações.
G57 removeu o mirror runtime também de `SemanticScene`; o campo JSON e a
projeção externa `Chapter.visual_queries` seguem derivados para compatibilidade.
G58 moveu reuso cross-scene e anotação de assets repetidos do coordenador para
`media_selection.py`, sem alterar critérios nem formato persistido.
G59 faz a etapa visual devolver `MediaStageResult` validado; pipeline e
políticas de reuso consomem esse contrato tipado sem uma conversão intermediária.
G60 transfere atualizações de reuso e projeção compatível para o contrato
`SceneMediaSelection`, que revalida a seleção alterada.
G61 (`7a568aa`) agrupa a auditoria por query em `SearchQueryAudit` e centraliza
sua projeção pela ordem de `SearchPlan`.
G62 (`a51c06d`) move travessia de providers, dedupe e gates técnicos para
`SceneCandidateCollector`; ranking, seleção e fallback continuam em seus
owners.
G63 (`73f6e6c`) valida `visual_decision` por `VisualDecision`, centraliza
updates de seleção e mantém a projeção JSON compatível.
G64 (`519c1fa`) substitui o payload genérico por campos nomeados e
imutáveis, preservando round-trip do formato salvo e extensões legadas.
G65 (`28e4799`) separa o acumulador mutável da auditoria por query do snapshot imutável entregue pela coleta de candidatos.
G66 (`8bed5ec`) faz `Candidate` capturar um `ProviderAssetSnapshot` imutável; `MediaAsset` segue mutável no ciclo técnico de download.
O relatório arquitetural completo — com estado antes/depois, commits,
contratos, fases, testes, regressões, etapa de mídia e pendências — está em
[docs/relatorios/20261005-relatorio-arquitetura-estado-atual.md](docs/relatorios/20261005-relatorio-arquitetura-estado-atual.md).
consultou 40 queries lógicas (NASA e Wikimedia), mas obteve mídia real em 2/6
cenas; 4 cenas permaneceram sintéticas e duas buscas terminaram incompletas
por falhas de provider. Zero reusos e 6 IDs reais únicos foram registrados.
O tempo de mídia subiu para 129 s, com 20 retries e 4 timeouts do Wikimedia.
`consumption.media.shortlist_assets_unique` conta candidatos encaminhados para
download; `real_scene_assets_unique` segue a seleção final e coincide com
`visual_report.unique_assets`. `selected_unique` permanece alias compatível.
O manifesto de roteiro schema 2 também assina inputs de roteiro e título, incluindo contexto de pesquisa, políticas e rotas: cache gerado stale é invalidado, título verifica o roteiro de origem, e edições/projetos legados sem proveniência são preservados explicitamente.
Ver [relatório de migração e validação](docs/relatorios/20261004-migracao-contratos-cenas.md).
`ResearchResult` é a fonte única para target, fontes, rejeições, consultas e
etimologia; `ResearchStageResult` contém apenas status, prompt e duração da
etapa, sem cópias concorrentes desses dados.
`script.generate_script` e `generate_title` produzem `ScriptArtifact` e
`TitleArtifact` validados. O pipeline cria esses mesmos contratos para texto
fornecido e cache; proveniência/texto continuam gravados nos arquivos e campos
de metadata existentes. `pipeline_script.run_script_stage` agora é o dono da
transição de pesquisa para roteiro/título: autocura de roteiro cacheado,
grounding, invalidação de cenas quando o roteiro muda, título e persistência
retornam juntos em `ScriptStageResult`; o coordenador só compõe esse resultado
com a etapa de cenas. `script/artifacts.json` registra hash/proveniência do
roteiro e título e, para título gerado, o hash do roteiro de origem. Os arquivos
continuam editáveis: alteração externa é preservada e invalida cenas/TTS; `--force`
é a solicitação explícita para regenerar. Projetos anteriores ao manifesto
migram seu estado atual sem inferir se ele foi editado manualmente.
O cache de TTS registra em `audio/tts-manifest.json` a assinatura do texto e
dos parâmetros de voz/idioma/duração, além da identidade de `words.json`; cache
legado sem manifesto só é migrado quando metadata e transcrição comprovam o
mesmo roteiro. Se o roteiro mudar, a invalidação chega explicitamente ao áudio,
e o MP4 final só é reutilizado quando o áudio usado nele continua vigente.
O planejamento visual e suas métricas recebem `SemanticScene[]` e
`TimelineSpan[]` separados; `Chapter` vive em
`stages/scene_projection.py` como projeção de compatibilidade para metadata e
formatos externos; `stages/scenes.py` mantém apenas reexport legado. Classificação de tipo visual
e normalização de representações ficam em módulos compartilhados por planner,
enrichment e projeção histórica.
Aquisição por provider e mídia manual recebem somente `SemanticScene`; reuse
consulta a mesma intenção tipada, sem adaptadores de Chapter.
A seleção vazia é tratada por `pipeline_media.prepare_media_standby`, que
persiste estado/instruções manuais antes de propagar `MediaStandby`.
O metadata recebe semântica e timing tipados e só materializa `chapters` ao
serializar o schema existente.
`pipeline_metadata.build_assisted_run_metadata` projeta resultados tipados de
pesquisa, roteiro, cenas, áudio, timeline e render no JSON público; `_run_pipeline`
coordena os estágios sem montar esse schema campo a campo.
O resultado de planejamento/enrichment carrega apenas cenas semânticas e
spans; `Chapter` é criado nas fronteiras que serializam ou consomem o formato
histórico. A folha de contato e o dry-run leem `SemanticScene` diretamente.
O teleprompter também combina texto semântico e spans tipados, validando a
ordem das cenas antes de distribuir as falas no tempo.
O `rerender` replaneja geometria visual com os mesmos contratos, preservando
ordem manual sem converter Chapter dentro do replanejamento.
Finalize usa `TimelineSpan` para extensão após áudio e métricas; Chapter só é
carregado para adaptar o `timeline.json` salvo e reserializado se tempos mudam.
O render silencioso recebe os mesmos contratos: identidade/texto vêm de
`SemanticScene`, duração vem de `TimelineSpan`, e a assinatura das transições
rejeita batches desalinhados. A seleção vira `SceneRenderPlan` com apenas
identidade de cena e caminho/tipo do asset. Geração cria-o de `MediaStageResult`;
finalize e rerender usam adaptador nomeado do `media.json` histórico, sem fingir
que os metadados editoriais legados foram validados. `Chapter` é adaptado ao
reabrir projetos salvos; não participa da escolha de segmentos no render.
No consumo de mídia, `logical_queries`, `provider_requests` e
`provider_search_calls` têm unidades próprias; retries são separados e o tempo
de adapter inclui seus retries/backoff. `download_durations` mede a cadeia
remota de cada asset, retries/fallback incluídos; `downloads_time` soma essas
cadeias e pode exceder tempo de parede quando downloads sobrepõem. A duração
individual de cada tentativa HTTP de busca continua desconhecida, então
`time_per_request` é `null`.
O enriquecimento pós-planner de contexto está centralizado em
`scene_enrichment.py`: consome cenas semânticas e devolve uma transformação
validada sem mutar a saída do planner. Contexto global, âncoras, aliases
verificados e contexto etimológico têm transformações puras; `Chapter` só é
projetado no final para manter timeline/render e `chapters.json` compatíveis.
`scenes.build_semantic_scenes` e `build_local_semantic_scenes` retornam
`ScenePlanResult` com cenas semânticas e tempos separados. `pipeline_scenes.py`
coordena planner/cache/enrichment e retorna `SceneStageResult`, que carrega o
resultado enriquecido como batch canônico, spans alinhados, origem e invalidação
de mídia explícita; não mantém uma segunda cópia das cenas. LLM e fallback local convergem para `SemanticScene`
antes de enrichment; `TimelineSpan` carrega somente duração e limites temporais,
e a projeção `SemanticScene + TimelineSpan → Chapter` atende consumidores de
timeline/render. A projeção `Chapter → SemanticScene` não cria
mais representações pela narração; somente cache legado incompleto passa por
recuperação determinística explícita, marcada e persistida na fronteira de
leitura. A projeção também não sincroniza implicitamente `visual_queries` com
`representations`: estas são a fonte canônica e as queries são uma projeção
compatível derivada delas. Consultas legadas/declaradas recebem proveniência
própria e não passam a contar como intenção semântica estruturada no scoring.
`ScenePlanResult` valida ids únicos e correspondência ordenada entre cenas e
spans; `SemanticScene.from_dict` valida e reconstrói o contrato sem passar por
`Chapter`. O SearchPlanner mantém a ordem combinada das consultas e não trata
esses espelhos como representações editoriais independentes.
O cache canônico do pipeline fica em `script/scene-plan.json` (schema 1), com
semântica e `TimelineSpan` separados. Projetos existentes migram ao serem lidos
de `chapters.json`; esse arquivo continua sendo atualizado como projeção para
CLI, TUI e render enquanto esses consumidores forem dependentes do formato.
`scene-plan-manifest.json` liga o plano ao hash do roteiro, aos parâmetros do
planner e ao contexto semântico; plano canônico sem identidade compatível é
recalculado. O manifesto persiste somente o hash, não os valores de configuração.
`pipeline_timeline.py` converte Chapters temporizados e seleções em
`VisualTimelineResult`, grava as inserções opcionais e atualiza as métricas de
beats no mesmo limite.
`pipeline_audio.py` consome `SemanticScene[]` e `TimelineSpan[]`; o alinhador
`stages/timing.py` devolve spans novos a partir de word boundaries ou pacing
proporcional. O `AudioStageResult` traz warnings e tempos próprios do estágio;
o coordenador os mescla explicitamente, sem emprestar seus dict/list de estado.
`timeline.json` continua sendo uma projeção `Chapter` enquanto subtitle, render
e rerender migram para o contrato separado.
`pipeline_visual.py` resolve a seleção em ordem manual → cache de projeto
validado → aquisição e retorna `MediaStageResult` com origem explícita; o
contrato tipado em `media/selection_result.py` valida IDs únicos, identidade e
coerência entre asset/entries/decision. Contagens de seleção são derivadas desse
contrato. `to_rows()` projeta explicitamente o schema persistido para consumidores
ainda em migração; o coordenador não cria rows só para testar se há cenas. A
seleção tipada segue diretamente para fonte/créditos, timeline, render, metadata e
review; cada owner projeta o formato externo que ainda precisa. `pipeline_timeline`
exige esse resultado tipado e valida o
alinhamento entre cena, mídia e span antes de materializar o plano visual. O estágio
registra auditoria por cena e distingue seleção real,
sintética e cena sem visual; o
`pipeline_media_sources.py` registra direitos/proveniência e retorna créditos e
avisos explícitos; o mesmo componente persiste `sources.json` e `FONTES.md` nos
modos assistido e `human-pending`, para que mídia, pesquisa e créditos tenham a
mesma trilha editorial nos dois fluxos.
Review recebe `ReviewMediaPlan`: geração deriva os campos exibidos da seleção
tipada; CLI adapta explicitamente `media.json` salvo para a leitura histórica,
sem exigir que metadados antigos ausentes virem identidade editorial.
`pipeline_metadata.py` monta os campos base comuns de geração humana/assistida
consumindo `MediaStageResult`, valida os mesmos IDs de cena/span e deriva dele a
origem da seleção; só o owner persiste a projeção `media` histórica. Ele fecha
persistência de geração e finalize: mede o estágio `finalize`, grava a
mesma tabela de tempos no metadata e no arquivo de métricas, e mantém
`metrics_file` no metadata persistido. O coordenador compõe campos específicos
de cada modo.
A auditoria e a evidência de execução real desta migração estão em
[`docs/analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md`](docs/analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md)
e [`docs/relatorios/20261004-validacao-arquitetural-execucoes-reais.md`](docs/relatorios/20261004-validacao-arquitetural-execucoes-reais.md)
e [`docs/relatorios/20261005-pos-g48-validacao-arquitetural.md`](docs/relatorios/20261005-pos-g48-validacao-arquitetural.md).
As execuções pós-migração incluem uma amostra científica e outra histórica,
rerender/cache e inspeção visual. Elas confirmam contratos e ausência de reuso,
mas também registram um falso positivo grave (Parlamento de Budapeste para
Mohács) e busca incompleta quando providers falham; a aquisição histórica
continua sendo uma limitação aberta, descrita no relatório.
O relatório desta migração de contratos está em
[`docs/relatorios/20261004-migracao-contratos-cenas.md`](docs/relatorios/20261004-migracao-contratos-cenas.md).
`SemanticScene` separa os campos semânticos dos tempos em `Chapter`. Planner
LLM, reparos estruturais e fallback local produzem esse contrato diretamente;
`Chapter` é uma projeção explícita para persistência compatível e consumidores
de timeline/render.
Seleções de imagens manuais também registram `SelectionDecision`, incluindo
quando um arquivo precisou ser reutilizado em rodízio.
As durações, tipos e assinatura de transições são produzidos juntos em um
`RenderTransitionPlan`, compartilhado por geração, preparação humana e finalize.
Geração também delega composição final, seleção de áudio e decisão de cache a
`pipeline_render.run_render_stage`: o coordenador monta um `RenderStageInput`
validado por campos nomeados e consome `RenderStageResult`.
Cada cena no resultado de mídia precisa carregar uma `SelectionDecision`,
inclusive cartões sintéticos e cenas sem asset.
O VisualPlanner não lê narração: representações locais são criadas no estágio
de planejamento local de cenas, materializadas no contrato e então consumidas
por VisualPlan/SearchPlan.
`planning_mode` registra a proveniência LLM/determinística; o prefixo textual
`local fallback` é interpretado apenas ao carregar capítulos antigos. Scoring
consome assunto/evento/representações declarados e não extrai termos da narração.
Timeline pode ordenar inserções apenas com queries/representações do plano;
narração não preenche evidência que faltou no planejamento.
Aquisição automática tem um único caminho (`visual.fetch_media_multi`);
`pipeline_media.py` trata apenas mídia manual e estado de standby.

Princípio editorial: *o vídeo pode simplificar uma ideia para torná-la
acessível, mas não deve falsificá-la para torná-la mais viral.*

## Status

Em evolução (v0.2): dois fluxos de produção.

```text
Fluxo A (narração IA):
IDEIA → ROTEIRO → CENAS → MÍDIA → NARRAÇÃO → LEGENDAS → VÍDEO FINAL

Fluxo B (narração humana):
IDEIA → ROTEIRO → CENAS → MÍDIA → SILENCIOSO + TELEPROMPTER
→ (você grava) → FINALIZE → VÍDEO FINAL
```

## Requisitos

- Linux, Python 3.11+
- `ffmpeg` + `ffprobe` (renderização)
- `espeak-ng` com voz `pt-br` (fallback local offline)
- Internet (só para a voz neural padrão; sem rede, usa espeak-ng)
- Opcional: GPU Intel com VA-API (ex.: Arc B580) — sem ela, usa CPU (libx264)

## Instalação

```bash
./scripts/install.sh
video-gen doctor   # ou: ./scripts/run.sh doctor
```

O `install.sh` tenta `pip install -e .` para criar os comandos `video-gen` e
`curio-tui`. Sem rede/sem pip, use `./scripts/run.sh` (roda direto do código).

## Uso

```bash
# Gerar um vídeo (narração IA, com mídia dinâmica)
video-gen generate "De onde veio a palavra salário?"

# Duração automática (padrão: o conteúdo manda) ou meta à sua escolha
video-gen generate --duration 30 "O que é um satélite?"
# auto/30/45/60/90/120/180 ou segundos (5..600) — meta, nunca corta nem
# acelera a fala; sem --duration, o vídeo tem o tamanho do conteúdo

# Gerar base para narrar você mesmo (silencioso + teleprompter)
video-gen generate --narration human "De onde veio a palavra salário?"
# abre a pasta do teleprompter + Audacity sozinho (desliga com --no-open
# ou CURIO_AUTO_OPEN=0; binários em config.toml [teleprompter])
# ...grave sua voz, depois:
video-gen finalize de-onde-veio-a-palavra-salario --audio minha-voz.wav

# Roteiro já pronto (narração preservada; Curio monta o restante do vídeo)
video-gen from-script meu-roteiro.txt --narration ai
# 1-5 fotos por cena com sobreposição estilo álbum (--max-images 3);
# SFX discretos em ~1/3 das inserções (desliga com CURIO_VISUAL_SFX=0)

# Refazer tudo do zero (padrão: reaproveita artefatos existentes)
video-gen generate --force "O mito dos capacetes com chifres dos vikings"

# Interface visual em terminal (abre a TUI)
video-gen tui
# Atalho: ./scripts/run.sh sem argumentos também abre a TUI
# Em "Roteiro pronto", cole o texto em várias linhas e termine com
# <<FIM_DO_ROTEIRO>> em uma linha isolada.

# Listar vídeos e ver metadados
video-gen list
video-gen info --slug salario

# Verificar um vídeo contra os critérios do MVP (PRD §19)
video-gen verify --slug salario

# Métricas de cada vídeo (tempo, consumo, tamanhos) em metrics/
video-gen metrics --slug salario
# sem --slug: gera para todos os projetos (a partir do metadata quando
# a execução é anterior à metrificação)
```

Backfill recupera duração, plano visual, assets e decisões por cena do
`metadata.json`. Requests, tokens e downloads sem registro persistido ficam
nulos; não são estimados.

O relatório visual também distingue assets únicos, cenas com asset novo,
cenas com reuso e cenas sintéticas. Reuso só ocorre após busca por
representações específicas e contextuais e tentativa de visual local.

Progresso esperado:

```text
[1/6] Gerando roteiro... OK
[2/6] Interpretando cenas... OK
[3/6] Buscando mídia... OK
[4/6] Gerando narração... OK
[5/6] Sincronizando legendas... OK
[6/6] Montando vídeo... OK

Output: output/salario/render/final.mp4
```

## Gêneros editoriais

A TUI pergunta o gênero **antes** da ideia, com uma lista vertical
(`↑ ↓`, `Enter`, `Esc`) que mostra a descrição e o ritmo do perfil selecionado.
A escolha muda a pesquisa, então pedir o tema primeiro seria escrever contra o
formato errado. O `dry-run` e a folha de contato mostram o gênero escolhido e
os números que ele produziu.

O gênero não é um prompt com outro texto em cima. Ele é um perfil
que age em seis etapas:

| Etapa | O que o perfil decide |
|---|---|
| **pesquisa** | os termos que entram **antes** das keywords genéricas, e o que as fontes precisam distinguir (numa etimologia, origem documentada de hipótese e de etimologia popular) |
| **roteiro** | a estrutura narrativa a seguir e o que não escrever (biografia não é hagiografia; resumo histórico não é cronologia seca) |
| **cenas** | quantas cenas o mesmo roteiro vira, e os segundos de cada uma |
| **visual** | a escada de meio (etimologia põe tipografia antes de foto; ciência põe diagrama antes de foto decorativa) |
| **legendas** | densidade e destaque, que é a segunda coisa que se percebe sem ver o título |
| **metadados** | `genre` e `genre_profile` no `metadata.json` |

### Os seis perfis

| chave | ritmo | legenda | o que o torna ele |
|---|---|---|---|
| `history` | 9,0 s | 5 palavras | quedas de impérios, crimes e desastres como narrativa, nunca como aula |
| `etymology` | 7,5 s | 4 | a palavra hoje, a forma antiga, a transformação; tipografia é parte da composição |
| `mythology` | 12,0 s | 6 | o mito como produto humano do seu tempo, com a tradição de lado |
| `mystery` | 11,0 s | 5 | fato e hipótese mantidos separados; nunca resolve o que as fontes não resolvem |
| `science` | 14,0 s | 6 | tempo para o diagrama ser compreendido; nunca laboratório decorativo |
| `people` | 13,0 s | 6 | primeiro resolve **quem** é a pessoa, depois a trajetória e o legado |

O mesmo roteiro de 298 palavras vira 16 cenas em etimologia, 12 em
história, 11 em mistério, 10 em mitologia e 9 em ciência e pessoas.

### Sem gênero, nada muda

`genre = ""` (o padrão) não é um perfil: é a ausência dele. O teto de
cenas volta a ser 12, o pacing 9,0 s e a legenda 5 palavras — os mesmos
números de antes do recurso, verificados por teste. `history` é o perfil
que reproduz o comportamento antigo **de propósito**, para quem quiser
escolhê-lo explicitamente.

Um projeto gerado antes do recurso não tem `genre` no `metadata.json`, e a
revisão o lê sem reclamar.

Via CLI, use `CURIO_GENRE` ou `genre` no `config.toml`.

## Tipografia por gênero

Trocar a fonte do vídeo inteiro não cria identidade editorial — cria uma
diferença de glifo. O que faz um vídeo de História de Pessoas parecer um
livro em vez de um post é a distinção entre **a voz que narra** e **a voz
que cita**. Por isso a fonte decide por **papel**, e não globalmente.

A cena declara a **função** do texto, nunca a fonte:

```json
{"text": "Ora et labora", "role": "quote", "language": "la"}
```

E o perfil do gênero decide o desenho. Uma cena que escrevesse
`font = "Minion Pro Italic"` quebraria a abstração no instante em que o
gênero muda, e trocar de gênero é justamente o que precisa ser barato.

### Os papéis

`title` · `person` · `subtitle` · `kicker` · `caption` · `quote` ·
`document` · `latin` · `term` · `date` · `location` · `emphasis` · `concept`

O papel mapeia para uma **intenção** (`serif`, `serif_italic`, `sans`,
`mono`, `condensed`), e a intenção resolve para uma família. É essa
separação que permite que dois gêneros usem as mesmas intenções com
fontes diferentes, e que trocar `primary` mova todos os papéis serifados
de uma vez.

Em `people`, `title` e `person` são serifada de leitura, e `quote`,
`document` e `latin` são **itálico serifado** — a Minion Pro Italic é
recurso editorial, nunca a fonte do vídeo. A legenda fica de fora por
decisão: legibilidade vale mais que estilo, e nenhuma configuração
redireciona esse papel.

### As fontes de cada gênero

| gênero | serifada / itálico | sem serifa | mono |
|---|---|---|---|
| `people` | Minion Pro / Minion Pro Italic | Inter | Source Code Pro |
| `history` | Minion Pro / Minion Pro Italic | Inter | Source Code Pro |
| `etymology` | EB Garamond / EB Garamond Italic | Inter | Source Code Pro |
| `mythology` | Adobe Caslon Pro / Adobe Caslon Pro Italic | Inter | Source Code Pro |
| `mystery` | Source Serif Pro / Source Serif Pro Italic | Roboto Condensed | IBM Plex Mono |
| `science` | Noto Serif | Inter | JetBrains Mono |

`etymology` põe o termo em corpo de destaque porque ali a tipografia **é**
o diagrama: as formas históricas da cadeia recebem o tratamento
documental, e a forma atual fica no corpo de título. `mystery` usa mono
para data, lugar e identificador, o que separa fato de testemunho na
tela. `science` não tem ornamento em lugar nenhum.

### Fontes: nunca assumidas, nunca baixadas

A Minion Pro é proprietária e não está em máquina nenhuma por padrão.
O curio **não baixa fonte alguma** — nem a proprietária, nem uma
substituta. Ele pergunta ao fontconfig o que já está instalado e, quando
a pedida não existe, cai numa cadeia genérica da mesma função
(`EB Garamond` → `Noto Serif` → `Liberation Serif` para serifada;
`Noto Sans` → `Liberation Sans` para sem serifa).

Duas armadilhas do fontconfig são tratadas explicitamente:

- ele **substitui em silêncio**. `fc-match "Minion Pro"` responde
  `Noto Sans`. O curio exige que o nome pedido volte na família
  resolvida, senão isso não é fallback, é outra fonte;
- quando a família **não tem itálico**, ele devolve o **regular** e
  reporta sucesso. `fc-match "EB Garamond:italic"` responde `Regular`
  aqui. Aceitar isso colocaria a citação na mesma fonte da narração e a
  distinção inteira sumiria **sem erro e sem log**. O curio confere o
  estilo resolvido e cai para a próxima candidata se não for itálico.

O itálico que vence é o **irmão da família que a voz principal já
resolveu**: título em EB Garamond pede o itálico do EB Garamond, e não
"qualquer serifada". Sem isso a citação sairia numa família parecida com
a do título, o que parece acidente em vez de decisão.

`video-gen doctor` diz, papel a papel, qual família foi pedida e qual
respondeu. "Minion Pro não está instalada" é uma frase que o autor
precisa ler antes de gastar quarenta minutos de render.

A folha de contato e o `dry-run` mostram a mesma linha, com a família que
**respondeu** e, quando foi fallback, a que foi pedida:

```
Tipografia: título: Utopia · citação: Utopia itálico (pediu Minion Pro Italic) · legenda: Archivo Black
```

Os dois leem o que está gravado no `metadata.json`, e não resolvem de
novo: se o gravado e o resolvido divergirem, o vídeo foi montado com
outra fonte, e a revisão é o pior lugar para esconder isso.

### O par, e por que o título e a citação não saem em famílias diferentes

Quando a família pedida não existe — ou existe mas não tem itálico — o
gênero inteiro desce para a primeira da cadeia que tem **os dois rostos**.
A alternativa ingênua resolve as duas vozes de forma independente e
produz um título numa família e a citação em outra: uma old-style e uma
transitional, nenhuma das duas Minion. Duas famílias no mesmo vídeo leem
como dois vídeos colados.

Na cadeia genérica, **Utopia** abre a lista de serifadas, e não por gosto:
foi desenhada por Robert Slimbach, o mesmo da Minion Pro, e vem nos dois
rostos nas distribuições Linux. Uma família que você fixar no
`config.toml` é respeitada mesmo sem itálico, porque isso é escolha e não
preferência — a regra do par existe para consertar os nossos padrões, não
para desobedecer aos seus.

### Onde a tipografia não entra

Duas superfícies ficam de fora, por decisão:

- **legendas queimadas** — a fonte de exibição pesada, como antes. A
  legibilidade vem primeiro, e nenhuma configuração redireciona esse
  papel;
- **teleprompter** — é um arquivo de narração, não de identidade
  editorial. Vai para um monitor onde alguém lê o texto ao vivo.

### Trocar a fonte

No `config.toml`, por gênero e por intenção:

```toml
[typography.people]
primary = "Minion Pro"        # todos os papéis serifados
italic = "Minion Pro Italic"  # citação, documento, latim
fallback = "EB Garamond"      # cabeça da cadeia genérica

[typography.people.roles]
quote = "Cormorant Garamond"  # escape hatch: um papel só
```

Nomes são escritos como se escreve: `italic = "Liberation Serif Italic"`
funciona, porque o sufixo de estilo vira a consulta `família:italic`.
Uma família que não exista **não** apaga a serifada do papel — ela cai
na cadeia do gênero. Também por ambiente, para quem não mantém
config.toml:

```sh
CURIO_TYPOGRAPHY_PEOPLE="primary=Minion Pro;italic=Minion Pro Italic"
```

## Escolha visual: como cada cena é visualizada

O requisito não é que a cena tenha uma **fotografia** — é que ela tenha
**um visual final**. Quando a foto não serve ao conteúdo, trocar de
medium é a resposta certa, e uma imagem genérica "só para preencher" nunca
entra.

Cada cena declara, na etapa de cenas, o que precisa mostrar e como:

| `visual_type` | Quando | Estratégia |
|---|---|---|
| `literal` | dá para fotografar (objeto, lugar, animal) | foto → arte → cartão |
| `mechanism` | a cena explica **como** algo funciona | **diagrama** → cartão |
| `historical_art` | santos, antiquity, religião, mitologia | **arte de domínio público** → foto → cartão |
| `typographic` | a ideia **é uma palavra** (etimologia, termo, data) | **cartão** |
| `conceptual` | abstrato demais para fotografar | cartão → diagrama |

Fluxo da decisão:

```text
roteiro → contexto global → intenção visual por cena → representações
        → queries → providers → gate técnico e semântico
        → relevância temática + relevância da cena → ranking → visual/fallback
```

Diagrama e cartão são gerados por código (Pillow, já usado no projeto),
sem rede e sem licença de terceiros. Nenhum deles inventa conteúdo: as
palavras vêm do que a cena declarou.

**Gate técnico** rejeita licença bloqueada, resolução insuficiente,
arquivo acima do teto e termos decorativos/proibidos. **Gate semântico**
separa relevância para o tópico do vídeo e para a cena atual. Usa frases
completas da intenção e representações, além de descrição, tags, categorias,
data e tipo quando o provider fornece esses metadados. Um token compartilhado
não aprova imagem.

O ranking prioriza relevância da cena, depois tópico, qualidade e diversidade.
Metadata do provider informa evidência e desempate; não substitui prova da
representação. Abaixo do mínimo, a cena troca de estratégia visual em vez de
usar candidato "menos ruim". Decisão, queries, providers, evidências,
rejeições e fallback ficam em `media.json` e `metrics/*.json`.

Quando o planner LLM falha, frases completas das queries locais também podem
provar relevância da cena. Nomes alternativos confirmados pela pesquisa entram
no contexto de scoring. Termos com uma palavra não provam identidade.

Provedores sem chave não quebram o fluxo: `video-gen doctor` lista cada
um e o motivo de cada exclusão. Para `historical_art`, os museus (Met, AIC)
e Wikimedia são consultados antes dos bancos genéricos; só entra obra em
domínio público com imagem e direitos claros.

Queries locais vêm de representações visuais concretas validadas, preservam
o tópico ou alias confirmado e recebem variantes adequadas ao tipo de cena
(evento, pessoa, lugar, exército ou artefato). Palavras isoladas, verbos e
ordinais não viram âncoras; uma busca só é marcada como esgotada quando as
queries razoáveis foram executadas sem falhas de provider. A auditoria por
cena registra representações descartadas, queries executadas, providers,
resultados, rejeições, duplicatas e fallback em `media.json`. Consulte o
[relatório de formação de queries e validação histórica](docs/relatorios/20261004_relatorio-formacao-queries-diretor-visual.md).

## Revisão humana

```bash
video-gen review --slug <slug>              # abre review/contact_sheet.html
video-gen review --slug <slug> --dry-run    # a decisão por cena, em texto
video-gen swap --slug <slug> --scene 3 --pick 1
video-gen rerender --slug <slug>
```

A folha de contato é um HTML estático com uma linha por cena: o texto, o
tipo de visual, a imagem escolhida com nota, provedor e licença, e **os
motivos das principais rejeições**. É o que permite revisar um vídeo em
~1 minuto e corrigir o tema em vez de adivinhar.

`swap` delega a escolha à política de seleção: reordena os candidatos locais,
sincroniza `SelectionDecision` com o asset primário e marca reuso se a imagem já
foi atribuída a outra cena. O CLI só verifica o arquivo local e persiste o
resultado. `rerender` refaz o vídeo e as legendas a partir do que mudou — **sem**
re-sintetizar a narração, sem re-pesquisar e sem chamar o LLM.

## Configuração

Copie `config.example.toml` para `config.toml` e ajuste (duração-alvo, voz,
backend de render `auto|vaapi|qsv|cpu`, resolução, legendas). Variáveis de
ambiente (`CURIO_OUT_DIR`, `CURIO_TTS`, `CURIO_BACKEND`, …) sobrescrevem o
arquivo. Chaves de API nunca vão no código nem no repo — use `.env`
(gitignored; veja `.env.example`).

### Variáveis que valem a pena conhecer

| Variável | Efeito |
|---|---|
| `CURIO_GENRE` | gênero editorial: `history`, `etymology`, `mythology`, `mystery`, `science`, `people` (vazio = nenhum) |
| `CURIO_TYPOGRAPHY_<GÊNERO>` | fonte por gênero sem config.toml: `"primary=Minion Pro;italic=Minion Pro Italic"` |
| `CURIO_CLIP_ENABLED` | liga reranking CLIP opcional (`1`/`true`; desligado por padrão) |
| `CURIO_CLIP_DEVICE` | device CLIP: `auto`, `xpu`, `cuda`, `mps` ou `cpu` |
| `CURIO_CLIP_ALLOW_CPU` | permite CPU com device `auto` (`1`/`true`) |
| `CURIO_CONTACT` | **defina isto.** contato no `User-Agent`; sem ele a Wikimedia responde `429` a tudo, o que derruba a pesquisa e as imagens do Commons |
| `CURIO_WIKI_UA` | substitui o `User-Agent` inteiro, se preferir |

O `doctor` avisa quando o contato não está configurado. A Wikimedia
exige `nome/versão (contato) biblioteca/versão`, e sem contato a resposta
não é um erro legível — é `HTTP 429` em toda requisição.

### Seleção de mídia

| Chave (config) | Variável | Padrão | O que faz |
|---|---|---|---|
| `[media] providers` | `CURIO_MEDIA_PROVIDERS` | `pixabay,unsplash,pexels,nasa,met,aic,wikimedia` | ordem de tentativa; `none` desliga |
| — | `CURIO_MEDIA_SCORE_MIN` | `34` | nota mínima (0–100); `0` desliga o corte |
| — | `CURIO_MEDIA_MIN_DIMENSION` | `1080` | lado mínimo em px |

### CLIP opcional (desligado por padrão)

O gate temático e de cena por metadados roda sem dependências ML. CLIP só
reranqueia shortlist que já passou pelo gate; não pesquisa e não reabilita
candidato rejeitado. Instale a extra apenas se quiser CLIP:

```bash
pip install 'curio[clip]'
```

Ative em `[visual]` com `clip_enabled = true` ou via `CURIO_CLIP_ENABLED=1`.
`auto` usa XPU, CUDA ou MPS disponíveis. CPU exige `clip_device = "cpu"` ou
`clip_allow_cpu = true`. A primeira execução habilitada pode baixar pesos do
modelo; execução normal não carrega modelo nem baixa pesos. `video-gen doctor`
mostra disponibilidade e device.

## Estrutura de saída

```text
output/[<genero>/]<AAAAMMDD-titulo>/
├── script/script.txt + title.txt + artifacts.json + scene-plan.json
│   └── scene-plan-manifest.json + chapters.json (projeção compatível)
├── media/media.json (+ cache/media/ global com licenças)
├── timeline/timeline.json (+ visual_timeline.json no modo roteiro-pronto)
├── audio/narration.wav + words.json + tts-manifest.json (IA) / human.wav
│   └── sfx.wav + mixed.wav (SFX discretos, só roteiro-pronto com inserções)
├── sources/sources.json (claims factuais + procedência de mídia)
│   └── FONTES.md (o mesmo em texto claro: fontes, imagens, créditos)
├── review/contact_sheet.html (revisão visual por cena)
├── teleprompter/teleprompter.mp4 (fluxo humano: fonte grande, marca a virada de cena)
├── subtitles/subs.srt + subs.ass
├── render/silent.mp4 + final.mp4
└── metadata.json (capítulos, assets, licenças, tempos, visual_report)
```

Com gênero escolhido, o projeto cai em `output/<genero>/` (uma pasta por
gênero: `people/`, `history`, …); sem gênero, fica direto em `output/`.
O nome da pasta é `AAAAMMDD_titulo` (só a data de hoje + título); se dois
vídeos do mesmo dia tiverem o mesmo título, o segundo ganha `-2`, `-3`…
Projetos antigos em `output/<slug>` continuam abrindo normal nos comandos
`review`, `swap`, `rerender`, `verify`, `sources` e `finalize`.

## Roteiros via LLM (chain com rodízio)

```bash
cp .env.example .env
# edite .env e preencha ao menos uma chave (gere em):
# NVIDIA https://build.nvidia.com · OpenRouter https://openrouter.ai/keys
# Groq https://console.groq.com/keys · Mistral https://console.mistral.ai
# Gemini https://aistudio.google.com/apikey
./scripts/run.sh generate "De onde veio a palavra salário?"
```

Ordem preferencial: Groq → NVIDIA → OpenRouter → Mistral → Gemini. O Curio
para no primeiro provider que responde corretamente. NVIDIA espera sem limite
de resposta e fica em segundo lugar após Groq; HTTP 400 remove NVIDIA do resto
da execução. `video-gen doctor` mostra status e modelo de cada provider. Sem nenhuma
chave, o pipeline usa o gerador local (base curada + template, custo
zero). Com roteiro em cache, a API **não** é chamada de novo — salvo
com `--force`.

Modelos: NVIDIA `meta/llama-3.3-70b-instruct`, Groq
`openai/gpt-oss-20b`, OpenRouter
`meta-llama/llama-3.3-70b-instruct:free`, Mistral `mistral-small-latest`
e Gemini `gemini-2.5-flash`. Troque via `*_MODEL`.

Robustez: até **6 rodadas globais de provider** (`CURIO_LLM_ATTEMPTS`,
1–12) com retries HTTP/backoff internos para erros transitórios. O resumo
final distingue rodadas do rodízio de requests HTTP consumidos dentro delas;
um provider que esgota seus retries não volta a abrir outro bloco de tentativas
na mesma execução. Erro HTTP 400 e outros 4xx, exceto 429, tiram o provider
do rodízio. Sem nenhuma chave, vale o gerador local acima.

Timeouts de chamada: NVIDIA usa **espera de resposta ilimitada**; sua
**conexão/handshake continua em 10 s**
(`[nvidia] connect_timeout` ou `NVIDIA_CONNECT_TIMEOUT`) e
(`[nvidia] connect_timeout` ou `NVIDIA_CONNECT_TIMEOUT`). Rede ou endpoint
sem handshake continuam falhando rápido. Os outros providers usam o limite
global padrão de 120 s (`[nvidia] timeout_max` ou `NVIDIA_TIMEOUT_MAX`).
Assim, Groq pode falhar e liberar o segundo lugar para NVIDIA; depois de um
HTTP 400 da NVIDIA, o rodízio segue para OpenRouter/Mistral/Gemini sem tentar
NVIDIA de novo naquela execução.

`CURIO_LLM_ATTEMPTS` limita as rodadas globais de seleção de provider. Os
retries HTTP dentro de cada rodada aparecem separadamente no diagnóstico; um
provider que esgota os retries transitórios sai do rodízio daquela execução.

Groq usa base oficial `https://api.groq.com/openai/v1`. Para GPT-OSS,
Curio solicita `reasoning_effort=low`
para reservar o orçamento de completion para o conteúdo e envia um User-Agent
identificando o Curio. Erros HTTP Groq preservam status e mensagem real da API
em vez de serem presumidos como chave inválida. A etapa JSON de cenas registra
`finish_reason`, `max_tokens`, tokens de completion disponíveis e tamanho da
resposta; JSON sintaticamente válido que não reproduza o roteiro continua sendo
rejeitado pelo gate literal e cai para a divisão local.

Mistral usa API OpenAI-compatible em `https://api.mistral.ai/v1` e chave
`MISTRAL_API_KEY`. Erros 4xx preservam mensagem original sem expor a chave.

Para múltiplas chaves NVIDIA futuras existe `NVIDIA_API_KEYS="key1,key2"`
(aceita na config, usa a 1ª; **rotação ainda não implementada**).

## Como funciona

| Etapa | Implementação MVP |
|---|---|
| Roteiro | chain LLM (Groq → NVIDIA → OpenRouter → Mistral → Gemini; timeout finito e fallback local de cenas); tom conversado (conta como a um amigo, sem jargão); sem chave: base curada + template |
| Cenas | divisão semântica via LLM do chain (JSON) ou local; HTTP 429 tem até 2 tentativas curtas por provider; falha do chain usa divisão local que preserva roteiro e tópico |
| Mídia | consulta vários provedores, filtra com motivo, pontua por relevância sobre o assunto e corta abaixo do mínimo; sem foto boa a cena vira diagrama ou cartão, nunca imagem genérica |
| Fontes | registro persistente de claims factuais (status de evidência) + procedência de mídia por obra; CLI `sources`; `FONTES.md` com fontes, imagens e créditos prontos; URLs exatas da pesquisa |
| Narração | edge-tts neural `pt-BR-AntonioNeural` (masculina, grátis, sem login); fallback espeak-ng offline — ou sua voz via teleprompter |
| Legendas | timestamps reais (Edge WordBoundary / Whisper); blocos curtos na base, Archivo Black com caixa preta sólida |
| Título | pergunta curta gerada pela IA a partir do roteiro (metadados `video_title`), queimada nos primeiros 5 s |
| Render | segmentos por cena concatenados; VA-API → QSV → libx264; 1080×1920, 30 fps |

### Variedade de mídia no render

Assets relevantes selecionados alternam como fundos nos beats já planejados.
O orçamento de inserções limita fotos sobrepostas, não a variedade dos fundos.
Entre candidatos aprovados, o Curio prefere assets ainda não usados; repetição
por falta de alternativas fica marcada como `eligible_pool_exhausted`.

Métricas distinguem tentativas de seleção, assets únicos selecionados/disponíveis,
origem (`download` ou `cache`) e `visual_asset_beat_counts` por provider/asset.
`visual_assets_reused` conta reuso entre cenas; manter uma foto durante vários
beats de câmera não conta como nova seleção. O cache de segmentos considera
assets, arquivos e apresentação. `rerender` usa a timeline temporizada e grava
novas métricas sem gerar outra narração.

### Diagnósticos de fontes e mídia

A pesquisa começa pelo tema amplo e consolida trechos literais com suas URLs.
Com LLM configurado, um planejamento curto seleciona fatos relevantes e lacunas
essenciais. A mesma etapa executa no máximo três buscas específicas na Wikipedia,
reutilizando extração e filtro de relevância existentes. Evidência suficiente evita
novas buscas; lacunas não resolvidas seguem explícitas no contexto, que permanece
limitado a 2500 caracteres. `sources/research.json` registra fatos, buscas
complementares e motivos; métricas incluem `research.complementary_queries`.

- Cada execução cria `output/<slug>/logs/run-<timestamp>.jsonl` antes da pesquisa.
  O log registra etapas, providers, fallbacks, erros e tempos, inclusive em
  falhas ou `Ctrl+C`. Terminal mostra resumo; JSONL contém detalhes sanitizados.
  `metadata.json` aponta para `execution_log`. `metrics/` continua separado.
- Afirmações numéricas sem correspondência nas fontes continuam passando
  pelo mesmo gate de grounding. O aviso inclui o trecho do roteiro, a causa
  provável e as fontes avaliadas; consulte `sources/FONTES.md` para o relatório
  completo.
- Pesquisa sem fonte no passe estrito não trava mais o vídeo: um segundo
  passe aceita por núcleo no título (sem exigir discriminante, homônimos
  em `forbidden` continuam barrados) e um terceiro tenta núcleo + Wikipedia
  em inglês; se nada falar do tema, o roteiro sai mesmo assim com status
  `weak`, aviso explícito e incerteza no texto — nunca erro fatal no
  `generate`. A precisão vem do portão; a garantia, dos passes.
- Providers sem configuração necessária, como Pexels sem `PEXELS_API_KEY`,
  avisam uma vez por execução. A cascata de fallback continua usando os outros
  providers disponíveis.
- `metadata.json` registra `provider_downloads` por provider: candidatos
  encontrados, downloads tentados/sucedidos/falhos, HTTP 403 e outros erros.
  Cache hits não contam como novos downloads.
  `consumption.media.funnel` nas métricas separa candidatos retornados,
  duplicados, filtros, score, seleção e uso. `rejection_reasons` resume motivos;
  campos sem ocorrência podem estar ausentes (zero). `assets_rejected` inclui
  rejeições por score. `synth_diagrams` inclui cards gerados localmente.
- `media.json` registra assets repetidos em `reuse` com as cenas e o motivo
  `same_top_match`; a reutilização continua permitida. Cenas sem foto adequada
  podem receber cards ou diagramas semânticos.

O relatório do caso São Jerônimo, incluindo validação e limitações, está em
[`docs/relatorios/20260930-144326_relatorio_diagnosticos-sao-jeronimo.md`](docs/relatorios/20260930-144326_relatorio_diagnosticos-sao-jeronimo.md).

### Identidade audiovisual por gênero

O recurso vem ativado por padrão (`audio_enabled`, `music.mode=auto`,
`transitions=auto`); desligue com `--music-mode none` ou
`[audio].transitions = "none"`. O `config.toml` permite ajustar ganho,
ducking e autopreenchimento. A biblioteca persistente fica em:

```text
assets/library/music/<genre>/
assets/library/sfx/<genre>/<category>/
```

O render consulta somente esse acervo local. Quando abaixo do mínimo,
`auto_fill` pode preenchê-lo até o alvo; com a configuração de exemplo, o
primeiro uso pode bootstrapar o acervo. Depois de atingir o mínimo, vídeos não
pesquisam nem baixam. Limites padrão: música 3/6/10 por gênero (mínimo/alvo/
máximo); SFX 2/5/8 por categoria. O autopreenchimento pode ser desligado para
exigir atualização manual.

A única fonte automática inicial é a API oficial do Freesound. Defina
`FREESOUND_API_KEY` em `.env` (chave em
<https://freesound.org/apiv2/apply>). O Curio usa os previews oficiais e só
aceita CC0 ou CC BY; NC, ND, SA e licenças ausentes/ambíguas são rejeitadas.
CC BY mantém autor, origem e link da licença no metadata para atribuição. Não
há scraping nem download do endpoint original que exige OAuth2. Arquivos
manuais são marcados como fornecidos pelo usuário, com licença não verificada.

```bash
# atualizar música (sem --genre: gênero ativo ou todos os gêneros)
./scripts/run.sh music update --genre people
# atualizar uma categoria SFX
./scripts/run.sh music update --kind sfx --genre people --category paper
# listar acervo e contador de uso sem acessar a rede
./scripts/run.sh music list --genre people

# na geração: auto, none ou manual
./scripts/run.sh generate "Fale sobre São Jerônimo" --music-mode none
./scripts/run.sh generate "Fale sobre São Jerônimo" \
  --music-mode manual --music-file "$HOME/Music/faixa.mp3"
```

A TUI expõe Automática, Nenhuma, arquivo manual e atualização da biblioteca em
Configurações → Áudio. A seleção automática busca camas calmas/ambientais,
rejeita títulos que indiquem efeitos/ruído e revalida faixas em cache. Se não
houver faixa compatível, o vídeo sai sem música em vez de usar áudio confuso.
Entre as faixas aprovadas, favorece assets menos usados e desempata com seed
estável do projeto. A música usa ganho padrão de −3 dB (configurável entre
−40 e −3 dB), fades de
entrada/saída e sidechain ducking sob a voz, com release para atravessar pausas.
SFX da biblioteca substituem apenas eventos pontuais já existentes; sem asset
local, o SFX sintético atual continua disponível. Transições de cena têm
efeito por gênero (dissolve, fade a preto, deslizamento), duração ajustada
por gênero/papel da cena, cortes secos em mudanças dramáticas e fade final.
`[audio].transitions = "none"` desliga a camada de transição. O `metadata.json`
registra faixa/licença/atribuição, SFX, volume, ducking e identidade de cache
do áudio efetivamente renderizado. Sem foto específica, a cena tenta o
genérico do gênero (igreja, biblioteca, manuscrito) antes do cartão; cartão
sem assunto mostra a primeira frase da narração, nunca tela vazia.

## Roadmap

- **MVP (agora):** pipeline básico provando ideia → vídeo publicável.
- **V1:** pesquisa/fontes, seleção de mídia, templates, cache, TTS melhor.
- **V2:** fila de ideias, lote com dezenas de vídeos, retry automático.
- **V3:** publicação, analytics, interface local (se houver demanda real).

## Commits

Padrão [Conventional Commits](https://www.conventionalcommits.org/): `feat:`,
`fix:`, `docs:`, `chore:`, etc. Ex.: `fix: change password type from number to text`.

## Licença

MIT — ver `LICENSE`.
