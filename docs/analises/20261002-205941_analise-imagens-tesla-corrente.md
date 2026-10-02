# Análise — Corrente virou rio no vídeo de Nikola Tesla

- **Data:** 2026-10-02 20:59 (UTC)
- **Tipo:** analise
- **Escopo:** métrica `20261002-180209`, coerência das queries Tesla/corrente e imagens selecionadas
- **Commit(s):** `8ce2861`
- **Origem:** relato do usuário

## 1. Veredito

Groq gerou 9 divisões, mas narração não reproduziu roteiro; Curio caiu para
7 cenas locais. Essas cenas perderam sujeito e contexto. Query `Correntes`
casou com pontes e Rio Corrente; query `Tesla` casou com Gigafactory e rua
Nová Tesla. Resultado: nenhuma imagem clara do motor CA ou da corrente
elétrica de Tesla.

## 2. Evidência da métrica e logs

`metrics/20261002-180209_20261002_fale-sobre-nikola-tesla-o-genio.json`:

- 99,4 s; 7 cenas locais; mídia levou 50,42 s.
- 21 assets únicos; 48 candidatos score 0; 33 score-rejected registrados.
- Wikimedia devolveu `Ponte das Correntes, Pontevedra` e `Ponte sobre o Rio Corrente`.
- Wikimedia também devolveu três fotos de Tesla Gigafactory e três fotos da rua Nová Tesla.
- Pixabay devolveu relógios para `time`, campos para `field` e máquinas CNC para `machine`.
- Log `run-20261002-205941-945685.jsonl`: Groq retornou 9 cenas; validador rejeitou narração; Curio usou fallback local com 7 cenas.

## 3. Causa

Fallback local traduziu tokens soltos. `corrente` é ambíguo entre fluxo de
água e corrente elétrica; `Tesla` é nome de pessoa, empresa e rua. Scoring
aceitava sobreposição de uma palavra, mesmo quando o título era sobre outro
referente. Dados da pesquisa conheciam Nikola Tesla, mas não chegavam ao
scoring local.

## 4. Risco

Uma busca apenas por `current` continuará ambígua. Termos compostos
(`alternating current`, `direct current`, `induction motor`) são necessários.
Para imagens de Tesla, títulos precisam distinguir Nikola Tesla de Tesla
Motors e homônimos. Referências têm título, não visão semântica do pixel.
