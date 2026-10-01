# Relatório — Fontes sempre geram texto e timeout NVIDIA separado

- **Data:** 2026-10-01 08:15 (-03:00)
- **Tipo:** relatorio
- **Escopo:** segundo passe de fontes (núcleo + EN + garantia de texto) e separação conexão vs resposta nos timeouts LLM.
- **Commit(s):** pendente
- **Origem:** erro fatal de pesquisa em "A Guerra do Balde de Carvalho" (56 fontes achadas, 0 aceitas) + timeout de 15 s insuficiente para 550B no NIM.

## 1. O que foi pedido

Aumentar a precisão do texto, garantir que sempre haverá texto (o erro fatal de pesquisa é inaceitável), aumentar o tempo da NVIDIA (15 s nunca responde) e separar espera de conexão de espera de processamento/resposta.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `src/curio/stages/entity.py` | Precisão do alvo | Prompt do resolvedor ganha regras 8–9 (eventos/obras: nunca inventar autor/data; discriminants vazio quando incerto; exemplo Guerra do Balde); `TargetEntity` ganha `core_terms()` + `nucleus_in_title()` (tolera 1 qualificador a menos: 2/3 passa, 0/3 barra). |
| `src/curio/stages/research.py` | Garantia sem perder precisão | `research_topic(..., allow_weak=False)`: passe 2 aceita por núcleo no título (sem discriminante, `forbidden` continua barrando); passe 3 (só quando zerou) tenta núcleo sem qualificadores + Wikipedia EN; com `allow_weak=True` retorna resultado `weak` com warnings em vez de levantar. Default preservado (testes antigos passam). |
| `src/curio/pipeline.py` | Garantia no produto | Chama pesquisa com `allow_weak=True`; status `weak` + aviso em `warnings` quando passe relaxado ou zero fontes; roteiro sai com incerteza explícita (prompt já manda omitir/ressalvar). |
| `src/curio/stages/nvidia.py` | Timeouts separados | `_post_once` reescrito em `http.client`: handshake com teto curto (`llm_connect_timeout`, padrão 10 s) e envio+resposta com orçamento total (padrão 120 s); mensagens distinguem `conexão/handshake` de `resposta/processamento`; 401/403/404 definitivos, resto transitório (inalterado). |
| `src/curio/config.py`, `config.example.toml` | Orçamentos | `nvidia_timeout` 15→60, `nvidia_timeout_max` 15→120, novo `nvidia_connect_timeout` 10 (`[nvidia] connect_timeout`, `NVIDIA_CONNECT_TIMEOUT`). |
| `tests/` | Regressão | `test_research.py` (+3: núcleo, passe relaxado, `allow_weak`), `test_llm_timeout.py` (novos padrões + helper de conexão + config), `test_llm_fallback.py` e `test_llm_diagnostics.py` (mocks migrados de `urlopen` para `http.client` + teste de separação connect/total). |
| `README.md` | Uso | Parágrafo de timeouts reescrito (10 s vs 120 s) + bullet do comportamento da pesquisa (passes + `weak`, nunca fatal no `generate`). |

## 3. Evidências

```text
python -m compileall -q src/curio tests
python -m pytest -q -p no:cacheprovider
634 passed, 1 failed em 84 s
```

O 1 falho (`test_audio_render.py::test_default_music_gain_is_audible_under_ducking`, espera `-24`, árvore tem `-21`) é sujeira pré-existente de outra sessão (gains em `config.toml`, `audio/*`, `render.py`, `visual.py` — arquivos que esta entrega não tocou); no HEAD limpo o teste passa. Verificado via worktree em `/tmp` (removido após).

Testes novos/ajustados passam: `test_research.py`, `test_llm_timeout.py`, `test_llm_fallback.py`, `test_llm_diagnostics.py`, `test_entity_relevance.py`, `test_sources_rights.py` (121 passed isolados).

## 4. Status vs PRD §19

Sem PRD no repositório para checar §19. Critérios do pedido: texto sempre gerado (pipeline com `allow_weak=True`), precisão preservada (estrito primeiro, `forbidden` sempre barra, `weak` sinalizado), timeout folgado e separado (120 s total / 10 s handshake, configuráveis). Cobertos por testes; sem chamada real a provider nesta entrega.

## 5. Limitações

- Com zero fontes, o roteiro sai com grounding fraco: honesto (aviso + incerteza), não equivalente a fundamentado. `coverage` vai a 0 e `verify_grounding` lista tudo como não verificado.
- Passe 3 só roda quando o estrito zerou (evita duplicatas EN do mesmo artigo); com ≥1 fonte estrita, o teto continua `max_sources` sem segundo passe.
- `connect_timeout` por provider não existe (só global); `LLM_PROVIDER_TIMEOUT` continua valendo só para o total.
- Não rodei `generate` real (rede/LLM/TTS/render fora do escopo da suíte); validação viva do caso Balde fica pendente.
- Sujeira de outra sessão na árvore (`-24`→`-21` e queries de biblioteca) intencionalmente intocada; o commit desta entrega deve incluir só os arquivos da tabela acima.
