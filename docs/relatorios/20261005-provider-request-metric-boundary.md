# F15 — contagem de requests no limite de provider

**Estado:** implementada, testada e commitada.  
**Escopo:** tentativas HTTP de API, incluindo falhas e chamadas auxiliares dos
providers Met, AIC e NASA.

## Problema observado

No replay G95, o tempo/chamadas de adapter do Met e AIC apareciam em
`provider_search_calls`, mas suas tentativas de busca com falha não apareciam
em `provider_requests`. O Met também consulta um endpoint de objeto para cada
ID encontrado e essas requests secundárias não eram contadas.

As duas métricas medem unidades diferentes: `provider_search_calls` conta uma
execução do adapter; `provider_requests` conta cada tentativa HTTP. Portanto
não se espera que os totais coincidam, mas todos os requests de API precisam
ser contabilizados mesmo quando falham.

## Mudança

`_provider_get_json()` agora registra a tentativa imediatamente antes do GET.
Met e AIC usam o helper para requests de busca e Met marca cada consulta de
objeto como `metadata`. Unsplash e NASA também encaminham suas requests pela
mesma fronteira; os manifests de arquivos NASA entram como metadata. Outros
providers que fazem `urlopen` diretamente mantêm a contagem no ponto da
tentativa.

`RunMetrics.media_search(provider, operation)` preserva os agregados
compatíveis e adiciona as dimensões:

- `provider_requests` / `requests_per_provider`: total de tentativas HTTP por
  provider;
- `provider_requests_by_operation` /
  `requests_by_provider_operation`: detalhamento por `search`, `metadata` e
  `unknown`;
- `provider_search_calls`: quantidade de invocações de adapter, separada das
  tentativas HTTP;
- `searches`: alias de schema legado do agregado de requests.

Downloads de imagens continuam em `downloads` e não são contados como requests
de API. Requests de metadata fazem parte do total do provider e são
identificadas separadamente.

## Arquivos e contratos

- `src/curio/media/providers.py`: helper de contagem e chamadas Met/AIC/NASA/
  Unsplash encaminhadas pela fronteira.
- `src/curio/metrics.py`: contador por operação, mantendo os agregados e
  aliases anteriores.
- `tests/test_media_museums.py`: regressões de busca Met com falha de lookup
  e busca AIC que falha antes de obter resposta.
- `tests/test_media_metric_units.py`: contrato de unidades e projeções.
- `README.md`: definições observáveis das métricas.

## Validação

- Focados (`test_media_metric_units.py`, `test_media_museums.py`,
  `test_media_providers.py`): **40 passaram**.
- Suíte completa: **1014 passaram em 182,23 s**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

## Validação em runtime após o commit

Uma execução real `from-script` foi feita com o roteiro histórico Mohács já
existente, divisão local e chaves de LLM vazias. O primeiro intento parou na
pesquisa por HTTP 429 da Wikipédia, pois o ambiente não tinha
`CURIO_CONTACT`. O replay foi repetido com a URL pública do repositório no
User-Agent, saída/cache/métricas isolados em `/tmp/curio-f15-*` e narração
humana para evitar TTS.

Resultado da geração: **4 cenas; 4 assets reais; 4 únicos; 0 reusos; 0
sintéticos; 31 queries lógicas; 8 downloads; 15.603.293 bytes; 0 retries e 0
timeouts; 148,89 s total, dos quais 81,98 s em mídia**. Todos os vencedores
vieram do Wikimedia. Cada um dos cinco providers configurados teve 31
invocações de adapter e 31 requests `search`, confirmando os agregados e
aliases na execução. O Met respondeu HTTP 410 em suas chamadas e AIC HTTP 500;
NASA retornou zero resultados nesse tema; portanto essa geração não acionou
lookups auxiliares desses providers e mostrou zero `metadata`.

Uma sondagem real independente de NASA com `Apollo 11` retornou um asset e
registrou `nasa: {search: 1, metadata: 1}`, confirmando o caminho de manifesto.
Sondagem Met `Julius Caesar` retornou HTTP 410, então o lookup de objeto Met
foi validado por regressão simulada, não por serviço live. Erros de API seguem
contados antes de propagar a falha.

| Cena | Representação/query vencedora | Asset | Nível | Inspeção |
|---|---|---|---|---|
| 1 | evento / `Battle of Mohacs 1526` | mapa histórico da batalha | específica | Mapa identifica Mohács e 1526; adequado. |
| 2 | `Ottoman Battle of Mohacs` | miniatura turca da batalha | representação/variante | Miniatura histórica da própria batalha; adequada. |
| 3 | `Kingdom of Hungary Battle of Mohacs` | diorama do Museu Militar de Istambul | representação/variante | Mostra a batalha, mas é fotografia moderna de exposição, não imagem de época. |
| 4 | `Hungary Battle of Mohacs` | miniatura de combate individual, Suleymanname | representação/variante | Ilustração histórica da batalha; adequada. |

O primeiro vencedor marcou fallback `specific`; os três restantes vieram de
representação/variante. Os gates e scores não mudaram. A inspeção visual
confirma quatro imagens diferentes e relacionadas, mas o diorama moderno
permanece uma ressalva editorial. A execução também registra indisponibilidade
real do Met/AIC; os totais não devem ser lidos como prova de que esses acervos
foram pesquisados com sucesso.
