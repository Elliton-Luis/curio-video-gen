# Relatório — pesquisa RAG iterativa limitada

- **Data:** 2026-10-01 18:43 -0300
- **Tipo:** relatorio
- **Escopo:** busca ampla, planejamento de lacunas, até três buscas específicas e contexto factual consolidado.
- **Commit(s):** commit desta entrega (`feat: add bounded iterative research`)
- **Origem:** pedido de RAG iterativo dentro da etapa atual de pesquisa.

## 1. O que foi pedido

Pesquisar o tema amplamente, extrair informações sustentadas, identificar lacunas essenciais e preencher somente essas lacunas com no máximo três consultas complementares. Preservar procedência, orçamento de contexto e fluxo existente.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `src/curio/stages/research.py` | Primeiro passe | Consulta ampla com nome canônico antes dos refinamentos editoriais existentes; mantém resolução de entidade, extração pública e gate de relevância. |
| `src/curio/stages/research.py` | Planejamento | Uma solicitação curta ao chain existente seleciona citações literais e até três lacunas essenciais. Só usa LLM quando já configurado; falha de planejamento preserva fontes existentes. |
| `src/curio/stages/research.py` | Complementação | Cada lacuna recebe uma consulta Wikipedia; examina no máximo três candidatos, aceita no máximo uma fonte adicional por consulta e reavalia suporte antes da próxima. Não repete consultas já realizadas. |
| `src/curio/stages/research.py` | Contexto | Valida citações por correspondência literal e URL da fonte; descarta citações inventadas, deduplica frases e reserva espaço para lacunas não resolvidas dentro dos 2500 caracteres existentes. |
| `src/curio/pipeline.py` | Persistência e handoff | `research.json` recebe fatos, consultas complementares/motivos e lacunas; roteiro recebe contexto consolidado do mesmo resultado. URLs e fontes completas permanecem disponíveis ao grounding/registry. |
| `src/curio/metrics.py` | Contadores | Quantidade total de consultas, fontes e consultas complementares separadas; corrige contagem por idioma nas buscas de recuperação existentes. |
| `tests/test_research_iterative.py` | Prova focada | Testa limite, citações inventadas, fonte irrelevante, query repetida, suporte suficiente, reavaliação entre consultas, contexto limitado, logs, métricas e plano malformado. |
| `tests/test_editorial.py` | Compatibilidade | Expectativas passam a considerar busca ampla primeiro; consultas específicas de gênero continuam verificadas depois dela. |
| `README.md`, `docs/README.md` | Uso e índice | Documentam fluxo, limite, arquivos de auditoria e métrica. |

Os trechos são extraídos das fontes, não sintetizados pelo planner. Até três fontes podem ser acrescentadas ao conjunto inicial; buscas iniciais e fallbacks já existentes conservam seus limites. Não há outro pipeline nem dependência nova.

## 3. Evidências

- Métrica recente consultada: `metrics/20261001-171949_20261001_como-a-peste-negra-mudou-a-euro.json`: pesquisa 3,52 s, 2 buscas, 4 fontes. Não havia contador separado de complementação.
- Antes da suíte: `python -m pytest -q tests/test_research_iterative.py tests/test_research.py tests/test_entity_relevance.py` — **36 passed** na primeira rodada ampliada.
- Após ajuste das expectativas editoriais: testes focados com `tests/test_editorial.py` — **113 passed**; `python -m pytest -q` — **669 passed**.
- Após proteção contra plano malformado e inclusão do contador no resumo: mesmos testes focados — **114 passed**.
- Prova do fluxo completo da etapa: queries `Lua` e `Lua crateras impacto`, duas fontes aceitas, uma busca complementar, motivo registrado no JSONL.
- Prova de custo: cinco lacunas propostas resultam em apenas três buscas; uma fonte que responde duas lacunas elimina a segunda consulta.
- Nenhuma API real foi chamada na validação desta entrega; fontes e planner foram simulados para medir limites de forma determinística.

## 4. Status vs PRD §19

Etapa atual de pesquisa agora realiza complementação limitada antes de gerar roteiro. Fontes, contexto e grounding compartilham a mesma procedência; fatos não sustentados não são inseridos como evidência. Identidade de `VIDEO.MD` permanece: pesquisa busca material para pergunta, descoberta e consequência sem inventar resposta.

## 5. Limitações

- A escolha de lacunas depende do modelo configurado. O preenchimento é verificado por termos de evidência em citações literais e pelo gate de entidade; não é prova automática de causalidade ou veracidade universal.
- Sem LLM ou com planejamento indisponível, continuam busca existente e consolidação local, sem complementação orientada por modelo.
- Planejamento reutiliza o chain e seus retries/fallbacks; uma solicitação de planejamento não significa exatamente um request HTTP.
- Fontes complementares são Wikipedia, extraídas pela API pública. Falta de evidência permanece registrada, sem relaxar o gate para forçar resposta.
