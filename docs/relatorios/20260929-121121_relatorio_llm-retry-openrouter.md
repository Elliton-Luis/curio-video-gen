# Relatorio — retry 5× no LLM + fallback OpenRouter

- **Data:** 2026-09-29 12:11 (-03)
- **Tipo:** relatorio
- **Escopo:** robustez da etapa LLM (roteiro e cenas): 5 tentativas com backoff + fallback automático OpenRouter
- **Commit(s):** pendente
- **Origem:** pedido do usuário após timeout da NVIDIA sem retry nem explicação ("nem sei pq falhou")

## 1. O que foi pedido

1. A etapa LLM deve tentar **5 vezes** antes de desistir (antes: 1 tentativa, qualquer timeout virava erro final).
2. Adicionar **fallback da OpenRouter** (usuário já tem a chave).
3. Implícito: o erro precisa dizer **por que falhou** (o que foi tentado, quantas vezes, o que fazer).

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `src/curio/stages/nvidia.py` | retry + fallback | `_post_once` (1 tentativa, marca `retryable`) + `_post_with_retries` (até N=5, backoff 2/4/8/16 s, só repete timeout/conexão/429/5xx; 401/403/404 falham direto) + `_chat` (NVIDIA → OpenRouter) retornando `(body, "provedor:modelo")` |
| `src/curio/stages/nvidia.py` | credenciais fallback | `OpenRouterCredentials` (só `OPENROUTER_API_KEY`); sem chave, provedor é pulado (`_Skipped`) e o erro final explica como habilitá-lo |
| `src/curio/stages/script.py` | proveniência | `script_source` agora é o rótulo real (`nvidia:…` ou `openrouter:…`) em vez de assumir NVIDIA |
| `src/curio/stages/scenes.py` | proveniência | `scenes_source` real (`nvidia` \| `openrouter` \| `local`); aviso de divergência literal cita o provedor que serviu |
| `src/curio/config.py` | config do fallback | `openrouter_model` (padrão `google/gemini-2.5-flash`, escolha do usuário) + `openrouter_base_url`; precedência CLI > env > `config.toml` > padrão, igual à NVIDIA |
| `src/curio/cli.py` | diagnóstico | `doctor` mostra status do OpenRouter; hints de `NvidiaError` viraram "tentativas esgotadas, verifique chaves/modelos" |
| `.env.example`, `config.example.toml` | documentar chaves | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `CURIO_LLM_ATTEMPTS` (1–10, padrão 5) |
| `scripts/smoke.sh` | testes offline | seção 7 (5 cheques, `urlopen` simulado, sleep anulado): retry 2×+sucesso, 401 sem repeat, esgotamento com contagem, fallback assume, erro sem chave explica |

Não-regressão deliberada: sem `OPENROUTER_API_KEY`, o comportamento é idêntico ao anterior + retries (gerador local continua quando não há chave NVIDIA; divisão local do modo roteiro-pronto inalterada).

## 3. Evidências

```text
$ ./scripts/smoke.sh
40 passaram, 0 falharam.   # era 35; +5 novos (retry, 401, esgotamento, fallback, erro)

$ ./scripts/run.sh doctor
[OK] NVIDIA API — chave configurada (1 configurada(s), usa a 1ª)
[--] OpenRouter (fallback LLM) — sem chave (sem fallback; defina OPENROUTER_API_KEY)
```

Teste de fallback simulado (seção 7 do smoke): NVIDIA com timeout ×5
(`CURIO_LLM_ATTEMPTS` respeitado: com `=3`, exatamente 3 chamadas e erro
"após 3 tentativas") e OpenRouter assumindo na 6ª chamada com rótulo
`openrouter:or-model`. Chaves nunca aparecem nas mensagens (só no header
`Authorization`, nunca logado).

Sem validação live ponta a ponta: o `.env` local não tem
`OPENROUTER_API_KEY` ainda (usuário adiciona) e a NVIDIA real estava com
timeout de 60 s no momento (5 tentativas × 60 s ≈ 5 min — motivo extra
para adicionar a chave de fallback).

## 4. Status vs PRD §19

Sem impacto nos 8 cheques de vídeo (mudança só na etapa LLM, antes do
TTS). Proveniência (`script_source`, `scenes_source`, métricas
`nvidia.calls` com rótulo do provedor) melhora a rastreabilidade sem
quebrar o formato do `metadata.json`.

## 5. Limitações

- Fallback só cobre a etapa LLM (roteiro/cenas). Queda do Edge TTS ou do
  Wikimedia continua com os fallbacks próprios já existentes (espeak-ng,
  reuso/gradiente) — sem mudança aqui.
- Rotação entre chaves (`NVIDIA_API_KEYS`) continua não implementada;
  vale uma `melhoria` futura junto com fallback TTS secundário.
- Pior caso continua lento: 5 timeouts longos na NVIDIA antes do
  fallback. Mitigação documentada: `NVIDIA_TIMEOUT` menor e/ou
  `CURIO_LLM_ATTEMPTS` menor (ex.: 3).
