# Produção editorial com qualquer agente

`agent-flow` é um fluxo opcional. O agente opera por CLI e arquivos JSON locais. Não depende de Codex, Antigravity, SDK, API de agente ou modelo específico. Os comandos existentes continuam disponíveis.

O agente faz pesquisa, roteiro, planejamento visual, intenção musical, curadoria e inspeção editorial. Curio exporta candidatos, monta áudio e vídeo e valida o arquivo. Nenhum provedor LLM interno decide essas etapas neste fluxo. TTS continua configurável; buscas de mídia continuam disponíveis na exportação.

## Iniciar

### Informar o tema e escolher como operar

`--topic` define o assunto; `--slug` nomeia o projeto; `--genre` escolhe o perfil editorial e a pasta. Por exemplo:

```sh
video-gen agent-flow init --slug buracos-negros --topic "Como buracos negros distorcem o tempo" --genre science
```

`init` cria o contrato e pausa: não produz o vídeo sozinho. Para trocar o tema depois da criação, edite `plan.json`, incluindo pesquisa, roteiro e cenas coerentes, e use `replan` se o plano anterior já tiver sido importado.

Se o agente já tem acesso ao terminal e aos arquivos deste projeto, basta pedir no chat:

> Produza um vídeo sobre “Como buracos negros distorcem o tempo”, usando agent-flow, slug buracos-negros, gênero science. Execute os comandos, leia o AGENT.md do projeto e cumpra request.json até revisão e aprovação fundamentada.

Nesse caso, o próprio agente executa `video-gen`; não é necessário um segundo terminal. Um chat sem ferramentas para executar comandos exige um terminal separado, operado por você ou por um executor. `agent-flow` não conecta um chat ao terminal, não instala agentes e não inicia agentes automaticamente. Inspeção de áudio/vídeo depende das ferramentas disponíveis ao agente; sem essa capacidade, mantenha a avaliação correspondente pendente.

### Executar os comandos manualmente

Execute na raiz do repositório:

```sh
video-gen agent-flow init --slug meu-video --topic "Tema do vídeo" --genre people
video-gen agent-flow status --slug meu-video
```

Se `video-gen` não estiver instalado, substitua-o por `./scripts/run.sh`. Opções globais, como `--out-dir` e `--backend`, vêm antes de `agent-flow`. `init` e `status` de um projeto pendente retornam código 3; isso é esperado.

Um projeto existente também pode ser usado: informe seu slug, sem `--topic`. Os artefatos existentes servem como rascunho; ainda exigem aprovação editorial.

A pasta `output/<genero>/<slug>/agent_flow/` contém:

- `AGENT.md`: instruções portáveis para o agente escolhido.
- `plan.json`: pesquisa, roteiro, cenas e escolha musical editáveis.
- `state.json`: estado persistente e histórico das etapas.
- `request.json`: próxima tarefa e evidências disponíveis.
- `media-feedback.json`: seleção explícita por cena.
- `feedback.json`: avaliação do render atual.
- `evidence-NNN/`: frames do vídeo, verificações técnicas, identidade dos arquivos e avaliação de cada iteração.
- `discarded/` e `previous/`: arquivos preservados durante correções.

Peça ao agente: **Leia `output/<genero>/<slug>/agent_flow/AGENT.md` e o `request.json` dessa pasta; conclua a tarefa indicada, execute `advance` e continue revisando até aprovação fundamentada.** Qualquer agente com acesso a arquivos, terminal, pesquisa e inspeção de imagens/áudio pode usar o contrato. A troca de agente não muda comandos ou artefatos.

## Contrato, versão 1

### Plano

Preencha `plan.json` antes de avançar:

- `schema_version: 1`, `topic`, `genre`, `title`, `script`.
- `research.sources`: fontes com `title`, URL HTTP(S) em `url` e evidência em `snippet`. Campos adicionais seguem `sources/research.json`.
- `scene_plan`: contrato existente `script/scene-plan.json`, versão 1, com `source`, `semantic_scenes` e `timeline_spans`. A soma das narrações deve reproduzir literalmente o roteiro. O arquivo inicial inclui um exemplo estrutural; substitua seu conteúdo. Declare representações, contexto e aliases sustentados por fontes.
- `music`: `mode` igual a `manual` ou `none`; `intent` e `reason` obrigatórios. Intenção descreve narrativa, ritmo e emoção. Em `manual`, informe arquivo local em `file`, `source_url`, licença livre reconhecida em `license`, `license_url` e `instrumental: true`. O agente pesquisa/downloads trilhas quando necessário. Em `none`, justifique silêncio. `auto` não é aceito neste fluxo.

Use caminhos de arquivo absolutos para trilhas externas. Volume, ducking, transições e voz continuam vindo da configuração existente. A revisão deve conferir direitos e atribuições; validação estrutural não comprova a veracidade de fontes.

```sh
video-gen agent-flow advance --slug meu-video
```

Esse comando importa o plano, exporta candidatos e retorna à revisão de mídia. Não escreve um roteiro novo. Mudanças no roteiro ou nas cenas invalidam áudio e timeline antigos; os arquivos são arquivados.

### Seleção de mídia

Inspecione `media_review/scene_NN/` e seus manifests. Preencha cada linha de `media-feedback.json`:

```json
{
  "schema_version": 1,
  "scenes": [
    {
      "scene_id": 1,
      "filename": "001_wikimedia_imagem.jpg",
      "reason": "A imagem representa o local mencionado nesta cena.",
      "rights_evidence": "Licença e atribuição conferidas no manifest e na fonte.",
      "fallback_reason": ""
    }
  ]
}
```

Escolha exatamente um arquivo por cena. Outros candidatos são arquivados, sem exclusão definitiva. O agente pode adicionar imagens e metadados aos manifests, preservando origem e direitos. Use `filename: null` somente após procurar alternativas, com `fallback_reason` explícito. Curio então permite cartão nessa cena.

```sh
video-gen --backend cpu agent-flow advance --slug meu-video
```

Curio utiliza somente as escolhas locais, reaproveita narração válida e renderiza. Retorna obrigatoriamente ao agente com frames por cena, dados da mídia usada, trilha escolhida, verificações técnicas e caminho do vídeo. Não aprova automaticamente.

### Revisão do vídeo e correções

Inspecione vídeo, frames, legendas e áudio. Em `feedback.json`, preserve `render_id`, identifique `reviewer` e informe `decision: approve` ou `revise`.

Aprovação exige:

- Todos os sete `checks` com `ok: true` e `evidence`: precisão factual, imagens, variedade, enquadramento/legendas, ritmo, áudio/música e direitos.
- Todas as cenas com `ok: true` e evidência específica.
- `issues: []` e verificações técnicas aprovadas.

Rejeição exige `issues` com problemas encontrados. O agente deve declarar apenas inspeções que realizou. Frames isolados não provam revisão integral do vídeo ou do áudio.

```sh
video-gen agent-flow advance --slug meu-video
# Havendo problemas, corrija a seleção, depois:
video-gen agent-flow revise --slug meu-video
video-gen --backend cpu agent-flow advance --slug meu-video
```

Cada novo render gera nova identidade e nova revisão obrigatória. Para mudar roteiro, cenas, pesquisa ou trilha, edite `plan.json` e execute:

```sh
video-gen agent-flow replan --slug meu-video
video-gen agent-flow advance --slug meu-video
```

`replan` arquiva artefatos derivados e volta ao planejamento. Para revisar apenas mídia, use `revise`; imagens anteriores permanecem em `discarded/` e podem ser copiadas de volta.

## Automação e códigos de saída

- `0`: vídeo aprovado e identidade dos arquivos ainda válida.
- `3`: tarefa editorial pendente; leia `request.json`, trabalhe e continue.
- `1`: falha ou contrato inválido; corrija antes de retomar.

Um executor externo pode repetir esses passos. Não interprete `3` como falha fatal nem como aprovação. Não execute `advance` em loop sem cumprir a tarefa pendente. Curio não inicia agentes nem depende de uma sessão de chat permanente.

Aprovação inclui hashes do vídeo, plano, mídia local utilizada, candidatos restantes, áudio, fontes, legendas e timeline. Alterações exigem nova revisão. `status` também invalida aprovação após mudanças. Os hashes detectam mudanças; não medem qualidade editorial. Essa qualidade continua dependendo do agente e das evidências de inspeção.
