"""Ruído de provider ausente e diagnóstico de download.

Duas coisas que a execução de São Jerônimo mostrou, e que são
independentes: um aviso de provider sem chave que se repete por cena, e
um "download falhou (HTTP 403)" que não diz se o provedor está vazio ou
está baixando mal.
"""

import pytest

from curio.media import providers as P
from curio.media import cache as C
from curio.metrics import RunMetrics


# --- provider indisponível avisa uma vez por execução -----------------

def _cfg(providers="pixabay,unsplash,pexels,nasa,wikimedia"):
    from curio.config import CurioConfig
    cfg = CurioConfig()
    cfg.media_providers = providers
    return cfg


def test_sem_chave_avisa_uma_vez_por_execucao(monkeypatch, capsys):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    P.reset_provider_health()
    cfg = _cfg()
    for _ in range(12):          # doze cenas
        P.get_providers(cfg)
    err = capsys.readouterr().err
    assert err.count("pexels ignorado") == 1, err


def test_aviso_diz_o_que_fazer(monkeypatch, capsys):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    P.reset_provider_health()
    P.get_providers(_cfg())
    err = capsys.readouterr().err
    assert "PEXELS_API_KEY" in err
    assert "demais fontes continuam em uso" in err


def test_aviso_nao_repete_por_provedor(monkeypatch, capsys):
    """Cada provider fala uma vez, não um por cena nem um por provider."""
    for env in ("PEXELS_API_KEY", "PIXABAY_API_KEY", "UNSPLASH_ACCESS_KEY"):
        monkeypatch.delenv(env, raising=False)
    P.reset_provider_health()
    cfg = _cfg()
    for _ in range(5):
        P.get_providers(cfg)
    err = capsys.readouterr().err
    for nome in ("pexels", "pixabay", "unsplash"):
        assert err.count(f"{nome} ignorado") == 1, (nome, err)


def test_provider_sem_chave_nao_e_instantiado_de_novo(monkeypatch):
    """O aviso único é consequência do memo, não um filtro de log.

    Reconstruir o provider sem chave a cada cena é trabalho inútil, e o
    pedido foi explícito: parar de tentar.
    """
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    P.reset_provider_health()
    construcoes = []

    class Contavel:
        def __init__(self):
            construcoes.append(1)
            raise P.MediaError("pexels: sem PEXELS_API_KEY no ambiente")

    original = P.PROVIDERS["pexels"]
    P.PROVIDERS["pexels"] = Contavel
    try:
        for _ in range(6):
            P.get_providers(_cfg("pexels,nasa"))
    finally:
        P.PROVIDERS["pexels"] = original
        P.reset_provider_health()
    # UMA construção em seis chamadas: a primeira é a que descobre que
    # falta a chave. As cinco seguintes são evitadas pelo memo. Zero
    # também estaria errado, porque ninguém teria como saber.
    assert len(construcoes) == 1, construcoes


def test_fallback_permanece_intacto(monkeypatch, capsys):
    """Sem Pexels, os outros continuam na lista e na MESMA ordem."""
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    P.reset_provider_health()
    ps = P.get_providers(_cfg("pixabay,pexels,nasa,wikimedia"))
    nomes = [p.name for p in ps]
    assert "pexels" not in nomes
    assert "nasa" in nomes and "wikimedia" in nomes
    # a ordem relativa dos restantes não muda
    assert nomes == [n for n in ("pixabay", "pexels", "nasa", "wikimedia")
                     if n in nomes]


def test_com_chave_o_provider_entra(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "x" * 20)
    P.reset_provider_health()
    ps = P.get_providers(_cfg("pexels"))
    assert [p.name for p in ps] == ["pexels"]
    P.reset_provider_health()


def test_memoria_da_indisponibilidade_pode_ser_zerada(monkeypatch):
    """Mudar o ambiente tem de fazer o curio olhar de novo.

    Sem isto, instalar a chave no meio do processo deixa o provider
    marcado como indisponível para sempre — a mesma armadilha do cache de
    fontes, e a mesma razão de existir `clear_cache`.
    """
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    P.reset_provider_health()
    assert "pexels" not in [p.name for p in P.get_providers(_cfg("pexels"))]
    monkeypatch.setenv("PEXELS_API_KEY", "y" * 20)
    P.reset_provider_health()
    assert [p.name for p in P.get_providers(_cfg("pexels"))] == ["pexels"]
    P.reset_provider_health()


def test_nome_desconhecido_ainda_avisa_uma_vez(monkeypatch, capsys):
    P.reset_provider_health()
    for _ in range(4):
        P.get_providers(_cfg("naoexiste,nasa"))
    err = capsys.readouterr().err
    assert err.count("desconhecido") == 1
    P.reset_provider_health()


# --- diagnóstico de download por provider ----------------------------

def _metrics():
    return RunMetrics("proj", "ideia", "nar")


def _asset(provider, asset_id, url, fallback=""):
    return P.MediaAsset(provider=provider, asset_id=asset_id, title="t",
                        author="", license="CC0", license_url="",
                        source_url="", download_url=url,
                        download_fallback_url=fallback)


@pytest.fixture
def fetch(monkeypatch):
    def _set(fn):
        monkeypatch.setattr(C, "_fetch", fn)
    return _set


def test_403_conta_separado(tmp_path, fetch):
    m = _metrics()

    def fake(url):
        raise Exception("HTTP Error 403: Forbidden")

    fetch(fake)
    for i in range(3):
        with pytest.raises(Exception):
            C.download_asset(_asset("pixabay", f"b{i}", "http://x/i.jpg"),
                             str(tmp_path), m)
    rel = m.media_download_report()["pixabay"]
    assert rel["http_403"] == 3
    assert rel["other_errors"] == 0
    assert rel["downloads_failed"] == 3


def test_outro_erro_nao_vira_403(tmp_path, fetch):
    m = _metrics()

    def fake(url):
        raise TimeoutError("timed out")

    fetch(fake)
    with pytest.raises(Exception):
        C.download_asset(_asset("wikimedia", "c1", "http://x/i.jpg"),
                         str(tmp_path), m)
    rel = m.media_download_report()["wikimedia"]
    assert rel["http_403"] == 0
    assert rel["other_errors"] == 1


def test_sucesso_conta_no_provider_certo(tmp_path, fetch):
    m = _metrics()
    fetch(lambda url: b"x" * 50)
    C.download_asset(_asset("nasa", "a1", "http://x/ok.jpg"), str(tmp_path), m)
    rel = m.media_download_report()["nasa"]
    assert rel["downloads_attempted"] == 1
    assert rel["downloads_succeeded"] == 1
    assert rel["downloads_failed"] == 0


def test_fallback_que_funciona_nao_conta_falha_duas_vezes(tmp_path, fetch):
    """Uma tentativa ruim e uma boa: uma falha, um sucesso."""
    m = _metrics()

    def fake(url):
        if "primaria" in url:
            raise Exception("HTTP Error 403: Forbidden")
        return b"x" * 50

    fetch(fake)
    a = _asset("pixabay", "f1", "http://primaria/i.jpg",
               "http://secundaria/i.jpg")
    C.download_asset(a, str(tmp_path), m)
    rel = m.media_download_report()["pixabay"]
    assert rel["downloads_attempted"] == 2
    assert rel["downloads_failed"] == 1
    assert rel["downloads_succeeded"] == 1
    assert rel["http_403"] == 1


def test_cache_nao_conta_download(tmp_path, fetch):
    """Cache é cache: não é tentativa de download."""
    m = _metrics()
    fetch(lambda url: b"x" * 50)
    a = _asset("nasa", "k1", "http://x/k.jpg")
    C.download_asset(a, str(tmp_path), m)
    b = _asset("nasa", "k1", "http://x/k.jpg")
    C.download_asset(b, str(tmp_path), m)
    assert m.media_download_report()["nasa"]["downloads_attempted"] == 1


def test_relatorio_separa_achar_de_baixar(tmp_path, fetch):
    """A pergunta da execução: está vazio ou está baixando mal?

    Setenta candidatos e três 403 é um provedor que funciona; sete
    candidatos e zero tentativas é um provedor que não encontra nada. As
    duas coisas apareciam como a mesma linha de log.
    """
    m = _metrics()
    m.media_record_results("pixabay", 70)
    m.media_record_results("nasa", 4)

    def fake(url):
        raise Exception("HTTP Error 403: Forbidden")

    fetch(fake)
    for i in range(3):
        with pytest.raises(Exception):
            C.download_asset(_asset("pixabay", f"z{i}", "http://x/i.jpg"),
                             str(tmp_path), m)
    rel = m.media_download_report()
    assert rel["pixabay"]["candidates_found"] == 70
    assert rel["pixabay"]["http_403"] == 3
    assert rel["nasa"]["candidates_found"] == 4
    assert rel["nasa"]["downloads_attempted"] == 0


def test_relatorio_vazio_nao_quebra():
    assert _metrics().media_download_report() == {}


def test_relatorio_vai_para_o_metadata(tmp_path, monkeypatch, fetch):
    from curio.stages import visual as V
    m = _metrics()
    m.media_record_results("pixabay", 5)
    src = open("src/curio/pipeline.py", encoding="utf-8").read()
    assert "provider_downloads" in src, "o relatório precisa ir para o metadata"
