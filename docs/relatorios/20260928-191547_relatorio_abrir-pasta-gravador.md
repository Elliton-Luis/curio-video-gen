# Relatório — abrir pasta + gravador pós-teleprompter

- **Data:** 2026-09-28 19:15 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** Dolphin na pasta + Audacity automáticos após gerar teleprompter
- **Commit(s):** este lote
- **Origem:** pedido do usuário

## 1. O que foi feito

- Novo `src/curio/openers.py`: `open_after_teleprompter(cfg, tele_dir, force)`
  abre gerenciador de arquivos (na pasta) + gravador (vazio, pronto p/ REC).
  Nunca levanta: sem sessão gráfica, binário ausente ou erro → mensagem.
- Config `[teleprompter]`: `file_manager` (dolphin), `audio_recorder`
  (audacity), `auto_open` (padrão on) + env `CURIO_FILE_MANAGER`,
  `CURIO_AUDIO_RECORDER`, `CURIO_AUTO_OPEN` (+ `.env.example`/`.env`/exemplo).
- CLI `generate --narration human` abre sozinho (opt-out `--no-open`); TUI
  pergunta "[S/n]" e força na confirmação. README documenta.

## 2. Testes (binários falsos em /tmp/fakebin — nenhuma GUI real aberta)

1. force → "Abrindo..." ×2, args certos (dolphin recebe a pasta).
2. Gravador inexistente → aviso + pasta abre (sem raise).
3. `auto_open=0` sem force → "desligada"; com force → abre.
4. Sem `DISPLAY`/`WAYLAND_DISPLAY` → "sem sessão gráfica, arquivos em...".
5. CLI `--no-open` em projeto existente → zero linhas "Abrindo".

## 3. Limitações

- Audacity abre projeto vazio (não aceita caminho de save útil via CLI);
  o `finalize` copia qualquer arquivo informado — fluxo segue manual e simples.
- Em sessão gráfica real aqui, Dolphin/Audacity abririam de verdade: o usuário
  valida no uso ( stubs cobrem a lógica).
