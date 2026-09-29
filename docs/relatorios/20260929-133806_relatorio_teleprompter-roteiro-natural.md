# Relatorio — teleprompter legível com viradas + roteiro conversado

- **Data:** 2026-09-29 13:38 (-03)
- **Tipo:** relatorio
- **Escopo:** teleprompter (legibilidade + indicação de cena, sem tocar sincronia) e prompt de roteiro mais humano/conversado
- **Commit(s):** pendente
- **Origem:** pedido do usuário (duas melhorias independentes)

## 1. O que foi pedido

1. Teleprompter: fonte maior e legível, área central confortável, contraste,
   separação visual de cenas ("estou terminando esta parte; agora vem a
   próxima"), sem alterar texto nem sincronização.
2. Roteiro: manter as regras de curiosidade, mas escrita humana/conversada
   (nada acadêmico, nada de comédia forçada, precisão intacta).

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `stages/teleprompter.py` | legibilidade | fonte 84→104 (atual) / 56→64 (próximo), `Bold=1`, margens laterais 60→120, caixa mais opaca (`&HCC000000`), `LineSpacing=12` (extensão libass; inócuo se ignorado), ≤5 palavras/≤34 chars por linha |
| `stages/teleprompter.py` | virada de cena | cues carregam `chapter_id`; fronteira mostra separador `··· próxima parte ···` + próximo bloco em ciano (`≠` cinza = continua); aviso amarelo estendido (1.4 s) no fim de cena; texto/tempos intactos |
| `stages/nvidia.py` | tom do roteiro | regra 7 vira "contar a um amigo" (frases faladas, retóricas, comparações, personalidade sem gíria/humor forçado); regra 11 proíbe conclusões artificiais (`diante disso, podemos concluir`, moral, resumo) e manda fechar com resposta/observação; formato de saída e regras 1–6/8–10 intactos |
| `scripts/smoke.sh` | testes | seção 9 (7 cheques): capítulo nos cues, ≤5 palavras/linha, estilo ASS, separador+ciano, narração intacta, prompt com curiosidade+formato e tom conversado |

## 3. Evidências

```text
$ ./scripts/smoke.sh  →  54 passaram, 0 falharam (era 47).
E2E curto (2 cenas, 3 cues): 2 eventos de separador na virada ✓
E2E multi-cena (salário, 5 cenas, 26 cues): 4 separadores (1 por fronteira) ✓
Burn teleprompter c/ LineSpacing: OK no libass; frames t=1/5/7/11 distintos ✓
Finalize real (voz edge-tts como stand-in + faster-whisper):
  final.mp4 44.8 s, legendas: 24 blocos (whisper) — sincronia inalterada ✓
$ ./scripts/run.sh verify --slug teste-salario-h  →  8/8 ✓
```

## 4. Status vs PRD §19

`verify` 8/8 no vídeo finalizado. Sincronização (WPM estimado → Whisper
real) intocada por construção: `build_teleprompter_cues` mantém pesos e
durações; `transcribe`/`subs`/`finalize` sem nenhuma alteração.

## 5. Limitações

- `LineSpacing` validado por aceite do render + variação de frames, não
  por medição da entrelinha em pixels.
- "Inspeção visual" feita por cheques estruturais + frames distintos (sem
  eyeball humano neste ambiente).
- Tom do roteiro novo ainda não validado com geração live (NVIDIA
  instável no momento); prompt coberto por teste de conteúdo + `_sanitize`
  inalterado.
