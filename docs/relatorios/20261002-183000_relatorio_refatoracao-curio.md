# Relatório — Refatoração estrutural do Curio

- **Data:** 2026-10-02 18:30 (UTC)
- **Tipo:** relatorio
- **Escopo:** etapas 1–5 da auditoria: limpeza, fontes únicas, adapters, responsabilidades e performance
- **Commit(s):** `2afe77b`, `5985a65`, `2c25cc5`, `3c93b7f`, `beb0653`, `4b106d9`, `2968972`, `b98d3ee`, `3a07e64`, `2c7e38b`
- **Origem:** `docs/analises/20261002-131932_analise_refatoracao-codigo-morto.md`

## 1. O que foi pedido

Refatorar incrementalmente, preservar produto, manter testes verdes e
registrar relatório de cada entrega. Um pipeline, adapters declarativos,
fontes gerais e especialistas, performance só depois da estrutura.

## 2. O que foi feito

| Etapa | Resultado | Commit |
|---|---|---|
| 1. Limpeza | Removidos símbolos/imports confirmados mortos, `NotImplementedError` inutilizado e no-op; testes migrados antes de remover gates quase-mortos. | `2afe77b` |
| 2. Fonte única | `textnorm.py`; um gate de mídia; piso de dimensão único; `ResearchResult` explícito; licença estruturada em fontes. | `5985a65`, `2c25cc5` |
| 3. Responsabilidades | Prompts em `stages/prompts.py`; terminal em `tui_terminal.py`; timeline/SFX em `visual_timeline.py`; render silencioso/transições em `pipeline_render.py`; pesquisa em `pipeline_research.py`; TTS/timing/legendas em `pipeline_audio.py`; mídia manual/legacy/standby em `pipeline_media.py`. | `3c93b7f`, `4b106d9`, `2968972`, `3a07e64`, `2c7e38b` |
| 4. GenreAdapter | Seis adapters declaram ritmo, direção, mídia, fontes especialistas, providers, transição, música e SFX. Registry de conectores especialistas executa fora dos adapters. Etimologia usa Wiktionary/Logeion/Perseus; fontes gerais continuam ativas. | `beb0653` |
| 5. Performance | Busca e download limitados/concorrentes; timeout retorna sem esperar shutdown; ffprobe cacheado; resultados de busca repetidos compartilhados no vídeo; Logeion/Perseus paralelos; planner LLM omitido para evidência rica. | `b98d3ee` |

O pipeline mantém ordem única: pesquisa, roteiro, cenas, mídia, áudio,
render. Adapters guardam dados/políticas; nenhuma chamada HTTP, LLM,
download ou FFmpeg roda dentro deles.

## 3. Evidências

- Suíte completa: `python3 -m pytest tests/ -q` — **728 passed**.
- Contratos testados: adapters declaram fontes registradas e políticas de áudio/transição; fontes especialistas coexistem com Wikipedia; `Barrier` prova concorrência limitada de busca/download; resultados mantêm ordem determinística; timeout não bloqueia o chamador; busca igual em cenas distintas reutiliza resultados; cache de ffprobe invalida com alteração de tamanho/mtime; pesquisa rica pula chamada LLM de lacunas.
- Módulos resultantes: `visual.py` 1.258 linhas; `visual_timeline.py` 268; `pipeline.py` 1.543; `pipeline_research.py` 90; `pipeline_audio.py` 124; `pipeline_media.py` 190; `pipeline_render.py` 149; `tui.py` 1.307; `tui_terminal.py` 220; `nvidia.py` 1.106; `prompts.py` 397.

Commits de implementação, na ordem:

1. `2afe77b refactor(etapa1): remove codigo morto, imports mortos e no-op`
2. `5985a65 refactor(etapa2a): textnorm como fonte unica de normalizacao e stopwords`
3. `2c25cc5 refactor(etapa2b): gate unico de midia, piso unico e ResearchResult explicito`
4. `3c93b7f refactor: move editorial prompts to prompts module`
5. `beb0653 refactor: centralize genre adapters and source registry`
6. `4b106d9 refactor: separate terminal mechanics from TUI flows`
7. `2968972 refactor: separate pipeline render and visual timeline stages`
8. `b98d3ee perf: bound and parallelize pipeline network work`
9. `3a07e64 refactor: isolate narration timing and subtitle stage`
10. `2c7e38b refactor: isolate media acquisition and standby stage`

## 4. Status vs PRD §19

Produto, formatos, CLI/TUI e custo operacional preservados. Nenhuma
dependência paga ou pacote novo. Fontes especializadas permanecem
complementares, nunca exclusivas. TUI segue stdlib only.

## 5. Limitações e decisões preservadas

- `nvidia.py` ainda é grande, mas agora tem uma responsabilidade: client e
  chain LLM. Todo prompt editorial saiu. Dividir transporte/provedor exige
  novo contrato e não reduz comportamento nem custo por si só.
- `pipeline.py` ainda coordena metadados/cache e pontos de encontro entre
  estágios. Pesquisa, mídia, áudio, render e timeline têm donos separados;
  não criei pipeline paralelo nem camada de estado genérica.
- `tui.py` ainda tem fluxos de negócio; entrada, teclado, menus e file
  browser já estão isolados em `tui_terminal.py`.
- `diagram.render_strip_diagram` e `visuals.render_diagram` ficam separados:
  um desenha tira de teste com componentes fixos; outro desenha processos
  arbitrários. São produtos visuais diferentes, não duplicatas idênticas.
- Timeout Python não mata thread em execução. Socket timeout do provider
  encerra worker; executor limita workers e o chamador não aguarda shutdown.
- Cache de queries seleciona resultados entre cenas só durante a execução;
  cache em disco continua guardando assets selecionados por consulta.
- Etimologia segue cadeia de elos serialmente por dependência; somente
  consultas independentes Logeion/Perseus rodam em paralelo.
- Fontes externas podem falhar, vir vazias ou não corresponder ao tema;
  o gate mantém a decisão de relevância e fontes gerais continuam fallback.
