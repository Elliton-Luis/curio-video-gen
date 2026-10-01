# Análise — Scores baixos na execução de Tomás de Aquino

- **Data:** 2026-10-01 04:52 (-03:00)
- **Tipo:** analise
- **Escopo:** explicar componentes dos scores reais, origem do threshold e contrato entre consultas, cenas e metadados de providers.
- **Origem:** diagnóstico da execução `fale-sobre-a-historia-e-importancia-de-s`.

## 1. Veredito

A execução perdeu o vocabulário visual ao cair em cenas locais. O buscador criou consultas locais, mas não as colocou em `Chapter.visual_queries`; o scorer comparou títulos, predominantemente em inglês, com todas as palavras da narração em português. Isso dilui acertos corretos e produz zeros por incompatibilidade de idioma.

O problema combina dados insuficientes da cena, qualidade de consultas e limitação lexical; há uma incompatibilidade de integração demonstrada, não erro aritmético. Rejeitar homônimos e imagens fora do assunto continua correto. Não há faixa de threshold capaz de separar os candidatos adequados dos inadequados desta amostra.

## 2. Evidência e alcance

Consultei primeiro `metrics/20261001-040048_fale-sobre-a-historia-e-importancia-de-s.json`, depois os artefatos do mesmo projeto em `output/fale-sobre-a-historia-e-importancia-de-s/`:

- `metadata.json`;
- `script/chapters.json`;
- `media/media.json`.

Métricas confirmam 169 normalizados, 138 únicos, 132 elegíveis, seis hard rejects, 132 score rejects, zero acima de 34, zero downloads, 11 sintéticos. Dos score rejects, 99 aparecem como nota 0, três como 2, 15 como 3, seis como 6, dois como 8 e sete como 12.

`scenes_source=local`, gênero `people`. As 11 cenas têm `subject=""`, `visual_queries=[]`, `global_visual_queries=[]`, `visual_entities=[]`, `context=[]` e `forbidden=[]`. Não são apenas campos ausentes de algumas cenas: falta vocabulário estruturado em todas.

`media.json` guarda até oito rejeitados por cena. Há 88 rejeições preservadas: seis hard rejects e **82 rejeições por score reproduzíveis**. Reexecutei `scoring.base_score()` offline com títulos reais e `Chapter.from_dict()` real. Os 82 valores recalculados reproduzem integralmente os motivos arredondados registrados. Os outros 50 score rejects só têm histograma agregado; não inventei seus títulos nem decomposição.

Não chamei APIs, não baixei imagens, não gerei vídeo e não modifiquei código/configuração. A adequação visual discutida abaixo é inferida do título/tema, não confirmada por inspeção de pixels.

## 3. Algoritmo exato

### 3.1 Threshold e origem

- `src/curio/stages/scoring.py:31`: `DEFAULT_THRESHOLD=34.0`.
- `scoring.threshold():162–169`: override por `CURIO_MEDIA_SCORE_MIN`, limitado a 0–100; inválido usa default. Zero desliga o corte.
- `visual._search_scene_with_shortcircuit()` chama `scoring.below_threshold()` antes de download; score igual ao mínimo passa.
- Motivos históricos desta execução registram `mínimo 34`, evidência do valor efetivo. Ambiente atual não prova configuração passada.
- Histórico `a290177` (2026-09-30 09:09) introduziu 34 na proteção contra imagens irrelevantes. Commit descreve caso papel térmico/usina e testes corretos/incorretos; não apresenta derivação estatística de 34.
- `0b0dad6` (2026-09-30 09:34) manteve 34 e mudou fórmula: núcleo até 75, apoio até 25. Exemplo documentado: usina com uma de três palavras do assunto fica em 25 e é bloqueada; arte correta de São Francisco subiu de 33 para 95 com núcleo específico.
- Comentários/config exemplo documentam corte mínimo; não encontrei conjunto rotulado, curva precisão/recall ou calibração representativa de biografias com cenas locais. O valor é heurística editorial com regressões pontuais, não limite calibrado para qualquer distribuição de entrada.

### 3.2 Tokenização e campos

`_fold()` aplica NFKD, remove acentos e lowercase. `_tokens()` separa por qualquer caractere fora de `[0-9a-z]`, mantém tokens com pelo menos três caracteres. Não traduz, não aplica stemming, sinônimos ou aliases e **não remove stopwords** de três ou mais letras. `File:` e `.jpg` não quebram a primeira palavra; a correção histórica de pontuação está presente.

O núcleo vem de apenas um caminho:

1. Tokens de `subject`, peso 3 por token único;
2. se vazio, união dos tokens de `visual_queries`, peso 2;
3. se ambos vazios, todos os tokens únicos da narração, peso 1.

Apoio: `visual_entities` peso 2, `context` peso 1. Repetições não aumentam peso: guarda o maior peso por token. Os tokens de cada título viram um conjunto; repetir tags não aumenta score.

```text
H = soma dos pesos dos tokens do núcleo presentes no título
W = soma dos pesos de todos os tokens do núcleo
C = H / W
núcleo = 75 * C
apoio = 0, se C < 0.5
apoio = min(25, 5 * soma dos pesos do apoio presentes no título), se C >= 0.5
TOTAL = round(min(100, núcleo + apoio), 2)
```

Não há penalidades numéricas: `forbidden`, dimensões, licença e tamanho são gates eliminatórios anteriores, não parcelas negativas. Score baixo não é penalidade; é baixa cobertura.

Máximo teórico: **100** com cobertura completa e pelo menos 25 de apoio. Sem apoio, máximo **75**, inclusive no fallback local. Não há impossibilidade matemática de atingir 34 com título apenas: exige cerca de 45,33% do peso do núcleo. Com núcleo curto de duas palavras, um acerto vale 37,5; três palavras, dois acertos valem 50. Na execução, a narração inflou o denominador para 6–34 tokens.

CLIP/vision não pontuam no caminho atual: `rank_candidates():239–259` chama apenas `base_score()`, mesmo com interfaces/status opcionais. Não há componente semântico oculto, bônus por provider ou bônus pelo score da API.

### 3.3 Denominador real das cenas locais

Como todos os pesos do núcleo são 1 e apoio está vazio, cada acerto vale `75 / N`:

| Cena | Tokens únicos N | Acertos mínimos para 34 | Um acerto |
|---|---:|---:|---:|
| 1 | 34 | 16 | 2,21 |
| 2 | 26 | 12 | 2,88 |
| 3 | 9 | 5 | 8,33 |
| 4 | 28 | 13 | 2,68 |
| 5 | 31 | 15 | 2,42 |
| 6 | 13 | 6 | 5,77 |
| 7 | 13 | 6 | 5,77 |
| 8 | 28 | 13 | 2,68 |
| 9 | 16 | 8 | 4,69 |
| 10 | 24 | 11 | 3,12 |
| 11 | 6 | 3 | 12,50 |

Núcleo da cena 3: `como, ele, fez, isso, vez, rejeitar, aristoteles, tomas, adaptou`. Um retrato de Aristóteles precisaria também descrever verbos/pronomes para atingir cinco acertos. O score não está errado ao dividir 1 por 9; o vocabulário fornecido é inadequado para a comparação desejada.

## 4. Trace real compacto

Os motivos persistidos arredondam para zero casas decimais. `12.50` aparece como `12` por formatação `.0f`; `5.77` aparece como `6`. São os mesmos scores, não divergência de cálculo.

### A. Score zero apesar de candidato relacionado ao assunto

```text
Cena/query: 3 / Aristóteles
Narração: Como ele fez isso? Em vez de rejeitar Aristóteles, Tomás o adaptou.
Candidato: File:Aristotle Altemps Inv8575.jpg
Provider: wikimedia
Título disponível: File:Aristotle Altemps Inv8575.jpg
Descrição/tags separadas: não preservadas no contrato MediaAsset nem nesta rejeição
Núcleo: 0 acertos / 9 tokens; aristotle != aristoteles
Núcleo: +0.00
Apoio: +0.00 (lista vazia)
Penalidades: nenhuma
TOTAL: 0.00; mínimo: 34
Resultado: rejeitado
```

Pelo título, um registro de Aristóteles é plausível para a cena que menciona o filósofo. Não confirmei imagem nem pertinência composicional. Outro resultado real, `File:"The School of Athens" by Raffaello Sanzio da Urbino.jpg`, recebe 0 pela mesma ausência de correspondência lexical, apesar da associação temática conhecida. O scorer não faz essa associação.

### B. Score baixo com nome em português

```text
Cena/query: 3 / Aristóteles
Candidato: File:Aristóteles Ilustração.png
Provider: wikimedia
Título disponível: File:Aristóteles Ilustração.png
Descrição/tags separadas: não preservadas
Matched: aristoteles
Núcleo: 75 * (1/9) = +8.33
Apoio: +0.00 (lista vazia; cobertura 11.11% também não habilita bônus)
Penalidades: nenhuma
TOTAL: 8.33; mínimo: 34
Resultado: rejeitado
```

Controle negativo real na mesma cena: `File:Aristoteles crater 4103 h3.jpg` também marca `aristoteles` e recebe **8,33**. Um threshold menor não distingue ilustração do filósofo de cratera lunar.

### C. Lugar diretamente citado, reprovado por diluição

```text
Cena/query: 7 / Fossanova
Narração: Em 1274, aos 49 anos, Tomás morreu em Fossanova. Apesar de sua vida curta, sua influência se espalhou rapidamente.
Candidato: File:Fossanova Abbey fc01.jpg
Provider: wikimedia
Título disponível: File:Fossanova Abbey fc01.jpg
Descrição/tags separadas: não preservadas
Matched: fossanova
Núcleo: 75 * (1/13) = +5.77
Apoio: +0.00
Penalidades: nenhuma
TOTAL: 5.77; mínimo: 34
Resultado: rejeitado
```

Abadia de Fossanova é semanticamente plausível como local da trajetória narrada; pixels não foram examinados. Controle negativo: `File:Mairie d'Anos.jpg` recebe os mesmos **5,77** porque coincide com `anos`, palavra comum da narração. Comparação ignora intenção da query usada naquela entrada.

### D. Um dos maiores scores não indica melhor imagem

```text
Cena/query: 11 / like
Narração: Deixe seu like e até o próximo vídeo.
Candidato: File:Toll-Like Receptors (TLRs).png
Provider: wikimedia
Título disponível: File:Toll-Like Receptors (TLRs).png
Descrição/tags separadas: não preservadas
Matched: like
Núcleo: 75 * (1/6) = +12.50
Apoio: +0.00
Penalidades: nenhuma
TOTAL: 12.50; mínimo: 34
Resultado: rejeitado
```

Receptores biológicos não ilustram CTA de like. O mesmo máximo observado aparece em `carp-like` nas tags de carpa do Pixabay. É um dos melhores candidatos **por score**, não por adequação. A métrica agregada confirma sete ocorrências de nota arredondada 12 e nenhuma maior.

### E. Query ambígua recupera referente errado

```text
Cena/query: 1 / Aquino
Candidato: File:Aquino (FR) - chiesa di Santa Maria della Libera.jpg
Provider: wikimedia
Matched: aquino
Núcleo: 75 * (1/34) = +2.21
Apoio: +0.00
Penalidades: nenhuma
TOTAL: 2.21; mínimo: 34
Resultado: rejeitado
```

A consulta também retorna monumentos de **Melchora Aquino** pelo Pixabay, com score 2,21. Sobrenome isolado não preserva “Tomás de Aquino”. Cena 2 usa `Agostinho` e recupera Agostinho Neto; cena 4 usa `doctor`/`Angelicus` e recupera médicos/espécies; cena 9 usa `school` para “escola de pensamento” e recupera salas de aula. Há falha real de queries, além da diluição de pontuação.

## 5. Dados realmente entregues pelos providers

O scorer só consome `asset['title']`. Não espera campos separados de tags, descrição ou contexto de imagem. `MediaAsset` não tem esses campos. Alguns adapters embutem descrição/tags no campo chamado título:

| Provider | Fonte do `title` entregue ao scorer | Limitação/score alcançável |
|---|---|---|
| Wikimedia | `page.title`, nome do arquivo | Nome curto, idioma variável; metadados de autor/licença não dão pontos. Pode chegar a 75/100 com assunto apropriado no mesmo idioma. Na amostra, retrato com `Aristotle` recebeu 0 e Fossanova 5,77. |
| Pixabay | `item.tags` | Tags são efetivamente usadas, apesar do comentário “só título, não tags”. Repetições não aumentam score. Sem tradução, `aristotle` não pontua contra `aristoteles`. |
| Unsplash | `alt_description`, depois `description`, depois `slug` | Uma descrição pode existir como título, mas sem nome/entidade: `a stone building with a tower` recebe 0 contra narração PT. Não há campo separado que habilite bônus. |
| NASA | título mais até cinco `keywords` anexadas | Tags podem pontuar indiretamente. Não preserva descrição geral nesse campo. A execução tem 30 resultados NASA; rejeições individuais NASA não sobreviveram no recorte de oito por cena. Sem evidência para estimar média NASA. |
| Pexels | `photo.alt` | Sem alt útil, não há evidência lexical. Não participou dos contadores desta execução; alcance teórico igual, média empírica indisponível. |
| Openverse | `item.title` | Nome curto/idioma variável, sem tags/descrição adicional. Não participou dos contadores desta execução; média empírica indisponível. |

Qualquer provider pode atingir o máximo com título que cubra núcleo e apoio. Não se pode declarar score típico universal por provider a partir de 82 rejeições recortadas. Nesta execução o teto efetivo era 75 por ausência de apoio em todas as cenas; nenhum provider poderia ganhar bônus, porque **a cena** não forneceu apoio, não porque o provider deixou de fornecer metadados adicionais.

A descrição do algoritmo tem duas imprecisões documentais: `base_score()` menciona cobertura 0–100, embora núcleo seja 0–75; e diz não usar tags, embora Pixabay/NASA as incorporem em `title`. Nenhuma dessas frases muda a fórmula executada.

## 6. Contrato quebrado entre busca e scoring

Trajeto demonstrado:

1. Roteiro PT gerado por `groq:openai/gpt-oss-20b`;
2. cenas caem para `_local_chapters()`, que preserva texto, classifica tipo, mas deixa assunto/queries/apoio vazios (`scenes.py:418–441`);
3. `_waterfall_queries()` gera termos locais via `local_queries()` e adiciona genéricos (`visual.py`, funções com esses nomes);
4. consultas ficam em variável local `queries`; candidato guarda query, mas a cena não recebe esse vocabulário;
5. `rank_candidates(candidates, ch)` passa apenas asset e `ch` para `base_score()`, que **não lê `entry['query']`**;
6. scorer cai em narração PT, sem tradução nem desambiguação.

Portanto não existe identidade obrigatória entre a query realmente executada e o vocabulário usado para julgar seus resultados. Tradução parcial do gerador agrava a quebra: `escola` vira `school`, `campo` vira `field`, `Deus` vira `god`; título inglês pode corresponder à query, mas não à palavra portuguesa do núcleo. `query=school`, `title=School Environment` resultou em 0.

Gênero `people` influencia prompt/pesquisa/pacing, mas `base_score()` não recebe gênero. Proibições derivadas de tipo podem barrar hard filters, mas não explicam os 132 elegíveis. Entidade-alvo da pesquisa não é passada diretamente ao scorer. Não há diferença de peso por provider/gênero nem penalidade oculta por `historical_art`.

## 7. Classificação e recomendação, sem implementação

- **Bug/incompatibilidade de integração:** vocabulário produzido para buscas do fallback local não chega ao scoring; scorer interpreta narração inteira como assunto. Correção recomendada: gerar um contexto visual explícito e compartilhado na fronteira de cenas locais, preservando entidade/aliases, idioma, assunto por cena e CTA; validar resultado antes de mudar threshold. Apenas copiar query para assunto não basta: `Aristóteles` e cratera lunar continuam homônimos.
- **Qualidade das queries:** fragmentos e palavras genéricas recuperam lugares, pessoas e conceitos errados. Comprovado por Aquino/Melchora, Agostinho Neto, `doctor`, `school` e CTA.
- **Dados insuficientes para scoring:** todas as cenas perderam campos estruturados; alguns títulos de fotos não descrevem entidade mesmo quando busca relaciona resultado.
- **Limitação dos providers/algoritmo lexical:** títulos multilíngues, aliases e relações temáticas não viram identidade lexical. Não é bug na remoção de acentos; normalização funciona, mas não traduz.
- **Comportamento esperado:** hard filters e threshold recusam falsos positivos; download não começa sem score suficiente.
- **Configuração/calibração:** 34 não foi calibrado para narração longa; isso não prova que reduzir 34 seja solução segura. Não há erro aritmético localizado no cálculo reproduzido.

### Faixa plausível e por que não adotá-la

Para admitir Fossanova com dados atuais seria necessário mínimo **≤5,77**; para ilustração PT de Aristóteles, **≤8,33**. A faixa de investigação **5,77–8,33** só representa esses exemplos, não recomendação de produção. O máximo observado **12,50** pertence ao CTA e a candidatos fora do assunto. Diminuir para 5,77 aceita prefeitura de Anos e cratera lunar junto com imagens plausíveis. Para admitir título inglês de Aristóteles seria necessário **0**, também admitindo todos os zeros; há 99 deles.

Não existe faixa segura demonstrada pelo conjunto atual. Primeiro corrigir vocabulário e identidade; depois calibrar em conjunto rotulado com positivos e negativos reais por gênero/provider. Threshold fica **34** nesta tarefa.

## 8. Observabilidade mínima recomendada

Métricas mostram histograma arredondado e funil, mas não mostram `H`, `W`, idioma, core source nem bônus. `score_detail` registra score final como `base`, matched e só seis missing; não separa parcelas. Rejeições persistidas descartam esse detalhe e mantêm apenas título/query/provider/motivo, no máximo oito por cena. `nota_media=null` e `nota_baixa=0` significam nenhum asset usado pontuado, não que candidatos tiveram média zero ou nenhuma nota baixa.

Proposta futura, sem implementação nesta tarefa:

- um resumo por cena: `core_source` (`subject`, `visual_queries`, `narration`), número/peso do núcleo, quantidade de apoio, threshold, min/max e número de zeros;
- até dois exemplos por cena: melhor rejeitado por score e primeiro selecionado; título curto, provider, query curta, score exato, peso acertado/total, cobertura, bônus e poucos tokens matched/missing;
- guardar esses exemplos junto ao evento/resumo já existente, sem prompts, payloads, secrets, URLs ou coleção completa de candidatos.

Isso explica perda em vez de multiplicar logs e usa os valores calculados pelo próprio scorer, evitando dupla contagem.

## 9. Reprodução offline

```bash
PYTHONPATH=src python - <<'PY'
import json
from collections import Counter
from pathlib import Path
from curio.stages.scenes import Chapter
from curio.stages.scoring import base_score

root = Path('output/fale-sobre-a-historia-e-importancia-de-s')
chapters = json.loads((root / 'script/chapters.json').read_text())
media = json.loads((root / 'media/media.json').read_text())
counts = Counter()
checked = 0
for raw, scene in zip(chapters, media):
    chapter = Chapter.from_dict(raw)
    for rejected in scene.get('rejected', []):
        if not rejected['reason'].startswith('nota '):
            continue
        info = base_score({'title': rejected['title']}, chapter)
        expected = f"nota {info['score']:.0f} abaixo do mínimo 34"
        assert rejected['reason'] == expected
        counts[info['score']] += 1
        checked += 1
print(checked, dict(counts))
PY
```

Resultado: **82/82 motivos reproduzidos**. Histograma da amostra: 50 zeros, três 2,21; oito 2,68; três 2,88; três 3,12; seis 5,77; dois 8,33; sete 12,50. Não extrapolar esse recorte para distribuição por provider dos 132.

## 10. Pontos fortes, gaps e riscos

Pontos fortes: cálculo determinístico para títulos/cenas fixos; gate evita usar imagem inadequada; histograma preservado permite reconstrução parcial; arquivo original de cenas mantém narração exata usada pelo scorer.

Não há PRD disponível para aferir gaps normativos. Gaps técnicos: ausência de contexto visual no fallback local (alto); desalinhamento de idiomas/identidade (alto); ausência de parcelas nas rejeições persistidas (médio); origem de 34 sem calibração ampla (médio).

Riscos: reduzir corte promove homônimos; traduzir nomes sem aliases pode confundir referentes; rotular automaticamente resultado “adequado” pelo título não prova pixels; recorte de rejeitados favorece ordem de ranking e não representa todos os providers.

### O que não alterar nesta tarefa

Não alterar código, threshold, pesos, filtros, queries, providers ou comportamento editorial. Correções e instrumentação acima são recomendações para implementação posterior. Causa demonstrada por artefatos reais e replay offline; investigação encerrada sem chamadas externas.
