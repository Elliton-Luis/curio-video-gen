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
