# G93 — prioridade de providers independente por cena

**Commit:** `38b892e fix: order media providers per scene`  
**Estado:** implementada e validada por testes; aquisição real posterior ainda
necessária para observar disponibilidade e latência atuais dos acervos.  
**Arquivos:** `src/curio/stages/visual.py`, `tests/test_pipeline_visual.py`.

## Causa

`media_provider_policy.ordered_providers()` recebia o `VisualPlan` de cada
cena, mas `fetch_media_multi()` achatava as listas em uma única ordem global e
deduplicava os nomes. A primeira ocorrência de cada provider determinava sua
posição para todas as cenas seguintes. Portanto, uma cena histórica no início
da lista podia deixar `Met` antes de `NASA` também para a cena espacial, apesar
da política especial de ciência/espaço.

## Mudança e ownership

O pipeline agora deriva `ordered_providers(cfg, scene_plan, genre)` dentro do
loop de cada cena e passa somente essa ordem à busca daquela cena. O contrato de
`ordered_providers` continua sendo ordenar adapters disponíveis conforme o
plano visual; ela não consulta acervos nem avalia relevância. O coordenador
`visual.py` seleciona o plano da cena e aplica essa política localmente. Queries,
providers configurados, gates, scoring, coleta, diversidade, fallback e cache
permanecem iguais.

## Regressão e validação

O teste novo combina uma cena histórica (`Met`, `Wikimedia`) seguida por uma
cena espacial (`NASA`, `Wikimedia`) e verifica a lista exata entregue ao
coordenador de busca de cada cena. Antes da mudança, a ordem da primeira cena
era compartilhada pela segunda.

- Testes focados (`test_pipeline_visual.py`, `test_media_museums.py`,
  `test_media_diag.py`, `test_visual_director.py`): **82 passaram**.
- Suíte completa: **1010 passaram em 190,57 s**.
- `python -m compileall -q src tests` e `git diff --check`: passaram.

Não foi executada geração real nesta fase. O teste prova qual ordem chega a
cada cena, mas não mede disponibilidade, resultados, latência nem qualidade
editorial dos providers em execução real. Isso continua em aberto na validação
da fase I.
