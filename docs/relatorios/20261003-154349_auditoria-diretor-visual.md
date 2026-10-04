# Relatório — Auditoria do diretor visual e telemetria

- **Data:** 2026-10-03 15:43 (-03:00)
- **Tipo:** análise e correção
- **Escopo:** implementação do diretor visual, 20 métricas mais recentes e 10 relatórios mais recentes; métricas de teste excluídas da avaliação de produto
- **Commit(s):** em andamento

## 1. Conclusão

O diretor visual está implementado no pipeline. Cenas carregam contexto e
representações; providers fornecem metadados; scoring aplica gates técnicos e
semânticos; `media.json`, folha de contato e métricas registram decisões. O
relatório de direção visual registra ainda uma avaliação real do estágio de
mídia com cinco assets contextuais.

A implementação tinha uma falha de integração no fallback local. Um alias
inglês obtido da página de pesquisa entrava nas queries, mas não no contexto
semântico. As queries locais também não eram usadas como evidência de cena.
Resultado observado: 212 candidatos, zero elegíveis e 11/11 visuais sintéticos
no vídeo do Império Otomano.

## 2. Evidência analisada

As 20 métricas mais recentes continham 16 execuções `teste-integracao`, três
registros `proj-review` sem buscas de mídia e um backfill do vídeo real. Os
registros de teste foram ignorados conforme pedido. Os registros `proj-review`
não representam uma geração e não medem a taxa de acerto do diretor.

O backfill mais recente mostrava duração total zero, zero cenas/assets visuais,
decisões vazias e consumo indisponível. O metadata da mesma execução registra
11 cenas, 212 candidatos, zero candidatos retidos, 100% de visuais gerados por
código e rejeições por ausência de evidência do tópico/âncora. O backfill perdeu
dados já disponíveis no metadata.

Os 10 relatórios lidos foram os dois relatórios de fallback LLM, os relatórios
da direção visual (completo e parcial), queries elétricas Tesla, aprendizado
contável, mood musical por gênero, busca fresca, âncora de pessoa/tópico e
âncora visual. Eles confirmam implementação estrutural, gates conservadores,
CLIP opcional sem pesos reais e ausência de geração completa com mídia real na
validação anterior.

`video-gen doctor` confirmou a causa ambiental do fallback: nenhum provider LLM
tem chave, `CURIO_CONTACT` não está definido e Pixabay, Unsplash e Pexels não
têm chaves. NASA, Met, AIC e Wikimedia aparecem configurados, mas a busca
observada não encontrou candidato que passasse os gates.

## 3. Problema 1 — evidência semântica incompleta no fallback local

Capítulos locais já carregavam queries inglesas confirmadas por link de idioma,
mas `fill_missing_context()` não copiava esse nome para `video_context`, que é
a fonte do scoring de tópico. Além disso, `attach_video_context()` removia os
termos locais de `visual_entities`, e scoring não consultava `visual_queries`
como evidência de cena.

Corrigi as duas lacunas. Nomes confirmados entram em `primary_entities` e
`aliases`; fallback local usa suas queries como frases completas de cena.
Correspondência de uma palavra continua sem valor probatório. README atualizado
com esse comportamento.

## 4. Problema 2 — backfill apagava métricas visuais e duração

O metadata já persiste `visual_report`, cenas, mídia, decisões por candidato,
horários por etapa e duração de processamento. `backfill_from_metadata()` criava
uma instância vazia de `RunMetrics` e zerava as seções de consumo, mas também
deixava zerados os campos visuais e `total_seconds`, mesmo quando os valores
eram recuperáveis.

Corrigi `backfill_from_metadata()` para recompor contagens e IDs visuais,
decisões por cena e `visual_report` do metadata. Duração total e timestamps vêm
de `processing_time_seconds` e `created_at`. Contadores de requests, tokens e
tentativas sem registro persistido continuam nulos. README documenta essa
distinção.

## 5. Validação

Gerei novamente a métrica com `video-gen metrics --slug
history/20261003_imperio-otomano-como-surgiu-com`. Backfill agora mostra 11
cenas, 36 beats, 11 decisões e o resumo visual completo. Duração total bate
com metadata: 180,6 s. Requests e tokens seguem nulos no backfill; a execução
live guarda esses contadores separadamente.

## 6. Problema 3 — asset contextual repetido em excesso

A geração live após a correção selecionou asset real em 10/11 cenas. Porém,
repetiu o mesmo mapa Wikimedia do Império Otomano em dez cenas. Esse asset tem
evidência contextual de cena 35/100; ranking apenas desempata por uso anterior
e ainda o escolhe quando é o único candidato elegível. Métricas mostram dois
assets únicos e nove reusos.

A busca levou 104,32 s, consultou 46 combinações query/provider e teve três
timeouts. Reuso de resultados internos reduziu trabalho; falhas HTTP da
Wikimedia ainda prolongaram a busca. A repetição por evidência contextual baixa
é o próximo problema a corrigir.

## 7. Validação de geração

Após corrigir aliases e queries locais, nova geração produziu 10/11 cenas com
asset real, contra zero na execução anterior. Um visual sintético cobriu cena
sem candidato. `video-gen verify` passou **8/8**. O render levou 73,65 s.

## 8. Repetição de assets: causa e correção

Na execução baseline de 11 cenas, o mesmo mapa contextual do Império Otomano
foi selecionado em dez cenas: 2 assets únicos, 9 reusos, 10 cenas com mídia
real e 1 sintética. O fluxo interrompia a busca ao encontrar evidência forte
mesmo quando o resultado já fora usado; a deduplicação era por `provider:id`,
e a preferência por uso anterior só desempatatava o ranking. Assim, outras
representações podiam ficar sem consulta, e resultados espelhados por
provedores diferentes podiam parecer distintos.

A correção mantém os gates e faz a busca continuar quando só há candidatos
usados, percorrendo representações específicas antes das contextuais e
genéricas. Assets novos são selecionados antes dos usados; visual sintético
local é tentado antes do reuso. `source_url` canônica unifica duplicatas entre
provedores e queries, preservando IDs qualificados como fallback. O relatório
agora separa assets únicos, reusos, cenas com asset novo/reutilizado/sintético,
razão de reuso e queries que só retornaram duplicatas.

Regressões reproduzem cenas do mesmo tópico com mapas compartilhados e
representações de evento próprias, além do cenário sem alternativa. A suíte
completa passou: **782 testes**.

## 9. Comparação real antes/depois

O artefato original não está neste checkout. Para comparar a mesma escala e o
mesmo tópico, gerei um roteiro histórico equivalente, dividido localmente em
11 cenas (LLM de planejamento indisponível), e executei a aquisição e o render
silencioso. Esta validação não é replay byte a byte do roteiro original.

| Medida | Baseline original | Execução após correção |
|---|---:|---:|
| Cenas | 11 | 11 |
| Cenas com asset real | 10 | 5 |
| Assets reais únicos | 2 | 9 |
| Cenas com asset novo | — | 5 |
| Cenas com asset reutilizado | 9 | 0 |
| Ocorrências de reuso | 9 | 0 |
| Razão de assets únicos | 20% (2/10 cenas reais) | 100% (9/9 ocorrências reais) |
| Cenas sintéticas | 1 | 6 |
| Queries abandonadas só por duplicatas | não medida | indisponível no backfill antigo |

A seleção por cena ficou assim. Todas as queries listadas foram consultadas
contra os providers ativos `AIC`, `Met`, `NASA` e `Wikimedia`; após surgir uma
opção nova com prova suficiente, as de prioridade menor ficaram sem consulta.
Cada resultado real venceu pela ordem de relevância da cena, relevância do
tópico e qualidade; os valores são os scores/auditoria persistidos.

| Cena | Queries tentadas | Seleção e motivo |
|---|---|---|
| 1 | Império Otomano Anatólia; Império Otomano; Ottoman Empire; Anatólia; frontier | NASA, Istanbul, 92,25; melhor opção elegível para localização/contexto |
| 2 | Império Otomano Galípoli; Império Otomano | Wikimedia, bandeira cronológica otomana, 100; passou tópico e cena |
| 3 | Império Otomano Kosovo; Império Otomano; Ottoman Empire | Wikimedia, Ottoman Empire (1876), 100; passou tópico e cena |
| 4 | 8 queries: Império Otomano gold; Império Otomano; Ottoman Empire; pintura/fresco/gravura/woodcut; gold | Card local; nenhuma alternativa passou os gates semânticos |
| 5 | 3: Império Otomano Istambul; Império Otomano; Ottoman Empire | Card local; nenhuma alternativa passou os gates semânticos |
| 6 | 7: Império Otomano Ridaniya; Império Otomano; Ottoman Empire; Ridaniya; city; laboratory; microscope | Card local; nenhuma alternativa passou os gates semânticos |
| 7 | 8: Império Otomano Mohács; Império Otomano; Ottoman Empire; pintura/fresco/gravura/woodcut; Mohács | Card local; nenhuma alternativa passou os gates semânticos |
| 8 | 7: Império Otomano janizaros; Império Otomano; Ottoman Empire; janizaros; formavam; laboratory; microscope | Card local; nenhuma alternativa passou os gates semânticos |
| 9 | 6: Império Otomano Preveza; Império Otomano; Ottoman Empire; Preveza; laboratory; microscope | Card local; nenhuma alternativa passou os gates semânticos |
| 10 | Império Otomano empire | Wikimedia, mapa histórico C. 1897, 100; melhor score elegível |
| 11 | Império Otomano Primeira | Wikimedia, mapa ferroviário otomano na Primeira Guerra, 76,75; passou os gates |

Houve **zero reusos**, então nenhuma cena entrou no fallback de asset anterior;
as cenas sem asset novo tentaram 1–8 queries/provider antes de usar o visual
local. A busca levou 185,68 s, recebeu 5 timeouts e sofreu retries HTTP da
Wikimedia. Só 5/11 cenas encontraram asset real acima dos gates; seis ficaram
sintéticas porque o planejamento local extraiu intenções rasas como “gold” e
o ambiente não tinha chaves de Pixabay/Unsplash/Pexels. Isso mantém relevância
e evita repetir o mapa, mas deixa duas melhorias mensuráveis: reduzir retries
do provider lento e melhorar representações locais por cena sem adicionar
chamadas LLM.

Métricas pós-correção: `metrics/20261004-084933_history_20261004_validacao-diversidade-otomana.json`.
O cache de resultados mostra 6 candidatos duplicados, mas metadata antiga não
marca quais queries retornaram somente duplicatas; o campo fica nulo em
backfill, em vez de publicar zero enganoso. Execuções live novas registram esse
contador e anotam as queries no audit. Render silencioso terminou; TTS foi
omitido (`--narration human`).

## 10. Limitações

Pixabay, Unsplash e Pexels não tinham credenciais e Wikimedia respondeu erros
HTTP/retries; o resultado real mede os providers disponíveis neste ambiente.
CLIP real segue fora da instalação e sem pesos; continua opcional.
