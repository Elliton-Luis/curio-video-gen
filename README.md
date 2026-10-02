# curio — Máquina de Conteúdo Educativo em Vídeo

> Conteúdo curto que respeita a inteligência do espectador.

Ferramenta local (Linux, CLI + TUI) que transforma **uma ideia textual** em um
**vídeo vertical de ~45 s** com roteiro, narração em PT-BR, legendas queimadas
e MP4 final — tudo com **custo próximo de zero** (TTS local + FFmpeg).

Princípio editorial: *o vídeo pode simplificar uma ideia para torná-la
acessível, mas não deve falsificá-la para torná-la mais viral.*

## Status

Em evolução (v0.2): dois fluxos de produção.

```text
Fluxo A (narração IA):
IDEIA → ROTEIRO → CENAS → MÍDIA → NARRAÇÃO → LEGENDAS → VÍDEO FINAL

Fluxo B (narração humana):
IDEIA → ROTEIRO → CENAS → MÍDIA → SILENCIOSO + TELEPROMPTER
→ (você grava) → FINALIZE → VÍDEO FINAL
```

## Requisitos

- Linux, Python 3.11+
- `ffmpeg` + `ffprobe` (renderização)
- `espeak-ng` com voz `pt-br` (fallback local offline)
- Internet (só para a voz neural padrão; sem rede, usa espeak-ng)
- Opcional: GPU Intel com VA-API (ex.: Arc B580) — sem ela, usa CPU (libx264)

## Instalação

```bash
./scripts/install.sh
video-gen doctor   # ou: ./scripts/run.sh doctor
```

O `install.sh` tenta `pip install -e .` para criar os comandos `video-gen` e
`curio-tui`. Sem rede/sem pip, use `./scripts/run.sh` (roda direto do código).

## Uso

```bash
# Gerar um vídeo (narração IA, com mídia dinâmica)
video-gen generate "De onde veio a palavra salário?"

# Duração automática (padrão: o conteúdo manda) ou meta à sua escolha
video-gen generate --duration 30 "O que é um satélite?"
# auto/30/45/60/90/120/180 ou segundos (5..600) — meta, nunca corta nem
# acelera a fala; sem --duration, o vídeo tem o tamanho do conteúdo

# Gerar base para narrar você mesmo (silencioso + teleprompter)
video-gen generate --narration human "De onde veio a palavra salário?"
# abre a pasta do teleprompter + Audacity sozinho (desliga com --no-open
# ou CURIO_AUTO_OPEN=0; binários em config.toml [teleprompter])
# ...grave sua voz, depois:
video-gen finalize de-onde-veio-a-palavra-salario --audio minha-voz.wav

# Roteiro já pronto (narração preservada; Curio monta o restante do vídeo)
video-gen from-script meu-roteiro.txt --narration ai
# 1-5 fotos por cena com sobreposição estilo álbum (--max-images 3);
# SFX discretos em ~1/3 das inserções (desliga com CURIO_VISUAL_SFX=0)

# Refazer tudo do zero (padrão: reaproveita artefatos existentes)
video-gen generate --force "O mito dos capacetes com chifres dos vikings"

# Interface visual em terminal (abre a TUI)
video-gen tui
# Atalho: ./scripts/run.sh sem argumentos também abre a TUI
# Em "Roteiro pronto", cole o texto em várias linhas e termine com
# <<FIM_DO_ROTEIRO>> em uma linha isolada.

# Listar vídeos e ver metadados
video-gen list
video-gen info --slug salario

# Verificar um vídeo contra os critérios do MVP (PRD §19)
video-gen verify --slug salario

# Métricas de cada vídeo (tempo, consumo, tamanhos) em metrics/
video-gen metrics --slug salario
# sem --slug: gera para todos os projetos (a partir do metadata quando
# a execução é anterior à metrificação)
```

Progresso esperado:

```text
[1/6] Gerando roteiro... OK
[2/6] Interpretando cenas... OK
[3/6] Buscando mídia... OK
[4/6] Gerando narração... OK
[5/6] Sincronizando legendas... OK
[6/6] Montando vídeo... OK

Output: output/salario/render/final.mp4
```

## Gêneros editoriais

A TUI pergunta o gênero **antes** da ideia, com uma lista vertical
(`↑ ↓`, `Enter`, `Esc`) que mostra a descrição e o ritmo do perfil selecionado.
A escolha muda a pesquisa, então pedir o tema primeiro seria escrever contra o
formato errado. O `dry-run` e a folha de contato mostram o gênero escolhido e
os números que ele produziu.

O gênero não é um prompt com outro texto em cima. Ele é um perfil
que age em seis etapas:

| Etapa | O que o perfil decide |
|---|---|
| **pesquisa** | os termos que entram **antes** das keywords genéricas, e o que as fontes precisam distinguir (numa etimologia, origem documentada de hipótese e de etimologia popular) |
| **roteiro** | a estrutura narrativa a seguir e o que não escrever (biografia não é hagiografia; resumo histórico não é cronologia seca) |
| **cenas** | quantas cenas o mesmo roteiro vira, e os segundos de cada uma |
| **visual** | a escada de meio (etimologia põe tipografia antes de foto; ciência põe diagrama antes de foto decorativa) |
| **legendas** | densidade e destaque, que é a segunda coisa que se percebe sem ver o título |
| **metadados** | `genre` e `genre_profile` no `metadata.json` |

### Os seis perfis

| chave | ritmo | legenda | o que o torna ele |
|---|---|---|---|
| `history` | 9,0 s | 5 palavras | quedas de impérios, crimes e desastres como narrativa, nunca como aula |
| `etymology` | 7,5 s | 4 | a palavra hoje, a forma antiga, a transformação; tipografia é parte da composição |
| `mythology` | 12,0 s | 6 | o mito como produto humano do seu tempo, com a tradição de lado |
| `mystery` | 11,0 s | 5 | fato e hipótese mantidos separados; nunca resolve o que as fontes não resolvem |
| `science` | 14,0 s | 6 | tempo para o diagrama ser compreendido; nunca laboratório decorativo |
| `people` | 13,0 s | 6 | primeiro resolve **quem** é a pessoa, depois a trajetória e o legado |

O mesmo roteiro de 298 palavras vira 16 cenas em etimologia, 12 em
história, 11 em mistério, 10 em mitologia e 9 em ciência e pessoas.

### Sem gênero, nada muda

`genre = ""` (o padrão) não é um perfil: é a ausência dele. O teto de
cenas volta a ser 12, o pacing 9,0 s e a legenda 5 palavras — os mesmos
números de antes do recurso, verificados por teste. `history` é o perfil
que reproduz o comportamento antigo **de propósito**, para quem quiser
escolhê-lo explicitamente.

Um projeto gerado antes do recurso não tem `genre` no `metadata.json`, e a
revisão o lê sem reclamar.

Via CLI, use `CURIO_GENRE` ou `genre` no `config.toml`.

## Tipografia por gênero

Trocar a fonte do vídeo inteiro não cria identidade editorial — cria uma
diferença de glifo. O que faz um vídeo de História de Pessoas parecer um
livro em vez de um post é a distinção entre **a voz que narra** e **a voz
que cita**. Por isso a fonte decide por **papel**, e não globalmente.

A cena declara a **função** do texto, nunca a fonte:

```json
{"text": "Ora et labora", "role": "quote", "language": "la"}
```

E o perfil do gênero decide o desenho. Uma cena que escrevesse
`font = "Minion Pro Italic"` quebraria a abstração no instante em que o
gênero muda, e trocar de gênero é justamente o que precisa ser barato.

### Os papéis

`title` · `person` · `subtitle` · `kicker` · `caption` · `quote` ·
`document` · `latin` · `term` · `date` · `location` · `emphasis` · `concept`

O papel mapeia para uma **intenção** (`serif`, `serif_italic`, `sans`,
`mono`, `condensed`), e a intenção resolve para uma família. É essa
separação que permite que dois gêneros usem as mesmas intenções com
fontes diferentes, e que trocar `primary` mova todos os papéis serifados
de uma vez.

Em `people`, `title` e `person` são serifada de leitura, e `quote`,
`document` e `latin` são **itálico serifado** — a Minion Pro Italic é
recurso editorial, nunca a fonte do vídeo. A legenda fica de fora por
decisão: legibilidade vale mais que estilo, e nenhuma configuração
redireciona esse papel.

### As fontes de cada gênero

| gênero | serifada / itálico | sem serifa | mono |
|---|---|---|---|
| `people` | Minion Pro / Minion Pro Italic | Inter | Source Code Pro |
| `history` | Minion Pro / Minion Pro Italic | Inter | Source Code Pro |
| `etymology` | EB Garamond / EB Garamond Italic | Inter | Source Code Pro |
| `mythology` | Adobe Caslon Pro / Adobe Caslon Pro Italic | Inter | Source Code Pro |
| `mystery` | Source Serif Pro / Source Serif Pro Italic | Roboto Condensed | IBM Plex Mono |
| `science` | Noto Serif | Inter | JetBrains Mono |

`etymology` põe o termo em corpo de destaque porque ali a tipografia **é**
o diagrama: as formas históricas da cadeia recebem o tratamento
documental, e a forma atual fica no corpo de título. `mystery` usa mono
para data, lugar e identificador, o que separa fato de testemunho na
tela. `science` não tem ornamento em lugar nenhum.

### Fontes: nunca assumidas, nunca baixadas

A Minion Pro é proprietária e não está em máquina nenhuma por padrão.
O curio **não baixa fonte alguma** — nem a proprietária, nem uma
substituta. Ele pergunta ao fontconfig o que já está instalado e, quando
a pedida não existe, cai numa cadeia genérica da mesma função
(`EB Garamond` → `Noto Serif` → `Liberation Serif` para serifada;
`Noto Sans` → `Liberation Sans` para sem serifa).

Duas armadilhas do fontconfig são tratadas explicitamente:

- ele **substitui em silêncio**. `fc-match "Minion Pro"` responde
  `Noto Sans`. O curio exige que o nome pedido volte na família
  resolvida, senão isso não é fallback, é outra fonte;
- quando a família **não tem itálico**, ele devolve o **regular** e
  reporta sucesso. `fc-match "EB Garamond:italic"` responde `Regular`
  aqui. Aceitar isso colocaria a citação na mesma fonte da narração e a
  distinção inteira sumiria **sem erro e sem log**. O curio confere o
  estilo resolvido e cai para a próxima candidata se não for itálico.

O itálico que vence é o **irmão da família que a voz principal já
resolveu**: título em EB Garamond pede o itálico do EB Garamond, e não
"qualquer serifada". Sem isso a citação sairia numa família parecida com
a do título, o que parece acidente em vez de decisão.

`video-gen doctor` diz, papel a papel, qual família foi pedida e qual
respondeu. "Minion Pro não está instalada" é uma frase que o autor
precisa ler antes de gastar quarenta minutos de render.

A folha de contato e o `dry-run` mostram a mesma linha, com a família que
**respondeu** e, quando foi fallback, a que foi pedida:

```
Tipografia: título: Utopia · citação: Utopia itálico (pediu Minion Pro Italic) · legenda: Archivo Black
```

Os dois leem o que está gravado no `metadata.json`, e não resolvem de
novo: se o gravado e o resolvido divergirem, o vídeo foi montado com
outra fonte, e a revisão é o pior lugar para esconder isso.

### O par, e por que o título e a citação não saem em famílias diferentes

Quando a família pedida não existe — ou existe mas não tem itálico — o
gênero inteiro desce para a primeira da cadeia que tem **os dois rostos**.
A alternativa ingênua resolve as duas vozes de forma independente e
produz um título numa família e a citação em outra: uma old-style e uma
transitional, nenhuma das duas Minion. Duas famílias no mesmo vídeo leem
como dois vídeos colados.

Na cadeia genérica, **Utopia** abre a lista de serifadas, e não por gosto:
foi desenhada por Robert Slimbach, o mesmo da Minion Pro, e vem nos dois
rostos nas distribuições Linux. Uma família que você fixar no
`config.toml` é respeitada mesmo sem itálico, porque isso é escolha e não
preferência — a regra do par existe para consertar os nossos padrões, não
para desobedecer aos seus.

### Onde a tipografia não entra

Duas superfícies ficam de fora, por decisão:

- **legendas queimadas** — a fonte de exibição pesada, como antes. A
  legibilidade vem primeiro, e nenhuma configuração redireciona esse
  papel;
- **teleprompter** — é um arquivo de narração, não de identidade
  editorial. Vai para um monitor onde alguém lê o texto ao vivo.

### Trocar a fonte

No `config.toml`, por gênero e por intenção:

```toml
[typography.people]
primary = "Minion Pro"        # todos os papéis serifados
italic = "Minion Pro Italic"  # citação, documento, latim
fallback = "EB Garamond"      # cabeça da cadeia genérica

[typography.people.roles]
quote = "Cormorant Garamond"  # escape hatch: um papel só
```

Nomes são escritos como se escreve: `italic = "Liberation Serif Italic"`
funciona, porque o sufixo de estilo vira a consulta `família:italic`.
Uma família que não exista **não** apaga a serifada do papel — ela cai
na cadeia do gênero. Também por ambiente, para quem não mantém
config.toml:

```sh
CURIO_TYPOGRAPHY_PEOPLE="primary=Minion Pro;italic=Minion Pro Italic"
```

## Escolha visual: como cada cena é visualizada

O requisito não é que a cena tenha uma **fotografia** — é que ela tenha
**um visual final**. Quando a foto não serve ao conteúdo, trocar de
medium é a resposta certa, e uma imagem genérica "só para preencher" nunca
entra.

Cada cena declara, na etapa de cenas, o que precisa mostrar e como:

| `visual_type` | Quando | Estratégia |
|---|---|---|
| `literal` | dá para fotografar (objeto, lugar, animal) | foto → arte → cartão |
| `mechanism` | a cena explica **como** algo funciona | **diagrama** → cartão |
| `historical_art` | santos, antiquity, religião, mitologia | **arte de domínio público** → foto → cartão |
| `typographic` | a ideia **é uma palavra** (etimologia, termo, data) | **cartão** |
| `conceptual` | abstrato demais para fotografar | cartão → diagrama |

Fluxo da decisão:

```text
cena → o que precisa ser mostrado → visual_type → estratégia
     → busca → filtros eliminatórios → nota → visual final
```

Diagrama e cartão são gerados por código (Pillow, já usado no projeto),
sem rede e sem licença de terceiros. Nenhum deles inventa conteúdo: as
palavras vêm do que a cena declarou.

**Filtros eliminatórios** rejeitam: licença bloqueada ou incompatível com
edição de vídeo, resolução menor que 1080 px no lado curto, arquivo
acima do teto, e títulos com termo decorativo (`wallpaper`, `4k`,
`background`, `mockup`, `template`, `logo`…) ou com um termo que a própria
cena declarou proibido — foi assim que "térmico" parou de puxar usina
termelétrica e "tinta" parou de puxar uva.

**Nota de relevância** (0–100) = cobertura do assunto (até 75) + bônus
pelas entidades pedidas na cena (até 25). Lê o **título** da imagem, nunca
as tags do provedor: tag é palpite de quem doou o acervo, e é
justamente ela que traz "wallpaper, 4k" para uma cena de conteúdo. Abaixo
do mínimo, a cena **não** fica com a imagem "menos ruim" — ela troca de
estratégia.

Provedores sem chave não quebram o fluxo: `video-gen doctor` lista cada
um e o motivo de cada exclusão. Para `historical_art`, os museus (Met, AIC)
e Wikimedia são consultados antes dos bancos genéricos; só entra obra em
domínio público com imagem e direitos claros.

## Revisão humana

```bash
video-gen review --slug <slug>              # abre review/contact_sheet.html
video-gen review --slug <slug> --dry-run    # a decisão por cena, em texto
video-gen swap --slug <slug> --scene 3 --pick 1
video-gen rerender --slug <slug>
```

A folha de contato é um HTML estático com uma linha por cena: o texto, o
tipo de visual, a imagem escolhida com nota, provedor e licença, e **os
motivos das principais rejeições**. É o que permite revisar um vídeo em
~1 minuto e corrigir o tema em vez de adivinhar.

`swap` troca a imagem de uma cena; `rerender` refaz o vídeo e as legendas
a partir do que mudou — **sem** re-sintetizar a narração, sem re-pesquisar
e sem chamar o LLM.

## Configuração

Copie `config.example.toml` para `config.toml` e ajuste (duração-alvo, voz,
backend de render `auto|vaapi|qsv|cpu`, resolução, legendas). Variáveis de
ambiente (`CURIO_OUT_DIR`, `CURIO_TTS`, `CURIO_BACKEND`, …) sobrescrevem o
arquivo. Chaves de API nunca vão no código nem no repo — use `.env`
(gitignored; veja `.env.example`).

### Variáveis que valem a pena conhecer

| Variável | Efeito |
|---|---|
| `CURIO_GENRE` | gênero editorial: `history`, `etymology`, `mythology`, `mystery`, `science`, `people` (vazio = nenhum) |
| `CURIO_TYPOGRAPHY_<GÊNERO>` | fonte por gênero sem config.toml: `"primary=Minion Pro;italic=Minion Pro Italic"` |
| `CURIO_CONTACT` | **defina isto.** contato no `User-Agent`; sem ele a Wikimedia responde `429` a tudo, o que derruba a pesquisa e as imagens do Commons |
| `CURIO_WIKI_UA` | substitui o `User-Agent` inteiro, se preferir |

O `doctor` avisa quando o contato não está configurado. A Wikimedia
exige `nome/versão (contato) biblioteca/versão`, e sem contato a resposta
não é um erro legível — é `HTTP 429` em toda requisição.

### Seleção de mídia

| Chave (config) | Variável | Padrão | O que faz |
|---|---|---|---|
| `[media] providers` | `CURIO_MEDIA_PROVIDERS` | `pixabay,unsplash,pexels,nasa,met,aic,wikimedia` | ordem de tentativa; `none` desliga |
| — | `CURIO_MEDIA_SCORE_MIN` | `34` | nota mínima (0–100); `0` desliga o corte || — | `CURIO_MEDIA_MIN_DIMENSION` | `1080` | lado mínimo em px |

### Pontuação semântica (opcional, desligada)

A camada `base` (lexical) é a padrão e **não** precisa de nada além do
projeto. A camada CLIP existe como ponto de extensão e é **desligada por
padrão** — o `curio` não instala nem baixa torch, `open_clip` ou pesos de
modelo:

```bash
CURIO_CLIP_ENABLED=1     # liga (exige torch + open_clip instalados à mão)
CURIO_CLIP_DEVICE=auto  # auto | xpu | cuda | mps | cpu
```

Com `auto`, o projeto procura aceleradores de verdade no torch
instalado — `xpu` (Intel, o caso do Arc B580), `cuda`, `mps` — e só
recua para `cpu` se nenhum existir. `video-gen doctor` informa o estado
da camada e o device. CLIP entra **depois** dos filtros e da nota base,
só nos melhores candidatos, porque inferência pesada em todos eles
transformaria um vídeo rápido em lento.

## Estrutura de saída

```text
output/[<genero>/]<AAAAMMDD-titulo>/
├── script/script.txt + chapters.json
├── media/media.json (+ cache/media/ global com licenças)
├── timeline/timeline.json (+ visual_timeline.json no modo roteiro-pronto)
├── audio/narration.wav + words.json (IA) / human.wav (sua voz)
│   └── sfx.wav + mixed.wav (SFX discretos, só roteiro-pronto com inserções)
├── sources/sources.json (claims factuais + procedência de mídia)
│   └── FONTES.md (o mesmo em texto claro: fontes, imagens, créditos)
├── review/contact_sheet.html (revisão visual por cena)
├── teleprompter/teleprompter.mp4 (fluxo humano: fonte grande, marca a virada de cena)
├── subtitles/subs.srt + subs.ass
├── render/silent.mp4 + final.mp4
└── metadata.json (capítulos, assets, licenças, tempos, visual_report)
```

Com gênero escolhido, o projeto cai em `output/<genero>/` (uma pasta por
gênero: `people/`, `history`, …); sem gênero, fica direto em `output/`.
O nome da pasta é `AAAAMMDD_titulo` (só a data de hoje + título); se dois
vídeos do mesmo dia tiverem o mesmo título, o segundo ganha `-2`, `-3`…
Projetos antigos em `output/<slug>` continuam abrindo normal nos comandos
`review`, `swap`, `rerender`, `verify`, `sources` e `finalize`.

## Roteiros via LLM (chain com rodízio)

```bash
cp .env.example .env
# edite .env e preencha ao menos uma chave (gere em):
# NVIDIA https://build.nvidia.com · OpenRouter https://openrouter.ai/keys
# Groq https://console.groq.com/keys · Mistral https://console.mistral.ai
# Gemini https://aistudio.google.com/apikey
./scripts/run.sh generate "De onde veio a palavra salário?"
```

Ordem preferencial: Groq → NVIDIA → OpenRouter → Mistral → Gemini. O Curio
para no primeiro provider que responde corretamente. NVIDIA espera sem limite
de resposta e fica em segundo lugar após Groq; HTTP 400 remove NVIDIA do resto
da execução. `video-gen doctor` mostra status e modelo de cada provider. Sem nenhuma
chave, o pipeline usa o gerador local (base curada + template, custo
zero). Com roteiro em cache, a API **não** é chamada de novo — salvo
com `--force`.

Modelos: NVIDIA `meta/llama-3.3-70b-instruct`, Groq
`openai/gpt-oss-20b`, OpenRouter
`meta-llama/llama-3.3-70b-instruct:free`, Mistral `mistral-small-latest`
e Gemini `gemini-2.5-flash`. Troque via `*_MODEL`.

Robustez: até **6 rodadas globais de provider** (`CURIO_LLM_ATTEMPTS`,
1–12) com retries HTTP/backoff internos para erros transitórios. O resumo
final distingue rodadas do rodízio de requests HTTP consumidos dentro delas;
um provider que esgota seus retries não volta a abrir outro bloco de tentativas
na mesma execução. Erro HTTP 400 e outros 4xx, exceto 429, tiram o provider
do rodízio. Sem nenhuma chave, vale o gerador local acima.

Timeouts de chamada: NVIDIA usa **espera de resposta ilimitada**; sua
**conexão/handshake continua em 10 s**
(`[nvidia] connect_timeout` ou `NVIDIA_CONNECT_TIMEOUT`) e
(`[nvidia] connect_timeout` ou `NVIDIA_CONNECT_TIMEOUT`). Rede ou endpoint
sem handshake continuam falhando rápido. Os outros providers usam o limite
global padrão de 120 s (`[nvidia] timeout_max` ou `NVIDIA_TIMEOUT_MAX`).
Assim, Groq pode falhar e liberar o segundo lugar para NVIDIA; depois de um
HTTP 400 da NVIDIA, o rodízio segue para OpenRouter/Mistral/Gemini sem tentar
NVIDIA de novo naquela execução.

`CURIO_LLM_ATTEMPTS` limita as rodadas globais de seleção de provider. Os
retries HTTP dentro de cada rodada aparecem separadamente no diagnóstico; um
provider que esgota os retries transitórios sai do rodízio daquela execução.

Groq usa base oficial `https://api.groq.com/openai/v1`. Para GPT-OSS,
Curio solicita `reasoning_effort=low`
para reservar o orçamento de completion para o conteúdo e envia um User-Agent
identificando o Curio. Erros HTTP Groq preservam status e mensagem real da API
em vez de serem presumidos como chave inválida. A etapa JSON de cenas registra
`finish_reason`, `max_tokens`, tokens de completion disponíveis e tamanho da
resposta; JSON sintaticamente válido que não reproduza o roteiro continua sendo
rejeitado pelo gate literal e cai para a divisão local.

Mistral usa API OpenAI-compatible em `https://api.mistral.ai/v1` e chave
`MISTRAL_API_KEY`. Erros 4xx preservam mensagem original sem expor a chave.

Para múltiplas chaves NVIDIA futuras existe `NVIDIA_API_KEYS="key1,key2"`
(aceita na config, usa a 1ª; **rotação ainda não implementada**).

## Como funciona

| Etapa | Implementação MVP |
|---|---|
| Roteiro | chain LLM (Groq → NVIDIA → OpenRouter → Mistral → Gemini; NVIDIA sem timeout de resposta); tom conversado (conta como a um amigo, sem jargão); sem chave: base curada + template |
| Cenas | divisão semântica via LLM do chain (JSON) ou local; cada cena declara `visual_type`, assunto, entidades, contexto e termos proibidos |
| Mídia | consulta vários provedores, filtra com motivo, pontua por relevância sobre o assunto e corta abaixo do mínimo; sem foto boa a cena vira diagrama ou cartão, nunca imagem genérica |
| Fontes | registro persistente de claims factuais (status de evidência) + procedência de mídia por obra; CLI `sources`; `FONTES.md` com fontes, imagens e créditos prontos; URLs exatas da pesquisa |
| Narração | edge-tts neural `pt-BR-AntonioNeural` (masculina, grátis, sem login); fallback espeak-ng offline — ou sua voz via teleprompter |
| Legendas | timestamps reais (Edge WordBoundary / Whisper); blocos curtos na base, Archivo Black com caixa preta sólida |
| Título | pergunta curta gerada pela IA a partir do roteiro (metadados `video_title`), queimada nos primeiros 5 s |
| Render | segmentos por cena concatenados; VA-API → QSV → libx264; 1080×1920, 30 fps |

### Variedade de mídia no render

Assets relevantes selecionados alternam como fundos nos beats já planejados.
O orçamento de inserções limita fotos sobrepostas, não a variedade dos fundos.
Entre candidatos aprovados, o Curio prefere assets ainda não usados; repetição
por falta de alternativas fica marcada como `eligible_pool_exhausted`.

Métricas distinguem tentativas de seleção, assets únicos selecionados/disponíveis,
origem (`download` ou `cache`) e `visual_asset_beat_counts` por provider/asset.
`visual_assets_reused` conta reuso entre cenas; manter uma foto durante vários
beats de câmera não conta como nova seleção. O cache de segmentos considera
assets, arquivos e apresentação. `rerender` usa a timeline temporizada e grava
novas métricas sem gerar outra narração.

### Diagnósticos de fontes e mídia

A pesquisa começa pelo tema amplo e consolida trechos literais com suas URLs.
Com LLM configurado, um planejamento curto seleciona fatos relevantes e lacunas
essenciais. A mesma etapa executa no máximo três buscas específicas na Wikipedia,
reutilizando extração e filtro de relevância existentes. Evidência suficiente evita
novas buscas; lacunas não resolvidas seguem explícitas no contexto, que permanece
limitado a 2500 caracteres. `sources/research.json` registra fatos, buscas
complementares e motivos; métricas incluem `research.complementary_queries`.

- Cada execução cria `output/<slug>/logs/run-<timestamp>.jsonl` antes da pesquisa.
  O log registra etapas, providers, fallbacks, erros e tempos, inclusive em
  falhas ou `Ctrl+C`. Terminal mostra resumo; JSONL contém detalhes sanitizados.
  `metadata.json` aponta para `execution_log`. `metrics/` continua separado.
- Afirmações numéricas sem correspondência nas fontes continuam passando
  pelo mesmo gate de grounding. O aviso inclui o trecho do roteiro, a causa
  provável e as fontes avaliadas; consulte `sources/FONTES.md` para o relatório
  completo.
- Pesquisa sem fonte no passe estrito não trava mais o vídeo: um segundo
  passe aceita por núcleo no título (sem exigir discriminante, homônimos
  em `forbidden` continuam barrados) e um terceiro tenta núcleo + Wikipedia
  em inglês; se nada falar do tema, o roteiro sai mesmo assim com status
  `weak`, aviso explícito e incerteza no texto — nunca erro fatal no
  `generate`. A precisão vem do portão; a garantia, dos passes.
- Providers sem configuração necessária, como Pexels sem `PEXELS_API_KEY`,
  avisam uma vez por execução. A cascata de fallback continua usando os outros
  providers disponíveis.
- `metadata.json` registra `provider_downloads` por provider: candidatos
  encontrados, downloads tentados/sucedidos/falhos, HTTP 403 e outros erros.
  Cache hits não contam como novos downloads.
  `consumption.media.funnel` nas métricas separa candidatos retornados,
  duplicados, filtros, score, seleção e uso. `rejection_reasons` resume motivos;
  campos sem ocorrência podem estar ausentes (zero). `assets_rejected` inclui
  rejeições por score. `synth_diagrams` inclui cards gerados localmente.
- `media.json` registra assets repetidos em `reuse` com as cenas e o motivo
  `same_top_match`; a reutilização continua permitida. Cenas sem foto adequada
  podem receber cards ou diagramas semânticos.

O relatório do caso São Jerônimo, incluindo validação e limitações, está em
[`docs/relatorios/20260930-144326_relatorio_diagnosticos-sao-jeronimo.md`](docs/relatorios/20260930-144326_relatorio_diagnosticos-sao-jeronimo.md).

### Identidade audiovisual por gênero

O recurso vem ativado por padrão (`audio_enabled`, `music.mode=auto`,
`transitions=auto`); desligue com `--music-mode none` ou
`[audio].transitions = "none"`. O `config.toml` permite ajustar ganho,
ducking e autopreenchimento. A biblioteca persistente fica em:

```text
assets/library/music/<genre>/
assets/library/sfx/<genre>/<category>/
```

O render consulta somente esse acervo local. Quando abaixo do mínimo,
`auto_fill` pode preenchê-lo até o alvo; com a configuração de exemplo, o
primeiro uso pode bootstrapar o acervo. Depois de atingir o mínimo, vídeos não
pesquisam nem baixam. Limites padrão: música 3/6/10 por gênero (mínimo/alvo/
máximo); SFX 2/5/8 por categoria. O autopreenchimento pode ser desligado para
exigir atualização manual.

A única fonte automática inicial é a API oficial do Freesound. Defina
`FREESOUND_API_KEY` em `.env` (chave em
<https://freesound.org/apiv2/apply>). O Curio usa os previews oficiais e só
aceita CC0 ou CC BY; NC, ND, SA e licenças ausentes/ambíguas são rejeitadas.
CC BY mantém autor, origem e link da licença no metadata para atribuição. Não
há scraping nem download do endpoint original que exige OAuth2. Arquivos
manuais são marcados como fornecidos pelo usuário, com licença não verificada.

```bash
# atualizar música (sem --genre: gênero ativo ou todos os gêneros)
./scripts/run.sh music update --genre people
# atualizar uma categoria SFX
./scripts/run.sh music update --kind sfx --genre people --category paper
# listar acervo e contador de uso sem acessar a rede
./scripts/run.sh music list --genre people

# na geração: auto, none ou manual
./scripts/run.sh generate "Fale sobre São Jerônimo" --music-mode none
./scripts/run.sh generate "Fale sobre São Jerônimo" \
  --music-mode manual --music-file "$HOME/Music/faixa.mp3"
```

A TUI expõe Automática, Nenhuma, arquivo manual e atualização da biblioteca em
Configurações → Áudio. A seleção automática busca camas calmas/ambientais,
rejeita títulos que indiquem efeitos/ruído e revalida faixas em cache. Se não
houver faixa compatível, o vídeo sai sem música em vez de usar áudio confuso.
Entre as faixas aprovadas, favorece assets menos usados e desempata com seed
estável do projeto. A música usa ganho padrão de −9 dB (configurável entre
−40 e −6 dB), fades de
entrada/saída e sidechain ducking sob a voz, com release para atravessar pausas.
SFX da biblioteca substituem apenas eventos pontuais já existentes; sem asset
local, o SFX sintético atual continua disponível. Transições de cena têm
efeito por gênero (dissolve, fade a preto, deslizamento), duração ajustada
por gênero/papel da cena, cortes secos em mudanças dramáticas e fade final.
`[audio].transitions = "none"` desliga a camada de transição. O `metadata.json`
registra faixa/licença/atribuição, SFX, volume, ducking e identidade de cache
do áudio efetivamente renderizado. Sem foto específica, a cena tenta o
genérico do gênero (igreja, biblioteca, manuscrito) antes do cartão; cartão
sem assunto mostra a primeira frase da narração, nunca tela vazia.

## Roadmap

- **MVP (agora):** pipeline básico provando ideia → vídeo publicável.
- **V1:** pesquisa/fontes, seleção de mídia, templates, cache, TTS melhor.
- **V2:** fila de ideias, lote com dezenas de vídeos, retry automático.
- **V3:** publicação, analytics, interface local (se houver demanda real).

## Commits

Padrão [Conventional Commits](https://www.conventionalcommits.org/): `feat:`,
`fix:`, `docs:`, `chore:`, etc. Ex.: `fix: change password type from number to text`.

## Licença

MIT — ver `LICENSE`.
