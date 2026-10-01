"""Cachoeira específico→genérico, gate de metadados e diagrama sintético."""

import os
from types import SimpleNamespace

from curio.media.providers import MediaAsset, MediaError
from curio.metrics import RunMetrics
from curio.stages import visual as V


def _ch(queries=(), narration="Texto da cena.", cid=1, glob=(), **extra):
    """Cena de teste. `entities`/`subject` existem porque o scoring compara
    o título da foto com o vocabulário da cena: uma cena cuja narração não
    tem nada a ver com a foto deve (e deve) reprovar o candidato."""
    base = dict(id=cid, narration=narration,
                visual_queries=list(queries),
                global_visual_queries=list(glob),
                visual_type="literal", subject="", visual_entities=[],
                context=[], forbidden=[])
    base.update(extra)
    return SimpleNamespace(**base)


def _asset(provider="pixabay", aid="1", title="water glass laboratory",
           url="https://cdn.x/photo.jpg", w=1920, h=1280,
           lic="CC BY-SA 4.0"):
    return MediaAsset(provider=provider, asset_id=aid, title=title,
                      download_url=url, width=w, height=h, license=lic)


def test_waterfall_ordem_e_limite():
    # Termos avulsos como o pipeline real entrega (split de "water glass").
    ch = _ch(("water", "glass"),
             glob=("pregnancy test", "water glass"))
    qs, generics = V._waterfall_queries(ch)
    assert qs[0] == "water glass"  # L1: exato da IA
    assert "microscope" in qs  # L2: avulso
    assert "pregnancy test" in qs  # L3: tema
    assert any(q.endswith("diagram") for q in qs)  # L3b
    assert "laboratory" in qs  # L4: genérico
    assert "laboratory" in generics  # genérico marcado p/ núcleo próprio
    assert len(qs) == len(set(q.lower() for q in qs))  # sem dup
    assert len(qs) <= 8
    # sem nada da IA: usa local + genéricos, nunca vazio
    qs2, _ = V._waterfall_queries(_ch((), "O sal preservava a comida romana."))
    assert qs2 and "laboratory" in qs2
    # people: acervo (igreja, biblioteca), não laboratório
    qs3, gen3 = V._waterfall_queries(_ch(("saint",)), genre="people")
    assert "church interior" in qs3 and "church interior" in gen3
    assert "laboratory" not in qs3


def test_validate_asset_corrige_gate():
    # pixabay-like (sem size_bytes) agora passa no gate de metadados
    assert V._validate_asset(_asset())
    # NASA (dims desconhecidas) passa p/ conferir após o download
    assert V._validate_asset(_asset(provider="nasa", w=0, h=0,
                                    url="http://images-assets.nasa.gov/x.jpg"))
    # licença ND bloqueada em qualquer provedor
    assert not V._validate_asset(_asset(lic="CC BY-NC-ND 4.0"))
    # extensão inválida / oversize
    assert not V._validate_asset(_asset(url="https://x/foto.tiff"))
    big = _asset()
    big.size_bytes = 100 * 1024 * 1024
    assert not V._validate_asset(big)
    # resolução conhecida abaixo do mínimo
    assert not V._validate_asset(_asset(w=640, h=480))


def test_looks_mechanistic():
    assert V._looks_mechanistic(
        _ch(("antibody", "protein"), "Antibodies bind to hCG."), ["antibody"])
    assert not V._looks_mechanistic(
        _ch(("rome", "soldier"), "Roma caiu."), ["rome"])


class _FakeProv:
    def __init__(self, name, results=None, error=None):
        self.name = name
        self._results = results or []
        self._error = error
        self.calls = []

    def search(self, query, limit=5, metrics=None):
        self.calls.append(query)
        if metrics is not None:
            metrics.media_search(self.name)
        if self._error:
            raise self._error
        return list(self._results)


def _dummy_file(tmp_path, name="dummy.jpg", size=20000):
    path = str(tmp_path / name)
    with open(path, "wb") as fh:
        fh.write(b"\0" * size)
    return path


def _mock_download(monkeypatch, tmp_path):
    dummy = _dummy_file(tmp_path)

    def _fake(cand, *args, **kwargs):
        cand.local_path = dummy
        return cand

    monkeypatch.setattr(V, "download_asset", _fake)


def test_todos_os_provedores_sao_consultados(tmp_path, monkeypatch):
    """Contrato antigo (parar no 1º provedor) foi a causa do defeito.

    Com o Pixabay primeiro na fila e short-circuit, ele resolvia o vídeo
    inteiro: as 23 imagens saíram dele e nenhuma alternativa foi vista.
    Agora todos são consultados e a escolha passa a ser do scoring.
    """
    _mock_download(monkeypatch, tmp_path)
    p1 = _FakeProv("pixabay", [_asset(aid="ok1")])
    p2 = _FakeProv("nasa", [_asset(provider="nasa", aid="n1",
                                   title="nasa water glass")])
    ch = _ch(("water glass",), subject="water glass",
             visual_entities=["glass", "water"])
    scenes, warns = V._search_scene_with_shortcircuit(
        ch, [p1, p2], SimpleNamespace(cache_dir=str(tmp_path)), 1, None,
        str(tmp_path))
    assert p1.calls and p2.calls, "provedor posterior não foi consultado"
    # com max_images=1 fica o de maior nota, não o primeiro que chegou
    assert scenes[0]["asset"]["asset_id"] in ("ok1", "n1")


def test_provedor_que_so_devolve_lixo_nao_esgota_a_cena(tmp_path, monkeypatch):
    """Um acervo ruim (wallpaper/4k) não pode decidir a cena."""
    _mock_download(monkeypatch, tmp_path)
    lixo = [_asset(aid="w1", title="mountain river wallpaper 4k hd"),
            _asset(aid="w2", title="desert field background 4k")]
    p1 = _FakeProv("pixabay", lixo)
    p2 = _FakeProv("wikimedia", [_asset(provider="wikimedia", aid="w1real",
                                        title="thermal paper receipt")])
    ch = _ch(("thermal paper receipt",), subject="thermal paper receipt",
             visual_entities=["receipt", "paper"])
    scenes, _ = V._search_scene_with_shortcircuit(
        ch, [p1, p2], SimpleNamespace(cache_dir=str(tmp_path)), 1, None,
        str(tmp_path))
    assert scenes[0]["asset"]["asset_id"] == "w1real"
    reasons = [r["reason"] for r in scenes[0]["rejected"]]
    assert any("termo bloqueado" in r for r in reasons), reasons


def test_waterfall_avanca_ate_generico_e_401_desativa(tmp_path, monkeypatch):
    _mock_download(monkeypatch, tmp_path)
    empty, err401 = [], MediaError("unsplash: busca falhou (HTTP 401: bad)")
    p1 = _FakeProv("unsplash", empty)
    p2 = _FakeProv("nasa", empty, err401)
    p3 = _FakeProv("wikimedia", [_asset(provider="wikimedia", aid="w1",
                                        title="science laboratory")])
    ch = _ch(("water glass",), subject="science laboratory",
             visual_entities=["laboratory", "science"])
    m = RunMetrics("s", "idea", "narr")
    scenes, _ = V._search_scene_with_shortcircuit(
        ch, [p1, p2, p3], SimpleNamespace(cache_dir=str(tmp_path)), 1, m,
        str(tmp_path))
    assert scenes[0]["asset"]["provider"] == "wikimedia"
    assert p2._disabled is True  # 401 persistente desativa no run
    assert p1.calls  # específico foi tentado antes do genérico
    assert m.media_searches.get("wikimedia", 0) >= 1


def test_synth_diagram_em_cena_mecanistica_sem_nada(tmp_path):
    ch = _ch(("antibody gold",),
             "Antibodies tagged with gold bind to the hormone hCG.")
    m = RunMetrics("s", "idea", "narr")
    cfg = SimpleNamespace(cache_dir=str(tmp_path), language="en-US")
    scenes, warns = V._search_scene_with_shortcircuit(
        ch, [], cfg, 1, m, str(tmp_path))
    assert scenes[0]["asset"]["provider"] == "synth"
    assert scenes[0]["asset"]["local_path"].endswith(".png")
    assert os.path.getsize(scenes[0]["asset"]["local_path"]) > 10000
    assert m.media_synth_diagrams == 1
    assert not warns  # diagrama resolve: sem fallback


def test_cena_sem_foto_boa_troca_de_estrategia(tmp_path):
    """Sem foto boa, a cena NÃO fica vazia: ela vira cartão.

    Este é o ponto que muda o produto. Antes, "nada encontrado" significava
    gradiente com o título — um placeholder que parecia erro. Agora a cena
    recebe um visual coerente com o que ela diz.
    """
    ch = _ch(("roman legion",), "A legião romana marchou até o rio.",
             subject="roman legion", visual_entities=["legion", "roman"])
    scenes, warns = V._search_scene_with_shortcircuit(
        ch, [], SimpleNamespace(cache_dir=str(tmp_path), language="pt-BR"),
        1, None, str(tmp_path))
    asset = scenes[0]["asset"]
    assert asset is not None, "cena ficou sem visual"
    assert asset["provider"] == "synth"
    assert os.path.getsize(asset["local_path"]) > 10000
    assert scenes[0]["strategy"] in ("card", "diagram")
    # não é degradation silenciosa: a troca fica registrada
    assert warns == [] or any("visual por código" in w for w in warns)


def test_download_rejeita_dims_reais_baixas(tmp_path):
    from PIL import Image
    small = str(tmp_path / "small.jpg")
    Image.new("RGB", (100, 100), "red").save(small)
    a = _asset(provider="nasa", w=0, h=0)
    a.local_path = small
    assert V._downloaded_dims_ok(a) is False
    big = str(tmp_path / "big.jpg")
    Image.new("RGB", (1200, 1200), "blue").save(big)
    b = _asset(provider="nasa", w=0, h=0)
    b.local_path = big
    assert V._downloaded_dims_ok(b) is True
    assert (b.width, b.height) == (1200, 1200)


def test_used_in_marcado_no_pick_e_limpo_no_cache(tmp_path):
    import shutil
    from curio.stages.visual import _get_cached_asset, _save_to_cache
    m = RunMetrics("s", "idea", "narr")
    ch2 = _ch(("antibody gold",), "Gold antibodies bind hCG hormone.")
    scenes, _ = V._search_scene_with_shortcircuit(
        ch2, [], SimpleNamespace(cache_dir=str(tmp_path), language="en-US"),
        1, m, str(tmp_path))
    assert scenes[0]["asset"]["used_in"] == "cena 1"
    # o cache de consulta nunca carrega used_in de outro vídeo
    src = scenes[0]["asset"]["local_path"]
    assert os.path.getsize(src) > 10000
    a = _asset(aid="reuse1")
    a.local_path = src
    a.used_in = "cena 9"
    _save_to_cache(str(tmp_path), "water glass reuse", a)
    cached = _get_cached_asset(str(tmp_path), "water glass reuse")
    assert cached is not None and cached.used_in == ""
    shutil.rmtree(str(tmp_path), ignore_errors=True)
