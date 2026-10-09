# Seleção de imagens: causas, correções e evidências

## Causas confirmadas

- Aliases verificados não chegavam a todas as cenas. Consultas longas em português e variantes do primeiro conceito consumiam o orçamento de pesquisa.
- O coletor encerrava a busca por quantidade de candidatos tecnicamente elegíveis, antes da avaliação semântica. Resultados pertinentes de fontes posteriores ficavam sem avaliação.
- A correspondência com um conceito local era promovida automaticamente a prova da entidade global. Isso aceitava homônimos, fotos genéricas e eventos de anos diferentes. Traduções de âncoras globais também podiam virar provas locais.
- O sintético precedia o reúso real e tornava esse caminho praticamente inacessível. O reúso privilegiava a maior nota repetidamente; descobertas posteriores não substituíam sintéticos anteriores.
- A inspeção do vídeo revelou outra perda: uma transição de 0,04 s a 24 fps encerrava silenciosamente a sequência após a primeira cena, apesar do sucesso do FFmpeg e da duração correta do áudio.

## Correções

O contexto verificado agora acompanha todas as cenas. A IA traduz somente representações locais aprovadas, preservando proveniência. O orçamento cobre conceitos distintos antes de variantes. A coleta libera o buffer após avaliação e percorre todas as consultas e fontes planejadas.

Identidade e intenção local exigem evidências independentes. Correspondências lexicais preservam todos os termos informativos; lugares e períodos isolados não comprovam identidade. A revisão contextual reconhece traduções, obras e artefatos mediante citações literais dos metadados. Decisões incertas não preservam homônimos aceitos anteriormente. Qualificadores temporais contraditórios não podem ser anulados pela IA; a data de criação da obra é distinguida do evento representado.

Assets reais novos precedem reúso; reúso qualificado privilegia os menos usados e precede sintético. Duplicatas descobertas após download alimentam corretamente o caminho de reúso. Descobertas posteriores podem substituir sintéticos, com qualificação semântica; tipografia intencional permanece deliberada. Licença, resolução e download continuam exigidos. O prefetch não inicia downloads após preencher a seleção.

Traduções e avaliações têm cache por entradas, metadados, modelo e instrução. Sem IA, permanece a avaliação lexical conservadora. As versões dos artefatos invalidam seleções antigas. Transições usam frames inteiros; duração truncada provoca recuperação por cortes e falha explícita se a sequência continuar incompleta.

## Comparação real

| Conteúdo | Cenas reais antes | Cenas reais depois |
| --- | ---: | ---: |
| Platão | 0/3 | 4/4 |
| Mohács, 1526 | 1/3 | 2/3 |
| Tesla e corrente alternada | 1/3 | 4/4 |

Total: **2/9 para 10/11 cenas reais**; sintéticos **7 para 1**; arquivos reais únicos **4 para 15**. A execução histórica final encontrou cotas e timeouts dos modelos, usou planejamento local e manteve um sintético. Os roteiros são idênticos; o planejador não determinístico mudou a divisão em cenas. Esta comparação é observacional.

A inspeção dos frames confirma busto, pintura, caverna e manuscritos; mapa e miniatura da batalha; laboratório, motor e exposição de Tesla. O aeroporto homônimo foi rejeitado. A rejeição do evento de 1687 foi confirmada também reprocessando o candidato real da execução intermediária com a política final.

Persistem dois reúsos reais qualificados; a contagem por arquivo não mede similaridade entre edições da mesma fotografia. No cenário controlado de quatro reúsos, o código anterior repetia um asset quatro vezes; o novo alterna dois assets qualificados. Não se declara eliminação de toda repetição visual.

## Regressão e reprodução

Os testes cobrem aliases, traduções, provas inventadas, confiança inválida, homônimos, períodos, proveniência, falha e cache da IA, fontes posteriores, orçamento, resolução, rotação e ordem dos fallbacks. Testes com FFmpeg verificam transições curtas em 10, 24, 30 e 60 fps e recuperação de truncamento.

A suíte final teve **1.054 testes aprovados** e exclui somente `test_standby_sem_imagens` (pesquisa externa sem isolamento da rede) e `test_needs_single_sequence_depende_do_encoder` (expectativa de Intel Arc indisponível no ambiente). O resultado está em [final-tests.txt](../../output/media-selection-proof-20261008/final-tests.txt).

O benchmark usa pesquisa, modelos, fontes, downloads, TTS e render reais, a 480×854/24 fps. O vídeo histórico foi remontado dos artefatos reais após a correção da transição, sem repetir pesquisa ou narração. Os seis vídeos foram decodificados integralmente; a duração do stream visual cobre todas as cenas.

- [Entradas reproduzíveis](../../scripts/fixtures/media_selection_cases.json) e [executor](../../scripts/media_selection_benchmark.py).
- [Comparação e assets](../../output/media-selection-proof-20261008/comparison.json), [validação dos streams](../../output/media-selection-proof-20261008/render-validation.json), [rotação controlada](../../output/media-selection-proof-20261008/controlled-reuse-results.json) e [rejeição temporal](../../output/media-selection-proof-20261008/temporal-identity-replay.json).
- Frames finais: [Platão](../../output/media-selection-proof-20261008/after/people/platao/review/rendered-frames.jpg), [Mohács](../../output/media-selection-proof-20261008/after-final/history/mohacs/review/rendered-frames.jpg), [Tesla](../../output/media-selection-proof-20261008/after/science/tesla/review/rendered-frames.jpg).
- Vídeos finais: [Platão](../../output/media-selection-proof-20261008/after/people/platao/render/final.mp4), [Mohács](../../output/media-selection-proof-20261008/after-final/history/mohacs/render/final.mp4), [Tesla](../../output/media-selection-proof-20261008/after/science/tesla/render/final.mp4).
