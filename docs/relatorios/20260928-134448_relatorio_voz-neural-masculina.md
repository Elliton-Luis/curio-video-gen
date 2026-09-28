# Relatório — voz neural masculina (edge-tts)

- **Data:** 2026-09-28 13:44 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** trocar TTS padrão espeak-ng por voz neural gratuita sem login
- **Commit(s):** este lote (ver `git log`)
- **Origem:** pedido do usuário ("voz tá muito ruim", masculina, grátis, sem login)

## 1. Decisão: Microsoft Edge TTS

Levantadas as opções gratuitas sem login: Google Translate TTS (não-oficial,
voz feminina, sem escolha de gênero) vs **Edge TTS** (endpoint do Read Aloud,
sem chave/conta, vozes neurais com gênero escolhido). Escolhido Edge TTS com
**`pt-BR-AntonioNeural` (masculina, PT-BR)** — confirmado via
`edge-tts --list-voices` (única masculina PT-BR; demais: Francisca, Thalita).

## 2. Mudanças

| Arquivo | Mudança |
|---|---|
| `src/curio/stages/tts.py` | Provider `edge-tts` (asyncio + `Communicate.save`, mp3→wav via ffmpeg); 1 retry de ritmo via `rate` (±30%); fallback p/ espeak-ng `pt-br` com AVISO no stderr (nunca silencioso); `speed` do resultado vira wpm estimado p/ neural |
| `config.py`, `config.example.toml`, `.env(.example)` | Padrão `edge-tts` + `pt-BR-AntonioNeural`; espeak documentado como offline |
| `scripts/install.sh` | Instala `edge-tts` via pip (best-effort; sem rede, segue espeak) |
| `cli.py` (doctor) | Checa pacote `edge_tts` + informa voz padrão |
| `README.md` | Requisitos (internet só p/ voz neural), tabela de etapas |

Sem dependência nova obrigatória: sem pacote/rede, o pipeline segue 100% local.

## 3. Testes

1. **Voz neural fim-a-fim** — `nvidia-talheres`: TTS `edge-tts/AntonioNeural
   (-22% auto-ritmo)`, áudio 45,07 s, vídeo 45,87 s, `verify` **8/8** (44 s).
2. **Fallback** — voz inexistente: AVISO + espeak `pt-br`, vídeo OK, **8/8**.
   (Achado e corrigido no teste: fallback repassava a voz neural inválida ao
   espeak; agora usa `pt-br`.)
3. **`voices`/`doctor`**: listam `espeak-ng, edge-tts`; doctor com nova linha
   edge-tts OK e defaults `tts=edge-tts/pt-BR-AntonioNeural`.

## 4. Limitações

- Requer internet (sem ela: fallback robótico automático, com aviso).
- `edge-tts` é endpoint não-documentado da MS — se mudar, o fallback segura;
  fixar versão no install seria próximo passo (`pip install edge-tts==7.2.8`).
- Sincronia segue proporcional (edge-tts entrega `WordBoundary` real por
  palavra — melhoria futura de precisão, sem retranscrição).
- Qualidade "neural" atestada por especificação + duração natural; avaliação
  auditiva final é humana (ouvir o `nvidia-talheres/render/final.mp4`).
