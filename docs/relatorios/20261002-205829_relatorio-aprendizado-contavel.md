# Relatório — Aprendizado claro e fácil de contar

- **Data:** 2026-10-02 20:58 (UTC)
- **Tipo:** relatorio
- **Escopo:** orientar roteiro para entendimento sem replay e aprendizado retellable
- **Commit(s):** `524d8fc fix: focus scripts on retellable learning`
- **Origem:** feedback editorial do usuário; `VIDEO.MD`

## 1. O que foi pedido

O espectador deve sair sentindo que aprendeu algo útil, entender sem rever
o vídeo e conseguir contar a ideia a outra pessoa.

## 2. O que foi feito

| Arquivo | Mudança |
|---|---|
| `VIDEO.MD` | Nova diretriz editorial permanente: ideia central compreensível sem replay, contável em uma frase; termo técnico recebe explicação simples e exemplo na primeira menção. |
| `stages/prompts.py` | Prompt PT/EN exige compreensão autônoma, exemplo concreto para jargão e uma ideia principal retellable no fechamento; mantém hook, grounding e pergunta final. |
| `stages/prompts.py` | Removidas definições duplicadas de prompts de título que sobrescreviam valores idênticos no mesmo módulo. |
| `tests/test_script_hook.py` | Regressões para compreensão sem replay e takeaway que o espectador consegue contar. |

## 3. Evidências

- `python3 -m pytest tests/test_script_hook.py tests/test_active_word.py tests/test_shorts60.py tests/test_editorial.py -q` — 94 passed.
- `python3 -m pytest tests/ -q` — **736 passed**.

## 4. Status vs PRD §19

Sem chamadas extras de LLM, dependências ou mudanças no formato do vídeo.
Mudança só orienta geração já existente.

## 5. Limitações

Prompt orienta o modelo, não garante cumprimento. Grounding e validação
estrutural existentes continuam em vigor.
