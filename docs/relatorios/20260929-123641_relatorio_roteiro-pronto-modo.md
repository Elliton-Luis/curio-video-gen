# Relatorio — modo roteiro-pronto (organizar mídia sem reescrever)

- **Data:** 2026-09-29 12:36 (-03)
- **Tipo:** relatorio
- **Escopo:** novo modo `from-script`: roteiro pronto vira sequência visual dinâmica, narração intocada
- **Commit(s):** pendente
- **Origem:** pedido do usuário ("Modo: Roteiro pronto + organização de mídia")

## 1. O que foi pedido

Opção em que o usuário fornece o roteiro já pronto e o sistema **não
reescreve nem altera a narração**: preserva o texto exato, divide em
trechos/cenas, pesquisa imagens por trecho, garante cobertura visual total
com sobreposição estilo álbum (foto sobre foto, entradas suaves, Ken Burns
quando há 1 imagem só), e gera timeline visual renderizável pelo pipeline.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `src/curio/stages/visual.py` (novo) | coração do modo | `read_script_file` (verbatim, só aparas), `split_script` + `validate_preserved` (junção das cenas precisa reproduzir o roteiro ou falha em voz alta), `fetch_media_multi` (até N fotos/cena, gate relevância>0, dedup de títulos, reuso da vizinha), `local_queries` (PT→EN offline com dicionário + plural + anti-entidade de início de frase), `build/retime_visual_timeline`, `visual_summary` |
| `src/curio/stages/render.py` | cena-álbum | `render_collage_segment`: base tela cheia (Ken Burns) + cartões com borda branca, rotação/dx-dy, overlay animado (`drop_in/slide_left/slide_right/fade_scale`), reserva de 360 px p/ legendas; 0–1 imagem delega p/ fallback/Ken Burns; 1º teste manual: 6 s/12 s OK em CPU e VA-API |
| `src/curio/pipeline.py` | fiação | `run_pipeline` ganha `provided_script/max_images` (cache invalida cenas+mídia se o texto mudar), `run_script_pipeline` (título=1ª linha), `_build_silent_visual`, fallback p/ divisão local se a NVIDIA cair no modo script, `finalize` replaneja a timeline esticando a última cena |
| `src/curio/cli.py` | entrada | `video-gen from-script ROTEIRO.txt [--slug/--title/--duration/--narration/--max-images/--force]` |
| `src/curio/tui.py` | entrada | opção 9 (roteiro pronto, IA ou 2 passos); ajuda com seção [C]; lista marca "(roteiro pronto)" |
| `src/curio/config.py`, `config.example.toml` | config | `[visual] max_images/overlap` + env `CURIO_VISUAL_*` (1–5) |
| `scripts/smoke.sh` | testes | seções 6 (verbatim, adulteração, plano, fallback, retime) e 8 parcial; 35 cheques |

 Fidelidade: `script_source="provided"`, `mode="script"`, `timeline/visual_timeline.json`
 por trecho (narração original, início/fim, imagens c/ consulta, ordem,
 duração, transição, escala/rotação/dx-dy).

## 3. Evidências

```text
$ ./scripts/run.sh from-script roteiro.txt --narration human --slug teste-roteiro-pronto --max-images 2
Timeline visual: cena 1: 2 img [drop_in]; cena 2: 2 img [drop_in]; … (7 cenas, reuso c/ aviso onde sem mídia)
$ diff roteiro.txt output/…/script/script.txt && echo SCRIPT-IDENTICO  → SCRIPT-IDENTICO
$ ./scripts/run.sh from-script roteiro-salario.txt --narration ai --slug teste-salario-ai
Output: output/teste-salario-ai/render/final.mp4
Duração: 45.08s (alvo: 45.0s) | TTS: edge-tts | render: libx264
$ ./scripts/run.sh verify --slug teste-salario-ai  →  8/8 verificações passaram.
```

SFX sintetizado (swish/tap, pico −35/−36 dB) e mix validado: narração
-6.3 dB antes e depois (não compete). Colagem com 6 estilos em 14 s:
frames em t=1/5/9/13 todos distintos. `smoke.sh`: 47/47.

Achado ao vivo: `scenes: openrouter` — o fallback do doc anterior assumiu
as cenas quando a NVIDIA deu timeout (prova ponta a ponta do retry+fallback).

## 4. Status vs PRD §19

`verify` 8/8 no vídeo IA do modo novo (MP4, streams, 1080×1920, 9:16,
duração ±25%, SRT com 24 blocos). Sem regressão nos fluxos por ideia
(smoke preservado; `generate` inalterado quando sem `provided_script`).

## 5. Limitações

- Heurística offline de consultas erra homônimos (`Empire, Ohio` p/
  "empire") e verbos crus quando faltam traduzidos — documentado; com
  NVIDIA/OpenRouter as `visual_queries` do LLM são melhores.
- `output/` do ambiente foi apagado externamente no meio dos testes
  (só cache sobreviveu); defesa adicionada (`_write_json` recria o
  diretório). Massa de teste refeita em `/tmp/opencode/roteiro-salario.txt`.
- Rotação `rotate` com expressão por frame (tilt_in) validada só por
  sucesso do render + variação de frames, não por inspeção visual.
