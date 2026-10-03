# Relatório — Direção visual semântica

- **Data:** 2026-10-03 09:58 (-03:00)
- **Tipo:** relatorio
- **Escopo:** implementação da Fase 2, validação por suíte e busca real, comparação antes/depois e limitações
- **Commit(s):** pendente
- **Origem:** `docs/analises/20261002-184536_analise-direcao-visual.md`; progresso anterior em `docs/relatorios/20261003-002807_relatorio-fase2-direcao-visual-parcial.md`

## 1. O que foi pedido

Substituir escolha de mídia por associação de palavras por contexto global,
intenção visual estruturada, representações, evidência independente de tópico
e cena, gates semânticos, fallback seguro, auditoria por candidato e CLIP
opcional. Preservar pipeline, providers, cache, CLI/TUI e dependências leves.

## 2. O que foi feito e como

| Arquivo | Responsabilidade e decisão |
|---|---|
| `src/curio/stages/scenes.py` | `Chapter` agora carrega contexto global, intenção, entidade, evento, lugar, período e representações. Parser aceita schema novo e legado. Planner preserva intenção quando recupera spans literais. Repara contagem só quando pode fundir cenas com âncora compatível ou dividir mantendo âncora compartilhada. Resposta inválida herda `video_context` antes do fallback local. |
| `src/curio/stages/prompts.py` | Uma chamada de cenas produz contexto do vídeo e intenção/representações por cena. Prompt pede nomes canônicos em idiomas originais quando conhecidos e proíbe inventar aliases. Não há chamada LLM adicional por cena. |
| `src/curio/stages/visual_context.py` | Entidade pesquisada e tópico do vídeo são propagados às cenas. Fallback lexical usa tópico + foco local para busca; não exibe keyword extraída como fato confirmado. Tradução/alias seguem auxiliares. |
| `src/curio/stages/visual.py` | Busca ordena representações, consulta cada nível até haver prova forte, mede queries realmente consultadas, aplica gates antes da shortlist, pontua tópico/cena separadamente, e só usa CLIP depois da aprovação. Reuso entre cenas exige compatibilidade com a cena destinatária. Sem providers, cada cena tenta visual sintético próprio. Auditoria guarda queries, providers, candidatos, scores, evidência, rejeições, seleção e fallback. |
| `src/curio/stages/scoring.py` | Frases completas de intenção e representação dão evidência de cena; entidades/eventos globais dão evidência de tópico. Um token ou correspondência isolada em creator/source não aprova asset. Título, descrição, tags, categorias, data e tipo têm pesos distintos. Creator/provider/source entram como proveniência e apoio de qualidade limitado, após evidência temática. Rejeições semânticas não passam mesmo com threshold configurado em `0`. |
| `src/curio/media/providers.py` | `MediaAsset` preserva campos opcionais de descrição, tags, categorias, data e tipo sem alterar ordem de argumentos posicionais existentes. Adapters extraem os metadados disponíveis em Wikimedia, Openverse, Pixabay, Pexels, Unsplash, NASA, Met e AIC. Wikimedia também devolve categorias. |
| `src/curio/pipeline.py`, `src/curio/pipeline_media.py` | Pipeline principal usa aquisição semântica também com uma imagem por cena. Cache antigo sem decisão auditável é invalidado. Mídia manual registra origem. Decisões chegam ao relatório de execução. |
| `src/curio/metrics.py` | JSON de métricas registra intenção, entidades, representações, queries emitidas/não emitidas, providers, evidência por campo, creator/source/date/type, candidatos, CLIP, seleção e fallback, com limites por cena. |
| `src/curio/config.py`, `config.example.toml`, `pyproject.toml`, `src/curio/cli.py` | CLIP tem config TOML/env, device automático (`xpu`, `cuda`, `mps`), CPU só por opt-in, status em `doctor` e extra opcional `curio[clip]`. A instalação base não instala ML. Pesos só podem baixar após ativação explícita. |
| `README.md` | Fluxo semântico, campos de relevância e ativação do CLIP documentados. |
| `tests/test_visual_director.py`, `tests/test_clip_config.py` | Regressões de ambiguidades, replay de falsos positivos reais, funis completos, idioma original, contexto global, reparo de cenas, resolução pós-download, configuração e reranking CLIP. |
| `tests/test_tts_coverage.py` | Render isolado nos testes de cache afetados pela invalidação de mídia antiga sem contexto visual. Áudio/render não mudaram. |

## 3. Evidências

### Testes

- `python3 -m pytest tests/ -x -q` — **775 passed**, 175,85 s.
- Teste focal atual mais recente — **37 passed** em `test_visual_director.py` e `test_clip_config.py`.
- `python3 -m py_compile` nos módulos alterados — passou.
- `git diff --check` — passou.
- CLIP real não foi instalado: `torch` existe no ambiente; `open_clip` não. O encoder e reranker foram exercitados com modelo falso, sem baixar pesos. Config, shortlist, limite de CPU e fallback sem modelo foram testados.

### Antes/depois: casos reproduzidos

O score lexical legado aceitava cada candidato abaixo com **75/100**, acima do
limite padrão 34. O gate atual devolve **0**, com motivo `no topic evidence`:

| Cena antiga | Título real do candidato | Antes | Agora |
|---|---|---:|---:|
| Revolução Francesa | `File:Dog walker - Buenos Aires.jpg` | 75 | 0 |
| Buraco negro | `Mass station bus terminal` | 75 | 0 |
| Marco Aurélio | `Mughal Empire under Emperor Akbar` | 75 | 0 |

Inspecionei pixels locais das três imagens. Primeira mostra passeador e vários
cães; segunda mostra mapa do Império Mughal sob Akbar; terceira mostra ponte
sobre rio. Confirmações visuais independem dos títulos usados no replay.

### Funis reais, sem LLM e sem render

Executei `fetch_media_multi()` contra providers já existentes, com contexto e
representações explícitos. Busca usou Wikimedia e NASA; total: **6 chamadas de
busca** para 5 cenas. Requisições de manifestos internos da NASA não entram
nesse total.

| Tópico | Asset escolhido | Resultado observado |
|---|---|---|
| Revolução Francesa / Bastilha | `Charles Thévenin - Prise de la Bastille, le 14 juillet 1789` | Pintura da tomada, score de cena 100. Alias em francês permitiu correspondência ao texto inglês da query. |
| Marco Aurélio / guerras marcomanas | `Column of Marcus Aurelius` | Artefato diretamente ligado ao imperador e às guerras romanas, score de cena 100. Dois candidatos de descrição genérica foram rejeitados por falta de evidência da cena. |
| Buracos negros / horizonte de eventos | `Black Hole Milkyway Event Horizon` | Visual do buraco negro e horizonte, score de cena 100. |
| Mercúrio / composição da superfície | `KSC-04pd1531` | Imagem da missão MESSENGER, relacionada ao tópico, mas não mapa de superfície. Score contextual de cena 35; o mapa de potássio mais específico tinha 635×640 px e foi rejeitado após download por resolução mínima de 1080 px. A auditoria registra esse motivo. |
| Efeito Doppler — tópico não cadastrado no léxico | `Transverse Doppler Effect Diagram` | Diagrama do efeito Doppler, score de cena 100. Foram emitidas duas queries; genéricos posteriores não foram consultados. |

Inspecionei os cinco assets escolhidos. Quatro mostram diretamente o evento,
objeto ou mecanismo esperado. MESSENGER é fallback contextual real, não uma
imagem de superfície; o funil informa essa diferença. Nenhuma das cinco cenas
usou fallback sintético.

O cache temporário usado nessa inspeção fica em `/tmp/opencode/curio-visual-director`.
Os arquivos de teste não alteram `output/` nem assets do projeto.

### Custo e performance

- Chamadas LLM adicionais: **0**. Contexto e intenção global usam chamada de cenas existente.
- Prompt de cenas aumentou **1.005 caracteres** em PT e EN, cerca de **250 tokens estimados** por chamada com aproximação chars/4; consumo real de tokens ainda não foi medido.
- Providers/APIs adicionados: **0**. A instalação base não ganhou dependência ML.
- Busca real observada: 1 query em cada cena histórica/científica, exceto Doppler com 2. Limite por execução continua oito queries planejadas por cena; queries não emitidas ficam marcadas.
- Render, TTS e tempo total de geração não foram medidos nesta validação de mídia.

## 4. Status vs requisitos do usuário

Atende às restrições exercitadas: pipeline único, adapters/providers existentes,
busca fresca, cache de download, hierarquia de representação, score separado,
fallback sintético e CLIP opcional. Não há arquivo PRD no checkout; avaliação
usa os requisitos fornecidos pelo usuário e `VIDEO.MD`.

## 5. Limitações e avaliação final

**Melhorou nos casos reproduzidos.** Títulos que antes passavam com 75 agora
falham por falta de tópico/cena. Funis reais selecionaram cinco assets
contextuais; queries irrelevantes não foram consultadas depois da primeira
prova forte. A inspeção de pixels confirmou quatro representações diretas e
um artefato MESSENGER contextual. Isso é evidência concreta de melhoria, não
prova de precisão universal.

Limitações restantes:

1. Mídia de topic novo depende da qualidade do contexto/representações emitidos pelo planner. Valide planner com respostas reais e avalie aliases multilíngues adicionais.
2. Metadata prova relação textual, não conteúdo dos pixels. CLIP segue desligado; modelo real/GPU não foi exercitado.
3. Resolução pode rejeitar mídia conceitualmente melhor, como mapa Mercury de 635×640 px. O Curio então seleciona artefato relacionado de resolução válida ou visual sintético.
4. Alguns providers fornecem só título/ID e pouco contexto; nesses casos o sistema prefere fallback, reduzindo recall para manter precisão.
5. O teste real exercitou estágio de mídia, não geração/render completo. TTS, legendas e render não foram alterados.

Arquivos finais e esse relatório seguem sem commit. A análise inicial permanece
em `docs/analises/20261002-184536_analise-direcao-visual.md`; o relatório
parcial foi preservado como histórico do progresso.
