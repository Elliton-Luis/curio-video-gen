# G60 — atualizações de reuso pertencem ao contrato — 2026-10-05

## Problema

Após G59, as políticas de reuso recebiam e devolviam `MediaStageResult`, mas
editavam `SceneMediaSelection.to_dict()` para mudar campos de reuso e depois
reconstruíam a cena. O consumidor ainda precisava conhecer a representação
persistida para transformar um resultado tipado.

## Mudança

- `SceneMediaSelection.with_reuse_audit()` é o owner da atualização do relatório
  de repetição e reconstrói a cena por seu validador.
- `SceneMediaSelection.with_cross_scene_reuse()` recebe `SelectedAsset`,
  `SelectionDecision`, doador e evidências; valida cena/doador/asset/estado e
  atualiza a projeção persistida internamente.
- `media_selection` mantém a política de elegibilidade e escolha, mas aplica as
  mudanças por essas operações tipadas, sem editar rows diretamente.
- Teste verifica estado atualizado e rejeição de auto-reuso.

## Compatibilidade e limite

O schema `media.json`, os scores/relevâncias e os motivos de reuso não mudam.
O contrato ainda preserva `_row` para round-trip de metadata histórica; sua
projeção só é alterada pelo owner do contrato. Conversão a partir de formatos
legados continua restrita a `from_dict()`/`to_dict()`.

## Arquivos

- Código: `src/curio/media/selection_result.py` e
  `src/curio/stages/media_selection.py`.
- Testes: `tests/test_media_selection.py`.
- Documentação: README, índice, auditoria e relatório de estado completo.

## Verificação

- Testes focados de seleção, contrato e auditoria de reuso: **46 passaram**.
- Suíte completa: **915 passaram em 187,94 s**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
