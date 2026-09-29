# Relatorio — chain LLM de 4 provedores em rodízio + .env organizado

- **Data:** 2026-09-29 14:29 (-03)
- **Tipo:** relatorio
- **Escopo:** Gemini direto e Groq no chain (rodízio intercalado com levantamento final) + limpeza do `.env`/`.env.example`
- **Commit(s):** pendente
- **Origem:** pedido do usuário (novos providers; retry intercalado N→OR→N→Gemini→N→Groq; levantamento se ninguém responder; env organizado)

## 1. O que foi pedido

1. Novos providers LLM: Gemini (2.5 flash) e Groq (gpt-oss 120B); usuário
   coloca as chaves.
2. Retry intercalado: NVIDIA falhou 1x → já troca; rodízio
   N→OpenRouter→N→Gemini→N→Groq.
3. Se nenhum responder, fazer um levantamento (o que foi tentado/onde parou).
4. Organizar `.env` e `.env.example` (enxutos; valores do `.env` preservados).

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `stages/nvidia.py` | chain genérico | `PROVIDER_SPECS` + `PROVIDER_ORDER` (nvidia→openrouter→gemini→groq); todos OpenAI-compatíveis (Gemini via `/v1beta/openai`); `_rotation()` intercala NVIDIA entre fallbacks; erro definitivo (401/403/404) elimina do rodízio; budget total `CURIO_LLM_ATTEMPTS` (padrão 6) |
| `stages/nvidia.py` | levantamento | `_survey()`: tentativas por provedor + últimos erros + chaves ausentes + próximos passos; `GeminiCredentials`/`GroqCredentials` (2ª env alternativa p/ Gemini: `GOOGLE_API_KEY`) |
| `stages/script.py`, `stages/scenes.py` | gates | `any_llm_available()` (qualquer chave habilita LLM); `generate_script` sem exigir chave NVIDIA; `extra=cfg.llm_overrides()` |
| `config.py`, `config.example.toml` | modelos/base | `gemini_*`, `groq_*` (arquivo + env); `llm_overrides()` |
| `cli.py` | doctor | 4 linhas de status do chain |
| `.env.example`, `.env` | organização | 44/43 → ~35 linhas: chaves juntas, modelos juntos, comentários redundantes removidos; valores reais do `.env` preservados byte a byte + slots vazios `GEMINI_API_KEY`/`GROQ_API_KEY` |
| `scripts/smoke.sh` | testes | seção 7 reescrita (rodízio, ordem exata N,OR,N,Gem,N,Groq, eliminação no 401, Gemini sozinho, sem-chave); 77 cheques |

Proveniência automática: rótulos `gemini:…`/`groq:…` em `script_source`,
`scenes_source` e métricas, sem mudar callers além do `extra`.

## 3. Evidências

```text
$ ./scripts/smoke.sh  →  77 passaram, 0 falharam (era 73).
$ ./scripts/run.sh doctor
[OK] NVIDIA (LLM) — chave configurada (nvidia/nemotron-3-ultra-550b-a55b)
[OK] OpenRouter (LLM) — chave configurada (google/gemini-2.5-flash)
[--] Gemini (LLM) — sem chave (pula no rodízio; defina GEMINI_API_KEY)
[--] Groq (LLM) — sem chave (pula no rodízio; defina GROQ_API_KEY)
Levantamento real (6 timeouts simulados): "LLM indisponível após 6/6
tentativa(s) | NVIDIA: 3 tentativa(s), último erro: … | OpenRouter: 1 …
| Gemini: 1 … | Groq: 1 … | Defina/renove as chaves…"
```

Sem validação live de Gemini/Groq: chaves ainda não cadastradas (usuário
vai colocar); transporte idêntico ao OpenRouter já provado + testes
mockados cobrem ordem, eliminação e rótulos.

## 4. Status vs PRD §19

Sem impacto (etapa LLM anterior ao TTS; `metadata.json` ganha rótulos
novos sem quebrar formato).

## 5. Limitações

- Ordem do chain fixa (sem prioridade configurável) — YAGNI por ora.
- Gemini via camada OpenAI-compatível do Google (não `generateContent`
  nativo): mesma forma de resposta, sem código extra.
- `gpt-oss-120b` é modelo de raciocínio: escalada de tokens existente
  cobre truncamento; comportamento real só com a chave.
