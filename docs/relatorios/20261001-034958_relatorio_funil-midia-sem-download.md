# Relatório — Funil de mídia sem downloads

- **Data:** 2026-10-01 03:49 (-03:00)
- **Tipo:** relatorio
- **Escopo:** localizar perdas de candidatos, corrigir contadores e o reconhecimento da URL JPG do Unsplash sem mudar relevância editorial.
- **Commit(s):** commit desta entrega, `fix: correct media funnel accounting and image urls`
- **Origem:** geração de São Francisco com 87,35 segundos de mídia e zero downloads.

## 1. O que foi pedido

Traçar candidatos desde consulta até asset ou fallback, executar diagnóstico pequeno, corrigir apenas bugs comprovados, preservar providers e filtros editoriais e registrar validação.

## 2. Causa raiz e funil histórico

Arquivos consultados primeiro:

- `metrics/20261001-031534_fale-sobre-a-historia-de-sao-francisco-d.json`;
- `output/fale-sobre-a-historia-de-sao-francisco-d/metadata.json`;
- `output/fale-sobre-a-historia-de-sao-francisco-d/script/chapters.json`;
- `output/fale-sobre-a-historia-de-sao-francisco-d/media/media.json`;
- comparação recente: `metrics/20261001-033749_explique-a-relacao-entre-escravo-e-ciao.json` (70,01 s de mídia, dois downloads, quatro visuais sintéticos).

O funil da execução relatada é:

```text
121 MediaAsset retornados por providers (já normalizados/filtrados internamente)
108 candidatos passam filtros eliminatórios e chegam ao ranking
4 rejeitados por filtros eliminatórios (termos decorativos)
9 restantes: duplicação ou orçamento de coleta; histórico não separa esses motivos
108 rejeitados por score (64 nota 0, 22 nota 2, 20 nota 3, 2 nota 6)
0 acima do threshold 34
0 selecionados, 0 tentativas de download, 0 cache de imagem real, 0 usados reais
9 visuais locais: 8 cards e 1 diagram
```

**O ponto de perda dominante é `scoring.below_threshold()`**, antes de qualquer download. Os 121 não são o total bruto das APIs: `results_received` conta objetos que o provider já converteu em `MediaAsset`. Não é possível recuperar do histórico a quantidade descartada dentro de cada adapter.

As nove cenas foram geradas por fallback local (`scenes_source=local`). Todas têm `subject`, `visual_entities`, `context`, `forbidden`, `visual_queries` e `global_visual_queries` vazios. `_waterfall_queries()` então deriva consultas do texto, como `São`, e completa com `laboratory`, `microscope`, `science` etc. Exemplo: `São` trouxe imagens de São Paulo e mosteiro de São Bento, não uma representação contextualizada de São Francisco.

`scoring._scene_terms()` usa narração inteira quando não há assunto nem queries estruturadas. `base_score()` calcula cobertura das palavras dessa narração no título do asset. Os títulos das imagens encontradas cobrem pouquíssimas palavras e ficam entre 0 e 6, muito abaixo de 34. O filtro evitou imagens fora do assunto; reduzir threshold esconderia a falha de consultas/contexto e admitiria fotos inadequadas.

## 3. Caminho completo inspecionado

| Etapa | Código e decisão |
|---|---|
| Query | `visual._waterfall_queries()` cria até oito consultas; `local_queries()` usa até dois termos locais quando cenas não trazem queries. A extração passa por um `set`, tornando a primeira entidade dependente do hash do processo. |
| Provider / API | `visual._search_with_timeout()` chama `provider.search(query, 5, metrics)`. Os próprios providers contam chamadas. Wikimedia inclui espera de cortesia, retry e seleção de thumbnails; NASA pode buscar catálogo de arquivos por resultado. |
| Normalização | Providers convertem JSON em `MediaAsset` e descartam metadados inválidos: URL, resolução, tamanho, licença, identificador ou ausência de arquivo, conforme adapter. `results_received` começa depois disso. |
| Coleta / deduplicação | `_consider()` deduplica por `asset_id`, passa `_validate_asset_for()` e coleta até `max_images * CANDIDATE_MULTIPLIER` (3 × 4 = 12 nesta cena). O restante da resposta não é examinado quando o orçamento foi preenchido. Deduplicação atual não inclui namespace do provider; colisão entre IDs de providers diferentes é possível, mas não foi comprovada como causa desta execução. |
| Filtro | `_validate_asset_for()` verifica URL de imagem, licença sem ND, direitos blocked, lado mínimo 1080, teto 25 MiB e termos bloqueados no título. Não consulta bytes nem faz download. |
| Ranking | `scoring.rank_candidates()` usa título e vocabulário da cena; `below_threshold()` remove notas menores que 34. Na execução relatada todos os elegíveis caem aqui. |
| Seleção | Só `ranked[:max_images]` entra no laço de download. Não há tentativa com os demais se os primeiros selecionados falharem. |
| Direitos | `MediaAsset.__post_init__()` classifica licença em clear/verify/blocked. Blocked é barrado no gate; verify gera aviso apenas no asset selecionado e utilizável. `rights_verify` nunca foi “quantidade de licenças examinadas”. |
| Download | `media.cache.download_asset()` usa `download_url`, depois `download_fallback_url` se a primeira falha. `source_url`/`license_url` são páginas de procedência, não URLs para baixar imagem. `downloads` conta arquivos gravados com sucesso, não todas as tentativas. |
| Cache | Primeiro consulta índice por query; depois cache por provider/ID e sidecar. Arquivo existente pode evitar novo download. Na execução histórica ambos hits e downloads são zero. |
| Pós-download | `_downloaded_dims_ok()` exige arquivo maior que 10000 bytes; com dimensões conhecidas confia no adapter, sem dimensões usa ffprobe. Rejeição ocorre antes de uso final. |
| Asset final | Asset recebe `used_in`, é salvo no índice de cache, ganha score/order e entra em `picked`. |
| Fallback | Se não há imagem escolhida, tenta mecanismo sintético quando aplicável; depois `visuals.visual_for_scene()`. `synth_diagrams` inclui cards, não somente diagramas. |

### URLs e defeito localizado independente

Wikimedia usa `thumburl` preferencialmente, não a página `fullurl`. Na execução pequena houve URLs reais `https://thumb.wikimedia.org/wikipedia/commons/thumb/.../1920px-....jpg?...`; a regex aceita `.jpg?`. No histórico não há evidência de falha de download dessas URLs: o laço nunca foi alcançado.

Unsplash constrói `https://images.unsplash.com/photo-...?w=1920&q=80&fm=jpg`. Essa URL entrega JPG por transformação do CDN, mas não tem extensão `.jpg` no caminho. O gate antigo rejeitava a URL como “não é imagem”, independentemente do conteúdo, título e dimensões. Corrigi o reconhecimento do formato **somente para HTTPS, host exato `images.unsplash.com` e `fm=jpg`**. URL genérica com `fm=jpg`, host parecido, ausência de formato e `fm=html` continuam rejeitados. Não mudei relevância, resolução, licença ou providers.

Outro detalhe identificado: Wikimedia consulta thumbnail, mas confere `size` e dimensões do original. Dois originais grandes foram barrados na execução pequena mesmo com URL de thumbnail. Essa regra não explica a perda dos 108 candidatos já elegíveis. Não a alterei; precisa de verificação de dimensões/bytes da representação efetivamente baixada antes de mudar critérios.

## 4. Execução real pequena

Fixture: **somente cena 1** de `output/fale-sobre-a-historia-de-sao-francisco-d/script/chapters.json`. Configuração via `CurioConfig.load()`, ambiente local preservado, cache isolado em `/tmp/opencode/media-funnel-cache`, `max_images=3`, gênero `people`, providers atuais. Sem LLM, pesquisa de roteiro, TTS ou render.

Instrumentação temporária em `/tmp/opencode/media_funnel_probe.py` conta respostas brutas JSON e decisões existentes sem alterar a escolha de imagens. Resultado completo em `/tmp/opencode/media-funnel-probe.json`. Comando final:

```bash
PYTHONHASHSEED=0 PYTHONPATH=src python /tmp/opencode/media_funnel_probe.py
```

```text
5 tentativas HTTP: Wikimedia 2, Pixabay 1, NASA 1, Unsplash 1
15 resultados brutos
2 excluídos no adapter Wikimedia por tamanho do original acima de 25 MiB:
  4122x6465, 29459847 bytes; 6000x4000, 36141643 bytes
13 normalizados retornados (Wikimedia 8, Pixabay 5)
1 não examinado por limite da coleta
12 únicos avaliados; 0 duplicados; 0 rejeitados pelo gate da cena
12 elegíveis e ranqueados; todos com nota 2, mínimo 34
0 selecionados; 0 downloads tentados/concluídos; 0 imagens reais usadas
1 card local; rights_verify=0 e rights_blocked=0
```

Houve três sondagens pequenas para fechar instrumentação, totalizando **16 tentativas HTTP** (6 + 5 + 5). A primeira escolheu `Bernardone` em vez de `São` devido à ordem não determinística do `set` em `local_queries()`. Trouxe partituras da ópera “Giannina e Bernardone”, confirmando que fragmentos isolados do nome não preservam identidade. A segunda reproduziu o funil, mas faltava motivo dos descartes internos do adapter; a terceira registrou os dois tamanhos e fixou `PYTHONHASHSEED=0`. Não houve execução repetida do pipeline completo. Resultados vivos e hash diferentes impedem tratar as sondagens como avaliação pareada de performance.

## 5. Inconsistências das métricas e correções

| Defeito | Correção mínima |
|---|---|
| Chamadas contadas pelo chamador e novamente no provider; 96 não prova 96 requests HTTP. | Removi contagem duplicada de `_search_scene_with_shortcircuit()`. Providers continuam donos da contagem de requests. A pequena execução fecha 5 observadas = 5 registradas. |
| `assets_rejected=4` contava hard filters, mas não os 108 rejeitados por score. | Passei a contar rejeições por score no mesmo contador. |
| Score rejeitado aparecia duas vezes no resumo de motivos. | Removi contagem antecipada redundante; cada rejeição aparece uma vez. |
| `rights_blocked` não era incrementado no gate que bloqueava licença. | Contagem adicionada ao gate, sem mudar decisão. `rights_verify` segue sendo aviso de uso para licença a conferir. |
| `gerado_por_codigo_pct=0` apesar dos nove visuais sintéticos. | Percentual passa a usar contador de visuais gerados, não tipo semântico da cena. |
| Perdas por deduplicação/orçamento não eram separadas. | Adicionei funil agregado em `consumption.media.funnel`, sem logs por candidato. |
| Motivos só apareciam em metadata/review, não em metrics. | `consumption.media.rejection_reasons` persiste motivos agregados. |

Novos pontos contabilizados: normalizados retornados, cache retornado, únicos considerados, duplicados, não examinados por orçamento, hard rejects, elegíveis, rejeitados por score, acima do threshold, selecionados, falhas de download, rejeições pós-download e usados reais. Chaves sem ocorrência podem estar ausentes; ausência corresponde a zero. Resultados brutos antes dos adapters continuam fora do coletor persistente; a sonda temporária os mediu diretamente.

Exceções inspecionadas: busca com `MediaError` é capturada e ignora provider naquele query; 401/403/429 desativa provider e atualmente incrementa `timeouts`, embora não seja timeout de rede. `from_dict()` pode ser ignorado em `TypeError`; erros de download viram warnings; ffprobe ilegível vira rejeição. Não há evidência de nenhuma dessas exceções no ponto que elimina os 108: as notas e contagem zero acima do threshold explicam a perda integral.

## 6. Arquivos e testes

| Arquivo | Responsabilidade |
|---|---|
| `src/curio/stages/visual.py` | Contadores no gate/ranking, orçamento/deduplicação e fim do funil; remoção da dupla contagem de buscas; reconhecimento correto da URL de imagem. |
| `src/curio/metrics.py` | Persistência do funil/motivos e percentual correto de visuais gerados. |
| `src/curio/stages/media_rules.py` | Reconhecimento estrito da transformação JPG no CDN oficial Unsplash. |
| `tests/test_media_funnel.py` | Regressão: perda por licença, deduplicação, orçamento, score, download e uso; rejeições uma vez; requests uma vez; percentual; URL CDN sem extensão e negativos. |
| `tests/test_media_waterfall.py` | Fake provider passa a contar requests como os providers reais. |
| `README.md`, `docs/README.md` | Campos novos e índice da entrega. |

```text
Primeira rodada focada: 99 passed, 1 failed.
Falha: fake provider não contava requests; dependia da contagem duplicada removida.
Corrigido contrato do fake, sem alterar expectativa de seleção.

python -m pytest -q -p no:cacheprovider tests/test_media_funnel.py tests/test_media_diag.py tests/test_visual_strategies.py tests/test_media_waterfall.py tests/test_media_providers.py tests/test_pipeline_integration.py
107 passed in 41.16s

Após correção da URL Unsplash:
python -m pytest -q -p no:cacheprovider tests/test_media_funnel.py tests/test_media_diag.py tests/test_visual_strategies.py tests/test_media_waterfall.py tests/test_media_providers.py tests/test_entity_relevance.py
116 passed in 7.33s
```

Teste de funil fecha seis retornados = três únicos examinados + um duplicado + dois não examinados. Três únicos = um bloqueado por direitos + dois elegíveis; um elegível reprova score, outro é baixado/usado. Não exige afrouxamento de nenhum filtro.

## 7. Status vs PRD §19 e pendências

Não há PRD disponível para verificar §19. Critérios desta solicitação cobertos por artefatos reais, execução de mídia isolada e regressões específicas.

Recomendação de próxima mudança editorial: preservar assunto/entidade-alvo e consultas específicas quando cenas caem para divisão local, antes de adicionar providers ou reduzir threshold. Deve haver fixture para evitar homônimos e garantir que consultas/score expressem “São Francisco de Assis”, não “São” ou texto inteiro da narração.

Pendências não corrigidas: ordem não determinística de termos locais; deduplicação sem namespace; limite da coleta antes do ranking pode impedir queries melhores; original versus thumbnail no adapter Wikimedia; dimensões conhecidas não são reprobed do arquivo real; falha dos primeiros selecionados não tenta candidatos seguintes; `timeouts` mistura erros de acesso/cota; retries HTTP internos de alguns adapters não têm contagem individual. São limitações documentadas, não foram usadas para afirmar que todas as perdas vêm do mesmo ponto.

`metrics/` e `output/` são ignorados pelo Git; Glob pode omitir esses arquivos. Nesta investigação a leitura direta dos diretórios encontrou os artefatos reais. Não foi necessário adicionar provider, alterar prompt, mudar score/threshold ou executar pipeline completo.
