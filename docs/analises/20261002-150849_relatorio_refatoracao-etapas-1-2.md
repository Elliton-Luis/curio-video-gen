# Relatório de implementação — Etapas 1 e 2 (limpeza + unificações)

Data: 2026-10-02. Fonte de verdade: `20261002-131932_analise_refatoracao-codigo-marto.md`.
Commits: `2afe77b` (etapa 1), `5985a65` (etapa 2a), `2c25cc5` (etapa 2b).
Suíte: **720/720** em todos os três commits (nenhum teste removido ou afrouxado).

## O que foi feito

### Etapa 1 — limpeza (`2afe77b`, +99/−139)

Mortos confirmados pela auditoria e removidos, todos com verificação de
zero referências fora da própria definição:

| Símbolo | Onde estava |
|---------|-------------|
| `SearchTask` | `stages/visual.py` |
| `split_script` | `stages/visual.py` |
| `_slug_from_text` | `stages/visual.py` |
| `_list_flow` | `tui.py` |
| `CurioConfig.as_dict` | `config.py` |
| `pause_queue`/`resume_queue`/`cancel_queue` | `queue.py` |
| `VisualState.form_used` | `stages/visuals.py` |
| `media_record_asset_reused`, `media_record_layer`, `media_record_retry`, `media_record_search_time`, `research_report` | `metrics.py` |
| `openrouter_settings` | `stages/nvidia.py` |
| `Credentials.rotate` (só levantava `NotImplementedError`) | `stages/nvidia.py` |
| `write_srt` | `stages/subs.py` |

Imports mortos (9) e o no-op `media_cache_misses += 0`. Detalhe dito no
commit: `backfill_from_metadata` e `slugify` estavam trocados entre
`pipeline.py` e `cli.py` — cada arquivo importava o que o outro usava.

**Divergência documentada:** `docs/relatorios/20260929-123641_relatorio_roteiro-pronto-modo.md:21`
descreve `split_script` e "gate relevância>0". Log datado não foi reescrito:
reescrever histórico para parecer atual é pior que deixar a marca. A
divergência está registrada aqui.

### Etapa 2a — `textnorm.py`, fonte única de comparação textual (`5985a65`)

Sete cópias de "minúsculas sem acento" e três listas de stopword que já
não concordavam entre si viraram um módulo só, com responsabilidade
estreita — **comparar texto** (normalizar, tokenizar, stopwords, léxico),
sem buscar, sem decidir mídia, sem falar com rede:

- `fold`, `tokens`, `fold_phrase`, `query_terms`;
- `STOP_PT` (união das duas listas), `STOP_EN`, `STOP_SHORT`;
- `SPACE_MARKERS` + `is_space_topic` (a lista estava replicada em 3 lugares);
- `PT_LEXICON` + `translate` (o `PT_EN` de 90 entradas).

A união das stopwords foi conferida antes de aplicar: 89 de 97 coincidiam;
as 8 exclusivas de `visual.PT_STOP` (nesta, embora, essas) e as 17
exclusivas de `research.STOP_PT` são todas stopword genuína, e a pesquisa
nunca casa 3 letras (exige 4+). Logo, a união não muda resultado: ela só
impede a próxima divergência.

Nenhuma semântica alterada. `scenes._norm` e `VisualState._norm` ficaram
de fora de propósito: normalizam frases com semântica diferente (comparação
de roteiro literal preservado), e unificá-las seria mudar comportamento.

### Etapa 2b — gate único, piso único, resultado explícito (`2c25cc5`)

**Gate de mídia:** havia três implementações da mesma regra —
`_validate_asset` (booleano), `_validate_asset_for` (motivo) e
`passes_hard_filters` (motivo, sem checar licença). Viraram
`media_rules.asset_gate_reason()`, que devolve o motivo e aceita
`MediaAsset` ou dict. Testes migrados para o gate único (não removidos).

**Piso de resolução:** `providers.MIN_DIMENSION = 1000` e
`media_rules.min_dimension()` = 1080 eram ambos usados em produção. Uma
foto de 1023px era aceita na busca e rejeitada no gate — e o relatório
mostrava a rejeição sem dizer de onde o número vinha. Agora há uma função,
`media.providers.min_dimension()` (1080, env `CURIO_MEDIA_MIN_DIMENSION`),
usada pelos 4 filtros de provedor e pelo gate.

Consequência honesta: provedores agora descartam candidatos de 1000–1079px
antes (antes deixavam passar e o gate pegava depois). É a convergência
para a regra documentada, não uma escolha nova.

**`ResearchResult` explícito:** `genre` e `etymology` eram atribuídos de
fora depois da construção (`res.genre = ...`), com `getattr(..., None)`
escondendo a possibilidade do atributo não existir. Agora todo campo é
declarado no `__init__`.

**Licença como dado:** `Source` ganhou `license`/`license_url` (antes
era frase dentro de `notes`), o relatório de fontes imprime, e
`add_claim` completa a licença em vez de duplicar a entrada.

## O que NÃO foi feito (e por quê)

1. **Diagramas duplicados** (`diagram.render_strip_diagram` vs
   `visuals.render_diagram`): unificar exige escolher um dos dois formatos
   de cache e de estilo visual. Isso é mudança de arte, não de estrutura —
   fica para depois da Etapa 3, com o VisualState à vista.
2. **`if genre == "etymology"` na pesquisa** (`research.py:519`): é
   exatamente o que a Etapa 4 elimina (adapter + registro de fontes
   nomeadas). Fazer agora seria criar a abstração duas vezes.
3. **Gargalos de performance**: por instrução explícita, só depois que a
   estrutura estiver estável (Etapa 5).
4. **`docs/relatorios/`**: ver divergência acima.

## Estado após a Etapa 2

| Módulo | Antes | Agora |
|--------|-------|-------|
| `stages/visual.py` | 1776 | 1568 |
| `stages/research.py` | 999 | 993 |
| `textnorm.py` | — | 255 (novo, dono da comparação textual) |

Importantes ainda intocados, por serem Etapas 3–4: `_run_pipeline`
(~1290 linhas), `tui.py` (1537), `nvidia.py` (1291, com os prompts
editoriais), e os dois renderizadores de diagrama.

## Como conferir

```
python3 -m pytest tests/ -q          # 720 passed
python3 -c "from curio.stages.media_rules import asset_gate_reason as g; \
  from curio.stages import media_rules as m; print(m.min_dimension())"   # 1080
```