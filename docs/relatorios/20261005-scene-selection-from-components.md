# G82 — construir seleção de cena a partir de contratos tipados

**Data:** 2026-10-05  
**Commit:** `1b00689` (`refactor: build scene selections from typed values`)  
**Estado:** implementado e validado.

## Problema

G81 manteve `SceneMediaSelection` tipado entre o seletor por cena e
`fetch_media_multi`, mas `visual.py` ainda montava dicionários para asset,
lista de assets, decisão, rejeições e estratégia antes de chamar
`SceneMediaSelection.from_dict`. A etapa conhecia detalhes da row de projeto
para produzir seu próprio contrato.

## Mudança

`SceneMediaSelection.from_components` agora recebe `SelectedAsset` tipado,
`VisualDecision` e metadados nomeados da cena. O contrato valida e possui a
projeção interna para a row persistida. `visual.py` usa a fábrica tanto para o
fallback tipográfico quanto para a seleção comum. A identidade do primeiro
asset vem do `SelectedAsset` projetado, preservando metadata legado já presente
na seleção.

`from_dict` permanece para leitura de projetos/rows existentes. Reuso e
`with_cross_scene_reuse` mantêm a adaptação de rows existente nesta fase. O
schema `media.json`, decisões, políticas e ordem de fallback não mudaram.

## Arquivos e testes

- `src/curio/media/selection_result.py`: nova fábrica tipada
  `SceneMediaSelection.from_components`.
- `src/curio/stages/visual.py`: remove construção de row no seletor novo.
- `tests/test_media_selection.py`: testa projeção fiel e rejeição de decisão
  pertencente a outra cena.

## Validação

- Testes focados de seleção, contrato, diretor visual, waterfall, receipt,
  funil e pipeline de mídia: **126 passaram** em 0,83 s.
- Suíte completa: **962 passaram** em 175,45 s.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

## Limites

O objeto ainda conserva `_row` congelada para round-trip fiel de formatos de
projeto, e `from_dict` segue dono da leitura legada. Essa compatibilidade não
foi removida. G82 elimina montagem de row no seletor novo; não remove dicts de
auditoria por query/candidato nem simplifica o restante de `visual.py`.
Nenhuma geração real foi necessária porque aquisição e política editorial não
mudaram.
