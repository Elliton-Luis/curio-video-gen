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

NOVO PIPELINE DE MÍDIA (short-circuit):
- Hierarquia rígida: Pixabay → Pexels (se chave) → Wikimedia
- Para ao primeiro provedor que retorne ativo válido por cena
- Cache local por termo de busca (visual_search_terms)
- Apenas 2 termos em inglês por cena (substantivos visuais atómicos)
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..config import CurioConfig
from ..media import download_asset, get_providers
from ..media.providers import MediaAsset, MediaError, MediaProvider
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

# Limites de concorrência para busca/baixa de mídia (configuráveis via env)
import os as _os
MAX_CONCURRENT_SEARCHES = int(_os.environ.get("CURIO_MAX_CONCURRENT_SEARCHES", "3"))
MAX_CONCURRENT_DOWNLOADS = int(_os.environ.get("CURIO_MAX_CONCURRENT_DOWNLOADS", "2"))
SEARCH_TIMEOUT = float(_os.environ.get("CURIO_MEDIA_SEARCH_TIMEOUT", "15.0"))
DOWNLOAD_TIMEOUT = float(_os.environ.get("CURIO_MEDIA_DOWNLOAD_TIMEOUT", "30.0"))

# Hierarquia de provedores (ordem de prioridade)
PROVIDER_PRIORITY = ("pixabay", "pexels", "wikimedia", "openverse")

# Cache local de mídia por termo de busca
MEDIA_CACHE_DIR = "cache/media_query"


@dataclass
class SearchTask:
    """Representa uma tarefa de busca: (provider, query)."""
    provider: str
    query: str
    provider_obj: MediaProvider


def _search_with_timeout(provider_obj, query: str, timeout: float, metrics=None) -> list[MediaAsset]:
    """Executa busca com timeout."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(provider_obj.search, query, 5, metrics)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            if metrics:
                metrics.media_record_timeout()
            raise MediaError(f"{provider_obj.name}: busca timeout ({timeout}s)")


def _cache_key(query: str) -> str:
    """Gera chave de cache determinística para o termo de busca."""
    return hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]


def _get_cached_asset(cache_dir: str, query: str) -> MediaAsset | None:
    """Verifica se há ativo válido em cache para o termo de busca."""
    cache_path = Path(cache_dir) / MEDIA_CACHE_DIR
    key = _cache_key(query)
    meta_file = cache_path / f"{key}.json"
    if not meta_file.is_file():
        return None
    try:
        with open(meta_file, encoding="utf-8") as f:
            data = json.load(f)
        # Verifica se o arquivo ainda existe
        asset_file = Path(data.get("local_path", ""))
        if asset_file.is_file() and asset_file.stat().st_size > 10000:
            asset = MediaAsset.from_dict(data)
            asset.local_path = str(asset_file)
            return asset
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return None


def _save_to_cache(cache_dir: str, query: str, asset: MediaAsset) -> None:
    """Salva ativo no cache local indexado por termo de busca."""
    cache_path = Path(cache_dir) / MEDIA_CACHE_DIR
    cache_path.mkdir(parents=True, exist_ok=True)
    key = _cache_key(query)
    meta_file = cache_path / f"{key}.json"
    # Copia o arquivo para o cache de consulta se não estiver lá
    src = Path(asset.local_path)
    dst = cache_path / f"{key}{src.suffix}"
    if not dst.is_file():
        import shutil
        shutil.copy2(src, dst)
    record = asset.to_dict()
    record["local_path"] = str(dst)
    record["query"] = query
    record["cached_at"] = time.time()
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=1)


def _sanitize_query(query: str) -> str:
    """Sanitiza termo de busca: apenas alfanuméricos, espaços, hífens."""
    return re.sub(r"[^\w\s-]", "", query).strip()


def _validate_asset(asset: MediaAsset) -> bool:
    """Valida se o ativo atende aos requisitos mínimos."""
    return (
        asset.width >= 1000 and
        asset.height >= 1000 and
        asset.size_bytes > 10000 and
        asset.download_url and
        re.search(r"\.(jpe?g|png|webp)(\?|$)", asset.download_url, re.I)
    )


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


def local_queries(narration: str, k: int = 2) -> list[str]:
    """Consultas visuais offline a partir do texto do trecho (PT→EN).

    Retorna exatamente 2 termos em inglês (substantivos visuais atómicos).
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
    translated = [(c, _en(b)) for b, c in freq.items() if _en(b)]
    raw = [(c, b) for b, c in freq.items() if not _en(b)]
    translated.sort(key=lambda t: -t[0])
    raw.sort(key=lambda t: -t[0])
    keywords: list[str] = []
    for _count, term in translated + raw:
        if term not in entities and term not in keywords:
            keywords.append(term)
    # Constrói exatamente 2 termos: entidade + substantivo visual
    queries: list[str] = []
    if entities:
        queries.append(entities[0])
    if keywords:
        queries.append(keywords[0])
    # Fallback se não houver entidades
    if len(queries) < 2:
        if entities and len(entities) > 1:
            queries.append(entities[1])
        elif keywords and len(keywords) > 1:
            queries.append(keywords[1])
    return queries[:2]


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

    Com duração escolhida, vale o maior entre meta e tamanho (nunca menos
    cenas que o conteúdo pede). No Automático, só o tamanho manda.
    Limitado a 12 cenas para não explodir o nº de buscas de mídia.
    """
    by_length = scenes_stage.scenes_for_length(len(script_text.split()))
    if cfg.duration_target <= 0:
        return by_length
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


def _provider_priority_order(cfg: CurioConfig) -> list[MediaProvider]:
    """Retorna provedores na ordem de prioridade rigorosa."""
    all_providers = get_providers(cfg)
    # Ordena pela hierarquia definida
    priority_map = {name: i for i, name in enumerate(PROVIDER_PRIORITY)}
    return sorted(all_providers, key=lambda p: priority_map.get(p.name, 999))


def _search_scene_with_shortcircuit(
    ch,
    providers: list[MediaProvider],
    cfg: CurioConfig,
    max_images: int,
    metrics,
    cache_dir: str,
) -> tuple[list[dict], list[str]]:
    """
    Busca mídia para uma cena com short-circuit:
    - Para cada query, tenta provedores em ordem de prioridade
    - Para no primeiro provedor que retorne ativo válido
    - Verifica cache local antes de bater na API
    """
    warnings = []
    queries = list(ch.visual_queries) or local_queries(ch.narration)
    
    # Sanitiza queries
    queries = [_sanitize_query(q) for q in queries if q.strip()]
    if not queries:
        queries = [local_queries(ch.narration)[0]] if local_queries(ch.narration) else ["abstract concept"]
    
    picked: list[dict] = []
    picked_ids = set()
    picked_titles = set()
    
    for query in queries:
        if len(picked) >= max_images:
            break
            
        # 1. Verifica cache local primeiro
        cached = _get_cached_asset(cache_dir, query)
        if cached and _validate_asset(cached):
            if cached.asset_id not in picked_ids:
                norm_title = re.sub(r"\s+", " ", (cached.title or "").lower()).strip()
                if not norm_title or norm_title not in picked_titles:
                    picked_ids.add(cached.asset_id)
                    if norm_title:
                        picked_titles.add(norm_title)
                    picked.append({
                        "asset": cached.to_dict(),
                        "query": query,
                        "relevance": 100,  # cache hit = max relevance
                        "order": len(picked),
                        "from_cache": True
                    })
                    if metrics:
                        metrics.media_cache_hits += 1
                        metrics.media_record_asset_reused()
                    continue
        
        # 2. Busca com short-circuit por provedor
        asset_found = False
        for prov in providers:
            # Skip se provedor desativado por 429
            if getattr(prov, "_disabled", False):
                continue
                
            if metrics:
                metrics.media_search(prov.name)
            
            try:
                results = _search_with_timeout(prov, query, SEARCH_TIMEOUT, metrics)
            except MediaError as exc:
                # Se for 429, desativa provedor temporariamente
                if "429" in str(exc) or "Too Many Requests" in str(exc):
                    prov._disabled = True
                    if metrics:
                        metrics.media_record_timeout()
                    print(f"AVISO: {prov.name} desativado por rate limit (429)", file=sys.stderr)
                continue
            
            if metrics:
                metrics.media_record_results(prov.name, len(results))
            
            # Filtra e valida resultados
            for cand in results:
                if not _validate_asset(cand):
                    continue
                if cand.asset_id in picked_ids:
                    continue
                norm_title = re.sub(r"\s+", " ", (cand.title or "").lower()).strip()
                if norm_title and norm_title in picked_titles:
                    continue
                
                # Tenta baixar
                try:
                    asset = download_asset(cand, cfg.cache_dir, metrics)
                except MediaError as exc:
                    if metrics:
                        metrics.media_record_asset_rejected()
                    continue
                
                # Sucesso! Salva no cache de query e adiciona
                _save_to_cache(cache_dir, query, asset)
                
                picked_ids.add(cand.asset_id)
                if norm_title:
                    picked_titles.add(norm_title)
                picked.append({
                    "asset": asset.to_dict(),
                    "query": query,
                    "relevance": _relevance(query, cand),
                    "order": len(picked),
                    "from_cache": False
                })
                asset_found = True
                break  # Short-circuit: para no primeiro provedor que funcionar
            
            if asset_found:
                break  # Short-circuit: para de tentar outros provedores para esta query
        
        if not asset_found and metrics:
            metrics.media_record_asset_rejected()
    
    if not picked:
        msg = (f"cena {ch.id}: sem mídia relevante "
               f"({', '.join(queries) or 'sem consultas'}) — fallback")
        warnings.append(msg)
        print(f"AVISO: {msg}", file=sys.stderr)
    
    first = picked[0]["asset"] if picked else None
    return [{
        "chapter_id": ch.id,
        "asset": first,
        "assets": picked,
        "reused_from": None
    }], warnings


def fetch_media_multi(chapters, cfg: CurioConfig,
                      max_images: int = 3,
                      metrics=None) -> tuple[list[dict], list[str]]:
    """Busca ativos por cena com short-circuit rigoroso e cache local.

    Hierarquia: Pixabay → Pexels → Wikimedia → Openverse
    Para no primeiro provedor que retornar ativo válido por query.
    Cache local indexado por termo de busca (visual_search_terms).
    """
    max_images = max(1, min(5, int(max_images)))
    providers = _provider_priority_order(cfg)
    if not providers:
        return _fetch_media_fallback(chapters, max_images, warnings=[])
    
    all_warnings = []
    scenes = []
    
    for ch in chapters:
        scene_scenes, scene_warnings = _search_scene_with_shortcircuit(
            ch, providers, cfg, max_images, metrics, cfg.cache_dir
        )
        scenes.extend(scene_scenes)
        all_warnings.extend(scene_warnings)
    
    _resolve_reuse_multi(scenes)
    return scenes, all_warnings


def _fetch_media_fallback(chapters, max_images: int, warnings: list) -> tuple[list[dict], list[str]]:
    """Fallback quando não há providers configurados."""
    scenes = []
    for ch in chapters:
        msg = f"cena {ch.id}: sem providers de mídia — fallback"
        warnings.append(msg)
        print(f"AVISO: {msg}", file=sys.stderr)
        scenes.append({"chapter_id": ch.id, "asset": None, "assets": [], "reused_from": None})
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
