# Relatório — Volume de música e SFX aumentado

- **Data:** 2026-10-01 18:20 (-03:00)
- **Tipo:** relatorio
- **Escopo:** elevar ganho padrão de música e efeitos pontuais de inserção.
- **Commit(s):** pendente
- **Origem:** música/SFX continuavam baixos após ajuste anterior.

## 1. O que foi pedido

Aumentar o volume do som.

## 2. O que foi feito e como

| Área | Antes | Agora |
|---|---:|---:|
| Música de fundo | -15 dB | -9 dB padrão; configurável de -40 a -6 dB |
| SFX das inserções | -21 dB | -15 dB padrão; limite continua -12 dB |
| Ducking | ativo | inalterado |

Atualizados defaults do runtime, seleção, render, configuração local/exemplo, TUI, documentação e expectativas de teste. Nenhuma frequência/quantidade de evento foi alterada.

## 3. Evidências

```text
python -m pytest -q -p no:cacheprovider tests/test_audio_render.py tests/test_audio_library.py tests/test_insertions.py tests/test_sources_rights.py
117 passed in 2.85s

python -m compileall -q src/curio tests
sucesso
```

## 4. Status vs PRD §19

Não há PRD no repositório para comparar. Ganhos verificados por teste e clamp de configuração revisado.

## 5. Limitações

Não foi renderizado novo vídeo real. O nível percebido ainda varia conforme a masterização da faixa escolhida; o valor pode ser ajustado até -6 dB, mantendo ducking.
