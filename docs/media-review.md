# Revisão de imagens por pasta

## Projeto existente

```sh
video-gen media-review --slug 20261008_aristoteles-discipulo-de-platao
# Apague as imagens irrelevantes de media_review/scene_01/, scene_02/, ...
video-gen resume-media-review --slug 20261008_aristoteles-discipulo-de-platao
```

Na execução usada para validar esta implementação, os candidatos de Aristóteles foram exportados em `output/people/20261008_aristoteles-discipulo-de-platao/media_review/`. Essa pasta é um artefato local e não acompanha o clone do repositório; use seu próprio slug em outras instalações.
Se usar o launcher do projeto, substitua `video-gen` por `./scripts/run.sh`.

## Vídeo novo

```sh
video-gen generate "Aristóteles" --slug aristoteles-revisao --media-review
video-gen resume-media-review --slug aristoteles-revisao
```

Também funciona em `from-script`. Alternativas: `REVIEW_MEDIA=1` ou `review_media = true` no config TOML. A pausa termina com código **3**, indicando revisão pendente.

## Auditoria sem pausa

```sh
video-gen generate "Aristóteles" --slug aristoteles-auditoria --media-dump
video-gen media-review --slug projeto-existente --dump
```

Alternativas: `DUMP_MEDIA_CANDIDATES=1` ou `dump_media_candidates = true`. O segundo comando exporta a etapa de mídia do projeto existente; `--media-dump` em generate/from-script continua até o vídeo.

## Como escolher

- Cada `scene_XX/` contém candidatos reais, inclusive os rejeitados semanticamente, e manifests JSON/CSV com origem, query, título, score e motivo. Falhas de download/licença ficam no manifest sem arquivo de imagem.
- Apague os arquivos irrelevantes. Pode adicionar imagens próprias JPG, PNG ou WebP à pasta da cena.
- Com vários arquivos restantes, **usa o de maior score original**, com desempate pelo nome ordenado. O resumo lista todos os restantes e a escolha efetiva. Para escolher exatamente uma imagem, deixe apenas ela.
- A escolha manual prevalece sobre a rejeição semântica anterior. Licenças bloqueadas e arquivos inválidos continuam sinalizados.
- Cena vazia usa fallback sintético, registrado explicitamente. Arquivo corrompido interrompe a retomada com diagnóstico.
- A retomada reaproveita pesquisa, roteiro e cenas. Se já houver áudio/timeline, refaz somente o render. Não repõe imagens apagadas nem refaz buscas.
- `selected/` contém cópias locais; `review_summary.json` registra encontrados, exportados, restantes, usados, erros dos provedores e saída renderizada.
- Interrupção durante a exportação: repita `media-review`. Revisão já concluída: use `resume-media-review`. Mudanças nas cenas exigem nova exportação em outro projeto.
- Com ambos os modos desligados, segue a seleção automática.
