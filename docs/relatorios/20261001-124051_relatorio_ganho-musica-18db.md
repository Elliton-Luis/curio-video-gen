# Relatório — Ganho musical em −18 dB

- **Data:** 2026-10-01 12:40 (-03:00)
- **Tipo:** relatorio
- **Escopo:** subir cama musical mantendo ducking e faixa válida.
- **Commit(s):** pendente
- **Origem:** pedido do usuário (fundo ainda baixo).

## 1. O que foi pedido

Aumentar mais o som da música de fundo.

## 2. O que foi feito e como

| Arquivo / área | Responsabilidade | Decisão e implementação |
|---|---|---|
| `src/curio/config.py`, `config.toml`, `config.example.toml`, `stages/render.py`, `audio/selection.py` | Default de ganho | −21 → −18 dB (faixa −40..−15 e ducking intactos). |
| `tests/test_audio_render.py`, `tests/test_audio_library.py` | Regressão | Teste de default atualizado; teste de assinatura usa −20 para não colidir. |
| `README.md`, `docs/README.md` | Documentação | Ganho documentado em −18 dB. |

## 3. Evidências (comandos + números reais, nunca inventados)

- `python -m pytest -q -p no:cacheprovider tests/test_audio_library.py tests/test_audio_render.py tests/test_audio_cli.py` → **43 passed** (teste de ducking falhou 1x isolado por flakiness de timing e passou no retry e na repetição).
- `./scripts/run.sh doctor` → áudio OK (`gain=-18dB`).

## 4. Status vs PRD §19

Sem PRD no repositório. Critério do pedido coberto por testes e doctor; sem geração nova (só default alterado, sem lógica).

## 5. Limitações

- −18 dB com ducking continua cama, não protagonista; acima disso brigaria com a voz.
