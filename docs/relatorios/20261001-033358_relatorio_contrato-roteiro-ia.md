# Relatório — Documentação do contrato de roteiro por IA

- **Data:** 2026-10-01 03:33 -03:00
- **Tipo:** relatorio
- **Escopo:** analisar e documentar prompts, dados de entrada, validações, formatos e compatibilidade de Roteiro Pronto.
- **Commit(s):** pendente
- **Origem:** solicitação para registrar contrato atual da geração automática de roteiro.

## 1. O que foi pedido

Investigar o contrato real de prompt/resposta, inputs interpolados, gêneros, fontes, limites, normalizações, fallbacks, consumidores downstream e gerar template copiável. Não alterar código.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `docs/analises/20261001-032940_analise_contrato-geracao-roteiro-ia.md` | Análise técnica | Registrei prompts PT/EN integrais, blocos/dados, contrato de saída em texto puro, schemas separados de entidade/título/cenas, limites, validações, normalizações, fallbacks, consumo e template manual com placeholders. |
| `docs/README.md` | Índice | Registrei análise e relatório. |

Nenhum arquivo de código foi alterado. Nenhum provider foi chamado.

## 3. Evidências

- `REGRAS.md`: exige documentação de análises/implementações, índice atualizado e consulta inicial a `metrics/` para análises de pipeline.
- `metrics/` não contém arquivos nesta cópia; não há medições recentes a comparar.
- Inspecionei `script.py`, `nvidia.py`, `entity.py`, `research.py`, `editorial.py`, `scenes.py`, `visual.py`, `pipeline.py`, `cli.py`, `tui.py` e prompts relacionados.
- Executei extração local, sem rede, das diretrizes de gênero com `PYTHONPATH=src`; confirmou textos efetivos, inclusive sequência de caracteres quebrada em `HISTORY.must_distinguish`.
- Verifiquei template e índice com `git diff --check`; sem alterações de código, não rodei suíte de testes.

## 4. Status vs PRD §19

Não há arquivo PRD no repositório para verificar §19. Critério desta tarefa era registrar estado observado sem mudar comportamento; documentação e índice foram atualizados.

## 5. Limitações

- Geração por provider não foi executada; análise documenta caminhos e validações do código atual, não garante obediência de modelo externo.
- Métricas históricas não estavam disponíveis.
- A análise documenta incompatibilidade de estrutura com Roteiro Pronto e defeito de diretriz do gênero `history`; ambos ficaram sem alteração de código conforme pedido.
