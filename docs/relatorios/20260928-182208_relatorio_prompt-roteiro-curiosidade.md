# Relatório — prompt de roteiro com loops de curiosidade

- **Data:** 2026-09-28 18:22 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** adotar o prompt de roteiro do usuário como regra oficial
- **Commit(s):** este lote
- **Origem:** prompt enviado pelo usuário + pedido anterior ("regras para geração do vídeo e das legendas" — veio só o de roteiro)

## 1. O que foi feito

`SCRIPT_SYSTEM_PROMPT` (`src/curio/stages/nvidia.py`) reescrito com as 11
regras do usuário: abrir com pergunta/afirmação/problema, responder toda
pergunta criada, plantar perguntas novas, progressão sem entregar tudo,
priorizar o surpreendente, fechar respondendo a ideia inicial, fala natural,
concisão, sem "Olá pessoal..." (mantido também o veto a "Você sabia que" do
PRD). Preservados como proteção: formato de saída rígido (só narração, sem
markdown/cenas/preâmbulos), honestidade editorial (não inventar, admitir
incerteza) e princípio anti-clickbait.

## 2. Teste real

`generate "Por que a Lua parece maior no horizonte?" --slug lua-horizonte`:
roteiro abre com a observação intrigante → pergunta "será que mudou de
tamanho?" → responde (fotos idênticas) → nova pergunta (por que o cérebro
insiste?) → responde (régua do horizonte) → fecha. Sem intro genérica,
conciso, explicação real (ilusão de Ponzo). 5 cenas, 5 mídias licenciadas,
43,47 s, `verify` **8/8**. Frame inspecionado: paisagem + legenda sincronizada.

## 3. Observações

- Edge fundiu 1 palavra de novo (103×102) → fallback proporcional com aviso
  (rede de segurança funcionando; recorrente, investigar causa um dia).
- O pedido mencionava regras "das legendas" mas só veio prompt de roteiro:
  regras de legenda (blocos curtos, base, timestamps reais) já existiam e
  seguem inalteradas. Se mandar o de legendas, integro em `subs.py`.
