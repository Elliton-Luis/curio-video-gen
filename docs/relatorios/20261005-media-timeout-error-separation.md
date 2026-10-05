# F11 — timeout separado de bloqueio de provider

**Commit:** `4ee2506 fix: separate provider disablement from media timeouts`  
**Estado:** concluída e validada.  
**Escopo:** semântica de `consumption.media.timeouts` e falhas de provider.

## Problema

`search_providers()` incrementava `media_timeouts` tanto quando a espera por
uma resposta realmente expirava quanto quando um `401`, `403` ou `429`
desativava o provider para a execução. Isso misturava latência com
autorização/rate limit e tornava o contador de timeout falso.

## Mudança

Somente exceções de timeout incrementam `timeouts`; agora também fica salvo
`timeouts_by_provider`. Respostas que desativam provider são contadas em
`disabled_providers[provider]` com motivo `rate_limited` ou `access_denied`.
Os totais de buscas e retries continuam sem alteração. O código de
desativação permanece no limite do adapter de busca, mas a métrica expressa o
evento observado corretamente.

## Regressões e validação

- `429 Too Many Requests` desativa o provider e não aumenta timeout.
- `403 Forbidden` desativa o provider e não aumenta timeout.
- timeout real da espera é contado e atribuído ao provider correto.
- focados (`test_media_search_contract.py` e `test_media_metric_units.py`): **20 passaram**.
- suíte completa: **1002 passaram em 190,17 s**.
- `python -m compileall -q src tests` e `git diff --check`: passaram.

## Limites restantes

Falhas do provider que não são timeout nem 401/403/429 continuam visíveis na
auditoria por query, mas ainda não há um contador global tipado para cada
categoria de erro. Backfill não consegue reconstruir timeout histórico sem
eventos persistidos. Nenhuma geração real foi executada nesta fase.
