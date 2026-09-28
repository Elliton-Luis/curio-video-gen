# Relatório — mídia dinâmica + teleprompter humano + sincronização real

- **Data:** 2026-09-28 16:19 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** cenas semânticas, Wikimedia+Ken Burns, WordBoundary, teleprompter, finalize+Whisper
- **Commit(s):** este lote (`feat(media)` + `docs`)
- **Origem:** tarefa "Mídia Dinâmica + Teleprompter Humano + Sincronização Real"

## 1. Objetivo

Trocar `roteiro + voz + fundo genérico` por `roteiro + cenas + mídia relacionada
+ movimento + voz + legendas sincronizadas`, e permitir "eu quero narrar"
(teleprompter + áudio humano como fonte de sincronia). Sem web, sem reescrita.

## 2. Implementação

**Cenas** (`stages/scenes.py`): NVIDIA retorna JSON `{title, chapters[]}`
(narration literal PT-BR + `visual_queries`/`visual_intent` em inglês);
validado que a junção reproduz o roteiro (senão divisão local por frases).
Estimativa por 150 wpm. Novo `nvidia.complete_json()` reutilizando o
HTTP/erros existentes. Sem chave: divisão local (sem consultas visuais).

**Providers** (`media/`): abstração `MediaProvider` + `WikimediaProvider`
(sem chave; `filetype:bitmap`, filtros ≥1000px/≤25MB, licença+autor via
`extmetadata`). Registro pronto p/ futuros (Pexels exigiria chave — não
implementado, YAGNI). Seleção por relevância consulta↔título (evita
associações falsas). `cache/media/<prov>/<id>.<ext>` + sidecar `.json`
(proveniência total); nunca rebaixa. `CURIO_MEDIA_PROVIDERS=none` = fallback.

**Montagem** (`render.py`): primitivas por cena — imagem: Ken Burns
(zoom-in/pan alternados, `out_range=mpeg`, sem distorção); fallback:
gradiente+título (identidade MVP); concat `-c copy`; `burn_final`
(silent + ASS + áudio num encode só). `render_video` antigo removido.

**Sincronização** (`tts.py`, `subs.py`): Edge em texto puro +
`boundary="WordBoundary"` → `audio/words.json` (offsets reais, 1ª palavra em
0,121 s — sem offset artificial, §16). `cues_from_words`: quebra em fim de
frase com corpo, limites 5 palavras/36 chars/4,5 s. Sem boundaries (espeak):
modo proporcional legado. Whisper (`transcribe.py`, faster-whisper `base`
CPU/int8, `word_timestamps=True`) → mesma função de agrupamento.

**Teleprompter** (`teleprompter.py`, CLI, TUI): `generate --narration human`
→ `silent.mp4` + `teleprompter.mp4` (ASS 84px, centro, caixa
semi-transparente; tempos por `--wpm`/WPM). `finalize SLUG --audio` valida,
transcreve, legenda, ajusta visual (estende ÚLTIMA cena se áudio maior;
corta cauda + aviso se menor; aviso alto se razão fora de 0,5–2×), merge.

**SSML descartado com prova**: com SSML o Edge retorna boundaries dos
TOKENS DO MARKUP (`speak, voice, break…`) — offsets poluídos. Helpers SSML
(não-lançados) removidos; texto puro + WB.

## 3. Arquivos modificados/criados

Criados: `media/{__init__,providers,cache}.py`, `stages/{scenes,transcribe,
teleprompter}.py`, este relatório. Alterados: `pipeline.py` (2 fluxos +
`finalize_project`), `render.py`, `subs.py`, `tts.py`, `nvidia.py`,
`cli.py` (`--narration`, `finalize`, doctor), `tui.py`, `config.py`,
`config.example.toml`, `install.sh`, `README.md`, `.gitignore` (`cache/`),
versão 0.2.0.

## 4. Testes (comandos, resultados, tempos)

**T1 — IA** (`generate "De onde veio a palavra salário?" --slug salario-cenas`):
5 cenas NVIDIA, 4–5 assets Wikimedia licenciados (CC0, CC BY-SA 4.0/2.0,
domínio público), 82 palavras reais, 17 cues WB, 45,46 s, `verify` **8/8**
(~60 s com mídia; reexecução 7,36 s).

**T2 — cache**: reexecução → 0,26 s, `render: cache`, zero chamadas externas.

**T3 — teleprompter** (`--narration human`, slug salario-humano): silent
40 s (WPM 150) + teleprompter 19 cues; frame lido: texto grande central
legível sem esconder tudo.

**T4 — áudio humano (SIMULADO)**: `finalize` com Edge-Francisca lendo o
roteiro (stand-in, NÃO é voz humana real): whisper 98 palavras, 20 cues,
merge 34,6 s, **8/8**; áudio 5,9 s < estimado → cauda cortada + aviso.
Mecânica validada; falta repetição com gravação real do usuário.

**T5 — sem mídia** (`CURIO_MEDIA_PROVIDERS=none`, local): só fallbacks,
39,34 s, **8/8**; expôs e exercitou o fallback proporcional (Edge fundiu
1 palavra: roteiro=98 vs áudio=97 → aviso + proporcional).

**Mídia**: só Wikimedia foi usado (sem chave, como priorizado). Pexels/
Pixabay/Openverse: nenhuma (exigem chave — fora do escopo útil agora).

## 5. Sincronização: antes × depois

Antes: tempos ∝ nº de caracteres, 1º bloco em 0,150 s fixo. Depois: palavras
reais do TTS (início 0,121 s), agrupadas por frase; humano: palavras reais
do Whisper. Timeline costurada sem buracos (pausas pertencem às cenas).

## 6. Validação visual (§32)

Frames lidos do final: moeda romana + "latim salarium" ✅; sal do Mar Morto
+ "conservar alimentos" ✅; fallback gradiente+título ✅; contrato 1936 +
"designar qualquer [pagamento]" ✅. **Problema encontrado e corrigido**:
foto de fuzileiro moderno numa cena romana (associação falsa) → ranking por
relevância; cena virou fallback honesto + aviso. Observação: pintura clássica
com nudez (Gérôme, domínio público) apareceu no teleprompter — sem filtro
NSFW (backlog). Sem distorção, sem cortes abruptos imotivados, legendas na
base acompanhando a fala.

## 7. Problemas e correções durante os testes

1. `write_subtitles(words=)` inexistente (assinatura esquecida) — corrigido.
2. Ken Burns + VAAPI sem `hwupload` — adicionado `_hw_upload` às 3 primitivas.
3. Concat com paths relativos (resolve no .txt) — absolutos.
4. `yuvj420p` (fotos) × `yuv420p` (fallback) quebrava o burn VAAPI no meio do
   stream — `out_range=mpeg` nas fotos.
5. Pausas entre falas perdidas na timeline (visual 39,1 s < áudio 44,6 s) —
   costura por ponto médio + última cobre até o fim do áudio.
6. Wikimedia 429 em originais — thumbnails `iiurlwidth=1920` + retry/backoff +
   intervalo; buscas ainda 429 sob rajada (fallback honesto cobre).
7. Timeout 60 s estourou numa chamada JSON de cenas — default 120 s.

## 8. Limitações

- Só imagens (sem vídeo de stock; vídeos §9 ficam p/ depois).
- T4 com voz humana real pendente (usuário deve gravar ~45 s e rodar finalize).
- Sem filtro de adequação de conteúdo (nudez clássica possível).
- 429 da Wikimedia sob rajada; Pexels/Openverse/Pixabay não integrados.
- Voz segue AntonioNeural (Edge cargos mantidos, §26/§36).
- Gradução de `media.json` exige mesmos chapter ids ( `--force` regenera tudo).

## 9. Próximos passos

1. Gravação real do usuário + `finalize` (fecha T4 de verdade).
2. Suporte a vídeo-stock (trecho + crop 9:16) quando houver fonte sem chave.
3. Filtro simples de adequação (ex.: pular retratos com nudez via tags).
4. Validador editorial automático (backlog) + Piper TTS (backlog).
