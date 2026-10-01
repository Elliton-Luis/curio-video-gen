# Análise — Contrato de geração automática de roteiro por IA

- **Data:** 2026-10-01 03:29 -03:00
- **Tipo:** analise
- **Escopo:** prompts, dados, formatos, validações, fallbacks e consumo posterior da geração automática de roteiro.
- **Commit(s):** pendente
- **Origem:** solicitação para documentar contrato atual e template manual compatível.

## 1. Veredito

A geração automática de roteiro solicita **texto puro de narração**, não JSON. O título é gerado em chamada separada; cenas, termos visuais e metadados também pertencem a etapas distintas.

O modo `Roteiro Pronto` aceita somente texto integral como narração. Colar JSON ou metadados nessa entrada faria esses dados serem tratados como texto narrado; o modo não preserva a estrutura automática.

## 2. Evidência consultada

- Código: `src/curio/stages/nvidia.py`, `script.py`, `entity.py`, `research.py`, `editorial.py`, `scenes.py`, `visual.py` e `pipeline.py`.
- Fluxo da interface: `src/curio/cli.py` (`from-script`) e `src/curio/tui.py` (`_script_flow`).
- Documentação de continuidade: `docs/_modelos/MODELO.md`, `docs/README.md` e relatório de gênero `20260930-221049_relatorio_tui-seletor-vertical-genero.md`.
- Relatório recente consultado: `20260930-232100_relatorio-diagnostico-groq-nvidia-json.md`.
- Métricas: `metrics/` não contém registros nesta cópia. Não há evidência de execução recente de roteiro para comparar.

## 3. Contrato da chamada que gera o roteiro

### 3.1 System prompt integral — português

O código interpola `{duration_clause}` neste texto. Não há schema JSON de roteiro.

```text
Você escreve roteiros curtos e envolventes de vídeo educativo em português do Brasil. O roteiro será lido em voz alta, {duration_clause}. Regras de narrativa (obrigatórias): 1) comece com uma pergunta, afirmação intrigante ou problema; 2) toda pergunta criada deve ser respondida em algum momento; 3) crie novas perguntas ao longo do roteiro para manter a curiosidade; 4) cada parte leva naturalmente à próxima, com progressão — não entregue tudo de uma vez; 5) priorize o mais interessante e surpreendente; corte o que não ajuda a história; seja conciso; 6) termine respondendo à ideia principal apresentada no início; 7) escreva como quem conta algo interessante a um amigo, não como quem lê um artigo: frases faladas e curtas, com ritmo; perguntas retóricas, comparações simples e pequenas surpresas são bem-vindas; um toque de personalidade, sem gíria e sem forçar humor; 8) proibido introduções genéricas ('Olá pessoal, hoje vamos falar sobre...', 'Você sabia que' e equivalentes); 9) GROUNDING OBRIGATÓRIO: toda afirmação factual (datas, nomes, números, definições, eventos, etimologias) deve vir das FONTES FORNECIDAS junto ao pedido; é PROIBIDO afirmar qualquer fato ausente das fontes; se algo for incerto ou não estiver nas fontes, diga a incerteza com honestidade ou omita — nunca preencha com invenção; 10) sem fontes falsas nem estudos inexistentes; nunca invente fatos, datas, nomes ou citações para ficar interessante; 11) proibido tom de documentário institucional e conclusões artificiais ('diante disso, podemos concluir', 'é importante ressaltar', 'vale destacar', moral da história ou resumo acadêmico); feche com a resposta ou uma observação que aproxime o assunto do espectador. 12) explique conceitos complexos em palavras simples: se mencionar algo técnico, explique na hora com analogia ou definição direta (ex.: 'se o ângulo for rasante o suficiente, ou seja, se o ângulo for bem próximo do chão...'); nunca use jargão sem explicar. 13) SEMPRE encerre assim: depois de responder a ideia principal, faça UMA pergunta aberta relacionada ao tema mas NÃO respondida no vídeo (gancho para comentários — ex.: 'mas será que se ele tivesse ido mais preparado para o frio, teria ganhado?'), e em seguida uma chamada curta para like ('deixe seu like e até o próximo vídeo'). FORMATO DE SAÍDA (obrigatório): responda SOMENTE com o texto da narração. PROIBIDO: títulos, 'Cena 1', 'Narrador:', rubricas entre colchetes, markdown, listas, aspas de diálogo, emojis, preâmbulos como 'Aqui está' ou qualquer explicação sobre o roteiro. Se precisar raciocinar, faça-o apenas no raciocínio interno, nunca no texto final. Princípio editorial: simplificar para tornar acessível, nunca falsificar para viralizar. O objetivo é o espectador continuar assistindo porque sempre há uma pergunta sendo respondida e outra surgindo.
```

### 3.2 System prompt integral — inglês

Selecionado quando `language.lower().startswith("en")`.

```text
You write short, engaging educational video scripts in American English. The script will be read aloud, {duration_clause}. Mandatory storytelling rules: 1) start with an intriguing question, statement or problem; 2) every question you raise must be answered at some point; 3) raise new questions along the way to sustain curiosity; 4) each part leads naturally to the next, with progression — never dump everything at once; 5) prioritize the most interesting and surprising; cut whatever does not serve the story; be concise; 6) end by answering the main idea from the beginning; 7) write like someone telling a friend something interesting, not like reading an article: short spoken sentences with rhythm; rhetorical questions, simple comparisons and small surprises are welcome; a touch of personality, no slang, no forced humor; 8) no generic intros ('Hey guys, today we will talk about...', 'Did you know that' and equivalents); 9) MANDATORY GROUNDING: every factual claim (dates, names, numbers, definitions, events, etymologies) must come from the PROVIDED SOURCES; it is FORBIDDEN to state any fact absent from the sources; if something is uncertain or not in the sources, state the uncertainty honestly or omit it — never fill gaps with invention; 10) no fake sources or nonexistent studies; never invent facts, dates, names or quotes to sound interesting; 11) no institutional documentary tone and no artificial conclusions; close with the answer or an observation that brings the topic closer to the viewer. 12) explain complex concepts in simple words: whenever you mention something technical, explain it on the spot with an analogy or a direct definition; never use unexplained jargon. 13) ALWAYS end like this: after answering the main idea, ask ONE open question related to the topic but NOT answered in the video (comment hook — e.g.: 'but would he have won if he had been better prepared for the cold?'), followed by a short like call-to-action ('leave a like and see you in the next video'). OUTPUT FORMAT (mandatory): answer ONLY with the narration text. FORBIDDEN: titles, 'Scene 1', 'Narrator:', bracketed stage directions, markdown, lists, dialogue quotes, emojis, preambles like 'Here is' or any explanation about the script. If you need to reason, do it only in internal reasoning, never in the final text. Editorial principle: simplify to make accessible, never falsify to go viral.
```

### 3.3 User prompt integral

Português:

```text
Escreva o roteiro de narração para a ideia: {idea}
```

Inglês:

```text
Write the narration script for this idea: {idea}
```

Após o prefixo, o código acrescenta blocos opcionais nesta ordem: `entity_context`, depois `research`.

### 3.4 Duração e limite de texto

O chamador calcula `max_chars` usando `CHARS_PER_SECOND = 13.5`:

- Automático (`duration_target <= 0`): `max_chars=None`, teto técnico `AUTO_MAX_CHARS=4000`. Cláusula PT exata: `sem duração fixa: complete o assunto com começo, meio e fim, sem enrolar nem cortar (teto técnico de 4000 caracteres)`. O conteúdo define duração; 4000 é proteção técnica, não meta.
- Duração definida: `ceiling = int(duration_target * 13.5)`. Cláusula PT: `com duração aproximada de {round(ceiling / 13.5)} segundos (no máximo {ceiling} caracteres; meta, não corte seco)`. Limites de duração aceitos pela configuração: 5 a 600 segundos.
- Inglês usa `no fixed duration: cover the subject with beginning, middle and end, no padding and no cutting (technical ceiling of {ceiling} characters)` ou `about {round(ceiling / 13.5)} seconds long (at most {ceiling} characters; target, never a hard cut)`.
- A chamada HTTP usa `temperature=0.7`, `max_tokens=1500`. Se `finish_reason == "length"`, faz segunda chamada com `max_tokens=3000`; não há terceira escalada neste gerador.
- Payload da chamada de roteiro: `model`, `messages=[system,user]`, `temperature`, `max_tokens`; roteiro não envia `response_format` nem JSON mode. Para modelo Groq GPT-OSS, `_post_once()` acrescenta `reasoning_effort="low"`.
- Essas chamadas entram no rodízio geral de providers/retries de `_chat`; o prompt não escolhe provider individual.
- A resposta precisa conter `choices[0].message.content`. Se `finish_reason` continuar `length` após segunda chamada, erro fatal para a etapa. Texto limpo com menos de 100 caracteres também é rejeitado.
- Divergência: prompt chama limite de duração definida de “meta, não corte seco”, mas `_sanitize()` corta o resultado final a `ceiling` caracteres mesmo assim.

### 3.5 Dados variáveis e blocos inseridos

| Dado | Origem | Entra em |
|---|---|---|
| `idea` | Entrada do usuário | User prompt, busca de pesquisa e resolução da entidade. Preservada verbatim no prompt, sem `strip()` nessa interpolação. |
| Idioma | `cfg.language` | Escolhe prompt PT-BR ou American English; pesquisa, entity resolver e diretrizes também recebem idioma. Valor padrão `pt-BR`. |
| Duração/`duration_clause` | `cfg.duration_target` | System prompt; determina também teto de caracteres. |
| Diretriz de gênero | Perfil de `cfg.genre`/gênero explícito do pipeline | Acrescentada ao final do system prompt, depois de duas quebras de linha. Sem gênero, não é acrescentada. |
| Contexto de entidade | Resultado de `resolve_entity()` convertido por `entity.script_context()` | Acrescentado ao user prompt depois da ideia. Vazio se não houver entidade própria ou nome-alvo. |
| Fontes | `research_topic()` e `format_for_prompt()` | Bloco acrescentado por último ao user prompt; uma fonte real é requisito da pesquisa antes da geração. |
| Modelo e base | Configuração ambiente/TOML/default e chain | Payload HTTP, não texto do prompt. |
| Métricas | `RunMetrics` | Passadas ao código para contagem; não são conteúdo do prompt. |

Formato exato de contexto de entidade em português, com linhas condicionais:

```text
O SUJEITO DESTE VÍDEO É: {target.name}.
É a mesma pessoa que: {aliases separados por vírgula}. Pode usar uma forma mais curta quando a narração pedir, mas conserve a forma que identifica quem é.
Termos que identificam ESTE sujeito: {discriminants separados por vírgula}.
NUNCA confunda este sujeito com: {forbidden separados por vírgula}. São outros lugares ou outras pessoas; falar deles significa que o vídeo é sobre outra coisa.
```

As linhas sobre aliases, discriminants e forbidden só existem quando as listas correspondentes não estão vazias. Inglês usa os equivalentes `THE SUBJECT OF THIS VIDEO IS`, `It is the same person as`, `Words that identify THIS subject` e `NEVER confuse this subject with`.

Formato exato do pack de fontes em português:

```text
FONTES OBRIGATÓRIAS (pesquisa web — use SOMENTE estes fatos):
[1] {title} — {url}
    trecho: {snippet}
[2] {title} — {url}
    trecho: {snippet}
```

Cada fonte é incluída nessa forma até atingir `PROMPT_BUDGET_CHARS=2500`, contando o cabeçalho e chunks; a conta não inclui os `\n` que `join()` insere. A pesquisa suporta até `cfg.research_max_sources` (default 3), extrai até 1200 caracteres por artigo, remove whitespace repetido do trecho e filtra fontes sem relação com o referente/tema. O pack não inclui campos `origin`, target, queries tentadas, fontes rejeitadas nem metadados de pesquisa. Inglês usa cabeçalho `MANDATORY SOURCES (web research — use ONLY these facts):`; o label do trecho continua `trecho:`.

### 3.6 Gênero e diretriz interpolada

O bloco é texto literal criado por `editorial.script_directive(profile)`. Não existe gênero padrão: vazio significa nenhuma diretriz. Os perfis existentes são:

| Chave | Direção efetiva de roteiro | Ritmo solicitado | Fechamento e legenda |
|---|---|---|---|
| `history` | Gancho, contexto mínimo, situação inicial, ruptura, escalada, acontecimento principal, consequência, legado; evitar resumo cronológico/lista de datas. | Alta densidade; 9 s/cena (3,5–18); ritmo moderado crescente, acelera no evento. | Fechar no legado/consequência atual. Destacar nomes, lugares e datas; corte de 5 em 5. |
| `etymology` | Palavra hoje, estranhamento, forma antiga, origem, transformação, significado intermediário e atual; marcar etimologia popular como popular. | Alta; 7,5 s (2,5–13); rápido e revelador. | Fechar na transformação do sentido. Destacar a palavra; corte de 4 em 4. |
| `mythology` | Gancho, mundo, personagem/entidade, conflito, desenvolvimento, clímax e significado; não tratar reconstrução moderna como fato. | Média; 12 s (5–22); atmosférico, com variações. | Fechar no significado atual da tradição. Destacar entidade/tradição; corte de 6 em 6. |
| `mystery` | Mistério, contexto, fatos, pistas, contradições, hipóteses, conhecido e sem resposta; não inventar resolução nem afirmar hipótese como fato. | Média; 11 s (4–19); pausas antes da revelação. | Fechar no que segue sem resposta. Marcar fato/hipótese/não confirmado. |
| `science` | Fenômeno/pergunta, problema, observação, descoberta, mecanismo, evidência e implicação; não acumular curiosidades sem explicar mecanismo. | Média; 14 s (6–26); tempo para acompanhar mecanismo. | Fechar na implicação prática. Destacar termos técnicos/medidas; corte de 6 em 6. |
| `people` | Gancho humano, pessoa, mundo, transformação, conflito/desafio, decisão/obra, consequências e legado; adaptar à vida, sem cronologia seca, hagiografia ou propaganda. | Média; 13 s (4–28); momentos decisivos respiram. | Fechar no legado atual. Destacar nome/lugar/data; corte de 6 em 6. |

A diretriz do gênero também acrescenta obrigatoriedade de distinguir categorias factuais e, quando configurado, linha `ENDING` e `CAPTIONS`. Os metadados de pacing e captions afetam cenas/legendas downstream; não são campos de saída do roteiro.

Textos literais gerados para as seis opções:

```text
history:
EDITORIAL GENRE: História geral / Dark History. This video must be recognisably this genre, not a generic educational video with a different title.
NARRATIVE STRUCTURE — follow it: Estrutura: gancho, contexto mínimo, situação inicial, ruptura, escalada, acontecimento principal, consequência, legado. Não entregue tudo em ordem cronológica.
DO NOT: Não transforme em resumo cronológico nem em lista de datas.
PACING: high information density, roughly 9 seconds of narration per scene (between 3.5 and 18). Moderate and rising, accelerating through the event.
You MUST keep these separate in the narration and never present one as another: o,  , q, u, e,  , é,  , r, e, g, i, s, t, r, o,  , d, o, c, u, m, e, n, t, a, l,  , e,  , o,  , q, u, e,  , é,  , a, t, r, i, b, u, i, ç, ã, o,  , p, o, s, t, e, r, i, o, r.
ENDING: Feche no legado ou na consequência que dura até hoje.
CAPTIONS: Destaque nomes de pessoas, lugares e datas; corte de 5 em 5.

etymology:
EDITORIAL GENRE: Etimologia e origem de palavras. This video must be recognisably this genre, not a generic educational video with a different title.
NARRATIVE STRUCTURE — follow it: Estrutura: a palavra hoje, o estranhamento, a forma antiga, a origem, a transformação, o significado intermediário, o significado atual.
DO NOT: Não diga que uma etimologia popular é verdade sem marcar que é popular.
PACING: high information density, roughly 7.5 seconds of narration per scene (between 2.5 and 13). Fast and revelatory, with a feeling of discovery.
You MUST keep these separate in the narration and never present one as another: origem documentada, hipótese, etimologia popular.
ENDING: Feche na transformação do sentido, não numa curiosidade solta.
CAPTIONS: Destaque a própria palavra a cada menção; corte de 4 em 4.

mythology:
EDITORIAL GENRE: Mitologia e folclore. This video must be recognisably this genre, not a generic educational video with a different title.
NARRATIVE STRUCTURE — follow it: Estrutura: gancho, mundo, personagem ou entidade, conflito, desenvolvimento, clímax, significado.
DO NOT: Não apresente reconstrução moderna como fato histórico.
PACING: medium information density, roughly 12 seconds of narration per scene (between 5 and 22). Atmospheric, with rhythm changes.
You MUST keep these separate in the narration and never present one as another: tradição, fonte textual, interpretação moderna.
ENDING: Feche no significado que a tradição carrega até hoje.
CAPTIONS: Destaque o nome da entidade e da tradição; corte de 6 em 6.

mystery:
EDITORIAL GENRE: Mistérios e casos não resolvidos. This video must be recognisably this genre, not a generic educational video with a different title.
NARRATIVE STRUCTURE — follow it: Estrutura: o mistério, o contexto, os fatos estabelecidos, as pistas, as contradições, as hipóteses existentes, o que sabemos, o que continua sem resposta.
DO NOT: Não invente resolução e não apresente hipótese como fato.
PACING: medium information density, roughly 11 seconds of narration per scene (between 4 and 19). Controlled, with pauses before the reveal.
You MUST keep these separate in the narration and never present one as another: fato documentado, testemunho, alegação, hipótese, não confirmado.
ENDING: Feche no que continua aberto, sem resolver por conveniência.
CAPTIONS: Destaque a palavra do status: fato, hipótese, não confirmado.

science:
EDITORIAL GENRE: Ciência e descobertas. This video must be recognisably this genre, not a generic educational video with a different title.
NARRATIVE STRUCTURE — follow it: Estrutura: fenômeno ou pergunta, o problema, a observação, a descoberta, o mecanismo, a evidência, a implicação.
DO NOT: Não acumule curiosidades sem montar o mecanismo.
PACING: medium information density, roughly 14 seconds of narration per scene (between 6 and 26). Slow enough for the viewer to follow the mechanism.
You MUST keep these separate in the narration and never present one as another: evidência medida, hipótese, especulação.
ENDING: Feche na implicação prática, não em 'é muito importante'.
CAPTIONS: Destaque termos técnicos e medidas; corte de 6 em 6.

people:
EDITORIAL GENRE: História de pessoas. This video must be recognisably this genre, not a generic educational video with a different title.
NARRATIVE STRUCTURE — follow it: Estrutura: gancho humano, quem era, o mundo em que viveu, a primeira transformação importante, o conflito ou desafio, a decisão ou obra central, as consequências, o legado. Adapte à pessoa: uma vida marcada por uma única descoberta pode concentrar o vídeo nela. Não empilhe cronologia seca.
DO NOT: Não reduza a vida a nascimento, estudo, casamento e morte, e não transforme biografia em hagiografia nem em propaganda.
PACING: medium information density, roughly 13 seconds of narration per scene (between 4 and 28). Varied, with decisive moments allowed to breathe and routine information compressed.
You MUST keep these separate in the narration and never present one as another: trajetória documentada, tradição devocional, atribuição posterior.
ENDING: Feche no legado: o que da pessoa continua presente.
CAPTIONS: Destaque nome, lugar e data; corte de 6 em 6.
```

**Inconsistência observada:** em `HISTORY.research.must_distinguish`, o código declarou string única em vez de tupla. `script_directive()` chama `", ".join()` nessa string e envia letras separadas: `o,  , q, u, e,  , é, ...`. O roteiro recebe instrução quebrada nesse ponto. Registrei o defeito; esta tarefa não altera código.

## 4. Resposta do roteiro e validação

### 4.1 Formato esperado

Resposta de roteiro: texto puro, somente narração. Não há objeto JSON, chaves obrigatórias, campos opcionais, título, keywords, tags, metadata, consultas visuais ou fontes estruturadas na resposta. Fontes e contexto aparecem no input; o output requerido continua prosa.

O parser extrai só `choices[0].message.content`. Após duas tentativas no limite de tokens, `nvidia._sanitize(text, ceiling)`:

1. remove blocos `think...end` (case-insensitive, multiline) e cercas ```...```;
2. remove rubricas em colchetes e prefixos de linha `Narrador:`, `narração:`, `roteiro:`, `narrator:` ou `script:`;
3. remove preâmbulos iniciais reconhecidos (`aqui está...`, `roteiro...`, `claro`, `here is`, `here's`, `sure`, `of course`);
4. remove marcadores de lista por `subs.strip_list_markers`;
5. remove `*`, `#` e aspas duplas; colapsa whitespace e remove cercas/apóstrofos dos extremos;
6. se exceder teto, corta na última fronteira de frase encontrada depois de metade do limite; sem essa fronteira, corta na última palavra completa e acrescenta ponto final.

Sanitização não verifica verdade, aderência a fontes nem presença de pergunta final/CTA. A pesquisa posterior `verify_grounding()` confere fatos numéricos e emite avisos; ela não remove afirmações não verificadas do roteiro.

### 4.2 Erros e fallbacks

- Chave LLM disponível: erro HTTP/rede, resposta sem `choices/message`, truncamento persistente ou texto limpo com menos de 100 caracteres falha a etapa; não troca silenciosamente para texto local.
- Sem chave LLM: não há prompt de IA. Português tenta texto curado para alguns temas; caso contrário usa template local. O template/curado não implementa os campos estruturados de cenas.
- Título é chamada separada. Resposta inválida, JSON ruim, erro de provider ou validação rejeitada usa `_fallback_title()`, baseado na ideia original; não altera narração.
- Falha de parsing/validação na geração de cenas, ou narrações de cena que não reproduzem o roteiro segundo `_norm()`, usa divisão local por frases. Essa queda local preserva o roteiro e perde consultas visuais produzidas pela IA.
- Pesquisa sem fonte utilizável levanta `ResearchError`; não gera roteiro apenas com IA.

## 5. Chamadas anteriores e posteriores — schemas que não pertencem ao roteiro

### 5.1 Resolução de entidade, antes do prompt de roteiro

Quando há provider e `cfg`, o resolver envia user prompt `Sobre qual sujeito é este pedido de vídeo: {idea.strip()}` (ou inglês `Which subject is this video request about: ...`) e system prompt `_ENTITY_SYSTEM_PROMPT`. Saída JSON solicitada:

```json
{
  "target": "...",
  "aliases": ["..."],
  "discriminants": ["..."],
  "search_queries": ["..."],
  "forbidden": ["..."],
  "ambiguous": true,
  "is_entity": true
}
```

Regras do prompt: canonical target no idioma; aliases 0–4; discriminants 0–6; queries 2–4; forbidden 2–5; `ambiguous` boolean; `is_entity=false` para tema comum. Parser exige dict e target não vazio; lista pode vir como string, remove vazios/duplicatas e corta nos limites (aliases 4, discriminants 6, queries 4, forbidden 5). `bool()` converte flags. Falha usa heurística, sem abortar pesquisa. `source`/`topic_terms` são gerados pelo código e não fazem parte do JSON externo.

### 5.2 Título, depois do roteiro

System prompt PT integral:

```text
Você cria o título de um vídeo a partir do roteiro educativo já pronto, em português do Brasil. Responda SOMENTE com JSON válido, sem markdown nem explicações: {"title": "..."}. Regras (obrigatórias): 1) o título é SEMPRE uma pergunta terminando com '?'; 2) representa a principal curiosidade que o vídeo responde (NUNCA copie a primeira frase do roteiro); 3) curto: no máximo 55 caracteres; 4) soa natural falado em voz alta; 5) desperta curiosidade sem clickbait: nada de exagero, mistério falso ou promessa que o vídeo não cumpre; 6) sem aspas, markdown, emojis, hashtags ou explicações. Princípio editorial: simplificar para tornar acessível, nunca falsificar para viralizar.
```

User prompt exato: `Crie o título para este roteiro:\n\n{script_text}`. Inglês usa `Create the title for this script:\n\n{script_text}` e `TITLE_SYSTEM_PROMPT_EN` no código.

Objeto solicitado: `{"title":"..."}`; `complete_json()` envia `response_format={"type":"json_object"}`, começa em 2000 tokens e sobe uma vez a 4000 se a resposta for truncada. Campo lido: `title`. `_validate_title()` aplica `strip()`, troca newline por espaço, remove backticks/apóstrofos/aspas nas bordas, exige 12–90 caracteres, `?` terminal, rejeita `*#[]{}` e rejeita cópia normalizada da primeira frase. Prompt pede no máximo 55; parser permite até 90. Título segue para metadata e render de abertura; não entra no TTS/legendas.

System prompt EN integral:

```text
You create a video title from an already finished educational script, in American English. Answer ONLY with valid JSON, no markdown or explanations: {"title": "..."}. Mandatory rules: 1) the title is ALWAYS a question ending with '?'; 2) it represents the main curiosity the video answers (NEVER copy the first sentence of the script); 3) short: at most 55 characters; 4) sounds natural when spoken aloud; 5) sparks curiosity without clickbait: no exaggeration, fake mystery or promises the video does not keep; 6) no quotes, markdown, emojis, hashtags or explanations.
```

Essa variante não contém a frase explícita de princípio editorial presente na versão PT.

### 5.3 Cenas, depois do título/roteiro

System prompt de cenas solicita envelope JSON:

```json
{
  "scenes": [
    {
      "index": 1,
      "narration": "...",
      "subject": "...",
      "visual_type": "literal",
      "visual_search_terms": ["..."],
      "visual_entities": ["..."],
      "context": ["..."],
      "forbidden": ["..."],
      "text_role": "",
      "text_language": ""
    }
  ]
}
```

O user prompt PT é `Divida este roteiro em cenas:\n\n{script}`; EN: `Split this script into scenes:\n\n{script}`. O system prompt preenche `{n}`, `{lo}`, `{hi}` para número esperado e faixa `n-1` a `n+1` (mínimo 3). Com gênero, `scene_directive` é anexada ao system prompt de cenas, não ao roteiro.

Regras essenciais: narração literal e ordenada cobrindo roteiro; uma cena por momento semântico; narração PT-BR ou American English; 3–5 termos concretos em inglês, 1–4 palavras cada, com contexto; `visual_type` em `literal`, `mechanism`, `historical_art`, `conceptual`, `typographic`; `subject` 1–4 palavras; `visual_entities` 2–4 frases nominais; `context` 0–3; `forbidden` 2–5; `text_role` limitado aos papéis tipográficos conhecidos ou vazio; `text_language="la"` para texto em latim.

Campos obrigatórios? O prompt pede todos; parser trata muitos como opcionais. `narration` não vazia é necessária para manter uma cena. `index` cai para id sequencial; `visual_type` inválido/ausente é classificado do texto; texto role inválido vira vazio. Lists aceitam string separada por vírgula/ponto e vírgula, e são truncadas (`visual_entities` 4, `context` 3, `forbidden` 5). `visual_search_terms` aceita lista, string CSV/semicolon ou legacy `visual_queries`; máximo 5. Narration concatenada é comparada via `_norm()` (lowercase, whitespace e pontuação removidos), não igualdade byte-a-byte. Se falha, cenas locais.

Esses campos abastecem `Chapter`, timeline e mídia. Termos/entidades/contexto/proibições/visual type têm efeito visual. Cenas fornecem a divisão usada por TTS alignment e captions. Nada disso pode ser entregue junto com narração no arquivo de `Roteiro Pronto` sem ser falado como texto.

## 6. Consumo por etapas e metadados

| Campo/dado | Cenas | Mídia | TTS | Legendas | Render/metadata |
|---|---|---|---|---|---|
| Texto do roteiro | Dividido em `Chapter.narration`, sem reescrever; cenas validadas contra texto. | As queries visuais saem do estágio de cenas; texto pode servir a seleção contextual. | Entrada integral para síntese. | Texto e word timings geram cues; cobertura TTS é verificada. | Conteúdo narrado/renderizado; salvo em `script.txt`, metadata guarda `script_chars` e source. |
| Título | Não entra no prompt de cenas. | Pode influir no contexto/seleção de áudio. | Não narrado. | Não legendado. | `video_title`, `title_source`; usado na abertura/render. |
| `genre` e perfil | Direção visual/pacing; influencia nº cenas, visual strategy, captions. | `scene_directive`, hints e perfil influenciam busca/seleção. | Não é enviado ao TTS. | Caption style do perfil. | metadata `genre`, `genre_profile`, typography e transições. |
| Research sources/evidence | Não enviado ao prompt de cenas diretamente. | Registry inclui fontes de pesquisa e direitos de mídia. | Não enviado ao TTS. | Não entram nas legendas. | `research.json`, `sources.json`, report e `metadata.research` com contagem, status, títulos, grounding, target/rejected. |
| Entity target, aliases, discriminants, forbidden | Só influencia cena via texto já gerado/diretriz. | Pesquisa filtra fontes; entity context evita homônimos no roteiro. | Não há metadata TTS dedicada. | Sem campo dedicado. | Incluído em `research.target_entity`/research artifact. |
| Search keywords/queries | Cenas criam queries por capítulo em etapa separada. | Queries de pesquisa de entidade/gênero, palavras-chave da ideia e `visual_search_terms` servem às buscas em etapas distintas. | Não utilizados. | Não utilizados. | Queries tentadas ficam em `research.json`; output do roteiro não contém keywords. |

Metadata de execução não é solicitada ao modelo de roteiro. Pipeline constrói `title`/`input`, `slug`, `duration_target`, `script_source`, `script_chars`, `scenes_source`, `chapters`, `media`, `warnings`, resolução, dimensões, tempos, gênero, título, TTS, subtitles, render, research e paths de artifacts. Metrics contam providers/modelos/chamadas/tokens retornados quando disponíveis; não vão no prompt.

## 7. Compatibilidade com `Roteiro Pronto`

`read_script_file()` remove BOM e whitespace externo; preserva o restante integralmente. `run_script_pipeline()` usa todo conteúdo como `script_text`, `script_source="provided"`, e gera etapas a partir disso. Não faz parse JSON, front matter, YAML, títulos embutidos, keywords, fontes fornecidas ou cenas pré-estruturadas. Sem `--title`, usa primeira linha como title; TUI não apresenta campo de título, enquanto CLI `from-script` tem `--title`. O pipeline refaz pesquisa com ideia/título e divide cenas novamente.

Portanto, para compatibilidade total no modo atual, salve e cole **somente narração em texto puro**. Dados de título podem ser passados à parte apenas pela flag CLI. Estrutura de cena/source/entity não pode ser preservada por essa entrada. Isso é incompatibilidade documentada; não foi corrigida.

## 8. Template copiável

Substitua todos os placeholders. `DIRETRIZ_GENERO` deve ser o bloco atual de `editorial.script_directive()` para chave selecionada; use string vazia sem gênero. `CONTEXTO_ENTIDADE` e `PACK_FONTES` devem usar exatamente os blocos acima, ou ficar vazios se não se aplicarem. Copie **somente a narração textual devolvida** para arquivo do modo `Roteiro Pronto`; não copie cabeçalhos/metadados JSON.

```text
SYSTEM:
Você escreve roteiros curtos e envolventes de vídeo educativo em português do Brasil. O roteiro será lido em voz alta, {CLAUSULA_DURACAO_EXATA}. Regras de narrativa (obrigatórias): 1) comece com uma pergunta, afirmação intrigante ou problema; 2) toda pergunta criada deve ser respondida em algum momento; 3) crie novas perguntas ao longo do roteiro para manter a curiosidade; 4) cada parte leva naturalmente à próxima, com progressão — não entregue tudo de uma vez; 5) priorize o mais interessante e surpreendente; corte o que não ajuda a história; seja conciso; 6) termine respondendo à ideia principal apresentada no início; 7) escreva como quem conta algo interessante a um amigo, não como quem lê um artigo: frases faladas e curtas, com ritmo; perguntas retóricas, comparações simples e pequenas surpresas são bem-vindas; um toque de personalidade, sem gíria e sem forçar humor; 8) proibido introduções genéricas ('Olá pessoal, hoje vamos falar sobre...', 'Você sabia que' e equivalentes); 9) GROUNDING OBRIGATÓRIO: toda afirmação factual (datas, nomes, números, definições, eventos, etimologias) deve vir das FONTES FORNECIDAS junto ao pedido; é PROIBIDO afirmar qualquer fato ausente das fontes; se algo for incerto ou não estiver nas fontes, diga a incerteza com honestidade ou omita — nunca preencha com invenção; 10) sem fontes falsas nem estudos inexistentes; nunca invente fatos, datas, nomes ou citações para ficar interessante; 11) proibido tom de documentário institucional e conclusões artificiais ('diante disso, podemos concluir', 'é importante ressaltar', 'vale destacar', moral da história ou resumo acadêmico); feche com a resposta ou uma observação que aproxime o assunto do espectador. 12) explique conceitos complexos em palavras simples: se mencionar algo técnico, explique na hora com analogia ou definição direta (ex.: 'se o ângulo for rasante o suficiente, ou seja, se o ângulo for bem próximo do chão...'); nunca use jargão sem explicar. 13) SEMPRE encerre assim: depois de responder a ideia principal, faça UMA pergunta aberta relacionada ao tema mas NÃO respondida no vídeo (gancho para comentários — ex.: 'mas será que se ele tivesse ido mais preparado para o frio, teria ganhado?'), e em seguida uma chamada curta para like ('deixe seu like e até o próximo vídeo'). FORMATO DE SAÍDA (obrigatório): responda SOMENTE com o texto da narração. PROIBIDO: títulos, 'Cena 1', 'Narrador:', rubricas entre colchetes, markdown, listas, aspas de diálogo, emojis, preâmbulos como 'Aqui está' ou qualquer explicação sobre o roteiro. Se precisar raciocinar, faça-o apenas no raciocínio interno, nunca no texto final. Princípio editorial: simplificar para tornar acessível, nunca falsificar para viralizar. O objetivo é o espectador continuar assistindo porque sempre há uma pergunta sendo respondida e outra surgindo.

{DIRETRIZ_GENERO_EXATA}

USER:
Escreva o roteiro de narração para a ideia: {IDEIA_EXATA}

{CONTEXTO_ENTIDADE_EXATO}

{PACK_FONTES_EXATO}

FORMATO DE SAÍDA:
Somente texto puro da narração. Sem JSON, título, keywords, cenas, fontes ou explicações. Siga o limite: {LIMITE_CARACTERES}; duração: {DURACAO_OU_AUTO}.
```

Para inglês, substitua o system pelo texto integral da seção 3.2, idioma de diretriz/contextos/fontes pelo equivalente inglês e user pelo template `Write the narration script for this idea: {IDEIA_EXATA}`. Isso replica o contrato textual, não promete que uma IA externa seguirá instruções ou replique validações internas.

## 9. Pontos fortes, gaps e riscos

### Pontos fortes

- Instrução editorial explícita de grounding, narração oral, progressão e proibição de clickbait/fabricação.
- Fontes filtradas por pertinência e contexto de entidade chegam ao mesmo user prompt.
- Limite técnico protege geração; uma escalada de tokens existe somente para truncamento.
- Texto passa por sanitizer, checagem mínima de comprimento, grounding numérico, geração separada de título e gate literal de cenas.
- Falha de cenas preserva texto original com divisão local em vez de reescrever roteiro.

### Gaps vs PRD

Não há PRD no repositório para comparar seção por seção. Gaps observáveis no contrato atual:

| Severidade | Gap | Evidência |
|---|---|---|
| Alta | Modo Roteiro Pronto aceita texto, não estrutura de geração automática. | `visual.read_script_file()` retorna string única; `run_script_pipeline()` preenche script/title, depois pesquisa e cenas novamente. |
| Média | Roteiro é texto puro e não transporta title, keywords ou scene schema. | System prompt proíbe título/cena/lista; prompt de cenas ocorre depois. |
| Média | Prompt pede cumprimento editorial, mas sanitizer não valida essas regras nem verifica todas alegações factuais; grounding automatizado foca fatos numéricos. | `_sanitize()` e `verify_grounding()`. |
| Média | Diretriz `history` corrompe texto de `must_distinguish` por tratar string como sequência de caracteres. | `editorial.HISTORY.research.must_distinguish` e `script_directive()` usam `join`. |
| Baixa | Prompt de título pede ≤55 caracteres, validação permite até 90. | `TITLE_SYSTEM_PROMPT`, `TITLE_MAX_CHARS`. |

### Riscos técnicos específicos

- Instruções longas e packs de fonte ocupam contexto; pack tem limite de 2500 caracteres, além de system/user prompts e contextos.
- Modelo externo pode ignorar instruções; sanitize não prova aderência editorial. O modo manual não executa sanitizer do output externo.
- Limite de 100 caracteres é uma barreira simples, não avaliação de qualidade.
- Comparação de narrativa de cenas usa normalização que remove pontuação e ignora maiúsculas, portanto não comprova identidade byte a byte.
- Gênero afeta bastante o roteiro e outras etapas, mas o modo Roteiro Pronto da TUI não oferece escolha de gênero nesse fluxo.

### O que NÃO mexer nesta tarefa

- Nenhum código, prompt, saída/entrada, validador ou comportamento do pipeline foi alterado.
- Não converter resposta para JSON: contradiz o formato atual de narração e o parser do modo Roteiro Pronto.
- Não afirmar paridade estruturada entre roteiro automático e Roteiro Pronto.

## 10. Limitações

Esta análise reflete o código inspecionado em 2026-10-01. Não houve chamada a provider, geração de exemplo, modificação de código nem execução do pipeline. Um modelo externo não pode ser garantido como compatível apenas por receber este prompt; o template replica instruções e placeholders disponíveis, mas não inclui verificações internas do Curio.
