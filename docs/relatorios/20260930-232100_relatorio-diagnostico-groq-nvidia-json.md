# Relatório — Diagnóstico de Groq, NVIDIA Lightning e JSON de cenas

- **Data:** 2026-09-30 23:21 (-03:00)
- **Tipo:** relatorio
- **Escopo:** verificar modelo Lightning/NIM, corrigir acesso Groq e diagnosticar a etapa JSON de cenas com evidências reais.
- **Commit(s):** implementação/testes/documentação pendentes.
- **Origem:** solicitação de diagnóstico focado NVIDIA/Groq após falha de cenas JSON.

## 1. O que foi pedido

Confirmar sem inventar o ID Lightning disponível no NIM; validar Groq com `https://api.groq.com/openai/v1` e `openai/gpt-oss-20b` sem presumir chave inválida; fazer request mínimo; depois repetir a etapa JSON de cenas, registrando `finish_reason`, budget solicitado, tokens gerados e tamanho da resposta. Não aumentar arbitrariamente `max_tokens`, retries ou timeout, e não reestruturar o chain.

## 2. O que foi feito e como

| Arquivo / área | Responsabilidade | Decisão e implementação |
|---|---|---|
| `src/curio/stages/nvidia.py` — NIM | ID Lightning | Usei a entrada existente `FUTURE_MODELS["scale"]` (`nvidia/nemotron-3.5-lightning-30b-a3b`) e confirmei o mesmo ID no endpoint autenticado `GET https://integrate.api.nvidia.com/v1/models` (HTTP 200). O teste Lightning foi temporário em runtime; default Nemotron e config persistente não foram trocados. |
| `src/curio/stages/nvidia.py` — Groq | Request/identidade | O endpoint já era formado corretamente como `{base_url}/chat/completions`, a base default já era a oficial e `Authorization: Bearer ...` estava correto. O Curio não enviava User-Agent; com `Python-urllib` o Cloudflare bloqueou o request. O cliente Groq agora envia `curio/0.2.0 (LLM API client)`, sem simular navegador. Erros Groq 4xx preservam status e mensagem real da API; o body é limitado a 1200 caracteres e a chave é redigida caso apareça. |
| `src/curio/config.py`, `config.example.toml`, `.env.example` | Modelo Groq | Atualizado o default para `openai/gpt-oss-20b` e documentados base/modelo oficiais. O `.env` local não tinha `GROQ_MODEL` nem `GROQ_BASE_URL`; portanto antes usava o default 120B e a base oficial por default. A chave local foi confirmada presente, mas nunca impressa. |
| `src/curio/stages/nvidia.py` — reasoning Groq | Consumo do budget de cena | GPT-OSS 20B consumiu quase todo o limite em reasoning sem produzir conteúdo. O request Groq para GPT-OSS agora envia o parâmetro documentado `reasoning_effort=low`; o max tokens do Curio permanece 2000/4000 e a temperatura/prompt não foram alterados. |
| `src/curio/stages/nvidia.py` — cenas | Diagnóstico de saída | Cada tentativa de `complete_json` registra `finish_reason`, `max_tokens` solicitado, `completion_tokens` quando disponível, chars e bytes. A segunda tentativa anuncia o budget de 4000 antes do request. O erro final distingue truncamento (`finish_reason=length`) de JSON inválido com geração encerrada (`finish_reason=stop`) e inclui os diagnósticos disponíveis. |
| `tests/test_llm_diagnostics.py` | Regressão | Testa ID/default, base Groq, Authorization/User-Agent/endpoint/body, preservação de erro 403, permanência do Groq no rodízio, finish reason, tokens, tamanho do JSON e o diagnóstico da segunda tentativa. |
| `README.md` | Documentação operacional | Atualizados Groq GPT-OSS 20B, User-Agent, reasoning low e diagnóstico JSON de cenas. |

## 3. Evidências, tentativas e erros

### ID NVIDIA Lightning

- `GET https://integrate.api.nvidia.com/v1/models` com a chave local em header Authorization respondeu **HTTP 200**.
- O catálogo retornou `nvidia/nemotron-3.5-lightning-30b-a3b`, igual ao ID já presente em `FUTURE_MODELS["scale"]`.
- O modelo foi usado por override temporário no diagnóstico. `NVIDIA_MODEL`/default persistente continuou `nvidia/nemotron-3-ultra-550b-a55b`.
- Uma chamada Lightning pelo caminho normal (timeout configurado em 15 s) expirou antes do body; nessa chamada não há `finish_reason` ou usage para registrar.

### Groq: chave, endpoint, modelo, header e body

1. Estado local consultado sem imprimir valores secretos: `GROQ_API_KEY` está configurada; `GROQ_MODEL` e `GROQ_BASE_URL` não estavam definidos no `.env`. O default antigo do Curio era `openai/gpt-oss-120b`; a base já era `https://api.groq.com/openai/v1`.
2. Request mínimo para `openai/gpt-oss-20b` pelo `urllib` padrão recebeu **HTTP 403**. A mensagem real da Cloudflare era `Error 1010: Access denied`, `browser_signature_banned`, com detalhe de bloqueio da assinatura do User-Agent — não erro de chave.
3. O mesmo endpoint/modelo com cliente `curl` e a mesma chave Bearer respondeu **HTTP 200**, confirmando a validade da chave. Com `max_completion_tokens=16`, retornou `finish_reason=length`, 16 completion tokens (9 reasoning tokens) e conteúdo vazio; esse budget mínimo é consumido pelo reasoning do GPT-OSS.
4. O mesmo body pipeline-like enviado por `urllib` com User-Agent identificando Curio (`max_tokens=2000`, temperatura 0.3, `response_format=json_object`) respondeu **HTTP 200**, `finish_reason=stop` e JSON válido. Isso isolou o 403 no User-Agent padrão, não em URL, endpoint, Authorization ou modelo.
5. Com o prompt completo de cenas e sem `reasoning_effort`, o Groq em JSON mode respondeu HTTP 400 `json_validate_failed` / `Failed to validate JSON`, `failed_generation` vazio. Sem `response_format`, o mesmo prompt usou **2000/2000 completion tokens**, dos quais **1998 eram reasoning**, e retornou `finish_reason=length` com zero chars. O limite estava sendo consumido por reasoning, não por uma incompatibilidade do header ou da base.
6. Com o parâmetro documentado `reasoning_effort=low`, a etapa real de cenas respondeu pelo provider `groq:openai/gpt-oss-20b`: `finish_reason=stop`, **1024 completion tokens**, **12 reasoning tokens**, **4415 chars / 4459 bytes**, JSON parseável. `build_chapters` rejeitou esse caso porque a narração gerada não reproduziu literalmente o roteiro (roteiro 2186 chars; junção das cenas 2175) e usou a divisão local, como determina o gate existente. Em um teste adicional menor, Groq produziu 3 cenas literais e retornou `source=groq`; portanto continua no rodízio e o gate existente segue ativo.

### NVIDIA: finish reason, tokens e tentativa estendida

- Com Lightning como único provider viável, a tentativa 1 pediu `max_tokens=2000` e retornou `finish_reason=length`, `completion_tokens=2000`, **7855 chars / 7954 bytes**. É truncamento real pelo limite solicitado, não apenas JSON sintaticamente inválido.
- `complete_json` solicitou a escalada existente para `max_tokens=4000`; não alterei o valor ou a política. No modo sem timeout, essa chamada não respondeu dentro de 180 s e foi encerrada pelo limite do harness; não houve body, `finish_reason` ou usage nessa resposta. Um request separado com o timeout normal de 15 s também terminou por timeout antes do body.
- O truncamento em 2000 também ocorreu no modelo Lightning, portanto não é específico do Nemotron atual. A causa exata do segundo request estendido não pode ser inferida sem resposta: o que foi observado foi latência/ausência de conclusão, não um segundo JSON inválido recebido.
- O modelo Nemotron original não foi chamado novamente nesta execução. O teste foi temporário e não alterou seu default persistente.

### Testes automatizados

```text
python -m compileall -q src/curio tests
python -m pytest -q -p no:cacheprovider
601 passed in 77.10s
```

Os testes direcionados de provider/modelo/JSON passaram; a suíte completa confirmou os mesmos comportamentos. Nenhuma chave foi exibida em terminal, log ou metadata.

## 4. Status vs PRD §19

Não há arquivo PRD no repositório para verificar §19. Os critérios desta solicitação foram cobertos por chamadas mínimas reais, execução real do estágio de cenas Groq e testes de regressão. A resposta Lightning foi observada no endpoint NIM; a segunda resposta estendida não foi concluída dentro da janela do diagnóstico.

## 5. Limitações

- Groq completa uma resposta JSON válida para o prompt de cenas com reasoning low, mas no roteiro São Jerônimo o gate literal rejeitou a paráfrase e caiu para divisão local. Não alterei prompts nem enfraqueci esse gate.
- A tentativa NVIDIA de 4000 tokens não forneceu body nem finish reason antes do limite de 180 s; não há evidência para afirmar o que a resposta teria sido se concluísse.
- Não rodei o pipeline inteiro: reproduzi a etapa `build_chapters` com o roteiro/fonte em cache, evitando pesquisa, TTS e render alheios ao diagnóstico.
