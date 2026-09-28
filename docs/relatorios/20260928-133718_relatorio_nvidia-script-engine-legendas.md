# Relatório — NVIDIA Script Engine + legendas legíveis

- **Data:** 2026-09-28 13:37 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** roteiros via NVIDIA API (Nemotron 3 Ultra) + correção visual das legendas
- **Commit(s):** `5b7fc6e` (integração base) + commit de correção/diagnóstico desta etapa
- **Origem:** tarefa "NVIDIA Script Engine + Legendas Legíveis" + backlog item 6 (fonte escalada)

## 1. Objetivo

Trocar o roteiro curado/template pelo roteiro gerado na NVIDIA API para ideias
livres, preparar config para N chaves (sem rotação) e deixar as legendas
menores, na parte inferior e em blocos curtos — sem reescrever o pipeline.

## 2. Estado anterior

`generate_script` usava base curada (2 temas) → hook LLM genérico silencioso
(`except: return None`) → template. Legendas: SRT queimado via `force_style`
com `FontSize=64` absoluto e blocos de até 7 palavras/42 chars.

## 3. Mudanças realizadas

| Arquivo | Mudança |
|---|---|
| `src/curio/stages/nvidia.py` (novo) | Client NVIDIA (stdlib/urllib, OpenAI-compat), `NvidiaCredentials` (1..N chaves, usa a 1ª; `rotate()` levanta `NotImplementedError`), `NvidiaError` com mensagens por status (401/403, 404, 429, 5xx, timeout, conexão) sem vazar a chave, prompt editorial com formato de saída rígido, token budget 1500 + 1 escalada a 3000 se truncar, `_sanitize` anti-roteiro-de-cena |
| `src/curio/stages/script.py` | Com chave: NVIDIA autoritativa (falha explícita, sem fallback silencioso). Sem chave: curado → template (offline intacto) |
| `src/curio/config.py`, `config.example.toml` | Bloco `[nvidia]` (base_url, model, timeout) + env `NVIDIA_MODEL/BASE_URL/TIMEOUT`; chave nunca entra no config (lida via `NvidiaCredentials`) |
| `src/curio/cli.py` | `except NvidiaError` → `ERRO na etapa 'NVIDIA'` com motivo + retry; `doctor` informa chave/modelo sem chamada de rede |
| `src/curio/stages/subs.py` | Quebra por frases + blocos ≤5 palavras/36 chars; gera **SRT + ASS** dos mesmos cues (mesma sincronia) |
| `src/curio/stages/render.py`, `pipeline.py` | Queima o `.ass` (sem `force_style`); `subtitles_ass` nos artefatos/metadata |
| `.env.example` / `.env` (gitignored) / `run.sh` | `.env` espelha o example; `run.sh` carrega `.env` sem sobrescrever shell (shell > `.env` > toml) |
| `README.md` | Seção NVIDIA API |

## 4. Decisões técnicas

- **Sem SDK**: `urllib` basta para um POST; zero deps (regra do MVP).
- **Chave fora do config/metadata**: `NvidiaCredentials.from_env()` no ponto de
  uso; `grep nvapi-` nos outputs confirma ausência de vazamento.
- **Falha explícita com chave, fallback só sem chave**: preserva o offline e
  nunca esconde erro da API.
- **ASS em vez de `force_style`**: diagnóstico visual provou a causa raiz —
  sem `PlayRes`, o libass assume 384×288 e multiplica fonte (≈2,8×) e desloca
  a margem para o centro/topo. Com `PlayRes=1080×1920`, fonte e `MarginV` são
  pixels reais: base 68, `MarginV=200`, `Alignment=2`.

## 5. Configuração NVIDIA e múltiplas chaves

```bash
NVIDIA_API_KEY="nvapi-..."                 # única (suficiente)
NVIDIA_API_KEYS="key1,key2,key3"           # futuro: aceita, USA A 1ª
NVIDIA_MODEL=nvidia/nemotron-3-ultra-550b-a55b
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_TIMEOUT=60
```

**Rotação/sorteio/fallback/retry entre chaves NÃO implementados** (escopo
proibido). `NvidiaCredentials.rotate()` falha alto de propósito; sem chamadas
paralelas. Modelos irmãos (`super-120b`, `lightning-30b`) registrados como
constante `FUTURE_MODELS` só para referência.

## 6. Testes executados (todos reais, sem mock)

1. **Ideia curta** — `generate "De onde veio a palavra doença?" --force`:
   roteiro NVIDIA limpo (526 chars, sem "Você sabia que", sem markdown),
   áudio 45,58 s, vídeo 46,4 s, `verify` **8/8**, tempo 32,94 s.
2. **Ideia complexa** — `"Por que o ano tem 12 meses e quem decidiu isso?"`:
   roteiro correto (10 meses romanos, César+Sosígenes, 45 a.C., bissexto),
   vídeo 46,3 s, `verify` **8/8**, tempo 24,34 s.
3. **Cache** — reexecução com `NVIDIA_API_KEY` inválida: sucesso em **0,23 s**,
   `render: cache` (prova de zero chamadas à API).
4. **Falha simulada** — `NVIDIA_BASE_URL=http://127.0.0.1:9`: `ERRO na etapa
   'NVIDIA'`, exit 1, zero consumo.
5. **Inspeção visual** — frames extraídos e lidos: legenda pequena na base
   ("do corpo ou da alma."), título no topo, centro livre. Comparado ao frame
   antigo (texto gigante centralizado), o problema está resolvido.
6. **Diagnóstico de formato** — 3 chamadas de sonda: confirmado
   `message.content` = resposta, `message.reasoning_content` = raciocínio.

Modelo nos testes: `nvidia/nemotron-3-ultra-550b-a55b` (principal escolhido).
Consumo total da etapa: ~5 chamadas (3 sondas + 2 gerações).

## 7. Problemas encontrados (com causa e correção)

1. **Roteiro com o "prompt da IA"** (reportado pelo usuário): o `script.txt`
   continha o raciocínio do modelo ("The user wants...") em vez da narração.
   Causa dupla: `max_tokens=500` insuficiente para modelo de raciocínio
   (raciocínio consome o orçamento) + prompt sem proibir formato de roteiro de
   cena. Correção: budget 1500 (+escalada a 3000), formato de saída rígido no
   prompt, `_sanitize` remove `<think>`, cercas, `[rubricas]`, `Narrador:` e
   preâmbulos; resposta <100 chars após limpeza vira `NvidiaError` (retry).
   Reprodução com `max_tokens=500` também revelou markdown/`[Cena]`/`Narrador:`
   — mesma correção cobre.
2. **HTTP 500 transitório** numa sonda: retry manual passou. Sem ação no código
   (erros 5xx já têm mensagem + retry).
3. **Legendas gigantes mesmo após reduzir para 44**: causa raiz era o
   `PlayRes` padrão 384×288 do libass (ver §4). Corrigido com ASS explícito.
4. **Vídeos antigos sumiram de `output/`** entre sessões (dir gitignored):
   sem impacto no código; artefatos de teste são descartáveis por desenho.

## 8. Limitações restantes

- Voz espeak-ng segue robótica (backlog: Piper).
- Sincronia ainda proporcional (sem alinhamento por palavra).
- Sem pesquisa/fontes: a honestidade do roteiro depende do modelo + prompt;
  validador editorial automático continua pendente (backlog item 3).
- Sanitize é heurístico: um modelo muito criativo no formato pode exigir
  ajuste das regexes (o guarda de <100 chars garante falha visível, não lixo).
- Sem batch/paralelismo (fora de escopo, PRD §20).

## 9. Impacto no PRD

- §6 (roteiro): deixa de depender só do curado — ideia livre vira roteiro real.
- §7 (pesquisa): continua futura; prompt exige honestidade sobre incerteza.
- §8/§11: TTS e render intocados; §12/§19: cache prova zero rechamadas;
  §18: config estendida sem segredos no repo; §2 (editorial): roteiros
  gerados verificados manualmente nos 2 testes (sem clickbait/fake).
- Critério final da tarefa: `ideia → NVIDIA → roteiro → TTS → legendas
  menores na base → FFmpeg → 9:16 ~45 s com áudio` — **atingido nos 2 vídeos**.

## 10. Próximos passos recomendados

1. Validador editorial automático (backlog item 3) — barato e reduz risco §7.
2. Piper TTS (backlog item 1) — maior gargalo de retenção restante.
3. Quando houver 2ª chave: implementar seleção explícita (ainda sem
   rotação automática) — o `NvidiaCredentials` já comporta.
