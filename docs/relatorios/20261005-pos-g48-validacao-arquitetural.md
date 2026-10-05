# Validação arquitetural após G48 — 2026-10-05

Esta rodada verifica os contratos novos com a suíte integral e reabre projetos
reais já adquiridos. Rerender foi escolhido para testar o caminho atual sem
refazer pesquisa, gastar chamadas de LLM ou confundir cache de bytes com nova
seleção editorial.

## Testes e contratos

Após G48, `pytest -q` passou com **904 testes em 187,69 s**. Também passaram
`compileall` e `git diff --check`. Os focados de scene contract, planner LLM e
local, projection e enrichment foram 80/80. G39–G48 mantiveram a suíte entre
903 e 904 testes verdes.

## Projetos reais e rerender atual

| Projeto | Cenas | Cenas com asset real | IDs reais selecionados | Reuso | Sintéticas | Busca original | Rerender atual |
|---|---:|---:|---:|---:|---:|---:|---:|
| `battle-mohacs` | 3 | 1 | 2 | 0 | 2 | 35,99 s | 26,27 s |
| `black-hole-lensing` | 3 | 2 | 4 | 0 | 1 | 40,24 s | 21,13 s |
| `20261004-refactor-black-hole-rerender` | 3 | 3 | 3 | 0 | 0 | 8,40 s na geração registrada | 27,50 s |

Os rerenders atuais mantiveram narração, roteiro e legendas do cache; não houve
nova pesquisa, busca visual ou TTS. O número de IDs conta assets de provider
selecionados, inclusive complementares na mesma cena, e não mede cobertura de
cenas nem pertinência editorial. Para `battle-mohacs`, a cena 1 tem dois IDs
reais, mas as outras duas cenas ficaram sintéticas. Para `black-hole-lensing`,
a cena 1 tem três assets e a cena 3 um; a cena 2 ficou sintética.

A amostra otomana anterior, `20261004-refactor-ottoman`, não tem
`narration.wav` por ter sido criada como preparação para voz humana; o comando
de rerender corretamente pediu `generate` quando esse artefato obrigatório
faltou. A validação foi repetida com o projeto Mohács, que possui áudio salvo.

## Providers, queries e proveniência

`battle-mohacs` planejou 24 consultas (oito por cena), com seis adapters
registrados: AIC, Met, NASA, Pixabay, Unsplash e Wikimedia. Pexels não estava
habilitado por credencial. O relatório existente registra 27 candidatos, 25
rejeições por ausência de evidência de tópico, uma por termo bloqueado e quatro
consultas abandonadas como duplicatas. A cena 1 selecionou Pixabay 1440679 e
6995487. Ambos foram retornados sob consulta de Hungria/Danúbio e ambos têm
como assunto visual o Parlamento de Budapeste; a representação ligada à cena
foi `Hungria exército 1526 planície Danúbio`. A escolha ganhou score 100 apesar
de não mostrar a batalha. A cena 2 (“Luís II”, 7 consultas) e a cena 3
(“Império Otomano”, 8 consultas) usaram cards sintéticos após falhas de
provider e ausência de candidato novo elegível. Este caso segue sendo uma
regressão editorial aberta: evidência territorial não pode substituir
identidade de evento histórico.

`black-hole-lensing` planejou 24 queries, com seis adapters consultados e
Pexels indisponível por credencial. A cena 1 escolheu o registro Wikimedia
146835069, imagem polarizada de Sagitário A* (score 100), e dois visuais
Pixabay distintos. A cena 2 ficou sintética depois de oito queries para logo e
rede do Event Horizon Telescope. A cena 3 escolheu uma imagem Hubble de campo
profundo (NASA, score 52,25) para a representação de lente gravitacional; ela
não mostra a lente em questão. O uso de mídia é novo e não repetido, mas a
precisão da cena 3 é fraca. O perfil mediu 12,63 s em research e 40,24 s em
mídia; o relatório de geração anterior detalha as 17 queries lógicas e 102
chamadas de adapter dessa execução.

`20261004-refactor-black-hole-rerender` tem três assets distintos selecionados
para três cenas: impressão artística de NGC 300 X-1, uma visualização artística
de buraco negro na Via Láctea e a imagem do EHT de M87. Foram inspecionados os
arquivos locais; todos têm assunto coerente e o terceiro é a observação
específica de M87. O rerender atual terminou em 27,50 s sem refazer os assets.

## Inspeção visual

A folha de revisão visual temporária foi montada com os sete arquivos do
projeto científico de três imagens e da seleção `black-hole-lensing`, mais os
dois vencedores de Mohács. Os arquivos Mohács mostram o Parlamento Húngaro
moderno, não batalha, exército nem cena de 1526. Os dois arquivos Pixabay de
`black-hole-lensing` têm pixels diferentes, mas repetem o mesmo motivo de
esfera/halo luminoso; são metáforas genéricas e não evidência observacional. A
imagem NASA é um campo profundo de galáxias, não lente gravitacional. No replay
científico com M87, os três visuais são distintos e pertinentes ao tema; o
último é a imagem EHT nomeada para Messier 87.

## Resultado arquitetural

A suíte e os rerenders mostram que as novas fronteiras não quebraram seleção
persistida nem render: projection, resultado único de enrichment, entrada/saída
tipadas de render, metadata assistida e standby são compatíveis com projetos
reais salvos. A revisão de imagem também impede uma conclusão precipitada: não
houve reuso nestes vídeos, porém o gate histórico ainda aceita evidência fraca
de localização/evento e a busca pode terminar sintética diante de erro de
provider. Este relatório não declara aquisição histórica resolvida nem usa o
rerender como se fosse uma nova busca.
