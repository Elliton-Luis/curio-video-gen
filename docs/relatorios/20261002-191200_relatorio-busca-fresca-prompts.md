# Relatório — Busca fresca de mídia e prompts curtos

- **Data:** 2026-10-02 19:12 (UTC)
- **Tipo:** relatorio
- **Escopo:** impedir reuso persistente de candidato por query e validar prompts reduzidos pelo usuário
- **Commit(s):** `5c99c15 fix: search fresh media with topic anchors`
- **Origem:** relato sobre geração em massa e mídia fora do tema

## 1. O que foi pedido

Busca precisa selecionar imagens coerentes em geração em massa. Prompts
mais curtos devem reduzir tokens por chamada sem perder regras essenciais.

## 2. O que foi feito

| Arquivo | Mudança |
|---|---|
| `stages/visual.py` | Removido cache persistente `cache/media_query` de candidatos escolhidos. Cada vídeo consulta provedores de novo; cache de resultados compartilhado só dura dentro da execução. |
| `media/cache.py` | Download por URL/asset continua cacheado para rerender e evitar bytes repetidos; esse cache não escolhe imagens nem impede nova busca. |
| `prompts.py` | Mantive as alterações reduzidas que já estavam no working tree do usuário. PT: 5.916 para 1.942 caracteres; EN: 4.377 para 2.065. |
| testes de prompt | Atualizados para validar as regras no texto curto, não frases antigas do prompt longo. |
| testes de busca | Confirmam nova busca entre execuções, mesmo asset bytes cacheados; query-result cache não existe mais. |

## 3. Evidências

- `python3 -m pytest tests/test_media_museums.py tests/test_visual_asset_usage.py tests/test_media_waterfall.py tests/test_media_funnel.py -q` — 40 passed.
- `python3 -m pytest tests/test_script_hook.py tests/test_shorts60.py tests/test_active_word.py -q` — 16 passed.
- `python3 -m pytest tests/ -q` — **733 passed**.
- Medições acima são caracteres, não tokens. Não há contagem real de tokens dos prompts encurtados neste relatório.
- Redução foi no prompt de roteiro. Prompt de cenas ficou igual; logs mostram respostas LLM inválidas (7/6 e 9/8 cenas) e fallback local. Reduzir prompt de roteiro não corrige esse fallback.

## 4. Status vs PRD §19

Busca nova continua sem chave paga. Download cache só evita baixar o mesmo
arquivo novamente; escolha continua vindo de nova resposta do provedor.

## 5. Limitações

Provedor ainda pode retornar títulos lexicalmente ambíguos. Cenas locais
exigem agora âncora do assunto, mas o gate compara metadados, não pixels.
Use imagens cacheadas para rerender do mesmo projeto; nova geração pesquisa
provedores novamente.
