# Migração incremental dos contratos de cena — 2026-10-04

## Mudanças

O planner LLM, seus reparos estruturais e o fallback local agora produzem e
transformam `SemanticScene` diretamente. A duração e os limites de timeline
viajam em `TimelineSpan`; a conversão para `Chapter` ocorre na fronteira de
persistência compatível e render.

O pipeline agora salva `script/scene-plan.json` (schema 1) como cache canônico
de semântica e spans. Quando encontra somente o `chapters.json` legado, valida
e converte os capítulos, recupera representações locais apenas quando a
recuperação legada se aplica e grava o novo plano. A leitura do plano canônico
ignora divergência de conteúdo no arquivo legado e repara a projeção antes de
devolvê-la a consumidores externos. Um schema canônico desconhecido ou inválido
falha claramente.

`ScenePlanResult` valida provenance, plano não vazio, IDs únicos e
correspondência em ordem entre cenas e spans. `SemanticScene.from_dict`
reconstrói o contrato sem usar `Chapter`.

## Verificação

- Focados de contrato, cache, integração de pipeline e seleção visual: 25
  passaram.
- Suíte completa: 843 passaram em 144,09 s.
- `compileall` e `git diff --check` passaram.
- Não foi executada uma nova geração real nesta subfase. As execuções reais
  anteriores seguem registradas em
  `20261004-validacao-arquitetural-execucoes-reais.md` e antecedem esta
  alteração.

## A4j: enrichment semântico puro

O enrichment deixa de mutar `Chapter`: as transformações de contexto global,
âncoras locais, contexto de entidade e etimologia recebem/devolvem
`SemanticScene`. `scene_enrichment` valida a batch e gera `Chapter` só como
projeção compatível de saída. Uma regressão integral mostrou o antigo `False`
de `fill_missing_context` para entidade sem nome sendo confundido com batch;
esse caminho agora retorna as cenas originais. Após a correção, os focados
passaram (39) e a suíte completa passou com 844 testes em 145,67 s.

`visual_context` e `etymology` agora rejeitam entrada que não seja
`SemanticScene` nas transformações novas. `scene_enrichment` ainda aceita
`Chapter` somente como adaptador dos caches antigos e projeta capítulos ao
final. A semântica não sofre mutação in-place durante enriquecimento.

## A4k: timing fora do planner semântico

`stages/timing.py` alinha `SemanticScene[]` a `TimelineSpan[]` sem alterar as
cenas. `pipeline_audio` retorna spans atualizados para WordBoundary ou fallback
proporcional e grava a visão legada de `timeline.json`; o pipeline só cria
`Chapter` depois desse limite. `SceneStageResult` valida que cenas, spans e
projeção correspondem em ordem. O antigo `scenes.apply_timings` foi removido
depois da migração de seu único consumidor. Focados: 66 passaram; suíte
completa: 847 passaram em 146,75 s.

## Snapshot após A4k (fronteiras migradas em A4l–A4o abaixo)

O pipeline ainda projeta `Chapter` para `chapters.json`, metadata externa,
revisão/folha de contato e consumidores de CLI que carregam projetos. A mídia,
timeline visual, teleprompter e render silencioso já usam contratos semânticos
e temporais separados. A migração continua por consumidor, preservando o
formato externo até esses limites usarem contratos tipados próprios. Cache de
aquisição permanece independente do cache semântico e não escolhe mídia.

## A4l: timeline visual e métricas recebem spans tipados

`build_visual_timeline` e `pipeline_timeline` agora recebem
`SemanticScene[] + TimelineSpan[]`; o tempo visual não é lido do objeto
Chapter. Ordenação de inserções exige `SemanticScene` e usa somente as
representações já declaradas. `retime_visual_timeline` também rejeita IDs
ausentes, duplicados ou fora de ordem, em vez de manter timestamps antigos
silenciosamente. Métricas visuais usam spans e o backfill converte linhas
históricas válidas do metadata, ignorando linhas inválidas como desconhecidas.
O formato `chapters.json` permanece como projeção para render, CLI/TUI e
compatibilidade externa. Focados: 120 passaram; suíte completa: 847 passaram
em 145,29 s; a nova regressão de desalinhamento foi validada isoladamente.
`compileall` e `git diff --check` passaram. Não houve geração real nesta fase.

A fronteira visual de planejamento/timing já não depende de Chapter. Permanecem
consumidores downstream de render, subtitles e ferramentas; também permanece
um adaptador Chapter explícito para operações legadas de replanejamento. A
próxima fase deve migrar esses consumidores antes de remover a projeção.

## A4m: teleprompter consome semântica e spans separados

`build_teleprompter_cues` e `write_teleprompter_ass` recebem agora
`SemanticScene[] + TimelineSpan[]`, validam identidade/ordem e distribuem os
blocos a partir do texto da cena e do span correspondente. `pipeline.py` usa
diretamente esses dados antes de qualquer projeção Chapter para render. O
formato ASS, texto, regras de quebra e avisos de mudança de cena foram
preservados. A regressão cobre rejeição de IDs desalinhados. Focados: 101
passaram; suíte completa: **849 passaram em 145,75 s**; `compileall` e
`git diff --check` passaram. O smoke script não chega aos testes do teleprompter:
falha antes por importar `pipeline._relevance`, removida anteriormente, e usa
`scenes._local_chapters`, também removida. Isso é dívida do script, não falha
da mudança atual.

## A4n: render silencioso recebe semântica e timeline separadas

`pipeline_render` não importa mais `Chapter`. Montagem por mídia e por visual
consome `SemanticScene[] + TimelineSpan[]`; segmentos recebem ID explícito e
duram conforme o span. Política de transição consome somente cenas semânticas,
e sua assinatura combina cenas e spans com validação de IDs. `pipeline.py`
usa os contratos produzidos na geração e no fluxo humano; finalize/rerender
convertem o arquivo Chapter histórico uma vez na entrada. A extensão de áudio
humano maior que a timeline também amplia o span usado no render, inclusive no
caminho sem visual timeline. Focados: 140 passaram; suíte completa: **850
passaram em 145,42 s**; `compileall` e `git diff --check` passaram. Sem nova
geração real nesta fase. O smoke script ainda para antes dos seus checks por
imports internos já removidos (`pipeline._relevance`, `scenes._local_chapters`).

## A4o: resultado de cenas não carrega projeção Chapter

`SceneEnrichmentResult` e `SceneStageResult` agora retornam somente
`SemanticScene[]` e `TimelineSpan[]`; removi a compatibilidade interna que
aceitava Chapter como entrada do enrichment e a duplicação `chapters[]` no
resultado do estágio. `pipeline_scenes` cria Chapter apenas ao persistir a
projeção `chapters.json`. O pipeline principal retém semântica/span em memória;
constrói Chapter depois do áudio somente para metadata, revisão e formato
compatível. Standby usa a quantidade de SemanticScene diretamente. Focados:
40 passaram; suíte completa: **850 passaram em 147,11 s**; compileall e
`git diff --check` passaram. Sem geração real nesta fase.

A fronteira de planejamento/enrichment já não depende de Chapter. Restam
adaptações de leitura/escrita do projeto salvo e metadata.

## A4p: revisão visual consome cenas semânticas

`scene_rows`, folha de contato e dry-run recebem `SemanticScene[]` e usam seus
campos tipados sem recuperar significado via `getattr`. Entrada Chapter falha
com erro de contrato, e IDs semânticos duplicados são rejeitados. Geração passa
as cenas atuais; `cmd_review` adapta o formato Chapter persistido ao carregar o
projeto. Layout, informação exibida, scoring, rejeições e arquivos gerados
permanecem iguais. Focados: 154 passaram; suíte completa: **851 passaram em
146,30 s**; compileall e `git diff --check` passaram. Sem geração real nesta
fase. A leitura e gravação do schema histórico e metadata permanecem como
fronteiras de compatibilidade.

## A4q: rerender usa contrato canônico ao replanejar a timeline visual

`rebuild_visual_timeline` recebe agora `SemanticScene[]` e `TimelineSpan[]`;
seu adaptador Chapter foi removido. A CLI ainda desserializa o projeto salvo
uma vez na entrada e passa os dois contratos ao replanejamento; a ordem manual
de imagens permanece intacta. Focados: 29 passaram; suíte completa: **851
passaram em 145,93 s**; compileall e `git diff --check` passaram. Sem nova
geração real nesta fase.

## A4r: Chapter é projetado no limite de metadata

`_base_metadata` consome `SemanticScene[] + TimelineSpan[]`, valida ordem e
projeta Chapter somente para a chave `chapters` já publicada em metadata.
Geração AI mantém a batch tipada após o áudio e calcula durações pelos spans;
human-pending só projeta na gravação legada de `timeline.json`. Removi
`ScenePlanResult.timeline_chapters`, método sem consumidores cuja documentação
indicava incorretamente que o render usava Chapter. Testes cobrem shape legado,
tempos projetados e erro para IDs desalinhados. Focados: 13 passaram; suíte
completa: **853 passaram em 147,46 s**; compileall e `git diff --check`
passaram. Sem geração real nesta fase.

## A4s: finalize mantém timing em TimelineSpan

`finalize` ainda lê `timeline.json` como Chapter para aceitar projetos salvos,
mas descarta essa projeção após derivar `SemanticScene[] + TimelineSpan[]`.
Extensão da última cena, `retime_visual_timeline` e métricas usam spans; ao
persistir tempos alterados, Chapter é reconstruído apenas para o schema salvo.
O rerender CLI usa seu batch de spans já carregado para métricas. Focados de
finalize/rerender/metadata: 5 passaram; suíte completa antes deste ajuste:
**853 passaram em 147,46 s**; após o ajuste, focados, compileall e
`git diff --check` passaram. Sem geração real nesta fase.

## A4t: aquisição e mídia manual recebem SemanticScene

`fetch_media_multi` e `_resolve_reuse_multi` recebem cenas semânticas tipadas;
`manual_media_scenes` lê campos canônicos diretamente. Os dois limites recusam
Chapter, impedindo extração ou reconstrução tardia da intenção. Removi
`_fetch_media_fallback`, órfão que repetia o comportamento de fallback da
aquisição ativa. Regressões cobrem a rejeição do formato antigo e preservam
seleção manual, mídia real e reuso validado. Focados: 49 passaram; suíte
completa: **855 passaram em 146,30 s**; compileall e `git diff --check`
passaram. Sem geração real nesta fase.

## A4u: resultado da pesquisa é validado na entrada do estágio

`pipeline_research.run_research_stage` declara `ResearchResult` como contrato
de entrada e valida o tipo imediatamente, antes de registrar fontes ou gravar
JSON. O estágio lê diretamente `target`, `rejected`, `tried_queries`,
`weak_warnings`, `facts`, `complementary_queries` e `unresolved_gaps`; removi
defaults de `getattr` que aceitavam resultados parciais e mascaravam produtor
inválido. Os testes de integração que forneciam uma lista de fontes como mock
foram migrados para construir o mesmo `ResearchResult` de produção. Uma nova
regressão prova que retorno incompleto falha antes de qualquer side effect.
Focados de pesquisa/pipeline/TTS/TUI: **50 passaram em 151,64 s**; a suíte
completa passou com **857 testes em 202,95 s**. `compileall` e
`git diff --check` passaram.


## F4: nomes de métricas distinguem seleção real e uso em timeline

As execuções reais mostraram que `visual_report.unique_assets` mede IDs reais
escolhidos, enquanto `pipeline.visual_assets_unique` inclui também cartões
sintéticos presentes na timeline. Os dois valores eram válidos em unidades
diferentes, mas os nomes pareciam contraditórios. Adicionei
`visual_timeline_assets_unique` e
`visual_timeline_assets_reused_across_scenes`, que declaram a unidade; os
campos antigos continuam como aliases para compatibilidade de schema. Uma
regressão compara cenas real/reused/synthetic e prova a distinção. Focados:
`test_media_metric_units.py`, `test_visual_asset_usage.py` e
`test_review_flow.py` — 32 passaram. `compileall` e `git diff --check`
passaram; a suíte integral passou com **858 testes em 197,12 s**.

## V1: cards sintéticos separam intenção de busca e hierarquia de texto

A inspeção do card de ciência mostrou que `visual_entities` de busca eram
desenhadas como uma cadeia explicativa junto à narração, causando colisões.
Cards comuns agora exibem assunto e um trecho de narração; cadeia de entidades
fica exclusiva do tipo tipográfico, onde ela tem significado editorial. O
rodapé usa região própria, limita a duas linhas e indica truncamento com
reticências. A chave de cache do card foi versionada para invalidar PNGs com o
layout antigo. Testes instrumentam `textbbox` real do Pillow e exigem ausência
de colisões tanto para cards científicos como tipográficos. Focados de layout,
tipografia e receipt: **124 passaram**; compileall e `git diff --check`
passaram. A suíte integral passou com **860 testes em 177,31 s**.

## G2a: roteiro e título atravessam o pipeline como artefatos validados

`generate_script` agora produz `ScriptArtifact(text, source)` e
`generate_title` produz `TitleArtifact(text, source)`, ambos imutáveis e
rejeitando texto vazio ou proveniência ausente. O coordenador cria os mesmos
contratos para roteiro fornecido, cache curado e título em cache, valida o tipo
de retorno dos produtores antes de persistir e só extrai strings ao entrar nos
consumidores e formatos atuais. CLI, TUI, fontes do roteiro, conteúdo e schema
de saída permanecem iguais. Os mocks do pipeline foram migrados dos tuples
posicionais para contratos. Focados: **13 passaram em 35,89 s**; a suíte
integral passou com **863 testes em 191,55 s**. `compileall` e
`git diff --check` passaram.

## G2b: roteiro, título e grounding têm um resultado de etapa explícito

Extraí a transição de pesquisa → roteiro/título para
`pipeline_script.run_script_stage`. Essa etapa agora é dona da seleção entre
texto fornecido, cache e geração; autocura de marcadores no roteiro cacheado;
persistência dos artefatos; verificação/apresentação do grounding; invalidação
de cenas quando o roteiro fornecido muda; e carga do título em cache ou geração.
Ela retorna `ScriptStageResult` com `ScriptArtifact`, `TitleArtifact`, grounding,
warnings, decisão de refazer cenas e duração. `_run_pipeline` compõe esse
resultado e continua dono da emissão de progresso e da transição à próxima
etapa. Os arquivos e valores externos seguem texto/schema atuais.

Uma execução integral encontrou um teste da TUI acoplado ao antigo atributo
privado `pipeline.script_stage`; migrei o patch do teste para o módulo dono do
estágio. O teste da TUI, integração, grounding e contratos passou: **28 testes
em 35,87 s**. A suíte completa final passou: **863 testes em 172,90 s**;
`python -m compileall -q src/curio` e `git diff --check` passaram.

## E3: cache de TTS tem identidade verificável

A causa concreta era dupla: `pipeline_audio` aceitava qualquer cache com
cobertura suficiente de timestamps, sem conferir se os tokens eram do roteiro
atual nem se provider/voz/idioma/configuração continuavam iguais; além disso,
um roteiro fornecido alterado invalidava cenas e mídia, mas o áudio recebia
apenas o `force` original. Agora `audio/artifacts.py` define a assinatura e o
manifesto `audio/tts-manifest.json`: hash exato do texto, provider, voz,
velocidade, duração-alvo, idioma, resultado realmente sintetizado e identidade
dos word boundaries. TTS registra `TTSResult` após sucesso; os arquivos
`words.json` de provider anterior não sobrevivem a uma síntese sem boundaries.

Caches legados sem manifesto só são migrados se `metadata.json` confirmar
duração/configuração compatível e os tokens transcritos coincidirem exatamente
com o roteiro, além de cobertura. Se essa prova faltar, a síntese é refeita; os
arquivos antigos seguem legíveis e rerender continua fora desta busca. A etapa
de roteiro agora retorna `script_changed`, que invalida explicitamente cenas e
mídia e também força TTS quando o conteúdo muda. Um teste cobre roteiro legado
com mesmo comprimento e quantidade de palavras, porém conteúdo diferente; o
teste de geração cacheada confirma a migração para manifesto. A revisão do
consumidor final encontrou outro elo da mesma cadeia: MP4 final podia ser
reutilizado quando TTS acabara de sintetizar outro áudio, se legendas e trilha
musical parecessem iguais. `pipeline_render.final_cache_is_current` agora exige
reuso vigente de narração além das assinaturas de legenda/transição/trilha.

Validação focada de TTS e integração: **21 passaram em 118,99 s**; contratos,
regressões de cache, script e render final: **13 passaram**. A checagem
específica da política de cache final confirma que narração não reutilizada
bloqueia o MP4 existente. Após todas as mudanças desta fase, a suíte integral
passou: **872 testes em 183,62 s**. `compileall` e `git diff --check` passaram.

## E4: script e título são estado editorial editável do projeto

CLI/TUI não oferecem edição retroativa de arquivos, mas os caminhos
`script.txt`/`title.txt` são artefatos de projeto que o usuário pode alterar;
`from-script` preserva texto, e rerender lê título/roteiro desses arquivos.
Não faz sentido invalidá-los automaticamente por pesquisa ou configuração. A
regeneração permanece explícita via `force`; a identidade nova registra hashes
e proveniência em `script/artifacts.json`, com o hash de script usado para gerar
o título. Se um arquivo muda depois do manifesto, o conteúdo é tratado como
edição externa, preservado e rotulado `edited`; mudança de roteiro invalida
cenas, mídia e TTS; título editado pelo usuário fica preservado. Título gerado
de roteiro que mudou é regenerado. Projetos legados sem manifesto mantêm seus
arquivos como estão na primeira migração: não existe evidência histórica para
distinguir um cache gerado de uma edição externa anterior.

Regressões cobrem script externo alterado, title externo alterado, autocura de
roteiro legacy, `force`, o caminho TUI e round-trip/validação do manifesto.
Testes focados passaram (**12**); `compileall` e `git diff --check` passaram; a
suíte integral passou com **876 testes em 189,81 s**.

## Atualização do mapa arquitetural

Ao iniciar a próxima revisão de cache, comparei a auditoria inicial com os
módulos atuais e encontrei fluxo/grafo desatualizados após as fases de
contratos. Atualizei a auditoria para separar baseline histórica do estado
revisado em `eed59d7`, e o README agora alerta que as descrições da baseline
são históricas. A checagem documental `git diff --check` passou. Nenhum código
ou comportamento foi alterado nesta atualização.

## E5: scene-plan cache has input identity

O `scene-plan.json` canônico validava somente o schema; assim, representações
poderiam sobreviver a mudanças de inputs relevantes. `scene-plan-manifest.json`
agora registra SHA-256 do roteiro, parâmetros do planner, idioma/endpoints de
modelo, diretiva de gênero, tópico/alvo, fontes de pesquisa e etimologia. Só o
digest é persistido, nunca configuração em claro ou credenciais. Plano canônico
sem manifesto compatível é reconstruído; projetos com apenas `chapters.json`
histórico continuam migráveis e recebem manifesto quando o plano canônico é
gravado.

Regressões cobrem migração legada, reuso de plano compatível e reconstrução
após divergência da identidade de inputs. Testes focados de contrato/cache de
cenas passaram (**15**); `compileall` e `git diff --check` passaram; suíte
integral passou com **877 testes em 195,02 s**.

Revisão dos argumentos do planner mostrou que `script_mode` altera a regra de
contagem de cenas e precisava fazer parte da assinatura. Foi adicionado ao
manifesto e a regressão prova que o mesmo texto em modo roteiro-pronto e em
modo ideia tem identidades diferentes; teste focado `test_pipeline_scenes.py`:
**3 passaram**.

## E6: media stage rejects internally inconsistent outcomes

O resultado de aquisição ainda cruza consumidores como rows do formato de
projeto, mas `MediaStageResult` agora valida a fronteira: IDs de cena únicos,
listas/assets com shape esperado, asset principal consistente com a primeira
entrada, `SelectionDecision` associado à cena/asset correto, status coerente
com provider (inclusive `none` sem asset) e contagens real / sintético / ausente
iguais ao conteúdo. `SelectionDecision.from_dict` valida o schema persistido,
em vez de tratar decisão malformada como seleção implícita. O JSON externo
segue compatível; migrar timeline, render, credits e review para um batch
tipado permanece uma fase posterior.

Integração/funnel/selection focados: **23 passaram em 38,58 s**; regressões
direcionadas status/provider passaram (**15 em 0,10 s**). `compileall` e
`git diff --check` passaram; a suíte integral passou com **879 testes em
184,10 s**, antes do último reforço do contrato.

## G3: base metadata has one owner

`_base_metadata` vivia no coordenador apesar de já existir
`pipeline_metadata.py`; geração assistida e preparação humana chamavam a mesma
função. Ela foi movida para `pipeline_metadata.build_base_metadata`, dona da
projeção comum `SemanticScene + TimelineSpan → chapters` e dos campos base de
metadata. O pipeline continua compondo campos específicos por modo e dono de
progresso/ordem; formato e valores persistidos foram preservados. Testes foram
migrados para a API do módulo responsável.
Testes focados de metadata e integração passaram (**11 em 40,49 s**);
`compileall` e `git diff --check` passaram. A suíte integral será repetida no
gate final após as migrações seguintes.

## R1: research output validates before side effects

O estágio verificava somente `isinstance(ResearchResult)`, apesar da nota
anterior no README dizer que validava campos. Agora `validate_research_result`
rejeita fontes sem título/URL, fontes e tuplas rejeitadas com tipos errados,
queries vazias, warnings/fatos/gaps com shape inválido e etimologia sem
contrato antes de registrar claims ou escrever `research.json`. A validação
mantém `allow_weak` e ausência legítima de fontes para fallback já existente.
Regressões provam que retorno estruturalmente incompleto falha antes de
side-effects. Pesquisa/pipeline focados: **31 passaram em 0,15 s**.

## R2: ResearchResult is the research source of truth

`ResearchStageResult` duplicava `sources`, `target`, `rejected`, `queries` e
`etymology` já existentes em `ResearchResult`; o coordenador consumia as
cópias, criando dois lugares para o mesmo fato. Removi esses campos e o
pipeline agora lê os dados diretamente do resultado validado. O retorno de
etapa mantém somente `status`, `prompt` e `elapsed`, que são próprios da
orquestração. Testes de pesquisa/pipeline passaram (**39 em 38,11 s**).

## G4: audio stage returns owned state deltas

`run_audio_stages` mutava `stage_times` e `warnings` recebidos do coordenador,
depois retornava a mesma referência de tempos dentro de `AudioStageResult`.
Agora o resultado é frozen, contém tempos e warnings criados localmente, e o
coordenador os mescla explicitamente. O contrato valida duração, spans, fonte
de timing, contagem de cues e tempos finitos/não negativos. Isso mantém
progresso/métricas/arquivos dentro das responsabilidades existentes sem
compartilhar estado geral da execução.

Testes diretos cobrem fallback proporcional, resultado imutável e rejeição de
tempos inválidos; integração/TTS focados passaram (**26 em 143,41 s**).
Revalidar com a suíte completa no gate final.

## G5: execution config cannot leak back to the UI

`_apply_audio_request` aplica as preferências salvas de um projeto mutando
`CurioConfig`, e `finalize_project` também ajusta campos para aquele fluxo.
Ambos podiam alterar o objeto que TUI/queue pretendiam reutilizar. As APIs
públicas `run_pipeline` e `finalize_project` agora fazem uma cópia profunda no
limite da execução antes de qualquer política local; configurações/arquivos do
projeto continuam sendo lidos e salvos da mesma forma. Testes unitários e
integração passaram (**10 em 37,12 s**).

## G6: teste de metadata acompanha o módulo responsável

Após mover a projeção base para `pipeline_metadata.py`, a suíte completa
apontou uma regressão no próprio teste: ele verificava por busca textual que
`pipeline.py` continha `provider_downloads` e `metrics.media_download_report()`.
Essas strings agora pertencem ao módulo dono da projeção. Migrei a inspeção
para `pipeline_metadata.py`; a asserção continua verificando a persistência do
relatório sem prender o teste ao coordenador antigo. O teste isolado passou.

Gate após a migração: `pytest -q` — **888 passed em 174,45 s**;
`python -m compileall -q src/curio` e `git diff --check` passaram. Este gate
fecha somente as fases registradas até G6; não declara concluídas a arquitetura,
as métricas ou a validação real final descritas na auditoria.

## A4v: tópico pesquisado e aliases têm autoridade/proveniência explícitas

A geração real de Mohács localizou `Batalha de Mohács` em `ResearchResult`,
mas o planner de cenas escreveu `Batalha de Ponta de Gál` no seu contexto.
`attach_video_context` preservava o tópico do planner e juntava aliases sem
proveniência; `SearchPlanner` usava qualquer string como âncora. Assim a busca
foi formada com o nome incorreto e o gate aceitou o Parlamento de Budapeste
porque o título/tags continham Danúbio/Hungria. A inspeção do asset confirmou o
falso positivo visual.

O enrichment agora aplica o alvo pesquisado como tópico canônico, mantendo o
contexto sugerido pelo planner sem autoridade para substituí-lo. Aliases sem
proveniência continuam registrados para auditoria, mas não entram nas queries.
Uma ligação de idioma da Wikipedia vira alias verificado somente com a URL da
fonte como evidência; target aliases não corroborados ficam explicitamente
não verificados. O SearchPlanner usa somente aliases verificados. Regressões
cobrem conflito de tópico, alias inventado, tópico canônico, ligação Wikipedia
e o alias editorial validado. Focados: **27 passaram**; suíte integral:
**889 passaram em 183,04 s**; compileall e diff check passaram.

Validação real comparativa atualizada em
`20261004-validacao-arquitetural-execucoes-reais.md`. No re-run Mohács, o
Parlamento deixou de vencer, mas 3/3 cenas ficaram sintéticas: 36 candidatos
foram rejeitados por ausência de evidência do tópico, busca levou 55,48 s e
providers falharam (Met 410, AIC 500; Pexels sem chave). É degradação segura
enquanto faltam candidatos eventuais adequados, não uma solução de cobertura.
A amostra M87 usou fallback local de cenas após o planner LLM produzir divisão
incompatível com a narração; a execução concluiu com mídia real, sem reuso.
Visualmente, dois IDs NASA selecionados na mesma cena têm SHA-256 igual, uma
limitação pendente da identidade por conteúdo.

## D4: identidade de asset prefere SHA-256 dos bytes adquiridos

Uma inspeção real encontrou IDs NASA diferentes com arquivo de imagem
byte-a-byte idêntico dentro da mesma cena. `asset_key` e o selector usavam URL
ou ID de provider mesmo quando `local_path` já existia, então a timeline e
`visual_report.unique_assets` contavam conteúdo repetido como único. Agora
`media.identity.asset_identity` calcula SHA-256 para arquivos locais (memoizado
por caminho/tamanho/mtime) e usa URL normalizada ou ID do provider enquanto os
bytes não estão disponíveis. A seleção compara a identidade depois do download;
se descobre duplicata, registra rejeição e continua a shortlist para procurar
outro candidato. Mídia manual, timeline, reuse e métricas usam o mesmo helper.

Regressões cobrem IDs/providers distintos com bytes iguais, continuação para
outro candidato, downloads paralelos de arquivos distintos e reuse sob a nova
chave. O primeiro gate integral revelou três fixtures antigas que atribuíam o
mesmo arquivo a IDs ficticiamente diferentes e uma que semeava a chave antiga
de reuse; as fixtures passaram a modelar respectivamente bytes distintos ou a
identidade contratual. Focados: 41 passaram antes da migração das fixtures;
depois as regressões afetadas passaram (18). Gate integral final: **891
passed em 186,93 s**, `compileall` e `git diff --check` passaram.

A geração real M87 v3 selecionou dois assets de bytes distintos em três cenas
(dois reais, um sintético, zero reuso; SHA-256 distintos 2; 24 queries
planejadas/21 executadas; mídia 53,26 s). Isso não mostra observação específica
de M87: a NASA venceu como ilustração de buraco negro e o Pixabay retornou uma
ilustração genérica; a cena de massa/ring ficou sintética com busca incompleta.
O tempo total foi 159,93 s, dos quais 81,34 s vieram de pesquisa/grounding e
53,26 s de mídia. A auditoria real anterior já reproduz o bug de identidade:
3 IDs selecionados, somente 2 hashes. A lógica nova e sua regressão evitam que
esse caso conte duplicação como diversidade; o novo run teve apenas uma imagem
por cena real, então a validação visual de diversidade intrasscene veio do
teste determinístico.

## G7: project layout tem um dono independente do pipeline

`VideoPaths`, construção de paths, resolução de referência de projeto e
listagem estavam definidos dentro de `pipeline.py`, apesar de serem consumidos
por geração, CLI e TUI. Extraí `project_paths.py` como fonte única e tornei
`VideoPaths` frozen. CLI/TUI e testes passaram a importar o módulo responsável;
`pipeline.py` usa o contrato por módulo e não reexporta a API anterior. O
layout no disco, referências `<genre>/<slug>` e projetos legados planos foram
preservados. A busca por consumidores antigos encontrou um teste de cache TTS
que ainda acessava `pipeline.video_paths`; migrei esse último consumidor antes
do gate final.

Focados da fronteira: 24 passaram antes do reforço frozen; 17 focados passaram
depois. Suíte final: **892 passed em 194,27 s**; compileall e diff check
passaram. Esta fase retira ownership de projeto do coordenador, mas geração e
finalize continuam no `pipeline.py`; a extração do fluxo finalize é próxima
fronteira independente, depois de mapear seus helpers compartilhados.

## G8: composição de áudio não pertence ao coordenador de geração

Antes da extração de `finalize_project`, o rastreamento de consumidores mostrou
que `cli.py` importava sete helpers privados do `pipeline.py` para aplicar a
configuração de áudio persistida, extrair eventos SFX, decidir fades, compor
SFX e registrar uso de trilhas. O próprio pipeline também usava esses helpers
no fluxo IA, fluxo humano e finalize. Isso era uma dependência escondida que
faria uma extração direta de finalize duplicar ou importar política do
coordenador.

Movi esses comportamentos para `audio/composition.py`. `pipeline.py` e `cli.py`
agora dependem do módulo de áudio, e testes passaram a importar a política pelo
seu dono. A decisão de trilha continua em `audio.selection`; o novo módulo
coordena composição/efeitos e aplica a escolha já persistida. Os helpers
privados foram removidos de `pipeline.py` sem manter reexports internos.

Focados: 20 testes de isolamento, render e integração passaram; 3 testes de CLI
de áudio passaram. A suíte integral passou: **892 testes em 186,96 s**;
compileall e diff check também passaram. O teste focado inicial detectou que
os builders SFX ficam em `stages.render`, e o ownership foi ligado ali, sem
alterar a política. Próximo passo após o gate:
extrair finalize usando os módulos de composição de áudio e render já donos,
com `pipeline.py` mantendo apenas a fronteira pública/log e coordenação da
geração. Código em `91c5f89`.

## G9: leitura e gravação de artefatos têm uma implementação compartilhada

`pipeline.py` definia leitura de texto/JSON e gravação JSON com criação de
diretório; CLI importava esses helpers privados do coordenador. `pipeline_visual`
mantinha uma leitura JSON duplicada para validar seu cache. Isso faria o
próximo módulo de finalize depender do pipeline ou duplicar I/O.

Extraí `project_artifacts.py` com `read_text`, `read_json` e `write_json`.
Pipeline, CLI e pipeline_visual usam a mesma implementação; os helpers locais
foram removidos. Formato UTF-8, indentação, serialização Unicode e criação
defensiva do diretório pai foram preservados.

19 testes focados de pipeline, mídia, áudio e CLI passaram; a suíte integral
passou com **892 testes em 195,38 s**. Compileall e diff check passaram. Código
em `2934469`. A próxima extração de finalize já pode ler/escrever artefatos sem
importar o coordenador; ainda será necessário mapear contratos de render,
transcrição e logging.

## G10: o workflow de finalize tem módulo e entrada próprios

`pipeline.py` mantinha junto à geração o fluxo de áudio humano: validação de
inputs, transcrição/cache, legendas, ajuste de duração do silencioso,
composição de áudio, render e metadata. O wrapper público também era usado por
CLI/TUI e precisava conservar clonagem de config, resolução de projeto,
RunLog e eventos de falha/conclusão.

Extraí o workflow para `pipeline_finalize.run_finalize`. A fronteira recebe o
slug, o áudio, a configuração local e `VideoPaths` já resolvido; usa os owners
de `project_artifacts`, `audio.composition`, render, transcrição e metadata.
`pipeline.finalize_project` permanece a API externa e agora só resolve o
projeto, abre o log, delega e fecha eventos. Removi `_finalize_project` e um
wrapper legado sem consumidores que a extração havia copiado. Também movi a
resolução da fonte de título para `pipeline_render` e a projeção de tipografia
para `pipeline_metadata`; os testes importam esses módulos diretamente.

`pipeline.py` caiu de 1.054 para 739 linhas; `pipeline_finalize.py` concentra
275 linhas do workflow humano. Na primeira suíte integral, dois testes ainda
dependiam de aliases privados de pesquisa/subtitle no pipeline; foram
migrados para `pipeline_research`, `stages.subs` e `stages.render`. Depois da
migração, **892 testes passaram em 173,98 s**. Após remover o wrapper morto,
25 testes focados de finalização, TTS e isolamento passaram em 150,41 s;
compileall e diff check passaram. Código em `bbd06b3`.

Rerender/finalize preserva o contrato de CLI/TUI e usa os mesmos arquivos em
disco. A coordenação da geração IA/humana e o workflow visual extenso continuam
no pipeline; separar finalize não conclui a simplificação do coordenador.

## G11: regras de roteiro fornecido saem da aquisição de mídia

`stages/visual.py` ainda era importado por CLI e `pipeline_scenes` para ler
roteiro de arquivo/stdin, calcular contagem de cenas por pacing e garantir que
a divisão preservasse literalmente a narração. Essas decisões são do modo de
entrada de roteiro; misturá-las à aquisição fazia esse módulo participar de
um caminho sem relação com providers ou seleção.

Extraí as três operações para `stages/script_input.py`. CLI e `pipeline_scenes`
consomem o novo owner, e os testes de pacing importam esse contrato. Removi as
implementações de `visual.py` e atualizei a referência documental em
`scenes.py`. A leitura continua removendo BOM e espaços nas bordas, e a
validação mantém a normalização histórica de comparação.

91 testes focados passaram; a suíte integral passou com **892 testes em
195,33 s**, compileall e diff check aprovados. Código em `39a36d8`. `visual.py`
caiu de 1.290 para 1.238 linhas; ainda conserva a aquisição e uma função de
construção de timeline visual, que foi avaliada na fase seguinte sem
misturar decisões de aquisição com geometria temporal.

## G12: timeline visual passa a ter o módulo dono

`stages/visual.py` ainda implementava `build_visual_timeline`, embora essa
função organize beats, distribua imagens, trate inserções e atribua SFX —
responsabilidade de timeline. Ela dependia de helpers já pertencentes a
`visual_timeline.py`; o módulo temporal, por sua vez, importava `visual.py`
dinamicamente para o rerender, formando um ciclo conceitual e de import.

Movi o builder e sua validação de entrada para `stages/visual_timeline.py`.
`pipeline_timeline.py` agora chama o dono temporal diretamente; o rebuild usa
a função local, sem import tardio de aquisição. Testes de inserções, uso de
assets, review e pipeline foram migrados ao novo owner. Removi de `visual.py`
imports temporais que ficaram mortos.

64 testes focados passaram; a suíte integral passou com **892 testes em
178,13 s**, além de compileall e diff check. Código em `c238f02`. `visual.py`
caiu para 1.123 linhas e `visual_timeline.py` está com 386. Aquisição ainda é
um módulo grande, mas agora seu escopo exclui entrada de roteiro e geometria
temporal; a próxima análise deve mapear subresponsabilidades internas de
aquisição sem mover gates ou fallback por tamanho.

## G13: late reuse precisa atualizar a decisão tipada

`fetch_media_multi` já tenta o reuso por cena depois de buscas e fallback
sintético. Uma segunda passagem, `_resolve_reuse_multi`, pode preencher cenas
sem visual usando um asset de outra cena, inclusive quando só uma cena futura
tem um candidato adequado. Essa passagem alterava `asset`/`assets`, mas deixava
`visual_decision.selection` como `status="none"`; o boundary `MediaStageResult`
rejeitava a contradição (`empty selection decision has a selected asset`). A
passagem também copiava o conjunto inteiro do doador embora só um asset tivesse
evidência para a cena destino.

O late fallback agora copia somente o candidato validado e emite uma
`SelectionDecision` com status `reused`, identidade do mesmo asset, motivo e
nível `validated_reuse`. O fallback cross-scene permanece porque cobre donors
que só são encontrados em cenas posteriores; a validação semântica continua
obrigatória e não houve alteração de thresholds.

A regressão reproduz a saída contraditória e exige que `MediaStageResult` aceite
o resultado coerente, conte as cenas reais e registre donor/asset/status. 40
focados passaram; a suíte integral passou com **893 testes em 197,53 s**;
compileall e diff check passaram. Após limpeza de estilo, o teste novo também
passou sozinho. Código em `0c83ee8`. A política de reuse ainda tem dois
caminhos (seleção sequencial e late cross-scene); centralizar os dois sem
perder a descoberta de donors posteriores continua sendo dívida arquitetural.

## G14: o audit trail de candidatos não deve repetir campos

Uma varredura AST detectou cinco chaves repetidas no dicionário de candidato
de `visual.py`: provider, creator, source_url, date_created e media_type. Os
valores eram idênticos e o Python ocultava a duplicação ao manter só o último;
isso dificultava revisar o schema da auditoria.

Removi as entradas repetidas. 55 testes de waterfall, funnel e diretor passaram;
compileall e diff check passaram. Uma checagem AST específica confirmou que
`visual.py` não possui mais chaves literais repetidas. Código em `71058e2`.

## G15: ordenação do doador de reuso tem owner de seleção

O late cross-scene reuse ainda calculava evidência e ordenava doadores dentro
de `visual.py`. A avaliação semântica permanece no scorer; movi a regra de
ordenação para `media_selection.select_reuse_candidate`, com `ReuseCandidate`
tipado carregando doador, asset e relevâncias já avaliadas. A política
preservada prioriza relevância da cena, depois proximidade e, em empate,
preferência pelo doador anterior. `visual.py` segue responsável por coordenar
a busca tardia e materializar a decisão tipada, incluindo evidência e
proveniência.

O teste de seleção cobre a precedência por relevância, distância e desempate.
84 testes focados passaram; a suíte integral passou com **894 testes em
195,03 s**, além de compileall e diff check. Código em `e7f5b08`. Isso
centraliza uma decisão de política, mas não consolida ainda a seleção
sequencial e o late reuse em um único workflow; aquisição/fallback continuam
coordenados em `visual.py`.

## G16: projeção de auditoria dos candidatos sai da aquisição

`_search_scene_with_shortcircuit` montava linhas de auditoria de candidatos
junto da busca, download e escolha. Extraí a projeção pura para
`visual_audit.candidate_audit_rows`: recebe avaliações, rejeições, seleção,
níveis de representação e threshold já decididos, e apenas serializa a razão
observável. Não chama scoring nem modifica candidatos/seleção. A montagem do
relatório completo por cena continua na coordenação de `visual.py`, que ainda
agrega resultados de provider e estado de fallback.

Dois testes cobrem seleção/reuso, rejeição semântica, threshold e eliminação
de linha duplicada. 59 testes focados passaram; a suíte integral passou com
**896 testes em 176,37 s**; compileall e diff check passaram. Código em
`155e6af`. O módulo visual ficou 51 linhas menor, mas permanece um coordenador
grande; esta extração é uma fronteira de responsabilidade, não uma conclusão
da migração da aquisição.

## G17: política de ordem dos providers sai da aquisição

`visual.py` calculava a prioridade por cena, consultando o adapter de gênero e
interpretando flags de `VisualPlan` antes de chamar os providers. A regra foi
movida para `media_provider_policy.ordered_providers`, que recebe um plano já
construído, lê as preferências declarativas de gênero e apenas ordena os
adapters disponíveis. Pesquisa e avaliação continuam fora dessa política; a
ordem observada para história, espaço, mecanismo e demais cenas foi preservada.

Os testes de museus e providers agora usam o módulo dono e continuam cobrindo
prioridade histórica, prioridade-base e Unsplash ao final. 73 testes focados
passaram; a suíte integral passou com **896 testes em 175,70 s**; compileall e
diff check passaram. Código em `4fc4bf3`.

## G18: preparação para narração humana sai do coordenador

`pipeline._human_prep` concentrava a timeline estimada, composição de eventos
de áudio, persistência de fontes, render silencioso, teleprompter e metadata.
Extraí o workflow completo para `pipeline_human_prep.prepare_human_project`.
`pipeline.py` mantém a decisão de encaminhar a narração humana e passa os
resultados explícitos das etapas anteriores; o novo módulo consome os owners
de timeline, áudio, render e metadata. A assinatura funcional e os artefatos
persistidos foram preservados. A extração expôs uma dependência implícita do
seletor de áudio no coordenador; ela foi declarada no módulo novo e os testes
humanos voltaram a passar.

Os testes de integração de human prep/finalize, timeline, TUI e standby
passaram após corrigir essa dependência; a suíte integral passou com **896
testes em 177,84 s**. Compileall, diff check e varredura de imports sem uso
passaram. Código em `4b3bb27`; `pipeline.py` foi reduzido em cerca de 150
linhas. Ainda coordena a geração assistida principal.

## G19: tópico descritivo não pode virar entidade truncada

A primeira execução local de ciência (`Buracos negros: sombras e ondas`)
mostrou que a heurística de entidade promovia a primeira palavra em maiúscula
do título (`Buracos`) a entidade própria. Esse alvo truncado foi copiado pelo
planner local e pelo enrichment para o contexto das cenas; a query resultante
misturou `black hole` com `Buracos` e chegou a selecionar uma estação ferroviária
com esse nome. A origem foi `entity.resolve_entity_heuristic`, não o provider.

A heurística agora preserva como tópico descritivo frases de título com mais de
uma palavra, em vez de inventar entidade pelo primeiro token. A proveniência
continua marcada como tópico, e o planner local, enrichment, VisualPlan e
SearchPlan recebem o mesmo alvo. Regressões cobrem o título e a cadeia até a
query, incluindo a ausência da âncora isolada. 45 testes focados passaram.
Código em `99d51b1`.

## G20: busca não pode declarar alternativa nova antes de confirmar identidade

A geração v2 corrigiu o tópico, mas revelou outro erro real: candidatos eram
marcados como novos pela URL/ID do provider; após download, SHA-256 mostrava que
eram bytes já usados. A busca então rejeitava o duplicado sem retomar as outras
representações. `visual.py` agora associa a identidade provisória à identidade
de conteúdo quando baixa ou deduplica, e, em cenas posteriores, percorre a
árvore específica de queries antes de concluir que não existe alternativa.
Isso preserva a deduplicação por conteúdo e mantém reuso como último recurso.

A regressão reproduz o mesmo conteúdo sob ID/URL diferentes, exige tentativa da
representação alternativa e seleciona seu asset único. 67 testes focados e a
suíte integral de **900 testes em 199,29 s** passaram; compileall e diff check
passaram. Código em `2de90ae`.

Geração real local, sem credenciais LLM, confirmou a correção de identidade e
expôs limite de cobertura/custo: Otomanos v1 teve 8 cenas, 6 ocorrências reais,
6 assets únicos, zero reuso e 4 sintéticas (mídia 121,90 s; total 185,04 s).
Buracos negros v1/v2/v3 tiveram 6 cenas. V1 carregou o alvo errado `Buracos`;
v2 corrigiu o alvo mas encerrava buscas cedo; v3 buscou 40 queries lógicas e
80 requests (NASA 27, Wikimedia 47), com 6 assets reais únicos em 2 cenas, 4
sintéticas e zero reuso. Duas cenas esgotaram as queries; outras duas acabaram
com busca incompleta por erro de provider. A inspeção visual confirmou imagens
de Sagittarius A* e M87 nas duas cenas reais. Tempo v3: mídia 129,04 s, total
171,87 s. Wikimedia registrou 20 retries e 4 timeouts; soma de tempos por
provider excede o tempo de parede, então não representa duração serial. A
busca mais completa ficou correta quanto às tentativas, mas não aumentou a
cobertura real; ainda não está aprovada como resultado final de mídia.

A execução mostrou que `consumption.media.selected_unique` não era contagem de
assets finais: o mesmo conjunto era preenchido na shortlist de download e na
projeção de assets das cenas. Isso explicava 12 contra 6. G21 abaixo separa os
contadores e mantém o nome antigo como alias temporário; a contagem canônica de
assets reais finais é a mesma de `visual_report.unique_assets`. `media.json`
ainda expõe auditoria detalhada dentro de `metadata.json`, não como arquivo
separado.

Rerender de cópia isolada do projeto `black-hole-lensing`, com providers
desligados, reutilizou narração/roteiro/legendas persistidos e gerou novo MP4
sem nova pesquisa. As falhas reais de provider foram observadas no v3; a
execução foi sem LLM e usou Wikimedia/NASA gratuitos.

## G21: shortlist não é seleção final

`metrics.media_selected_ids` era preenchido duas vezes: primeiro no shortlist
de candidatos que seguiriam para download e depois ao percorrer assets finais
atribuídos às cenas. A métrica `consumption.media.selected_unique` misturava
esses escopos, e a métrica de timeline tinha ainda outro escopo (assets reais e
sintéticos que chegaram aos beats). A saída agora nomeia o contador inicial
`shortlist_assets_unique`, mantém `selected_unique` como alias de compatibilidade
e publica `real_scene_assets_unique` e `real_scene_asset_occurrences` usando o
contrato canônico de `MediaSelectionStats`/`visual_report`. O caminho de geração
não altera decisões editoriais.

Teste reproduz shortlist com duas identidades e uma seleção real final. 23
testes de métricas/funnel/uso passaram; suíte integral: **901 testes em
188,67 s**; compileall e diff check passaram. Alteração segue no commit de
documentação/código da fase G21.
