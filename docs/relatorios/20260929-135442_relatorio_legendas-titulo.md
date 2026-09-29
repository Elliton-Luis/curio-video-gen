# Relatorio — legendas pesadas com caixa + título-pergunta IA

- **Data:** 2026-09-29 13:54 (-03)
- **Tipo:** relatorio
- **Escopo:** apresentação das legendas (fonte/caixa, sincronia intacta) + título-pergunta gerado pela IA e queimado ≥5 s
- **Commit(s):** pendente
- **Origem:** pedido do usuário (duas melhorias no vídeo)

## 1. O que foi pedido

1. Legendas: fonte pesada/larga (estilo Archivo Black), texto branco,
   fundo preto sólido com padding generoso acompanhando o bloco (nunca
   faixa total), embaixo com margens; só visual, sem tocar sincronia.
2. Título IA em forma de pergunta (curto, curioso, sem clickbait, com
   `?`, não-cópia da 1ª frase) nos metadados + render (≥5 s na tela),
   separado de narração/legendas.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `stages/subs.py` | fonte + caixa | `ensure_display_font()`: Archivo Black (OFL) via fontconfig; instala 1ª vez em `~/.local/share/fonts` (cache/fonts + download GitHub); fallback DejaVu Bold — nunca fatal. `cues_to_ass`: BorderStyle 3 + cores opacas + Outline 10 (= padding, provado no libass local) + margens 80; cantos arredondados inexistentes no ASS (limitação registrada) |
| `stages/subs.py` | sincronia | `build_cues/cues_from_words/chunk` intocados; só linha de estilo muda |
| `stages/nvidia.py` | prompt de título | `TITLE_SYSTEM_PROMPT` (pergunta, ≤55 chars, natural, sem clickbait, JSON puro); reusa `complete_json` (retry + fallback OpenRouter) |
| `stages/script.py` | título | `generate_title` (validação: 12–90 chars, `?`, sem markdown, ≠1ª frase) + `_fallback_title` (ideia se pergunta, senão verbatim documentado); nunca entra no TTS |
| `stages/render.py` | abertura | `burn_final(..., title, title_fontfile)`: drawtext ≤3 linhas (wrap 24, `?` preservado), caixa preta própria, topo `h*0.12`, `enable between(0,5)`; teleprompter passa `None` |
| `pipeline.py` | fiação | `script/title.txt` (cache-aware) + `metadata.video_title/title_source` + artefato; IA e `finalize` queimam; `title` (ideia) preservado p/ `list` |
| `config.py`, `config.example.toml` | tamanho | `sub_font_size` 68→92 |
| `scripts/smoke.sh` | testes | seção 10 (11 cheques): estilo ASS, tempos intactos, agrupamento, resolver, wrap/escape, validação, fallback, prompt) |

## 3. Evidências

```text
$ ./scripts/smoke.sh  →  64 passaram, 0 falharam (era 54).
E2E IA (teste-titulo, 45.08 s): Título: "Salário era mesmo pago em sal?"
  (nvidia:…) — pergunta, 28 chars, ≠1ª frase ✓
Título na tela: caixa linhas 202–317 em t=1/2/4; ausente t=6/8 (5 s) ✓
Legenda t=8/15/25/35 (fundos distintos): caixa preta + branco dentro ✓
  (t=35: caixa 1618–1729, 5.8% branco = glifos; branco extra = fundo claro)
Título fora do roteiro como frase e fora dos blocos SRT; title.txt == metadata ✓
```

## 4. Status vs PRD §19

Sem impacto nos cheques (1 trilha AAC, duração, SRT). Título e caixa são
apresentação queimada no mesmo encode final.

## 5. Limitações

- "Inspeção visual" por métricas de pixels (caixa/texto por banda), sem
  eyeball humano neste ambiente.
- Fallback de título sem LLM pode sair sem `?` (ideia verbatim) —
  documentado como melhor esforço; com chave, a IA cumpre a regra.
- Título truncado além de 3 linhas vira `…?` (raro: prompt limita a 55).
