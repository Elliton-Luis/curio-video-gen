# G88 — ownership da montagem da decisão visual

**Data:** 2026-10-05  
**Commit:** `c5424b5 refactor: centralize visual decision audit`  
**Estado:** concluída no escopo desta migração; não conclui a refatoração arquitetural global.

## Problema

Após G85 e G87, a auditoria já derivava provenance do `VisualPlan` e a classificação de exaustão/fallback vinha de contratos tipados. Ainda assim, `_search_scene_with_shortcircuit()` em `visual.py` montava à mão o payload inteiro de `VisualDecision`: tópico, planos, intenção, entidades, representations, aliases, auditoria de queries, providers, candidatos, vencedor e nível de fallback. O coordenador de busca, portanto, também era dono da projeção final de auditoria.

## Mudança

`visual_audit.build_scene_visual_decision()` agora reúne os fatos tipados já produzidos por seleção, cena, planejamento, coleta e provenance. Valida tipos e coerência de IDs de cena, conjunto de queries planejadas, estado selecionado/ausente, identidade do asset vencedor, nível de fallback, threshold e plano de fallback antes de criar `VisualDecision`.

`visual.py` calcula a decisão de seleção e delega a construção da auditoria. Os campos projetados e o formato persistido continuam os mesmos. A nova função não muda queries, gates, scoring, ordem de providers, aquisição, reuso ou política sintética. `evaluated_entries` e `rejected` ainda chegam como rows dict; sua migração para contratos tipados continua uma dívida de fronteira.

## Arquivos e contratos

- `src/curio/stages/visual.py`: remove a composição inline e chama o owner de auditoria.
- `src/curio/stages/visual_audit.py`: adiciona a fábrica/validação `build_scene_visual_decision`.
- `tests/test_visual_audit.py`: adiciona regressão que confere a projeção da decisão e sua provenance.

Não foi criado schema persistido novo nem removido contrato anterior. `VisualDecision` continua sendo o resultado e o JSON permanece compatível.

## Validação

- `pytest -q tests/test_visual_audit.py`: **9 passaram**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- `pytest -q`: **994 passaram em 185,22 s**.

Não foi feita geração real, pois G88 move ownership e adiciona validação sem alterar comportamento editorial ou consultas. A suíte comprova regressões cobertas, não qualidade universal de seleção.

## Limites remanescentes

`visual.py` continua coordenando busca, coleta, avaliação, tentativas de aquisição e transições de fallback. A auditoria ainda aceita rows de candidatos/rejeições em parte da fronteira. G88 reduz uma responsabilidade do coordenador, mas não encerra a fase G nem prova por si só o objetivo arquitetural maior.
