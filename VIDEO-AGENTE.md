# Produzir um vídeo com o agente

Este arquivo é o ponto de entrada para qualquer agente que opere o Curio. Use o fluxo `agent-flow`, com arquivos JSON e CLI, sem depender de um fornecedor de agente.

## 1. Atalho e início da conversa

O usuário pode iniciar este fluxo dizendo **“Curio pronto”**, sem precisar pedir que você leia este arquivo. Leia este guia e as instruções do repositório.

- Se disser apenas “Curio pronto”, **não inicie uma produção ainda**. Responda apenas:

> Pronto. Envie o tema e, se quiser, a duração. Exemplo: “Aristóteles e sua filosofia, 60s”. Sem duração, uso automático de até 60 segundos.

- Se disser “Curio pronto” junto com um tema, como “Curio pronto: Aristóteles e sua filosofia, 60s”, comece a produção nessa mesma mensagem, sem pedir o tema novamente. Sem duração, use automático, com teto de 60 segundos.

O mesmo fluxo também vale quando o usuário pedir explicitamente para ler este arquivo. Não peça ao usuário para abrir outro terminal, criar JSON, escolher imagens ou executar comandos, se você já tem ferramentas para fazer isso neste projeto.

Se não tiver acesso ao terminal ou aos arquivos do projeto, explique essa limitação. Ler este arquivo não conecta um chat ao terminal nem instala ferramentas.

## 2. Reconhecer o pedido

Interprete a próxima mensagem como o pedido do vídeo:

- `Aristóteles e sua filosofia, 60s`: tema “Aristóteles e sua filosofia”; meta de 60 segundos.
- `Aristóteles e sua filosofia`: mesmo tema; duração automática.
- `Aristóteles e sua filosofia, automático` ou `..., auto`: duração automática.

Aceite duração em segundos no fim da mensagem, separada por vírgula ou espaço, como `60s`. Converta `60s` para `60` ao executar comandos. Um número sem unidade só é duração se estiver explicitamente separado do tema por vírgula. Não remova datas ou números que façam parte do assunto.

Curio aceita metas numéricas entre **5 e 600 segundos**, mas o padrão editorial de todo vídeo é **no máximo 60 segundos reais**. Só ultrapasse 60 segundos quando o usuário pedir expressamente uma duração maior. Use `auto` para duração automática, também limitada a 60 segundos. Se a duração for inválida, peça somente essa correção; não altere a meta silenciosamente.

A duração é uma meta editorial. Planeje o roteiro e as cenas para ela; confira o tempo real depois da narração. Não corte frases nem estique imagens para fingir que atingiu a duração. No modo automático, escolha a menor duração que explique bem a descoberta, respeitando o teto de 60 segundos. Se o áudio ultrapassar o teto, enxugue o roteiro e gere novamente a narração; não acelere a voz nem corte frases para fazê-lo caber. Inclua a ponte do loop no tempo total.

O idioma padrão é português; respeite outro idioma solicitado explicitamente. Infira o perfil editorial pela intenção do conteúdo, sem tabela de palavras por tema. Perfis disponíveis estão em `src/curio/stages/editorial.py`: `history`, `etymology`, `mythology`, `mystery`, `science` e `people`. Escolha o mais adequado ou deixe o gênero vazio quando nenhum servir. Não transforme um pedido sobre filosofia em uma biografia inteira apenas porque escolheu `people`.

Depois de receber um pedido válido, conduza a produção. Não peça confirmação para cada etapa. Pergunte apenas quando faltar informação indispensável ou quando uma autorização realmente for necessária.

## 3. Preparar o projeto

Execute comandos na raiz do repositório. Use `./scripts/run.sh`, que dispensa instalar o comando `video-gen`. Confira as dependências se necessário:

```sh
./scripts/run.sh doctor
```

Escolha um slug legível e novo, por exemplo `20261009-aristoteles-filosofia`. Verifique que ele não identifica um projeto existente. Só reutilize um projeto se o usuário pedir continuação.

Inicialize o contrato. Exemplo para o pedido de 60 segundos:

```sh
CURIO_DURATION=60 ./scripts/run.sh --out-dir output agent-flow init \
  --slug 20261009-aristoteles-filosofia \
  --topic "Aristóteles e sua filosofia" --genre people
```

Para duração automática, use `CURIO_DURATION=auto`. Substitua tema, slug e gênero pelo pedido atual. Sem perfil editorial, omita `--genre`.

**Repita o prefixo `CURIO_DURATION=60` ou `CURIO_DURATION=auto` em todos os comandos do projeto.** Ferramentas de terminal podem abrir um processo novo a cada chamada; não dependa de um `export` feito em uma chamada anterior. `agent-flow` não tem opção CLI `--duration`.

O comando imprime o caminho do contrato em `output/projetos/<slug>/agent_flow/`. O gênero escolhido afeta o perfil editorial, nunca a organização das pastas.

Leia o `AGENT.md` e o `request.json` dessa pasta. Leia também [o contrato completo](docs/agent-flow.md) antes de preencher os arquivos. Registre o pedido e a duração em `agent_flow/brief.json` para continuidade entre sessões, por exemplo:

```json
{
  "request": "Aristóteles e sua filosofia, 60s",
  "topic": "Aristóteles e sua filosofia",
  "duration_target": 60,
  "genre": "people"
}
```

Em automático, registre `duration_target: 0`. Esse arquivo é uma nota para o agente; **Curio recebe a duração por `CURIO_DURATION`**, não por `brief.json`.

## 4. Conduzir a produção

O usuário fornece o tema. Você pesquisa, preenche arquivos e executa comandos. Use as fontes e ferramentas disponíveis, sem acionar os provedores LLM internos para tomar decisões editoriais neste fluxo.

### Planejamento

Todo vídeo deve entregar uma conclusão concreta que responda à curiosidade e retome o título antes da pergunta final. Conecte os fatos em uma explicação e diga explicitamente o que o espectador aprendeu; uma sequência de curiosidades isoladas não basta. Sempre inclua uma síntese e, quando ajudar a compreensão, mostre-a na tela. Em comparações, números e contas, mantenha os valores relevantes juntos, com rótulos e unidades, e exiba a relação ou operação e sua consequência em um único quadro legível. Prefira dados aproximados quando as fontes assim os tratam. Nos vídeos sobre santos, ligue as ações ao ensinamento e a uma aplicação cotidiana, distinguindo síntese editorial de citação literal.

Use somente a marca d’água “palavras_mortas.oficial”, discreta mas legível, em área segura e sem competir com a imagem ou as legendas. Não exiba a marca “CURIO” nem rótulos fixos extras na parte inferior, como repetição do nome do santo ou identificação genérica da origem das imagens. Mantenha o título de abertura, as legendas sincronizadas e as sínteses visuais que ajudam a compreender o conteúdo. Registre atribuições de fontes e licenças no documento de créditos.

Planeje todo vídeo como um loop imperceptível, criando abertura e encerramento juntos. Depois da pergunta final e do convite natural para compartilhar, escreva uma ponte curta cuja continuação seja o próprio título narrado ao reiniciar. Não repita o título no final. Faça a imagem e o movimento finais desembocarem no início; ajuste trilha, efeitos sonoros e legendas para atravessar essa passagem sem quebra perceptível. Evite tela de encerramento, silêncio e fade de saída. Preserve a ponte dentro da duração total.

Busque o vídeo mais direto possível: cada frase e cada cena precisam avançar a descoberta. Use imagens reais pertinentes e variadas, cortes e movimentos ligados ao que está sendo dito e efeitos sonoros sincronizados com momentos de descoberta e mudanças visuais. Preserve a inteligibilidade da voz e o ducking; som e imagem devem prender a atenção sem criar afirmações que as fontes não sustentam.

Planeje os primeiros 3 segundos como o momento de maior impacto: título curto e memorável, dito literalmente como a primeira frase da narração e exibido sobre uma imagem real pertinente. Prefira 3 a 7 palavras e no máximo 55 caracteres. O título pode ser afirmação ou pergunta, sempre fiel às fontes. Mantenha atenção ao longo do vídeo com novas descobertas, frases ágeis e exemplos concretos. Na revisão, confira no áudio a duração da primeira fala e o destaque de cada palavra; não aceite introdução antes do título nem um título diferente da abertura narrada.

Escreva para quem está rolando o feed, tem curiosidade e não conhece o assunto. Comece com uma situação concreta e interessante; explique uma ideia por vez com palavras simples e exemplos familiares. Evite jargões, tom de aula e referências que pressuponham conhecimento prévio. Toda a linguagem deve ser compreensível e interessante para quem conhece o assunto e para quem nunca ouviu falar dele. Use primeiro a palavra ou explicação em português comum. Termos técnicos, religiosos ou em outro idioma só entram quando necessários à precisão ou como complemento útil, sempre explicados na primeira menção; nunca substituem a explicação acessível. Por exemplo, diga “fala das virtudes (areté, em grego)”, quando essa equivalência for sustentada pela fonte e pertinente ao contexto; não diga apenas “fala do areté”. Na narração, torne esse complemento natural: “fala das virtudes, chamadas de areté em grego”. Preserve causas, limites, incertezas e distinções sustentados pelas fontes: simplifique a explicação, não o conteúdo. Mantenha a qualidade e o formato audiovisual atuais, incluindo imagens reais pertinentes e variadas, legendas, narração, trilha e ducking, gancho inicial e pergunta com convite para compartilhar no encerramento, seguidos da ponte para o loop.

As regras de linguagem acessível, termos como complemento e gancho forte nos primeiros 3 segundos valem para todos os vídeos, inclusive sobre santos. Nos vídeos sobre santos, mantenha sempre um tom respeitoso e reverente, sem brincadeiras, memes, efeitos cômicos ou montagem espalhafatosa. Refira-se à pessoa com o tratamento religioso adequado (“São”, “Santo” ou “Santa”) em todas as menções pelo nome, incluindo título, narração e legendas. Use trilha sóbria, movimentos suaves e efeitos discretos que favoreçam a contemplação e a compreensão. Nos demais vídeos, intensifique os efeitos visuais e sonoros pertinentes e o ritmo dos cortes para sustentar a atenção, preservando clareza, precisão e inteligibilidade.

Quando o tema for um santo ou uma santa, concentre o vídeo na vida, nas escolhas, nas ações e nos ensinamentos dessa pessoa, com exemplos concretos que mostrem por que isso pode importar na vida cotidiana. Escolha o gancho mais forte dentro desse foco. Curiosidades secundárias só entram se ajudarem a entender essa trajetória ou seus ensinamentos; não desloque o assunto para detalhes periféricos apenas por serem incomuns. Apresente os termos religiosos em linguagem acessível e preserve a distinção entre fatos históricos, tradição e relatos de fé conforme as fontes.

Preencha `agent_flow/plan.json` com pesquisa verificável, título, roteiro, cenas e intenção musical. Preserve o foco do pedido. Cada fonte precisa de título, URL e trecho de evidência. As narrações das cenas devem reproduzir o roteiro inteiro, sem alterações. Abra com um gancho concreto e surpreendente, sustentado pelas fontes, que entregue a descoberta, consequência ou imagem mais intrigante do assunto. Para Eratóstenes, por exemplo, prefira “O homem que calculou o tamanho da Terra usando a sombra do Sol” a uma abertura cronológica como “Ele era um grego que viveu há 2.000 anos”. Não abra com saudação, definição escolar ou contexto biográfico genérico. No encerramento, inclua uma pergunta curta que conecte o tema à vida cotidiana e faça o público pensar em algo que talvez nunca tenha percebido; em seguida, inclua um convite natural para compartilhar com alguém que se interessaria pelo assunto. Coloque pergunta e convite na narração da última cena e nas legendas finais, antes da ponte para a abertura. Adapte a formulação a cada conteúdo: não use CTA genérico nem invente fatos para criar impacto.

Declare entidades, aliases, traduções e representações com base nas fontes. Planeje imagens reais pertinentes e variadas. Diferencie fotografia de lugar, retrato e representação artística de um evento; não apresente uma pintura posterior como registro documental do evento narrado.

Escolha uma trilha instrumental local com fonte, licença compatível e intenção ligada à narrativa, ritmo e emoção. Pesquise e baixe uma alternativa quando necessário, reaproveitando o acervo local quando adequado. Caso silêncio seja a escolha editorial, justifique. Preserve configurações existentes de voz, ganho e ducking.

Depois de preencher o plano:

```sh
CURIO_DURATION=60 ./scripts/run.sh --out-dir output agent-flow advance \
  --slug 20261009-aristoteles-filosofia
```

### Curadoria das imagens

Em `awaiting_media`, inspecione as imagens em `media_review/scene_NN/` e os manifests. Preencha `media-feedback.json` com exatamente um arquivo por cena, justificativa semântica e evidência dos direitos. Procure alternativas reais se os candidatos não servirem. Não escolha só pelo score ou pelo nome do arquivo.

Use `filename: null` e `fallback_reason` explícito apenas após esgotar alternativas pertinentes. Não aprove uma sequência de cartões por conveniência. Os candidatos não escolhidos são arquivados.

Execute `advance` novamente. Curio seleciona os arquivos locais, gera ou reaproveita narração e renderiza. Para usar CPU, a opção global vem antes de `agent-flow`:

```sh
CURIO_DURATION=60 ./scripts/run.sh --out-dir output --backend cpu \
  agent-flow advance --slug 20261009-aristoteles-filosofia
```

### Revisão do render

Em `awaiting_render_review`, leia o novo `request.json`. Inspecione o vídeo, os frames por cena, as legendas e o áudio com as ferramentas disponíveis. Confira duração real (máximo de 60 segundos, salvo pedido expresso de duração maior), fidelidade ao tema, precisão factual, imagens, variedade, enquadramento, ritmo, música, efeitos sonoros e direitos. Confira o impacto do gancho e do título nos primeiros 3 segundos. Verifique se há uma conclusão que resolve o título e uma síntese compreensível; em contas e comparações, confira valores, unidades e consequência juntos na tela. Confira a marca “palavras_mortas.oficial” e a ausência de rótulos fixos extras. Reproduza também o fim seguido imediatamente do início: verifique a continuidade da fala, imagem, movimento, legendas, trilha e efeitos, depois da pergunta e do convite. Registre evidências dessa passagem; revise qualquer quebra que revele o reinício. Nos critérios `factual_accuracy` e `pacing`, registre evidências de linguagem acessível para quem não conhece o assunto: abertura concreta, uma ideia por vez, exemplos familiares e termos indispensáveis explicados na primeira menção, sempre como complemento da linguagem comum. Para temas sobre santos, confira se a vida, as ações e os ensinamentos conduzem o roteiro e o gancho, e se curiosidades secundárias realmente ajudam a compreender esse foco. Reescreva os trechos que soem como aula ou exijam conhecimento prévio; preserve causas, limites e incertezas das fontes.

Preencha `feedback.json`, preservando `render_id`. Registre evidências específicas e problemas reais. Nunca declare que assistiu ou ouviu algo que não conseguiu inspecionar. Se faltar uma ferramenta indispensável à revisão, mantenha o critério pendente e informe a limitação.

- Para aprovar: todos os critérios e cenas precisam de `ok: true` e evidência; `issues` deve estar vazio; verificações técnicas precisam passar.
- Para rejeitar: use `decision: revise`, identifique o revisor e registre os problemas em `issues`.

Execute `advance` para registrar essa avaliação. Renderizar sem erros não equivale a aprovação editorial.

### Corrigir e voltar à revisão

Se o estado for `needs_revision`, corrija a mídia e use:

```sh
CURIO_DURATION=60 ./scripts/run.sh --out-dir output agent-flow revise \
  --slug 20261009-aristoteles-filosofia
CURIO_DURATION=60 ./scripts/run.sh --out-dir output agent-flow advance \
  --slug 20261009-aristoteles-filosofia
```

Para mudar pesquisa, título, roteiro, cenas ou trilha depois da importação, edite `plan.json` e execute `replan`, seguido de `advance`. Se tema, título, fontes e semântica visual das cenas continuarem iguais, Curio reaproveita as imagens revisadas e segmentos de vídeo; atualiza narração, legendas e render sem repetir a busca. Se esses elementos mudarem, o fluxo completo de curadoria continua disponível. Use `replan` também para ajustar o roteiro à duração solicitada.

```sh
CURIO_DURATION=60 ./scripts/run.sh --out-dir output agent-flow replan \
  --slug 20261009-aristoteles-filosofia
CURIO_DURATION=60 ./scripts/run.sh --out-dir output agent-flow advance \
  --slug 20261009-aristoteles-filosofia
```

Cada novo render exige nova revisão. Continue corrigindo até obter aprovação fundamentada ou encontrar um bloqueio que dependa do usuário. Não rode `advance` em loop sem cumprir a tarefa de `request.json`.

## 5. Pausas, retomada e entrega

Códigos de saída:

- **3:** etapa editorial pendente. Leia `request.json` e trabalhe; não é falha fatal.
- **1:** erro ou contrato inválido. Corrija antes de avançar.
- **0:** aprovação válida no fluxo `agent-flow`.

Para retomar, leia `brief.json`, `state.json` e `request.json`, mantenha a mesma duração e consulte:

```sh
CURIO_DURATION=60 ./scripts/run.sh --out-dir output agent-flow status \
  --slug 20261009-aristoteles-filosofia
```

Não reinicie buscas ou gere outro projeto para uma continuação. Alterar arquivos após aprovação invalida a revisão; confira `status` antes de entregar.

Ao concluir, entregue uma resposta curta com caminho do MP4, duração real, quantidade de imagens reais e fallbacks, estado da revisão e limitações relevantes. Não publique nem envie o vídeo a terceiros sem autorização. Se estiver pendente, diga isso claramente; não declare sucesso editorial apenas porque existe um MP4.
