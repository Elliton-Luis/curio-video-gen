# G79 — separação de tópico/título e validação real pós-G78

**Data:** 2026-10-05  
**Commit de implementação:** `58f0aea refactor: separate script topic from display title`  
**Estado:** contrato migrado no caminho `from-script`; validação real concluída
para ciência e história, com limitações de provider descritas abaixo.

## Causa confirmada

`run_script_pipeline()` encaminhava o título de exibição como `idea` de
`run_pipeline()`. O pipeline tratava esse único texto como entrada da pesquisa,
contexto semântico das cenas, argumento do slug e título. Na execução de
controle, `--title "Buracos negros — validação G78"` levou o resolver local a
produzir `TargetEntity("Buracos")`: o sufixo editorial interferiu na resolução
do assunto. O contexto visual herdou `Buracos`, as queries terminaram em
`... Buracos` e dois candidatos científicos foram rejeitados por não ancorarem
nesse rótulo.

O problema não estava no planner de mídia. A causa era a entrada `idea` com
mais de um significado. O mesmo acoplamento existia em qualquer título fornecido
que não fosse uma expressão adequada para pesquisa.

## Mudança arquitetural

O comando `from-script` agora aceita `--topic` para o assunto usado na pesquisa
e no contexto das cenas, mantendo `--title` como título editorial. Esse fluxo
passa o tópico para `run_pipeline(idea=...)` e o título para
`run_script_stage(provided_title=...)`, que grava um `TitleArtifact` com origem
`provided`. Sem `--topic`, o título continua sendo usado como assunto, mantendo
compatibilidade com chamadas e comandos existentes.

Não foi criado um novo dataclass nesta fase: a fronteira pública nomeia os dois
valores separadamente, e os contratos já existentes `ResearchResult`,
`SemanticScene` e `TitleArtifact` recebem cada valor no campo correto. Uma
estrutura de request só será necessária se surgirem mais campos com lifecycle
compartilhado.

Arquivos alterados: `src/curio/cli.py`, `src/curio/pipeline.py`,
`src/curio/pipeline_script.py`, `tests/test_tui_script_input.py` e
`tests/test_pipeline_script_stage.py`. O CLI segue aceitando os argumentos
anteriores; `--topic` é opcional. Quando um título é explicitamente informado,
ele é preservado como título fornecido e não passa pela geração automática.

## Testes

- Regressão prova que tópico explícito chega tanto a `research_topic()` quanto
  ao planejamento de cenas.
- Compatibilidade prova que sem `--topic` o título continua sendo o assunto.
- O título explícito é persistido sem chamar o gerador de título.
- O parser CLI expõe `--topic` junto de `--title`.
- Testes focados de script, pesquisa, integração e metadata: **36 passaram**.
- Suíte ampla após a mudança: `pytest -q -k 'not test_standby_sem_imagens'` —
  **953 passaram, 1 desmarcado em 178,70 s**. O teste desmarcado acessa a API
  real da Wikipédia, que havia respondido HTTP 429 nos gates anteriores.
- `python -m compileall -q src tests` e `git diff --check` passaram.

## Validação real

As três gerações usaram `--narration human`, sem chaves de LLM e sem TTS; o
planner local de cenas produziu o mesmo contrato downstream. Providers de mídia
foram gratuitos. Os projetos foram gravados em `/tmp`, fora do repositório.

| Execução | Cenas | Assets reais | Únicos | Reusos | Sintéticos | Queries planejadas/executadas | Providers | Mídia |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| Otomano pós-G78, providers NASA/Met/AIC | 11 | 1 | 1 | 0 | 10 | 88/88 | NASA, Met, AIC | 52,69 s |
| Buracos negros pré-G79, controle do defeito | 3 | 3 | 3 | 0 | 0 | 24/24 | NASA, Wikimedia | 121,32 s |
| Buracos negros pós-G79, `--topic`, NASA | 3 | 0 | 0 | 0 | 3 | 24/24 | NASA | 4,98 s |

### História — Império Otomano

O roteiro tinha 11 cenas e cada cena executou 8 queries. Os âncoras específicos
foram: Anatólia; Dardanelos/Galípoli; Battle of Kosovo/Kosovo; Siege of
Constantinople/Mehmed Segundo; Mehmed Segundo/Constantinople; Selim Primeiro/Marj
Dabiq; Suleiman Magnífico/Mohács; janízaros; Battle of Preveza/Mediterrâneo;
Ottoman Empire; Primeira Guerra Mundial. As combinações preservaram
`Ottoman Empire` ou `Império Otomano`; variações incluíram painting, engraving,
artifact, portrait, army, uniform, cavalry, illustration, historical map ou
fresco conforme o tipo de representação. Todas as 88 queries foram iniciadas;
nenhuma foi deixada como `not_consulted`.

Met falhou com HTTP 410, HTTP 403 e HTTP 410/403 em tentativas diferentes; AIC
falhou com HTTP 500; NASA respondeu zero resultados na maioria das consultas.
O único asset real foi NASA `PIA02665`, “Istanbul, Turkey (Earth, Terra)”, para
a representação `constantinople`, score 92,25. A inspeção visual mostrou uma
imagem orbital moderna em falso colorido da região de Istambul: geograficamente
relacionada à cena da conquista de Constantinopla, mas fraca como representação
histórica do evento. As demais dez cenas ficaram sintéticas, sem reuso. Portanto
1/11 `asset_id` real não representa cobertura histórica adequada, e as falhas
de provider impedem concluir que a busca razoável não teria mídia.

### Ciência — controle anterior à separação

O título `Buracos negros — validação G78` virou o tópico `Buracos`. O sistema
executou oito queries por cena, totalizando 24, consultou NASA e Wikimedia,
recebeu 22 resultados contados na auditoria e marcou 5 duplicatas. Foram
registrados 15 candidatos elegíveis, 2 rejeições por mismatch de tópico, 21
retries HTTP 429 e quatro timeouts de Wikimedia. O funil adquiriu quatro
downloads e teve um cache hit; os vencedores foram três IDs únicos, sem reuso ou
sintéticos:

| Cena | Representation vencedora | Asset | Score | Inspeção |
|---|---|---|---:|---|
| 1 | `black hole` | Wikimedia `9551709`, impressão artística de NGC 300 X-1 | 100 | Ilustração direta de sistema com buraco negro e estrela companheira. |
| 2 | `black hole` | Wikimedia `370240`, “Black Hole Milkyway” | 100 | Visualização científica de lente gravitacional em torno de buraco negro. |
| 3 | `event horizon` | Wikimedia `77916527`, imagem M87 do Event Horizon Telescope | 95,25 | Imagem observacional direta de M87*, adequada ao trecho sobre o telescópio. |

As três imagens selecionadas são visualmente distintas e semanticamente
relacionadas às cenas. O run, contudo, **não prova a correção G77**: candidatos
específicos não falharam tecnicamente deixando slots vazios; portanto a tier
contextual após falha de aquisição não foi acionada.

### Ciência — validação do contrato G79

A execução usou `--title "Buracos negros — field notes G79"` e
`--topic "Buracos negros"`. O metadata persistiu `input=Buracos negros` e
`video_title=Buracos negros — field notes G79`; `sources/research.json` persistiu
`idea=Buracos negros` e `target=Buracos negros`. As cenas produziram oito
queries cada, com âncoras `black hole`, `gravity` e `event horizon`; todas as
24 foram executadas em NASA. O provider não retornou candidatos, então as três
cenas usaram visual sintético. A execução provou separação do tópico e título
no caminho real, mas não cobertura de mídia: NASA isoladamente não encontrou
assets e o run não foi renderizado com imagens reais.

## Limites e trabalho restante

- A camada `idea` ainda é string em partes do pipeline AI, TUI e queue; G79
  separa somente o caminho `from-script` com título fornecido. O contrato
  canônico global de assunto ainda precisa ser migrado entre todos os modos.
- A validação real pós-G78 não reproduziu a condição específica de G77. Falta
  um replay determinístico com candidato específico elegível cuja aquisição
  falha e candidato contextual posterior utilizável.
- A cobertura histórica continua inconclusiva porque Met/AIC falharam e NASA
  não encontrou assets históricos adequados. Reexecutar quando providers
  estiverem saudáveis.
- O run científico pré-G79 teve erros de rate limit, embora selecionasse três
  assets únicos. O run pós-G79 com NASA apenas teve 3/3 sintéticos. São sinais
  de saúde/cobertura distintos e não devem ser confundidos com correção dos
  contratos.
- As fases de métricas canônicas, lifecycle de cache, profile por componente,
  rerender, falha de provider/LLM e domínios pessoa/etimologia permanecem
  incompletas.
