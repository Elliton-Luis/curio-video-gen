# Relatório — colar roteiro pronto na TUI

- **Data:** 2026-10-01 15:33 -0300
- **Tipo:** relatorio
- **Escopo:** entrada multiline de Roteiro Pronto e preservação literal até o pipeline.
- **Commit(s):** pendente
- **Origem:** pedido para colar narração diretamente na TUI.

## 1. O que foi pedido

Trocar o caminho principal de Roteiro Pronto no TUI, que exigia caminho `.txt`, por colagem multiline com terminador explícito; confirmar tamanho recebido, preservar o roteiro e continuar pelo pipeline existente.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `src/curio/tui.py` | Entrada de roteiro | Lê linhas com `input()` até `<<FIM_DO_ROTEIRO>>` em linha isolada. Linhas vazias e espaços das demais linhas são conteúdo. Mostra confirmação em caracteres/palavras e remove mensagens incorretas sobre “só as fotos”. |
| `src/curio/pipeline.py` | Contrato verbatim | Valida texto vazio com `.strip()`, sem atribuir o texto limpo; preserva `provided_script` em `script_text` e grava o mesmo conteúdo em `script.txt`. |
| `tests/test_tui_script_input.py` | Regressão | Testa acentos, pontuação, parágrafos, linhas vazias, espaços nas bordas, terminador excluído, confirmação TUI, handoff e gravação literal antes das próximas etapas. |
| `README.md` | Uso | Documenta colagem e terminador na TUI; corrige descrição de Roteiro Pronto para explicar que Curio também gera título, cenas, narração, legendas e vídeo. |

O suporte a `.txt` continua disponível pela CLI `video-gen from-script`; a TUI passa a colar diretamente.

## 3. Evidências

- `python -m pytest -q tests/test_tui_script_input.py tests/test_tui_genre.py tests/test_pipeline_integration.py tests/test_visual_context.py` — **24 passed**.
- `python -m pytest -q` — **653 passed**.
- `python -m compileall -q src/curio tests/test_tui_script_input.py` — concluído sem erros.
- Teste de pipeline interrompe após persistir `script.txt` e verifica igualdade exata com o roteiro colado, incluindo espaços e newline final; geração IA de roteiro é bloqueada nesse teste.
- Não foi executado TTS nem render de vídeo real.

## 4. Status vs PRD §19

Entrada multiline usa apenas stdlib. O marcador não entra no texto. Após o handoff, o fluxo existente continua com fontes, título, cenas, mídia, TTS/teleprompter, legendas e render, conforme modo escolhido.

## 5. Limitações

- O terminador é uma linha exata `<<FIM_DO_ROTEIRO>>`; se o roteiro precisar conter essa linha literal, deve-se usar o fluxo CLI por arquivo.
- O terminal fornece linhas Unicode; o TUI reconstrói o texto com `\n`, preservando linhas, espaços, acentos e parágrafos, não bytes de newline específicos do sistema.
