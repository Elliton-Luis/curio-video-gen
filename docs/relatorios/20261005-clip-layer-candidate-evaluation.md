# G84 — camada CLIP na avaliação de candidatos

**Commit:** `bc131b9 refactor: move clip reranking into candidate evaluation`  
**Estado:** concluída; ownership movido sem mudança de política editorial.

## Causa e mudança

`visual.py` tinha uma função local `apply_clip` que preparava e baixava
imagens, validava dimensões, executava o score opcional CLIP, atualizava a
evidência imutável de candidatos ranqueados, reordenava a shortlist e contava
uso da camada nas métricas. O módulo já era dono da avaliação semântica e da
evidência de `CandidateEvaluation`, portanto o comportamento de rerank estava
no coordenador de busca em vez de junto à avaliação do candidato.

G84 moveu esse comportamento para `apply_clip_layer()` em
`src/curio/stages/candidate_evaluation.py`. `visual.py` delega a aplicação
para candidatos específicos e contextuais e continua coordenando a ordem das
tiers e a seleção. Download/cache permanecem delegados a
`media_acquisition`; este commit não move transporte ou persistência para o
avaliador.

## Contrato e comportamento

`apply_clip_layer()` recebe e devolve uma `list[RankedSelectionCandidate]`.
Rejeita entradas que não sejam uma lista de candidatos ranqueados. Mantém o
mesmo limite de shortlist, gate de configuração CLIP, validação dimensional,
tratamento de falhas técnicas, ordenação e métricas existentes. A avaliação
aplica o score por `with_clip_score()`, preservando atualização imutável da
evidência e do snapshot tipado do asset.

Não foi criado schema persistido, serviço ou modelo de dados novo. Não houve
mudança em thresholds, busca, providers, diversidade, fallback ou aquisição
editorial.

## Arquivos

- `src/curio/stages/candidate_evaluation.py`: nova função `apply_clip_layer()`.
- `src/curio/stages/visual.py`: remove função local duplicada e chama o
  avaliador nos dois caminhos de ranking.

## Validação

Testes focados da direção visual, seleção, waterfall, museus, funil, conceitos
de query e avaliação: **104 passaram em 0,69 s**. A suíte completa terminou
com **965 testes passando em 195,46 s**. `python -m compileall -q src tests` e
`git diff --check` passaram. Não foi executada geração real: a fase só moveu
ownership e preservou comportamento.

## Limite restante

`visual.py` ainda orquestra coleta, tiers, ranking, fallback, reuso, auditoria e
métricas. G84 extraiu uma decisão de camada, mas não simplifica por si só o
coordenador nem conclui o ownership canônico de efeitos operacionais. A próxima
extração deve ser guiada por contratos e dependências observados, não pelo
tamanho do arquivo.
