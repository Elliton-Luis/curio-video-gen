# Relatório — Contexto visual compartilhado e áudio automático

- **Data:** 2026-10-01 06:39 (-03:00)
- **Tipo:** relatorio
- **Escopo:** corrigir ausência de imagens reais via identidade entidade↔scoring e ativar subsistema áudio/música/SFX/transições por padrão.
- **Commit(s):** pendente
- **Origem:** análise `20261001-045242_analise_scores-baixos-tomas-aquino.md` + pedido de ativação do áudio.

## 1. O que foi pedido

Resolver sumiço de imagens (só cards) com base no levantamento de scoring, sem mexer em threshold, prompts LLM, ordem de providers ou fallback de cenas/mídia. Ativar áudio automático por padrão, popular biblioteca `people`/SFX via fluxo oficial e validar de ponta a ponta. Se geração cair em `scenes_source=local` com 0 imagens, reportar como limitação separada.

## 2. O que foi feito e como

| Arquivo / área | Responsabilidade | Decisão e implementação |
|---|---|---|
| `src/curio/stages/visual_context.py` (novo) | Vocabulário compartilhado | `fill_missing_context()` preenche cenas locais sem assunto/consultas com nome da entidade, aliases (incl. inglês via `langlinks` da Wikipedia, sem traduzir nome próprio), consulta ancorada (`<nome> painting/portrait`) e `forbidden` da entidade. Lugares literais na narração viram assunto local. Narração e cenas da IA nunca são reescritas. |
| `src/curio/stages/visual_context.py` | Cenas LLM com assunto da entidade | Cenas com assunto idêntico à entidade (PT ou EN) ganham aliases + consulta ancorada, sem tocar assunto/consultas. Assunto genérico de pessoa (`man`, `person`…) sem nomes rivais na narração é ancorado à entidade. Assuntos de outras cenas ficam intactos. |
| `src/curio/stages/scoring.py` | Gate de identidade | Quando há aliases, exige nome completo no título (cobre homônimos tipo Melchora Aquino); acerto integral vale cobertura 1.0. Sem aliases, fórmula inalterada. Threshold 34 intacto. |
| `src/curio/stages/scenes.py`, `pipeline.py` | Fio do contexto | Campo `subject_aliases` com roundtrip em `chapters.json`; pipeline aplica contexto após cenas e refaz mídia quando há mudança. |
| `src/curio/config.py`, `config.toml` | Áudio padrão | `audio_enabled=True` por padrão; `config.toml` com `[audio] transitions=auto`, `[music] mode=auto gain_db=-30 ducking=true auto_fill=true`, `[sfx] library_enabled=true auto_fill=true`. Sem segredos no TOML. |
| `src/curio/audio/library.py` | Consultas Freesound | Queries people/SFX simplificadas para termos com retorno; filtro prévio por duração informada evita downloads fadados ao descarte. Só CC0/CC BY. |
| `src/curio/audio/selection.py`, `pipeline.py` | Seleção e créditos | Gênero neutro `people` quando ausente; SFX não some quando eventos mudam; créditos CC BY no metadata. |
| `src/curio/cli.py` | Doctor | Mostra estado do áudio e contagens da biblioteca por gênero/categoria; corrige chamada `clip_status`. |
| `tests/test_visual_context.py` | Regressão | 10 testes: alias autoritativo, lugar explícito, ordem religiosa, inserção real, cenas estruturadas, assunto EN/PT, pessoa genérica e nome rival. |
| `README.md`, `docs/README.md` | Documentação | Áudio padrão documentado; índice atualizado. |

## 3. Evidências (comandos + números reais, nunca inventados)

Métricas consultadas primeiro: execução `20261001-040048` (240,35 s; mídia 79,17 s; 169 normalizados; 132 score rejects; 0 downloads; 11 sintéticos).

Biblioteca via fluxo oficial (`music update`, só CC0/CC BY, NC/ND/SA recusados):
- `music update --genre people`: 0 → 6 (4 licenças recusadas);
- SFX `paper`: 2 → 5; SFX `soft_impact`: 1 → 5 (durações fora do limite filtradas antes do download).

Doctor (`CURIO_GENRE=people`):
- `[OK] Áudio — music=auto, transitions=auto, gain=-30dB, ducking=True`;
- `[OK] Biblioteca people — música 6; SFX/paper 5; SFX/soft_impact 5`.

Geração real curta (`--duration 30`, slug `validacao-contexto-audio-5`):
- roteiro Groq `openai/gpt-oss-20b`; cenas `groq` (não local);
- cena 1 (assunto genérico `person` ancorado): 3 pinturas reais de Tomás de Aquino no Wikimedia, score 75, 3 downloads;
- cenas 2–3 (`birthplace`, `teology`, sem âncora segura): cards;
- `audio.music.mode=auto` com faixa CC BY + crédito; `transitions.mode=auto` com `[0.34, 0.46]`; sem aviso de biblioteca vazia;
- `verify --slug`: 8/8; MP4 1080x1920 com áudio.

Geração `validacao-contexto-audio-6`: 2/3 cenas com asset real Wikimedia, 1 card.

Suíte: `python -m pytest -q -p no:cacheprovider` → **626 passed**. `compileall` e `git diff --check` passam.

## 4. Status vs PRD §19

Sem PRD no repositório. Critérios do pedido: imagens reais voltaram nas cenas ancoradas à entidade; áudio automático validado com faixa, transições e biblioteca; SFX de biblioteca depende de inserção visual (0 inserções nas validações → `sfx.mode=none`, por desenho, não por falha).

## 5. Limitações → analise/melhoria

- Cenas LLM com assunto vago não-entidade (`birthplace`, `teology`) continuam no scoring lexical PT×EN e podem zerar; qualidade do assunto vem do prompt LLM (fora de escopo).
- Inserção/SFX sobre empate de scores não ocorre (regra exige foto estritamente mais precisa); SFX de biblioteca só substitui eventos já planejados.
- `_language_alias` faz 1 chamada Wikipedia por execução quando há cenas sem aliases.
- Deduplicação de `asset_id` segue sem namespace de provider (não comprovado como causa; não mexido).
