# F6 — coleção imutável de tempos de etapa

**Commit:** `11022b2 refactor: make stage timings immutable`  
**Escopo:** substituir a agregação mutável de `stage_times` dentro do pipeline
por um contrato imutável; manter dicts somente na projeção para metadata e
métricas persistidas.  
**Estado:** implementado e validado. F6 fecha a mutação interna comum dos tempos,
mas não completa a fase F de métricas/estado.

## Problema

Após F5, os resultados individuais validavam elapsed, mas o pipeline ainda
agregava os valores em `dict[str, float]`. O pipeline, áudio, preparação humana,
standby e persistência podiam alterar o mesmo objeto; nomes duplicados eram
silenciosamente sobrescritos. A validação do valor não definia dono da coleção
nem garantia um snapshot consistente para serialização.

## Contrato e comportamento

`StageTiming(name, seconds)` representa uma medição nomeada, em segundos,
finita e não negativa. `StageTimings` armazena uma tupla imutável de medições,
rejeita nomes repetidos, acrescenta uma medição com `with_stage()` e combina
coleções distintas com `merged()`. A classe implementa leitura `Mapping` para
consumidores read-only como o callback de progresso.

O pipeline principal e o resultado de áudio compartilham o mesmo contrato.
Preparação humana, standby, metadados e finalize exigem `StageTimings`; nenhum
deles altera um dict recebido. A persistência calcula `finalize` uma única vez
e cria um snapshot com `to_dict()` para `metadata.json` e `metrics.save()`. Os
schemas externos e chaves persistidas não mudaram. O loader/backfill histórico
de métricas continua lendo os dicts já persistidos.

## Arquivos

- `src/curio/stage_timing.py`: `StageTiming`, `StageTimings` e operações
  imutáveis.
- `src/curio/pipeline.py`, `pipeline_audio.py`: agregação central e resultado
  de áudio tipado.
- `pipeline_human_prep.py`, `pipeline_media.py`: contrato aplicado aos modos
  humano e standby.
- `pipeline_metadata.py`, `pipeline_finalize.py`: projeção explícita para
  persistência e medição única de finalize.
- `tests/test_stage_timing.py`, `test_pipeline_audio_contract.py`,
  `test_pipeline_metadata.py`: imutabilidade, merge, nomes duplicados, rejeição
  de dict no resultado de áudio e consistência do snapshot final.

## Falha encontrada durante a migração

O teste de integração do finalize humano detectou que o produtor já incluía a
chave `finalize`, enquanto `persist_run_metadata()` também era o ponto que
atualizava essa medição. Com a regra de nomes únicos, a duplicação deixou de
ser sobrescrita e falhou visivelmente. O produtor passou a entregar a coleção
vazia; a persistência permaneceu como única dona da medição final. O teste de
integração passou após a correção.

## Validação

- Suíte completa: **978 passaram em 200,91 s**.
- Após adicionar a última validação explícita de tipo em preparação humana:
  `tests/test_pipeline_integration.py`, `test_pipeline_metadata.py` e
  `test_stage_timing.py`: **22 passaram em 36,48 s**.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

A execução completa ocorreu imediatamente antes dessa última verificação de
tipo; os testes de integração e contrato foram repetidos depois dela. Nenhuma
geração real foi necessária: a mudança altera a agregação/serialização de
timings, sem alterar pesquisa, aquisição, seleção, render ou conteúdo editorial.

## Limites restantes da fase F

Ainda faltam definições canônicas para todas as métricas, distinguir dado
desconhecido de zero em históricos, cobrir lifecycle timers e suboperações,
perfilar custos por componente e reconciliar seleção visual com render. F6
estabiliza a coleção de tempos em memória; não declara os valores de todos os
estágios completos nem conclui profiling de performance.
