# Relatório — Pasta por gênero e slug datado AAAAMMDD_titulo

- **Data:** 2026-10-01 12:54 (-03:00)
- **Tipo:** relatorio
- **Escopo:** saída aninhada por gênero (`output/<genero>/<slug>`) e nome de projeto `AAAAMMDD_titulo`.
- **Commit(s):** pendente
- **Origem:** pedido para organizar vídeos por pasta de gênero e datar o título com a data de hoje.

## 1. O que foi pedido

Ao escolher o gênero, o vídeo sempre ficar dentro da pasta do gênero (uma pasta por gênero); e o título (slug da pasta) ser `datahoje_titulo`.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `src/curio/slug.py` | Formato + pastas | `slugify_with_timestamp` agora gera `AAAAMMDD_titulo` (só data, sem hora); novos `project_dir()` (com gênero → `output/<genero>/<slug>`, sem gênero → plano legado), `find_project_root()` (plano, depois `<genero>/`, alfabético) e `unique_slug()` (rerun da mesma ideia reutiliza; colisão com outra ideia sufixa `-2`, `-3`…). |
| `src/curio/pipeline.py` | Geração e buscas | `video_paths(out_dir, slug, genre="")`; `_resolve_paths()` centraliza slug final + anti-colisão (só p/ slug automático — explícito é endereço exato p/ retomada); `run_pipeline`/`_run_pipeline` aninham por gênero; `_paths_for_slug()` aceita `slug`, `genero/slug` e legado; `iter_projects()` lista ambos; `metadata` ganha `project_dir`. |
| `src/curio/cli.py` | Comandos | `_lookup_paths()` em `sources/review/swap/rerender/verify/info`; `list` e `metrics` enumeram aninhados; mensagens de log dizem `output/[<genero>/]<slug>/logs/`. |
| `src/curio/tui.py` | Fluxos | Geração usa `slugify_with_timestamp` e mostra a pasta com gênero; `_project_status`, verify, apagar e listagem via `_paths_for_slug`/`iter_projects` (refs `genero/slug`); limpeza apaga pelos topos listados. |
| `src/curio/queue.py` | Fila | Slug automático também datado; raiz derivada do artefato (já funcionava aninhado). |
| `tests/test_slug.py` | Regressão | Formato `AAAAMMDD_titulo`, aninhamento, legado, unicidade/colisão, refs e `FileNotFoundError`. |
| `tests/test_pipeline_integration.py` | Ajuste | Caso `genre="people"` espera `video_paths(..., "people")`. |
| `README.md` | Uso | Estrutura de saída documenta `output/[<genero>/]<AAAAMMDD-titulo>/`, `-2` em colisão e compat com projetos antigos. |

Métricas (`metrics/AAAAMMDD-HHMMSS_slug.json`) inalteradas de propósito: carimbo próprio com hora preserva ordenação.

## 3. Evidências

```text
python -m pytest -q -p no:cacheprovider tests/test_slug.py tests/test_review_flow.py \
  tests/test_standby_flow.py tests/test_tts_coverage.py tests/test_pipeline_integration.py
todos passam (33 testes; tts/review levam ~3 min por ffmpeg)
```

Bug pego pelos testes: o anti-colisão inicial renomeava slug explícito e quebrava retomada de standby (`teste-standby` virou `teste-standby-2-2`); corrigido para sufixar só slug automático.

## 4. Status vs PRD §19

Sem PRD no repositório para checar §19. Critérios do pedido: gênero → pasta do gênero; slug `AAAAMMDD_titulo`; comandos antigos seguem achando projetos legados. Cobertos por testes.

## 5. Limitações

- Mesmo título+gênero no mesmo dia sufixa em vez de reutilizar quando a ideia difere (proposital); `--slug` explícito nunca sufixa (endereço exato).
- Mesmo slug em dois gêneros: lookup pelo slug puro pega o primeiro em ordem alfabética — use `genero/slug` para desambiguar.
- `metrics/` continua plano (só `output/` aninha).
- Não rodei `generate` real; validação viva pendente. Commit deve excluir sujeira alheia na árvore (`config.toml`, `audio/*`, `render.py`, `visual.py`, gains `-21`).
