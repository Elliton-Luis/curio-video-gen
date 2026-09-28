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

# Duração aproximada à sua escolha (roteiro, cenas e verificação acompanham)
video-gen generate --duration 30 "O que é um satélite?"

# Gerar base para narrar você mesmo (silencioso + teleprompter)
video-gen generate --narration human "De onde veio a palavra salário?"
# abre a pasta do teleprompter + Audacity sozinho (desliga com --no-open
# ou CURIO_AUTO_OPEN=0; binários em config.toml [teleprompter])
# ...grave sua voz, depois:
video-gen finalize de-onde-veio-a-palavra-salario --audio minha-voz.wav

# Refazer tudo do zero (padrão: reaproveita artefatos existentes)
video-gen generate --force "O mito dos capacetes com chifres dos vikings"

# Interface visual em terminal (abre a TUI)
video-gen tui
# Atalho: ./scripts/run.sh sem argumentos também abre a TUI

# Listar vídeos e ver metadados
video-gen list
video-gen info --slug salario

# Verificar um vídeo contra os critérios do MVP (PRD §19)
video-gen verify --slug salario
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

## Estrutura de saída

```text
output/<slug>/
├── script/script.txt + chapters.json
├── media/media.json (+ cache/media/ global com licenças)
├── timeline/timeline.json
├── audio/narration.wav + words.json (IA) / human.wav (sua voz)
├── teleprompter/teleprompter.mp4 (fluxo humano)
├── subtitles/subs.srt + subs.ass
├── render/silent.mp4 + final.mp4
└── metadata.json (capítulos, assets, licenças, tempos)
```

## Configuração

Copie `config.example.toml` para `config.toml` e ajuste (duração-alvo, voz,
backend de render `auto|vaapi|qsv|cpu`, resolução, legendas). Variáveis de
ambiente (`CURIO_OUT_DIR`, `CURIO_TTS`, `CURIO_BACKEND`, …) sobrescrevem o
arquivo. Chaves de API nunca vão no código nem no repo — use `.env`
(gitignored; veja `.env.example`).

## Roteiros via NVIDIA API

```bash
cp .env.example .env
# edite .env e preencha NVIDIA_API_KEY (gerada em https://build.nvidia.com)
./scripts/run.sh generate "De onde veio a palavra salário?"
```

Com chave configurada, o roteiro vem do modelo `nvidia/nemotron-3-ultra-550b-a55b`
(via `NVIDIA_MODEL` é possível trocar sem mexer no pipeline). Sem chave, o
pipeline usa o gerador local (base curada + template, custo zero). Com roteiro
em cache, a API **não** é chamada de novo — salvo com `--force`.

Para múltiplas chaves futuras existe `NVIDIA_API_KEYS="key1,key2"` (aceita na
config, usa a 1ª; **rotação ainda não implementada**).

## Como funciona

| Etapa | Implementação MVP |
|---|---|
| Roteiro | NVIDIA API (Nemotron 3 Ultra) com chave; sem chave: base curada + template |
| Cenas | divisão semântica via NVIDIA (JSON) ou local; consultas visuais em inglês |
| Mídia | Wikimedia + Openverse (sem chave) e Pexels (com chave); só entra imagem com título ligado ao tema, sem marca d'água; fallback gradiente honesto + Ken Burns |
| Narração | edge-tts neural `pt-BR-AntonioNeural` (masculina, grátis, sem login); fallback espeak-ng offline — ou sua voz via teleprompter |
| Legendas | timestamps reais (Edge WordBoundary / Whisper); blocos curtos na base |
| Render | segmentos por cena concatenados; VA-API → QSV → libx264; 1080×1920, 30 fps |

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
