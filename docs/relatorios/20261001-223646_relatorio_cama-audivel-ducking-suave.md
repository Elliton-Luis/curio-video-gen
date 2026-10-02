# Relatório — cama audível com normalização e ducking suave

- **Data:** 2026-10-01 22:36 -0300
- **Tipo:** relatorio
- **Escopo:** música como elemento principal audível sem cobrir a voz.
- **Commit(s):** commit desta entrega (`feat: normalize music bed and soften ducking`)
- **Origem:** cama inaudível no vídeo de Santo Antônio (faixa a −9 dB + ducking 5:1).

## 1. O que foi pedido

Música tem que existir e ser audível como elemento principal do vídeo.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `stages/render.py` | Cama | `loudnorm=I=-21:TP=-2:LRA=11` antes do ganho: faixas de volumes diferentes chegam ao mesmo patamar; limite `-40..-3 dB` preservado. |
| `config.py`, `audio/selection.py`, `stages/render.py`, `config.example.toml`, `README.md` | Ganho | Default −7 → −5 dB; teto configurável −6 → −3 dB. |
| `stages/render.py` | Ducking | `sidechaincompress` 5:1 → 3:1 com threshold 0,025 → 0,04: a voz continua afundando a cama, mas ela permanece presente. Limiter intacto. |

## 3. Evidências

- Fixture voz 2 s + pausa 2 s com violino real: pausa com cama antiga (−9, sem norm, sem duck) −33,2 dB → nova (−5, norm, duck 3:1) −29,2 dB (**+4 dB**); voz domina o trecho falado (−23,8 dB, pico −19,2).
- `python -m pytest -q tests/test_audio_library.py tests/test_audio_render.py` — **45 passed**, incluindo o teste de ducking (cama cai sob voz e volta na pausa).

## 4. Status vs PRD §19

Sem PRD no repositório. Voz segue dominante (picos ~10 dB acima da cama); limiter a 0,97 evita clipping.

## 5. Limitações

- Passagens muito quietas da própria faixa continuam quietas (dinâmica da música preservada).
- Vídeos já renderizados (ex.: Santo Antônio) precisam de `rerender` para herdar o novo mix.
