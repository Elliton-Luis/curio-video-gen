# Relatório — run.sh abre TUI + verificação de vídeos

- **Data:** 2026-09-28 12:37 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** corrigir `run.sh` sem argumentos e dar à TUI um fluxo visual de teste
- **Commit(s):** `4a7fac5` — `fix: open TUI when run without args and add video verification`
- **Origem:** pedido do usuário ("run.sh não funciona; deve abrir interface visual que permita testar")

## 1. O que foi pedido

`./scripts/run.sh` sem argumentos morria com `error: the following arguments are
required: cmd` (exit 2). O esperado: abrir uma interface visual que permita testar.

## 2. Causa raiz

`cli.py` declarava `add_subparsers(required=True)` sem default. Sem subcomando,
o argparse abortava antes de qualquer código nosso — o `run.sh` em si estava correto.

## 3. O que foi feito e como

| Arquivo | Mudança | Decisão |
|---|---|---|
| `src/curio/cli.py` | `required=False`; sem `cmd`, abre a TUI; novo subcomando `verify --slug` | `run.sh`, `video-gen` e `python3 -m curio` sem args caem na TUI; `tui` explícito continua funcionando |
| `src/curio/verify.py` (novo, 104 linhas) | `verify_video()` via ffprobe: 8 cheques (MP4 existe/tamanho, ffprobe lê, stream vídeo, stream áudio, resolução exata, 9:16, duração ±25% da meta, SRT com blocos) + `VerifyReport.render()` | Só leitura, nunca reprocessa; reaproveita `ff.run`/`FFMpegError` existentes |
| `src/curio/tui.py` (reescrita, 83→~190 linhas) | Banner ASCII + cores ANSI (auto-desliga sem tty/`NO_COLOR`), `clear`, 6 opções: gerar (com verificação automática), **teste rápido**, listar, verificar, doctor, sair; `EOFError`/`Ctrl+C` saem limpos (exit 0) | Continua stdlib puro, zero deps (regra do MVP) |
| `README.md` | Documenta TUI via `run.sh` sem args + `verify` | README vivo, como pedido no PRD |

Fluxo "teste rápido": gera `output/teste-rapido/` do zero (`force=True`, ideia
curada do salário) e roda a verificação em seguida — Um comando, prova completa.

## 4. Evidências (comandos reais)

- `./scripts/run.sh </dev/null` → banner + menu + `Até logo!`, exit 0 (antes: exit 2).
- `printf '5\n\n6\n' | ./scripts/run.sh` → doctor 7/7 OK dentro da TUI, volta ao menu, sai, exit 0.
- `./scripts/run.sh verify --slug de-onde-veio-a-palavra-salario` → **8/8 OK**
  (h264 1080×1920, aac, 46,8 s, 15 blocos SRT), exit 0; slug inexistente → exit 1.
- `printf '2\n\n\n6\n' | ./scripts/run.sh` → teste rápido gerou
  `output/teste-rapido/render/final.mp4` (46,77 s em 16,73 s) + **8/8 OK**.

## 5. Status vs PRD §19

Reforça dois critérios: "sincronização aceitável / reproduzível" (agora
verificável por máquina) e "produzido sem intervenção manual" (teste rápido
prova de ponta a ponta). Nenhum comportamento anterior quebrou: `generate`,
`--force`/cache e `doctor` intactos.

## 6. Limitações

Verificação checa **presença** das legendas (SRT existe, tem blocos), não que
estejam queimadas/legíveis no frame — isso ainda exige olho humano (ver backlog:
amostragem de frames). Cores ANSI desligam fora de tty (logs de CI ficam limpos).
