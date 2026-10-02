# Relatório — Seleção musical por mood do gênero

- **Data:** 2026-10-02 20:34 (UTC)
- **Tipo:** relatorio
- **Escopo:** evitar camas musicais calmas no volume, mas incoerentes com gênero
- **Commit(s):** `5126939 fix: match music mood to genre adapter`
- **Origem:** relato do usuário e metadata do vídeo de Marco Aurélio

## 1. O que foi pedido

Rever música: alguns assets são bons, mas criam clima inadequado. Cada
gênero deve selecionar trilha com mood próprio.

## 2. Causa confirmada

Marco Aurélio recebeu `Haunting Music 1.wav`, tag `contemplative`, embora
adapter people pedisse “violin classical ambient”/`classical`. Filtro antigo
aceitava qualquer mood em lista calma, e afinidade temática podia empatar
em zero; rodízio determinístico então escolhia faixa calma, porém sombria.

## 3. O que foi feito

| Arquivo | Mudança |
|---|---|
| `stages/editorial.py` | Cada adapter declara `music_mood_terms` junto de query/mood. Exemplos: people `classical/violin/strings`; history `tense/suspense/dramatic`; science `minimal/science/subtle`. |
| `audio/library.py` | `matches_music_mood` filtra mood/título; `AudioLibrary.select` exige termos de mood quando adapter fornece. Calma sozinha não basta. |
| `audio/selection.py` | Faixa cacheada só é mantida se combina com mood do adapter. Query/mood entram metadata e assinatura; troca de adapter força reseleção. Query musical entra hints de afinidade. |
| testes | Cobrem rejeição de `Haunting Music` para people e seleção de faixa clássica compatível. Fixtures de render declaram mood correto por gênero. |

Se biblioteca não tem faixa compatível, Curio renderiza sem música e avisa;
não escolhe mood errado só para preencher trilha.

## 4. Evidências

- Metadata Marco: mood anterior `contemplative`, título `Haunting Music 1.wav`; people esperava mood `classical`.
- `python3 -m pytest tests/test_audio_library.py tests/test_audio_render.py -q` — 49 passed.
- `python3 -m pytest tests/ -q` — **735 passed**.

## 5. Status vs PRD §19

Sem serviço pago ou mudança em mix/ganho/ducking. Adapter decide mood; biblioteca local seleciona e infraestrutura mistura áudio.

## 6. Limitações

Se tags/título da faixa omitirem mood certo, faixa pode ser rejeitada e
vídeo sai sem música. Isso é preferível a cama que quebra a identidade do
vídeo. Autopreenchimento continua opcional e exige `FREESOUND_API_KEY`.
