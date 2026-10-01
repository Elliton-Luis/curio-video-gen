# Relatório — Log persistente de execução

- **Data:** 2026-10-01 04:32 -03:00
- **Tipo:** relatorio
- **Escopo:** registrar eventos concisos de execução em CLI/TUI e JSONL desde startup, inclusive em falha/interrupção.
- **Commit(s):** `e52a236` (`feat(observability): persist pipeline run logs`)
- **Origem:** solicitação para melhorar observabilidade sem substituir metrics.

## 1. O que foi pedido

Mostrar progresso útil e curto durante etapas, persistir diagnóstico antes de metrics, reter evidência de falha/interrupção, evitar segredos/prompts e preservar métricas existentes.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Implementação |
|---|---|---|
| `src/curio/runlog.py` | Logger pequeno | JSONL por execução em `output/<slug>/logs/`; flush por evento; contexto ativo; redação de secrets e omissão de campos prompt/response/payload. |
| `src/curio/pipeline.py` | Ciclo de vida | Abre log antes do pipeline e antes de metrics; grava etapa/provider/fallback/contagens/warnings, conclusão, standby, falha e interrupção; guarda path em metadata. Aplicado também a `from-script` e `finalize`. |
| `src/curio/stages/nvidia.py`, `research.py`, `entity.py`, `scenes.py`, `script.py`, `tts.py`, `visual.py` | Eventos de operação | Provider/modelo, retries, timeout/fallback, pesquisa, validação de cenas, mídia por cena, download, TTS e fallback local. Prompts e respostas completas não entram no log. Prints longos ligados a estes eventos ficam para chamadas sem logger. |
| `src/curio/cli.py`, `tui.py`, `queue.py` | Terminal e segurança | Mostram eventos curtos, passam callback em fluxo individual/fila/finalização, tratam `KeyboardInterrupt` e sanitizam erros exibidos. |
| `tests/test_runlog.py`, `tests/test_llm_fallback.py`, `tests/test_pipeline_integration.py` | Regressão | Cobrem startup antes do trabalho, sucesso, falha sem metrics final, interrupção, redação de secrets, TUI concisa, fallback provider e contexto em worker de busca. |
| `README.md`, `docs/README.md` | Operação/documentação | Documentam localização, formato e distinção entre log e metrics; índice aponta este relatório. |

## 3. Métricas e evidências

Consultei primeiro metrics disponíveis. Execução mais recente observada: `metrics/20261001-040048_fale-sobre-a-historia-e-importancia-de-s.json`.

- duração total: 240,35 s; pesquisa 27,68 s; roteiro 16,17 s; cenas 16,93 s; mídia 79,17 s; TTS 12,16 s; legendas 0,02 s; render 72,30 s;
- provider/modelo: `groq:openai/gpt-oss-20b`; 4 chamadas LLM, 4608 prompt tokens, 2022 completion tokens;
- mídia: 87 queries, 169 resultados normalizados, 132 score rejections, 0 acima do threshold 34, 0 downloads, 11 sintéticos;
- TTS: Edge TTS `pt-BR-AntonioNeural`; 55 cues; render `arc` / `av1_vaapi`.

Estes valores justificam eventos de pesquisa, fallback, mídia, TTS e render. Não executei pipeline vivo nem chamadas API para validar logger. Propaguei contexto do logger ao worker de busca para registrar retries internos do provider Wikimedia.

### Testes focados

```text
python -m pytest -q -p no:cacheprovider tests/test_runlog.py tests/test_llm_fallback.py tests/test_pipeline_integration.py tests/test_research.py tests/test_tts_coverage.py tests/test_visual_strategies.py tests/test_media_funnel.py tests/test_media_diag.py tests/test_media_waterfall.py
133 passed in 40.91s
```

Teste da integração completa também verifica que JSONL começa antes do trabalho, lista etapas e termina em `run_completed`.

### Suíte completa

```text
python -m pytest -q -p no:cacheprovider
615 passed in 79.54s
python -m compileall -q src/curio tests
git diff --check
```

Comandos focados após adicionar eventos de retry/download:

```text
python -m pytest -q -p no:cacheprovider tests/test_media_diag.py tests/test_media_funnel.py tests/test_media_providers.py tests/test_runlog.py tests/test_llm_fallback.py tests/test_pipeline_integration.py
60 passed in 37.61s

python -m pytest -q -p no:cacheprovider tests/test_runlog.py tests/test_visual_strategies.py tests/test_media_waterfall.py tests/test_media_providers.py
81 passed in 4.40s

python -m pytest -q -p no:cacheprovider tests/test_runlog.py tests/test_llm_fallback.py tests/test_pipeline_integration.py tests/test_media_diag.py tests/test_media_funnel.py
49 passed in 38.18s
```

A primeira suíte completa encontrou um teste no ramo de cenas sem provider que usava `run_event` antes do import local. Movi import para início da função; suite passou. Um teste focado também revelou mocks de `_fetch(url)` incompatíveis com novo argumento opcional de provider; atualizei mocks sem mudar lógica e testes passaram.

## 4. Segurança e persistência

- Log começa em `output/<slug>/logs/run-<timestamp>.jsonl` ou `finalize-<timestamp>.jsonl`, antes da pesquisa e validação de finalize.
- Cada linha contém timestamp UTC, run ID, slug, etapa, evento, mensagem curta e detalhes; cada evento chama `flush()`.
- `KeyboardInterrupt` grava `run_interrupted` e fecha/flush antes de propagar. Falhas registram tipo, mensagem e traceback sanitizado.
- Secrets presentes em ambiente, Bearer, query parameters e campos de credenciais são removidos. Campos com `prompt`, `response`, `payload` ou `messages` são omitidos. CLI/TUI limitam resumo de erro/evento para não despejar URL/payload longo.
- Metrics permanecem intactas e continuam fonte de quantidades/custo. Log responde ao estado e motivo operacional.

## 5. Status vs PRD §19

Não há PRD no repositório para conferir §19. Critérios observáveis foram cobertos por testes de logger e integração pipeline.

## 6. Limitações

- Uma morte forçada do processo/host (`SIGKILL`/perda de energia) não executa `finally`; cada evento anterior já está flushado.
- Log por execução usa output do projeto e não substitui metrics; consumidores que chamam pipeline sem TTY/callback ainda gravam JSONL, mas não recebem impressão de eventos no terminal.
- Não alterei a lógica editorial, escolha de provider, filtros, geração, retry ou thresholds.
