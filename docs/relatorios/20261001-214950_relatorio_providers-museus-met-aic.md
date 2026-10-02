# Relatório — providers de museus para conteúdo histórico

- **Data:** 2026-10-01 21:49 -0300
- **Tipo:** relatorio
- **Escopo:** Met Open Access + Art Institute of Chicago integrados à cascata de mídia, com prioridade em cenas históricas.
- **Commit(s):** commit desta entrega (`feat: add met and aic museum providers`)
- **Origem:** pedido de provedores de museu para temas históricos sem quebrar o pipeline.

## 1. O que foi pedido

Adicionar The Met Open Access e Art Institute of Chicago via APIs oficiais, aceitando só imagens de uso público compatível; priorizar museus + Wikimedia em temas históricos; preservar metadata, score, dedup, cache e fallback; falhar sem interromper o pipeline.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `media/providers.py` | Providers | `MetMuseumProvider` (busca → IDs → `/objects/{id}`, só `isPublicDomain` com imagem) e `ArtInstituteProvider` (busca com `is_public_domain=true`, só com `image_id`, imagem via IIIF). Sem chave, erros viram `MediaError`, objetos falhos são pulados. |
| `media/providers.py` | Direitos | Licenças `Domínio público (...)` → `classify_rights` devolve `clear`; metadata carrega obra, autor, data, instituição, URLs e provider. |
| `stages/visual.py` | Prioridade | `historical_art` consulta `met, aic, wikimedia, openverse` antes dos bancos; ordem global inalterada para os demais tipos (museus entram antes do Unsplash). |
| `config.py`, `config.example.toml`, `tui.py` | Config | `met,aic` no default e nas opções da TUI; sem chave nova, sem migração. |
| `README.md` | Uso | Default atualizado e regra de prioridade histórica documentada. |
| `tests/test_media_museums.py` | Regressão | Busca, direitos, cache, dedup, fallback e priorização com fixtures, sem rede. |

Cache, dedup, score e fallback são os existentes: o coletor já consulta cache por query antes da rede, deduplica por `provider:id`, pontua pelo título e segue ao próximo provider em `MediaError`.

## 3. Evidências

- `python -m pytest -q tests/test_media_museums.py tests/test_media_providers.py tests/test_media_funnel.py tests/test_media_diag.py` — passou na prova focada.
- `python -m pytest -q` — **692 passed**.
- Nenhuma API real foi chamada na validação; providers externos foram simulados.

## 4. Status vs PRD §19

Sem PRD no repositório. Providers novos são somente-leitura, sem chave e sem dependência; falha de museu cai para o próximo provider. Nenhum provider existente foi alterado.

## 5. Limitações

- Met exige 1 request por objeto (limitado a `limit*2`); AIC resolve tudo em 1 request.
- Dimensões dos museus só após download (sonda ffprobe), como na NASA.
- Cobertura de entidade (César/Roma) continua dependendo de `subject_aliases` + scoring; museus aumentam o acervo, não mudam a nota.
