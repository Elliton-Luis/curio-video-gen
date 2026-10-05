# I2 — aquisição científica real após F15

**Estado:** geração concluída; aquisição e métricas verificadas; qualidade
editorial tem problemas abertos.  
**Execução:** /tmp/curio-f15-science-output/f15-m87-metrics.

## Procedimento

Foi reutilizado como entrada o roteiro M87 do replay G94, com from-script,
divisão determinística local, LLM desabilitado, providers reais e saída/cache/
métricas isolados em /tmp/curio-f15-science-*. Título: “M87 Black Hole”;
tópico: “M87 black hole Event Horizon Telescope”. A geração produziu um MP4
silencioso e teleprompter, sem narração sintética.

## Resultado de aquisição

- **4 cenas; 4 assets reais; 4 IDs/hash únicos; 0 reusos; 0 sintéticos;**
  unique_asset_ratio = 1.0.
- 30 queries lógicas. Providers: Wikimedia, Met, AIC, NASA e Openverse.
- Requests: NASA 23 (14 search + 9 metadata), Openverse 14, Met 26, Wikimedia
  14, AIC 26; total 103 tentativas. Met respondeu HTTP 410 e AIC HTTP 500.
  NASA metadata requests vieram de manifests dos resultados.
- 39 candidatos no relatório visual, 27 mantidos; duas queries foram
  abandonadas por duplicatas. Não houve timeout nem retry.
- 5 downloads, 1.187.898 bytes.
- 38,33 s na etapa de mídia; 76,00 s totais. Pesquisa 2,74 s, montagem
  silenciosa 23,88 s e teleprompter 11,01 s. Durações por provider incluem
  trabalho sobreposto, não são aditivas em tempo de parede.
- nvidia.calls = 0; cenas vieram do fallback local.

## Cenas e inspeção visual

| Cena | Representações | Query do vencedor | Asset vencedor | Inspeção |
|---|---|---|---|---|
| 1 | M87, black hole, galaxy | black hole M87 | EHT M87 em luz polarizada, ID 102736603 | Visualização polarizada de M87. |
| 2 | M87, black hole, event horizon | black hole M87 | EHT M87 em luz polarizada, ID 170480594 | Quase a mesma composição da cena 1, apesar de ID/hash diferentes. |
| 3 | M87, black hole, galaxy | black hole M87 | ilustração “Black hole - Messier 87”, ID 77916527 | Visual abstrato centrado no buraco negro. |
| 4 | M87, black hole | black hole artifact M87 | imagem da galáxia M87 em infravermelho, ID 51392756 | Galáxia observacional; licença marcada para revisão manual. |

Hashes SHA-256 dos quatro arquivos foram distintos. Inspeção visual mostra que
isso não resolve diversidade perceptual: as cenas 1 e 2 são quase duplicatas.
O ranking as pontuou em 100; o score textual não mede semelhança visual entre
selecionados. Fica confirmada a regressão editorial já observada, não um
problema de identidade binária.

## Fonte factual e limites

A pesquisa aceitou “Messier 87”, “Capacete M87” e “Zastava M87”, embora as duas
últimas sejam homônimos irrelevantes. O roteiro recebeu alerta para uma
afirmação sobre 2019 sem correspondência nas fontes. Isso mostra uma falha
adicional na recuperação/qualificação de fontes factuais; não deve ser
confundida com o sucesso da aquisição visual.

Met/AIC estavam indisponíveis, então seus contadores refletem tentativas HTTP
falhas, não cobertura de acervo. A geração confirma a métrica F15 de
search versus metadata e satisfaz o segundo domínio real após F15. Não fecha
a validação arquitetural: faltam correção do falso positivo de fontes,
diversidade perceptual, falhas combinadas e rerender após troca manual.
