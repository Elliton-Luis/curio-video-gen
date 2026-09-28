# docs — índice da documentação de trabalho

Tudo que é analisado ou implementado neste projeto gera um documento aqui.
Convenção de nomes: `AAAAMMDD-HHMMSS_<tipo>_<slug>.md`
(tipos: `relatorio`, `analise`, `melhoria`). Processo completo em
`_modelos/MODELO.md`.

## Relatórios (o que foi feito e como)

- `relatorios/20260928-123219_relatorio_mvp-inicial.md` — scaffolding + pipeline
  MVP + teste end-to-end (commit `7a18ec6`).
- `relatorios/20260928-123729_relatorio_run-sh-tui-verify.md` — `run.sh` sem args
  abre a TUI; novo `verify` (8 cheques) + fluxo "teste rápido".
- `relatorios/20260928-133718_relatorio_nvidia-script-engine-legendas.md` —
  roteiros via NVIDIA API (Nemotron 3 Ultra) + legendas refeitas (ASS com
  PlayRes real, base 68, blocos curtos); inclui correção do bug "roteiro com
  o prompt da IA".

## Análises (estado, gaps, riscos)

- `analises/20260928-123219_analise_estado-atual-mvp.md` — veredito: MVP prova a
  tese; riscos altos = voz robótica e falta de pesquisa/fontes.

## Melhorias (backlogs e propostas)

- `melhorias/20260928-123219_melhoria_backlog-v1.md` — 9 itens priorizados
  (Piper TTS, base curada 10 temas, validador editorial, templates visuais,
  testes de fumaça, `batch`, …).
