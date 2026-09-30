"""Ruído de provider ausente e diagnóstico de download.

Duas coisas que a execução de São Jerônimo mostrou, e que são
independentes: um aviso de provider sem chave que se repete por cena, e
um "download falhou (HTTP 403)" que não diz se o provedor está vazio ou
está baixando mal.
"""

import pytest
import itertools
from pathlib import Path

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


def test_relatorio_vai_para_o_metadata(fetch):
    """O relatório precisa chegar ao metadata.json, não ficar só em memória.

    A verificação é sobre o texto do pipeline (o caminho inteiro de um
    `generate` até o JSON exigiria rede e TTS), e o caminho é montado a
    partir do pacote instalado — não de "src/curio/pipeline.py", que só
    existe se o pytest rodar a partir da raiz do repositório.
    """
    import curio.pipeline as PL
    src = Path(PL.__file__).read_text(encoding="utf-8")
    assert "provider_downloads" in src, "o relatório precisa ir para o metadata"
    assert 'metrics.media_download_report()' in src


# --- reutilização: permitida, e agora observável --------------------

def _cena(cid, assets, reused_from=None):
    return {"chapter_id": cid,
            "asset": assets[0] if assets else None,
            "assets": [{"asset": a, "order": i} for i, a in enumerate(assets)],
            "reused_from": reused_from}


def _a(aid, title="t", prov="wikimedia"):
    return {"asset_id": aid, "title": title, "provider": prov}


def test_mesmo_asset_em_duas_cenas_e_registrado():
    """O caso de São Jerônimo: cena 1 e cena 3, mesma pintura.

    As duas cenas TINHAM mídia própria — cada uma buscou e o provedor
    devolveu o mesmo melhor resultado. `_resolve_reuse_multi` não trata
    esse caso, porque ele só preenche cena vazia, e `reused_from` ficava
    vazio nas duas. Sem registro, a repetição só aparecia comparando o
    media.json à mão.
    """
    from curio.stages import visual as V
    a = _a("Saint_Jerome_in_His_Study", "Saint Jerome in his study")
    scenes = [_cena(1, [a]), _cena(2, [_a("outra")]), _cena(3, [a])]
    V._annotate_reuse(scenes)
    reuso = scenes[2]["reuse"]
    assert len(reuso) == 1
    assert reuso[0]["previous_scene"] == 1
    assert reuso[0]["current_scene"] == 3
    assert reuso[0]["asset"] == "Saint_Jerome_in_His_Study"
    assert scenes[0]["reuse"] == []


def test_reutilizacao_NAO_e_proibida():
    """A anotação informa; ela não impede."""
    from curio.stages import visual as V
    a = _a("mesma")
    scenes = [_cena(1, [a]), _cena(2, [a])]
    V._annotate_reuse(scenes)
    assert scenes[1]["assets"], "o asset precisa continuar na cena"
    assert scenes[1]["asset"]["asset_id"] == "mesma"


def test_o_motivo_nao_afirma_intencao_editorial():
    """`thematic_reuse` seria invenção.

    Reuso editorial intencional é decisão do autor, e o curio não lê
    decisão em dado nenhum. O registro entrega o par de cenas e o asset
    para o autor decidir; afirmar o motivo seria chamar invenção de
    diagnóstico.
    """
    from curio.stages import visual as V
    a = _a("mesma")
    scenes = [_cena(1, [a]), _cena(3, [a])]
    V._annotate_reuse(scenes)
    r = scenes[1]["reuse"][0]
    assert r["reason"] == "same_top_match"
    assert "thematic" not in r["reason"]


def test_asset_repetido_tres_vezes_aparece_nas_duas_repeticoes():
    """`previous_scene` aponta a PRIMEIRA ocorrência, não a anterior.

    A pergunta do autor é "onde mais essa imagem aparece", e a primeira
    ocorrência é onde a imagem foi escolhida. Apontar para a cena
    imediatamente anterior daria uma cadeia sem origem, e na cena 3 o
    registro diria 2 quando a imagem entrou na 1.
    """
    from curio.stages import visual as V
    a = _a("mesma")
    scenes = [_cena(1, [a]), _cena(2, [a]), _cena(3, [a])]
    V._annotate_reuse(scenes)
    assert scenes[0]["reuse"] == []
    assert scenes[1]["reuse"][0]["previous_scene"] == 1
    assert scenes[2]["reuse"][0]["previous_scene"] == 1


def test_cena_sem_repeticao_registra_lista_vazia():
    """O campo existe sempre: ausência de registro precisa ser distinguível
    de 'a anotação não rodou'."""
    from curio.stages import visual as V
    scenes = [_cena(1, [_a("a")]), _cena(2, [_a("b")])]
    V._annotate_reuse(scenes)
    assert scenes[0]["reuse"] == [] and scenes[1]["reuse"] == []


def test_asset_sem_id_nao_quebra():
    from curio.stages import visual as V
    scenes = [_cena(1, [{"title": "sem id"}]), _cena(2, [{"title": "sem id"}])]
    V._annotate_reuse(scenes)
    assert scenes[1]["reuse"] == []


def test_cena_sem_midia_continua_usando_reused_from():
    """Os dois mecanismos convivem: `reused_from` é falta de alternativa,
    `reuse` é o mesmo melhor resultado em duas cenas."""
    from curio.stages import visual as V
    a = _a("so_esta")
    scenes = [_cena(1, [a]), _cena(2, [], reused_from=1)]
    V._annotate_reuse(scenes)
    assert scenes[1]["reused_from"] == 1
    assert scenes[1]["reuse"] == []
