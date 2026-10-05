# I1 — rerender real sem nova pesquisa

**Estado:** validado em runtime.  
**Escopo:** provar que o comando de rerender usa a seleção persistida e não
repete aquisição de mídia.

## Procedimento

Foi copiado para `/tmp` o projeto científico real
`output/science/20261004-refactor-black-hole-rerender`. O rerender foi feito
na cópia, com métricas e cache separados:

```bash
video-gen --out-dir /tmp/curio-f15-rerender rerender \
  --slug 20261004-refactor-black-hole-rerender
```

Antes e depois, os SHA-256 de `media/media.json` e
`media/media-selection.json` foram idênticos:

- `media.json`: `56f372577c8b35947aaace89e593023c20977bd69accf254bc6a5d8f2473b906`
- `media-selection.json`: `adcc2c7664f1d56e9f8aacc2519ade2cc079b15b687cf9c0376bfad0a0733ec5`

As métricas novas do rerender registraram `provider_requests: {}`,
`provider_search_calls: {}` e `logical_queries: 0`. O comando informou que
narração, roteiro e legendas vieram do cache. Isso verifica o caminho runtime
do projeto: rerender consumiu os bytes/seleção existentes sem nova busca.

## Resultado e limites

- Rerender concluído em **22,83 s** de processamento medido; o MP4 final tem
  **27,5 s**, resolução **1080×1920**, vídeo AV1 e áudio AAC.
- `video-gen verify` passou **8/8** verificações, incluindo MP4, streams,
  resolução, proporção, duração e SRT.
- Projeto de origem intacto; execução e artefatos de prova ficaram em
  `/tmp/curio-f15-rerender`.

Este caso prova compatibilidade de rerender com seleção persistida para um
projeto real de ciência. Não valida rerender após alteração manual de asset,
cache frio, falha de download nem seleção histórica. Esses cenários continuam
abertos no plano de validação.
