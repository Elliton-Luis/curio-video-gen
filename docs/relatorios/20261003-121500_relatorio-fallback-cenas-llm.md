# Relatório — Timeout e fallback no planejamento de cenas

- **Data:** 2026-10-03 12:15 (-03:00)
- **Tipo:** relatorio
- **Escopo:** encerrar espera ilimitada da NVIDIA, limitar retries HTTP 429 e recuperar geração automática com divisão local de cenas
- **Commit(s):** pendente
- **Origem:** `output/history/20261003_imperio-otomano-como-surgiu-com/logs/run-20261003-134032-024526.jsonl`; relato do usuário

## 1. O que foi pedido

Investigar por que Groq devolveu `HTTP 429`, depois `HTTP 400 json_validate_failed`,
e o processo continuou sem progresso. Corrigir causa arquitetural para que falha
de planejamento não paralise nem encerre uma geração automática já roteirizada.

## 2. Diagnóstico e mudanças

| Arquivo | Mudança |
|---|---|
| `src/curio/stages/nvidia.py` | Toda leitura HTTP agora tem timeout finito, inclusive `timeout=None` em chamadas internas. Última tentativa NVIDIA usa timeout configurado, faz uma chamada e imprime limite/progresso. HTTP 429 lê `Retry-After` ou espera do corpo, tenta no máximo duas vezes, espera no máximo 5 s e então troca de provider. HTTP 400 continua definitivo para aquele provider. |
| `src/curio/pipeline.py` | Falha do chain durante planejamento de cenas cai para divisão local em modo automático e roteiro pronto. A narração original permanece protegida pela validação existente. |
| `src/curio/stages/prompts.py` | Cenas geram `representations` como fonte única das queries. Removi segunda lista duplicada `visual_search_terms` do schema/prompt para reduzir a resposta JSON. Parser ainda aceita schema legado. |
| `README.md`, `config.example.toml` | Documentei timeout finito, retry curto em 429 e fallback local de cenas. |
| `tests/test_llm_fallback.py`, `tests/test_llm_diagnostics.py`, `tests/test_llm_timeout.py` | Cobrem timeouts finitos, resposta `Retry-After`, retries limitados, erro definitivo e encerramento após última tentativa NVIDIA. |
| `tests/test_pipeline_integration.py` | Geração automática continua para mídia/render com cenas locais se planner LLM falhar; todas as frases do roteiro ficam preservadas. |

## 3. Evidência

O log registra início da etapa de cenas em `2026-10-03T13:40:50Z`. Groq
devolveu JSON truncado com `max_tokens=2000`; escalada a `4000` recebeu dois
429 e depois `400 json_validate_failed`. Groq saiu do rodízio. O trace final
termina em `http.client.getresponse()` / `ssl.recv_into()` dentro de
`nvidia.py::_post_once`, porque o fallback passava `timeout=None` ao socket.
O processo esperou aproximadamente **51 minutos** até SIGINT. A chamada de
pipeline também relançava `NvidiaError` no modo de ideia, em vez de usar cenas
locais.

Após a correção:

- 429 com `Retry-After: 539.999999ms` espera aproximadamente **0,54 s**; segundo 429 encerra provider após a segunda tentativa.
- `Retry-After` maior que 5 s encerra provider sem dormir minutos.
- Fallback NVIDIA faz **uma** requisição com timeout finito; falha volta ao chain/pipeline.
- Se o chain acabar sem resposta JSON válida, modo automático segue com divisão local, tema anexado e narração literal.
- Prompt não pede queries duplicadas em dois campos. Tokens de completion diminuem; chamadas adicionais não foram introduzidas.

Testes:

- `python3 -m pytest tests/test_llm_fallback.py tests/test_llm_diagnostics.py tests/test_llm_timeout.py tests/test_pipeline_integration.py tests/test_visual_model.py -q` — **95 passed**.
- `python3 -m pytest tests/ -x -q` — **779 passed**, 179,15 s.
- `python3 -m py_compile` nos módulos LLM/pipeline/cenas — passou.
- `git diff --check` — passou.

O SIGINT enviado à execução antiga gravou `run_interrupted` com `KeyboardInterrupt`.
O processo `python3 -m curio` permaneceu no TUI aguardando interação; a chamada
HTTP bloqueada terminou.

## 4. Status vs requisitos do usuário

Atende: falhas de rate limit têm retries curtos; nenhuma chamada NVIDIA espera
sem limite; JSON inválido não bloqueia o vídeo; fallback conserva o roteiro e
continua o pipeline. Não adicionei providers nem serviços externos.

## 5. Limitações

- O endpoint NVIDIA pode usar todo timeout configurado, padrão atual de até 60 s na chamada de cenas. Depois desse limite, pipeline usa fallback local.
- Os erros 429 e 400 desta execução foram reproduzidos em testes por fixtures; o log original foi usado para verificar o trace bloqueado. Não repeti chamada LLM real nem consumo de quota.
- Fallback local preserva narração e tema, mas tem menos detalhe de intenção que resposta estruturada válida.

Relatórios da direção visual e progresso anterior permanecem em
`docs/relatorios/20261003-095825_relatorio-direcao-visual.md` e
`docs/relatorios/20261003-002807_relatorio-fase2-direcao-visual-parcial.md`.
Nenhum commit foi feito.
