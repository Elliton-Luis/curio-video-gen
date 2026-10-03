# Relatório — Auditoria do diretor visual e telemetria

- **Data:** 2026-10-03 15:43 (-03:00)
- **Tipo:** análise e correção
- **Escopo:** implementação do diretor visual, 20 métricas mais recentes e 10 relatórios mais recentes; métricas de teste excluídas da avaliação de produto
- **Commit(s):** em andamento

## 1. Conclusão

O diretor visual está implementado no pipeline. Cenas carregam contexto e
representações; providers fornecem metadados; scoring aplica gates técnicos e
semânticos; `media.json`, folha de contato e métricas registram decisões. O
relatório de direção visual registra ainda uma avaliação real do estágio de
mídia com cinco assets contextuais.

A implementação tinha uma falha de integração no fallback local. Um alias
inglês obtido da página de pesquisa entrava nas queries, mas não no contexto
semântico. As queries locais também não eram usadas como evidência de cena.
Resultado observado: 212 candidatos, zero elegíveis e 11/11 visuais sintéticos
no vídeo do Império Otomano.

## 2. Evidência analisada

As 20 métricas mais recentes continham 16 execuções `teste-integracao`, três
registros `proj-review` sem buscas de mídia e um backfill do vídeo real. Os
registros de teste foram ignorados conforme pedido. Os registros `proj-review`
não representam uma geração e não medem a taxa de acerto do diretor.

O backfill mais recente mostrava duração total zero, zero cenas/assets visuais,
decisões vazias e consumo indisponível. O metadata da mesma execução registra
11 cenas, 212 candidatos, zero candidatos retidos, 100% de visuais gerados por
código e rejeições por ausência de evidência do tópico/âncora. O backfill perdeu
dados já disponíveis no metadata.

Os 10 relatórios lidos foram os dois relatórios de fallback LLM, os relatórios
da direção visual (completo e parcial), queries elétricas Tesla, aprendizado
contável, mood musical por gênero, busca fresca, âncora de pessoa/tópico e
âncora visual. Eles confirmam implementação estrutural, gates conservadores,
CLIP opcional sem pesos reais e ausência de geração completa com mídia real na
validação anterior.

`video-gen doctor` confirmou a causa ambiental do fallback: nenhum provider LLM
tem chave, `CURIO_CONTACT` não está definido e Pixabay, Unsplash e Pexels não
têm chaves. NASA, Met, AIC e Wikimedia aparecem configurados, mas a busca
observada não encontrou candidato que passasse os gates.

## 3. Problema 1 — evidência semântica incompleta no fallback local

Capítulos locais já carregavam queries inglesas confirmadas por link de idioma,
mas `fill_missing_context()` não copiava esse nome para `video_context`, que é
a fonte do scoring de tópico. Além disso, `attach_video_context()` removia os
termos locais de `visual_entities`, e scoring não consultava `visual_queries`
como evidência de cena.

Corrigi as duas lacunas. Nomes confirmados entram em `primary_entities` e
`aliases`; fallback local usa suas queries como frases completas de cena.
Correspondência de uma palavra continua sem valor probatório. README atualizado
com esse comportamento.

## 4. Problema 2 — backfill apaga métricas visuais e duração

O metadata já persiste `visual_report`, cenas, mídia, decisões por candidato,
horários por etapa e duração de processamento. `backfill_from_metadata()` criava
uma instância vazia de `RunMetrics` e zerava as seções de consumo, mas também
deixava zerados os campos visuais e `total_seconds`, mesmo quando os valores
eram recuperáveis.

Próximo passo: preservar no backfill os campos visuais deriváveis do metadata e
calcular início/fim/total a partir de `created_at` e
`processing_time_seconds`. Contadores de requests, tokens e tentativas sem
registro persistido devem continuar nulos.

## 5. Limitações

Não rodei testes, conforme pedido. Não validei a correção com nova busca externa;
este checkout não tem contato Wikimedia nem chaves dos providers de imagem.
CLIP real segue fora da instalação e sem pesos; continua opcional.
