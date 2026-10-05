# G81 — seleção de mídia por cena permanece tipada

**Data:** 2026-10-05  
**Commit:** `aa25487` (`refactor: keep scene media selection typed`)  
**Estado:** implementado e validado.

## Problema

`_search_scene_with_shortcircuit` construía e retornava `list[dict]`, embora
cada item já representasse uma seleção de cena com asset, decisão editorial,
auditoria, fallback e rejeições. `fetch_media_multi` agregava essas rows e
imediatamente as convertia de volta em `MediaStageResult` por `from_rows`.
Esse ciclo ocultava o contrato entre o seletor por cena e o agregador da etapa.

## Mudança

O helper agora retorna `tuple[SceneMediaSelection, list[str]]`: uma seleção
imutável e validada por cena, mais avisos. Os caminhos de mídia tipográfica e
seleção normal constroem o mesmo contrato. `fetch_media_multi` agrega as
seleções e instancia `MediaStageResult` diretamente, sem serializar cada cena
em uma row e revalidar a lista.

`media.json` continua sendo o formato persistido. A seleção ainda é montada a
partir de campos/auditoria em formato row e passa pela fábrica
`SceneMediaSelection.from_dict`; G81 remove a transição row retornada entre
funções, mas não migra toda a montagem interna para construtores de domínio.
Não mudou política editorial, busca, scoring, fallback, reuso ou aquisição.

Os testes que inspecionam o formato persistido usam
`tests/test_support/media_scene_search.py` como adapter explícito para
`to_dict()`. Esse adapter também verifica que o helper de produção retornou
`SceneMediaSelection`.

## Arquivos e contratos

- `src/curio/stages/visual.py`: helper por cena agora retorna
  `SceneMediaSelection`; agregador monta `MediaStageResult` a partir dos
  contratos tipados.
- `tests/test_support/media_scene_search.py`: projeção de teste explícita.
- Regressões em waterfall, receipt, museus, buraco negro, queries visuais,
  diversidade, seleção, funil e integração da etapa migraram para o adapter de
  teste ou para fixtures tipadas.
- Contrato usado: `SceneMediaSelection`; nenhum schema persistido foi removido.

## Validação

- Testes focados de mídia e contratos: **160 passaram** em 1,94 s.
- Suíte completa: **960 passaram** em 187,17 s.
- `python -m compileall -q src tests`: passou.
- `git diff --check`: passou.

## Limite restante

O agregador já recebe seleções tipadas, mas o corpo do coordenador de cena
continua extenso e ainda monta parte da decisão em payloads de auditoria antes
de chamar `SceneMediaSelection.from_dict`. Isso pede uma próxima fase guiada
por responsabilidades, não uma extração baseada apenas no tamanho de
`visual.py`. G81 não inclui geração real de mídia: não mudou provider, query,
score nem comportamento de seleção.
