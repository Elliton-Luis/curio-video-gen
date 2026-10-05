# G64 — campos explícitos da decisão visual

**Commit:** `519c1fa refactor: model visual decision fields explicitly`  
**Estado:** implementação e gate registrados; refatoração arquitetural geral continua em andamento.

## Problema

G63 havia introduzido `VisualDecision` para validar `SelectionDecision`, campos
conhecidos e updates de seleção/reuso. Ainda guardava, porém, os demais fatos
conhecidos em um payload mapping genérico. A estrutura continuava sendo
consumida como dicionário e o contrato não deixava claro quais atributos
pertenciam à decisão visual.

## Alteração

`VisualDecision` agora tem atributos nomeados para tópico, plano visual, plano
de fallback e busca, intenção, entidades, representações, aliases, queries,
providers consultados, candidatos, seleção, estado/razão de esgotamento e nível
de fallback. Campos textuais, objetos, listas e booleanos são validados. A
criação usada pelos produtores rejeita nomes desconhecidos.

`from_dict()` e `to_dict()` continuam sendo o adaptador do formato persistido.
O contrato registra presença para preservar a diferença entre campo omitido e
campo presente com `null`; extensões desconhecidas de projetos antigos também
fazem round-trip. Valores mapping e sequências são congelados recursivamente,
enquanto `to_dict()` devolve uma projeção independente que pode ser serializada
ou modificada pelo consumidor.

## Limites preservados

Não houve mudança na query, nos providers, gates, scoring, seleção, fallback,
cache ou formato do projeto. Rows internos de query/candidato ainda são
mappings JSON, não contratos independentes. Esta migração também não remove a
orquestração de aquisição e seleção que ainda existe em `stages/visual.py`.

## Arquivos

- `src/curio/media/visual_decision.py`
- `tests/test_visual_decision.py`

Os testes cobrem atributos e round-trip, extensions antigas, campo ausente,
imutabilidade profunda, cópia projetada e rejeição de campos de produtor
desconhecidos.

## Validação

- Foco em decisão, seleção e pipelines visuais: **31 testes passaram**.
- Suíte ampla: **930 passaram, 1 excluído** (`test_standby_sem_imagens`), pois
  a chamada real à API da Wikipédia respondeu HTTP 429.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- Não houve geração real de vídeo nem inspeção visual nesta fase.

## Relação com a investigação de mídia

G64 era uma etapa da refatoração de ownership/contratos, não uma nova tentativa
de corrigir a qualidade de aquisição. As regressões que motivam a cadeia de
migrações incluem repetição de assets entre cenas e queries semanticamente
ruins (`gold`, `formavam`, `laboratory`, `microscope`). Nesta fase, a tarefa
precisa era tornar explícita a estrutura da decisão visual que registra os
resultados dessas etapas, sem afrouxar gates nem alterar a busca.

Ainda falta transformar rows de auditoria em estruturas próprias, continuar a
redução de responsabilidades do coordenador visual e validar a aquisição atual
com geração real. O relatório arquitetural completo e o mapa das fases estão em
[relatorio de estado](20261005-relatorio-arquitetura-estado-atual.md) e na
[auditoria de pipeline e contratos](../analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md).
