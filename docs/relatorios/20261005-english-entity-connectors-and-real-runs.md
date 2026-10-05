# G95 — nomes próprios ingleses e replay sem LLM

**Commit:** `3978670 fix: preserve English entity phrases in local resolver`  
**Estado:** correção local concluída e validada; qualidade editorial histórica e
consistência de métricas seguem incompletas.  
**Arquivos de código:** `src/curio/stages/entity.py`,
`tests/test_entity_relevance.py`.

## Causa confirmada

Sem LLM, `resolve_entity_heuristic()` escolhe o primeiro bloco capitalizado.
`_capitalized_spans()` reconhecia conectores portugueses, mas separava
construções inglesas como `Battle of Mohacs`: `Battle` virava o alvo antes de
`Mohacs`. O alvo genérico foi usado em `target_entity`, nas queries de pesquisa
e no contexto visual global. Evidência do replay anterior está em
`/tmp/curio-g94-history-output/history/g94-mohacs-local/sources/research.json`:
o alvo era `Battle`; as fontes aceitas incluíam `Battle`, `Battle of Battle
Hill` e `Battle Royale`.

## Mudança

O extrator agora conserva `of`, `the` e `and` entre palavras capitalizadas,
inclusive cadeias como `Battle of the Bulge`, sem adicionar um léxico por tema.
O regex `_CAP`, sem consumidores, foi removido. Regressões verificam que
`Battle of Mohacs 1526` resolve para `Battle of Mohacs` e que o nome não se
reduz ao token inicial.

## Replay histórico antes/depois

Ambas as gerações usaram `from-script`, divisão local sem LLM, providers reais,
cache/métricas isolados em `/tmp`, 4 cenas e o mesmo roteiro.

| Métrica | Antes (`g94`) | Depois (`g95`) |
|---|---:|---:|
| Entidade pesquisada | `Battle` | `Battle of Mohacs` |
| Fontes aceitas / alerta grounding | 3 / 1 não verificada | 3 / todas verificadas |
| Assets reais selecionados | 2 | 3 |
| Assets reais únicos | 2 | 3 |
| Reusos / cenas sintéticas | 0 / 2 | 0 / 1 |
| Queries lógicas | 24 | 26 |
| Downloads / bytes | 3 / 10.477.971 | 5 / 12.157.990 |
| Timeouts / retries | 0 / 0 | 0 / 0 |
| Mídia / duração total | 61,67 / 100,52 s | 66,43 / 105,75 s |

No pós-correção, a primeira cena escolheu o mapa histórico “Hungarian map of
the Battle of Mohacs”; a segunda escolheu uma gravura de Darda, 1687 (batalha
otomana diferente); a terceira escolheu foto de diorama do Museu Militar de
Istambul; a quarta recebeu um card sintético “Danube”. A inspeção visual
confirma pertinência direta do mapa e do diorama, mas a gravura de 1687 é
anacrônica para a narração de Mohács em 1526. A melhora da fonte de verdade
corrige o tópico de pesquisa e não resolve a especificidade de evento/período
no scoring e nas representações por cena.

Antes da correção, a cena 2 escolheu o Monumento à Batalha das Nações em
Leipzig, visualmente inadequado para Mohács. Esse replay terminou com duas
cenas sintéticas. Portanto o resultado depois melhorou cobertura e tópico, mas
continua abaixo do critério editorial de sucesso.

## Replay científico e validação do fallback

O replay de ciência `g94-m87-local` produziu 3 cenas, 3 assets Wikimedia
distintos por ID e SHA-256, zero reusos e zero sintéticos, com 18 queries
lógicas, 27,68 s de mídia e 65,71 s totais. As imagens são visualizações do
buraco negro M87; inspeção visual encontrou duas imagens de polarização com
composição quase idêntica e uma imagem EHT mais compacta. IDs e hashes binários
distintos, portanto, não garantem diversidade perceptual/editorial.

Nos replays históricos e científicos, `nvidia.calls` foi zero e as cenas foram
planejadas localmente; não foram adicionadas chamadas LLM por cena. Isso prova
que esses dois casos `from-script` completaram o caminho sem LLM, não que todas
as falhas de provider/LLM da suíte e2e estejam cobertas.

## Performance, métrica contraditória e evidência

No replay G95, `provider_search_time` atribui 59,32 s agregados à Wikimedia,
em 26 buscas; não houve retry nem timeout. Durações por provider se sobrepõem e
não devem ser somadas como tempo de parede. `media_query_generation_time`
aparece como `0.0` após arredondamento.

O mesmo JSON publica `provider_search_calls` para Met/AIC, mas
`provider_requests` não inclui esses providers, embora seus tempos apareçam.
Esses campos não compartilham uma definição canônica; contagens de requests
precisam ser alinhadas antes de usar o breakdown para comparação de performance.

Arquivos gerados, métricas e imagens permanecem fora do Git em
`/tmp/curio-g94-{history,science}-output`, `/tmp/curio-g94-metrics`,
`/tmp/curio-g95-history-output` e `/tmp/curio-g95-metrics`. Foram inspecionados
os vencedores reais e os dois cards sintéticos históricos.

## Testes

- Regressões focadas de entidade/pesquisa/ciência: **40 passaram** antes da
  suíte; após remover `_CAP`, `test_entity_relevance.py`: **17 passaram**.
- Suíte completa: **1012 passaram em 175,13 s**.
- `python -m compileall -q src tests` e `git diff --check`: passaram.
