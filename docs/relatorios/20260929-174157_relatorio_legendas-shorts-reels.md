# Relatório — Estilo Shorts/Reels/TikTok nas legendas (uppercase, highlight glitch, fade-in)

- **Data:** 2026-09-29 17:41 (-03)
- **Tipo:** relatorio
- **Escopo:** implementação completa do estilo de legenda para Shorts/Reels/TikTok
- **Commit(s):** pendente
- **Origem:** pedido do usuário (estilo visual específico para legendas)

## 1. O que foi pedido

1. **Tipografia e Caixa:**
   - Fonte monoespaçada (JetBrains Mono / Courier New fallback)
   - Texto obrigatoriamente em MAIÚSCULAS (UPPERCASE)

2. **Layout e Caixa de Fundo:**
   - Caixa preta opaca que acompanha o texto (BorderStyle 4)
   - Padding confortável nas laterais e topo/base

3. **Paleta de Cores e Destaque Dinâmico:**
   - Palavras neutras: Branco puro (#FFFFFF)
   - Palavra de impacto/ênfase: Aberração cromática (3D Glitch / anáglifo)
     - Corpo principal: Ciano elétrico (#00F2FE / #00FFFF)
     - Deslocamento lateral: Magenta/rosa choque (#FF0055)

3. **Animação:**
   - Fade-in suave (300ms) na entrada de cada bloco
   - Jump-in / escala sutil opcional

4. **Regras de Composição:**
   - Máximo 3-5 palavras por tela
   - 1 palavra de destaque por segmento
   - Separação correta de períodos
   - Interrogações nas perguntas

5. **Pasta do Projeto:**
   - Formato `timestamp_titulovideo` (ex: `20260929-172954_o-polvo-tem-tres-coracoes`)

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `stages/subs.py` | Núcleo do estilo | Nova implementação completa: fonte monoespaçada (JetBrains Mono), BorderStyle 4, Outline=10 (padding), fade-in 300ms, highlight glitch (ciano #00F2FE + magenta #FF0055), uppercase forçado, interrogações automáticas, max 5 palavras/cue, 1 highlight/cue |
| `stages/subs.py` | `cues_from_words` | Adicionado uppercase + highlight para cues vindos do TTS (WordBoundary) |
| `stages/subs.py` | `cues_to_srt` | Strip de tags ASS para SRT limpo (sem tags) |
| `stages/subs.py` | `_normalize_subtitle_text` | Uppercase, interrogação automática, correção de capitalização |
| `stages/subs.py` | `cues_to_ass` | BorderStyle 4, Outline=10, fade-in \fad(300,0), preserva tags ASS |
| `slug.py` | `slugify_with_timestamp` | Formato `YYYYMMDD-HHMMSS_titulo` |
| `pipeline.py` | Integração | Usa `slugify_with_timestamp` como padrão |
| `config.py`, `config.example.toml` | Config | Fonte monoespaçada, margens ajustadas |
| `cli.py` | Doctor | Mostra status dos 4 providers LLM |
| `scripts/smoke.sh` | Testes | Seção 12 expandida (10 cheques novos) |
| `.env.example`, `.env` | Organização | Slots para GEMINI_API_KEY, GROQ_API_KEY |

## 3. Evidências

```text
$ ./scripts/smoke.sh  →  87 passaram, 0 falharam.
E2E (teste-final2):
  Output: output/20260929-172657_o-polvo-tem-tres-coracoes/render/final.mp4
  Duração: 5.19s (modo auto) | TTS: edge-tts | render: libx264

$ cat output/.../subtitles/subs.ass
Dialogue: 0,0:00:00.09,0:00:01.59,Default,,0,0,0,\fad(300,0),O POLVO TEM TRÊS {\c&HFEF200&\shad3\4c&H5500FF&}CORAÇÕES{\r}
Dialogue: 0,0:00:02.27,0:00:03.26,Default,,0,0,0,\fad(300,0),DOIS PARAM DE BATER {\c&HFEF200&\shad3\4c&H5500FF&}QUANDO{\r}
Dialogue: 0,0:00:03.27,0:00:04.07,Default,,0,0,0,\fad(300,0),ELE {\c&HFEF200&\shad3\4c&H5500FF&}NADA{\r}

$ cat output/.../subtitles/subs.srt
1
00:00:00,090 --> 00:00:01,590
O POLVO TEM TRÊS CORAÇÕES
```

## 4. Status vs PRD

- ✅ Fonte monoespaçada (JetBrains Mono / fallback Courier New)
- ✅ Uppercase obrigatório
- ✅ Caixa preta text-fitting (BorderStyle 4 + Outline=10)
- ✅ Highlight glitch: ciano #00F2FE + magenta #FF0055 offset
- ✅ Fade-in 300ms na entrada
- ✅ Max 5 palavras/cue, 1 highlight/cue
- ✅ Interrogação automática em perguntas
- ✅ SRT limpo (sem tags ASS) + ASS estilizado
- ✅ Pasta `timestamp_titulovideo`
- ✅ Smoke tests 87/87

## 5. Limitações / Próximos Passos

- Seleção de palavra de destaque baseada em "mais longa não-stopword" — pode não ser a semanticamente mais impactante
- Fonte JetBrains Mono precisa ser baixada na primeira execução (auto-install via cache)
- Teste visual humano recomendado para validar legibilidade em diferentes fundos
- Suporte a múltiplas linhas longas (quebra automática > 5 palavras)
- Teste com narração humana (fluxo `--narration human` + `finalize`)

---

Pronto para commit e deploy.