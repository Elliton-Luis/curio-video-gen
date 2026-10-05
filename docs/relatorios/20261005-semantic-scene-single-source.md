# G57 — uma fonte runtime para queries de cena — 2026-10-05

## Problema

`SemanticScene` guardava `representations` e `visual_queries` em paralelo. O
mirror era reconstruído, mas continuava exposto a consumidores e podia ser
lido ou atualizado como segunda fonte de verdade.

## Mudança

- Removido `visual_queries` do dataclass runtime `SemanticScene`.
- Planejadores e reparo de cenas agora produzem apenas `representations`.
- Scoring, contexto, timeline, regras de mídia e review leem representações.
- `to_dict()` continua emitindo `visual_queries` derivado para manter
  compatibilidade com artefatos persistidos.
- `from_dict()` conserva adaptação explícita de caches query-only antigos e
  rejeita cache com queries e representações divergentes.
- `Chapter` continua como projeção externa compatível: materializa queries
  legadas em representações ao entrar no contrato semântico e deriva queries
  ao sair dele.
- Fixtures usam `VisualRepresentation` tipada. Testes verificam ausência do
  atributo runtime e projeção do campo legado na serialização.

## Compatibilidade e limite

Conteúdo e ordem das queries não mudam. Compatibilidade fica nos limites de
leitura/escrita e em `Chapter`, sem manter duas fontes runtime no objeto
semântico. Esta fase não remove o formato legado `chapters.json` nem extrai o
coordenador de aquisição visual.

## Verificação

- Testes focados nos contratos e consumidores relacionados: **249 passaram**.
- Suíte completa: **913 passaram em 205,78 s**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

O total integral anterior era 915. Dois testes específicos do mirror foram
substituídos por asserções de ausência do atributo runtime e projeção
serializada; a suíte completa terminou sem falhas.
