# Relatório — teleprompter de verdade (atual + próximo + aviso)

- **Data:** 2026-09-28 18:58 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** teleprompter com texto seguinte visível e indicação de virada
- **Commit(s):** este lote
- **Origem:** pedido do usuário (próximo texto abaixo + cor/animação de mudança)

## 1. O que foi feito (`src/curio/stages/teleprompter.py`)

Cada evento agora mostra **duas linhas**: bloco atual (84px, branco) e o
**próximo bloco** (56px, cinza) abaixo. Nos últimos 0,7 s do bloco
(`TELE_WARN_SECONDS`), o atual fica **amarelo** — o leitor vê a virada
chegando. Blocos curtos (≤1,2 s) usam fase única. Writer ASS dedicado
(estilo `Teleprompter`, centro, caixa semi-transparente) em vez de reusar o
das legendas.

## 2. Bug pego na inspeção visual

Tags de cor fora de `{}` vazavam como texto na tela
(`do latim\c&H00A0A0A0&`). Corrigido (bloco próprio `{...}`) e reinspecionado:
fase branca e fase amarela corretas, próximo sempre visível.

## 3. Teste

Rebuild barato (só teleprompter refeito, resto em cache) + 2 frames lidos:
t=1,0 branco+próximo; t=2,4 amarelo+próximo. Sem animação de scroll
(decisão: eventos discretos são previsíveis e confiáveis com ASS queimado;
scroll suave exigiria overlay animado — backlog se pedir).
