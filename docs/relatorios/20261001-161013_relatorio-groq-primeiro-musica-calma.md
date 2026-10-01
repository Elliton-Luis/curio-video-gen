# Relatório — Groq primeiro e camas musicais calmas

- **Data:** 2026-10-01 16:10 -0300
- **Tipo:** relatorio
- **Escopo:** ordem/timeout dos providers e seleção de música ambiente não intrusiva.
- **Commit(s):** pendente
- **Origem:** pedido para dar tempo ilimitado à NVIDIA e evitar música ruidosa.

## 1. O que foi pedido

Tentar Groq antes da NVIDIA; deixar NVIDIA sem limite de espera por resposta; remover NVIDIA do rodízio após HTTP 400. Selecionar camas musicais calmas que acompanhem a narração sem distrair.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `src/curio/stages/nvidia.py` | Ordem LLM | Ordena providers como Groq, NVIDIA, OpenRouter, Mistral e Gemini; remove o interleaving antigo que colocava NVIDIA primeiro. |
| `src/curio/stages/nvidia.py` | Espera/fallback NVIDIA | Passa `timeout=None` à NVIDIA; handshake segue no limite curto configurado. HTTP 400 remove NVIDIA da execução e o rodízio continua. |
| `src/curio/audio/library.py` | Catálogo musical | Busca instrumental/ambiente calmo, rejeita títulos que indiquem colisões, ruído ou efeitos e deixa seleção automática considerar só faixas compatíveis. |
| `src/curio/audio/selection.py` | Reuso de música | Valida a faixa anterior antes de reaproveitá-la; sem cama calma disponível, registra aviso e renderiza sem música. |
| `src/curio/config.py` | Timeout | Atualiza comentários: `nvidia_timeout`/`nvidia_timeout_max` continuam compatíveis para outros providers; NVIDIA não recebe teto de resposta. |
| `tests/test_llm_fallback.py`, `tests/test_llm_timeout.py`, `tests/test_llm_diagnostics.py` | Regressão LLM | Verifica Groq primeiro, NVIDIA segundo com timeout `None`, desvio em HTTP 400 e erro classificado. |
| `tests/test_audio_library.py`, `tests/test_pipeline_integration.py` | Regressão musical | Verifica rejeição de `Crashing Starship`, revalidação do cache, seleção de faixa calma e query instrumental. |
| `README.md` | Operação | Documenta ordem, espera NVIDIA, regra HTTP 400 e seleção musical calma. |

## 3. Evidências

- Execução `output/etymology/20261001_de-onde-veio-a-palavra-escola`: metadata apontava para `freesound:564166`, título **Crashing Starship**, mood `curious`, ganho −15 dB. A faixa foi reutilizada do cache porque a seleção não validava conteúdo/título antes.
- `resolve_audio()` com metadata real agora escolhe `Curious Ambience.wav` e avisa que descartou a faixa anterior; não fez download nem alterou o projeto.
- Não havia JSON de `metrics/` disponível nesta cópia; a evidência veio do `metadata.json` e do run log persistido.
- `python -m pytest -q tests/test_llm_fallback.py tests/test_llm_timeout.py tests/test_llm_diagnostics.py tests/test_audio_library.py` — **74 passed**.
- `python -m pytest -q` — **659 passed**.
- `python -m compileall -q src/curio tests/test_llm_fallback.py tests/test_llm_timeout.py tests/test_llm_diagnostics.py tests/test_audio_library.py` — concluído sem erros.

## 4. Status vs PRD §19

Providers seguem preferência explícita; NVIDIA espera sem limite de resposta e permanece depois de Groq. Bibliotecas locais deixam de escolher efeitos/ruído como música ambiente. Nenhum provider pago ou dependência foi adicionado.

## 5. Limitações

- Não gerei/renderizei um novo MP4 para avaliação auditiva; confirme a nova cama no próximo rerender.
- Compatibilidade musical é inferida por mood/título, não por análise semântica ou escuta automática do áudio. Faixa sem indicação calma é recusada; nesse caso o render fica sem música.
- Limite de handshake da NVIDIA permanece curto; somente a espera pela resposta/modelo é ilimitada.
