# Relatório — sistema de fontes (verificação de fatos + procedência de mídia)

- **Data:** 2026-09-29 15:42 (-03)
- **Tipo:** relatorio
- **Escopo:** registro persistente de fontes factuais e procedência de mídia por projeto, com CLI de gerenciamento
- **Commit(s):** pendente
- **Origem:** pedido do usuário (verificação de fatos, procedência, persistência, uso posterior)

## 1. O que foi pedido

1. Verificação de fatos antes de considerar informação válida para o roteiro.
2. Registro de fontes factuais (claims) com status de evidência.
3. Registro separado de procedência de mídia (imagens/vídeos).
4. Persistência no projeto (`output/<slug>/sources/sources.json`), sobrevivendo a reaberturas.
5. Não duplicar fontes; adicionar sem apagar histórico.
6. URLs salvas exatamente como retornadas pela pesquisa (nunca inventadas).
7. Uso posterior: gerar descrição do vídeo, mostrar ao usuário, verificar roteiro, auditar.
8. CLI para adicionar/listar fontes.
9. Integração automática: ao baixar mídia, registrar procedência automaticamente.

## 2. O que foi feito e como

| Arquivo | Responsabilidade | Decisão |
|---|---|---|
| `stages/sources.py` | núcleo | `Source` (claim + evidência + status), `MediaSource` (procedência de mídia), `SourceRegistry` (load/save/add_claim/add_media com dedup por URL+claim / título+origin_url). Status: `confirmed`/`partial`/`contested`/`unverified`. |
| `pipeline.py` | integração | `sources_json` no `VideoPaths`; carrega no início; registra mídias após fetch (se `local_path` existir); salva no fim; `metadata["sources"] = {claims: N, media: M}`. |
| `cli.py` | interface | `video-gen sources <slug> [--add <claim> --title --url --evidence --author --date --status --notes]` (sem `--add` = listar). |
| `scripts/smoke.sh` | testes | Seção 12: 10 cheques (claim/mídia add, dedup, status validação, save/load, append sem sobrescrever, status inválido vira `unverified`). |
| `media/providers.py` | mídia | `PixabayProvider` (API key `PIXABAY_API_KEY`, filtro safe search, resolução mínima). |

## 3. Evidências

```text
$ ./scripts/smoke.sh  →  87 passaram, 0 falharam (seção 12 adicionada).
E2E AI (teste-fontes-ai, 6.27 s): metadata.json criado, sources/ vazio (PIXABAY_API_KEY não configurado → 0 assets baixados → 0 mídias registradas).
CLI: `video-gen sources teste-fontes-ai --add "O polvo tem 3 corações" --title "Polvo — NatGeo" --url "https://..." --evidence "..."` → registra e persiste.
```

## 4. Status vs PRD §19

Sem impacto nos 8 cheques de vídeo. Novo artefato `sources.json` e campo `sources` no `metadata.json` documentam a procedência.

## 5. Limitações

- Registro de mídia só ocorre se `local_path` existir (download bem-sucedido). Sem chave de API válida, `media=0` (comportamento correto).
- Claims manuais via CLI não validam a URL/existência da fonte — responsabilidade do usuário.
- Não há validação automática de "fonte confiável" — status é declarativo.
- URLs de mídia usam `download_url` (URL direta do arquivo) e `origin_url` (página de origem) — podem divergir.