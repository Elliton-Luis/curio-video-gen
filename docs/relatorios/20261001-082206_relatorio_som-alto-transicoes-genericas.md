# Relatório — Som audível, transições com efeito e cascata genérica

- **Data:** 2026-10-01 08:22 (-03:00)
- **Tipo:** relatorio
- **Escopo:** ganhos audíveis de música/inserts, xfade por gênero, genéricos por gênero e cartões nunca vazios.
- **Commit(s):** pendente
- **Origem:** pedido do usuário (fundo inaudível, transições sem efeito, poucas imagens, cards vazios).

## 1. O que foi pedido

Aumentar música de fundo e sons de inserção, colocar efeitos nas transições, tentar genérico (igreja, biblioteca) quando específico falha, e nunca exibir cartão vazio.

## 2. O que foi feito e como

| Arquivo / área | Responsabilidade | Decisão e implementação |
|---|---|---|
| `src/curio/config.py`, `config.toml`, `config.example.toml`, `stages/render.py`, `audio/selection.py` | Ganhos | Música −24 → −21 dB; insert −30 → −24 dB; SFX sintético −26 → −22 dB. Faixas e ducking intactos. |
| `src/curio/stages/render.py`, `pipeline.py` | Efeitos | `concat_with_transitions` aceita `kinds` (`fade`, `fadeblack`, `fadewhite`, `wipeleft`, `slideright`, `smoothleft`); mapa por gênero via `_genre_transition_kinds`; assinatura de cache inclui kinds. |
| `src/curio/stages/visual.py`, `scoring.py` | Cascata genérica | `_generic_queries()` por gênero (`people`/`history`/`mythology`: igreja, biblioteca, manuscrito…); `generic_score()` pontua genérico contra próprio termo com mesmo mínimo 34, após específicas; threshold e veto intactos. |
| `src/curio/stages/visuals.py` | Cartão nunca vazio | Sem assunto, cartão/spotlight mostra primeira frase da narração em vez de "—". |
| `src/curio/audio/library.py` | Biblioteca por gênero | Queries simplificadas por gênero (as longas retornavam 0 resultados); todos os 6 gêneros com ≥5 faixas CC0/CC BY, sem redownload (auto_fill só abaixo do mínimo). |
| `tests/` | Regressão | Cascata por gênero, partição genérica, kinds por gênero, ganho default, ajuste de teste de assinatura colidido. |
| `README.md`, `docs/README.md` | Documentação | Ganho −21 dB, efeitos por gênero, cascata genérica e cartão com fallback documentados. |

## 3. Evidências (comandos + números reais, nunca inventados)

Métricas consultadas primeiro: `metrics/20261001-064759` (mídia 87,22 s; 192 normalizados; 49 acima; 33 selecionados; 6 downloads + 27 hits; 0 sintéticos).

- `python -m pytest -q -p no:cacheprovider` → **629 passed**.
- `./scripts/run.sh doctor` → áudio OK (`gain=-21dB`), biblioteca people 6 + 5 + 5.
- Biblioteca: 6 gêneros com 5–6 faixas cada (só CC0/CC BY; NC/ND/SA e sampling+ recusados).
- Geração real `--duration 30 "Quem foi São Tomás de Aquino?"` → 1/3 real + 2 cards, `music.gain_db=-21`, transições `[0.04, 0.32]`, verify 8/8, 286 s totais.
- Genérico coberto por teste (igreja aceita após específica rejeitada); nesta geração as específicas bastaram.

## 4. Status vs PRD §19

Sem PRD no repositório. Critérios do pedido cobertos por testes e geração real; genérico entra marcado e nunca à frente de específica.

## 5. Limitações

- Genérico em outro idioma ainda zera; cartão com texto da cena permanece.
- xfade restrito ao conjunto do ffmpeg; desconhecido cai em `fade`.
- SFX de biblioteca só em inserções; empate de scores bloqueia inserção.
