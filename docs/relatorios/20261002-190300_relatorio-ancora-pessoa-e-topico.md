# Relatório — Âncora local do sujeito e do tema

- **Data:** 2026-10-02 19:03 (UTC)
- **Tipo:** relatorio
- **Escopo:** corrigir seleção lexical de assets locais para Marco Aurélio, Revolução Francesa e buracos negros
- **Commit(s):** `9aad638`, `07f161c`
- **Origem:** `docs/analises/20261002-190300_analise-midia-marco-revolucao.md`

## 1. O que foi pedido

Analisar por que últimos vídeos tinham poucas fotos corretas e imagens
Argentina/ônibus fora do tema.

## 2. O que foi feito

| Arquivo | Mudança | Decisão |
|---|---|---|
| `textnorm.py` | Frases conhecidas `french revolution`, `black hole`, `marcus aurelius` e variantes em português | Preserva tema composto no fallback local. |
| `visual.py` | Marcadores do boost usam fronteiras de palavra | `sol` não casa dentro de `absoluto`; `solar` tem entrada explícita. |
| `scenes.py` | Cenas locais carregam marcador `local fallback` | Scoring distingue fallback local de cena estruturada pelo LLM. |
| `visual_context.py` | Propaga frase temática global às cenas locais, inclusive caches antigos marcados `scenes_source=local` | Busca combina tópico do vídeo e cena. |
| `scoring.py` | Títulos locais precisam conter uma frase-âncora completa; score inclui tokens dessa âncora | Argentina, Mughal Empire, Fábio Aurélio e ônibus não passam; retrato de Marco Aurélio pode servir a cenas locais sobre contexto. |
| `visual.py` | Fallback genérico aplica o mesmo gate | Igreja genérica não contorna âncora. |

Scoring de cenas LLM permanece igual. Nenhum output em disco foi editado;
pipeline aplica âncora ao reutilizar metadata antigo de cenas locais e
refaz mídia.

## 3. Evidências

- Na frase “rei absoluto”, `local_queries` não produz mais `sun`.
- `Revolução Francesa` gera âncora `french revolution`; `Buracos Negros`,
  `black hole`; `Imperador Marco Aurélio`, `marcus aurelius`.
- Regressões rejeitam título de bandeira argentina e título de ônibus;
  aceitam título de retrato de Marcus Aurelius mesmo em cena local sobre
  campanha na Armênia.
- `python3 -m pytest tests/ -q` — **733 passed**.

## 4. Status vs PRD §19

Sem rede ou dependência nova. Fallback semântica falsa vira visual sintético
quando nenhum título prova a âncora temática.

## 5. Limitações

Gate compara títulos, não conteúdo visual. Um retrato correto sem nome no
título pode ser rejeitado. Regerar projetos com cenas locais aplica a nova
âncora automaticamente; mídia antiga não muda até gerar novamente.
