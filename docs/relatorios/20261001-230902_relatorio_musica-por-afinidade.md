# Relatório — escolha musical por afinidade e ganho −3 dB

- **Data:** 2026-10-01 23:09 -0300
- **Tipo:** relatorio
- **Escopo:** cama escolhida por afinidade com o tema; ganho padrão −3 dB.
- **Commit(s):** commit desta entrega (`feat: match music bed to video theme`)
- **Origem:** música presente mas sem combinar com o vídeo; pedido de escolha pela IA e volume um pouco maior.

## 1. O que foi pedido

A escolha da música deve considerar o vídeo, não só revezar faixas; volume um pouco acima do atual.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `audio/library.py` | Afinidade | `content_hints` extrai palavras-tema (gênero, título, roteiro); `fit_score` conta sobreposição com título/mood da faixa; `select` prefere maior afinidade, com empate no menos-usado e seed estável. Sem dica, rodízio anterior prevalece. |
| `audio/selection.py` | Handoff | `resolve_audio` monta dicas de gênero, título e roteiro e passa a `select`. Sem chamada LLM: custo zero, determinístico. |
| `config.py`, `audio/selection.py`, `stages/render.py`, `config.example.toml`, `README.md` | Ganho | Default −5 → −3 dB (teto −3 dB); loudnorm e ducking 3:1 intactos. |

## 3. Evidências

- `python -m pytest -q tests/test_audio_library.py tests/test_audio_render.py` — **46 passed**, incluindo preferência por faixa com afinidade e fallback ao rodízio sem dica.
- Correção intermediária: funções novas haviam caído dentro do corpo da classe; classe restaurada e suíte verificada.

## 4. Status vs PRD §19

Sem PRD no repositório. Seleção continua só entre camas calmas aprovadas; voz segue dominante via ducking + limiter.

## 5. Limitações

- Afinidade é lexical (título/mood × tema); não há escuta do áudio nem chamada ao LLM — trocar por escolha via LLM custaria uma chamada por vídeo.
- Faixas sem nenhuma palavra em comum empatam e o rodízio decide, como antes.
