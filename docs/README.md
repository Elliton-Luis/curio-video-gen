# docs — índice da documentação de trabalho

Tudo que é analisado ou implementado neste projeto gera um documento aqui.
Convenção de nomes: `AAAAMMDD-HHMMSS_<tipo>_<slug>.md`
(tipos: `relatorio`, `analise`, `melhoria`). Processo completo em
`_modelos/MODELO.md`.

## Relatórios (o que foi feito e como)

- `relatorios/20261005-visual-fallback-contract.md` — `VisualFallbackPlan`, origem do assunto, etapas ordenadas explícitas para diagramas, rota especial removida, suíte integral: 942 testes.
- `relatorios/20261003-122730_relatorio-falha-chain-llm-cenas.md` — elimina timeout ilimitado, respeita rate limit Groq e recupera cenas locais em ideia automática; suíte 780/780.
- `relatorios/20261003-121500_relatorio-fallback-cenas-llm.md` — corrige espera NVIDIA sem timeout, limita 429 e preserva geração automática com fallback local; 779 testes passaram.
- `relatorios/20261003-095825_relatorio-direcao-visual.md` — Fase 2 final: diretor/contexto estruturados, gates independentes, funis reais para cinco temas, falsos positivos antes/depois e suíte 775/775.
- `relatorios/20261003-002807_relatorio-fase2-direcao-visual-parcial.md` — estado parcial da fase 2: contratos de intenção, ranking semântico, reparo de cenas, CLIP opcional, testes atuais e validações pendentes.
- `relatorios/20261002-205941_relatorio-queries-eletricas-tesla.md` — queries compostas para corrente elétrica e filtro contra rio/homônimos Tesla; 738 testes verdes.
- `relatorios/20261002-205829_relatorio-aprendizado-contavel.md` — roteiro exige compreensão sem replay e takeaway retellable; 736 testes verdes.
- `relatorios/20261002-203402_relatorio-musica-mood-genero.md` — seleção exige mood compatível com adapter; faixa contemplativa/haunting não entra em people; 735 testes verdes.
- `relatorios/20261002-191200_relatorio-busca-fresca-prompts.md` — nova busca em cada vídeo, cache só de bytes para rerender; prompts reduzidos preservados; 733 testes verdes.
- `relatorios/20261002-190300_relatorio-ancora-pessoa-e-topico.md` — âncora local exige título coerente com tema/pessoa; 733 testes verdes.
- `relatorios/20261002-185303_relatorio_anchor-topico-visual.md` — corrige desvio de assunto local; ancora cenas ao tema geral; 732 testes verdes.
- `relatorios/20261002-183000_relatorio_refatoracao-curio.md` — refatoração estrutural etapas 1–5; adapters, módulos por etapa e performance limitada; suíte: 728 testes.
- `relatorios/20261002-182037_relatorio_estagio-midia-pipeline.md` — aquisição, mídia manual e standby movidos de `pipeline.py` para `pipeline_media.py`; 29 testes focados verdes.
- `relatorios/20261002-180859_relatorio_estagio-audio-pipeline.md` — TTS, alinhamento e legendas extraídos para `pipeline_audio.py`; 728 testes verdes.
- `relatorios/20261002-171500_relatorio-performance-pipeline.md` — busca/download limitados e concorrentes, cache ffprobe e planner condicional; 727 testes verdes.
- `relatorios/20261002-170000_relatorio_separacao-etapas-render.md` — timeline/SFX, segmentos de render e pesquisa separados; `visual.py` reduzido; 727 testes verdes.
- `relatorios/20261002-163000_relatorio_tui-terminal.md` — terminal, teclado, menu e caminho movidos para `tui_terminal.py`; TUI permanece stdlib only; 721 testes verdes.
- `relatorios/20261002-160000_relatorio_adapters-genero-fonte-musica.md` — adapters declarativos, fontes especialistas e política de áudio por gênero; 721 testes verdes.
- `relatorios/20261002-153500_relatorio_prompts-editoriais.md` — prompts de roteiro e título movidos de `nvidia.py` para `stages/prompts.py`; 720 testes verdes.
- `relatorios/20261001-230902_relatorio_musica-por-afinidade.md` — cama por afinidade com o tema e ganho −3 dB; sem custo de LLM.

- `relatorios/20261001-223646_relatorio_cama-audivel-ducking-suave.md` — cama normalizada (loudnorm), ganho −5 dB e ducking 3:1; +4 dB audível na pausa, voz dominante.

- `relatorios/20261001-222132_relatorio_musica-genero-motion-slide.md` — camas por gênero (violino/tenso), ganho −7 dB, deriva sem tremor e slides de galeria; render real validado.

- `relatorios/20261001-214950_relatorio_providers-museus-met-aic.md` — Met Open Access + Art Institute of Chicago (domínio público, sem chave), prioridade em cenas históricas; suíte completa: 692 testes.

- `relatorios/20261001-203053_relatorio_variedade-assets-render.md` — seleção repetia IDs e overlays descartavam fundos; associa assets a beats, corrige cobertura central/cache e valida seis assets reais de César no render.
- `relatorios/20261001-184320_relatorio_rag-iterativo.md` — busca ampla, fatos literais com URLs e até três complementações por lacuna; logs/métricas e contexto de 2500 caracteres.
- `relatorios/20261001-182038_relatorio_volume-audio-aumentado.md` — música padrão −9 dB e SFX de inserção −15 dB; ducking preservado.
- `relatorios/20261001-174317_relatorio_qualidade-roteiro-legenda-audio.md` — highlight por WordBoundary e compensação temporal do limiter; render real validado, recuperação editorial ainda reprovada no grounding.
- `relatorios/20261001-161013_relatorio-groq-primeiro-musica-calma.md` — Groq primeiro, NVIDIA segundo sem timeout de resposta e desvio em HTTP 400; seleção rejeita camas com título de ruído e evita reuso de faixa inadequada.
- `relatorios/20261001-154612_relatorio_escape-apostrofo-ffmpeg.md` — corrige apóstrofos em título no `drawtext`; reproduz e cobre falha do filtergraph com ASS.
- `relatorios/20261001-153350_relatorio_tui-colar-roteiro.md` — Roteiro Pronto aceita colagem multiline até `<<FIM_DO_ROTEIRO>>`, preserva texto e segue pelo pipeline; suíte completa: 653 testes.
- `relatorios/20261001-141308_relatorio_fallback-resposta-invalida.md` — resposta LLM vazia/curta agora cai para próximo provider; inclui diagnóstico sem conteúdo sensível e 37 testes focados.
- `relatorios/20261001-135550_relatorio_shorts60.md` — duração editorial guiada 45–90 s, beats de câmera com assets existentes, legendas/safe area e métricas; validação focada: 115 testes.
- `relatorios/20261001-125954_relatorio_musica-15-inserts-21.md` — música −15 dB e inserts −21 dB, ducking intacto.
- `relatorios/20261001-125631_relatorio_ganho-musica-15db.md` — música `-15 dB`, insert SFX `-21 dB`, ducking intacto.
- `relatorios/20261001-125404_relatorio_pasta-por-genero-slug-datado.md` — saída em `output/<genero>/<AAAAMMDD_titulo>`, anti-colisão `-2` e compat com projetos legados.

- `relatorios/20261001-124051_relatorio_ganho-musica-18db.md` — cama musical em −18 dB com ducking intacto.

- `relatorios/20261001-082206_relatorio_som-alto-transicoes-genericas.md` — ganhos audíveis, xfade por gênero, cascata genérica e cartões nunca vazios.

- `relatorios/20261001-081537_relatorio_fontes-garantia-texto-timeout-separado.md` — segundo passe de fontes (núcleo + EN + `allow_weak`, nunca fatal) e timeout NVIDIA separado (10 s handshake / 120 s resposta).

- `relatorios/20261001-071636_relatorio_musica-transicoes-cascata-generica.md` — ganho −24 dB, xfade por gênero, genéricos com núcleo próprio e cartões nunca vazios.

- `relatorios/20261001-063937_relatorio_contexto-visual-audio-auto.md` — contexto visual compartilhado entidade↔scoring, áudio automático padrão, biblioteca people/SFX e validação real.

- `relatorios/20261001-045242_relatorio_diagnostico-scoring-tomas-aquino.md` — replay de scores reais, origem de 34 e decisão de preservar threshold.
- `relatorios/20261001-043232_relatorio-log-persistente-execucao.md` — eventos curtos de CLI/TUI, log JSONL desde startup, redação de secrets e cobertura de falha/interrupção.
- `relatorios/20261001-042350_relatorio-log-persistente-execucao.md` — eventos curtos em CLI/TUI, JSONL por execução, sanitização e captura de falhas/interrupções.
- `relatorios/20261001-034958_relatorio_funil-midia-sem-download.md` — causa do funil de São Francisco, execução pequena, contadores de perdas, URL JPG Unsplash e testes de regressão.
- `relatorios/20261001-033358_relatorio_contrato-roteiro-ia.md` — documentação do contrato de geração automática, template manual, incompatibilidade com Roteiro Pronto e validações documentais.
- `relatorios/20261001-031800_relatorio_providers-env-mistral.md` — auditoria e sincronização de `.env`, ordem/modelos LLM, integração Mistral e validações mínimas dos cinco providers.
- `relatorios/20260928-123219_relatorio_mvp-inicial.md` — scaffolding + pipeline
  MVP + teste end-to-end (commit `7a18ec6`).
- `relatorios/20260928-123729_relatorio_run-sh-tui-verify.md` — `run.sh` sem args
  abre a TUI; novo `verify` (8 cheques) + fluxo "teste rápido".
- `relatorios/20260928-133718_relatorio_nvidia-script-engine-legendas.md` —
  roteiros via NVIDIA API (Nemotron 3 Ultra) + legendas refeitas (ASS com
  PlayRes real, base 68, blocos curtos); inclui correção do bug "roteiro com
  o prompt da IA".
- `relatorios/20260928-134448_relatorio_voz-neural-masculina.md` — TTS padrão
  vira edge-tts neural `pt-BR-AntonioNeural` (grátis, sem login) com fallback
  espeak-ng avisado.
- `relatorios/20260928-135530_relatorio_benchmark-vozes.md` — Donato/Humberto/
  Nicolau/Valerio não existem no Edge TTS; mesma frase renderizada nas 3
  vozes PT-BR reais (`output/benchmark_vozes/`) para avaliação auditiva.
- `relatorios/20260928-161950_relatorio_midia-teleprompter-sincronizacao.md` —
  cenas NVIDIA + Wikimedia/Ken Burns + WordBoundary + teleprompter +
  finalize/Whisper; 5 testes + validação visual (T4 com stand-in, não voz real).
- `relatorios/20260928-180611_relatorio_tui-por-objetivo.md` — TUI reescrito
  por objetivo (vídeo pronto × narrar em 2 passos) + ajuda + lista com situação.
- `relatorios/20260928-182208_relatorio_prompt-roteiro-curiosidade.md` — prompt
  de roteiro do usuário vira regra oficial (loops pergunta-resposta); teste Lua.
- `relatorios/20260928-183330_relatorio_imagens-duracao.md` — Openverse+Pexels,
  gate de relevância, `--duration` e `verify` por projeto.
- `relatorios/20260928-185811_relatorio_teleprompter-real.md` — teleprompter
  com próximo bloco visível + fase amarela de aviso de virada.
- `relatorios/20260928-191108_relatorio_imagens-ate-o-fim.md` — cortesia
  anti-429 + reuso da cena vizinha: imagens do início ao fim.
- `relatorios/20260928-191547_relatorio_abrir-pasta-gravador.md` — Dolphin +
  Audacity automáticos pós-teleprompter (configurável, nunca falha).
- `relatorios/20260928-210734_relatorio_metricas.md` — `metrics/` com tempo,
  consumo (chamadas/tokens/downloads) e tamanhos por vídeo + backfill.
- `relatorios/20260928-195420_relatorio_json-cenas-smoke.md` — JSON de cenas
  tolerante (extração + orçamento estendido) + `scripts/smoke.sh` (14 cheques).
- `relatorios/20260929-121121_relatorio_llm-retry-openrouter.md` — etapa LLM
  com 5 tentativas (backoff, só transitório) + fallback OpenRouter
  (`OPENROUTER_API_KEY`, padrão `google/gemini-2.5-flash`); `smoke.sh` com
  40 cheques.
- `relatorios/20260929-123641_relatorio_roteiro-pronto-modo.md` —
  `from-script`: roteiro pronto vira colagem álbum sem reescrever a
  narração (timeline visual, Ken Burns p/ 1 foto, `verify` 8/8 no E2E IA).
- `relatorios/20260929-123641_relatorio_entradas-sfx-variedade.md` — 6
  entradas sem repetição consecutiva (seed do slug) + SFX discretos em
  ~1/3 das inserções (pico −35 dB, narração intacta); `smoke.sh` com
  47 cheques.
- `relatorios/20260929-133806_relatorio_teleprompter-roteiro-natural.md` —
  teleprompter legível (fonte 104, negrito, separador + ciano na virada de
  cena, sincronia intacta) + prompt de roteiro conversado; `smoke.sh` com
  54 cheques.
- `relatorios/20260929-135442_relatorio_legendas-titulo.md` — legendas
  Archivo Black com caixa preta sólida (sincronia intacta) + título-pergunta
  IA queimado 5 s (`video_title`); `smoke.sh` com 64 cheques.
- `relatorios/20260929-141815_relatorio_duracao-flexivel.md` — modo
  Automático/Ilimitado padrão (conteúdo manda), meta nunca corta, TTS sem
  compressão artificial, verify informativo; `smoke.sh` com 73 cheques.
- `relatorios/20260929-142919_relatorio_llm-chain-gemini-groq.md` — chain
  NVIDIA→OpenRouter→Gemini→Groq em rodízio intercalado com levantamento
  final + `.env` organizado; `smoke.sh` com 77 cheques.
- `relatorios/20260929-155200_relatorio_sistema-fontes.md` — sistema de
  fontes factuais + procedência de mídia (claims + mídia, persistência,
  dedup, status, CLI, registro automático de mídia); `smoke.sh` com
  87 cheques.
- `relatorios/20260929-174157_relatorio_legendas-shorts-reels.md` — legendas
  Shorts/Reels/TikTok (uppercase, glitch highlight, fade-in, timestamp folder);
  `smoke.sh` com 87 cheques.
- `relatorios/20260930-144326_relatorio_diagnosticos-sao-jeronimo.md` — contexto
  estruturado de São Jerônimo, grounding explicativo, diagnóstico de providers,
  timeout LLM configurável e evidências/limitações da validação manual.
- `relatorios/20260930-163126_relatorio_biblioteca-audiovisual-genero.md` —
  biblioteca local Freesound CC0/CC BY, política de atualização, seleção por
  uso/seed, mix com ducking, transições, metadata, testes FFmpeg e limitações.
- `relatorios/20260930-183440_relatorio_fallback-llm-nvidia.md` — NVIDIA como
  último provider viável, timeout removido no fallback final, até 5 retries,
  contagem separada de requests/rodadas e resultados pytest/smoke.
- `relatorios/20260930-232100_relatorio-diagnostico-groq-nvidia-json.md` — ID
  Lightning conferido no NIM, causa HTTP 403 Groq, reasoning do GPT-OSS,
  telemetria de truncamento JSON e resultados das chamadas reais.
- `relatorios/20260930-221049_relatorio_tui-seletor-vertical-genero.md` —
  seletor vertical de gênero com descrição e metadados dinâmicos, testes de
  teclado/lista e validação da suíte completa.
- `relatorios/20260930-232100_relatorio-diagnostico-groq-nvidia-json.md` —
  validação de NVIDIA Lightning e Groq 20B, causa do 403, reasoning-token
  budget, telemetria finish_reason e limites da segunda geração NVIDIA.

## Análises (estado, gaps, riscos)

- `analises/20261002-184536_analise-direcao-visual.md` — fluxo real de mídia, causas semânticas, evidências métricas, contratos e arquitetura proposta; diagnóstico sem mudança de código.
- `analises/20261002-205941_analise-imagens-tesla-corrente.md` — fallback local descontextualizou corrente e Tesla; métricas mostram pontes, Gigafactory e rua no lugar de invenções.
- `analises/20261002-190300_analise-midia-marco-revolucao.md` — métricas e títulos confirmam desvio lexical em dois vídeos locais.
- `analises/20261002-150849_relatorio_refatoracao-etapas-1-2.md` — implementação das etapas 1–2, gates, `textnorm` e `ResearchResult` explícito.
- `analises/20261002-131932_analise_refatoracao-codigo-morto.md` — auditoria estrutural, candidatos mortos, duplicações e ordem de refatoração.
- `analises/20261001-045242_analise_scores-baixos-tomas-aquino.md` — decomposição de candidatos reais, quebra entre consultas locais e scoring, idioma/denominador e instrumentação mínima recomendada.
- `analises/20261001-032940_analise_contrato-geracao-roteiro-ia.md` — prompts integrais e dados interpolados, estrutura separada de título/cenas, validação/fallback, consumo downstream e incompatibilidade com `Roteiro Pronto`.
- `analises/20260928-123219_analise_estado-atual-mvp.md` — veredito: MVP prova a
  tese; riscos altos = voz robótica e falta de pesquisa/fontes.

## Melhorias (backlogs e propostas)

- `melhorias/20260928-123219_melhoria_backlog-v1.md` — 9 itens priorizados
  (Piper TTS, base curada 10 temas, validador editorial, templates visuais,
  testes de fumaça, `batch`, …).
