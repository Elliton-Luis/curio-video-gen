# Relatorio — duração flexível (auto padrão, meta nunca corta)

- **Data:** 2026-09-29 14:18 (-03)
- **Tipo:** relatorio
- **Escopo:** fim da duração exata obrigatória: modo Automático/Ilimitado padrão, meta como preferência, ritmo natural sempre
- **Commit(s):** pendente
- **Origem:** pedido do usuário (conteúdo manda; sem compressão artificial; auto padrão)

## 1. O que foi pedido

Remover a ideia de duração exata: modo Automático/Ilimitado padrão
(38 s de conteúdo = vídeo de ~38 s), durações 30/45/60/90/120/180 +
personalizado como **meta** (sentido > ritmo > sem corte > aproximar),
sem mexer em sincronização de cenas/legendas.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `config.py` | padrão + parsing | `DURATION_AUTO = 0.0` vira default; `parse_duration()` aceita `auto/ilimitado/""/0`/nº (5..600, fora disso erro — sem clamp silencioso); `config.toml`/env passam pelo parser |
| `stages/script.py`, `stages/nvidia.py` | roteiro sem corte | auto = `max_chars=None` (prompt "sem duração fixa", só teto de segurança 4000 chars ≈ 5 min); com meta, tamanho é meta; curado/template não truncam no auto |
| `stages/scenes.py`, `stages/visual.py`, `pipeline.py` | cenas pelo conteúdo | novo `scenes_for_length` (3–12); auto usa só tamanho; com meta, `max(meta, tamanho)` — nunca menos cenas que o conteúdo pede |
| `stages/tts.py` | ritmo natural | **removido** o reajuste de rate/velocidade (±30% edge, re-synth espeak): sintetiza uma vez, sempre natural; `target_duration` virou informativo |
| `verify.py` | meta não reprova | duração sempre informativa: auto = "livre (auto)"; com meta, "dentro/fora da meta" com detalhe — vídeo nunca falha por tamanho do conteúdo |
| `cli.py`, `tui.py` | interface | `--duration auto\|30\|…\|Nºs` (antes: só float); TUI `[auto/30/…/outro Nºs, padrão auto]`; mensagens "meta, sem corte" |
| `config.example.toml` | exemplo | `duration_target = 0` comentado |
| `scripts/smoke.sh` | testes | seção 11 (9 cheques): parse, rejeições, cenas por tamanho, prompt sem segundos fixos, verify auto/meta) |

## 3. Evidências

```text
$ ./scripts/smoke.sh  →  73 passaram, 0 falharam (era 64).
E2E mesmo roteiro, narração IA:
  auto    → 45.08 s (modo auto),  voz pt-BR-AntonioNeural, 7 cenas
  meta 30 → 45.08 s (meta: 30s), voz idêntica sem sufixo de ritmo
  (antes, a meta 30 forçaria rate +30%; agora os vídeos são idênticos)
$ verify teste-auto    → 8/8 ("duração livre (auto)")
$ verify teste-meta30  → 8/8 ("duração fora da meta … sem corte")
```

## 4. Status vs PRD §19

Critério de duração evoluiu de regra para indicador (meta nunca reprova);
demais cheques intactos. `metadata.duration_target` 0 = auto (verify lê do
projeto, não da config atual).

## 5. Limitações

- Teto de 4000 chars no auto (anti-runaway da API) é documentado, não meta.
- Cap de 12 cenas: roteiros >~110 s ganham cenas mais longas (ok com
  3 fotos/cena ≈ 4 s/foto).
- Remoção do ajuste TTS muda vídeos antigos se regenerados com meta
  (agora naturais — comportamento desejado, não regressão).
