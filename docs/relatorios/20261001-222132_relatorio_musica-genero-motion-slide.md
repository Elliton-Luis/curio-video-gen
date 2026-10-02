# Relatório — música por gênero, motion suave e slides de galeria

- **Data:** 2026-10-01 22:21 -0300
- **Tipo:** relatorio
- **Escopo:** direções musicais (violino clássico/tenso leve), ganho −7 dB, deriva de câmera sem tremor e transições slide.
- **Commit(s):** commit desta entrega (`feat: genre music beds, drift motion and slide transitions`)
- **Origem:** pedido de músicas estilo TikTok mais altas, violino em pessoas, tensão leve em histórias e fim do tremor na imagem.

## 1. O que foi pedido

Baixar faixas marcantes por gênero (people com violino/clássico, histórias com tensão leve), aumentar o som, eliminar o tremor da imagem, mover levemente e transicionar como slide rápido de galeria com blur.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `audio/library.py` | Direções | `people` busca `violin classical ambient`, `history` busca `tense ambient`; moods `classical/tense/suspense` e títulos com violino/strings/sax/cinematic passam no filtro de cama calma; lista disruptiva intacta. |
| `config.py`, `audio/selection.py`, `stages/render.py`, `config.example.toml`, `README.md` | Ganho | Default música −9 → −7 dB, com ducking e limiter intactos; voz segue dominante. |
| `stages/render.py` | Motion | `_beat_zoompan` virou deriva linear unidirecional (zoom 5% ou pan lateral, alternando por variant); removida a oscilação senoidal por beat, causa do tremor. |
| `pipeline.py` | Transições | `GENRE_XFADE` todo em família slide (`slideright/wipeleft/smoothleft`); durações por gênero inalteradas. |
| Biblioteca local | Acervo | Baixadas 4 faixas `classical` em people e 4 `tense` em history via Freesound (só CC0/CC BY); biblioteca passa a 10 faixas por gênero. |

## 3. Evidências

- `python -m pytest -q tests/test_audio_library.py tests/test_audio_render.py tests/test_visual_asset_usage.py tests/test_media_museums.py` — **67 passed**.
- Render real CPU em `/tmp/opencode/mvfinal.mp4` (2 cenas, slide 0,3 s, cama clássica a −7 dB): frame em 2,85 s mostra o slide lateral no meio; `volumedetect` média −29,8 dB, pico −12,7 dB, sem clipping.
- Teste unitário garante expressões sem `sin/cos` e lineares em `on`.
- Faixas novas: `Orchestral-B1`, `Renaissance Strings`, `Peaceful Ambiance Theme`, `Harmonic Ambient Classical Theme` (people); 4 tensas em history.

## 4. Status vs PRD §19

Sem PRD no repositório. Voz continua dominante via ducking + limiter; beats/métricas de variedade inalterados; providers e scoring intactos.

## 5. Limitações

- Sons trend específicos do TikTok (ex.: covers de sax viralizados) são protegidos por copyright e não entram na biblioteca CC0/CC BY; o filtro agora aceita títulos com sax quando surgirem no Freesound.
- Faixas `tense` são avaliadas por título/mood, não por análise do áudio; `INTENSE AMBIENT RHYTHMIC PULSE` pode pesar — se pesar, remova o arquivo do acervo.
- Blur de movimento na transição não foi implementado: `xfade` não tem transição com blur e `gltransition` exigiria OpenGL (dependência nova, fora do escopo); o slide rápido dá a leitura de galeria.
