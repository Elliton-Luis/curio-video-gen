# MODELO — como documentar e continuar este projeto

> Instruções para IAs (e humanos) que forem analisar ou implementar neste repo.
> Leia este arquivo primeiro, depois o `docs/README.md` (índice) e os docs mais
> recentes da categoria relevante antes de agir.

## 1. Convenção de nomes (obrigatória)

Todo documento de trabalho vive em `docs/<categoria>/` com o nome:

```text
AAAAMMDD-HHMMSS_<tipo>_<nome-da-implementacao-ou-tema>.md
```

- **Timestamp:** data/hora local no momento da criação (`date +%Y%m%d-%H%M%S`).
  Documentos do mesmo lote podem compartilhar o timestamp; o nome os diferencia.
- **Tipo:** `relatorio` | `analise` | `melhoria` (minúsculas, sem acento).
- **Nome:** slug minúsculo com hífens (`backlog-v1`, `tts-piper`, `mvp-inicial`).
- **Exemplo:** `20260928-123219_relatorio_mvp-inicial.md`
- Exceções (sem timestamp, estrutura fixa): `docs/README.md` (índice),
  `docs/_modelos/MODELO.md` (este arquivo).

## 2. Categorias

| Pasta | Guarda o quê | Quando criar |
|---|---|---|
| `docs/relatorios/` | O que foi feito e como, com evidências | Ao fim de **toda** implementação |
| `docs/analises/` | Estado do código, gaps vs PRD, riscos | Antes de propor mudanças grandes |
| `docs/melhorias/` | Propostas priorizadas de evolução | Quando um backlog/ideia for formalizado |
| `docs/_modelos/` | Templates e guias de processo | Quase nunca (só mudando o processo) |

## 3. Cabeçalho obrigatório de todo doc

```markdown
# <Tipo> — <título>

- **Data:** AAAA-MM-DD HH:MM (fuso)
- **Tipo:** relatorio | analise | melhoria
- **Escopo:** o que este doc cobre (1 linha)
- **Commit(s):** hash + mensagem (em relatorios; `pendente` se ainda não commitado)
- **Origem:** link para o doc de origem, se houver (ex.: analise → melhoria)
```

## 4. Seções por tipo

- **relatorio:** 1. O que foi pedido · 2. O que foi feito e como (tabela
  arquivo → responsabilidade → decisão) · 3. Evidências (comandos + números
  reais, nunca inventados) · 4. Status vs PRD §19 · 5. Limitações → apontar
  para analise/melhoria.
- **analise:** 1. Veredito (2–4 linhas) · 2. Pontos fortes · 3. Gaps vs PRD
  (tabela com severidade) · 4. Riscos técnicos específicos · 5. O que NÃO mexer.
- **melhoria:** Origem + regra de não-regressão + itens numerados com
  **critério de aceite testável** cada + seção "Explicitamente NÃO fazer".

## 5. Regras de trabalho

1. **Evidência antes de síntese:** rode o código (`doctor`, `generate`,
   `ffprobe`) e cite números reais. Nunca invente métricas.
2. **Rastreabilidade PRD:** cite a seção (`PRD §8`) em decisões e gaps.
3. **Editorial intocável:** nada que incentive desinformação/clickbait (PRD §2).
4. **Custo zero por padrão:** sem dependência paga; isolar integrações externas.
5. **Cada implementação atualiza:** seu doc em `docs/`, o `docs/README.md`
   (índice), o `README.md` principal se o uso mudou, e **um commit
   Conventional Commits por entrega** (`feat:`/`fix:`/`docs:`/`chore:`).
6. **Nunca commite segredos**; `output/` segue gitignored.
7. Ao terminar, diga ao usuário: docs criados, commits feitos e próximos
   passos sugeridos (máx. 3).
