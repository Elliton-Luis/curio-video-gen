# Relatório — MVP inicial do curio

- **Data:** 2026-09-28 12:32 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** scaffolding completo + pipeline MVP + teste end-to-end + commit inicial
- **Commit:** `7a18ec6` — `feat: add MVP pipeline for educational short videos`
- **Branch:** `main`
- **Arquivos:** 19 criados, 1234 inserções, 1090 linhas de código/config (py+sh+toml)

## 1. O que foi pedido

Transformar o PRD "Máquina de Conteúdo Educativo em Vídeo" em um projeto real:
nome, README vivo, scripts de instalação/execução, TUI simples, commits no
padrão Conventional Commits.

## 2. O que foi feito e como

### 2.1 Nome e identidade

Escolhido **`curio`** (curiosidade + curto). Binários: `video-gen` (principal,
citado no PRD §14) e `curio-tui`. Versão `0.1.0`, licença MIT.

### 2.2 Sondagem do ambiente (antes de codar)

Verificado via terminal: FFmpeg 8.1.3 com `libass`/`libfreetype` (legenda
queimada OK), VA-API funcional (`Intel iHD`, encode H264/HEVC), `espeak-ng`
1.52.0 com voz `pt-br`, fonte DejaVu Bold, Python 3.14. Tudo isso definiu os
defaults: TTS = espeak-ng, render = auto-detect com VA-API primeiro.

### 2.3 Arquitetura implementada (PRD §17, KISS/YAGNI)

Sem frameworks, sem banco, só stdlib Python. Separação por etapa:

| Arquivo (linhas) | Responsabilidade | Decisão-chave |
|---|---|---|
| `config.py` (82) | Config central (PRD §18) | Precedência CLI > env > `config.toml` > padrão; segredos só via env |
| `slug.py` (14) | Nome do diretório por vídeo | Normalização NFKD, `[a-z0-9-]`, máx 40 chars |
| `ffmpeg.py` (104) | Prova real de hardware | Testa encode de 1 frame em vez de confiar só no `vainfo`; fallback VA-API → QSV → libx264 |
| `stages/script.py` (126) | Roteiro (PRD §6) | Base curada + template honesto; LLM (OpenAI-compat via `urllib`) só com `CURIO_LLM_API_KEY`; meta de ~13,5 chars/s |
| `stages/tts.py` (85) | Narração (PRD §8) | espeak-ng pt-br; **1 retry com velocidade corrigida** se duração fugir ±15% da meta |
| `stages/subs.py` (64) | Legendas (PRD §9) | SRT com tempos proporcionais ao nº de caracteres; blocos de ≤7 palavras/42 chars |
| `stages/render.py` (97) | Montagem (PRD §10–11) | Fundo em gradiente `lavfi` (sem downloads) + título `drawtext` + `subtitles` libass; 1080×1920@30fps, AAC, `faststart` |
| `pipeline.py` (162) | Orquestração (PRD §4,15,16,19) | 5 etapas, `metadata.json`, **reuso de artefatos** por padrão, `--force` refaz tudo, tempos por etapa |
| `cli.py` (172) | CLI (PRD §14) | `generate/tui/list/info/voices/doctor`; erros dizem etapa + motivo provável + como retomar |
| `tui.py` (83) | TUI | Menu em stdlib puro (sem `curses`/deps): gerar, listar, doctor, sair |
| `scripts/install.sh` (38) | Dependências | Checa python/ffmpeg/espeak-ng com instrução por distro; `pip install -e .` com fallback para `run.sh` |
| `scripts/run.sh` (6) | Execução sem install | `PYTHONPATH=src python3 -m curio` |
| `pyproject.toml` / `config.example.toml` / `README.md` / `LICENSE` / `.gitignore` | Empacotamento e docs | `output/` propositalmente gitignored |

### 2.4 Princípio editorial aplicado (PRD §2)

O roteiro curado de "salário" **desmente o mito** do pagamento em sal
(`salarium` era adicional em moeda, não o soldo) em vez de repeti-lo para
viralizar. Template genérico proíbe "Você sabia que" e clickbait.

### 2.5 Correção pós-teste

Detectado arquivo temporário `narration.wav.txt` vazando para `audio/`.
Corrigido com `os.remove()` após a síntese (`stages/tts.py`). Entrou no mesmo
commit inicial (árvore já estava staged antes do `git init`).

## 3. Evidências do teste end-to-end

Comando: `./scripts/run.sh generate "De onde veio a palavra salário?"`

- `doctor`: 7/7 OK (python, ffmpeg, ffprobe, espeak-ng, libass, VA-API `/dev/dri/renderD128`, fonte)
- Pipeline: `[1/5]…[5/5] OK`, saída `output/de-onde-veio-a-palavra-salario/render/final.mp4`
- `ffprobe`: h264 1080×1920 (46,77 s) + aac (46,77 s), 4,6 MB
- Metadados: `script_source=curated`, 529 chars, 15 cues SRT, TTS speed auto-ajustada 170→134, `render=h264_vaapi`, tempo total **17,01 s** (render 16,68 s)
- Reexecução sem `--force`: **0,25 s**, `render: cache` (critério PRD §19 atendido)

## 4. Critérios de aceitação MVP (PRD §19) — status

| Critério | Status |
|---|---|
| Entrada via CLI | ✅ |
| Roteiro → narração → legendas → montagem → MP4 | ✅ |
| Vertical 9:16, ~45 s, com áudio e legendas queimadas | ✅ (46,77 s) |
| Sincronização aceitável, reproduzível, sem intervenção manual | ✅ |
| Reexecução sem repetir etapas | ✅ |

## 5. Limitações conhecidas (viraram backlog)

Voz espeak-ng é robótica; legendas são proporcionais (não por palavra);
template genérico é raso para temas fora da base curada; sem pesquisa/fontes
(PRD §7, propositalmente futuro); sem testes automatizados; sem processamento
em lote. Detalhes em `docs/analises/20260928-123219_analise_estado-atual-mvp.md`
e `docs/melhorias/20260928-123219_melhoria_backlog-v1.md`.
