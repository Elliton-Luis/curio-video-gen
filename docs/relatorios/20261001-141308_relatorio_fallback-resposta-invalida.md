# Relatório — fallback para resposta LLM inválida

- **Data:** 2026-10-01 14:13 -0300
- **Tipo:** relatorio
- **Escopo:** continuar rodízio de providers quando geração retorna narração vazia/curta.
- **Commit(s):** pendente
- **Origem:** falha da execução `20261001_fale-sobre-a-historia-de-santa`

## 1. O que foi pedido

Investigar a execução que preservou etapas anteriores, mas parou ao gerar roteiro após timeout NVIDIA e resposta inválida do Groq.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `src/curio/stages/nvidia.py` | Rodízio LLM | Permite validar cada resposta dentro do rodízio. Resposta de roteiro com menos de 100 caracteres após sanitização agora remove aquele provider e tenta o próximo. |
| `src/curio/stages/nvidia.py` | Diagnóstico | Registra `finish_reason`, tamanho do conteúdo, tamanho após sanitização, tamanho do campo de raciocínio e tokens de conclusão, sem registrar o texto produzido. |
| `tests/test_llm_fallback.py` | Regressão | Simula resposta vazia do Groq seguida de roteiro válido no OpenRouter e verifica que a rotação continua; verifica que o diagnóstico não expõe o texto. |

## 3. Evidências

- Log `output/people/20261001_fale-sobre-a-historia-de-santa/logs/run-20261001-170538-168401.jsonl`: NVIDIA excedeu 60 s na pesquisa e na geração. Groq respondeu em `completion_time=0.0609s`; em seguida a validação de narração falhou. O corpo do modelo não foi preservado, então não é possível distinguir no log original texto vazio, texto curto ou conteúdo removido pela sanitização.
- Não havia arquivo JSON de `metrics/` para esta execução. O run log contém eventos de provider, fallback e erro.
- `python -m pytest -q tests/test_llm_fallback.py tests/test_llm_diagnostics.py tests/test_entity_context.py` — **37 passed**.
- `python -m compileall -q src/curio tests/test_llm_fallback.py` — concluído sem erros.
- Não repeti geração real; a validação usa providers simulados e não consome API.

## 4. Status vs PRD §19

Correção focada no fallback: resposta HTTP bem-sucedida não encerra mais o rodízio se narração sanitizada for inutilizável. O conteúdo continua sujeito à validação existente antes de chegar ao TTS.

## 5. Limitações

- O log da falha não contém texto nem dimensões da resposta original; o novo diagnóstico fornece dimensões em execuções futuras sem armazenar conteúdo.
- As três fontes aceitas nesta execução (`Livro da Vida (Santa Teresa de Jesus)`, `Santa Teresinha (bairro de São Paulo)` e uma paróquia) não parecem ser fontes biográficas adequadas para Santa Teresinha de Lisieux. Essa questão de seleção de fontes não causou o erro de resposta curta e requer investigação separada antes de confiar em novo roteiro.
