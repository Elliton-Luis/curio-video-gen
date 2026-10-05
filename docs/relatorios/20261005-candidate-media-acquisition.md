# G75 — aquisição técnica de candidatos de mídia

**Commit:** `c4ef8c5` (`refactor: isolate candidate media acquisition`)

**Estado:** concluída e testada; simplificação do coordenador visual continua.

## Problema

Depois de G74, `visual.py` ainda executava a janela concorrente de downloads,
consumia futures, verificava dimensões e identidade/hash, atualizava uso,
metrics/logging e convertia falhas para auditoria. Embora cada tentativa já
produzisse `CandidateAcquisitionOutcome`, essa responsabilidade permanecia no
coordenador de busca e seleção.

## Mudança

Novo módulo `media_candidate_acquisition.py` recebe candidatos ranqueados e
executa as tentativas de aquisição técnica. Para candidatos novos, devolve
`CandidateAcquisitionBatch`: sequência imutável de `CandidateAcquisitionOutcome`
e avisos. O lote oferece partições de selecionados e rejeitados sem converter
para JSON até a projeção de saída/auditoria.

O módulo também possui a tentativa tardia de aquisição para candidatos já
marcados para reuso. `visual.py` segue decidindo a ordem editorial: tenta
candidatos novos, então visual sintético e, se ele não for produzido, reuso.
Providers, `media_acquisition.py`, scoring, gates semânticos e thresholds não
foram alterados.

O código de aquisição ainda registra efeitos de métricas/logging e recebe o
mapa de usos de assets para detectar duplicata por hash. Essas responsabilidades
compartilhadas não são declaradas resolvidas por G75; são limites conhecidos
para futuras fases de ownership.

## Arquivos

- `src/curio/stages/media_candidate_acquisition.py` (novo): lote imutável,
  janela concorrente, aquisição, gates técnicos pós-download e outcomes.
- `src/curio/stages/visual.py`: delega tentativas de assets novos e reuso;
  mantém planejamento/fallback e projeções de cena.
- `tests/test_media_selection.py`: imutabilidade do lote, partições e dedupe
  por conteúdo após aquisição.

## Validação

- **102 testes focados** de seleção, direção visual, uso de assets, auditoria e
  integração/pipeline.
- **943 testes passaram; 1 foi desmarcado** por HTTP 429 da API real da
  Wikipédia, em **171,12 s** (`pytest -q -k 'not standby_sem_imagens'`).
- `python -m compileall -q src tests` e `git diff --check` passaram.
- Nenhuma geração real foi executada nesta fase. A extração preserva
  comportamento por regressões de teste, mas não mede disponibilidade externa
  nem qualidade editorial nova.

## Limites e próximo trabalho

G75 reduz as responsabilidades de aquisição em `visual.py`, mas o módulo novo
ainda acumula tentativa de download, validação técnica, deduplicação por hash e
efeitos operacionais. O selector continua calculando o pool fresh/reused, e a
política temporal fresh → sintético → reuso continua no coordenador. A próxima
fase deve auditar essas decisões e mover somente responsabilidades com owner
demonstrável, sem alterar a ordem editorial ou os gates semânticos.
