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

Não foi feita geração real nesta fase: a mudança afeta somente observabilidade
e não altera buscas, candidatos, scoring, seleção ou assets. A próxima geração
real deverá confirmar que os requests Met/AIC e metadata NASA aparecem com a
decomposição esperada.
