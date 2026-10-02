# Análise — Mídia fora de tema em Marco Aurélio e Revolução Francesa

- **Data:** 2026-10-02 19:03 (UTC)
- **Tipo:** analise
- **Escopo:** investigar métricas 15:42/15:46 e identificar por que cenas locais aceitaram homônimos e imagens alheias
- **Commit(s):** `9aad638`, `07f161c`
- **Origem:** relato do usuário; continuação de `20261002-185303_relatorio_anchor-topico-visual.md`

## 1. Veredito

Os dois vídeos foram divididos localmente (`scenes_source=local`). O divisor
gerou queries por frase, sem propagar nome/tema geral para cada cena. O
scoring aceitava uma palavra isolada do assunto local. Assim, `empire`
aceitou Mughal Empire, `aurelio` aceitou Fábio Aurélio, e `mass` aceitou
ônibus com “mass station”.

Os dois logs também mostram causa anterior: Groq devolveu cenas que não
reproduziam narração. Marco retornou 7 cenas, fallback local usou 6;
França retornou 9, fallback local usou 8. Fallback local perdeu a
estrutura visual da resposta LLM e gerou queries como `aurelio`, `dog`
e `sun`.

Revolução Francesa teve ainda erro de substring: detector buscava `sol`
sem fronteira e achava essa sequência dentro de `absoluto`, gerando
`sun nation`; bandeiras argentinas continham os termos e venceram score.

## 2. Evidência — Marco Aurélio

Fonte: `metrics/20261002-154227_20261002_imperador-marco-aurelio-seus-fe.json`.

- Duração: 79,1 s; 6 cenas; fontes de cena locais; mídia consumiu 33,55 s.
- 13 assets únicos incluem 2 cartões sintéticos e 11 fotos. Seleção usou 11;
  48 candidatos caíram por score 0; 24 passaram do threshold. Volume alto
  não significou pertinência.
- Cenas/seleções problemáticas: `empire` selecionou retrato de Akbar,
  imperador Mughal; `Armênia / war` selecionou paisagens/fotos modernas de
  guerra na Armênia; `Aurélio / greek` selecionou jogador Fábio Aurélio;
  consulta `rome` trouxe Coliseu/Roma, contexto aceitável. Cenas Domícia e
  Lúcio usaram cartões porque não havia retratos de época utilizáveis.
- A resolução do alvo trouxe “Imperador Marco Aurélio”, mas aliases e
  identidade não chegaram às queries locais. Assets receberam score por
  tokens `empire`, `Armenia`, `aurelio`, `rome` sem exigir Marco Aurélio.

## 3. Evidência — Revolução Francesa

Fonte: `metrics/20261002-154644_20261002_revolucao-francesa-sua-causa-su.json`.

- Duração: 70,6 s; 8 cenas locais; mídia consumiu 54,43 s.
- 20 assets únicos, 78 candidatos rejeitados por score; 6 usos genéricos.
- Cenas saíram com `ultima`, `dog`, `sun`, `Europa`, `auge`, `government`,
  `compartilhe`; resultados incluíram carro “ultima”, placa de cachorro no
  Cairo, templo no Japão, escola governamental na Coreia e arquivo
  `Compartilhe.jpg`.
- Execução anterior (`20261002-103910`) confirma bandeiras Argentina nas
  queries `sun nation`. Causa: substring `sol` de `absoluto` acionou boost
  espacial; nenhum global topic query restringiu seleção.

## 4. Causa técnica específica

1. Fallback local traduz trechos sem conhecer contexto do vídeo. Cada cena
   vira sujeito de palavras soltas, não assunto histórico completo.
2. Score local trata uma correspondência lexical isolada como prova
   suficiente. Título com `mass`, `empire`, `aurelio` ou `nation` passa,
   embora o recurso visual trate de outro referente.
3. Queries genéricas de history (`church interior`) também podiam entrar
   sem conexão ao vídeo.
4. Marcadores espaciais usavam substring para palavra curta `sol`.

## 5. Riscos

Uma âncora lexical pode rejeitar imagem historicamente correta cujo título
não contém o nome da revolução/pessoa. Para cenas locais, isso é preferível
a exibir referente errado; fallback gera cartão quando não há candidato
com título comprovável. Visão computacional segue fora do escopo.
