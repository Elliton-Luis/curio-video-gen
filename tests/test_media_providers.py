"""Providers Unsplash/NASA (fixtures, sem rede) + licenças + asset."""

from unittest.mock import patch

import pytest

from curio.media import providers as P


def _unsplash_payload():
    return {
        "results": [
            {
                "id": "abc123",
                "slug": "lab-microscope-abc123",
                "description": "Microscope in a lab",
                "alt_description": "microscope on laboratory bench",
                "width": 4000, "height": 6000,
                "user": {"name": "Jane Doe"},
                "links": {"html": "https://unsplash.com/photos/abc123"},
                "urls": {"raw": "https://images.unsplash.com/photo-1?ixid=xx"},
            },
            {
                "id": "tiny1",
                "slug": "tiny",
                "description": "tiny",
                "alt_description": "tiny thumb",
                "width": 100, "height": 100,
                "user": {"name": "X"},
                "links": {"html": "https://unsplash.com/photos/tiny1"},
                "urls": {"raw": "https://images.unsplash.com/photo-2"},
            },
            {
                "id": "noraw",
                "slug": "noraw",
                "width": 4000, "height": 4000,
                "user": {"name": "Y"},
                "links": {"html": "https://unsplash.com/photos/noraw"},
                "urls": {},
            },
        ]
    }


def _nasa_search_payload():
    return {
        "collection": {
            "items": [
                {
                    "href": "https://images-api.nasa.gov/asset/NID1",
                    "data": [{"nasa_id": "NID1", "title": "Lab Work",
                              "center": "JSC",
                              "keywords": ["laboratory", "microscope"]}],
                    "links": [{"href": "https://preview.jpg"}],
                },
                {
                    "href": "https://images-api.nasa.gov/asset/NID2",
                    "data": [{"nasa_id": "", "title": "Sem ID"}],
                    "links": [],
                },
            ]
        }
    }


def test_unsplash_parsing_e_licenca(monkeypatch):
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "fake-key")
    prov = P.UnsplashProvider()
    with patch.object(P, "_http_get_json", return_value=_unsplash_payload()) as m:
        assets = prov.search("microscope", limit=5)
    assert m.called
    assert len(assets) == 1  # tiny (<1000px) e sem raw caem fora
    a = assets[0]
    assert a.provider == "unsplash" and a.asset_id == "abc123"
    assert a.license == "Licença Unsplash (uso livre)"
    assert a.license_url == P.UNSPLASH_LICENSE_URL
    assert a.source_url == "https://unsplash.com/photos/abc123"
    assert "w=1920" in a.download_url and "fm=jpg" in a.download_url
    assert a.author == "Jane Doe"
    assert (a.width, a.height) == (4000, 6000)


def test_pixabay_usa_ua_de_navegador_e_per_page_minimo(monkeypatch):
    """Cloudflare do Pixabay barra UA de bot (1010); per_page < 3 dá 400."""
    import urllib.parse as _up
    import urllib.request as _ur

    monkeypatch.setenv("PIXABAY_API_KEY", "fake-key")
    prov = P.PixabayProvider()
    captured = {}

    def spy(req, timeout=30):
        captured["ua"] = req.get_header("User-agent")
        captured["url"] = req.full_url

        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"totalHits": 0, "hits": []}'

        return R()

    monkeypatch.setattr(_ur, "urlopen", spy)
    assert prov.search("microscope", limit=2) == []
    assert "Mozilla" in captured["ua"]
    qs = dict(_up.parse_qsl(_up.urlsplit(captured["url"]).query))
    assert int(qs["per_page"]) >= 3, qs


def test_unsplash_sem_chave_falha_explicita(monkeypatch):
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    with pytest.raises(P.MediaError, match="UNSPLASH_ACCESS_KEY"):
        P.UnsplashProvider()


def test_nasa_parsing_licenca_e_manifest(monkeypatch):
    prov = P.NASAProvider()

    def fake_get(url, headers=None, timeout=30):
        if url.startswith(P.NASAProvider.API):
            return _nasa_search_payload()
        assert url == "https://images-api.nasa.gov/asset/NID1"
        return ["https://x/NID1~orig.tif",
                "https://x/NID1~large.jpg",
                "https://x/NID1~small.jpg"]

    with patch.object(P, "_http_get_json", side_effect=fake_get):
        assets = prov.search("laboratory", limit=5)
    assert len(assets) == 1  # item sem nasa_id é pulado
    a = assets[0]
    assert a.provider == "nasa" and a.asset_id == "NID1"
    assert a.license == "Domínio público (NASA)"
    assert a.license_url == "https://images.nasa.gov/details-NID1"
    assert a.source_url == a.license_url
    assert a.download_url.endswith("~large.jpg")  # evita o TIFF gigante
    assert "microscope" in a.title  # keywords entram p/ o gate de relevância
    assert (a.width, a.height) == (0, 0)  # dims só após o download


def test_nasa_pick_file_prefere_jpg_medio():
    files = ["https://x/A~orig.tif", "https://x/A~small.jpg"]
    with patch.object(P, "_http_get_json", return_value=files):
        assert P.NASAProvider._pick_file("http://manifest").endswith("~small.jpg")
    with patch.object(P, "_http_get_json", return_value=["https://x/A~orig.tif"]):
        assert P.NASAProvider._pick_file("http://manifest") == ""
    with patch.object(P, "_http_get_json",
                      side_effect=P.MediaError("busca falhou (HTTP 500)")):
        assert P.NASAProvider._pick_file("http://manifest") == ""


def test_license_ok_bloqueia_nd():
    assert not P.license_ok("CC BY-ND 4.0")
    assert not P.license_ok("CC BY-NC-ND 2.0")
    assert P.license_ok("CC BY-SA 4.0")
    assert P.license_ok("CC BY-NC 4.0")
    assert P.license_ok("Domínio público (NASA)")
    assert P.license_ok("Licença Pixabay (uso livre)")
    assert P.license_ok("")


def test_asset_roundtrip_com_novos_campos():
    a = P.MediaAsset(provider="nasa", asset_id="NID1",
                     license_url="https://images.nasa.gov/details-NID1",
                     used_in="cena 2")
    b = P.MediaAsset.from_dict(a.to_dict())
    assert b.license_url == "https://images.nasa.gov/details-NID1"
    assert b.used_in == "cena 2"
    # dicts antigos (sem os campos) continuam lendo
    c = P.MediaAsset.from_dict({"provider": "x", "asset_id": "y"})
    assert c.license_url == "" and c.used_in == ""


def test_classify_rights():
    C = P.classify_rights
    # bloqueadas: ND em qualquer forma + todos os direitos reservados
    assert C("CC BY-ND 4.0") == "blocked"
    assert C("CC BY-NC-ND 2.0") == "blocked"
    assert C("Licença com NoDerivatives") == "blocked"
    assert C("Todos os direitos reservados") == "blocked"
    assert C("© 2024 Fulano") == "blocked"
    # livres: domínio público, CC-BY/SA, bancos, manual, sintético
    assert C("Domínio público (NASA)") == "clear"
    assert C("Public Domain") == "clear"
    assert C("CC0") == "clear"
    assert C("CC BY-SA 4.0") == "clear"
    assert C("Licença Pixabay (uso livre)", "pixabay") == "clear"
    assert C("Licença Pexels (uso livre)", "pexels") == "clear"
    assert C("Licença Unsplash (uso livre)", "unsplash") == "clear"
    assert C("manual do usuário", "manual") == "clear"
    assert C("Original (gerado por código)", "synth") == "clear"
    # verificar: NC, desconhecida, vazia
    assert C("CC BY-NC 4.0") == "verify"
    assert C("ver licença na source_url") == "verify"
    assert C("") == "verify"


def test_asset_carimba_rights_no_post_init():
    a = P.MediaAsset(provider="openverse", asset_id="1",
                     license="CC BY-NC 2.0")
    assert a.rights_status == "verify"
    b = P.MediaAsset(provider="wikimedia", asset_id="2",
                     license="CC BY-SA 4.0")
    assert b.rights_status == "clear"
    c = P.MediaAsset.from_dict({"provider": "x", "asset_id": "y"})
    assert c.rights_status == "verify"  # licença vazia → conferir
    d = P.MediaAsset.from_dict({"provider": "x", "asset_id": "y",
                                "rights_status": "clear"})
    assert d.rights_status == "clear"  # valor salvo é preservado


# --- Unsplash: último recurso e com orçamento --------------------------

def test_unsplash_tem_teto_de_requisições(monkeypatch):
    """A cota demo é 50/h; um vídeo com 12 cenas passaria dela fácil."""
    from curio.media import providers as P
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "fake")
    prov = P.UnsplashProvider()
    assert P.UnsplashProvider.MAX_REQUESTS == 15
    for i in range(P.UnsplashProvider.MAX_REQUESTS):
        prov._exhausted()
    assert prov.requests_used == P.UnsplashProvider.MAX_REQUESTS
    with pytest.raises(P.MediaError, match="orçamento"):
        prov._exhausted()
    assert prov.requests_used == P.UnsplashProvider.MAX_REQUESTS, "estourou o teto"


def test_unsplash_esgotado_nao_derruba_o_provedor(monkeypatch):
    """O erro é MediaError comum: o chamador segue para o próximo."""
    from curio.media import providers as P
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "fake")
    prov = P.UnsplashProvider()
    prov.requests_used = P.UnsplashProvider.MAX_REQUESTS
    with pytest.raises(P.MediaError):
        prov.search("qualquer coisa")


def test_unsplash_e_ultimo_na_ordem_de_prioridade():
    """Foto bonita que foge do assunto é o último recurso, não o primeiro."""
    from curio.stages.media_provider_policy import PROVIDER_PRIORITY
    assert PROVIDER_PRIORITY[-1] == "unsplash"
    # e os acervos abertos, que são os mais específicos, vêm antes dele
    for aberto in ("wikimedia", "openverse", "nasa"):
        assert PROVIDER_PRIORITY.index(aberto) < PROVIDER_PRIORITY.index("unsplash")
