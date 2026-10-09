# Trilhas contextuais

Na geração automática, Curio planeja uma intenção musical a partir do título, roteiro, narrativa, ritmo e emoção. A intenção contém descrição, consulta de busca, termos de atmosfera e preferência instrumental. Não usa o rótulo do gênero como substituto da intenção do vídeo. Gêneros ainda organizam a biblioteca e os perfis existentes.

## Cache e funcionamento sem IA

A intenção fica no metadata do projeto, identificada pelo hash de título, roteiro e idioma. Se o conteúdo não muda, a intenção é reutilizada. Quando os provedores LLM não estão disponíveis ou falham, uma consulta local deriva do conteúdo e prioriza música instrumental. Esse fallback não oferece a mesma interpretação emocional de um agente ou modelo.

A seleção usa arquivos locais em `assets/library/music/<genre>/`, considerando tags, título, pertinência e contadores de uso. Assets menos usados são favorecidos entre candidatos empatados. Arquivos incompatíveis podem ser rejeitados; sem faixa adequada, o render continua sem música. Cache e contadores reduzem consultas e repetição, sem garantir variedade em um acervo pequeno.

## Consultas externas

Com autopreenchimento habilitado e biblioteca abaixo do mínimo, Curio consulta a API oficial do Freesound usando a intenção musical. `FREESOUND_API_KEY` é necessária para esse download. Atingir o mínimo desliga esse autopreenchimento durante geração, mas não impede uma chamada LLM para planejar intenção de conteúdo novo. Atualização explícita da biblioteca continua disponível:

```sh
./scripts/run.sh music update --genre people
./scripts/run.sh music list --genre people
```

Os downloads automáticos aceitam CC0 ou CC BY e preservam atribuição. A preferência instrumental orienta a busca; metadados não comprovam ausência de voz em toda a faixa. Confira a trilha antes de publicar.

## Controle existente

```sh
./scripts/run.sh generate "Tema" --music-mode none
./scripts/run.sh generate "Tema" --music-mode manual --music-file /caminho/faixa.mp3
```

Ganho, ducking, fades e transições continuam configuráveis. Arquivos manuais da geração comum mantêm licença não verificada, sob responsabilidade de quem fornece o arquivo.

No [agent-flow](agent-flow.md), o agente fornece intenção e escolhe arquivo instrumental local com fonte e licença livre reconhecida, ou justifica silêncio. Esse fluxo não usa planejamento musical pelo LLM interno. A trilha efetivamente usada e sua atribuição são registradas antes da revisão do render. Validação estrutural e hashes não substituem audição nem conferência dos direitos.
