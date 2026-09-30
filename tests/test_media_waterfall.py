"""Cachoeira específico→genérico, gate de metadados e diagrama sintético."""

import os
from types import SimpleNamespace

from curio.media.providers import MediaAsset, MediaError
from curio.metrics import RunMetrics
from curio.stages import visual as V


def _ch(queries=(), narration="Texto da cena.", cid=1, glob=()):
    return SimpleNamespace(id=cid, narration=narration,
                           visual_queries=list(queries),
                           global_visual_queries=list(glob))


def _asset(provider="pixabay", aid="1", title="water glass laboratory",
           url="https://cdn.x/photo.jpg", w=1920, h=1280, lic="ok"):
    return MediaAsset(provider=provider, asset_id=aid, title=title,
                      download_url=url, width=w, height=h, license=lic)


def test_waterfall_ordem_e_limite():
    # Termos avulsos como o pipeline real entrega (split de "water glass").
    ch = _ch(("water", "glass"),
             glob=("pregnancy test", "water glass"))
    qs = V._waterfall_queries(ch)
    assert qs[0] == "water glass"  # L1: exato da IA
    assert "microscope" in qs  # L2: avulso
    assert "pregnancy test" in qs  # L3: tema
    assert any(q.endswith("diagram") for q in qs)  # L3b
    assert "laboratory" in qs  # L4: genérico
    assert len(qs) == len(set(q.lower() for q in qs))  # sem dup
    assert len(qs) <= 8
    # sem nada da IA: usa local + genéricos, nunca vazio
    qs2 = V._waterfall_queries(_ch((), "O sal preservava a comida romana."))
    assert qs2 and "laboratory" in qs2


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


def test_short_circuit_para_no_primeiro_provedor(tmp_path, monkeypatch):
    _mock_download(monkeypatch, tmp_path)
    good = [_asset(aid="ok1")]
    p1 = _FakeProv("pixabay", good)
    p2 = _FakeProv("nasa", [_asset(provider="nasa", aid="n1")])
    ch = _ch(("water glass",))
    scenes, warns = V._search_scene_with_shortcircuit(
        ch, [p1, p2], SimpleNamespace(cache_dir=str(tmp_path)), 1, None,
        str(tmp_path))
    assert scenes[0]["asset"]["asset_id"] == "ok1"
    assert p2.calls == []  # short-circuit: segundo nem é consultado
    assert not warns


def test_waterfall_avanca_ate_generico_e_401_desativa(tmp_path, monkeypatch):
    _mock_download(monkeypatch, tmp_path)
    empty, err401 = [], MediaError("unsplash: busca falhou (HTTP 401: bad)")
    p1 = _FakeProv("unsplash", empty)
    p2 = _FakeProv("nasa", empty, err401)
    p3 = _FakeProv("wikimedia", [_asset(provider="wikimedia", aid="w1",
                                        title="science laboratory")])
    ch = _ch(("water glass",))
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


def test_sem_imagens_nem_diagrama_vira_fallback(tmp_path):
    ch = _ch(("rome soldier",), "Roma caiu em guerra.")
    scenes, warns = V._search_scene_with_shortcircuit(
        ch, [], SimpleNamespace(cache_dir=str(tmp_path), language="pt-BR"),
        1, None, str(tmp_path))
    assert scenes[0]["asset"] is None
    assert warns and "fallback" in warns[0]


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
