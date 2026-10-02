# Relatório — variedade real de assets até o render

- **Data:** 2026-10-01 20:30 -0300
- **Tipo:** relatorio
- **Escopo:** seleção sem repetição desnecessária, identidade central, fundos por beat, cache e métricas de uso.
- **Commit(s):** commit desta entrega (`fix: preserve media variety in visual rendering`)
- **Origem:** discrepância selecionados/únicos/reutilizações nos vídeos de Medusa, Júlio César e buracos negros.

## 1. O que foi pedido

Localizar perdas entre resultado, seleção, aquisição, cena, beats e render; aproveitar variedade relevante disponível, priorizar a entidade central, evitar novos providers e não alterar scoring antes do diagnóstico.

## 2. Diagnóstico com os três casos reais

| Caso | Seleções reais registradas | Downloads / cache hits históricos | Únicos em `media.json` | Únicos enviados pela timeline antiga |
|---|---:|---:|---:|---:|
| Medusa | 21 ocorrências | 3 / 18 | 3 | 3 |
| Júlio César | 21 ocorrências + 1 card | 3 / 18 | 4, incluindo card | 4 |
| Buracos negros | 21 ocorrências | 0 / 21 | 3 | 2 |

**21 selecionados não significava 21 imagens distintas.** A repetição já começava na seleção: sete cenas recebiam os mesmos três IDs. Download/cache não descartou 18 imagens diferentes nesses casos.

### Pontos responsáveis

1. `_search_scene_with_shortcircuit` ordenava cada cena isoladamente, sem considerar imagens já selecionadas no vídeo. Os mesmos melhores resultados voltavam a entrar. O corte `ranked[:max_images]` também impedia aproveitar outro aprovado se um download falhasse.
2. `build_visual_timeline` aplicava o orçamento de inserções à lista de assets inteira. `order_for_insertion` devolvia somente a primeira imagem em empates ou sem precisão suficiente para um overlay; o restante era descartado, embora pudesse aparecer como fundo. Buracos negros perdeu efetivamente uma das três imagens disponíveis nessa passagem.
3. `visual_beats.plan` registrava movimentos e tempos, mas não ligava beats a assets. `render_collage_segment` mantinha um único fundo por cena. Ter muitos beats significava mover a mesma foto.
4. `RunMetrics.visual_plan` contava IDs em `media.json`, não na timeline renderizada, e estimava reutilizações como beats mais candidatos extras. Por isso os 41/54/55 números não mediam novas seleções nem exposições verificadas de todos os assets.
5. Cache de segmentos era identificado só por cena/duração. Uma imagem substituída com a mesma duração podia continuar usando um segmento antigo.
6. `rerender`/`finalize` carregavam cenas de `chapters.json`, que pode conter tempos ainda zerados. A fonte temporizada correta é `timeline.json`; usar a primeira podia reduzir cenas a 0,5 s e eliminar alternativas pelo limite de duração.

### Cobertura central

- Júlio César: a entidade gerada declarou **“Júlio” e “César” proibidos**. A pesquisa rejeitou o próprio artigo canônico e a mídia rejeitou pinturas com o nome correto. Sem fonte canônica, faltava o alias verificado `Julius Caesar`; bustos com esse título receberam score 0. O restante do vídeo caiu em `church interior`.
- Buracos negros: cenas locais estavam sem assunto/queries. `fill_missing_context` ignorava temas com `is_entity=False`, apesar da fonte canônica `Buraco negro`; a imagem era comparada com a narração inteira, em vez do assunto, e o fallback escolheu fotos de laboratório.
- Medusa: dois IDs selecionados eram águas-vivas, pelo homônimo “medusa”. O contexto mitológico não barrava `jellyfish`/`medusa-phase`.

## 3. O que foi feito e como

| Arquivo | Responsabilidade | Correção |
|---|---|---|
| `stages/visual.py` | Seleção e timeline | Considera uso anterior entre aprovados, mantém prioridade específico/genérico, tenta outro aprovado após falha e separa candidatos de fundo do orçamento de overlays. Preserva ordem manual no caminho existente de swap. |
| `stages/visual_beats.py` | Associação temporal | Liga beats existentes a IDs qualificados por provider e distribui fundos distintos, sem criar buscas ou aumentar o número de beats. |
| `stages/render.py` | Render | Concatena fundos planejados dentro da cena e conserva overlays existentes, com um encode por cena. Normaliza SAR para fontes de aspectos diferentes; em 1080×1920 mantém oversampling de 2×. |
| `pipeline.py` | Cache e integração | Encaminha fundos ao render, inclui identidade/mtime/tamanho/configuração no cache, invalida silencioso/final quando o plano muda e revalida homônimos em mídia antiga. Finalização lê a timeline temporizada. |
| `cli.py` | Rerender | Lê `timeline.json` e registra novas métricas de uso sem chamar pesquisa ou TTS. |
| `stages/entity.py`, `media_rules.py` | Identidade | Descarta negativos contraditórios com o próprio nome, preservando homônimos completos; bloqueia águas-vivas somente no contexto mitológico de Medusa. |
| `stages/visual_context.py` | Contexto | Ancora temas locais apenas quando têm título canônico aceito, recupera alias público da Wikipedia e reutiliza tradução local conhecida para Roma/Rome. |
| `metrics.py` | Observabilidade | Registra `selection_attempts`, `selected_unique`, `available_unique`, `available_occurrences`, `available_by_acquisition`, `visual_assets_unique`, `visual_asset_beat_counts`, detalhes e cenas por asset. IDs não usados recebem zero beats. |
| `tests/test_visual_asset_usage.py`, `tests/test_review_flow.py` | Regressão | Variedade entre cenas, orçamento de overlays, origem/cache, entidade, homônimos, mapas/artefatos, retiming, cortes, cache e render real de três fundos com aspectos diferentes. |

**Scoring, pesos, threshold, providers e regras de licença/resolução permanecem iguais.** Foram corrigidos inputs contraditórios/contexto e desempate por uso dentro do conjunto já aprovado.

`visual_assets_reused` agora conta repetições entre cenas. Persistência de uma foto durante vários beats aparece no contador por asset, sem ser confundida com nova seleção.

## 4. Evidências e validação real

- Métricas originais: `20261001-175131_20261001_por-que-medusa-tinha-serpentes.json`, `20261001-181308_20261001_como-julio-cesar-chegou-ao-pode.json`, `20261001-183657_20261001_como-os-buracos-negros-foram-de.json`.
- Auditoria local `/tmp/opencode/audit_visual_assets.py` cruzou os IDs do `media.json` e `visual_timeline.json`; confirmou a tabela, as igrejas/laboratórios e os homônimos.
- Validação de Júlio César: uma consulta ao **Pixabay existente** capturou candidatos reais; Wikipedia pública confirmou o alias canônico. Nenhum provider novo, nenhum LLM/TTS novo.
- Replay das duas primeiras cenas reais em clips de 6,3 s: **6 seleções, 0 downloads no replay, 6 aquisições em cache, 6 assets únicos disponíveis e 6 únicos renderizados**. Cada asset recebeu um beat; os arquivos são cinco bustos/estátuas de César e uma vista do Fórum Romano.
- IDs renderizados: `pixabay:3357150`, `pixabay:2775427`, `pixabay:2789915`, `pixabay:3616104`, `pixabay:1160739`, `pixabay:6604572`.
- Render efetivo: dois MP4 CPU de **6,333333 s**; diferença para 6,3 s é quantização a 12 fps. Frames de retrato e ruínas de Roma foram inspecionados visualmente.
- A primeira execução real detectou SAR incompatível entre imagens; a normalização foi corrigida e coberta por imagens de proporções diferentes no teste.
- Prova focada inicial: **99 passed** em testes de uso/entidade/contexto/funil/inserções/TTS. Prova adicional de rerender temporizado e testes de assets: **12 passed**.
- Suíte completa final: `python -m pytest -q` — **682 passed**.

Arquivos de auditoria: `/tmp/opencode/cesar-asset-usage.json`, `cesar-replayed-timeline.json`, `cesar-varied-0.mp4`, `cesar-varied-1.mp4`. Os MP4 originais do usuário não foram sobrescritos.

## 5. Status vs PRD §19 e limitações

Fluxo corrigido e verificado com assets reais. Variedade não exige buscas por beat e o orçamento de overlays permanece separado dos fundos. Entidades centrais/locais relacionados têm prioridade quando seus candidatos passam pelos gates existentes.

- Um conjunto com somente três imagens não se transforma em 21 imagens distintas. Se não houver mais aprovadas, o reuso permanece e é identificado como esgotamento do conjunto elegível.
- Cenas curtas podem não comportar todos os candidatos; seus IDs aparecem com zero beats nas métricas. Timing segue quantização de frames, sem alteração da narração.
- O teste real cobre duas cenas de César, não a regeneração completa dos três vídeos. Medusa e buracos negros tiveram os arquivos reais auditados e suas causas cobertas em testes focados.
