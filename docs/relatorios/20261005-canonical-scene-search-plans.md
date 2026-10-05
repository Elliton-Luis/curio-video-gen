# G94 — planos canônicos consumidos pela busca de cena

**Commit:** `60703ae refactor: pass canonical plans into scene search`  
**Estado:** implementada e validada por testes.  
**Arquivos:** `src/curio/stages/visual.py`,
`tests/test_support/media_scene_search.py`, `tests/test_pipeline_visual.py`.

## Causa

`fetch_media_multi()` construía um `VisualPlan` para escolher a prioridade de
providers; depois `_search_scene_with_shortcircuit()` reconstruía o plano e
gerava seu `SearchPlan`. Mesmo que a função determinística produzisse valores
equivalentes, a busca não consumia o mesmo artefato que justificou a ordem dos
providers. Isso duplicava trabalho e deixava a fronteira permitir divergência
futura entre política de providers e queries.

## Mudança de contrato

O loop por cena agora constrói uma única vez `VisualPlan` e `SearchPlan`, mede a
mesma etapa de planejamento e os passa junto com a cena à busca. O consumidor
exige esses tipos e verifica que ambos pertencem à cena recebida. O mesmo
`VisualPlan` alimenta a prioridade de providers e a construção da busca; a
aquisição não reconstrói semântica nem queries. As fixtures que chamam o helper
interno foram migradas para criar e passar explicitamente os dois planos.

O contrato de saída dos estágios e o formato persistido permanecem iguais; a
duração de `media_query_generation_time` continua cobrindo a construção de
ambos os planos. Queries, gates, scoring, provider adapters e seleção não foram
alterados.

## Validação

O teste de prioridade por cena também confirma que os mesmos planos são
encaminhados ao consumidor; outro teste garante rejeição de plano de cena
divergente. As regressões de diretor, waterfall, museus, conceitos, fallback e
coleção passaram.

- Testes focados: **138 passaram**.
- Suíte completa: **1011 passaram em 189,64 s**.
- `python -m compileall -q src tests` e `git diff --check`: passaram.

Não foi feita geração real nesta fase de ownership. Qualidade editorial e
disponibilidade de acervos permanecem pendentes da validação I.
