# Fluxo editorial modular — validação

## Implementação

Novo comando opcional `agent-flow`, com contrato JSON versão 1. Agentes fornecem pesquisa, roteiro, cenas, intenção musical e escolhas de mídia. Curio executa aquisição e render pelos componentes existentes. Não há dependência de SDK ou fornecedor de agente.

O fluxo passa por planejamento, revisão de mídia, revisão do render e aprovação. Correções retornam à revisão; mudanças no roteiro/cenas arquivam artefatos derivados. Aprovação exige avaliação por cena, sete critérios editoriais e verificações técnicas, vinculadas aos hashes dos arquivos. O processo não interpreta sucesso de render como sucesso editorial.

Arquivos desta alteração: `src/curio/agent_flow.py`, integração em `src/curio/cli.py`, `tests/test_agent_flow.py`, `docs/agent-flow.md` e README. Alterações anteriores de mídia e áudio foram preservadas.

## Evidência prática

Execução isolada: `output/agent-flow-proof/people/aristotle-agent/`, baseada no projeto real anterior de Aristóteles. Reutilizou pesquisa, narração e candidatos reais salvos; esta validação não fez novas buscas externas.

1. `init`: retornou código 3, estado `awaiting_plan`.
2. Plano editorial preenchido; intenção instrumental e trilha local Freesound `510806`, CC BY, declaradas com fonte e licença.
3. `advance`: retornou código 3, estado `awaiting_media`.
4. Escolhas explícitas por cena; `advance` renderizou 61,4 segundos, cinco imagens reais e zero cartões. Retornou código 3, estado `awaiting_render_review`.
5. Inspeção dos frames identificou rosto cortado na abertura. Também identificou divergência entre promessa do título e narrativa biográfica. Feedback registrou rejeição; estado `needs_revision`.
6. `revise`, substituição das imagens das cenas 1 e 5 e novo `advance`: segundo render com 61,4 segundos, cinco imagens reais, zero cartões e retorno obrigatório a `awaiting_render_review`.

O segundo render mostra identificação visual mais nítida na abertura. O projeto permanece pendente de avaliação editorial integral e correção da promessa do título. Não foi aprovado automaticamente nem se declara pronto para publicação. A revisão prática documentada aqui foi de frames e metadados; não se declara audição integral do vídeo.

Evidências:

- `agent_flow/state.json`: histórico persistente das duas iterações.
- `agent_flow/evidence-000/feedback.json`: rejeição documentada.
- `agent_flow/evidence-000/request.json` e `evidence-001/request.json`: frames e verificações técnicas de cada render.
- `agent_flow/render-proof.jpg` e `render-proof-iteration-1.jpg`: comparação visual.
- `media_review/review_summary.json`: escolhas realmente usadas.
- `render/final.mp4`: segundo render.

As duas iterações passaram verificação de streams, resolução, legendas e decodificação completa por FFmpeg com `-xerror`. Isso valida a integração técnica, sem substituir a revisão editorial.

## Regressões

22 testes novos cobrem contrato independente de provedor, etapas editoriais obrigatórias, rejeição e nova revisão, identidade do render, alterações/remoção de arquivos, assets externos ao projeto, revisão incompleta, fallback explícito, preservação de arquivos, invalidação do áudio após mudança do roteiro, CLI opcional e trilha realmente usada com atribuição.

Um teste de projeto novo executa seleção local, timeline, legendas e FFmpeg reais; pesquisa interna, planejamento e chamada LLM são bloqueados por fixtures que falham se invocados. TTS e aquisição de candidatos são fixtures nesse teste.

A suíte completa foi executada com duas exclusões já conhecidas do ambiente: teste que depende de rede externa sem fixture e teste que pressupõe encoder Intel Arc ausente. Resultado: **1100 testes passaram; 2 foram excluídos**, em 204,72 segundos. Log em `output/agent-flow-proof/full-tests.txt`.
