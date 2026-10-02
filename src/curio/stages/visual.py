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
import contextvars
import functools
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from .. import ffmpeg as ff
from .. import textnorm
from ..config import CurioConfig
from ..media import download_asset, get_providers
from ..media.providers import (
    MediaAsset,
    MediaError,
    MediaProvider,
    classify_rights,
    min_dimension,
)
from . import media_rules
from . import scenes as scenes_stage
from .visual_timeline import (_assign_sfx, _shuffled_styles, _spec_images,
                              insertion_scenes, mark_insertion,
                              order_for_insertion)

# Limites de concorrência para busca/baixa de mídia (configuráveis via env)
import os as _os
MAX_CONCURRENT_SEARCHES = int(_os.environ.get("CURIO_MAX_CONCURRENT_SEARCHES", "3"))
MAX_CONCURRENT_DOWNLOADS = int(_os.environ.get("CURIO_MAX_CONCURRENT_DOWNLOADS", "2"))
SEARCH_TIMEOUT = float(_os.environ.get("CURIO_MEDIA_SEARCH_TIMEOUT", "15.0"))
DOWNLOAD_TIMEOUT = float(_os.environ.get("CURIO_MEDIA_DOWNLOAD_TIMEOUT", "30.0"))
_SEARCH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(1, MAX_CONCURRENT_SEARCHES), thread_name_prefix="curio-search")
_DOWNLOAD_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(1, MAX_CONCURRENT_DOWNLOADS), thread_name_prefix="curio-download")

# Hierarquia de provedores (ordem de prioridade). Do mais específico para
# o mais genérico: primeiro os bancos de foto com chave, depois os acervos
# abertos, e o Unsplash por ÚLTIMO — é a foto mais bonita e a que mais
# foge do assunto, então só entra quando nada mais serviu, e com orçamento
# próprio de 15 requisições (a cota demo dele é 50/hora e um vídeo estoura
# isso em duas cenas).
PROVIDER_PRIORITY = ("pixabay", "pexels", "nasa",
                     "wikimedia", "openverse", "met", "aic", "unsplash")

# Cache local de mídia por termo de busca
MEDIA_CACHE_DIR = "cache/media_query"

# Quantos candidatos se coleta por consulta antes de escolher. O lineup
# antigo aceitava 1 asset do primeiro provedor; recolher uma dúzia e
# ordenar é o que permite escolher em vez de tomar o que veio.
CANDIDATE_MULTIPLIER = 4
# Rejeições que a folha de contato guarda por cena (o resto é ruído).
REJECTED_KEPT = 8


def _submit_search(provider_obj, query: str, metrics=None):
    """Submit one provider search, preserving run-log context in worker."""
    context = contextvars.copy_context()
    return _SEARCH_EXECUTOR.submit(context.run, provider_obj.search,
                                   query, 5, metrics)


def _search_with_timeout(provider_obj, query: str, timeout: float,
                         metrics=None) -> list[MediaAsset]:
    """Bound wait without executor context-manager's blocking shutdown.

    Old `with ThreadPoolExecutor` waited for worker exit while leaving the
    context, so timeout never returned at timeout. Provider HTTP calls have
    their own finite network timeout; cancel stops queued work and caller
    returns immediately. A running urllib call ends on its socket timeout.
    """
    future = _submit_search(provider_obj, query, metrics)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        if metrics:
            metrics.media_record_timeout()
        raise MediaError(f"{provider_obj.name}: busca timeout ({timeout}s)") from exc


def _submit_download(asset: MediaAsset, cache_dir: str, metrics=None):
    """Submit one download while preserving execution log context."""
    context = contextvars.copy_context()
    return _DOWNLOAD_EXECUTOR.submit(context.run, _download_with_origin,
                                     asset, cache_dir, metrics)


def _download_with_origin(asset: MediaAsset, cache_dir: str, metrics=None):
    """Download one asset and report whether bytes came from local cache."""
    from ..media.cache import _safe_ext
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", asset.asset_id) or "asset"
    path = os.path.join(cache_dir, "media", asset.provider,
                        safe_id + _safe_ext(asset.download_url))
    cached = os.path.isfile(path) and os.path.isfile(path + ".json")
    result = download_asset(asset, cache_dir, metrics)
    return result, "cache" if cached else "download"


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
            asset.used_in = ""  # uso anterior não vale p/ este vídeo
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
    record["used_in"] = ""  # uso é por vídeo, nunca do cache
    record["cached_at"] = time.time()
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=1)


def _sanitize_query(query: str) -> str:
    """Sanitiza termo de busca: apenas alfanuméricos, espaços, hífens."""
    return re.sub(r"[^\w\s-]", "", query).strip()


# O gate de metadados é `media_rules.asset_gate_reason`: era a terceira
# cópia da mesma regra, e a única que devolvia booleano — o que jogava fora
# a informação que o autor precisa ("por que a cena ficou sem foto").
_validate_asset_for = media_rules.asset_gate_reason


def _probe_dims(path: str) -> tuple[int, int]:
    """Dimensões reais via ffprobe; cache por caminho, tamanho e mtime."""
    try:
        stat = os.stat(path)
    except OSError:
        return 0, 0
    return _probe_dims_cached(path, stat.st_size, stat.st_mtime_ns)


@functools.lru_cache(maxsize=512)
def _probe_dims_cached(path: str, size: int,
                       mtime_ns: int) -> tuple[int, int]:
    """Cache invalida quando imagem muda; evita repetir subprocesso ffprobe."""
    _ = size, mtime_ns
    try:
        proc = ff.run([ff.FFPROBE, "-v", "error", "-select_streams", "v:0",
                       "-show_entries", "stream=width,height",
                       "-of", "csv=p=0", path])
        if proc.returncode == 0:
            w, h = proc.stdout.strip().split(",")[:2]
            return int(w), int(h)
    except (OSError, ValueError):
        pass
    return 0, 0


def _downloaded_dims_ok(asset: MediaAsset) -> bool:
    """Confere arquivo real pós-download; atualiza o asset (p/ o cache)."""
    try:
        size = os.path.getsize(asset.local_path)
    except OSError:
        return False
    if size <= 10000:
        return False
    asset.size_bytes = max(asset.size_bytes, size)
    if asset.width > 0 and asset.height > 0:
        return True  # já validado nos metadados
    w, h = _probe_dims(asset.local_path)
    if w <= 0 or h <= 0:
        return False  # ilegível: o render quebraria depois
    asset.width, asset.height = w, h
    return min(w, h) >= min_dimension()


# Heurística offline p/ consultas visuais (sem chave NVIDIA as cenas locais
# não trazem `visual_queries` — sem isto, tudo cairia em fallback). Extrai
# palavras-cheia do trecho e verte substantivos visuais PT→EN, pois os
# bancos de mídia respondem melhor em inglês. O gate de relevância continua
# valendo: só entra imagem cujo título contenha a consulta.
# Stopword e léxico PT→EN vivem em `curio.textnorm`: são dado linguístico
# compartilhado com a pesquisa e com o filtro de mídia, e manter cópia
# própria por estágio é o que faz "buraco negro" virar query "field"
# num lugar e continuar certo em outro.
PT_STOP = textnorm.VISUAL_STOP_PT
PT_EN = textnorm.PT_LEXICON


# Verte PT→EN (singular/plural) usando o léxico compartilhado.
_en = textnorm.translate


# Minúsculas sem acento: mesma comparação de texto da pesquisa e do scoring.
_strip_acc = textnorm.fold


# --- tópico espacial: nunca ilustrar com laboratório -------------------
# Sinais (já sem acento/minúsculas) de que a cena é sobre espaço/
# astronomia. "buraco negro" precisa estar aqui como expressão: sem isso,
# "campo gravitacional" virava query "field" e o vídeo recebia microscópio.
# O que é "tema espacial" é uma decisão de `textnorm`, não deste arquivo:
# a busca, o gate de imagem e o classificador de cena precisam
# reconhecer o mesmo conjunto.
is_space_topic = textnorm.is_space_topic


# Prioridade quando o assunto é espaço: o termo do tema vence a palavra
# mais frequente ("campo", "tempo") — que é genérica e puxa foto errada.
_SPACE_PRIORITY = (
    "black hole", "event horizon", "galaxy", "galaxies", "nebula",
    "gravity", "universe", "space", "cosmos", "astronomy",
    "singularity", "quasar", "relativity", "orbit",
    "star", "stars", "stellar", "sun", "moon", "planet",
    "telescope", "observatory", "light", "mass", "radiation",
)

# Genéricos de último recurso para tópico espacial: céu, nunca bancada.
# É o L4 da cachoeira quando o tema é espaço — "laboratory" aqui seria
# misinformation (foi o que ilustrou buraco negro com tubo de ensaio).
SPACE_GENERIC_QUERIES = (
    "black hole", "galaxy", "nebula", "starry sky", "telescope",
    "observatory",
)

def _space_boost(narration: str) -> list[str]:
    """Queries do tema espacial presentes NESTA narração, em ordem."""
    hay = _strip_acc(str(narration or ""))
    out: list[str] = []
    if ("buraco negro" in hay or "buracos negros" in hay
            or "black hole" in hay or "corpo negro" in hay):
        out.append("black hole")
    if "horizonte de eventos" in hay or "event horizon" in hay:
        out.append("event horizon")
    for marker, query in (("galaxia", "galaxy"), ("galaxy", "galaxy"),
                          ("nebulosa", "nebula"), ("nebula", "nebula"),
                          ("universo", "universe"), ("universe", "universe"),
                          ("gravidade", "gravity"), ("gravitacional", "gravity"),
                          ("gravitacao", "gravity"),
                          ("estrela", "star"), ("estrelas", "stars"),
                          ("sol", "sun"), ("telescopio", "telescope"),
                          ("luz", "light"), ("massa", "mass"),
                          ("radiacao", "radiation")):
        if marker in hay and query not in out:
            out.append(query)
    return out


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
    # Tópico espacial vence frequência: "campo"/"tempo" são frequentes e
    # genéricos — "buraco negro" é o assunto e precisa vir primeiro, ou a
    # busca pede "field" e o vídeo recebe microscópio.
    boost = _space_boost(narration)
    if boost:
        ordered = [t for t in boost if t in keywords or t in entities]
        ordered += [t for t in boost if t not in ordered]
        rest = [t for t in keywords if t not in ordered]
        # Termos espaciais traduzidos passam à frente dos genéricos.
        prio = [t for t in _SPACE_PRIORITY if t in keywords]
        rest_prio = [t for t in prio if t not in ordered]
        rest_other = [t for t in keywords if t not in ordered + rest_prio]
        keywords = ordered + rest_prio + rest_other
    # Constrói exatamente 2 termos: com tópico espacial, o tema vence a
    # entidade capitalizada; sem ele, entidade + substantivo visual.
    queries: list[str] = []
    if boost and keywords and keywords[0] in boost:
        queries.append(keywords[0])
    elif entities:
        queries.append(entities[0])
    if keywords:
        for kw in keywords:
            if kw not in queries:
                queries.append(kw)
                break
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


def scenes_for_script(script_text: str, cfg: CurioConfig,
                      genre: str = "") -> int:
    """Nº de cenas p/ roteiro pronto: acompanha o TAMANHO REAL do texto.

    Com duração escolhida, vale o maior entre meta e tamanho (nunca menos
    cenas que o conteúdo pede). No Automático, só o tamanho manda.
    Limitado a 12 cenas para não explodir o nº de buscas de mídia — teto
    esse que é do pipeline herdado, e só um perfil de gênero o substitui.
    """
    from . import editorial as _editorial
    perfil = _editorial.get(genre)
    pacing = perfil.pacing if perfil is not None else None
    alvo = pacing.target_scene_seconds if pacing is not None else 9.0
    teto = pacing.max_scenes if pacing is not None else None
    by_length = scenes_stage.scenes_for_length(len(script_text.split()),
                                               alvo, teto)
    if cfg.duration_target <= 0:
        return by_length
    return max(scenes_stage.scenes_for_duration(cfg.duration_target, alvo,
                                                teto), by_length)


def validate_preserved(original: str, chapters) -> None:
    """Garante que a divisão não reescreveu nada (falha em voz alta)."""
    joined = " ".join(c.narration for c in chapters)
    if scenes_stage._norm(joined) != scenes_stage._norm(original):
        raise ValueError(
            "divisão em cenas não reproduz o roteiro literal — "
            "recusando para não adulterar a narração")


# Palavras úteis de uma consulta: >2 letras, sem stopword. Havia uma cópia
# idêntica em `pipeline.py`, e as duas podiam divergir em silêncio.
_query_terms = textnorm.query_terms


def _relevance(query: str, asset: MediaAsset) -> int:
    haystack = f"{asset.title}".lower()
    return sum(1 for term in _query_terms(query) if term in haystack)


def _provider_priority_order(cfg: CurioConfig, ch=None,
                            genre: str = "") -> list[MediaProvider]:
    """Provedores na ordem de prioridade para ESTA cena.

    Para `historical_art` os museus e acervos sobem: uma foto de banco
    moderno é pior que nenhuma imagem para um santo do século XIII, e o
    Met/AIC/Wikimedia guardam pintura, fresco, escultura e objeto antigo em
    domínio público sem chave. A ordem global continua valendo para os
    demais tipos - a escada é por cena, não uma preferência permanente.
    """
    all_providers = get_providers(cfg)
    order = list(PROVIDER_PRIORITY)
    from . import editorial
    adapter = editorial.get(genre or getattr(cfg, "genre", ""))
    adapter_priority = list(adapter.media_provider_priority) if adapter else []
    if str(getattr(ch, "visual_type", "") or "") == "historical_art":
        adapter_priority = adapter_priority or ["met", "aic", "wikimedia", "openverse"]
    if adapter_priority:
        art_first = [p for p in adapter_priority if p in order]
        order = art_first + [p for p in order if p not in art_first]
    priority_map = {name: i for i, name in enumerate(order)}
    return sorted(all_providers, key=lambda p: priority_map.get(p.name, 999))


# Cachoeira de buscas (último recurso): termos genéricos de contexto para
# nunca entregar cena sem imagem quando há rede. Só disparam se tudo
# específico falhar. Por gênero: biografia/história caem em acervo
# (igreja, biblioteca, manuscrito), não em laboratório.
GENERIC_FALLBACK_QUERIES = (
    "laboratory", "microscope", "science", "research", "experiment",
    "test tube",
)

def _generic_queries(genre: str = "", ch=None) -> tuple[str, ...]:
    """Genéricos do gênero (L4 da cachoeira). Sem gênero: ciência, como antes.

    Exceção: tópico espacial nunca recebe bancada — recebe céu. Sem isso,
    "buraco negro" caía em "laboratory" e o vídeo saía com microscópio.
    """
    if ch is not None:
        try:
            hay = " ".join([
                str(getattr(ch, "narration", "") or ""),
                str(getattr(ch, "subject", "") or ""),
                " ".join(list(getattr(ch, "visual_queries", []) or [])),
                " ".join(list(getattr(ch, "visual_entities", []) or [])),
                " ".join(list(getattr(ch, "context", []) or [])),
            ])
            if is_space_topic(hay):
                return SPACE_GENERIC_QUERIES
        except Exception:  # noqa: BLE001 — genérico nunca é fatal
            pass
    from . import editorial
    adapter = editorial.get(genre)
    if adapter and adapter.generic_media_queries:
        return adapter.generic_media_queries
    return GENERIC_FALLBACK_QUERIES

# Meios que trazem ARTE para a frente numa busca. A ordem é o que o
# acervo tem de mais primeiro: pintura e fresco são o grosso do
# Wikimedia Commons para temas religiosos e antigos.
ART_MEDIA_HINTS = ("painting", "fresco", "engraving", "woodcut",
                   "illustration", "manuscript", "altarpiece", "mosaic",
                   "drawing", "etching")

# Cenas de mecanismo (ex.: anticorpo, linha de controle): bancos de foto
# mostram mãos/testes genéricos — L3/L4 + diagrama sintético cobrem.
_MECHANISM_KEYWORDS = (
    "antibody", "antibodies", "antigen", "hormone", "hcg", "strip",
    "lateral flow", "control line", "test line", "nanoparticle",
    "molecule", "microscope", "test tube", "pregnancy test",
    "anticorpo", "anticorpos", "hormonio", "hormônio", "tira",
    "linha de controle", "molecula", "molécula", "microscopio",
    "microscópio", "laboratorio", "laboratório", "gravidez",
)


def _waterfall_queries(ch, genre: str = "") -> tuple[list[str], set[str]]:
    """Cachoeira específico→genérico por cena (máx. 8 consultas).

    L1: termos exatos da IA ("water glass"); L2: termos avulsos;
    L3: tema do vídeo (global) + variante "diagrama do mecanismo";
    L4: genéricos de contexto (último recurso, nunca vazio).
    Devolve (consultas, genéricos): genéricos pontuam contra o próprio
    termo, não contra a narração inteira — foto de igreja entra como
    genérica honesta, nunca como específica.
    """
    seen: set[str] = set()
    out: list[str] = []

    def _add(query: str) -> None:
        query = _sanitize_query(query or "")
        if query and query.lower() not in seen:
            seen.add(query.lower())
            out.append(query)

    ai = [t.strip() for t in (list(ch.visual_queries) or []) if t.strip()]
    from .scoring import _tokens
    names = [set(_tokens(name)) for name in [getattr(ch, "subject", ""),
             *(getattr(ch, "subject_aliases", []) or [])] if _tokens(name)]
    same_subject = len(ai) >= 2 and all(
        any(name.issubset(set(_tokens(query))) for name in names) for query in ai[:2])
    if len(ai) >= 2 and not same_subject:
        _add(" ".join(ai[:2]))
    for term in ai:
        _add(term)
    if not ai:
        for term in local_queries(ch.narration):
            _add(term)
    for term in list(getattr(ch, "global_visual_queries", []) or []):
        _add(term)
    if str(getattr(ch, "visual_type", "") or "") == "historical_art":
        # Cena histórica precisa de ARTE, e o vocabulário que traz arte
        # para a frente é o meio, não o assunto. "saint francis" sozinho
        # devolve foto moderna de estátua em praça; "saint francis
        # painting" devolve o fresco.
        for term in list(ai[:2]) or list(getattr(ch, "visual_entities", []) or [])[:2]:
            for meio in ART_MEDIA_HINTS:
                _add(f"{term} {meio}")
    if ai:
        _add(" ".join(ai[:2]) + " diagram")
    generics = set()
    for term in _generic_queries(genre, ch):
        before = len(out)
        _add(term)
        if len(out) > before:
            generics.add(term.lower())
    if not out:
        _add("black hole" if is_space_topic(
            f"{getattr(ch, 'narration', '')} "
            f"{' '.join(list(getattr(ch, 'visual_queries', []) or []))}") else "science")
    return out[:8], generics


def _looks_mechanistic(ch, queries: list[str]) -> bool:
    """Cena sobre mecanismo invisível (anticorpo, linha de controle...)?"""
    haystack = f"{ch.narration} {' '.join(queries)}".lower()
    return any(k in haystack for k in _MECHANISM_KEYWORDS)


def _search_scene_with_shortcircuit(
    ch,
    providers: list[MediaProvider],
    cfg: CurioConfig,
    max_images: int,
    metrics,
    cache_dir: str,
    visual_state=None,
    genre: str = "",
    asset_uses: dict | None = None,
) -> tuple[list[dict], list[str]]:
    """Busca mídia de uma cena: COLETA candidatos, depois FILTRA e PONTUA.

    O comportamento antigo parava no primeiro asset que passasse no gate e
    no primeiro provedor que respondesse. Isso transformava o acervo inteiro
    num sorteio: com o Pixabay primeiro na fila, ele resolvia as 23 imagens
    do vídeo, e a que "casou" com a palavra do tema era a que o Pixabay
    devolveu primeiro — não a mais próxima do assunto. Foi assim que uma
    usina termelétrica entrou numa cena de papel térmico.

    Agora: junta candidatos de vários provedores, descarta com MOTIVO
    (licença, resolução, termo decorativo, termo proibido da cena) e só
    então ordena. Um provedor que responde mal não esgota mais a cena.
    """
    warnings = []
    results_before = sum(metrics.media_results_received.values()) if metrics else 0
    downloads_before = metrics.media_downloads if metrics else 0
    cache_before = metrics.media_cache_hits if metrics else 0
    queries, generics = _waterfall_queries(ch, genre)
    blocked = media_rules.scene_blocklist(ch)
    vtype = str(getattr(ch, "visual_type", "") or "literal")
    if metrics:
        metrics.media_queries_count += len(queries)

    # Uma cena tipográfica NÃO tem foto. A ideia dela É uma palavra, e
    # busca lexical por essa palavra traz qualquer coisa que a carregue no
    # título: "salarium" devolve um fungo chamado Clathurella salarium e
    # um navio-hospital. Não é um defeito do Threshold nem do filtro — é a
    # pergunta errada. A cena vai direto para o cartão, que é o visual
    # certo por construção.
    if vtype == "typographic":
        from . import visuals
        synth = visuals.visual_for_scene(ch, cfg.cache_dir,
                                         getattr(cfg, "language", "pt-BR"),
                                         visual_state, genre)
        if synth is not None:
            _save_to_cache(cfg.cache_dir, f"visual:{synth.asset_id}", synth)
            if metrics:
                metrics.media_record_visual_type(vtype)
                metrics.media_record_fallback("card")
                metrics.media_synth_diagrams += 1
            from ..runlog import event as run_event
            run_event("fallback", f"Cena {ch.id}: card tipográfico",
                      operation="media", scene=ch.id, strategy="card")
            return [{
                "chapter_id": ch.id,
                "asset": synth.to_dict(),
                "assets": [{"asset": synth.to_dict(), "query": "",
                            "relevance": 0, "order": 0, "from_cache": False,
                            "score": 0.0, "strategy": "card"}],
                "reused_from": None,
                "rejected": [],
                "visual_type": vtype,
                "strategy": "card",
            }], warnings

    candidates: list[dict] = []   # candidatos que passaram nos filtros
    rejected: list[dict] = []     # (motivo, título) p/ a folha de contato
    seen_ids: set[str] = set()

    def _consider(cand: MediaAsset, query: str, from_cache: bool) -> None:
        identity = f"{cand.provider}:{cand.asset_id}"
        if identity in seen_ids:
            if metrics:
                metrics.media_record_funnel("duplicates")
            return
        seen_ids.add(identity)
        if metrics:
            metrics.media_record_funnel("unique_considered")
        why = _validate_asset_for(cand, blocked)
        if why:
            rejected.append({"title": cand.title, "query": query,
                             "reason": why, "provider": cand.provider})
            if metrics:
                metrics.media_record_asset_rejected()
                metrics.media_record_funnel("hard_rejected")
                if classify_rights(cand.license or "", cand.provider) == "blocked":
                    metrics.media_record_rights("blocked")
            return
        if metrics:
            metrics.media_record_funnel("eligible")
        candidates.append({
            "asset": cand.to_dict(),
            "query": query,
            "relevance": 0,  # preenchido pelo scoring, não pela ordem de chegada
            "order": 0,
            "from_cache": from_cache,
            "generic": query.lower() in generics,
        })

    from . import scoring
    min_score = scoring.threshold()

    def collect(query_list: list[str], limit: int) -> None:
        for query in query_list:
            if len(candidates) >= limit:
                break
            cached = _get_cached_asset(cache_dir, query)
            if cached is not None:
                if metrics:
                    metrics.media_record_funnel("cache_returned")
                _consider(cached, query, from_cache=True)
                if metrics:
                    metrics.media_cache_hits += 1
            active = [prov for prov in providers
                      if not getattr(prov, "_disabled", False)]
            futures = [(prov, _submit_search(prov, query, metrics))
                       for prov in active]
            deadline = time.monotonic() + SEARCH_TIMEOUT
            # Wait in provider-priority order, even though requests run at
            # once. Candidate order and tie-breaks remain deterministic.
            for prov, future in futures:
                if len(candidates) >= limit:
                    for _later_provider, later in futures:
                        later.cancel()
                    break
                try:
                    remaining = max(0.0, deadline - time.monotonic())
                    results = future.result(timeout=remaining)
                except concurrent.futures.TimeoutError:
                    future.cancel()
                    if metrics:
                        metrics.media_record_timeout()
                    continue
                except MediaError as exc:
                    if (any(code in str(exc) for code in ("429", "401", "403"))
                            or "Too Many Requests" in str(exc)):
                        prov._disabled = True
                        if metrics:
                            metrics.media_record_timeout()
                        from ..runlog import event as run_event
                        logged = run_event(
                            "fallback", f"{prov.name}: provider desativado; {exc}",
                            operation="media_search", provider=prov.name,
                            error=str(exc))
                        if not logged:
                            print(f"AVISO: {prov.name} desativado nesta execução ({exc})",
                                  file=sys.stderr)
                    continue
                if metrics:
                    metrics.media_record_results(prov.name, len(results))
                    metrics.media_record_funnel("normalized_returned", len(results))
                for result_index, cand in enumerate(results):
                    if len(candidates) >= limit:
                        if metrics:
                            metrics.media_record_funnel(
                                "budget_unexamined", len(results) - result_index)
                        break
                    _consider(cand, query, from_cache=False)

    def score_specific(entries: list[dict]):
        ranked = scoring.rank_candidates(entries, ch)
        return scoring.below_threshold(ranked, min_score)

    # Colete e pontue específicos antes de buscar fotos genéricas do gênero.
    # Generic queries só rodam quando nenhuma foto específica passa o gate.
    specific_queries = [q for q in queries if q.lower() not in generics]
    generic_queries = [q for q in queries if q.lower() in generics]
    phase_budget = max_images * CANDIDATE_MULTIPLIER
    collect(specific_queries, phase_budget)
    specific, low_specific = score_specific(
        [entry for entry in candidates if not entry["generic"]])
    if specific:
        ranked, low = specific, low_specific
    else:
        collect(generic_queries, len(candidates) + phase_budget)
        generic_ranked = []
        for entry in [e for e in candidates if e["generic"]]:
            info = scoring.generic_score(entry["asset"], entry["query"])
            entry["score"] = info["score"]
            entry["score_detail"] = {"base": info["score"],
                                     "matched": info["matched"],
                                     "missing": info["missing"],
                                     "layers": ["base-generic"]}
            generic_ranked.append(entry)
        generic_ranked.sort(key=lambda e: (-e["score"], e["query"]))
        ranked, low_generic = scoring.below_threshold(generic_ranked, min_score)
        low = low_specific + low_generic
    for entry in low:
        # Descartado por NOTA, não por filtro: é o caso que mais importa
        # registrar, porque a imagem passou em todos os testes e ainda
        # assim não é do assunto (a usina que "casou" com "térmico").
        rejected.append({
            "title": entry["asset"].get("title", ""),
            "query": entry["query"],
            "reason": (f"nota {entry['score']:.0f} abaixo do mínimo "
                       f"{min_score:.0f}"),
            "provider": entry["asset"].get("provider", ""),
        })
        if metrics:
            metrics.media_record_asset_rejected()
            metrics.media_record_funnel("score_rejected")
    if metrics:
        metrics.media_record_selection(len(candidates), len(ranked))
        metrics.media_record_funnel("above_threshold", len(ranked))
    for rej in rejected:
        if metrics:
            metrics.media_record_rejection(rej["reason"])
    # A estratégia da cena é registrada mesmo quando ela dá certo: o
    # relatório precisa mostrar a distribuição (item 20), e um diagrama
    # não pode ser contado como falha.
    if metrics:
        metrics.media_record_visual_type(
            str(getattr(ch, "visual_type", "") or "literal"))

    picked: list[dict] = []
    from .visual_beats import asset_key
    if asset_uses is not None:
        # All candidates already passed relevance. Prefer fresh assets without
        # altering scores or allowing generic imagery ahead of specific imagery.
        ranked = sorted(ranked, key=lambda entry: (
            bool(entry.get("generic")), asset_uses.get(asset_key(entry["asset"]), 0),
            -entry.get("score", 0)))

    download_window = min(max(1, MAX_CONCURRENT_DOWNLOADS), max(1, max_images))
    download_futures: dict[int, object] = {}
    next_download = 0

    def fill_download_window() -> None:
        nonlocal next_download
        while len(download_futures) < download_window and next_download < len(ranked):
            index = next_download
            next_download += 1
            try:
                candidate = MediaAsset.from_dict(ranked[index]["asset"])
            except TypeError:
                continue
            if candidate.local_path and os.path.isfile(candidate.local_path):
                continue
            download_futures[index] = _submit_download(
                candidate, cfg.cache_dir, metrics)

    fill_download_window()
    for rank_index, entry in enumerate(ranked):
        if len(picked) >= max_images:
            break
        asset_dict = entry["asset"]
        if metrics:
            metrics.media_record_funnel("selected")
            metrics.media_selected_ids.add(asset_key(asset_dict))
        try:
            asset = MediaAsset.from_dict(asset_dict)
        except TypeError:
            continue
        local = asset.local_path
        acquisition = "cache" if local and os.path.isfile(local) else "download"
        if not (local and os.path.isfile(local)):
            future = download_futures.pop(rank_index, None)
            try:
                if future is None:
                    future = _submit_download(asset, cfg.cache_dir, metrics)
                asset, acquisition = future.result(timeout=DOWNLOAD_TIMEOUT)
                fill_download_window()
            except (MediaError, concurrent.futures.TimeoutError) as exc:
                if future is not None:
                    future.cancel()
                fill_download_window()
                msg = f"cena {ch.id}: download falhou ({exc})"
                warnings.append(msg)
                from ..runlog import event as run_event
                logged = run_event("warning", msg, operation="media_download",
                                   scene=ch.id, provider=asset.provider,
                                   error=str(exc))
                if not logged:
                    print(f"AVISO: {msg}", file=sys.stderr)
                if metrics:
                    metrics.media_record_funnel("download_failed")
                continue
        if not _downloaded_dims_ok(asset):
            msg = (f"cena {ch.id}: '{asset.title[:50]}' rejeitado após "
                   f"download (resolução insuficiente ou ilegível)")
            warnings.append(msg)
            rejected.append({"title": asset.title, "query": entry["query"],
                             "reason": "resolução/legibilidade após download",
                             "provider": asset.provider})
            if metrics:
                metrics.media_record_asset_rejected()
                metrics.media_record_rejection("resolução/legibilidade após download")
                metrics.media_record_funnel("post_download_rejected")
            continue
        asset.used_in = f"cena {ch.id}"
        if not asset.rights_status:
            asset.rights_status = classify_rights(asset.license or "",
                                                  asset.provider)
        if asset.rights_status == "verify":
            if metrics:
                metrics.media_record_rights("verify")
            msg = (f"cena {ch.id}: licença a conferir manualmente "
                   f"({asset.provider}: {asset.license or 'desconhecida'}) — "
                   f"{asset.license_url or asset.source_url or 'sem link'}")
            warnings.append(msg)
            from ..runlog import event as run_event
            logged = run_event("warning", msg, operation="media_rights",
                               scene=ch.id, provider=asset.provider,
                               rights_status="verify")
            if not logged:
                print(f"AVISO: {msg}", file=sys.stderr)
        _save_to_cache(cache_dir, entry["query"], asset)
        entry = dict(entry)
        entry["asset"] = asset.to_dict()
        if entry.get("generic") and metrics:
            metrics.media_record_funnel("generic_used")
        entry["order"] = len(picked)
        entry["acquisition"] = acquisition
        entry["score"] = entry.get("score", 0)
        if metrics:
            metrics.media_record_score(entry["score"])
        picked.append(entry)
        if asset_uses is not None:
            key = asset_key(entry["asset"])
            if asset_uses.get(key, 0):
                entry["reuse_reason"] = "eligible_pool_exhausted"
            asset_uses[key] = asset_uses.get(key, 0) + 1
        if metrics:
            metrics.media_record_funnel("used_real")

    if not picked and _looks_mechanistic(ch, list(ch.visual_queries)):
        synth = _synth_diagram_for_scene(ch, queries, cfg, metrics, genre)
        if synth is not None:
            picked.append(synth)
            seen_ids.add(synth["asset"]["asset_id"])
    strategy_used = "image"
    if not picked:
        # Nenhuma fotografia serviu. A cena NÃO fica vazia e NÃO recebe
        # imagem genérica: ela troca de medium. Um diagrama ou um cartão
        # é a cena certa mostrada do jeito certo, e a métrica registra
        # como estratégia, não como falha.
        from . import visuals
        synth = visuals.visual_for_scene(ch, cfg.cache_dir,
                                         getattr(cfg, "language", "pt-BR"),
                                         visual_state, genre)
        if synth is not None:
            _save_to_cache(cfg.cache_dir, f"visual:{synth.asset_id}", synth)
            picked.append({"asset": synth.to_dict(),
                           "query": queries[0] if queries else "",
                           "relevance": 0, "order": 0, "from_cache": False,
                            "score": 0.0, "strategy": "synth"})
            strategy_used = ("diagram"
                             if synth.title.startswith("Diagrama")
                             else synth.title.split(" — ")[0].lower())
            if metrics:
                metrics.media_record_fallback(strategy_used)
                metrics.media_synth_diagrams += 1
            from ..runlog import active as run_active
            if not run_active():
                print(f"cena {ch.id}: sem foto adequada — visual por código "
                      f"({strategy_used}): {synth.title[:60]}", file=sys.stderr)
    if not picked:
        msg = (f"cena {ch.id}: sem imagem adequada "
               f"({', '.join(queries[:3]) or 'sem consultas'})"
               + (f" — {len(rejected)} candidato(s) rejeitados" if rejected else "")
               + " — vai usar estratégia visual alternativa")
        warnings.append(msg)
        from ..runlog import event as run_event
        logged = run_event("warning", msg, operation="media", scene=ch.id)
        if not logged:
            print(f"AVISO: {msg}", file=sys.stderr)
        if metrics:
            metrics.media_record_asset_rejected()
            metrics.media_record_no_visual()

    from ..runlog import event as run_event
    returned = (sum(metrics.media_results_received.values()) - results_before
                if metrics else 0)
    downloads = metrics.media_downloads - downloads_before if metrics else 0
    cache_hits = metrics.media_cache_hits - cache_before if metrics else 0
    synthetic = bool(picked and picked[0].get("asset", {}).get("provider") == "synth")
    message = (f"Cena {ch.id}: {returned} resultados; {len(candidates)} elegíveis; "
               f"{len(ranked)} acima do score; {len(picked)} selecionado(s); "
               f"{downloads} baixado(s), {cache_hits} cache hit(s)"
               + ("; card/diagrama" if synthetic else ""))
    run_event("fallback" if synthetic else "result", message,
              operation="media", scene=ch.id, returned=returned,
              eligible=len(candidates), above_threshold=len(ranked),
              selected=len(picked), downloaded=downloads,
              cache_hits=cache_hits, strategy=strategy_used)

    first = picked[0]["asset"] if picked else None
    scene_rejected = rejected[:REJECTED_KEPT]
    return [{
        "chapter_id": ch.id,
        "asset": first,
        "assets": picked,
        "reused_from": None,
        "rejected": scene_rejected,
        "visual_type": str(getattr(ch, "visual_type", "") or "literal"),
        "strategy": strategy_used,
    }], warnings


def _synth_diagram_for_scene(ch, queries: list[str], cfg: CurioConfig,
                             metrics, genre: str = "") -> dict | None:
    """Gera diagrama de tira de teste p/ cena de mecanismo (offline).

    Retorna a entrada `picked` pronta ou None (PIL ausente/falha).

    O gênero entra porque a tira é desenhada por PIL com texto, e texto
    sem papel tipográfico sai na sans pesada de sempre — que é
    exatamente o que este projeto deixou de fazer.
    """
    try:
        from . import diagram as diagram_stage
    except ImportError as exc:
        print(f"AVISO: diagrama sintético indisponível ({exc}).",
              file=sys.stderr)
        return None
    try:
        terms = " ".join(queries[:2]) or ch.narration[:60]
        from . import typography as typo_stage
        asset = diagram_stage.render_strip_diagram(
            terms, cfg.cache_dir,
            language=getattr(cfg, "language", "pt-BR"),
            typo=typo_stage.for_genre(genre))
    except Exception as exc:  # noqa: BLE001 — fallback honesto abaixo
        print(f"AVISO: diagrama sintético falhou ({exc}).", file=sys.stderr)
        return None
    try:
        _save_to_cache(cfg.cache_dir,
                       f"synth-diagram:{terms}", asset)
    except OSError as exc:
        print(f"AVISO: cache do diagrama falhou ({exc}).", file=sys.stderr)
    if metrics:
        metrics.media_record_synth()
    asset.used_in = f"cena {ch.id}"
    return {"asset": asset.to_dict(), "query": terms,
            "relevance": 50, "order": 0}


def fetch_media_multi(chapters, cfg: CurioConfig,
                      max_images: int = 3,
                      metrics=None, genre: str = "") -> tuple[list[dict], list[str]]:
    """Busca ativos por cena com short-circuit rigoroso e cache local.

    Hierarquia: Pixabay → Unsplash → Pexels → NASA → Wikimedia → Openverse.
    Para no primeiro provedor que retornar ativo válido por query.
    Cache local indexado por termo de busca (visual_search_terms).
    Cachoeira por cena: termos exatos → avulsos → tema → diagrama →
    genéricos; cena de mecanismo sem nada ganha diagrama sintético.
    """
    max_images = max(1, min(5, int(max_images)))
    # A ordem de provedores é por cena: histórica quer acervo de arte
    # primeiro, as demais mantêm a ordem global.
    providers = []
    seen_names: set[str] = set()
    for ch in chapters:
        for prov in _provider_priority_order(cfg, ch, genre):
            if prov.name not in seen_names:
                seen_names.add(prov.name)
                providers.append(prov)
    if not providers:
        return _fetch_media_fallback(chapters, max_images, warnings=[])
    
    all_warnings = []
    scenes = []
    # O estado de variedade atravessa as cenas: é ele que impede seis cenas
    # conceituais de virarem seis cards idênticos.
    from . import visuals as _visuals
    visual_state = _visuals.VisualState()
    asset_uses: dict[str, int] = {}

    for ch in chapters:
        scene_scenes, scene_warnings = _search_scene_with_shortcircuit(
            ch, providers, cfg, max_images, metrics, cfg.cache_dir,
            visual_state=visual_state, genre=genre, asset_uses=asset_uses,
        )
        scenes.extend(scene_scenes)
        all_warnings.extend(scene_warnings)
    
    _resolve_reuse_multi(scenes)
    _annotate_reuse(scenes)
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


def _annotate_reuse(scenes: list[dict]) -> None:
    """Marca no media.json as imagens que aparecem em mais de uma cena.

    A São Jerônimo mostrou o caso que faltava. Duas cenas com midia
    PRÓPRIA podem receber o mesmo asset_id: cada uma buscou e o provedor
    devolveu o mesmo melhor resultado. Isso não é o que `_resolve_reuse_
    multi` trata, e o campo `reused_from` ficava vazio nas duas — o
    mesmo asset em cenas 1 e 3 só aparecia se alguém fosse comparar o
    media.json na mão.

    Entradas antigas mantêm `same_top_match`; novas seleções registram
    `eligible_pool_exhausted` quando faltam candidatas elegíveis inéditas.
    Não se inventa um motivo `thematic_reuse`. Reuso editorial intencional
    é uma decisão do autor, e o
    curio não tem como ler decisão nenhuma nos dados — afirmar
    "reuso temático" seria inventar o motivo e chamar de diagnóstico. O
    que o registro entrega é o par de cenas e o asset, para o autor
    decidir em um segundo se foi intencional.
    """
    primeira: dict[str, int] = {}
    from .visual_beats import asset_key
    for s in scenes:
        ids = []
        for entry in s.get("assets") or []:
            a = (entry or {}).get("asset") or {}
            aid = str(a.get("asset_id") or "")
            if not aid:
                continue
            ids.append((asset_key(a), a, entry))
        for aid, a, entry in ids:
            if aid in primeira:
                s.setdefault("reuse", []).append({
                    "asset": a.get("asset_id", ""),
                    "title": a.get("title", "")[:120],
                    "provider": a.get("provider", ""),
                    "previous_scene": primeira[aid],
                    "current_scene": s.get("chapter_id"),
                    "reason": entry.get("reuse_reason", "same_top_match"),
                })
            else:
                primeira[aid] = s.get("chapter_id")
    for s in scenes:
        s.setdefault("reuse", [])


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


def build_visual_timeline(chapters, media_scenes: list[dict],
                          overlap_cap: float = 0.9, seed: str = "",
                          sfx: bool = True,
                          insertions: int | None = None,
                          insert_style: str = "drop_in",
                           insert_gain_db: int = -15,
                          honor_order: bool = False) -> list[dict]:
    """Timeline visual renderizável: um trecho por cena com suas imagens.

    Cada trecho carrega texto/narração original, início/fim, imagens em
    ordem (com consulta que a encontrou), duração, transição e geometria
    de sobreposição. Capítulos precisam ter `start/end` já definidos
    (WordBoundary reais ou estimativa WPM) antes desta chamada.

    `insertions` é o orçamento de fotos COMPLEMENTARES do VÍDEO inteiro
    (padrão 2, `None` mantém o álbum por cena sem limite). As cenas
    escolhidas por `insertion_scenes` recebem 1 cartaz a mais, sempre com
    `insert_style` (padrão: caiu do álbum) e um toque de som discreto no
    instante exato da entrada — as outras cenas ficam só com o fundo.

    `honor_order` respeita a ordem que já está em `assets` em vez de
    redecidir o papel de cada foto. É o que o `swap` precisa: se o
    replanejamento re-executasse `order_for_insertion`, ele devolveria a
    foto que o autor acabou de tirar para o fim.
    """
    by_chapter = {s["chapter_id"]: s for s in media_scenes}
    styles = _shuffled_styles(seed)
    sparse = insertions is not None and not honor_order
    insert_at = (insertion_scenes(len(chapters), insertions or 0)
                 if sparse else set())
    scene_no_insert: set[int] = set()  # cena que ficou sem deepenho
    overlay_counter, sfx_ordinal, style_pos = 0, 0, 0
    timeline = []
    from .visual_beats import plan as plan_visual_beats, bind_assets, asset_key
    background_uses: dict[str, int] = {}
    for idx, ch in enumerate(chapters):
        scene = by_chapter.get(ch.id, {})
        start, end = round(float(ch.start), 3), round(float(ch.end), 3)
        dur = max(0.5, end - start)
        entries = list(scene.get("assets") or [])
        background_entries = list(entries)
        if not honor_order:
            background_entries.sort(key=lambda entry: (
                bool(entry.get("generic")),
                background_uses.get(asset_key(entry.get("asset") or {}), 0),
                -entry.get("score", 0)))
        if sparse:
            # A inserção tem de ser a imagem MAIS PRECISA sobre o assunto da
            # cena — é o que a diferencia do fundo. Sem candidata que bata o
            # fundo, a cena fica só com o fundo.
            background, insertion = order_for_insertion(entries, ch)
            entries = background if idx not in insert_at else background + insertion
            if idx in insert_at and not insertion:
                scene_no_insert.add(ch.id)
        images, consumed = _spec_images(entries, dur,
                                       overlap_cap, styles, style_pos)
        if sparse:
            # No modo esparso toda foto extra É uma inserção: entra no
            # ritmo de álbum e sempre marca com som, independentemente da
            # cadência ~1/3 do modo álbum cheio. `style_pos` não anda:
            # a sequência variada pertence só ao álbum cheio.
            mark_insertion(images, start, insert_style, insert_gain_db, sfx)
        else:
            style_pos += consumed
            overlay_counter, sfx_ordinal = _assign_sfx(
                images, start, overlay_counter, sfx_ordinal, sfx)
        beats = plan_visual_beats(dur, start)
        available = [_spec_images([entry], dur)[0][0] for entry in background_entries]
        backgrounds = bind_assets(beats, available, start)
        for background in backgrounds:
            key = asset_key(background)
            background_uses[key] = background_uses.get(key, 0) + 1
        for beat in beats:
            visible = beat.setdefault("asset_ids", [])
            for image in images[1:]:
                if image["start"] < beat["end"] - start:
                    key = asset_key(image)
                    if key and key not in visible:
                        visible.append(key)
        timeline.append({
            "chapter_id": ch.id,
            "narration": ch.narration,  # original, intocado
            "start": start,
            "end": end,
            "images": images,
            "visual_beats": beats,
            "backgrounds": backgrounds,
            "fallback": not images and not backgrounds,
            "reused_from": scene.get("reused_from"),
            **({"no_insertion": "nenhuma imagem mais precisa que o fundo"
               } if ch.id in scene_no_insert else {}),
        })
    return timeline
