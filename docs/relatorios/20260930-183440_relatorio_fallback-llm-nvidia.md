# Relatório — Fallback resiliente da NVIDIA

- **Data:** 2026-09-30 18:34 (-03:00)
- **Tipo:** relatorio
- **Escopo:** últimos-provider viable, timeout NVIDIA, retries HTTP internos e orçamento global do rodízio.
- **Commit(s):** `dab03b2` (`fix(llm): retry NVIDIA without timeout when it is the last provider`), `d699409` (`test(llm): cover last-provider fallback and retry accounting`); documentação: pendente.
- **Origem:** solicitação de correção do fallback LLM após NVIDIA ser descartada por timeout.

## 1. O que foi pedido

Preservar o timeout normal da NVIDIA enquanto há alternativas. Quando as alternativas forem definitivamente rejeitadas ou esgotarem retries transitórios, manter NVIDIA como último caminho, sem timeout e com até cinco tentativas. Erros transitórios devem ter backoff; autenticação/configuração/modelo inválidos devem encerrar sem insistir. Também foi pedido tornar claro como os retries internos entram no levantamento e como se relacionam com o orçamento global.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão e implementação |
|---|---|---|
| `src/curio/stages/nvidia.py` | Classificação HTTP/rede | `_post_once` aceita `timeout=None`. O timeout normal continua marcado como `fast_fail`; no modo final, falhas de rede/timeout continuam retryable. Também são tratados resets de conexão que cheguem como `OSError` não encapsulado. Cada erro leva `http_attempts`; esgotamento do retry interno leva `retry_exhausted`. |
| `src/curio/stages/nvidia.py` | Orçamento/rodízio | `CURIO_LLM_ATTEMPTS` limita rodadas globais de escolha de provider. `_post_with_retries` reporta o número real de requests HTTP dentro da rodada. Providers definitivos ou com retries internos esgotados saem do pool desta execução; timeout fast-fail de provider alternativo também é retirado do pool, enquanto NVIDIA continua elegível como último caminho. O resumo agora distingue rodadas globais, requests HTTP por provider e as tentativas do fallback final. |
| `src/curio/stages/nvidia.py` | Fallback final | Quando só NVIDIA continua viável (inclusive após todos os outros falharem), `_nvidia_resilient_fallback` chama `_post_once(..., timeout=None)` até cinco vezes. Mostra `último provider viável — fallback resiliente` e `tentativa n/5 — aguardando sem timeout...`. 429/5xx/rede/timeout recebem backoff; 401/402/403/404 e demais erros definitivos encerram imediatamente. |
| `README.md`, `.env.example`, `config.example.toml` | Documentação operacional | Atualizada a distinção entre timeout normal, rodadas globais, requests HTTP internos e o fallback sem timeout de cinco tentativas. O timeout normal continua configurável e não foi aumentado. |
| `tests/test_llm_fallback.py`, `tests/test_llm_timeout.py`, `scripts/smoke.sh` | Regressão | Cobertos rotação normal, fallback NVIDIA final, retorno em uma das cinco tentativas, cinco falhas transitórias, erro definitivo, conexão resetada, timeout `None` chegando ao urllib e contagem separada de requests/rodadas. O smoke offline foi atualizado para as novas mensagens. |

## 3. Evidências

### Testes automatizados

```text
python -m compileall -q src/curio tests
python -m pytest -q -p no:cacheprovider
590 passed in 73.84s
```

Os testes específicos do fallback também passaram isoladamente:

```text
python -m pytest tests/test_llm_fallback.py tests/test_llm_timeout.py -q -p no:cacheprovider
20 passed
```

### Smoke offline

`./scripts/smoke.sh` executou todos os cenários LLM atualizados com `urlopen` simulado: retry HTTP 503, timeout normal fast-fail, troca NVIDIA→OpenRouter, fallback resiliente sem timeout, cinco falhas transitórias e 401 definitivo. O resultado global do smoke foi **86 passaram / 2 falharam**; as duas falhas estão em checagens não relacionadas a LLM (`consultas offline traduzem o contexto` e `ASS: Archivo Black + caixa preta que acompanha o texto`). Não foram alteradas nesta correção.

### Contagem e resultado esperado

O teste do cenário de esgotamento completo verifica que Gemini teve seis requests HTTP em uma rodada interna, enquanto o rodízio contabilizou seis rodadas globais; depois disso, NVIDIA fez cinco requests com `timeout=None`. O resumo usa unidades explícitas, por exemplo `Gemini: 6 tentativa(s) HTTP em 1 rodada(s)` e `LLM indisponível após 6/6 rodada(s) globais`, eliminando a antiga ambiguidade entre o contador interno e o global.

## 4. Tentativas, erros e correções

- Os testes antigos de timeout configurável substituíam `_post_with_retries` e só forneciam a chave NVIDIA. Com a regra nova, NVIDIA sozinha já começa no modo final, portanto esses testes estavam exercitando o modo errado. Passei a fornecer também uma chave OpenRouter nos testes que validam o timeout normal; assim continuam verificando 15 s/configuração no rodízio comum.
- A primeira atualização do smoke ainda esperava retries internos para timeout de socket e somente seis URLs no cenário “todos down”. O comportamento atual faz timeout normal fast-fail e, após as seis rodadas comuns, adiciona cinco requests NVIDIA sem timeout. O smoke foi ajustado para usar HTTP 503 ao testar retries internos e conferir separadamente as seis URLs normais e as cinco finais.
- A primeira execução do smoke após a mudança revelou que o caso “NVIDIA 401” ainda tinha chave Gemini exportada; assim NVIDIA não era o único provider e o teste não entrava no fallback final. O caso agora remove as outras chaves antes de verificar a interrupção definitiva em uma tentativa.
- O smoke completo continua apontando duas falhas fora do escopo: a tradução de consultas offline e a expectativa de fonte/caixa das legendas ASS. Os cenários LLM do smoke passam.
- Não foi feita chamada real à NVIDIA: os cenários foram simulados para não consumir créditos nem depender de tempo/rede não determinísticos.

## 5. Status vs PRD §19

Não há arquivo PRD no repositório para verificar §19. Os cinco comportamentos enumerados na solicitação foram exercitados por testes, incluindo a continuidade do rodízio, o fallback sem timeout, sucesso dentro das cinco tentativas, esgotamento transitório e encerramento imediato por erro definitivo.

## 6. Limitações

- Uma chamada no modo final pode esperar indefinidamente se a conexão permanecer aberta sem resposta; isso é intencional para cumprir “sem timeout”. As cinco tentativas limitam erros que retornam, não o tempo de uma requisição travada.
- `CURIO_LLM_ATTEMPTS` é o orçamento de rodadas globais; cada rodada ainda pode conter retries HTTP internos. O levantamento agora mostra os dois contadores explicitamente.
- A suíte não validou o endpoint NVIDIA real; credenciais, disponibilidade e latência real seguem dependentes do serviço.
- Permanecem as duas falhas não relacionadas do `scripts/smoke.sh` descritas acima.
