# Relatório — TUI refeita por objetivo + ajuda

- **Data:** 2026-09-28 18:06 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** reescrever o menu do TUI (confuso) e explicar o fluxo humano
- **Commit(s):** este lote
- **Origem:** pedido do usuário ("TUI confuso; como vai ter narração humana sem vídeo?")

## 1. Problema

O TUI listava comandos técnicos (gerar, finalizar, verificar...) sem explicar
que **narração humana não produz vídeo final sozinha** — o usuário terminava o
passo 1 sem MP4 e sem saber o que fazer. A dúvida "como vai ter narração
humana sem vídeo?" é a prova: resposta correta é "não vai" — o vídeo nasce no
passo 2 — e a interface escondia isso.

## 2. Mudanças (`src/curio/tui.py`, reescrita)

- **Menu por objetivo**, em 4 blocos: QUERO UM VÍDEO PRONTO (voz de IA) /
  QUERO NARRAR EU MESMO (2 passos) / MEUS PROJETOS / AJUDA E SISTEMA.
- **Aba de ajuda (opção 6)**: explica os 2 fluxos, onde fica cada arquivo e
  responde literalmente à dúvida ("narração humana sem vídeo? Nunca — o vídeo
  final nasce no passo 2").
- **Assistente humano guiado**: passo 1 imprime painel "E AGORA?" (assistir
  teleprompter → gravar ~Xs → voltar); oferece finalizar na hora se o áudio
  já existe; passo 2 valida que a base existe antes de pedir o áudio.
- **Lista com situação**: ● vídeo final pronto / ○ aguardando sua voz
  (lê `narration` do metadata); `verify` num pendente explica em vez de errar.
- Mantidos: cores, banner, EOF/Ctrl+C limpos, teste rápido, verify, doctor.

## 3. Testes

- Menu renderiza e sai (`9` → exit 0); ajuda exibe completa.
- Lista real: 10 projetos com situação correta (9 prontos + 1 "SUA voz").
- `_project_status`: pendente/final/inexistente/corrompido verificados via
  projeto falso em /tmp (sem poluir `output/`).
- `py_compile` OK. Sem mudança em pipeline/CLI — risco de regressão mínimo.

## 4. Limitações

- Ajuda é texto estático (se os fluxos mudarem, atualizar `HELP_TEXT` junto).
- TUI não toca o áudio/vídeo (só mostra caminhos) — reprodução fica p/
  o player do usuário.
