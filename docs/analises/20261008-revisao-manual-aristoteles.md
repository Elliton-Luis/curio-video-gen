# Revisão manual de mídia — Aristóteles

**Falha de referência:** execução local `run-20261008-140609-141577.jsonl`: 5 cenas sintéticas, nenhuma imagem real. Candidatos pertinentes rejeitados por identidade/representação lexical; provedores Met/AIC falhando; revisão por IA indisponível por quota/timeouts. Os caminhos `/mnt/data` informados não existem neste ambiente; foram usados os artefatos locais da mesma execução.

**Implementação:** exportação opcional antes da seleção final, com pastas por cena, imagens reais, manifests JSON/CSV e resumo. A revisão pausa; a retomada usa os arquivos mantidos, independentemente do score semântico anterior. Escolhe o melhor restante e explica a escolha. Cena vazia recebe fallback explícito. Dump exporta sem pausar. Falhas e interrupções permanecem observáveis; licenças e integridade dos arquivos continuam verificadas.

**Evidência real:** 41 candidatos únicos registrados, 36 imagens exportadas. Na cópia de validação, foram apagadas 31 e mantidas 5, uma por cena: Ribera, Escola de Atenas, Rembrandt, Liceu e busto Altemps. Retomada pelo CLI sem acesso externo: vídeo de **61,4 s, 5 cenas com imagens reais, zero cards**. Decodificação integral com `ffmpeg -xerror` passou. As 36 imagens originais permanecem disponíveis para revisão do usuário.

**Artefatos:** `output/aristotle-repair/manual-proof.json`, `manual-proof.jpg`; vídeo `output/media-review-proof/people/aristotle-reviewed/render/final.mp4`; manifests e resumo no respectivo `media_review/`.

**Pontos alterados:** `config.py`, `cli.py`, `pipeline.py`, `pipeline_visual.py`, `pipeline_research.py`, `pipeline_script.py`, `pipeline_scenes.py` para retomada, `scene_candidate_search.py`, `visual.py`, novo `media_review.py`, testes e documentação. O render existente é reutilizado.

**Regressões:** revisão de candidatos rejeitados, exclusão persistente, escolha da melhor imagem restante, pasta vazia, arquivo corrompido, mudança de cena, recuperação de exportação interrompida, flags/CLI, dump preservando seleção automática/manual, retomada anterior ao TTS sem novas consultas e preservação de volume/ducking.

**Validação:** suíte geral com 1.076 testes passando e dois testes de ambiente excluídos (rede real/encoder específico); 43 testes focais finais passando. Evidências em `output/aristotle-repair/review-final-all-tests.txt` e `review-final-targeted.txt`.
