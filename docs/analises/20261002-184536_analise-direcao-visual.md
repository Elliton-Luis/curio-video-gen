# Análise — Causa arquitetural da seleção de mídia

- **Data:** 2026-10-02 18:45 (-03:00)
- **Tipo:** analise
- **Escopo:** fluxo completo de cenas e mídia, falhas observadas, contratos e arquitetura para direção visual sem implementação
- **Commit(s):** pendente
- **Origem:** solicitação do usuário; métricas e análises locais

## 1. Veredito

O Curio já possui campos e etapas que parecem semânticos (`subject`, `visual_entities`, `context`, `forbidden`, `visual_type`), mas não os produz nem os preserva de forma confiável em todo caminho. A falha central é a ausência de um contrato semântico obrigatório entre planejamento, consulta e avaliação: consultas podem ser tokens locais; o scorer compara título com vocabulário diferente; e busca por si só não prova que asset representa a cena.

O caso recente da Tesla confirma o caminho: planner retornou nove cenas, a validação literal falhou, e o fallback substituiu o planejamento por sete cenas derivadas lexicalmente. `corrente` virou pontes e rio; `Tesla` virou fábrica e rua. Para Marco Aurélio e Revolução Francesa, consultas como `empire`, `aurelio`, `dog`, `sun` e `government` admitiram referentes errados. Aumentar léxicos, proibições ou threshold não corrige a quebra de identidade/contexto.

## 2. Fluxo visual atual real

1. `pipeline.py` planeja cenas via `scenes.build_chapters()`. O prompt de cenas pede narração literal mais `subject`, `visual_type`, queries, entidades, contexto e termos proibidos.
2. `scenes.py` aceita resposta apenas quando concatenação normalizada das narrações reproduz o roteiro. Divergência de texto descarta todas as cenas e chama `_local_chapters()`; não há validação/reparo da contagem esperada quando a narração coincide.
3. `_local_chapters()` agrupa frases e chama `visual.local_queries()`. Cada palavra é traduzida pelo léxico quando disponível; entidade inferida por capitalização e palavras frequentes viram queries. Define a primeira query como assunto e deixa as relações/eventos sem representação.
4. `pipeline.py` marca fallback local e tenta `anchor_local_topic()` e `fill_missing_context()`. Âncora local converte tópico conhecido com `PT_TOPIC_PHRASES`/léxico, mas grava a frase global como âncora, não como modelo de entidades/eventos. `fill_missing_context()` funciona sobretudo para entidade-alvo pesquisada, não para qualquer assunto/evento; tenta traduzir locais isolados pelo léxico.
5. `visual._waterfall_queries()` prioriza queries do planner; senão extrai keywords locais. Junta entidades globais, adiciona variantes históricas por mídia e consultas genéricas por gênero. Ordem máxima oito. Isso amplia cobertura, mas não estabelece se uma query corresponde à intenção atual.
6. `visual._search_scene_with_shortcircuit()` consulta providers configurados, em paralelo por query; ordena providers por política do `GenreAdapter`. Gate de metadados valida URL, licença, dimensão, tamanho, termos decorativos e `forbidden` textual. Gate não julga identidade positiva nem relação semântica.
7. Scoring usa apenas `asset.title` e campos do `Chapter`. Avalia cobertura lexical do núcleo e bônus lexical de apoio; threshold padrão 34. Em cenas locais, `topic_anchor_matches()` exige frase global no título. Passar threshold comprova coincidência textual, não representação da cena.
8. Seleção baixa candidatos aprovados, podendo selecionar até `max_images`; se não houver, tenta diagrama para mecanismos ou visual sintético/cartão. Depois, `_resolve_reuse_multi()` copia assets de cena vizinha sem verificar relação temática. No pipeline legado `pipeline_media.fetch_media()`, há outro score lexical simples e reuso da imagem vizinha.
9. Cache de resultados de busca vive dentro do vídeo; bytes dos assets persistem para rerender. Busca é fresca em nova geração. Timeline varia crops/movimento, não semântica.

## 3. Responsabilidades e pontos de perda

| Módulo | Responsabilidade atual | Limite relevante |
|---|---|---|
| `stages/scenes.py` | Contrato `Chapter`, chamada de planner, validação da narração, divisão local | Descarta todas as cenas por mismatch; não repara contagem; fallback local faz busca lexical por frase |
| `stages/prompts.py` | Prompt JSON para cenas e entidade | Já pede contexto por termo, mas não produz contexto global nem evento/representações explicitamente; exemplos e proibições continuam instruções textuais ao LLM |
| `stages/visual_context.py` | Âncora de tópico local e preenchimento de identidade de entidade pesquisada | Cobertura condicionada a alvo/sources; contexto de vídeo é uma frase/alias, não universo global estruturado |
| `stages/visual.py` | Query waterfall, providers, gate, scoring/ranking, download, síntese e reuse | 1.197 linhas; keywords entram quando não há queries; pipeline executa níveis em lote e coleta por quantidade antes da validação semântica |
| `stages/scoring.py` | Core lexical 0–75, apoio lexical até 25, threshold e extensão CLIP | Não usa query associada ao resultado, tags/descritivo estruturado ou tipo/provider; nenhum gate semântico positivo |
| `stages/media_rules.py` | Rejeições duras com motivo | Detecta blacklist em título; ausência de conflito não prova pertinência |
| `media/providers.py` | Adapters de Wikimedia, Openverse, Pixabay, Pexels, Unsplash, NASA, Met e AIC | `MediaAsset` não tem descrição/tags/categoria/data/tipo de representação estruturados; alguns adapters comprimem tags em `title` |
| `stages/editorial.py` | `GenreAdapter`: providers, mídia genérica, direção e fontes | Mantém políticas editoriais reaproveitáveis; não deve virar catálogo de assunto |
| `pipeline_media.py` | mídia manual, modo legado, status e fallback simples | Seu `_resolve_reuse()` também reusa vizinho sem prova de pertinência |
| `stages/visuals.py` | Cartões/diagramas offline e fallback visual | Recurso seguro já existe, mas não cobre todas as intenções em formato específico |
| `textnorm.py` | Normalização, stopwords, léxico PT→EN e frases de tópico | Seu próprio contrato diz que compara texto; no caminho atual heurísticas o usam indiretamente para decidir intenção/query |

Intenção hoje nasce em dois lugares: prompt LLM de cenas (texto livre + campos) ou extração lexical em `local_queries()`. Em `Chapter`, os campos estruturados já podem carregar intenção, mas não há objeto obrigatório nem validação semântica. Contexto se perde quando `_local_chapters()` reconstrói cenas, e também quando queries executadas ficam em variáveis locais sem alimentar exatamente a avaliação da cena.

## 4. Papel real do léxico e dependência lexical

`PT_LEXICON` contém 297 entradas simples, com mapeamentos polissêmicos por definição (`massa→mass`, `campo→field`, `corrente` sem desambiguação lexical) e mapeamentos de componentes de expressão (`buraco`/`negro→black hole`). `PT_TOPIC_PHRASES` contém 17 frases de domínio, várias adicionadas para corrigir temas já vistos. Não é compreensão: é tradução/normalização e uma pequena lista de exceções de assunto.

No fallback, `local_queries()` usa palavras capitalizadas, frequência, stopwords e tradução para construir até duas queries. Na trilha principal, query waterfall aceita termos textuais do planner e combina aliases, topic phrases, meios e genéricos. Scoring e gate são lexicais: tokens de título e termos proibidos. Portanto a decisão efetiva depende fortemente de overlap lexical; o número de candidatos/score não mede compreensão.

Pode-se preservar `textnorm` para comparação, tradução auxiliar, alias e compatibilidade. Ele não deve produzir sozinho intenção visual, desambiguar referente, escolher representação ou aprovar asset.

## 5. Por que candidatos absurdos passam

- Títulos de providers são incompletos e heterogêneos. Pixabay põe tags no campo `title`; Wikimedia normalmente fornece nome de arquivo; Pexels fornece `alt`; NASA adiciona até cinco keywords. Não há descrição unificada para decisão.
- Score não exige correspondência de frase, alias completo ou relação entre evento e objeto em cenas LLM. Um token de título pode pontuar; a aprovação por threshold decorre de número/peso de tokens do núcleo, não prova de referente. Cenas locais têm âncora global, mas só quando a frase também existe no título.
- A âncora de tópico local ajuda, porém não basta para muitos recursos: exige a expressão completa literalmente no título; restringe recall de obras corretas sem nome do tópico e não distingue contexto/entidade homônima quando apenas termos gerais chegam ao scoring.
- `forbidden` é fornecido pelo próprio planner e comparado somente com título. Lista vazia, tradução diferente, metadado ausente ou conteúdo não textual não gera conflito detectável.
- Candidato pode entrar na busca por query ambígua e ser considerado elegível pelo gate de formato/licença. Métricas atuais explicam depois score baixo, mas não guardam todos os motivos completos nem evidência semântica positiva.
- Fallback final reutiliza asset da cena vizinha sem relação verificada. Mesmo asset aprovado para uma cena pode estar errado em outra.

## 6. Fallback local e falhas do planner

O planner solicita `{n-1, n, n+1}` cenas. `build_chapters()` não compara número de cenas com `n`; aceita qualquer quantidade se narração normalizada bater. Se narração divergir, descarta estrutura visual toda e usa `_local_chapters()`. Isso explica 7 cenas para alvo 6 e 9 para alvo 8: a validação está centrada na preservação de palavras, não na estrutura.

Reparo seguro futuro: preservar correspondência literal/ordem; para excesso, unir segmentos adjacentes e agregar metadados com evidência; para falta, dividir segmentos em limites de frases e derivar sub-intenção do contexto herdado; rejeitar apenas payloads impossíveis de reparar. Nunca fundir intenção incompatível. Se texto também estiver adulterado, fallback local continua necessário, mas deve receber contexto global já resolvido e gerar intenção/representação segura antes das queries.

## 7. Métricas de evidência

Métricas locais usadas: `metrics/20261002-180209_20261002_fale-sobre-nikola-tesla-o-genio.json`, `metrics/20261002-154227_20261002_imperador-marco-aurelio-seus-fe.json`, `metrics/20261002-154644_20261002_revolucao-francesa-sua-causa-su.json` e análises já registradas em `docs/analises/`.

| Caso | Evidência do funil | Sintoma/custo |
|---|---|---|
| Nikola Tesla | 9 cenas do planner reprovadas por reprodução; fallback local 7. 56 queries; 108 resultados, 89 únicos, 84 elegíveis, 33 score rejects, 51 acima do corte, 21 escolhidos. | Mídia 50,42 s; incluiu ponte do Rio Corrente, Tesla Gigafactory/rua Nová Tesla, campos, relógios e máquinas CNC. 4 chamadas LLM no total da execução, 4.995 tokens de prompt + 1.927 completion; não existe chamada LLM só para visual director hoje. |
| Marco Aurélio | 6 cenas locais; 48 queries; 87 normalizados, 72 únicos/elegíveis, 48 score rejects, 24 acima do corte, 11 assets reais + 2 cartões. | Mídia 33,55 s. Mughal Empire, guerras modernas na Armênia, Fábio Aurélio e cachorro “Aurelio” passaram como mídia. |
| Revolução Francesa | 8 cenas locais; 64 queries; 128 normalizados, 124 únicos, 120 elegíveis, 78 score rejects, 42 acima do corte; 6 genéricos usados. | Mídia 54,43 s. Carros “ultima”, cão, paisagem solar, igreja, escola governamental moderna e arquivo `Compartilhe.jpg`. |

Histograma de rejeições mostra que gate lexical rejeita bastante lixo, mas isso não impede falsos positivos acima do corte. Nos três casos, custo de mídia supera 33 s e pode consultar quatro providers por query. Métricas de score somam funil, mas não preservam por cena intenção, query-provider-candidato completo, topic/scene relevance, decomposição de pesos, bônus/penalidades nem justificativa da seleção. CLIP não ranqueia hoje: `rank_candidates()` executa só camada base.

## 8. Componentes a preservar

- Pipeline único e ponto coordenador existente (`pipeline.py`); `GenreAdapter` declarativo.
- `Chapter` como contrato retrocompatível e serialização `chapters.json` via `to_dict/from_dict`.
- Providers existentes, prioridade específica por gênero, consulta concorrente limitada, timeouts e cache de busca restrito à execução.
- Cache de bytes, busca fresca por nova geração, normalização lexical como ferramenta auxiliar.
- Gate único de licença/formato/resolução/tamanho e motivo, score threshold configurável como etapa de ranking, folha de contato, métricas e logs existentes.
- Síntese offline, cartões tipográficos, diagramas mecanísticos e timeline com crop/movimento.
- Pesquisa de entidade e aliases autoritativos quando disponíveis. Integrar resultado no contexto visual; não duplicar chamada de pesquisa/planner.

## 9. Arquitetura proposta

Criar contrato semântico de vídeo mais contrato de intenção por cena, sem pipeline paralelo:

1. Contexto visual do vídeo: tópico canônico, entidades primárias/secundárias, lugares, eventos, períodos, aliases e evidência/proveniência. Construir com target/research existentes e uma resposta estruturada do planner de cenas. Persistir em `chapters.json`/metadados com defaults retrocompatíveis.
2. Diretor visual roda antes dos providers. Para cada cena, registra resumo narrativo, intenção “o que aparece agora”, entidade/evento primário, relações/contexto herdado, período/local, tipo de visual e representações aceitáveis com evidência. Pode ser emitido na mesma chamada LLM de cenas; fallback compõe intenção aproximada com contexto global e entidades verificadas, sem léxico como cérebro.
3. Gerador de queries transforma representações ordenadas em queries compostas. Preserva categoria/prioridade e relação da query com a cena; léxico só normaliza/traduz aliases. Mantém orçamento de buscas e providers atuais.
4. Normalizador de candidatos preserva metadados disponíveis em campos separados (título, descrição, tags, categorias, creator, data/período, provider/source, tipo), sem fingir que todos providers fornecem tudo.
5. Gate temático avalia duas dimensões explícitas: topic relevance e scene relevance. Exige evidência de entidade/relação/tipo representado; identifica ambiguidade e conflito. Um match lexical pode recuperar candidato, nunca aprová-lo sozinho. Incerteza sem prova cai para representação mais ampla validada, asset verificado reutilizado ou síntese segura.
6. Busca hierárquica avança uma classe de representação por vez: evento/objeto/pessoa exata; entidade; alternativa visual da mesma entidade/evento; secundária relacionada; lugar/período; documento/mapa/artefato/retrato. Avalia e para após shortlist útil; evita gastar providers e queries genéricas quando há asset preciso.
7. Ranking aplica ordem: relevância temática, relevância da cena, correção, qualidade, diversidade. Diversidade desempata candidatos relevantes; nunca promove candidato menos relevante acima de outro melhor.
8. Fallback segura conteúdo: não usar imagem genérica para alegar representação. Reusar somente asset cujo topic relevance seja alto e cuja categoria seja válida para cena; documentar escopo de reuse. Depois usar retrato/mapa/documento relacionado, síntese/diagrama, e background neutro como último recurso. Não transferir cegamente imagem de cena vizinha.
9. Observabilidade grava registro por cena e decisão por candidato: contexto, intenção, entidades, representação, query, provider, metadados/evidências, scores separados, bônus/penalidades, rejeição, shortlist, asset final, motivo e fallback. Candidato absurdo precisa ter query de origem e motivo de inclusão visíveis.
10. CLIP fica adapter opcional pós metadata gate e shortlist pequena. Continua desligado por padrão; torch/modelo só carregam se ativados; GPU automática, CPU somente com ativação/config explícita. CLIP só reranqueia imagens baixadas/shortlist contra representação estruturada; não busca e não aprova isolado sem gate semântico.

## 10. Contratos que precisam mudar

| Contrato | Mudança necessária | Compatibilidade |
|---|---|---|
| Saída de cenas | Resposta traz contexto global + cenas com intenção/entidades/representações tipadas e queries deriváveis; narração literal permanece invariantemente preservada | Aceitar schema antigo com conversor; novas propriedades opcionais para arquivos existentes |
| `Chapter` | Guardar intenção estruturada, representação esperada, relações, prioridade e contexto herdado; preservar `visual_queries` como campo derivado/legado | `from_dict()` injeta defaults; timing já copia `to_dict()` integral |
| Planejamento | Retornar contexto do vídeo juntamente com capítulos, ou carregá-lo num objeto serializável ligado aos capítulos | Nenhum planner LLM separado; uma chamada atual de cenas no máximo |
| `MediaAsset` | Campos de metadados opcionais sem colapsar todos em `title` | Providers atuais preenchem o que têm; campos vazios não contam como evidência |
| Candidato/score | Candidato mantém query exata, nível hierárquico e evidência. Resultado expõe topic score, scene score, confidence, bônus, penalidades e motivos | Manter `score` legado como score final para relatórios/clientes atuais |
| Seleção/reuse | Seleção recebe intenção e critérios de fallback; reuse exige compatibilidade em vez de mera proximidade de cena | Formato `media.json` recebe campos opcionais |
| Métricas | Evento detalhado por cena e candidato com limite de cardinalidade, incluindo todos selecionados e rejeições decisivas | Somar nos agregados atuais; evitar logar conteúdo sensível/payload LLM completo |
| Configuração CLIP | Flag desativada por padrão, device e limites CPU/shortlist; extra opcional real no `pyproject.toml` ou instrução de instalação isolada | Instalação base segue sem dependência ML; corrigir referência atual a `video-gen[clip]`, que não existe neste `pyproject.toml` |

## 11. Impacto estimado

- **LLM:** zero chamadas adicionais no caminho normal. Enriquecer chamada existente de cenas com contexto global + intenções; resposta maior pode aumentar tokens de completion. Validar que planner condicional por pesquisa rica continua sem chamada extra.
- **Rede:** zero providers/APIs novos. Query composta e busca hierárquica devem reduzir requisições versus limite atual observado de 56–64 queries por vídeo, mas ranking incremental pode gastar mais tempo por query se continuar procurando após primeira shortlist. Definir orçamento por nível e medir.
- **CPU:** contexto estruturado, regras de evidência e scores têm custo baixo comparado à rede/download/render. Nenhuma dependência nova no caminho base.
- **GPU/CPU ML:** nenhum custo padrão. CLIP só em shortlist pequena e só com opt-in; GPU quando disponível. CPU exige opt-in explícito e precisa limite/timing para não atrasar render.
- **Latência:** pode cair ao interromper cascata quando há prova de cena; pode subir se representação exata não trouxer resultados e níveis precisarem ser tentados. Usar limite por fase/timeouts existentes e medir fase a fase.
- **Custo financeiro:** sem novas APIs pagas; providers pagos permanecem ausentes. Chamadas de LLM seguem cadeia já configurada.

## 12. Testes de produto para fase 2

Além de testes unitários, replay determinístico de pipeline sem rede com providers simulados e títulos/metadados realistas. Cobrir French Revolution × French bulldog; Roman Empire × produto/homônimo Roman; Mercury planeta × carro; Java linguagem × ilha/café; mass física × mass station; pessoa histórica × homônimo moderno. Medir intenção, queries, candidato incluído, decisão/rejeição e asset final.

Validar fluxo completo para Revolução Francesa, César/Marco Aurélio, buracos negros, ciência ambígua e tópico novo fora do léxico. Incluir payload planner com excesso/falta reparável e narrativas inválidas que ainda exigem fallback. Testes provarão que resolução não depende de acrescentar termo aos mapas. Rodar suíte completa e smoke/render representativo sem atribuir adequação visual só pelo título; amostras finais precisam inspeção de pixels.

## 13. Riscos e o que não mexer

- Metadados textuais não provam pixels. CLIP pode confirmar semelhança visual, mas não factualidade ou período histórico; fonte/descrição e identidade continuam necessárias.
- Similaridade semântica ampla pode voltar a aceitar candidato temático, mas errado para cena. Manter dois scores e threshold/gate independente.
- Metadata disponível varia por provider. Ausência deve reduzir confiança e orientar fallback, não virar aprovação implícita.
- Contexto global pode vazar entidade secundária para cena errada. A intenção local deve declarar relação e nível de prioridade.
- Reparo de quantidade só é seguro se preserva ordem/texto e não mistura segmentos semanticamente incompatíveis.
- Não alterar áudio, render, legendas ou providers; não adicionar dicionários por tema, APIs ou dependência ML obrigatória.

## 14. Estado da fase

Diagnóstico concluído. Nenhum código ou configuração de produto foi alterado. Próxima etapa exige autorização explícita para iniciar fase 2; implementar incrementalmente, manter suíte verde e produzir relatório de entrega conforme `docs/_modelos/MODELO.md`.
