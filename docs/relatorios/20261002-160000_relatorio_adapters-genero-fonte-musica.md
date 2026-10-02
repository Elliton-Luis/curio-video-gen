# Relatório — Adapters de gênero e fontes especializadas

- **Data:** 2026-10-02 16:00 (local)
- **Tipo:** relatorio
- **Escopo:** consolidar políticas de gênero em `GenreAdapter` e resolver fontes por registro
- **Commit(s):** `beb0653 refactor: centralize genre adapters and source registry`
- **Origem:** `docs/analises/20261002-131932_analise_refatoracao-codigo-morto.md`

## 1. O que foi pedido

Um pipeline único. Adapter declarativo fornece direção editorial, pesquisa,
fontes, mídia, transição, música e SFX. Infraestrutura faz rede, cache,
LLM, download e render. Cada gênero declara ao menos uma fonte especialista.

## 2. O que foi feito

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `stages/editorial.py` | `GenreAdapter` imutável e seis adapters declarativos | Armazena fontes, genéricos, prioridade de provedores, continuidade visual, mood, música, transição e SFX. Nenhum I/O. |
| `stages/research_sources.py` | Registry de fontes por nome | Implementa conectores sem chave para Wikidata, Library of Congress, NASA Images, PubMed, FBI Wanted, Perseus e Logeion; reutiliza bundle Wiktionary/Logeion/Perseus. |
| `stages/research.py` | Resolver fontes declaradas | Tenta fontes especializadas antes das gerais; todos passam pelo mesmo gate de relevância. Reserva uma vaga de fonte geral quando limite permite. |
| `stages/visual.py` | Executar política visual do adapter | Genéricos e prioridade de provedores vêm do adapter; fallback antigo continua para `genre` vazio. |
| `stages/visual_context.py` | Contexto e continuidade visual | Meio histórico (`painting`) vem de adapter, não de lista de gêneros. |
| `pipeline.py` | Aplicar ritmo/transições e cadeia etimológica | Duração, tipo de transição e consumo visual leem adapter. A lógica não contém `if genre == "etymology"`. |
| `audio/library.py` | Biblioteca musical | Gêneros derive do registry; query/mood vêm do adapter. |
| `audio/selection.py` | Seleção SFX | Categorias permitidas vêm do adapter; seleção e downloads ficam na infraestrutura. |

Fontes declaradas: história (`loc`, `perseus`); etimologia (`wiktionary`,
`logeion`, `perseus`); mitologia (`perseus`, `logeion`); mistério
(`fbi_wanted`); ciência (`nasa`, `pubmed`); pessoas (`wikidata`). Pesquisa
substituem fontes gerais. Fonte precisa passar relevância da entidade para
entrar no pack de grounding.

O adapter não chama API nem LLM. Registry e conectores ficam na camada de
pesquisa; dados de mídia/áudio são executados por seus serviços.

## 3. Evidências

- `python3 -m pytest tests/test_editorial.py tests/test_audio_library.py tests/test_pipeline_integration.py tests/test_research.py tests/test_etymology_sources.py tests/test_visual_context.py -q` — **156 passed** antes do teste de contrato novo.
- `python3 -m pytest tests/ -q` — **721 passed** após mudança.
- `test_adapters_declaram_fontes_visual_musica_e_transicoes` prova que cada adapter tem fonte registrada, música, transição e queries genéricas.
- Teste de RAG etimológico prova que fontes Wiktionary e Wikipedia coexistem no prompt.

## 4. Status vs PRD §19

Um pipeline único preservado. Gêneros declaram política; serviços comuns executam. Conectores usam APIs públicas, sem chave paga.

## 5. Limitações

- APIs externas podem retornar zero resultados, exigir rede ou recusar User-Agent; falha fica best-effort e pesquisa geral continua.
- Perseus/Logeion podem oferecer referência com trecho vazio quando o endpoint público não entrega conteúdo do verbete; URL é preservada, mas gate impede trecho vazio de fundamentar roteiro.
- Fontes genéricas de domínio (ex. FBI Wanted) podem ser irrelevantes a um tema concreto e são rejeitadas pelo gate. Adaptador declara fonte candidata, não força aceitação.
- Etapas 3/5 continuam: extração dos módulos gigantes e concorrência só vêm após estabilização estrutural.
