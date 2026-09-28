# Análise — estado atual do MVP

- **Data:** 2026-09-28 12:32 (UTC-3)
- **Tipo:** analise
- **Alvo:** commit `7a18ec6` (MVP inicial, 19 arquivos, ~1090 linhas)
- **Método:** leitura do código + resultado do teste end-to-end + confronto com o PRD

## 1. Veredito

O MVP **prova a tese do PRD §24**: uma ideia virou um vídeo publicável
(46,77 s, 1080×1920, legendado) em 17 s, sem intervenção manual e a custo
zero. A arquitetura está simples e desacoplada o suficiente para evoluir sem
reescrita. Os gaps abaixo são, em maioria, **adiamentos deliberados** do PRD —
não defeitos.

## 2. Pontos fortes

1. **Zero dependências pip** — só stdlib; `install.sh` tem fallback sem rede.
2. **Hardware nunca assumido** (`ffmpeg.py`): prova encode real de 1 frame
   antes de escolher VA-API; QSV e CPU como quedas d'água.
3. **Reuso de artefatos** funciona (0,25 s na reexecução) — base para fila/lote (V2).
4. **Editorial levado a sério**: roteiro curado corrige mito em vez de repeti-lo.
5. **Erros acionáveis** na CLI (etapa + motivo provável + como retomar).

## 3. Gaps vs. PRD (ordenados por risco)

| # | Gap | Seção PRD | Risco |
|---|---|---|---|
| 1 | Voz espeak-ng robótica; retenção em redes curtas depende muito de voz | §8 | **Alto** — maior ameaça à meta comercial (§23) |
| 2 | Sem pesquisa/fontes; afirmações curadas à mão não escalam e o template genérico é raso | §7 | **Alto** — fere o princípio editorial em escala |
| 3 | Legendas proporcionais, não alinhadas por palavra; erro cresce em frases longas | §9 | Médio |
| 4 | Visual único (gradiente + título); sem variação entre vídeos do mesmo canal | §10 | Médio |
| 5 | Sem testes automatizados; regressão só aparece no teste manual | §22 | Médio |
| 6 | Um vídeo por execução; sem fila/lote (meta 20/dia é futura, mas o caminho deve ser validado) | §12, §21 | Médio-baixo |
| 7 | `output/` gitignored: artefatos de teste não versionados; reprodução depende de reexecução | §15 | Baixo |
| 8 | Sem cache de LLM/TTS entre ideias nem `processing_time` agregado | §12, §22 | Baixo |

## 4. Riscos técnicos específicos

- **Piper/edge-tts ausentes**: `available_providers()` só lista espeak-ng aqui;
  trocar a voz exige instalar binários — documentar no `install.sh` (virou item de backlog).
- **Filtro `gradients`**: há fallback para `color`, mas se o comportamento da
  source mudar entre versões do FFmpeg, o visual muda silenciosamente.
- **`force_style` do libass**: `FontSize=64` calibrado para 1080p; se a
  resolução for configurada para outro valor, a legenda desproporciona
  (tamanho deveria escalar com a altura).
- **Velocidade TTS corrigida uma única vez**: textos muito fora da meta
  (>±15% após correção) passam batido; aceitar ou iterar é decisão editorial.

## 5. O que NÃO mexer agora

Interface web, banco de dados, publicação automática, analytics, geração de
vídeo por IA — todos fora do escopo pelo PRD §20, e a análise confirma: nenhum
deles é pré-requisito para validar retenção dos vídeos atuais.
