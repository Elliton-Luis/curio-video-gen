"""User-Agent e rate limit da Wikimedia.

O 429 da Wikimedia não é problema de rede, é política de User-Agent, e a
mensagem antiga dizia "verifique a rede". Esses testes existem para que a
regra da Wikimedia e o comportamento do retry não dependam de alguém
descobrir de novo na base do 429.
"""

import urllib.error
import urllib.request

import pytest

from curio import ua


def test_contato_configurado_entra_no_user_agent(monkeypatch):
    monkeypatch.setenv("CURIO_CONTACT", "alguem@exemplo.com")
    monkeypatch.delenv("CURIO_WIKI_UA", raising=False)
    assert "alguem@exemplo.com" in ua.user_agent()
    assert ua.tem_contato() is True
    assert ua.aviso_contato() == ""


def test_curio_wiki_ua_por_tem_precedencia(monkeypatch):
    monkeypatch.setenv("CURIO_CONTACT", "alguem@exemplo.com")
    monkeypatch.setenv("CURIO_WIKI_UA", "meu-bot/2.0 (https://exemplo.org)")
    assert ua.user_agent() == "meu-bot/2.0 (https://exemplo.org)"


def test_sem_contato_avisa_e_nao_falha(monkeypatch):
    monkeypatch.delenv("CURIO_CONTACT", raising=False)
    monkeypatch.delenv("CURIO_WIKI_UA", raising=False)
    assert ua.tem_contato() is False
    assert "CURIO_CONTACT" in ua.aviso_contato()
    # o UA continua identificando a ferramenta
    assert ua.user_agent().startswith("curio/")


def test_user_agent_tem_formato_exigido_pela_wikimedia(monkeypatch):
    """A política pede nome/versão, contato entre parênteses e a biblioteca."""
    monkeypatch.setenv("CURIO_CONTACT", "alguem@exemplo.com")
    ua_ = ua.user_agent()
    assert ua_.startswith("curio/") and "(" in ua_ and ")" in ua_
    assert "urllib" in ua_


def test_modulo_unico_de_user_agent():
    """research e media precisam falar com a mesma identidade."""
    from curio.media import providers
    from curio.stages import research
    assert research.USER_AGENT == ua.user_agent()
    assert providers.USER_AGENT == ua.user_agent()


# --- retry -------------------------------------------------------------

def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "erro", {}, None)


def test_429_e_retentado_e_hoje_erra(monkeypatch):
    from curio.stages import research as R
    monkeypatch.setenv("CURIO_CONTACT", "alguem@exemplo.com")
    R.USER_AGENT = ua.user_agent()
    monkeypatch.setattr("time.sleep", lambda s: None)
    chamadas = []

    def boom(req, timeout=None):
        chamadas.append(1)
        raise _http_error(429)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(R.ResearchError) as ei:
        R._get_json("https://pt.wikipedia.org/w/api.php?x=1")
    # três tentativas: o retry é o que diferencia "levou rate limit" de
    # "a ferramenta não funciona com a Wikimedia"
    assert len(chamadas) == 3
    msg = str(ei.value)
    assert "429" in msg
    # a mensagem antiga mandava "verifique a rede", que é o diagnóstico
    # errado: a rede estava ótima e o User-Agent é que não tinha contato
    assert "Verifique a rede" not in msg
    # com o contato já configurado não há o que sugerir
    assert "CURIO_CONTACT" not in msg


def test_429_sem_contato_diz_o_que_fazer(monkeypatch):
    from curio.stages import research as R
    monkeypatch.delenv("CURIO_CONTACT", raising=False)
    monkeypatch.delenv("CURIO_WIKI_UA", raising=False)
    R.USER_AGENT = ua.user_agent()
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: (_ for _ in ()).throw(
                            _http_error(429)))
    with pytest.raises(R.ResearchError) as ei:
        R._get_json("https://pt.wikipedia.org/w/api.php?x=1")
    assert "CURIO_CONTACT" in str(ei.value)


def test_429_que_passa_apos_uma_tentativa_nao_erra(monkeypatch):
    from curio.stages import research as R
    monkeypatch.setenv("CURIO_CONTACT", "alguem@exemplo.com")
    R.USER_AGENT = ua.user_agent()
    monkeypatch.setattr("time.sleep", lambda s: None)
    estado = {"n": 0}

    def as_vezes(req, timeout=None):
        estado["n"] += 1
        if estado["n"] == 1:
            raise _http_error(429)
        return _FakeResp('{"ok": true}')

    class _FakeResp:
        """A resposta que _get_json quer: um json.load() e ponto."""
        def __init__(self, payload): self._p = payload
        def read(self): return self._p.encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(urllib.request, "urlopen", as_vezes)
    assert R._get_json("https://pt.wikipedia.org/w/api.php?x=1") == {"ok": True}
    assert estado["n"] == 2


def test_erro_4xx_nao_eh_repetido(monkeypatch):
    """404 não melhora com espera; repetir só gasta o tempo do vídeo."""
    from curio.stages import research as R
    monkeypatch.setattr("time.sleep", lambda s: None)
    chamadas = []

    def boom(req, timeout=None):
        chamadas.append(1)
        raise _http_error(404)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(R.ResearchError):
        R._get_json("https://pt.wikipedia.org/w/api.php?x=1")
    assert len(chamadas) == 1


def test_5xx_usa_backoff_mas_nao_mais_de_tres_vezes(monkeypatch):
    from curio.stages import research as R
    monkeypatch.setattr("time.sleep", lambda s: None)
    chamadas = []

    def boom(req, timeout=None):
        chamadas.append(1)
        raise _http_error(503)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(R.ResearchError):
        R._get_json("https://pt.wikipedia.org/w/api.php?x=1")
    assert len(chamadas) == 3
