# Relatório — imagens garantidas + duração escolhível

- **Data:** 2026-09-28 18:33 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** (1) sempre ter imagens relevantes sem marca d'água; (2) duração aproximada à escolha do usuário
- **Commit(s):** este lote
- **Origem:** pedido do usuário ("satélite→mostre satélite", fontes livres, escolher tempo)

## 1. Mais fontes (garantia de imagens)

- **Openverse** sondado e integrado: funciona **sem chave**, retorna licença
  (CC BY 2.0 etc.), autor, dimensões e flag `mature` (filtrada). Detalhes que
  custaram debug real: thumbs Flickr `_b` (1024px) caíam no filtro de 1000px
  → upgrade `_k` (2048px) com fallback ao `_b` em 404/410; gate de dimensão
  desligado pós-upgrade (dims da API descrevem o `_b`).
- **Pexels** implementado com chave (`PEXELS_API_KEY`, grátis com cadastro):
  ativo só com chave, nunca quebra sem ela. Parser testado com fixture;
  **sem teste live** (sem chave) — documentado honestamente.
- Ordem: `wikimedia,openverse` (+pexels se houver chave); `none` = fallback.
- Sem marca d'água: política do Commons, originais Flickr via Openverse e
  licença Pexels — nenhum provedor aplica watermark.

## 2. Relevância (satélite→satélite)

Gate novo: só aceita candidato com **escore > 0** (termo da consulta no
título); zerados viram fallback honesto em vez de associação falsa (§11).
Prova: cena do fuzileiro moderno (escore 0) virou fallback com aviso; teste
"satélite" trouxe Suomi NPP/Chandra/NASA (domínio público).

## 3. Duração escolhível

- CLI `generate --duration 30|45|60` (qualquer 15–120 s na TUI); `CURIO_DURATION`
  e `config.toml` continuam valendo; roteiro (chars/s), nº de cenas
  (~1/9 s: 3/5/7), TTS e `verify` acompanham a meta.
- `verify` lia a meta da config atual e reprovava vídeos de 30 s: agora lê
  `duration_target` do `metadata.json` do projeto.
- Teste: `--duration 30` → 31,02 s, 3 cenas, **8/8**.

## 4. Bugs achados e corrigidos nos testes

- `.format()` no prompt de cenas quebrava nas chaves literais do JSON
  (`KeyError: '"title"'`) → chaves escapadas `{{...}}`.
- Ver item 3 (verify com meta errada).

## 5. Limitações

- Pexels sem teste live; Openverse depende de Flickr (410 em fotos antigas,
  coberto pelo fallback `_b`).
- Gate por título é heurístico: imagem certa com título ruim cai (fallback
  honesto, nunca imagem errada — troca consciente).
- Wikimedia dá 429 sob rajada; retry/backoff + thumbnails mitigam.
- Cenas variam ±1 do pedido conforme o modelo (faixa no prompt).
