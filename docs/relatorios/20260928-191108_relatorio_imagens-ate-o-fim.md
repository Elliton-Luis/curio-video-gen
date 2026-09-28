# Relatório — imagens do início ao fim (anti-fallback)

- **Data:** 2026-09-28 19:11 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** garantir imagens em todas as cenas, não só no início
- **Commit(s):** este lote
- **Origem:** pedido do usuário ("só o início tem imagens, depois fica genérico")

## 1. Diagnóstico (dados reais)

Projetos recentes: 1–2 fallbacks em 4–5 cenas (20–50%). Padrão "início com
imagem, fim genérico" = throttling progressivo: cada cena faz buscas +
downloads e o Wikimedia começa a responder 429 no meio da lista.

## 2. Correções

- **Cortesia entre buscas**: 1,5 s (Wikimedia) / 1,0 s (Openverse) + retry
  até 5× com backoff; memo de buscas por execução (consultas repetidas entre
  cenas não refazem request).
- **Reuso da cena vizinha** (`_resolve_reuse`): cena sem asset próprio reusa a
  imagem relevante mais próxima com outro movimento Ken Burns — registrado em
  `media.json` (`reused_from`) + AVISO. Gradiente só resta se NENHUMA cena
  tiver mídia.
- Ordem resultante por cena: asset próprio relevante → reuso vizinho →
  gradiente honesto.

## 3. Teste

Re-mídia do `salario-cenas` (sem custo NVIDIA/TTS): 5/5 cenas com imagem
(cena 4 reusa a cena 3), zero segmentos em gradiente, `verify` **8/8**,
frame t=28 inspecionado (fardo de sal-moeda + "sinal de pagamento" — coerente).

## 4. Limitações honestas

- Garantia é "melhor esforço com transparência", não absoluta: tema sem
  cobertura nos bancos ainda gera reuso/gradiente — sempre avisado, nunca
  imagem errada.
- Reuso repete imagem (com outro movimento); preferível ao genérico, mas
  Pexels com chave (já suportado) é o caminho p/ mais variedade moderna.
- 429 persiste sob rajada; mitigado, não eliminado.
