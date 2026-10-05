# G70 — candidatos ranqueados tipados na seleção visual

**Commit:** `dd19b24` (`refactor: type ranked media selection candidates`)
**Estado:** concluída; migração local, não encerra a refatoração da etapa de mídia.

## Problema e causa

Depois de G69, a coleta e a avaliação já produziam `Candidate` e
`CandidateEvaluation`, mas `visual.py` os achatava em rows mutáveis antes do
passe de CLIP e de `SelectionPool`. Score CLIP, asset baixado e estado de reuso
ficavam espalhados pelo dict. Isso permitia que `SelectionPool` aceitasse
qualquer mapping, embora dependesse de campos e invariantes específicos.

A conversão também revelou uma dependência acidental de aliasing: a row guardada
para auditoria e a row usada pela seleção eram o mesmo objeto. Quando o download
posterior rejeitava dimensões, a seleção recebia `rejection_reason`, mas a
avaliação original não. A auditoria passava a indicar `not_selected` em vez de
`rejected`.

## Mudança

`RankedSelectionCandidate` combina uma `CandidateEvaluation` aceita com o
`MediaAssetSnapshot` vigente no lifecycle de shortlist. O snapshot pode incluir
caminho local depois do download para CLIP. `CandidateEvaluation.with_clip_score`
retorna uma nova avaliação com score e evidência atualizados; essa avaliação é a
fonte única do score CLIP. A função `prepare_selection_pool` separa apenas
`RankedSelectionCandidate`, e `SelectionPool` valida tuplas desse tipo.

`visual.py` mantém os candidatos tipados durante o passe CLIP, ordenação e
separação fresh/reused. Projeta-os para rows JSON ao entrar no lifecycle
posterior que ainda é mutável. Rejeições de aquisição carregam a identidade do
candidato; `candidate_audit_rows` associa explicitamente essa rejeição à linha
avaliada. Falha de download também passa a aparecer como rejeição auditável.

A mudança preserva ordem e critérios de seleção, peso CLIP, gates semânticos,
thresholds, providers, política de reuso e schema de persistência. Não inclui
nova estratégia de pesquisa nem geração real.

## Arquivos

- `src/curio/stages/media_contracts.py`
- `src/curio/stages/media_selection.py`
- `src/curio/stages/visual.py`
- `src/curio/stages/visual_audit.py`
- `tests/test_media_selection.py`

## Validação

- Bateria focada de contratos, seleção, aquisição visual e auditoria: **89
  passaram**.
- Suíte ampla: **937 passaram, 1 deselecionado** por dependência da API real da
  Wikipédia que retornou HTTP 429, em **179,65 s**. Essa execução antecedeu a
  inclusão do último teste unitário que verifica a rejeição de rows dict no
  `SelectionPool`; após ele, a bateria focada passou com 89 testes.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.
- Nenhuma geração real nem inspeção visual foi executada nesta fase.

## Limite atual

Após o pool, `visual.py` ainda projeta candidatos em dicts para o lifecycle de
download, hash/deduplicação, escolha, fallback e persistência. Esse ciclo
continua acoplado ao coordenador e precisa de estados explícitos antes de outra
migração. Também permanecem pendentes os testes de aquisição real e a inspeção
editorial dos assets. O contrato G70 não certifica diversidade, pertinência de
queries ou qualidade visual do vídeo final.
