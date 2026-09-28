# Relatório — JSON de cenas tolerante + smoke test

- **Data:** 2026-09-28 19:54 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** corrigir "API não retornou JSON válido para as cenas" e testar antes de rodar tudo
- **Commit(s):** este lote
- **Origem:** erro reportado pelo usuário no fluxo humano (60 s, 7 cenas)

## 1. Causa raiz (reproduzida antes de corrigir)

Roteiro de 60 s → JSON de 7 capítulos consome ~1995/2000 tokens (medido).
`complete_json` tinha orçamento fixo, sem checar `finish_reason` e sem
extrair substring — qualquer truncamento ou preâmbulo virava o erro visto.
Diagnóstico feito com chamada direta (sem gastar pipeline).

## 2. Correções (`stages/nvidia.py`)

- `_extract_json`: cercas + substring do primeiro `{` ao último `}` (tolera
  preâmbulo/epílogo); truncado/sem-objeto → erro explícito.
- `complete_json`: 2000 → 4000 tokens se `finish_reason=length`; se ainda
  truncar, erro claro pedindo retry.

## 3. Teste antes de tudo (`scripts/smoke.sh`, novo)

14 cheques offline (sem rede/custo): extração de JSON (5 casos), cenas por
duração, divisão local literal, agrupamento por boundaries, gate de
relevância. **14/14 passando.** Rode `./scripts/smoke.sh` antes de depurar.

## 4. Validação fim-a-fim

Vídeo do usuário refeito direto: 7 cenas, 7/7 com imagem, teleprompter com
26 cues, Dolphin + Audacity abertos. Estimado 53,2 s p/ meta 60 s (WPM é
estimativa — a voz real define no finalize).
