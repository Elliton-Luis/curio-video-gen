# Relatório — Queries elétricas compostas para cenas locais

- **Data:** 2026-10-02 20:59 (UTC)
- **Tipo:** relatorio
- **Escopo:** impedir rio para “corrente” e assets Tesla sem relação com Nikola Tesla
- **Commit(s):** pendente
- **Origem:** `docs/analises/20261002-205941_analise-imagens-tesla-corrente.md`

## 1. O que foi pedido

Queries ambíguas devem ganhar contexto. Cena sobre corrente elétrica deve
buscar corrente alternada/contínua ou energia, não rio. Mostrar invenções
de Tesla, não resultados de Tesla Motors ou ruas homônimas.

## 2. O que foi feito

| Arquivo | Mudança |
|---|---|
| `textnorm.py` | Dicionário de frases PT/EN para corrente alternada, corrente contínua, Guerra das Correntes, motor de indução, energia sem fio, rede elétrica e campo magnético; Nikola Tesla recebe âncora canônica. |
| `visual.py` | `local_queries` prioriza frases de domínio compostas antes de palavras soltas. |
| `scoring.py` | Cenas locais aceitam título que comprove nome canônico ou conceito composto do texto; incluem âncora global no score. |
| testes | Rio Corrente, Gigafactory/homônimo, frase elétrica e retrato Nikola cobertos. |

Cache de resultado por query continua removido. Downloads guardados servem
rerender, nunca substituem busca ou escolha de assets.

## 3. Evidências

- `local_queries("motor de indução de corrente alternada")` prioriza
  `induction motor`/`alternating current`; `corrente contínua` vira
  `direct current`.
- “Ponte sobre o Rio Corrente” reprova; “Alternating current induction
  motor, Nikola Tesla” passa.
- `python3 -m pytest tests/ -q` — **738 passed**.

## 4. Status vs PRD §19

Sem API paga, cache de seleção ou mudança de roteiro. Busca continua no
pipeline único; fontes configuradas e filtro lexical existentes executam.

## 5. Limitações

Glossário cobre expressões frequentes do tema, não todo vocabulário técnico.
Se cena Groq continuar invalidando narração, fallback local usa este
glossário e âncora de entidade; título sem nome nem conceito composto será
rejeitado e cena pode cair para visual sintético.
