# G66 — snapshot imutável de asset em `Candidate`

**Commit:** `8bed5ec refactor: snapshot provider assets in candidates`  
**Estado:** implementado e validado; o plano arquitetural geral continua em andamento.

## Causa e limite de ownership

`Candidate` era `frozen`, mas seu campo `asset` apontava para `MediaAsset`, que é
mutável e contém listas modificáveis de tags/categorias. A resposta do provider
podia ser mutada por alias depois de entrar na coleção, alterando a evidência
que seria pontuada.

`MediaAsset` também tem responsabilidades legítimas de lifecycle: aquisição
altera tamanho/dimensões/caminho de arquivo, e a seleção pode preencher
`used_in`. Tornar esse modelo globalmente frozen misturaria o snapshot da
resposta do provider com o estado técnico posterior.

## Alteração

G66 adiciona `ProviderAssetSnapshot`, um retrato frozen dos campos de
`MediaAsset`; tags e categorias são tuplas. `Candidate.__post_init__` captura
esse retrato quando recebe um `MediaAsset`. O snapshot mantém `to_dict()` com os
mesmos campos, incluindo listas JSON para tags/categorias. O restante do
pipeline continua construindo/alterando `MediaAsset` no lifecycle de aquisição.

## Arquivos e regressão

- `src/curio/stages/media_contracts.py`
- `tests/test_media_contracts.py`

A regressão altera título, tags e caminho local no asset original depois de
criar o Candidate. A evidência congelada mantém os valores originais, não aceita
alterações diretas, e `to_evaluation_input()` continua emitindo a projeção usada
pelos consumidores.

## Validação

- Decisão, contratos, coleta, avaliação e diretor visual: **55 testes passaram**.
- Suíte ampla: **933 passaram, 1 excluído** (`test_standby_sem_imagens`), que
  depende da API real da Wikipédia e respondeu HTTP 429 nas execuções recentes.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- Sem geração real ou inspeção visual nesta fase.

G66 altera somente a integridade da evidência que entra em avaliação; não muda
queries, providers, gates, scoring, seleção, fallback ou download. Ver também o
[relatório arquitetural](20261005-relatorio-arquitetura-estado-atual.md) e a
[auditoria de pipeline/contratos](../analises/20261004-auditoria-arquitetura-pipeline-e-contratos.md).
