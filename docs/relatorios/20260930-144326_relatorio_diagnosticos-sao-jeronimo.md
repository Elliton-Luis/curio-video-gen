# Relatório — Diagnósticos e observabilidade no caso São Jerônimo

- **Data:** 2026-09-30 14:43 (-03:00)
- **Tipo:** relatorio
- **Escopo:** contexto de entidade religiosa, grounding, providers de mídia, reuso, timeout LLM e validação do caso São Jerônimo.
- **Commit(s):** implementação: `9324ba9`, `0a8d67b`, `88b0b78`, `14dc589`, `89f2d44`, `aa15ba1`, `5f2d7f6`, `bc5fec2`, `22b98f3`; documentação: `6d200cc` (`docs: record São Jerônimo diagnostics and validation`).
- **Origem:** prompt de correções após a execução de História de Pessoas: São Jerônimo.

## 1. O que foi pedido

Preservar o resultado editorial/visual existente e corrigir problemas concretos de contexto, diagnóstico de afirmações sem fonte, aviso repetido de provider ausente, observabilidade de downloads, identificação de reuso e investigação do timeout NVIDIA. O fallback visual por cards e o fallback entre providers deveriam continuar funcionando.

## 2. O que foi feito e como

| Arquivo / área | Responsabilidade | Decisão e implementação |
|---|---|---|
| `src/curio/stages/entity.py`, `script.py`, `nvidia.py` | Contexto editorial da entidade | O contexto estruturado existente (`TargetEntity`: nome, aliases, termos distintivos e homônimos) segue até o prompt do NIM. Não foi criada outra fonte de verdade nem foi feito replace textual do nome. A entidade pesquisada permanece São Jerônimo; o texto pode variar contextualmente. |
| `src/curio/pipeline.py`, `src/curio/stages/research.py` | Diagnóstico de grounding | O gate de `verify_grounding` e seus dados não foram enfraquecidos. O aviso passou a mostrar a afirmação/trecho, causa provável e fontes avaliadas. `_print_grounding_warning` centraliza a saída testável e retorna o resumo guardado em `warnings`; a exibição mantém limite de oito afirmações. |
| `src/curio/media/providers.py` | Providers indisponíveis | A indisponibilidade por configuração é memorizada durante o processo: a chave ausente gera uma mensagem por provider, sem reconstrução/tentativa por cena. A cascata dos demais providers não muda. |
| `src/curio/metrics.py`, `src/curio/media/cache.py`, `src/curio/stages/visual.py`, `src/curio/pipeline.py` | Diagnóstico de download | Métricas por provider contam candidatos, tentativas, sucessos, falhas, HTTP 403 e outros erros. O resumo é serializado em `metadata.json` sob `provider_downloads`; cache hit não é contabilizado como download. |
| `src/curio/stages/visual.py` | Reutilização de asset | Reutilizações continuam permitidas. A anotação `reuse` registra asset, título, provider, cena da primeira ocorrência, cena atual e motivo `same_top_match`; não presume intenção temática. O fallback de cena sem mídia mantém `reused_from`. |
| `src/curio/stages/visual.py`, `src/curio/stages/visuals.py` | Fallback visual | Não alterado nesta entrega. A falta de foto continua podendo gerar diagrama/card semântico; o caso curto produziu `Card — Jerome's birthplace`. |
| `src/curio/config.py`, `src/curio/stages/nvidia.py`, `src/curio/stages/script.py` | Timeout do NIM | A investigação confirmou um único `urlopen(timeout=...)` de socket, não limites separados de conexão, leitura e geração. O teto passa a ser configurável por `[nvidia].timeout_max` / `NVIDIA_TIMEOUT_MAX`, com padrão inalterado em 15 s e suporte a teto por provider. Não foi escolhido valor novo. |
| `config.example.toml`, `.env.example`, `README.md` | Documentação de configuração | Removida a afirmação obsoleta de teto rígido e documentado o teto configurável, incluindo a distinção entre timeout de socket e orçamento total de geração. |
| `tests/test_entity_context.py`, `tests/test_grounding_diag.py`, `tests/test_media_diag.py`, `tests/test_llm_timeout.py` | Cobertura de regressão | Cobertos contexto estruturado da entidade, detecção e conteúdo do aviso, deduplicação, métricas 403/fallback, reuso permitido, timeout configurável e rotação de fallback. O teste da rotação usa `islice`, pois o gerador é intencionalmente infinito. |
| `src/curio/cli.py` | Fechamento do comando | A validação revelou um `NameError` em `_print_sources` por uma linha residual de `_final_progress`. Removida a impressão que referenciava `label`/`status` inexistentes, para que `generate` termine sem traceback depois do render. |

## 3. Evidências

### Testes

```text
python -m pytest -q -p no:cacheprovider
537 passed in 49.31s
```

O teste de grounding de console foi executado isoladamente antes da suíte completa:

```text
python -m pytest tests/test_grounding_diag.py -q -p no:cacheprovider
17 passed in 0.07s
```

### Validação manual curta

Executado `./scripts/run.sh --config /tmp/opencode/val-peoples.toml generate "fale sobre a história de São Jerônimo" --slug validacao-sao-jeronimo-1420 --duration 45 --no-open`.

- Gênero: `people`; contexto de pesquisa identificou São Jerônimo e formas alternativas.
- Render: `av1_vaapi`, 1080×1920, duração observada de 26,7 s (meta de 45 s), 3 cenas.
- A cena 2 sem foto adequada gerou `Card — Jerome's birthplace`; fallback semântico permaneceu ativo.
- Na primeira passagem de mídia, Pexels avisou uma vez. Pixabay encontrou 35 candidatos; 1 download foi tentado, falhou com HTTP 403, e 0 baixaram. Wikimedia registrou 24 candidatos, 5 tentativas e 5 sucessos. O resumo observado em `metadata.json` foi:

```json
{
  "pixabay": {"candidates_found": 35, "downloads_attempted": 1, "downloads_succeeded": 0, "downloads_failed": 1, "http_403": 1, "other_errors": 0},
  "wikimedia": {"candidates_found": 24, "downloads_attempted": 5, "downloads_succeeded": 5, "downloads_failed": 0, "http_403": 0, "other_errors": 0}
}
```

- O NIM atingiu timeout em 15 s; OpenRouter/Gemini permitiram o fallback e o vídeo foi gerado.
- O rerun com cache terminou sem traceback e imprimiu `Output`, duração e fontes. Como mídia e render vieram do cache, esse rerun gravou `provider_downloads: {}`; as métricas acima são da primeira passagem, quando downloads ocorreram.
- O `ffprobe` do artefato confirmou AV1, 1080×1920, AAC e 26,7 s.

### Grounding do artefato São Jerônimo existente

Reexecutado `verify_grounding` sobre o roteiro e fontes salvos em `output/fale-sobre-a-historia-de-sao-jenonimo/`, e a saída foi emitida por `_print_grounding_warning`:

```text
AVISO: 2 afirmações do roteiro sem correspondência nas fontes:
  - 135: "…coleção de 135 pequenas biografias. Ele a completou em Belém, entre 392 e 393.…"
      possível causa: valor_ausente_das_fontes
  - 393: "…Ele a completou em Belém, entre 392 e 393. Essa obra é um registro valioso…"
      possível causa: valor_ausente_das_fontes
  Fontes avaliadas: Jerônimo, Joquebede, Dos Homens Ilustres (Jerônimo)
  Consulte sources/FONTES.md para as fontes relacionadas.
```

O gate manteve `checked=8`, `coverage=0.75` e `unverified=['135', '393']` nesse artefato.

### Tentativa de validação longa

Foi iniciada uma geração sem limite de duração para comparar com o caso anterior, mas ela parou na etapa LLM antes de mídia/render: o provedor OpenRouter informou limite de créditos, Gemini atingiu quota/429, houve resposta 503 na NVIDIA e a chave Groq foi rejeitada. Não foi possível obter um vídeo longo comparável; nenhum valor de timeout ou comportamento de fallback foi alterado para mascarar indisponibilidade externa.

## 4. Status vs PRD §19

Não há arquivo PRD no repositório que permita verificar §19. Em relação aos critérios desta solicitação: entidade estruturada, diagnóstico grounding, aviso único de provider, métricas de download, observabilidade de reuso, fallback por card e fallback de provider foram cobertos por testes e/ou pela validação curta. A validação visual longa ficou inconclusiva devido aos limites externos das APIs.

## 5. Limitações

- O timeout continua sendo um único timeout de socket; separar conexão, leitura e orçamento total de geração exigiria trocar a camada HTTP. O padrão permanece 15 s, configurável sem escolher um valor operacional arbitrário.
- A validação completa de longa duração não foi concluída porque os provedores estavam sem crédito, limitados por quota, sobrecarregados ou com credencial rejeitada.
- A validação curta testou a geração e o fallback semântico, mas não substitui comparação visual quadro a quadro com o vídeo longo original.
- O motivo de reuso observado é `same_top_match`; o pipeline não infere intenção editorial temática.
- A execução com cache não produz métricas novas de download; por isso seu `provider_downloads` ficou vazio.
