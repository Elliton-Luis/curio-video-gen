# Relatório — metrificação por vídeo

- **Data:** 2026-09-28 21:07 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** consumo, tempo e infos de todos os vídeos em `metrics/`
- **Commit(s):** este lote
- **Origem:** pedido do usuário (`timestamp_nomedovideo.json`)

## 1. O que foi feito

- Novo `src/curio/metrics.py`: `RunMetrics` (coletor explícito) grava
  `metrics/<AAAAMMDD-HHMMSS>_<slug>.json` com tempos (total + por etapa),
  durações, tamanhos (final/silent/áudio/teleprompter), provedores/modelos,
  contagens (cenas, cues, assets, fallbacks, reusos), avisos e **consumo**:
  NVIDIA (chamadas + prompt/completion tokens por chamada, incluindo retry),
  TTS (chamadas com provedor + chars, incluindo fallback/retry), mídia
  (buscas por provedor, downloads, bytes, cache_hits) e Whisper
  (chamadas + modelo). Sem segredos no arquivo.
- Instrumentação com param opcional (`metrics=None`): `nvidia.generate_script`
  e `complete_json` (tokens do `usage` por request), `_synth_edge/_synth_espeak`
  (cada síntese real), `search` dos 3 providers, `download_asset`
  (bytes + cache hit), `transcribe`. Pipeline cria o coletor em
  `generate` e `finalize` e salva ao fim (caminho `metrics_file` no metadata).
- `video-gen metrics [--slug]`: backfill a partir do `metadata.json` p/
  vídeos antigos (consumo fica nulo com nota `backfill`, o resto é real).
- `metrics/` no `.gitignore` (dado gerado, como `output/`); `CURIO_METRICS_DIR`
  configura o destino. Smoke estendido (17 cheques).
- README documenta o comando.

## 2. Testes

- Smoke: 17/17 (inclui nome do arquivo, consumo e marca de backfill).
- Backfill: vídeos existentes → 1 arquivo por projeto.
- Rerun live com tudo em cache (`fale-sobre-neuroplasticidade`): consumo
  `nvidia 0 chamadas, tts 1×edge 588 chars, mídia 0 buscas/0 downloads,
  5 assets/1 reuso`, etapas (`tts 4.45 s, render 12.69 s`), tamanhos
  (final 35,6 MB) — exatamente o retrato esperado de execução cached.
- Caminho `finalize` instrumentado igual, mas sem teste live (sem projeto
  humano no momento) — registrado como pendência.

## 3. Limitações

- `metrics/` é gitignored e some entre sessões de ambiente efêmero junto com
  `output/` (dado local, por desenho).
- Backfill não recupera consumo passado (nunca foi medido).
- Custo em R$ não calculado (tokens×preço varia por modelo) — os tokens
  brutos estão lá para conta futura.
