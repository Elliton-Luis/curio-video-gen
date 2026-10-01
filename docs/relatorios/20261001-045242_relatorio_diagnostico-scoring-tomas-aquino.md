# Relatório — Diagnóstico de scoring de Tomás de Aquino

- **Data:** 2026-10-01 04:52 (-03:00)
- **Tipo:** relatorio
- **Escopo:** auditar scores reais e documentar causa sem implementar mudanças editoriais.
- **Commit(s):** commit desta entrega documental, `docs: diagnose low media scores in local scenes`
- **Origem:** [análise de scores](../analises/20261001-045242_analise_scores-baixos-tomas-aquino.md).

## 1. O que foi pedido

Demonstrar por que 132 elegíveis tiveram scores baixos contra mínimo 34, decompor candidatos reais, auditar algoritmo/providers/queries, discutir calibração e recomendar observabilidade mínima sem alterar comportamento.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `docs/analises/20261001-045242_analise_scores-baixos-tomas-aquino.md` | Diagnóstico | Fórmula e origem de 34; cinco traces reais; limites por provider; replay, classificação causal e instrumentação recomendada. |
| `docs/README.md` | Índice | Referências à análise e ao relatório. |

Nenhuma mudança de código ou configuração, nenhum teste novo, nenhuma chamada API, nenhum download nem geração de pipeline.

## 3. Evidências e validações

- Métricas da execução `20261001-040048_fale-sobre-a-historia-e-importancia-de-s.json`: 169 normalizados, 138 considerados, 132 elegíveis, seis hard rejects, 132 score rejects, zero selecionados/downloads e 11 sintéticos.
- Artefatos de cenas: todas as 11 vieram de divisão local sem assunto/queries/apoio estruturados.
- `media.json`: 88 rejeições preservadas, das quais 82 são por score. Replay offline de `base_score()` reproduziu **82/82** motivos arredondados.
- Traces: Aristóteles inglês 0; Aristóteles PT e cratera homônima 8,33; abadia Fossanova e prefeitura de Anos 5,77; receptores biológicos na cena de like 12,50; Aquino 2,21.
- Histórico Git: `a290177` introduziu threshold 34; `0b0dad6` manteve valor ao separar núcleo 75/apoio 25, com defesa contra usina térmica.
- Verificação documental: `git diff --check`; nomes/links do índice conferidos. Sem alteração de código, não foi necessário executar suíte de testes.

## 4. Diagnóstico e decisão

Aritmética funciona conforme implementação. Input do fallback local é incompatível com objetivo do scoring: consultas locais não alimentam cena; título em inglês é comparado com narração em português, com denominador inflado por palavras comuns. Consultas ambíguas também recuperam sujeitos errados.

34 não é inalcançável para assuntos curtos e alinhados. Diminuir para 5,77–8,33 admitiria controles negativos reais; zero seria necessário para falso negativo em inglês e admitiria 99 zeros. Não há faixa segura demonstrada. Manter threshold e implementar posteriormente contexto visual compartilhado, identidade/aliases e diagnóstico de parcelas.

## 5. Status vs PRD §19

PRD não disponível. Requisitos desta tarefa cobertos por análise de métricas, código, histórico e candidatos preservados; nenhuma alteração editorial realizada.

## 6. Limitações e pendências

- Cinquenta rejeições por score não têm títulos preservados; apenas histograma. Não é possível reproduzir individualmente todas as 132.
- Não inspecionei imagens; adequação semântica dos exemplos positivos é inferida do tema/título.
- Sem conjunto rotulado por provider/gênero, não há estimativa legítima de score típico global nem ajuste calibrado de threshold.
- Recomendações aguardam implementação posterior; causa demonstrada, investigação encerrada.
