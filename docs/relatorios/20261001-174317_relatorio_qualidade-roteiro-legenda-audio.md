# Relatório — roteiro, highlight temporal e referência de áudio

- **Data:** 2026-10-01 17:43 -0300
- **Tipo:** relatorio
- **Escopo:** direção narrativa interna, highlight ASS por WordBoundary e compensação de latência do limiter.
- **Commit(s):** commit desta entrega (`fix: align subtitle highlights with spoken words`)
- **Origem:** pedido de recuperação de qualidade final em roteiro, legendas e áudio.

## 1. O que foi pedido

Investigar regressões editoriais, destacar exatamente a palavra pronunciada e verificar áudio final, preservando roteiro fornecido e o restante do pipeline.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `stages/nvidia.py` | Roteiro interno | Corrige regras existentes de hook/CTA, distingue pergunta factual de convite de opinião, preserva o payoff do gênero e explicita limites de causalidade/hipóteses/estatísticas. Não acrescenta provider nem altera Roteiro Pronto. |
| `stages/subs.py` | Highlight | Mantém agrupamento de leitura no SRT; ASS usa eventos por palavra nos timestamps reais, destacando cada palavra do grupo durante seu boundary. Pausas internas mantêm grupo neutro. Sem offset nem duração uniforme. |
| `pipeline.py` | Diagnóstico | Log distingue timing da legenda do timing das cenas: divergência de tokenização pode causar cenas proporcionais sem invalidar boundaries da legenda. |
| `stages/render.py` | Referência temporal | `alimiter` usa `latency=1`, compensando o lookahead de 5 ms. Ganhos, ducking e fades existentes permanecem. |
| `tests/test_active_word.py` | Regressão | Testa palavra curta, acentos, pontuação, número, primeira/última palavra e troca de grupo; verifica request de geração com fontes e gênero. |
| `tests/test_audio_render.py` | Áudio | Janela de medição de pausa termina antes do fade final; evita comparar ducking com atenuação de fade. |

### Causas encontradas

- Commit `701d26f` removeu o CTA obrigatório dos prompts e o closer local. A regra “toda pergunta respondida” também conflita com pergunta final de opinião. Hook conversado continuava presente, mas permitia preâmbulos como “Você já se perguntou”.
- `cues_from_words` escolhia a palavra mais longa e a destacava durante o grupo inteiro. Timestamps corretos chegavam do Edge, mas não controlavam a palavra colorida.
- Exemplo antigo: “Você” começa em 0,09 s; “perguntou” começa em 0,58 s. O grupo podia destacar “perguntou” já em 0,09 s.
- Limiter do mix usa ataque/lookahead de 5 ms sem compensação explícita. Não há evidência de clipping que justifique mudar os níveis.

## 3. Evidências

- Métrica recente consultada: `metrics/20261001-171949_20261001_como-a-peste-negra-mudou-a-euro.json`: roteiro Groq, 1532 caracteres; áudio 87,31 s; vídeo 87 s; 51 cues WordBoundary; TTS 8,65 s; render 81,53 s.
- Roteiro anterior da Peste Negra: abertura repete o título; inclui várias estatísticas e datas; termina com resumo histórico sem CTA.
- Testes completos: `python -m pytest -q` — **662 passed** antes dos ajustes finais de redação dos prompts.
- Após os ajustes finais: `python -m pytest -q tests/test_active_word.py tests/test_audio_render.py tests/test_tts_coverage.py tests/test_shorts60.py tests/test_tui_script_input.py` — **31 passed**.
- Validação real em `/tmp/opencode/`: geração Groq com fontes reais; Edge TTS; render CPU com ASS e música local; MP4 de **5,52 s**.
- Boundaries reais: `O` 0,09–0,16; `império` 0,17–0,54; `romano` 0,55–0,89; `476` 2,02–3,26; `história` 4,43–4,82 s.
- Frame inspecionado em 0,65 s destaca `romano`; frame em 2,5 s destaca `476`. Eventos ASS usam esses intervalos diretamente.
- `volumedetect`: voz curta média −24,3 dB, pico −7,0 dB; mix AAC média −23,7 dB, pico −6,7 dB. MP4 recente da Peste Negra: média −23,5 dB, pico −6,1 dB. Nenhum pico a 0 dBFS nas amostras medidas.
- Teste FFmpeg de ducking verifica voz dominante e recuperação da música em pausa sem medir o fade final.

### Inspeção editorial real — NÃO aprovado integralmente

As gerações reais recuperaram hook e pergunta final, mas ainda produziram extrapolações factuais. Uma geração transferiu números mundiais para Europa; outra atribuiu mecanização e transição ao capitalismo à peste sem apoio no pack. Uma revisão experimental por segunda chamada não resolveu e foi removida, evitando custo recorrente inútil.

- **Hook nos primeiros segundos:** sim no exemplo final, “Um terço da Europa desapareceu em menos de três anos”.
- **Fala ou livro:** mistura; início direto, mas explicação ainda formal.
- **Progressão:** sim, perda de trabalhadores, resposta portuguesa, consequências.
- **Payoff:** presente, porém parte das consequências não está sustentada.
- **CTA natural:** pergunta temática presente; convite direto a comentar não consistente.
- **Informação desnecessária:** ainda há datas e conclusões periféricas.
- **Grounding preservado:** instruções e fontes permanecem; obediência factual do modelo NÃO passou na inspeção real.

## 4. Status vs PRD §19

Highlight e referência temporal verificados em render real. Não considero recuperação editorial concluída: a geração real falhou no critério factual apesar dos testes. Roteiro Pronto continua literal. Busca/seleção/scoring de mídia e visual beats não foram alterados.

## 5. Limitações e continuidade

- Ainda é necessário resolver a extrapolação do modelo antes de aprovar qualidade de roteiro; aumentar prompts ou repetir calls não demonstrou resolver.
- Inspeção de áudio é instrumental (níveis, duração, teste de ducking), não avaliação auditiva humana. Frames do highlight foram inspecionados visualmente.
- Artefatos de validação ficam em `/tmp/opencode/quality-*`, fora do Git. O MP4 do usuário não foi sobrescrito.
