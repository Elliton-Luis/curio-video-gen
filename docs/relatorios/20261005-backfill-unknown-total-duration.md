# F7 — duração total desconhecida no backfill

**Commit:** `254f48f fix: preserve unknown backfill duration`  
**Motivação:** impedir o backfill de apresentar como duração total a soma de
timers que podem se sobrepor ou estar incompletos.  
**Estado:** implementado e validado.

## Causa

`metrics.backfill_from_metadata()` usava `processing_time_seconds` quando
existia; caso contrário somava `stage_times`. Isso não representa duração de
parede garantida: os timers não têm contrato de não sobreposição e podem medir
intervalos inclusivos. No áudio, por exemplo, a medição de legendas parte do
mesmo relógio inicial da etapa de TTS. Assim, metadados antigos sem duração
total explícita podiam receber uma duração fabricada.

## Mudança

O backfill agora valida `processing_time_seconds` com o mesmo contrato de
elapsed usado pelas etapas. Um valor explícito, numérico, finito e não negativo
é preservado. Se estiver ausente ou inválido, `time.total_seconds` e
`time.started_at` ficam `null`; nenhum total é inferido pela soma de etapas.
`finished_at` continua derivado de `created_at` quando essa data é válida. Se a
data ou a subtração temporal não puder ser representada, os campos temporais
derivados ficam `null`.

O schema JSON mantém os mesmos campos. CLI e consumidores recebem `null` onde a
duração não é recuperável, em vez de um zero ou total inventado.

## Testes e validação

Foram adicionados casos que provam que timers aparentemente sobrepostos não
são somados, e que um total explícito continua sendo usado para derivar o
início. Testes focados (`test_media_artifacts.py` e
`test_media_metric_units.py`): **17 passaram**. A suíte completa passou com
**980 testes em 187,65 s**. Após o último tratamento de overflow, os testes
focados foram repetidos; `compileall` e `git diff --check` passaram.

## Limites restantes

F7 não define uma matriz completa de campos desconhecidos em todo o backfill.
Outras métricas precisam ser auditadas para garantir que defaults não
transformem ausência em zero e que as definições live/backfill sejam únicas.
