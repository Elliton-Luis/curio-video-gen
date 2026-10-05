# G77 — continuar a busca contextual após falha de aquisição

**Commit:** `111995f` (`fix: continue media search after acquisition failure`)

**Estado:** concluída e testada; não equivale a uma validação real de acervo.

## Causa confirmada

Em `visual.py`, queries genéricas/contextuais só eram executadas no ramo em que
nenhum candidato específico passava o threshold. O ramo era escolhido antes do
download. Assim, um candidato podia passar scoring e falhar download ou
validação dimensional, mas a busca terminava em fallback sintético ou reuso sem
consultar as representações contextuais planejadas.

Isso contradizia o próprio fluxo: o comentário dizia que score não comprova
asset utilizável, porém a decisão de executar a próxima tier ainda se baseava
somente no score.

## Mudança

Queries específicas continuam sendo avaliadas e adquiridas primeiro. Se não
preencherem `max_images`, o diretor coleta e avalia as queries contextuais
genéricas planejadas, aplica o mesmo CLIP opcional e os mesmos gates/scoring e
tenta adquirir o que falta. Só depois segue para visual sintético e reuso.
Assets de tiers diferentes mantêm ordem sequencial estável, incluindo o índice
de seleção ao completar slots.

A coleta acumula auditoria no mesmo `SceneCandidateCollector`; a decisão final
registra queries/provedores realmente consultados, rejeições de candidatos
específicos e o asset contextual vencedor. A busca continua sujeita ao limite
global de candidatos; queries não executadas por esse limite continuam sendo
indicadas pela auditoria.

## Regressões

- Candidato específico passa scoring, falha no download; query contextual é
  consultada e seu asset elegível vence antes do fallback sintético.
- Candidato específico selecionado ocupa o primeiro slot; uma query contextual
  preenche o slot restante com ordem de seleção contígua.
- A auditoria aponta ambas as queries como consultadas e marca o candidato
  específico com falha de aquisição como rejeitado.

## Arquivos

- `src/curio/stages/visual.py`: transição para a tier contextual baseada em
  quantos assets foram adquiridos, com CLIP reaproveitado entre tiers.
- `src/curio/stages/media_candidate_acquisition.py`: offset validado de ordem
  de seleção ao completar assets em uma segunda tentativa.
- `tests/test_visual_director.py`: duas regressões do comportamento.

## Validação

- **90 testes focados** em direção visual, busca/auditoria, seleção e pipeline.
- **946 testes passaram; 1 foi desmarcado** por HTTP 429 da API real da
  Wikipédia, em **197,04 s** (`pytest -q -k 'not standby_sem_imagens'`).
- `python -m compileall -q src tests` e `git diff --check` passaram.
- Nenhuma geração real foi executada; esta evidência valida o fluxo determinístico
  com providers/downloads simulados, não a disponibilidade dos acervos.

## Limites preservados

Thresholds, gates, aliases, providers e ordem das representações não foram
afrouxados. A busca genérica continua sujeita ao teto global de candidatos; se
ele impedir execução, a auditoria registra a query como não executada e a cena
não deve ser descrita como busca completamente esgotada.
