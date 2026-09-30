# Relatório — Biblioteca audiovisual persistente por gênero

- **Data:** 2026-09-30 16:31 (-03:00)
- **Tipo:** relatorio
- **Escopo:** biblioteca local de música/SFX, atualização licenciada, seleção, mixagem, ducking, transições e metadata audiovisual.
- **Commit(s):** `6e678e3` (`feat(audio): add persistent genre audiovisual library`), `93f8427` (`test(audio): cover library caching and rendered mixes`), `02a3219` (`docs: record audiovisual library implementation`).
- **Origem:** solicitação “Curio — Biblioteca audiovisual automática por gênero”.

## 1. O que foi pedido

Adicionar identidade audiovisual por gênero sem pesquisar/baixar mídia a cada render. A biblioteca deveria persistir localmente, limitar quantidades, guardar procedência/licença, selecionar determinística e favorecer assets menos usados, misturar música baixa com ducking, preservar SFX opcionais, aplicar transições editoriais, oferecer controles CLI/TUI e gravar o áudio efetivamente usado no metadata. Configuração ausente deveria manter compatibilidade; biblioteca vazia não poderia impedir a produção do vídeo.

## 2. O que foi feito e como

| Arquivo / área | Responsabilidade | Implementação |
|---|---|---|
| `src/curio/audio/library.py` | Acervo persistente e fonte | Criada a biblioteca `assets/library/music/<genre>/` e `assets/library/sfx/<genre>/<category>/`, com sidecar JSON por arquivo. O único adapter inicial usa a API oficial Freesound e baixa os previews oficiais `preview-hq-mp3`; não faz scraping nem usa o endpoint de download original protegido por OAuth2. |
| `src/curio/audio/library.py` | Direitos e validação | O preenchimento automático aceita somente CC0 e CC BY. NC, ND, SA, licença ausente e valores ambíguos são rejeitados e diagnosticados. Registra título, autor, source/source URL, URL do preview, licença/link, timestamp, gênero, mood/categoria, duração medida por `ffprobe`, SHA-256 e contador de uso. A biblioteca só registra arquivo com extensão suportada, duração admissível e conteúdo não duplicado. |
| `src/curio/audio/selection.py` | Política de preenchimento/seleção | Geração normal lê localmente. Atualização em rede ocorre apenas por `music update` ou quando `auto_fill` está habilitado e a contagem está abaixo do mínimo. Assets com menor `use_count` têm prioridade; empate usa seed estável derivado de projeto/título/roteiro. O metadata do projeto mantém sua seleção em reruns. Contadores avançam após render real. |
| `src/curio/config.py`, `config.example.toml`, `.env.example`, `.gitignore` | Configuração e persistência | Acrescentados limites configuráveis, modo `auto/none/manual`, arquivo manual, ganho, ducking, autopreenchimento e diretório local. Padrões: música 3/6/10 por gênero e SFX 2/5/8 por categoria. Configuração ausente desabilita a nova camada; o exemplo habilita a experiência por gênero. `assets/library/` e segredos permanecem fora do Git. |
| `src/curio/cli.py` | Operação pelo terminal | Adicionados `video-gen music update [--genre] [--kind music|sfx] [--category]`, `music list`, `generate --music-mode auto|none|manual` e `--music-file`. Update lista rejeições de licença, duplicatas e erros; listagem é offline. |
| `src/curio/tui.py` | Operação pela TUI | Configurações → Áudio oferece música automática da biblioteca, nenhuma, arquivo manual e atualização, além de volume e ducking. |
| `src/curio/stages/render.py` | Mixagem e render | `burn_final` mantém o caminho anterior quando não há música. Com música, faz loop/trim, ganho configurável (padrão −30 dB), fade de entrada/saída, sidechain compressor acionado pela narração (attack 400 ms, release 1100 ms) e mix que mantém a voz dominante. Música continua nas pausas; o release evita alternância brusca entre frases. SFX locais substituem somente eventos de inserção já existentes; sem asset, o sintetizador existente segue como fallback. |
| `src/curio/pipeline.py`, `src/curio/stages/render.py` | Transições e cache | Cross-dissolve curto depende de gênero e papel/tipo da cena; revelações recebem dissolve mais longo, mudanças dramáticas aproximam-se de corte seco e o fechamento recebe fade visual/musical. A concatenação usa padding de frame para manter timestamps/duração. A identidade inclui faixa/conteúdo, gênero, ganho, ducking, eventos SFX e transições; `review` só lê o metadata gravado. |
| `src/curio/pipeline.py`, `src/curio/cli.py` | Fluxos e metadata | AI, roteiro pronto, rerender e finalize humano recebem o áudio selecionado. `metadata.json` registra modo, gênero, faixa, origem, licença, duração, caminho, ganho, ducking, SFX, transições e assinatura de render. Preparação de voz humana grava `audio_request`; finalize registra o resultado efetivamente mixado. |
| `README.md` | Documentação principal | Documenta caminhos, fonte/licenças, limites, comandos, configuração, TUI, mix e transições. |
| `tests/test_audio_library.py`, `test_audio_cli.py`, `test_audio_render.py`, `test_pipeline_integration.py` | Regressão | Cobrem limites/dedup/licenças, source oficial autenticado sem token na URL, política sem download, seleção/seed/uso, modos CLI, ducking medido, cross-dissolve, mixagem FFmpeg e integração dos fluxos AI/humano em dois gêneros. |

## 3. Evidências

### Testes automatizados

```text
python -m compileall -q src/curio tests
python -m pytest -q -p no:cacheprovider
581 passed in 75.97s
```

Integrações FFmpeg relevantes incluídas na suíte:

- `test_auto_usa_trilhas_locais_especificas_por_genero`: render real de `people` e `science`, selecionando arquivos de biblioteca distintos por gênero.
- `test_musica_manual_e_transicoes_de_genero_chegam_ao_video`: render AI com faixa manual e transições de `people`.
- `test_finalize_humano_aplica_trilha_salva_no_audio_request`: preparação humana seguida de finalize real com trilha preservada.
- `test_ducking_reduces_music_during_voice_and_returns_in_pause`: mede por componente de frequência que a música reduz durante a fala e retorna na pausa; sem ducking, o nível não sofre essa redução.
- `test_cross_dissolve_preserves_full_scene_duration`: verifica dissolve FFmpeg sem encurtar a timeline.

Os testes de update usam uma fonte fake para controlar conteúdo/licença. Foram exercitados **4 downloads fixture simulados** em testes de preenchimento/validação. Nenhum download externo foi realizado.

### CLI e ambiente real

- `video-gen music list --genre people` reportou `people: música 0/10`, sem rede.
- `video-gen music update --genre people` terminou com código 1 e a mensagem `FREESOUND_API_KEY ausente`; o fallback de vídeo permanece válido. Não há `FREESOUND_API_KEY` no ambiente nem entrada correspondente no `.env` desta execução.
- As integrações de dois gêneros renderizaram vídeos reais com FFmpeg e trilhas locais geradas para teste (tons de frequências distintas), não com música artística baixada. Portanto validam seleção/metadata/mix/cache, não uma avaliação auditiva da direção musical.

## 4. Status vs PRD §19

Não há arquivo PRD no repositório para verificar §19. Para os critérios desta solicitação, biblioteca, limites, deduplicação, licença, seleção determinística e least-used, ausência de rede quando suficiente, modos, mix/ducking, transições, metadata e fluxo humano foram cobertos por testes. Download real de Freesound e avaliação perceptiva com trilhas musicais não foram possíveis sem a chave.

## 5. Limitações

- A única fonte automática implementada é Freesound. A atualização requer chave oficial em `FREESOUND_API_KEY`; sem ela, `update` explica a ausência e o Curio gera o vídeo sem música ou mantém SFX sintético.
- O adapter usa previews HQ MP3, não o download original que exige OAuth2. Licenças fora de CC0/CC BY são deliberadamente recusadas. Arquivo manual é marcado como licença fornecida/não verificada.
- As trilhas de `people`/`science` usadas no teste A/B são fixtures sintéticas; a qualidade musical de uma biblioteca abastecida com assets reais precisa de audição editorial após configurar a chave.
- Nesta etapa só os eventos SFX já existentes são usados: `swish` pode selecionar `paper`; `tap` pode selecionar `soft_impact`. Não foi criado um novo sistema de sound design nem adicionados SFX em toda troca de cena.
- Os perfis de transição são regras pequenas por gênero/papel e palavras de revelação/drama, não um classificador audiovisual complexo.
