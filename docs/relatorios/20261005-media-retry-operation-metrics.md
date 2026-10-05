# F10 — retries de mídia classificados por operação

**Commit:** `1054c8a refactor: attribute media retries by operation`  
**Estado:** concluída e validada.  
**Escopo:** proveniência das novas tentativas de busca e download.

## Problema

O total `consumption.media.retries` e `retries_by_provider` somava retries de
busca do Wikimedia com retries de download de bytes. Os dois pontos de chamada
já sabiam qual operação estava repetindo, mas descartavam essa distinção ao
registrar o evento. Portanto, a métrica agregada não permitia separar falha ou
custo de aquisição de candidatos do custo de baixar um asset.

## Mudança e contrato

`media_record_retry(provider, operation)` preserva os campos agregados já
publicados (`retries`, `retries_by_provider`) e registra:

- `retries_by_operation`: totais em `search`, `download` e `unknown`;
- `retries_by_provider_operation`: a mesma separação por provider.

`WikimediaProvider` classifica suas tentativas repetidas como `search`; o fetch
de bytes em `media.cache` classifica-as como `download`. Chamada legada sem
operação continua somada aos totais antigos e é contabilizada como `unknown`.
Assim, os contadores históricos não mudam de unidade nem perdem dados por
falta de informação.

## Regressão e validação

O teste envia um retry de cada tipo pelo mesmo provider, verifica os totais
agregados e os dois breakdowns no documento de métricas.

- `pytest -q tests/test_media_metric_units.py tests/test_media_artifacts.py tests/test_media_providers.py`: **34 passaram**.
- `pytest -q`: **999 passaram em 187,91 s**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

## Limites restantes

`unknown` continuará possível para código externo/legado que chame o método
sem operação. `media_timeouts` ainda não separa provider request, adapter
timeout e outra interrupção; lifecycle completo de cache/download e profile
por suboperação seguem pendentes. Esta fase não executou geração real porque
altera apenas a classificação dos contadores.
