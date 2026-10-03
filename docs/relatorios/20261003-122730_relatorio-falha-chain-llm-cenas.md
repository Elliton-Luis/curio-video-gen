# Relatório — Falha do chain LLM no planejamento de cenas

- **Data:** 2026-10-03 12:27 (-03:00)
- **Tipo:** relatorio
- **Escopo:** diagnóstico e correção de Groq 429/400, espera NVIDIA sem timeout e fallback local ausente no modo automático
- **Commit(s):** pendente
- **Origem:** `output/history/20261003_imperio-otomano-como-surgiu-com/logs/run-20261003-134032-024526.jsonl`; relato do usuário

## 1. O que foi pedido

O planejamento visual ficou sem progresso depois de rate limit Groq e erro de
JSON. A geração precisa terminar ou cair para divisão local, nunca esperar
indefinidamente nem abortar vídeo automático com roteiro já pronto.

## 2. O que foi feito

| Arquivo | Mudança |
|---|---|
| `src/curio/stages/nvidia.py` | Todas as leituras HTTP usam timeout finito. A última tentativa NVIDIA usa timeout configurado, faz uma requisição e informa o limite. HTTP 429 lê `Retry-After` ou a espera textual; cada provider recebe no máximo duas tentativas 429, com espera máxima de 5 s. HTTP 400 JSON inválido elimina esse provider sem repetir. |
| `src/curio/stages/scenes.py` | Resposta nova usa `representations` como fonte das queries. Respostas antigas com `visual_search_terms` continuam aceitas. |
| `src/curio/stages/prompts.py` | Removida lista duplicada de queries do JSON pedido ao modelo; representações agora são fonte única. Reduz volume de completion. |
| `src/curio/pipeline.py` | Erro do chain no planejamento de cenas cai para divisão local tanto em geração automática quanto em roteiro pronto. Mantém narração literal e segue pipeline. |
| `README.md`, `config.example.toml` | Timeout finito, retry 429 e fallback de cenas documentados. |
| `tests/test_llm_fallback.py` | Chain com erros, timeout final limitado, providers posteriores e ausência de espera ilimitada. |
| `tests/test_llm_diagnostics.py` | Parsing de Retry-After, no máximo duas tentativas 429 e abandono imediato de espera longa. |
| `tests/test_llm_timeout.py` | NVIDIA deve receber timeout finito, incluindo valor padrão/configurado. |
| `tests/test_pipeline_integration.py` | Ideia em modo automático continua com divisão local se planner lança `NvidiaError`; teste confirma preservação integral da narração. |

## 3. Diagnóstico e evidências

O log original mostra a sequência:

1. Groq truncou JSON com `max_tokens=2000`; o Curio escalou para `4000`.
2. Groq respondeu `HTTP 429` duas vezes e depois `HTTP 400 json_validate_failed`.
3. Chain removeu Groq e tentou NVIDIA.
4. Fallback NVIDIA passou `timeout=None`; trace de SIGINT termina em `http.client.getresponse()` / `ssl.recv_into()`. A conexão ficou esperando resposta sem limite.
5. Mesmo quando o chain terminasse com erro, `pipeline.py` relançava `NvidiaError` no modo automático; divisão local só ocorria em roteiro pronto.

A execução foi interrompida com SIGINT. Log gravou `run_interrupted` / `KeyboardInterrupt`. O TUI continuou aberto para entrada; chamada HTTP bloqueada encerrou.

Verificações:

- `python3 -m pytest tests/ -x -q` — **780 passed**, 192,65 s.
- O teste focal final confirma que Groq `HTTP 400` leva a uma tentativa NVIDIA com timeout configurado; timeout NVIDIA termina sem retry ilimitado.
- O teste de integração confirma fallback local para o modo automático e narração preservada.
- `python3 -m py_compile` nos módulos afetados passou; `git diff --check` passou.

O prompt final de cenas não pede uma segunda lista `visual_search_terms`; queries
derivam de `representations`. O chain não ganhou provider nem chamada LLM.

## 4. Status vs requisitos do usuário

Falha corrigida no código e coberta por regressões. Nenhuma chamada API real foi
repetida depois da alteração; quota e estado atual dos providers não foram
assumidos. Não renderizei um vídeo novo. A suíte toda está verde.

## 5. O que falta

1. Execução real com roteiro pronto confirmou divisão local, narração preservada,
   mídia, TTS e render. O vídeo passou as oito verificações de `video-gen verify`.
2. A busca não encontrou imagens reais: Wikimedia respondeu erros HTTP e os
   providers Pixabay, Unsplash e Pexels estavam sem chaves. O vídeo usou 11
   visuais sintéticos. Revalidar mídia real quando rede e credenciais estiverem
   disponíveis.
3. CLIP real continua pendente; permanece opcional e desligado por padrão.

## 7. Validação real posterior

- Execução `from-script` reutilizou roteiro, título e pesquisa; planner LLM
  indisponível gerou 11 cenas locais e preservou o roteiro.
- Narração Edge TTS e render AV1/VA-API terminaram. Vídeo final:
  `output/history/20261003_imperio-otomano-como-surgiu-com/render/final.mp4`
- `video-gen verify --slug history/20261003_imperio-otomano-como-surgiu-com` —
  **8/8 verificações passaram**; 1080×1920, 63,8 s, áudio AAC e 34 blocos de legenda.
- Primeiro fechamento falhou ao salvar métricas porque o slug `history/<slug>`
  virou caminho de arquivo. `src/curio/metrics.py` agora troca barras por `_`;
  métricas de backfill foram geradas em `metrics/`.
- A execução real não produziu métricas de consumo completas: falha ocorreu após
  render, e backfill marca contadores indisponíveis.

## 6. Estado do checkout

Relatório, índice, código e testes seguem sem commit. O relatório da Fase 2 de
mídia permanece em `docs/relatorios/20261003-095825_relatorio-direcao-visual.md`.
