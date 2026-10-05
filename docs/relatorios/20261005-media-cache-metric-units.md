# F12 — métricas de cache de mídia com unidades explícitas

**Commit:** `9d86d4e refactor: name media cache metrics by cache type`  
**Estado:** concluída e validada.  
**Escopo:** métricas de cache de download e cache compartilhado de busca.

## Problema

O JSON expunha `cache_hits` e `cache_misses`, que contam apenas bytes de mídia
obtidos do cache local ou da rede. O cache compartilhado de resultados de busca
também existe, mas seus hits eram visíveis somente como uma etapa do funil.
Sem nomes explícitos, um consumidor podia interpretar `cache_hits` como
qualquer cache do pipeline.

## Mudança e contrato

`consumption.media` passa a expor:

- `download_cache_hits` e `download_cache_misses`: reuso local versus download
  de bytes;
- `shared_search_cache_hits`: resposta normalizada de provider reutilizada
  durante a geração, sem nova chamada externa.

As chaves `cache_hits` e `cache_misses` permanecem como aliases compatíveis dos
contadores de download. Os hits de busca continuam no `funnel` como diagnóstico
da aquisição, e a nova chave é uma projeção explícita desse mesmo contador.

## Validação

O teste registra hits e misses de download e dois hits de busca; verifica as
unidades independentes e os aliases históricos.

- `pytest -q tests/test_media_metric_units.py tests/test_media_search_contract.py`: **21 passaram**.
- `pytest -q`: **1003 passaram em 178,60 s**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

## Limites restantes

Esta fase distingue apenas essas duas famílias de cache no agregado. Não mede
bytes evitados pelo cache de download, duração de lookup, nem associa cada hit
de busca a query/provider no resumo agregado. Cache continua sendo mecanismo de
economia, não fonte de decisão editorial.
