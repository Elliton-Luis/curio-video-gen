# G80 — contrato explícito de entrada do pipeline

**Data:** 2026-10-05  
**Commit:** `5f3eeb9` (`refactor: require explicit pipeline input contract`)  
**Estado:** implementado e validado.

## Problema

Depois de G79, `from-script` separava tópico de título, mas `run_pipeline`
continuava recebendo `idea: str`, além de `provided_script` e `display_title`
como argumentos independentes. O core precisava combinar esses parâmetros
para descobrir o modo de execução e o assunto semântico. CLI, TUI e queue
também chamavam a mesma função com uma string sem significado de campo.

## Mudança

`PipelineInput` agora é o contrato obrigatório de `run_pipeline` e
`_run_pipeline`:

```python
PipelineInput(
    topic="Black holes",
    script="Optional verbatim narration",
    display_title="Optional editorial title",
)
```

O dataclass é congelado. `topic` é obrigatório e não vazio. `script` e
`display_title` são opcionais, mas não podem ser strings vazias quando
informados. Tópico e título são aparados nas bordas; o roteiro mantém todos os
espaços e quebras de linha fornecidos. `run_pipeline(str, ...)` agora falha com
`TypeError`, em vez de adaptar texto semântico implicitamente.

CLI, TUI e queue constroem o contrato ao chamar o pipeline. `run_script_pipeline`
constrói o mesmo contrato a partir do roteiro, tópico e título. A queue mantém o
formato persistido legado `idea` e converte esse campo na fronteira de leitura.
O pipeline passa `topic` para pesquisa, contexto de cenas, slug, métricas,
standby, preparação humana, render e metadata. Apenas o estágio de roteiro
consome `script` e `display_title`.

## Arquivos

- `src/curio/pipeline_input.py`: novo contrato imutável e validação de campos.
- `src/curio/pipeline.py`: core tipado; removidos `provided_script` e
  `display_title` como parâmetros paralelos e removido o adapter `str`.
- `src/curio/cli.py`, `src/curio/tui.py`, `src/curio/queue.py`: migração dos
  chamadores de aplicação.
- Testes de entrada, roteiro/TUI, queue indireta, logs, integração, standby,
  configuração e cache foram migrados para o contrato.

## Compatibilidade e limites

Os comandos CLI/TUI, `from-script`, o schema persistido da queue, projetos
existentes e a preservação verbatim do roteiro continuam compatíveis. A função
Python `run_pipeline` mudou intencionalmente: código externo que passava string
ou os argumentos removidos `provided_script`/`display_title` precisa construir
`PipelineInput`. O repositório não tinha outros chamadores de produção após a
migração.

G80 torna explícitos os dados de entrada; ainda não resolve ownership global
de estado/configuração nem simplifica a orquestração das etapas. Nos caminhos
AI/TUI, o texto escolhido pelo usuário ainda chega como `topic`, com semântica
de assunto. A geração real de mídia não foi repetida nesta fase, pois a mudança
não altera o SearchPlan nem aquisição.

## Validação

- Testes focados de entrada, roteiro/TUI, logs, configuração, integração,
  pesquisa, cache/TTS e standby: **64 passaram** em 143,18 s.
- Suíte completa após a migração: **960 passaram** em 196,40 s.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

O teste que passa string ao entrypoint agora verifica a rejeição explícita.
Não houve chamada a provider, LLM ou serviço pago nesta fase.

## Próxima etapa arquitetural

G80 estabelece um contrato único de entrada no pipeline. Continuam abertas as
fases de ownership do estado, métricas canônicas, simplificação do coordenador,
profile e validações reais multi-domínio já registradas no relatório de
[estado arquitetural](20261005-relatorio-arquitetura-estado-atual.md).
