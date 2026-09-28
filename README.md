# curio — Máquina de Conteúdo Educativo em Vídeo

> Conteúdo curto que respeita a inteligência do espectador.

Ferramenta local (Linux, CLI + TUI) que transforma **uma ideia textual** em um
**vídeo vertical de ~45 s** com roteiro, narração em PT-BR, legendas queimadas
e MP4 final — tudo com **custo próximo de zero** (TTS local + FFmpeg).

Princípio editorial: *o vídeo pode simplificar uma ideia para torná-la
acessível, mas não deve falsificá-la para torná-la mais viral.*

## Status

MVP em construção (v0.1.0). Pipeline funcional:

```text
IDEIA → ROTEIRO → NARRAÇÃO → LEGENDAS → MONTAGEM → VÍDEO FINAL
```

## Requisitos

- Linux, Python 3.11+
- `ffmpeg` + `ffprobe` (renderização)
- `espeak-ng` com voz `pt-br` (TTS local gratuito)
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
# Gerar um vídeo
video-gen generate "De onde veio a palavra salário?"

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
[1/5] Gerando roteiro... OK
[2/5] Gerando narração... OK
[3/5] Sincronizando legendas... OK
[4/5] Montando vídeo... OK
[5/5] Finalizando... OK

Output: output/salario/render/final.mp4
```

## Estrutura de saída

```text
output/<slug>/
├── script/script.txt
├── audio/narration.wav
├── subtitles/subs.srt
├── assets/
├── render/final.mp4
└── metadata.json
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
| Narração | `espeak-ng` pt-br, com 1 correção automática de ritmo |
| Legendas | SRT em frases curtas, fonte escalada pela altura, base inferior |
| Montagem | FFmpeg: gradiente lavfi + título + legendas libass |
| Render | auto-detecta VA-API → QSV → libx264; 1080×1920, 30 fps |

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
