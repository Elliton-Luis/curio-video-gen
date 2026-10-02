# Análise: bagunça estrutural, código morto e gargalos (pré-refatoração)

Data: 2026-10-02. Escopo: `src/curio` (~20,2 mil linhas, 33 módulos).
Método: cada item abaixo foi verificado com `grep`/AST contra `src + tests +
scripts + docs` — "morto" aqui significa **zero referências fora da própria
definição**. Nada foi removido; isto é o mapa para a refatoração.

Convenções usadas: `arquivo.py:linha` para cada achado.

---

## 1. Código morto confirmado (remover sem medo)

Funções/classes/métodos com zero chamadas em produção, testes, scripts e docs:

| # | Símbolo | Onde | Observação |
|---|---------|------|------------|
| 1 | `SearchTask` | `stages/visual.py:228` | dataclass do short-circuit antigo |
| 2 | `_slug_from_text` | `stages/visual.py:1757` | sobra de roteiro-pronto |
| 3 | `split_script` | `stages/visual.py:716` | idem; `docs/relatorios/...roteiro-pronto-modo.md:21` ainda diz que existe (doc desatualizado) |
| 4 | `_list_flow` | `tui.py:1346` | fluxo de menu nunca despachado (o menu chama os outros 10 `_flow`) |
| 5 | `CurioConfig.as_dict` | `config.py:410` | ninguém serializa config |
| 6 | `pause_queue`, `resume_queue`, `cancel_queue` | `queue.py:325-333` | CLI só usa `cancel_item`; fila sem pausar/retomar |
| 7 | `VisualState.form_used` | `stages/visuals.py:405` | método nunca lido |
| 8 | `media_record_asset_reused`, `media_record_layer`, `media_record_retry`, `media_record_search_time`, `research_report` | `metrics.py:130,186,192,233,324` | 5 métodos de métrica que nenhum estágio chama (métrica que ninguém emite é ruído no relatório) |
| 9 | `openrouter_settings` | `stages/nvidia.py:464` | settings resolvidos por outro caminho (`llm_settings`) |
| 10 | `Credentials.rotate` | `stages/nvidia.py:355` | morto por design (`raise NotImplementedError` documentado) — ou implementa ou apaga |
| 11 | `write_srt` | `stages/subs.py:463` | só `build_srt` é usado; `write_srt` chama `build_srt` dentro de si e ninguém a chama |

Imports mortos (mesmo critério):

- `pipeline.py:28` `backfill_from_metadata` (usado só em `cli.py:588`), `:31` `slugify` (só `slugify_with_timestamp` é usado)
- `cli.py:31` `slugify_with_timestamp` (só `slugify` é usado) — espelho do anterior: cada arquivo importa o que o outro usa
- `queue.py:17` `Path`, `tui.py:18` `time`, `tui.py:26-27` `nvidia_stage`, `media_prov`, `tui.py:883` `cancel_item` (import dentro de `_queue_detail`, função usa `remove_item`)
- `stages/entity.py:31` `json`, `stages/visual.py:1194` `visuals as _v` (bloco usa nomes diretos, `_v` sobra), `media/providers.py:14` `os`
- (`from __future__ import annotations` aparece como "não usado" em scan estático — é falso-positivo, diretiva intencional, manter.)

## 2. Quase-mortos: vivos só por teste, mortos em produção

Pior que morto: dão impressão de cobertura enquanto o caminho real usa outro código.

- `visual._validate_asset` — produção usa `_validate_asset_for`; testes em `test_media_waterfall.py:55-65` seguram o duplicado.
- `media_rules.passes_hard_filters` — produção usa `_validate_asset_for`; testes em `test_thermal_receipt.py:202-212` e `test_media_funnel.py:109`.
- Ou seja: o gate de metadados existe em **3 implementações** (`_validate_asset`, `_validate_asset_for`, `passes_hard_filters`). Unificar em uma e apontar os testes para ela.
- `typography.clear_cache/describe/used_requested`, `visual_beats.average_seconds`, `providers.reset_provider_health` — usados só em testes. Não apagar sem olhar, mas sinalizam API pública que a produção abandonou.

## 3. Duplicações de lógica (mesma ideia, N cópias)

1. **Normalização de texto em 7 lugares**: `scoring._fold/_tokens`, `media_rules._fold`, `entity._fold`, `research._strip_acc`, `visual._strip_acc`, `scenes._norm`, `etymology._fold` (este último entrou nos commits recentes — exemplo de como o problema se propaga a cada feature). Um `stages/text.py` único resolve.
2. **Stopwords em 3 listas**: `visual.PT_STOP`, `research.STOP_PT/STOP_EN`, `entity._STOP_CURTAS` (esta importa `research.STOP_PT` — acoplamento parcial já existe).
3. **`_query_terms` idêntico** em `pipeline.py:131` e `stages/visual.py:728`.
4. **Piso de resolução duplo e divergente**: `providers.MIN_DIMENSION = 1000` vs `media_rules.min_dimension()` default `1080`. Produção usa os dois (`_validate_asset`→1000, `_validate_asset_for`→1080). Efeito real: métricas mostram rejeição `1023x1118 menor que 1080px` num gate que o outro gate aprovaria. O docstring de `media_rules` admite a subida 1000→1080; `providers.py` ficou para trás.
5. **Dois renderizadores de diagrama**: `diagram.render_strip_diagram` (fallback mecanístico via `visual._synth_diagram_for_scene`) vs `visuals.render_diagram` (escada). Sobreposição parcial, dois caches, dois estilos.
6. **Dois caminhos de fetch de mídia**: `pipeline._fetch_media` (max_images==1) vs `visual.fetch_media_multi`.
7. **Marcadores de tópico espacial em 3 lugares**: `visual._SPACE_MARKERS`, `media_rules._SPACE_MARKERS`, `scenes._SPACE_HINTS` (divergiram na primeira semana — mesma doença do item 1).
8. **`metrics.media_cache_misses += 0`** (`visual.py:1151`) — no-op fóssil de lógica removida.
9. **`ResearchResult` com atributos pendurados** (`res.genre`, `res.etymology`, `res.facts`... definidos fora do `__init__`) — virar campos/dataclass de verdade.

## 4. Código fora de lugar (a queixa original)

1. **Prompts editoriais dentro do provedor LLM** (`stages/nvidia.py`, 1311 linhas): `SCRIPT_SYSTEM_PROMPT(_EN)` + `TITLE_SYSTEM_PROMPT(_EN)` moram ao lado de credenciais, retry HTTP e round-robin. Contraste: prompts de cenas vivem em `scenes.py` ✓ e de entidade em `entity.py` ✓. Proposta: `stages/prompts.py` (ou `editorial.py`) como dono único; `nvidia.py` só transporta.
2. **Dados linguísticos no estágio de mídia**: `visual.py` carrega `PT_EN` (~90 entradas), `PT_STOP`, `SPACE_*`, `_SPACE_PRIORITY`. Tradução PT→EN não é busca de mídia.
3. **Modo roteiro-pronto dentro de `visual.py`**: `read_script_file`, `scenes_for_script`, `split_script` (morto), `validate_preserved` — lógica de roteiro no módulo de fotos. (Parte já vazou para `pipeline.py:131` via `_query_terms` copiado.)
4. **Montagem dentro da busca**: `insertion_scenes`, `ENTRY_STYLES`, SFX, `_assign_sfx`, `_shuffled_styles`, `plan_scene_images`, `retime/rebuild_visual_timeline` — timeline/áudio morando no buscador de imagens.
5. **God functions/módulos**: `_run_pipeline` ≈ 1290 linhas numa função (de `pipeline.py:766` até o fim do arquivo); `visual.py` 1776 linhas com ~10 responsabilidades (busca, scoring-uso, fallback, timeline, inserções, SFX, roteiro-pronto); `tui.py` 1561 linhas.
6. **Identificadores PT no meio do EN**: `typography._par_de_bolso`, `_tem_ambos`, `tui.detalhes` — escolher um idioma para código.

## 5. Gargalos puramente de implementação (performance, sem mudar produto)

1. **Pesquisa 100% serial** (`research.py:378-401`): para cada query, 1 search + até 5 extracts, tudo sequencial. Vídeo típico: ~60 HTTPs seriais só aqui. Concorrência por query (com o mesmo teto de fontes) derrubaria o estágio mais lento do pipeline (13s no vídeo Marco Aurélio).
2. **Mídia serial com config fantasma**: `collect()` (`visual.py:~985`) itera query×provedor sequencialmente com `SEARCH_TIMEOUT=15s`; `MAX_CONCURRENT_SEARCHES/DOWNLOADS` existem como env mas **nunca são lidos por nenhum executor**. Ou implementa o pool ou remove o env.
3. **`_search_with_timeout` não limita nada** (`visual.py:237-250`): `ThreadPoolExecutor(max_workers=1)` por chamada + `with` que faz `shutdown(wait=True)` — no timeout, espera o request travado até o fim (o timeout vira enfeite) e vaza a thread. Um executor por estágio + `requests` com timeout real resolve.
4. **Downloads seriais** no loop de `picked` + **1 subprocesso ffprobe por asset** (`_probe_dims`) — paralelizável e cacheável pelo hash da URL.
5. **`_plan_gaps` = +1 chamada LLM por vídeo** sempre que há chave (`research.py:537`), mesmo com fontes suficientes. Virou custo fixo; condicionar a lacuna real.
6. **`complete_json`**: 2 tentativas × 1500 tokens por chamada de roteiro/cenas.
7. **Etymology serial** (culpa recente, mesma doença): cadeia resolve até 4 fetches em sequência + Logeion + Perseus. Reaproveitar o pool do item 2 quando existir.
8. **Mídia refaz busca por cena sem compartilhar**: 7 cenas × mesmos provedores; `MEDIA_CACHE_DIR` ajuda entre vídeos, não entre cenas do mesmo vídeo (o dedup é pós-busca).

## 6. Inconsistências menores (baratas de corrigir)

- `run_event`-ou-`print` repetido em ~30 sites de import (`from ..runlog import event as run_event` + `if not logged: print(...)`): extrair helper `avisar()` único.
- Assimetria de licença: `ResearchSource` tem `license/license_url`, mas `SourceRegistry.add_claim` não tem campo de licença (vai em `notes` como texto). Auditoria futura agradece o campo.
- `config.toml` versionado (11 linhas, sem segredos — verificado) ao lado de `config.example.toml`: ou o exemplo gera o real (e o real sai do git) ou documenta por que os dois vivem juntos. `.env` está ignorado ✓.
- Docs com drift: `docs/relatorios/...roteiro-pronto-modo.md` descreve `split_script` (morto, item 2) e "gate relevância>0" (não existe mais).

## 7. Ordem sugerida para a refatoração (menor risco primeiro)

1. **Limpeza**: remover §1 + imports mortos + `+= 0` (≈30 min, risco ~zero, cada remoção verificável por teste).
2. **Unificar gates e pisos**: 1 gate de metadados, 1 `MIN_DIMENSION`, 1 `_query_terms` (§2–§3.1/3.4 — mexe em comportamento, exige suíte verde).
3. **Extrair `text.py`** (normalização/stopwords/marcadores) e mover prompts para dono único (§3.1/3.7, §4.1 — resolve a queixa original sem tocar lógica).
4. **Quebrar `_run_pipeline` e `visual.py`** por etapa (§4.5 — o único passo com risco arquitetural real; fazer por último, com a suíte como rede).
5. **Concorrência** (§5.1–5.4 — só depois de 1–4, para não paralelizar código que vai mudar de lugar).

Total estimado de mortos+duplicados removíveis sem mudar comportamento: ~250–350 linhas + 10 imports.
