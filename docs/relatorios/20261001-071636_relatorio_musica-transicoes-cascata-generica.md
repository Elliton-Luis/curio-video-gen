# Relatório — Música audível, transições com efeito e cascata genérica

- **Data:** 2026-10-01 07:16 (-03:00)
- **Tipo:** relatorio
- **Escopo:** ganho musical audível, efeitos xfade por gênero, genéricos por gênero com núcleo próprio e cartões nunca vazios.
- **Commit(s):** pendente
- **Origem:** pedido do usuário (música inaudível, transições sem efeito, poucas imagens, cards vazios).

## 1. O que foi pedido

Aumentar som da música, colocar efeitos nas transições, tentar genérico (igreja, biblioteca) quando específico falha, e nunca exibir cartão vazio tipo "Palavra do Dia ---".

## 2. O que foi feito e como

| Arquivo / área | Responsabilidade | Decisão e implementação |
|---|---|---|
| `src/curio/config.py`, `config.toml`, `config.example.toml`, `stages/render.py` | Ganho musical | Default −30 → −24 dB (faixa −40..−15 intacta; ducking intacto). |
| `src/curio/stages/render.py`, `pipeline.py` | Efeitos de transição | `concat_with_transitions` aceita `kinds`; mapa por gênero (`mystery`/`mythology` fadeblack, `science` slideright, resto fade); assinatura de cache inclui kinds. |
| `src/curio/stages/visual.py`, `scoring.py` | Cascata genérica | Genéricos por gênero (`people`/`history`/`mythology`: igreja, biblioteca, manuscrito…); genérico pontua contra próprio termo com mesmo mínimo 34, entra depois das específicas; threshold e veto intactos. |
| `src/curio/stages/visuals.py` | Cartão nunca vazio | Sem assunto, cartão/spotlight mostra primeira frase da narração em vez de "—". |
| `tests/` | Regressão | Cascata por gênero, partição genérica, kinds por gênero, ganho default, ajuste de teste de assinatura que colidia com novo default. |
| `README.md`, `docs/README.md` | Documentação | Ganho −24 dB, efeitos por gênero, cascata genérica e cartão com fallback documentados. |

## 3. Evidências (comandos + números reais, nunca inventados)

Métricas consultadas primeiro: `metrics/20261001-064759` (mídia 87,22 s; 192 normalizados; 83 rejeitados nota 0; 49 acima; 33 selecionados; 6 downloads + 27 cache hits; 0 sintéticos).

- `python -m pytest -q -p no:cacheprovider` → **629 passed**.
- `./scripts/run.sh doctor` → áudio OK (`gain=-24dB`), biblioteca people 6 + 5 + 5.
- Geração real `--duration 30 "Quem foi São Tomás de Aquino?"` → 2/3 cenas com asset real, `music.gain_db=-24`, transições `[0.04, 0.32]`, 118 s totais.
- Teste de assinatura existente que fixava ganho antigo ajustado para valor distinto (−18), sem mudar lógica.

## 4. Status vs PRD §19

Sem PRD no repositório. Critérios do pedido cobertos por testes e geração real; genérico entra marcado (`generic: true`, `layers: base-generic`) e nunca à frente de específica.

## 5. Limitações

- Genérico honesto ainda pode zerar se título não contiver termo (ex.: título em outro idioma); aí cartão com texto da cena permanece.
- Efeitos xfade limitados ao conjunto do ffmpeg (`fade`, `fadeblack`, `fadewhite`, `wipeleft`, `slideright`, `smoothleft`); desconhecido cai em `fade`.
- Ganho −24 dB com ducking: audível sem competir; ajuste fino fica em `config.toml`/TUI.
