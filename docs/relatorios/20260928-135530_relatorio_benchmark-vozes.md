# Relatório — benchmark de vozes PT-BR

- **Data:** 2026-09-28 13:55 (UTC-3)
- **Tipo:** relatorio
- **Escopo:** sintetizar a mesma frase em 4 vozes pedidas + alternativas reais
- **Commit(s):** este lote
- **Origem:** pedido do usuário (ouvir e avaliar)

## 1. Resultado principal

As 4 vozes pedidas **não existem** no serviço Edge TTS (erro `No audio was
received` nas 4; lista oficial só tem 3 vozes PT-BR). Nada foi gerado para elas.

## 2. Arquivos para avaliação (`output/benchmark_vozes/`, mesma frase)

Frase: *"A palavra salário vem do latim salarium, ligado ao sal. Na Roma
antiga, o sal era essencial para conservar alimentos."*

| Arquivo | Voz / gênero | Duração |
|---|---|---|
| `pt-BR-AntonioNeural.mp3` | masculina (padrão atual) | 9,12 s |
| `pt-BR-FranciscaNeural.mp3` | feminina | 8,33 s |
| `pt-BR-ThalitaMultilingualNeural.mp3` | feminina (multilíngue) | 8,57 s |

## 3. Implicação

Se a avaliação preferir voz masculina, Antonio segue sem concorrente no
serviço gratuito sem login. Alternativas masculinas exigiriam outro provedor
(ex.: Google Cloud/ Azure com cadastro, ou Piper local — backlog item 1).
Aguardar veredito auditivo do usuário antes de trocar o padrão.
