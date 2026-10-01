# Relatório — Auditoria de providers, ambiente e Mistral

- **Data:** 2026-10-01 03:18 -03:00
- **Tipo:** relatorio
- **Escopo:** sincronizar `.env` e `.env.example`, padronizar providers, integrar Mistral e validar endpoints com chamadas mínimas.
- **Commit(s):** pendente
- **Origem:** solicitação de auditoria de ambiente e integração Mistral.

## 1. O que foi pedido

Auditar variáveis ambientais usadas pelo código, remover ruído dos arquivos env, configurar cinco providers na ordem pedida, integrar Mistral no chain, diagnosticar Groq e validar cada endpoint sem executar pipeline completo.

## 2. O que foi feito e como

| Arquivo / área | Responsabilidade | Decisão e implementação |
|---|---|---|
| `.env` | Ambiente local | Mantive valores de chaves sem exibi-los; corrigi nomes de modelos/base, renomeei a variável Mistral para `MISTRAL_API_KEY`, removi comentários históricos, normalizei espaço inicial de Freesound e incluí variáveis opcionais vazias. |
| `.env.example` | Modelo suportado | Lista chaves LLM, modelos e bases para NVIDIA, Groq, OpenRouter, Mistral e Gemini; lista credenciais opcionais de mídia e contato Wikimedia. |
| `src/curio/stages/nvidia.py` | Chain LLM | Adicionei Mistral ao contrato OpenAI-compatible, ordem preferencial solicitada, mensagens HTTP 4xx úteis, defaults dos modelos pedidos e preservação da mensagem original em respostas Groq/Mistral. |
| `src/curio/config.py` | Configuração Mistral | Adicionei modelo/base ao config, sobrescrita ambiental e `llm_overrides()`. |
| `src/curio/cli.py`, `src/curio/tui.py` | Diagnóstico | Incluí Mistral em `doctor` e listagem de configuração TUI. |
| `config.example.toml`, `README.md` | Documentação operacional | Atualizei modelos, ordem, endpoint Mistral e comportamento de fallback. |
| `tests/test_llm_diagnostics.py`, `tests/test_llm_fallback.py`, `scripts/smoke.sh` | Regressão | Cobri request Mistral, configuração e nova ordem de fallback. |

## 3. Evidências, tentativas e erros

### Auditoria de variáveis

- `.env` era ignorado por `.gitignore:15`; `git check-ignore -v .env` confirmou regra ativa. `git ls-files --error-unmatch .env` confirmou que arquivo não é rastreado.
- O launcher `scripts/run.sh` carrega `.env` local sem sobrescrever variáveis já exportadas. O código Python lê `os.environ`; não há carregamento dotenv direto.
- Groq estava ausente de `GROQ_MODEL` e `GROQ_BASE_URL` no `.env`, embora o código suportasse ambos. Modelo de ambiente agora explicita `openai/gpt-oss-20b` e base oficial.
- OpenRouter usava modelo Gemini via OpenRouter em ambos envs, divergindo do modelo pedido.
- NVIDIA usava Nemotron antigo. Mistral estava como `MISTRA_AI_API_KEY`, nome que nenhum código lia.
- `FREESOUND_API_KEY` tinha espaço após `=`; o consumidor usa `.strip()`, mas normalizei o arquivo.
- `PEXELS_API_KEY`, `CURIO_CONTACT` e campos de provider estavam omitidos. Pexels e contato agora constam sem valor; contato permanece opcional.
- `.env.example` anterior descrevia várias variáveis opcionais e configurações TOML. Estas seguem suportadas no código; o exemplo agora prioriza chaves, modelos e integrações de ambiente relevantes, sem comentários históricos. Configurações de pipeline continuam em `config.example.toml`.
- `NVIDIA_API_KEYS` e `GOOGLE_API_KEY` continuam aliases suportados pelo código. Não adicionei aliases ao exemplo para evitar configuração duplicada.

### Diagnóstico Groq e chamadas mínimas

Cada provider recebeu uma chamada única em `{BASE_URL}/chat/completions`, com Bearer e `max_tokens=16`. Nenhum retry ou pipeline foi executado.

| Provider | Resultado observado | Diagnóstico |
|---|---|---|
| NVIDIA | HTTP 410: modelo `meta/llama-3.3-70b-instruct` encerrou em 2026-08-26 | Endpoint respondeu; modelo pedido está indisponível no NIM. Provider será removido pelo erro definitivo e fallback segue. |
| Groq | HTTP 200; `finish_reason=length`, zero caracteres | Base, endpoint e autenticação funcionam. Budget de 16 tokens é insuficiente para GPT-OSS produzir conteúdo; integração Curio já usa `reasoning_effort=low` e budget maior, sem chamada extra nesta auditoria. |
| OpenRouter | HTTP 404: modelo indisponível no plano gratuito; API sugeriu slug pago sem `:free` | Chave/endpoint alcançaram API; slug solicitado não está disponível grátis. Mantive modelo exato pedido. |
| Mistral | HTTP 429 `Rate limit exceeded`, código `1300` | Endpoint recebeu request em formato Chat Completions e retornou erro da API. Sem resposta de sucesso; não repeti chamada para evitar custo/limite. |
| Gemini | HTTP 200; `finish_reason=length`, zero caracteres | Endpoint e autenticação responderam; limite de 16 tokens encerrou geração antes de texto. |

Groq 403 anterior foi atribuído ao bloqueio Cloudflare do User-Agent `Python-urllib` (`browser_signature_banned`), não a chave inválida. Código já envia User-Agent identificável, Bearer e endpoint oficial. Erros Groq preservam body e status; nunca registram chave.

### Testes

```text
python -m pytest -q -p no:cacheprovider tests/test_llm_diagnostics.py tests/test_llm_fallback.py tests/test_llm_timeout.py
29 passed in 0.09s

python -m compileall -q src/curio tests
sucesso

python -m pytest -q -p no:cacheprovider
605 passed in 75.29s

./scripts/smoke.sh
86 passaram, 2 falharam (consultas offline e formatação Archivo Black)
```

As duas falhas do smoke são checagens pré-existentes sem relação com providers; ambas já constam em relatório anterior.

## 4. Status vs PRD §19

Não há PRD no repositório para verificar §19. Contrato Mistral, ordem, configuração, proteção de segredos e respostas HTTP foram cobertos por testes e chamadas mínimas.

## 5. Limitações

- NVIDIA modelo pedido responde HTTP 410; OpenRouter responde que slug gratuito não está disponível; Mistral respondeu HTTP 429. São limitações atuais dos serviços, não foram mascaradas com troca de modelo ou retries.
- As chamadas de Groq e Gemini usaram `max_tokens=16`, suficientes para validar API, insuficientes para avaliar qualidade textual.
- Smoke manteve duas falhas conhecidas e não relacionadas: consulta offline de contexto e formato Archivo Black.
- Não executei pipeline completo. Falta validar resposta de sucesso Mistral após janela de rate limit e disponibilidade futura dos modelos NVIDIA/OpenRouter pedidos.
