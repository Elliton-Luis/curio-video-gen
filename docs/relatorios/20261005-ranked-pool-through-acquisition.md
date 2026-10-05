# G73 — manter candidatos ranqueados tipados até a aquisição

**Commit:** `7b965a1` (`refactor: keep ranked candidates typed through selection`)
**Estado:** concluída; a row transitória continua dentro de cada tentativa.

## Problema

Depois de `prepare_selection_pool()`, `visual.py` transformava toda a shortlist
fresh e toda a lista de reuso em dicts. A tipagem de G70 terminava na própria
fronteira que deveria consumi-la, antes de o candidato ser tentado para
acquisition.

## Mudança

`ranked` e `reused_ranked` permanecem listas de `RankedSelectionCandidate`.
A janela concorrente de download lê o snapshot do asset; o loop projeta uma row
somente quando inicia a tentativa que precisa manter estado técnico legado. A
ordenação da reserva de reuso lê diretamente o score tipado e cria a row apenas
para o candidato tentado.

A política de ranking, a janela/concorrência, o schema de auditoria e o
comportamento de fallback permanecem iguais.

## Arquivos

- `src/curio/stages/visual.py`

## Validação

- 99 testes focados de seleção, direção visual, pipeline e auditoria passaram.
- Suíte ampla: 940 passaram; um teste foi deselecionado após HTTP 429 da API
  real da Wikipédia. Duração: 178,02 s.
- `python -m compileall -q src tests` e `git diff --check` passaram.
- Nenhuma geração real.

## Limite

O row local ainda é editado com rejeição pós-download, dados do asset adquirido,
ordem final e motivo de reuso. O resultado tipado precisa representar esses
estados antes de a orquestração migrar para um owner menor. A tentativa de
adicionar um wrapper que apenas carregue o dict não resolveria essa dívida.
