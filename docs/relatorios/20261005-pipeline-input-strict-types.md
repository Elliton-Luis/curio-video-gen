# G83 — validar tipos do contrato de entrada

**Data:** 2026-10-05  
**Commit:** `31f6acf` (`fix: reject invalid pipeline input types`)  
**Estado:** implementado e validado.

## Problema

`PipelineInput` declarava campos textuais, mas convertia qualquer objeto para
`str`. Assim, valores como `42` ou `object()` viravam tópico, roteiro ou título
aceito, escondendo erro no produtor e propagando semântica inválida.

## Mudança

O contrato agora exige `str` em `topic` e, quando presentes, em `script` e
`display_title`. Tipos errados geram `TypeError`; tópico vazio, roteiro vazio e
título vazio geram `ValueError`. Tópico e título continuam aparados nas bordas;
roteiro continua preservado exatamente, incluindo whitespace.

## Arquivos

- `src/curio/pipeline_input.py`: valida os tipos antes de normalizar conteúdo.
- `tests/test_pipeline_input.py`: cobre valores não textuais para os três
  campos, além das regras de vazio, imutabilidade e preservação do roteiro.

## Validação

- Testes focados de entrada/TUI/configuração/logs: **25 passaram** em 0,21 s.
- Suíte completa: **965 passaram** em 192,60 s.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

Nenhum comportamento dos chamadores CLI/TUI/queue mudou para entradas válidas.
Busca e aquisição de mídia não foram alteradas.
