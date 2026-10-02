# Relatório — Limites e concorrência segura no pipeline

- **Data:** 2026-10-02 17:15 (local)
- **Tipo:** relatorio
- **Escopo:** limitar e paralelizar buscas/downloads; cache ffprobe; reduzir chamadas LLM sem lacuna visível
- **Commit(s):** `b98d3ee perf: bound and parallelize pipeline network work`
- **Origem:** auditoria `20261002-131932_analise_refatoracao-codigo-morto.md`, seção 5

## 1. O que foi pedido

Só otimizar depois da estrutura. Limites conservadores e determinísticos.

## 2. O que foi feito

| Arquivo | Mudança | Limite/decisão |
|---|---|---|
| `stages/visual.py` | Executor compartilhado de buscas; providers do mesmo query executam em paralelo | `CURIO_MAX_CONCURRENT_SEARCHES`, default 3, clamp ≥1; resultados consumidos em prioridade original. |
| `stages/visual.py` | Timeout não usa `ThreadPoolExecutor` em `with` | Chamada retorna no deadline; worker ativo termina no timeout de socket do provider. Deadline de cada query é comum aos providers. |
| `stages/visual.py` | Downloads dos assets selecionados usam pool | `CURIO_MAX_CONCURRENT_DOWNLOADS`, default 2; janela limita trabalho iniciado. Falhas continuam warning e próximo asset pode substituir. |
| `stages/visual.py` | Cache de dimensão ffprobe por path, tamanho e mtime_ns | Cache LRU 512 entradas; alteração do arquivo invalida. |
| `stages/visual.py` | Resultado de busca em memória por query/provider entre cenas do mesmo vídeo | Reaproveita resultado vazio ou com candidatos; registra `shared_search_hits`; cache em disco continua sendo usado entre execuções. |
| `stages/research.py` | Buscas Wikipedia em lotes paralelos | `CURIO_MAX_CONCURRENT_RESEARCH`, default 3, máximo 6; coleta/processamento preserva ordem de query; HTTP mantém timeout/retry existente. |
| `stages/etymology.py` | Logeion e Perseus rodam paralelos | Cadeia Wiktionary permanece serial porque próximo headword depende do elo anterior. Ordem de saída fica fixa. |
| `stages/research.py` | Planner LLM de lacunas pula fonte visivelmente rica | Só chama quando <5 fatos, <700 caracteres de evidência, ou <2 fontes. Heurística local, sem custo LLM quando evidência já é ampla. |
| `metrics.py` | Lock nos contadores chamados por workers | Evita perda de contagem durante buscas/downloads concorrentes. |

## 3. Evidências

- `python3 -m pytest tests/test_runlog.py tests/test_media_waterfall.py tests/test_research_iterative.py tests/test_etymology_sources.py tests/test_audio_library.py -q` — 78 passed.
- `python3 -m pytest tests/ -q` — **727 passed**.
- Teste de timeout prova retorno antes de liberar worker bloqueado.
- Teste de provider usa `Barrier` para provar buscas concorrentes.
- Teste de download usa `Barrier` para provar downloads selecionados concorrentes.
- Teste de pesquisa mede concorrência e confirma ordem determinística de resultados.
- Teste de cache confirma 1 ffprobe em leituras repetidas e invalidação após arquivo mudar.
- Teste de busca repetida confirma segunda cena não envia a mesma query/provider à rede.
- Teste de evidência rica prova `_plan_gaps` não roda.

## 4. Status vs PRD §19

Sem dependência paga ou telemetria externa. Workers limitados e fontes gerais preservadas.

## 5. Limitações

- Timeout não mata thread Python. Requisições em execução liberam worker quando timeout finito de socket do provider vence; fila segue limitada pelo executor.
- Pesquisa paraleliza `search`; extrações Wikipedia e resolução de entidade seguem serial para manter cota e aceitação previsível.
- A regra de evidência rica é limiar estrutural, não prova semântica de cobertura. Fontes curtas ainda chamam planner; fonte longa que omite nuance pode ser classificada como suficiente.
- Cadeia etimológica não pode paralelizar seus elos: cada consulta seguinte depende da etimologia parseada no elo anterior.
- Downloads especulativos não passam do tamanho da janela selecionada; evita baixar todo candidato do funil.
