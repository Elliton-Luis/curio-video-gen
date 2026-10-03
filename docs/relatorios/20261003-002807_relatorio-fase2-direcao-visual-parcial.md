# Relatório — Fase 2 da direção visual (parcial)

- **Data:** 2026-10-03 00:28 (-03:00)
- **Tipo:** relatorio
- **Escopo:** progresso de implementação do Visual Director, mudanças feitas e trabalho ainda pendente
- **Commit(s):** pendente
- **Origem:** `docs/analises/20261002-184536_analise-direcao-visual.md`

## 1. Pedido

Implementar arquitetura de mídia guiada por intenção visual, preservar o
pipeline existente e validar ambiguidades sem alimentar listas por assunto.
Este relatório registra o estado de trabalho interrompido antes de concluir
a suíte e a avaliação integral de produto.

## 2. Feito até agora

| Arquivo | Mudança |
|---|---|
| `src/curio/stages/scenes.py` | `Chapter` aceita contexto global, intenção estruturada, entidade, evento, lugar, período e representações; parser tolera formatos variados; planner restaura spans literais quando consegue alinhar narração paraphraseada com confiança; corrige excesso/falta de cenas somente quando há âncora declarada segura; resposta inválida ainda herda contexto global disponível. |
| `src/curio/stages/prompts.py` | Prompt de cenas pede contexto do vídeo e representações visuais concretas na chamada existente. Não adiciona chamada LLM por cena. |
| `src/curio/stages/visual_context.py` | Anexa tópico/aliases ao universo de cada cena; fallback local não exibe keyword extraída como se fosse entidade confirmada; âncora local preserva o tópico sem depender de tradução conhecida. |
| `src/curio/pipeline.py` | Atualiza chapters quando contexto muda; usa pipeline de busca principal também com `max_images=1`; registra decisão visual por cena nas métricas. |
| `src/curio/media/providers.py` | `MediaAsset` preserva descrição, tags, categorias, data e tipo opcionais; adapters preenchidos onde resposta da API fornece esses dados. |
| `src/curio/stages/scoring.py` | Relevância temática e relevância da cena separadas; correspondência de frase completa; tokens únicos não provam identidade; scores expõem correspondências, bônus e rejeições; CLIP opcional implementado para shortlist aprovada. |
| `src/curio/stages/visual.py` | Queries priorizam representações; busca para após prova forte de cena; diversidade desempata score; consulta genérica também exige contexto; reuse entre cenas exige evidência para a cena destinatária; sem provider, usa visual sintético por cena em vez de imagem vizinha sem prova; `media.json` registra funil por cena/candidato. |
| `src/curio/metrics.py` | Métricas JSON guardam intenção, queries, providers, candidatos, score temático/de cena, rejeição, CLIP e fallback, com limite por cena. |
| `pyproject.toml` | Extra opcional `curio[clip]`; instalação base não instala `torch` nem `open-clip-torch`. CPU só roda com opt-in explícito. |
| `tests/test_visual_director.py` | Testes de ambiguidades e funil completo para Revolução Francesa, César, Marco Aurélio, buracos negros, Mercury e tópico novo Doppler. Inclui reparo de cenas e política CPU do CLIP. |
| `tests/test_tts_coverage.py` | Render isolado por mock nos testes de cache afetados pela invalidação correta de mídia antiga sem contexto visual. |

## 3. Evidências disponíveis

- `python3 -m pytest tests/test_visual_director.py -q` — **17 passed** após as últimas mudanças.
- `python3 -m py_compile ...` — módulos alterados compilam.
- `git diff --check` — sem erro de whitespace.
- Suíte completa executada antes das últimas correções no gate semântico: **750 passed**, 616,47 s. Esse resultado não valida a versão atual integralmente.
- Nova suíte completa foi interrompida pelo usuário em aproximadamente 56%; não há resultado final válido dessa execução.
- Execução isolada de `tests/test_tts_coverage.py` — **10 passed**, 476,67 s, antes das últimas correções semânticas.
- CLIP não foi executado com pesos reais/GPU/CPU. A rota é opt-in; nesta máquina não foi validado modelo baixado nem desempenho.

## 4. O que falta

1. Rodar suíte completa na revisão atual e corrigir regressões restantes. A execução é longa: cerca de 10 minutos no último run completo.
2. Rodar novamente `tests/test_tts_coverage.py` após as últimas mudanças, se o run completo não alcançar/completar essa cobertura.
3. Reexecutar avaliações completas de produto com inspeção dos assets: Revolução Francesa, César/Marco Aurélio, buracos negros, tema científico ambíguo e tema novo. Testes atuais simulam providers e verificam decisões textuais, não conferem pixels reais.
4. Confirmar queries/providers e scores no artefato `media.json` e em `metrics/*.json` de uma geração real com credenciais/providers disponíveis.
5. Verificar metadados por adapter com fixtures reais: hoje descrições/tags/categorias variam entre APIs; `creator`, URL de origem e confiança por provider ainda não entram como evidência ponderada explícita.
6. Exercitar instalação `pip install 'curio[clip]'`, modelo CLIP e escolha de device. Registrar latência e memória; garantir falha de download/modelo volta ao ranking sem CLIP.
7. Rever reparo de narração aproximada em exemplos reais de planner. Alinhamento de spans tem threshold conservador, mas ainda precisa avaliação com respostas inválidas observadas.
8. Atualizar relatório de entrega final e índice somente após validação completa. Nenhum commit foi feito.

## 5. Estado

Implementação estrutural está em andamento, não concluída. As regressões unitárias focadas passaram na revisão atual. Critério de produto, suíte completa atual e CLIP real continuam sem prova.
