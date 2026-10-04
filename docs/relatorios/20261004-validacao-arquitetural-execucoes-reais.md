# Validação real da migração arquitetural — 2026-10-04

Este relatório registra geração de produto, separada dos relatórios pytest. As
execuções foram feitas sem credenciais de LLM; os roteiros foram fornecidos ou
humanos, portanto validam o pipeline posterior ao roteiro, não a qualidade do
planner LLM. Saídas em `output/` e caches não são versionados.

## História: Império Otomano

Projeto `output/history/history/20261004-refactor-ottoman`, 11 cenas, `--narration human`,
1 imagem por cena e providers NASA, Met, AIC e Wikimedia.

| Medida | Resultado |
|---|---:|
| Assets reais atribuídos | 4 |
| Assets reais únicos (SHA-256) | 4 |
| Reusos | 0 |
| Cenas sintéticas | 7 |
| Queries planejadas / executadas | 88 / 67 |
| Candidatos recebidos / mantidos | 31 / 5 |
| Queries abandonadas por duplicatas | 3 |
| Duração da etapa de mídia | 361,77 s |
| Duração total | 507,92 s |

Os quatro vencedores únicos foram o mapa do Império Otomano de 1566 (contexto
geral da cena 1), o diagrama tático da Batalha do Kosovo (cena 3), o modelo do
cerco de Constantinopla (cena 4) e uma colagem sobre a guerra otomano-espanhola
(cena 9; relação naval ampla, evidência fraca para Preveza especificamente).
Inspeção visual confirmou pertinência contextual nos três primeiros; o quarto
foi marcado como fallback semântico amplo. As outras sete cenas terminaram
sintéticas, sem reuso de imagem genérica.

Foram executadas 67 consultas entre os quatro providers. Met respondeu HTTP
410 em 67 chamadas, AIC HTTP 500 em 67, Wikimedia teve 15 timeouts; NASA não
devolveu resultado elegível nas consultas registradas. O diagnóstico não tinha
`CURIO_CONTACT` configurado para Wikimedia. Assim, a taxa sintética não prova
inexistência de acervo: a execução esgotou as consultas planejadas, mas ficou
limitada por falhas/indisponibilidade de providers e representações locais
fracas. Tempo de mídia foi dominado por chamadas e retries de providers; esta
execução é o baseline observável, ainda sem otimização.

Queries por cena: cena 1, 6/8, mapa contextual; cena 2, 8/8, sintética; cena 3,
2/8, batalha específica; cena 4, 2/8, cerco específico; cenas 5–8, 8/8 cada,
sintéticas (Constantinopla/Mehmed, Selim/Marj Dabiq, Suleiman/Mohács e
janízaros); cena 9, 1/8, colagem naval otomano-espanhola; cenas 10–11, 8/8
cada, sintéticas (pintura genérica otomana e Império Otomano/Primeira Guerra).
Os números menores que oito são consultas não necessárias após seleção
elegível. Nenhuma cena reutilizou mapa ou asset anterior.

## Ciência: buracos negros

Projeto `output/science/science/20261004-refactor-black-hole`, 3 cenas,
`--narration human`, providers NASA e Wikimedia.

| Medida | Resultado |
|---|---:|
| Assets reais atribuídos / únicos | 3 / 3 |
| Reusos / sintéticos | 0 / 0 |
| Queries executadas | 3 |
| Providers | NASA, Wikimedia |
| Duração da etapa de mídia | 10,01 s |
| Duração total | 36,32 s |

As três imagens foram uma impressão artística de NGC 300 X-1, uma visualização
de lente gravitacional e a imagem do buraco negro M87 do EHT. A inspeção visual
considerou as três pertinentes, sendo a última imagem observacional direta. A
execução no fluxo `--narration ai` com TTS local também produziu 3 assets
únicos/3 cenas, sem reuso ou sintético; mídia levou 4,96 s e a execução 29,5 s.
O alinhador local não gerou word boundaries, então o pipeline usou timeline
proporcional. O JSON daquela execução registra `downloads_time: 0` apesar de 6
downloads físicos: o timer ainda não era conectado ao cache. Esse zero não é
uma medida. F3 passou a registrar agora a duração de cada cadeia de download;
uma nova execução confirma a mudança:

| Medida | Resultado |
|---|---:|
| Cenas / assets reais únicos | 3 / 3 |
| Reusos / sintéticos | 0 / 0 |
| Queries lógicas / chamadas por provider | 3 / NASA 2, Wikimedia 2 |
| Downloads / cache-hits de bytes | 6 / 0 |
| Bytes baixados | 3.487.109 (3,49 MB) |
| `downloads_time` acumulado | 1,34 s |
| Etapa completa de mídia | 8,4 s |

Projeto `output/science/20261004-download-timing`; métricas em
`metrics/20261004-143325_20261004-download-timing.json`. As seis durações por
asset somam 1,3369 s, arredondadas para 1,34 s. Sem retries ou timeouts nesta
amostra. Isso confirma que `downloads_time` deixou de ser zero artificial;
não estima o custo histórico, dominado por busca e retries.

O `rerender` do projeto científico concluiu sem busca, narração ou roteiro
novos e preservou as mesmas três identidades visuais únicas. Render final:
27,5 s, encoder `av1_vaapi`.

## Antes e depois observável

O baseline histórico anterior tinha 2 assets únicos em 11 cenas e 9 reusos.
Nas novas execuções, o caso otomano teve 4 únicos, 0 reusos e 7 sintéticos;
ciência teve 3 únicos em 3 cenas, 0 reusos e 0 sintéticos. Isso confirma a
separação entre asset novo e reutilizado, mas também evidencia que a etapa
histórica ainda perde cobertura por qualidade/indisponibilidade de busca. Não
se declara a aquisição histórica resolvida apenas pela queda de reuso.

## Limites e próxima prova

Ainda faltam execuções reais sem fallback LLM para roteiro/cenas com falha
induzida, um tema de etimologia/pessoa, validação específica de cache em
rerender de seleção manual e a revisão visual de uma amostra histórica maior.
Também falta repetir o benchmark histórico após os providers voltarem a
responder, para separar tempo de rede de custo de planejamento/scoring. A suíte
completa da validação inicial passou com 825 testes em 148,36 s; os testes
focados de medição passaram (27), e a suíte completa após instrumentação passou
com 829 testes em 146,52 s; `compileall` e
`git diff --check` passaram.

## Execuções após os contratos A4a–A4t

As duas execuções abaixo foram geradas depois da migração de consumidores para
`SemanticScene` e `TimelineSpan`. Foram execuções completas com LLM e serviços
configurados no ambiente; a segunda repetição do vídeo de ciência reaproveitou
roteiro/cenas e bytes de assets, mas voltou a consultar providers. Os projetos
gerados estão em `output/architecture-refactor-validation/` (diretório local
ignorado pelo Git).

| Projeto | Cenas | Cenas com asset real | Assets reais únicos | Reusos | Sintéticos | Busca | Render | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `black-hole-lensing` | 3 | 2 | 4 | 0 | 1 | 52,23 s | 12,60 s | 79,16 s |
| `battle-mohacs` | 3 | 1 | 2 | 0 | 2 | 35,99 s | 14,32 s | 69,53 s |

“Assets reais únicos” conta IDs distintos de provider selecionados nas cenas,
incluindo imagens complementares dentro da mesma cena; não equivale ao número
de cenas cobertas. A primeira cena de ciência usou três imagens (Wikimedia,
Pixabay e Pixabay), e a terceira uma NASA, totalizando quatro IDs reais únicos
em duas cenas cobertas. A primeira cena histórica selecionou duas imagens
Pixabay (dois IDs únicos), mas somente uma imagem era adequada ao evento.
`unique_asset_ratio` ficou em 1,0 e o reuso em zero nos dois projetos; isso
prova identidade distinta, não pertinência editorial.

### Proveniência e qualidade observada

Em `black-hole-lensing`, foram planejadas 24 consultas (8 por cena), com
Wikimedia, Pixabay, Unsplash e NASA retornando resultados; Met e AIC falharam
com HTTP 410 e 500, e Pexels foi ignorado por falta de chave. A cena 1
selecionou a imagem polarizada de Sagitário A do EHT (Wikimedia; representação
“Sagitário A supermassive black hole center of galaxy”, score 100). A cena 2,
com `Event Horizon Telescope logo / global network of radio telescopes /
Sagittarius A* image Event Horizon Telescope`, recebeu 79 resultados, mas
nenhum passou o score para seleção nova; terminou em card sintético. A cena 3
selecionou o campo profundo Hubble da NASA (score 52,25; query
“gravitational lensing black hole light bending”). A imagem é astronomicamente
coerente, mas não mostra lente gravitacional; adequação parcial. Inspeção
visual da imagem EHT confirmou a imagem direta de Sagitário A. As duas imagens
Pixabay da cena 1 são variações de um túnel luminoso, metáforas genéricas, e
não observações ou diagramas confiáveis de buraco negro.

Em `battle-mohacs`, também foram planejadas 24 consultas. Pixabay devolveu a
imagem vencedora, enquanto buscas retornaram 27 candidatos; foram registrados
25 rejeitados por “no topic evidence”, 1 termo bloqueado e 4 consultas
abandonadas por duplicatas. A primeira cena selecionou duas imagens, ambas com
tags da Hungria/Danúbio. Uma delas é o Parlamento Húngaro moderno, visualmente
inspecionado e claramente inadequado para a batalha de 1526; apesar disso,
passou os gates com score 100 por evidência territorial (`Danube river`). As
outras duas cenas receberam cards sintéticos. O registro de seleção marca
`search_exhausted=false` e `search_exhaustion_reason=provider_errors`, portanto
essas cenas não demonstram exaustão real do espaço de busca. Met/AIC tiveram
falhas HTTP em ciência; Pexels continuou sem credencial. O pipeline registrou
explicitamente a busca incompleta, mas ainda selecionou um falso positivo
histórico. Isso é falha editorial real e bloqueia qualquer afirmação de que a
aquisição histórica está resolvida.

Consultas de Mohács mantiveram entidade, evento, data/local e tipo visual, por
exemplo `Batalha de Mohács 1526 mapa`, `Luís II 1526 26000 soldados Danúbio`
e `Vitória Otomana 1526 Batalha de Mohács`. Os providers produziram resultados
fora do domínio (Parlamento de Budapeste, fotos de obra/monastério e conteúdo
genérico); a validação demonstra que query contextual correta ainda não
garante candidato bom. O scoring de evidência territorial precisa deixar de
equivaler a evidência de evento/período quando a cena é histórica.

### Rerender, cache e testes de falha

O rerender de `black-hole-lensing` concluiu em 21,13 s com libx264; o log
informou que roteiro, narração e legendas vieram do cache, sem nova pesquisa,
aquisição de mídia ou TTS. A repetição de geração reutilizou o roteiro e plano
de cena, e os quatro bytes selecionados foram hits de cache de download; ainda
assim, consultou providers de novo (40,2 s de mídia). Portanto o cache de bytes
está comprovado e o rerender respeita a seleção persistida, mas esta repetição
não comprovou cache de decisão da busca.

A suíte completa após F4 passou com **858 testes em 197,12 s** (A4u havia passado
com 857 testes em 202,95 s);
`compileall` e `git diff --check` também passaram. Uma rodada direcionada das
regressões de fallback local, timeout NVIDIA, JSON inválido, timeout de
provider de mídia, cache/manifests e decisões de seleção passou com **60 testes
em 0,19 s**; os testes focados adicionais de pesquisa/pipeline/TTS/TUI passaram
com **50 testes em 151,64 s**. Ainda não foi executada uma geração e2e com
falha de LLM e falha de provider induzidas simultaneamente; não se deve tratar
esses testes como substitutos dessa prova.

### Estado da migração

As fases A4a–A4u concluídas transferiram pesquisa, planejamento, timing, render,
review, teleprompter, replanejamento, metadata, finalize e aquisição para os contratos
canônicos em commits pequenos. O fluxo de Chapter foi removido desses
consumidores e segue apenas nas fronteiras de projeto persistido/metadata.
Ainda não é uma refatoração arquitetural encerrada: pesquisa/script/configuração,
estado de execução, integração TUI/queue, relatórios/metadados e as decisões de
scoring/fallback continuam com partes em transição conforme o mapa da auditoria.
As execuções reais deixam dois próximos limites concretos: eliminar o falso
positivo de período/local em história e provar o cache de seleção sem esconder
mudança de plano. Não houve profile comparável pré/pós sob os mesmos providers;
os tempos acima são observações pontuais, não promessa de ganho de performance.
