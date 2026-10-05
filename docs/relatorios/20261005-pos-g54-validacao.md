# Validação pós-G54 — 2026-10-05

## Testes e contratos

Após G54, a suíte integral passou com **914 testes em 190,63 s**. Também
passaram `python -m compileall -q src tests` e `git diff --check`. As fases
G49–G54 preservaram pipeline, formato de projeto e decisões visuais, apertando
validação de contratos no caminho até avaliação.

## Rerenders reais com código atual

| Projeto | Cenas | IDs reais únicos | Reusos | Sintéticas | Tempo do rerender |
|---|---:|---:|---:|---:|---:|
| `battle-mohacs` (história) | 3 | 2 | 0 | 2 | 26,27 s |
| `20261004-refactor-black-hole-rerender` (ciência) | 3 | 3 | 0 | 0 | 27,50 s |

Os dois rerenders usaram roteiro/narração/legendas em cache. Não refizeram
pesquisa, aquisição de mídia ou TTS. Os contadores foram lidos do
`visual_report` persistido após o rerender.

## Auditoria visual

Inspecionei os sete assets locais que compõem as seleções. As três imagens
científicas são uma impressão artística de NGC 300 X-1, uma visualização da Via
Láctea e a imagem do EHT de M87: distintas e coerentes com o tema. Em Mohács,
os dois assets Pixabay mostram o Parlamento Húngaro contemporâneo, não a
batalha, exército ou período de 1526; as cenas restantes são cards “assembly
and advance” e “outcome”. Portanto, a compatibilidade de rerender está
confirmada, mas a qualidade editorial histórica continua falhando. A geração
histórica original foi feita antes das fases G49–G54; este rerender não deve
ser apresentado como nova validação de aquisição.

## Limite desta rodada

As mudanças recentes não alteram query policy nem scoring, então o rerender
confirma somente que artefatos existentes e contratos de saída seguem
consumíveis. Aquisição fresca em história/ciência, falha de provider sem LLM,
cache de resultados e profile segmentado ainda precisam de execuções específicas
na fase de validação/performance.
