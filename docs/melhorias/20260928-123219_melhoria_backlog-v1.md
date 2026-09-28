# Melhorias — backlog V1 proposto

- **Data:** 2026-09-28 12:32 (UTC-3)
- **Tipo:** melhoria
- **Origem:** `docs/analises/20260928-123219_analise_estado-atual-mvp.md`
- **Regra:** cada item implementado gera seu próprio doc timestamped em `docs/`; nenhum item pode quebrar o `generate` atual sem `--force`.

## Prioridade 1 — voz e credibilidade (atacam os riscos altos)

1. **Provedor TTS Piper local** (PRD §8)
   Implementar `PiperTTS` em `stages/tts.py` + voz pt-BR downloadable + flag
   `--tts piper`. Manter espeak-ng como fallback. Critério: mesmo roteiro,
   MOS informal melhor, duração ainda ~45 s.
2. **Ampliar base curada para 10 temas** (PRD §6–7)
   Salário e vikings existem; adicionar 8 temas de etimologia/mitos com a
   mesma disciplina editorial (cada afirmação revisável, sem viral-fake).
   Cada novo tema entra com fonte anotada em comentário no código — ponte
   para o estágio PESQUISA futuro.
3. **Validador editorial automático**
   Checagem simples no `generate`: proíbe lista de aberturas clickbait e
   afirmações absolutas sem qualificador ("sempre", "nunca", "cientistas
   provaram"). Falha com mensagem, não silenciosamente.

## Prioridade 2 — qualidade percebida

4. **Legenda proporcional por frase, não por bloco fixo** (PRD §9)
   Quebrar cues em fronteiras de pontuação antes de aplicar o limite de
   42 chars; reduz o erro de sincronia percebido sem precisar de transcrição.
5. **2–3 templates visuais alternados** (PRD §10)
   Paletas/posições de título configuráveis por `--template`; metadados
   registram qual foi usado (rastreabilidade para descobrir o que retém).
6. **`FontSize` da legenda escalado pela altura do vídeo** (bug latente §4 da análise)
   `font_size = base * height/1920`.

## Prioridade 3 — engenharia e escala

7. **Testes de fumaça** (`scripts/smoke.sh` + asserts em Python stdlib, sem pytest)
   Roteiro gera N chars; SRT cobre ~100% da duração; MP4 tem vídeo+áudio e
   `height == 2*width/…` (9:16). Roda em <60 s.
8. **Fila de ideias** (`video-gen batch ideias.txt`) (PRD §21-V2)
   Sequencial, um vídeo por vez, com `metadata.json` agregado
   (`batch.json`: tempo total, falhas, retomada do ponto de falha).
9. **Documentar provedores TTS opcionais no `install.sh`** (piper/edge-tts)
   Detecção + instruções por distro, sem tornar obrigatório.

## Explicitamente NÃO fazer (PRD §20)

Web UI, banco, auth, publicação automática, analytics, vídeo por IA, editor
visual. Reavaliar só após 20+ vídeos publicados com métricas reais de retenção.
