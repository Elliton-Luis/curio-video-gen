"""Modo roteiro-pronto: organiza mídia sobre uma narração já existente.

Este módulo NUNCA gera, reescreve ou altera o roteiro: o texto fornecido
pelo usuário é preservado byte a byte (só aparas de borda). A divisão em
trechos/cenas reaproveita `stages.scenes` com validação literal — se a
junção das narrações não reproduzir o roteiro, falha em voz alta em vez
de entregar narração adulterada.

Para cada trecho, busca-se até `max_images` imagens com gate de
relevância (título precisa conter algo da consulta — nunca associação
falsa só para preencher espaço). O plano visual distribui as imagens no
tempo da cena com sobreposição e entradas suaves/variadas (álbum de
fotografias): a nova imagem entra sobre a atual, assume o destaque e a
próxima repete o ciclo. Com uma única imagem adequada, o render usa Ken
Burns sutil em vez de inventar uma segunda.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata

from ..config import CurioConfig
from ..media import download_asset, get_providers
from ..media.providers import MediaAsset, MediaError
from . import scenes as scenes_stage

# Entradas suaves e variadas, sem repetição consecutiva no vídeo inteiro.
# Nomes estáveis: vão para timeline.json e para o render — renomear quebra
# compatibilidade ("fade_scale" legado ainda renderiza; novos planos usam
# "fade"). A ordem por vídeo é embaralhada com seed do slug (reprodutível),
# e o contador global atravessa cenas: inserções consecutivas nunca repetem.
ENTRY_STYLES = ("drop_in", "slide_left", "slide_right", "fade",
                "scale_in", "tilt_in")
LEGACY_STYLES = ("fade_scale",)

# SFX discretos em ALGUMAS inserções (nunca todas): 1 a cada 3 overlays,
# alternando swish (ruído filtrado) e tap (pulso grave curto). Baixos o
# suficiente para nunca competir com a narração; cenas de 1 foto (sem
# inserção) nunca têm SFX.
SFX_EVERY = 3
SFX_KINDS = ("swish", "tap")
SFX_GAIN_DB = -26
SFX_DURATION = 0.35

# Pequenas diferenças de composição entre fotos sobrepostas (álbum natural).
# Índices por ordem da imagem na cena.
ROTATIONS_DEG = (-5.0, 4.0, -3.0, 6.0, -4.0)
OFFSET_DX = (0, -34, 30, -22, 26)
OFFSET_DY = (0, -24, 18, 26, -18)

# Largura do cartão-foto em relação ao vídeo (0.85 ≈ 920/1080). O cartão
# fica centralizado na metade superior: a base inferior (~360 px) é reserva
# das legendas — imagens nunca cobrem a área de leitura.
CARD_WIDTH_RATIO = 0.85
SUBTITLE_RESERVE_PX = 360

MIN_IMAGE_SECONDS = 1.0
MAX_SCENES_SCRIPT_MODE = 12


# Heurística offline p/ consultas visuais (sem chave NVIDIA as cenas locais
# não trazem `visual_queries` — sem isto, tudo cairia em fallback). Extrai
# palavras-cheia do trecho e verte substantivos visuais PT→EN, pois os
# bancos de mídia respondem melhor em inglês. O gate de relevância continua
# valendo: só entra imagem cujo título contenha a consulta.
PT_STOP = {
    "para", "como", "mais", "muito", "isso", "esse", "esta", "este", "aquele",
    "aquela", "foram", "eram", "sido", "entre", "sobre", "quando", "onde",
    "qual", "quais", "todo", "toda", "todos", "todas", "cada", "muita",
    "muitas", "muitos", "pouco", "pouca", "mesmo", "mesma", "outro", "outra",
    "outros", "outras", "depois", "antes", "durante", "sempre", "nunca",
    "também", "através", "porque", "porém", "entretanto", "portanto",
    "então", "assim", "aqui", "agora", "hoje", "ainda", "mesmo", "coisa",
    "algo", "alguém", "ninguém", "tudo", "nada", "seja", "sejam", "pode",
    "podem", "deve", "devem", "fazer", "fez", "fazem", "seria", "seriam",
    "tinha", "tinham", "esteve", "foram", "sendo", "teria", "teriam",
    "semper", "pois", "qualquer", "tanto", "quanto", "desde", "até",
    "meio", "grande", "pequeno", "novo", "velho", "primeiro", "último",
}

PT_EN = {
    "roma": "rome", "romano": "roman", "romanos": "roman", "imperio": "empire",
    "imperador": "emperor", "legiao": "roman legion", "legioes": "roman legion",
    "soldado": "soldier", "exercito": "army", "guerra": "war",
    "batalha": "battle", "fronteira": "frontier", "barbaro": "barbarian",
    "barbaros": "barbarians", "guarda": "guard", "capacete": "helmet",
    "espada": "sword", "escudo": "shield", "moeda": "coin", "salario": "salary",
    "dinheiro": "money", "pagamento": "payment", "comercio": "trade",
    "mercado": "market", "sal": "salt", "pao": "bread", "vinho": "wine",
    "comida": "food", "igreja": "church", "templo": "temple", "castelo": "castle",
    "piramide": "pyramid", "estatua": "statue", "pintura": "painting",
    "retrato": "portrait", "mapa": "map", "livro": "book", "carta": "letter",
    "documento": "document", "fotografia": "photograph", "cerebro": "brain",
    "mente": "mind", "cabeca": "head", "mao": "hand", "corpo": "body",
    "doenca": "disease", "peste": "plague", "medico": "doctor", "hospital": "hospital",
    "cidade": "city", "rua": "street", "casa": "house", "aldeia": "village",
    "campo": "field", "colheita": "harvest", "mar": "sea", "navio": "ship",
    "rio": "river", "montanha": "mountain", "arvore": "tree", "flor": "flower",
    "floresta": "forest", "deserto": "desert", "ceu": "sky", "sol": "sun",
    "lua": "moon", "estrela": "star", "terra": "earth", "fogo": "fire",
    "agua": "water", "pedra": "stone", "ouro": "gold", "prata": "silver",
    "ferro": "iron", "cobre": "copper", "bronze": "bronze", "cavalo": "horse",
    "cao": "dog", "cachorro": "dog", "gato": "cat", "passaro": "bird",
    "peixe": "fish", "homem": "man", "mulher": "woman", "crianca": "child",
    "criancas": "children", "povo": "people", "multidao": "crowd", "rei": "king",
    "rainha": "queen", "campones": "peasant", "trabalho": "work",
    "trabalhador": "worker", "escola": "school", "teatro": "theater",
    "musica": "music", "danca": "dance", "festa": "festival", "religiao": "religion",
    "deus": "god", "mito": "myth", "lenda": "legend", "historia": "history",
    "antigo": "ancient", "ruina": "ruins", "ruinas": "ruins", "muralha": "wall",
    "ponte": "bridge", "estrada": "road", "trem": "train", "carro": "car",
    "aviao": "airplane", "fabrica": "factory", "maquina": "machine",
    "ciencia": "science", "laboratorio": "laboratory", "experimento": "experiment",
    "planeta": "planet", "satelite": "satellite", "telescopio": "telescope",
    "livraria": "bookstore", "biblioteca": "library", "escrita": "writing",
    "palavra": "word", "lingua": "language", "numero": "number", "tempo": "time",
    "inverno": "winter", "verao": "summer", "chuva": "rain", "neve": "snow",
    "vulcao": "volcano", "terremoto": "earthquake", "navio": "ship",
    "porto": "harbor", "farol": "lighthouse", "ilha": "island", "praia": "beach",
    "jardim": "garden", "parque": "park", "mercado": "market", "loja": "shop",
    "padaria": "bakery", "cozinha": "kitchen", "mesa": "table", "cadeira": "chair",
    "janela": "window", "porta": "door", "chave": "key", "relogio": "clock",
    "espelho": "mirror", "vela": "candle", "faca": "knife", "panela": "pot",
    "prato": "plate", "copo": "glass", "garrafa": "bottle", "cesta": "basket",
    "roupa": "clothes", "sapato": "shoe", "chapeu": "hat", "coroa": "crown",
    "anel": "ring", "colar": "necklace", "joia": "jewel", "tesouro": "treasure",
    "tumba": "tomb", "mumia": "mummy", "fossil": "fossil", "dinossauro": "dinosaur",
    "esqueleto": "skeleton", "crânio": "skull", "cranio": "skull",
    "sangue": "blood", "coração": "heart", "coracao": "heart", "olho": "eye",
    "rosto": "face", "maos": "hands", "pes": "feet", "nacao": "nation",
    "bandeira": "flag", "governo": "government", "eleicao": "election",
    "protesto": "protest", "revolucao": "revolution", "independencia": "independence",
    "escravidao": "slavery", "colonia": "colony", "reino": "kingdom",
    "republica": "republic", "senado": "senate", "lei": "law", "justica": "justice",
    "prisao": "prison", "crime": "crime", "pirata": "pirate", "viking": "viking",
    "nordico": "norse", "egito": "egypt", "grecia": "greece", "grego": "greek",
    "troia": "troy", "atenas": "athens", "esparta": "sparta", "gladiador": "gladiator",
    "coliseu": "colosseum", "aqueduto": "aqueduct", "foro": "forum",
    "cesar": "caesar", "augusto": "augustus", "nero": "nero",
    "constantinopla": "constantinople", "bizancio": "byzantium",
    "idade": "age", "seculo": "century", "medieval": "medieval",
    "renascimento": "renaissance", "iluminismo": "enlightenment",
    "industrial": "industrial", "moderno": "modern", "contemporaneo": "contemporary",
    "provincia": "province", "imposto": "tax", "tributo": "tribute",
    "germanico": "germanic", "mosaico": "mosaic", "invasao": "invasion",
    "queda": "fall", "crise": "crisis", "corrupcao": "corruption",
    "sucessao": "succession", "inflacao": "inflation", "muralhas": "walls",
    "pretoriana": "praetorian guard", "reforma": "reform", "senador": "senator",
    "tribuno": "tribune", "consul": "consul", "ditador": "dictator",
    "escravo": "slave", "gladiadores": "gladiators", "circo": "circus",
    "anfiteatro": "amphitheater", "termas": "baths", "vila": "villa",
    "palacio": "palace", "tesouro": "treasure",
}


def _en(base: str) -> str | None:
    """Verte PT→EN tentando singular (plurais -s/-es) antes de desistir."""
    hit = PT_EN.get(base)
    if hit:
        return hit
    for cand in (base[:-1] if base.endswith("s") else "",
                 base[:-2] if base.endswith("es") else ""):
        if cand and cand in PT_EN:
            return PT_EN[cand]
    return None


def _strip_acc(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in norm if not unicodedata.combining(c))


def local_queries(narration: str, k: int = 4) -> list[str]:
    """Consultas visuais offline a partir do texto do trecho (PT→EN).

    Nomes próprios no meio da frase primeiro (início de frase capitaliza
    qualquer palavra — "Não"/"Foi" não são entidades), depois palavras-cheia
    por frequência. Estrutura: entidade mais forte sozinha, duplas de termos
    e os melhores termos avulsos como rede de segurança. O ranking por
    relevância prefere os matches mais específicos; os avulsos só vencem
    quando nada melhor existe (fallback honesto em vez de tela vazia).
    """
    # Palavras que abrem frase (capitalização gramatical, não entidade).
    first_words = set()
    for sent in re.split(r"(?<=[.!?…])\s+", narration.strip()):
        m = re.match(r"\W*([A-Za-zÀ-ÿ]+)", sent)
        if m:
            first_words.add(_strip_acc(m.group(1)))
    # Entidades: capitalizada no MEIO da frase, ou 1ª palavra só se for
    # substantivo próprio conhecido (ex.: Roma, Cesar).
    mids = set(re.findall(r"[a-zà-ÿ]\s+([A-ZÀ-Þ][a-zà-ÿ]{2,})",
                          " " + narration))
    entities: list[str] = []
    for ent in dict.fromkeys(list(mids) + re.findall(
            r"[A-ZÀ-Þ][a-zà-ÿ]{2,}", narration)):
        base = _strip_acc(ent)
        if base in PT_STOP or len(base) < 3:
            continue
        if ent not in mids and base not in PT_EN:
            continue  # capitalizada só por abrir frase ("Não", "Virou")
        term = PT_EN.get(base, ent)
        if term not in entities:
            entities.append(term)
    words = re.findall(r"[a-zà-ÿ]{4,}", narration.lower())
    freq: dict[str, int] = {}
    for w in words:
        base = _strip_acc(w)
        if base in PT_STOP:
            continue
        freq[base] = freq.get(base, 0) + 1
    # Traduzidos primeiro (substantivos visuais conhecidos); crus por último
    # (verbo cru como "virou" só vira consulta se nada melhor existir).
    translated = [(c, _en(b)) for b, c in freq.items() if _en(b)]
    raw = [(c, b) for b, c in freq.items() if not _en(b)]
    translated.sort(key=lambda t: -t[0])
    raw.sort(key=lambda t: -t[0])
    keywords: list[str] = []
    for _count, term in translated + raw:
        if term not in entities and term not in keywords:
            keywords.append(term)
    queries: list[str] = []
    if entities:
        queries.append(entities[0])
    top = (entities + keywords)[:6]
    for i in range(0, len(top) - 1, 2):
        queries.append(" ".join(top[i:i + 2]))
    for term in (entities[:1] + keywords[:2]):
        if term not in queries:
            queries.append(term)
    seen_q, out = set(), []
    for q in queries:
        if q and q not in seen_q:
            seen_q.add(q)
            out.append(q)
    return out[:max(1, k)]


def read_script_file(path: str) -> str:
    """Lê o roteiro exatamente como fornecido (sem reescrever).

    Só remove BOM e espaços em branco das bordas. Todo o resto — ordem,
    palavras, pontuação — é preservado para o TTS e as legendas.
    """
    if path == "-":
        import sys as _sys
        text = _sys.stdin.read()
    else:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"roteiro não encontrado: {path}")
        with open(path, encoding="utf-8-sig") as fh:
            text = fh.read()
    text = text.strip()
    if not text:
        raise ValueError("roteiro vazio — informe um texto para narrar")
    return text


def scenes_for_script(script_text: str, cfg: CurioConfig) -> int:
    """Nº de cenas p/ roteiro pronto: acompanha o TAMANHO REAL do texto.

    `scenes_for_duration` usa só a duração-alvo (boa p/ roteiro gerado sob
    medida). Aqui o texto já existe e pode ser mais longo: estima a duração
    por WPM de leitura e usa o maior dos dois, limitado a 12 cenas para não
    explodir o nº de buscas de mídia.
    """
    words = len(script_text.split())
    est_dur = words / scenes_stage.WORDS_PER_MINUTE * 60
    by_length = max(3, min(MAX_SCENES_SCRIPT_MODE, round(est_dur / 9)))
    return max(scenes_stage.scenes_for_duration(cfg.duration_target), by_length)


def validate_preserved(original: str, chapters) -> None:
    """Garante que a divisão não reescreveu nada (falha em voz alta)."""
    joined = " ".join(c.narration for c in chapters)
    if scenes_stage._norm(joined) != scenes_stage._norm(original):
        raise ValueError(
            "divisão em cenas não reproduz o roteiro literal — "
            "recusando para não adulterar a narração")


def split_script(script_text: str, cfg: CurioConfig,
                 n_scenes: int | None = None,
                 metrics=None) -> tuple[list, str]:
    """Divide o roteiro preservado em cenas (fonte: 'nvidia' | 'local')."""
    chapters, source = scenes_stage.build_chapters(
        script_text, cfg,
        n_scenes=n_scenes or scenes_for_script(script_text, cfg),
        metrics=metrics)
    validate_preserved(script_text, chapters)
    return chapters, source


def _query_terms(query: str) -> list[str]:
    stop = {"the", "and", "with", "from", "into", "para", "uma", "para"}
    return [t.lower() for t in query.replace(",", " ").split()
            if len(t) > 2 and t.lower() not in stop]


def _relevance(query: str, asset: MediaAsset) -> int:
    haystack = f"{asset.title}".lower()
    return sum(1 for term in _query_terms(query) if term in haystack)


def fetch_media_multi(chapters, cfg: CurioConfig,
                      max_images: int = 3,
                      metrics=None) -> tuple[list[dict], list[str]]:
    """Busca até `max_images` assets relevantes por cena (gate > 0).

    Ordena por relevância consulta↔título; em empate, prefere assets ainda
    não usados em outras cenas (diversidade sem inventar relação). Falha de
    uma cena vira fallback honesto com aviso — nunca associação falsa.
    """
    max_images = max(1, min(5, int(max_images)))
    providers = get_providers(cfg)
    search_memo: dict[tuple[str, str], list] = {}
    used_count: dict[str, int] = {}
    scenes, warnings = [], []
    for ch in chapters:
        queries = list(ch.visual_queries) or local_queries(ch.narration)
        ranked: list[tuple[int, str, MediaAsset]] = []
        seen = set()
        for query in queries:
            for prov in providers:
                memo_key = (prov.name, query)
                if memo_key not in search_memo:
                    try:
                        search_memo[memo_key] = prov.search(query, metrics=metrics)
                    except MediaError as exc:
                        print(f"AVISO: {exc} — tentando próxima fonte.",
                              file=sys.stderr)
                        search_memo[memo_key] = []
                for cand in search_memo[memo_key]:
                    if cand.asset_id in seen:
                        continue
                    seen.add(cand.asset_id)
                    score = _relevance(query, cand)
                    if score > 0:
                        ranked.append((score, query, cand))
        # Diversidade: menos usados primeiro; depois maior relevância.
        ranked.sort(key=lambda r: (used_count.get(r[2].asset_id, 0), -r[0]))
        picked: list[dict] = []
        picked_ids = set()
        picked_titles = set()
        for score, query, cand in ranked:
            if len(picked) >= max_images:
                break
            if cand.asset_id in picked_ids:
                continue
            # Mesma cena, arquivo duplicado no Commons (títulos idênticos):
            # pula para não exibir a "mesma foto" duas vezes seguidas.
            norm_title = re.sub(r"\s+", " ", (cand.title or "").lower()).strip()
            if norm_title and norm_title in picked_titles:
                continue
            try:
                asset = download_asset(cand, cfg.cache_dir, metrics)
            except MediaError as exc:
                print(f"AVISO: {exc} — tentando próximo asset.",
                      file=sys.stderr)
                continue
            picked_ids.add(cand.asset_id)
            if norm_title:
                picked_titles.add(norm_title)
            used_count[cand.asset_id] = used_count.get(cand.asset_id, 0) + 1
            picked.append({"asset": asset.to_dict(), "query": query,
                           "relevance": score, "order": len(picked)})
        if not picked:
            msg = (f"cena {ch.id}: sem mídia relevante "
                   f"({', '.join(queries) or 'sem consultas'}) — fallback")
            warnings.append(msg)
            print(f"AVISO: {msg}", file=sys.stderr)
        first = picked[0]["asset"] if picked else None
        scenes.append({"chapter_id": ch.id,
                       "asset": first,  # compat: fluxos antigos usam 1 imagem
                       "assets": picked,
                       "reused_from": None})
    _resolve_reuse_multi(scenes)
    return scenes, warnings


def _resolve_reuse_multi(scenes: list[dict]) -> None:
    """Cena sem asset reusa as imagens relevantes mais próximas (outro trecho).

    Só o gradiente resta se NENHUMA cena tiver mídia. Mantém `asset`
    (singular) sincronizado com `assets[0]` para os fluxos legados.
    """
    have = [s for s in scenes if s["assets"]]
    if not have:
        return
    for s in scenes:
        if s["assets"]:
            continue
        cid = s["chapter_id"]
        nearest = min(have, key=lambda h: (abs(h["chapter_id"] - cid),
                                           0 if h["chapter_id"] < cid else 1))
        s["assets"] = [dict(entry, order=i)
                       for i, entry in enumerate(nearest["assets"])]
        s["asset"] = s["assets"][0]["asset"]
        s["reused_from"] = nearest["chapter_id"]
        print(f"AVISO: cena {cid} reusa imagem(ns) da cena "
              f"{nearest['chapter_id']} (sem mídia própria).", file=sys.stderr)


def _overlap_for(duration: float, n: int, cap: float) -> float:
    if n <= 1:
        return 0.0
    return max(0.4, min(cap, duration * 0.15))


def plan_scene_images(duration: float, n: int,
                      overlap_cap: float = 0.9,
                      styles: tuple = ENTRY_STYLES,
                      start: int = 0) -> list[dict]:
    """Distribui `n` imagens na cena com sobreposição entre elas.

    Retorna por imagem: ordem, início (offset na cena), duração, transição,
    escala do cartão, rotação e deslocamentos. A primeira imagem abre em
    tela cheia; as seguintes entram como foto sobre foto e permanecem por
    cima até o fim da cena (pilha de álbum). `styles`/`start` posicionam a
    cena na sequência global do vídeo (sem repetição consecutiva); com 1
    imagem, o plano é vazio (render usa Ken Burns).
    """
    duration = max(0.5, float(duration))
    # Garante ≥1 s por imagem: reduz a conta em vez de piscar fotos.
    while n > 1 and duration / n < MIN_IMAGE_SECONDS:
        n -= 1
    if n <= 1:
        return []
    overlap = _overlap_for(duration, n, overlap_cap)
    step = duration / n
    base_entry = min(0.9, max(0.4, step * 0.3))
    plan = []
    for i in range(n):
        start_t = round(i * step, 3)
        dur = round(duration - start_t if i == n - 1 else step + overlap, 3)
        if i == 0:
            transition, entry_dur = "base", 0.0
        else:
            transition = styles[(start + i - 1) % len(styles)]
            # Micro-variação determinística: inserções vizinhas assentam
            # em ritmos levemente distintos (nada mecânico, nada exagerado).
            entry_dur = round(base_entry + ((start + i) % 3) * 0.05, 3)
        plan.append({
            "order": i,
            "start": start_t,
            "duration": dur,
            # i=0 é a base (tela cheia): sem transição de entrada.
            "transition": transition,
            "scale": 1.0 if i == 0 else CARD_WIDTH_RATIO,
            "rotation_deg": 0.0 if i == 0 else ROTATIONS_DEG[i % len(ROTATIONS_DEG)],
            "dx": 0 if i == 0 else OFFSET_DX[i % len(OFFSET_DX)],
            "dy": 0 if i == 0 else OFFSET_DY[i % len(OFFSET_DY)],
            "entry_dur": entry_dur,
        })
    return plan


def _spec_images(entries: list[dict], duration: float,
                 overlap_cap: float = 0.9,
                 styles: tuple = ENTRY_STYLES,
                 start: int = 0) -> tuple[list[dict], int]:
    """Monta a lista `images` de um trecho (0, 1 ou N fotos).

    Uma única imagem adequada vira base em tela cheia (o render aplica Ken
    Burns sutil) em vez de fallback — nunca se inventa uma segunda foto.
    Retorna (images, consumidos), onde consumidos é quantas transições da
    sequência global foram usadas (para a próxima cena não repetir).
    """
    duration = max(0.5, float(duration))
    if len(entries) == 1:
        entry = entries[0]
        asset = entry.get("asset") or {}
        return [{
            "order": 0,
            "query": entry.get("query", ""),
            "asset_id": asset.get("asset_id", ""),
            "title": asset.get("title", ""),
            "provider": asset.get("provider", ""),
            "author": asset.get("author", ""),
            "license": asset.get("license", ""),
            "source_url": asset.get("source_url", ""),
            "local_path": asset.get("local_path", ""),
            "kind": asset.get("kind", "image"),
            "start": 0.0,
            "duration": round(duration, 3),
            "transition": "base",
            "scale": 1.0,
            "rotation_deg": 0.0,
            "dx": 0,
            "dy": 0,
            "entry_dur": 0.0,
            "sfx": None,
        }], 0
    plan = plan_scene_images(duration, len(entries), overlap_cap,
                             styles, start)
    # Plano pode encurtar a conta (cena curta): corta as excedentes.
    images = []
    for spec, entry in zip(plan, entries):
        asset = entry.get("asset") or {}
        images.append({
            "order": spec["order"],
            "query": entry.get("query", ""),
            "asset_id": asset.get("asset_id", ""),
            "title": asset.get("title", ""),
            "provider": asset.get("provider", ""),
            "author": asset.get("author", ""),
            "license": asset.get("license", ""),
            "source_url": asset.get("source_url", ""),
            "local_path": asset.get("local_path", ""),
            "kind": asset.get("kind", "image"),
            "start": spec["start"],
            "duration": spec["duration"],
            "transition": spec["transition"],
            "scale": spec["scale"],
            "rotation_deg": spec["rotation_deg"],
            "dx": spec["dx"],
            "dy": spec["dy"],
            "entry_dur": spec["entry_dur"],
            "sfx": None,
        })
    consumed = len([im for im in images if im["order"] > 0])
    return images, consumed


def _shuffled_styles(seed: str) -> list[str]:
    """Ordem de entradas do vídeo: embaralhada com seed, sem repetição.

    Embaralhar os 6 estilos e ciclar garante vizinhas sempre distintas;
    o seed (slug do projeto) torna o resultado reprodutível entre runs.
    """
    import random
    order = list(ENTRY_STYLES)
    random.Random(seed or "curio").shuffle(order)
    return order


def _assign_sfx(images: list[dict], scene_start: float,
                overlay_counter: int, sfx_ordinal: int,
                enabled: bool) -> tuple[int, int]:
    """Marca SFX em ~1/3 das inserções (nunca na base, nunca em todas).

    Contadores globais ao vídeo: a cadência não recomeça a cada cena e os
    dois tipos (swish/tap) alternam. Tempos absolutos (cena+offset) para o
    render posicionar o som junto da entrada da foto.
    """
    for img in images:
        if img["order"] == 0:
            img["sfx"] = None
            continue
        if enabled and overlay_counter % SFX_EVERY == 0:
            img["sfx"] = {
                "kind": SFX_KINDS[sfx_ordinal % len(SFX_KINDS)],
                "at": round(scene_start + img["start"], 3),
                "gain_db": SFX_GAIN_DB,
                "duration": SFX_DURATION,
            }
            sfx_ordinal += 1
        else:
            img["sfx"] = None
        overlay_counter += 1
    return overlay_counter, sfx_ordinal


def build_visual_timeline(chapters, media_scenes: list[dict],
                          overlap_cap: float = 0.9, seed: str = "",
                          sfx: bool = True) -> list[dict]:
    """Timeline visual renderizável: um trecho por cena com suas imagens.

    Cada trecho carrega texto/narração original, início/fim, imagens em
    ordem (com consulta que a encontrou), duração, transição e geometria
    de sobreposição. Capítulos precisam ter `start/end` já definidos
    (WordBoundary reais ou estimativa WPM) antes desta chamada. A sequência
    de transições atravessa o vídeo sem repetição consecutiva (ordem
    embaralhada com `seed`); SFX discretos marcam ~1/3 das inserções.
    """
    by_chapter = {s["chapter_id"]: s for s in media_scenes}
    styles = _shuffled_styles(seed)
    overlay_counter, sfx_ordinal, style_pos = 0, 0, 0
    timeline = []
    for ch in chapters:
        scene = by_chapter.get(ch.id, {})
        start, end = round(float(ch.start), 3), round(float(ch.end), 3)
        dur = max(0.5, end - start)
        images, consumed = _spec_images(list(scene.get("assets") or []), dur,
                                       overlap_cap, styles, style_pos)
        style_pos += consumed
        overlay_counter, sfx_ordinal = _assign_sfx(
            images, start, overlay_counter, sfx_ordinal, sfx)
        timeline.append({
            "chapter_id": ch.id,
            "narration": ch.narration,  # original, intocado
            "start": start,
            "end": end,
            "images": images,
            "fallback": not images,
            "reused_from": scene.get("reused_from"),
        })
    return timeline


def retime_visual_timeline(visual_timeline: list[dict],
                           chapters) -> list[dict]:
    """Replaneja tempos das imagens após mudança de duração (ex.: finalize).

    Mantém ordem, consultas, assets, transições, SFX e geometria; só
    recalcula início/duração de cada imagem (e o instante `at` do SFX) a
    partir dos novos `start/end`.
    """
    times = {c.id: (float(c.start), float(c.end)) for c in chapters}
    out = []
    for trecho in visual_timeline:
        start, end = times.get(trecho["chapter_id"],
                               (trecho["start"], trecho["end"]))
        dur = max(0.5, end - start)
        old = {im["order"]: im for im in trecho["images"]}
        entries = [{"query": im.get("query", ""),
                    "asset": {k: im.get(k, "") for k in
                              ("asset_id", "title", "provider", "author",
                               "license", "source_url", "download_url",
                               "local_path", "kind")}}
                   for im in trecho["images"]]
        images, _consumed = _spec_images(entries, dur)
        for img in images:
            prev = old.get(img["order"], {})
            if prev.get("transition") not in (None, "base"):
                img["transition"] = prev["transition"]
            sfx = prev.get("sfx")
            if img["order"] > 0 and isinstance(sfx, dict):
                img["sfx"] = {**sfx,
                              "at": round(start + img["start"], 3)}
            else:
                img["sfx"] = None
        trecho = dict(trecho)
        trecho.update(start=round(start, 3), end=round(end, 3),
                      images=images, fallback=not images)
        out.append(trecho)
    return out


def visual_summary(visual_timeline: list[dict]) -> str:
    """Linha legível por trecho p/ logs: cena, nº de imagens, transições."""
    parts = []
    for t in visual_timeline:
        if t["fallback"]:
            parts.append(f"cena {t['chapter_id']}: fallback")
            continue
        tr = ",".join(i["transition"] for i in t["images"][1:])
        nsfx = sum(1 for i in t["images"] if i.get("sfx"))
        parts.append(f"cena {t['chapter_id']}: {len(t['images'])} img"
                     + (f" [{tr}]" if tr else " [base]")
                     + (f" +{nsfx}sfx" if nsfx else ""))
    return "; ".join(parts)


def _slug_from_text(text: str, fallback: str = "roteiro") -> str:
    from ..slug import slugify
    first = re.split(r"(?<=[.!?…])\s+|\n+", text.strip())[0]
    return slugify(first[:60]) or fallback
