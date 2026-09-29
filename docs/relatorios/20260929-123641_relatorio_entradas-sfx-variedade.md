# Relatorio — variedade de entradas + SFX discretos

- **Data:** 2026-09-29 12:36 (-03)
- **Tipo:** relatorio
- **Escopo:** refino do modo roteiro-pronto: sem repetição consecutiva, 2 novas entradas, SFX em ~1/3 das inserções
- **Commit(s):** pendente
- **Origem:** pedido do usuário (variar deslizamento/escala/fade/rotação; SFX baixos em algumas inserções, nunca todas, nada exagerado)

## 1. O que foi pedido

1. Nunca repetir o mesmo efeito em inserções consecutivas (anti-mecânico).
2. Variar entre entradas simples: deslizamento, escala, fade, pequena rotação.
3. SFX discretos e baixos em **algumas** inserções (presença/movimento, sem competir com a narração); algumas entradas acontecem naturalmente.
4. Nada complexo ou exagerado: simplicidade, variedade, naturalidade.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `stages/visual.py` | sequência global | 6 estilos (`drop_in/slide_left/slide_right/fade/scale_in/tilt_in`), ordem embaralhada com seed do slug (reprodutível), contador global atravessa cenas — vizinhas nunca repetem; `"fade_scale"` antigo ainda renderiza (compat) |
| `stages/visual.py` | plano SFX | `_assign_sfx`: 1 overlay a cada 3 (`SFX_EVERY`), alternando `swish`/`tap`, ganho −26 dB, 0.35 s, instante absoluto `at`; base e cenas de 1 foto nunca têm SFX; `retime` preserva tipos e recalcula `at` |
| `stages/render.py` | novas entradas | `scale_in` (cresce 0.88→1.0 com `scale eval=frame` + dissolve), `tilt_in` (assenta +8°→base com `rotate` por frame + dissolve); `fade` estático; posições sempre na metade superior (reserva 360 px de legendas) |
| `stages/render.py` | som | `build_sfx_track` (swish=ruído rosa lowpass 750–950 Hz; tap=sine 140–160 Hz; fades in/out, `adelay`, `amix normalize=0`, `apad`) + `mix_sfx` (soma sem tocar no volume da narração); sem eventos → None (sem custo) |
| `pipeline.py` | fiação | `_sfx_track_for` + `_narration_with_sfx` (gera `audio/sfx.wav` e `audio/mixed.wav`); fluxo IA mistura antes do `burn_final` (sem mudar `burn_final`); `finalize` replaneja e mistura na voz humana; artefatos `sfx` no metadata |
| `config.py`, `config.example.toml` | liga/desliga | `visual_sfx` (`[visual] sfx`, `CURIO_VISUAL_SFX=0` desliga) |
| `scripts/smoke.sh` | testes | seção 8 (6 cheques): sem repetição em 3 cenas, 6 overlays cobrem os 6 estilos, SFX parcial c/ `at` nos limites e tipos alternados, `sfx=False` desliga, retime preserva |

## 3. Evidências

```text
$ ./scripts/smoke.sh  →  47 passaram, 0 falharam.
E2E IA (teste-salario-ai, 45.08 s, edge-tts):
  overlays: slide_right(swish) slide_left drop_in tilt_in(tap) scale_in fade
            slide_right(swish) slide_left drop_in  →  vizinhas distintas ✓
  sfx.wav: mean −66.6 dB, max −35.1 dB (discreto) ✓
  narração: pico −6.3 dB antes = depois do mix (não compete) ✓
  verify: 8/8 ✓
Colagem 14 s c/ 6 estilos (CPU): duração exata, frames t=1/5/9/13 distintos ✓
```

## 4. Status vs PRD §19

Sem impacto nos cheques (áudio continua 1 trilha AAC; duração e legendas
inalteradas). `metadata.visual.sfx` + artefato `sfx` documentam o som.

## 5. Limitações

- Animação do `tilt_in` validada por sucesso de render + variação de
  frames, não por inspeção visual quadro a quadro.
- SFX só existe no modo roteiro-pronto (`max_images>1`); fluxos por ideia
  (1 foto/cena) não têm inserções para pontuar — extensão futura se fizer
  sentido.
- Micro-variação de `entry_dur` (±0.1 s determinística) é sutil por
  desenho; exageros foram recusados conforme o pedido.
