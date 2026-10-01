# Relatório — corrigir aspas do título no filtro FFmpeg

- **Data:** 2026-10-01 15:46 -0300
- **Tipo:** relatorio
- **Escopo:** impedir falha do filtergraph quando título contém apóstrofo.
- **Commit(s):** pendente
- **Origem:** falha de render do projeto `20261001_de-onde-veio-a-palavra-escola`

## 1. O que foi pedido

Resolver o erro final de render `ffmpeg (av1_vaapi) falhou: No such filter: '0'` após mídia, TTS e legendas concluírem.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `src/curio/stages/render.py` | Escapar título em `drawtext` | Apóstrofo agora usa sequência de aspas FFmpeg que fecha e reabre o valor (`'\''`), em vez de `\'` dentro da string entre aspas. |
| `tests/test_audio_render.py` | Regressão | Renderiza com FFmpeg CPU e ASS junto a título `Como surgiu a palavra 'escola'?`; garante que o filtergraph real compila e produz MP4. |

## 3. Evidências

- Log `output/etymology/20261001_de-onde-veio-a-palavra-escola/logs/run-20261001-183104-743194.jsonl`: fontes, título e 8 cenas gerados; mídia terminou em 69,4 s; Edge TTS produziu 56,18 s de áudio; 44 cues gerados; erro ocorreu em `burn_final`, encoder `av1_vaapi`.
- `script/title.txt` contém `Como surgiu a palavra 'escola'?`.
- Não há JSON de `metrics/` para esta execução; falha ocorreu antes da gravação final das métricas. Run log preserva os tempos das etapas.
- Reproduzi `No such filter: '0'` com ASS + `drawtext` e título contendo apóstrofos. Após a correção, o teste de render real passou.
- `python -m pytest -q tests/test_audio_render.py` — **9 passed**.

## 4. Status vs PRD §19

Correção preserva título literal e filtro temporal `between(t,0,5)`; afeta somente escaping de apóstrofos no texto do título. Não muda backend nem altera artefatos anteriores.

## 5. Limitações

- O teste real usa encoder CPU; o erro foi reproduzido no parser do mesmo filtergraph, enquanto a execução original usou AV1 VAAPI. A diferença de encoder não altera a análise sintática do filtro.
