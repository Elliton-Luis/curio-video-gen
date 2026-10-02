# Relatório — Ancorar imagens locais no tema do vídeo

- **Data:** 2026-10-02 18:53 (UTC)
- **Tipo:** relatorio
- **Escopo:** corrigir Argentina em Revolução Francesa e ônibus em vídeo de buraco negro
- **Commit(s):** pendente
- **Origem:** métricas `20261002-103910_20261002_a-revolucao-francesa-e-suas-con.json`

## 1. O que foi pedido

Usuário relatou fotos argentinas em vídeo sobre Revolução Francesa e ônibus
em vídeo de buracos negros.

## 2. Causa confirmada

- Métrica da Revolução: `scenes_source=local`. Cena 2 gerou `sun nation` para
  frase sobre França e absolutismo; candidatos selecionados incluíram duas
  bandeiras argentinas. `_space_boost` procurava substring `sol`, então
  `absoluto` acionava `sun`.
- Métrica de buracos negros: cena 4 gerou `mass radiation`; título
  `bus, mass station` casou com assunto local `mass` e recebeu score 85.
- Cenas locais tinham queries isoladas, sem âncora comum do vídeo. Score
  lexical tratava uma palavra ampla como assunto suficiente.

## 3. O que foi feito

| Arquivo | Mudança | Efeito |
|---|---|---|
| `textnorm.py` | Mapa de frases `Revolução Francesa` e `Buracos Negros`; mapeamento França/francês | Mantém tópico composto ao traduzir. |
| `stages/visual.py` | `_space_boost` usa fronteira de palavra | `sol` não casa mais com `absoluto`; `solar` tem entrada própria. |
| `stages/scenes.py` | Marca cenas locais com `visual_intent="local fallback"` | Scoring distingue fallback local de cena descrita pelo LLM. |
| `stages/visual_context.py` | Anexa query global traduzida do tema a cenas locais, inclusive cache legado identificado por metadata | Cena conserva tópico geral junto à query local. |
| `stages/scoring.py` | Exige que título de imagem em cena local contenha tokens completos da query global | Argentina, igreja genérica e ônibus sem relação não passam. Cenas do LLM mantêm score anterior. |
| `stages/visual.py` | Aplica mesma âncora ao fallback genérico | Fallback não contorna o gate local. |

## 4. Evidências

- `local_queries("A França ... rei absoluto ...")` agora não contém `sun`.
- Query global para `Revolução Francesa`: `french revolution`.
- Query global para `Buracos Negros`: `black hole`.
- Score local rejeita `Argentinian flag, sun, country, nation`, `church interior`
  e `bus, mass station`; aceita título `French Revolution, Paris, 1789` e
  `black hole mass and event horizon`.
- `python3 -m pytest tests/ -q` — **732 passed**.

## 5. Limitações

Gate usa tokens do título, não visão computacional. Foto relevante com título
que omite query global pode ser rejeitada; nesse caso cena cai para visual
sintético em vez de aceitar associação semântica não comprovada.
