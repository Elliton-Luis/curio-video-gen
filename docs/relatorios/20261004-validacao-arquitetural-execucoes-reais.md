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
proporcional.

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
completa da revisão atual passou com 825 testes em 148,36 s; `compileall` e
`git diff --check` passaram.
