"""Contexto da entidade no roteiro, e o diagnóstico que o rodeia.

A execução de São Jerônimo mostrou que a pesquisa sabe exatamente quem é
o sujeito — nome canônico, formas alternativas, marcadores, armadilhas — e
que nada disso chegava ao gerador de roteiro. O roteiro era escrito a
partir da frase da ideia.

Estes testes olham a ESTRUTURA que alimenta o NIM, não a string final do
roteiro: o que importa é que o contexto exista, que traga a forma
canônica e as alternativas, e que não invente linguagem que ninguém
pediu.
"""

import pytest

from curio.stages import entity as EN
from curio.stages import nvidia as N


def sao_jeronimo() -> EN.TargetEntity:
    return EN.TargetEntity(
        name="São Jerônimo de Estrídia",
        aliases=["São Jerônimo", "Jerônimo de Estrídia",
                 "Eusébio Sofrônio Jerônimo"],
        discriminants=["Estridão", "Padre da Igreja", "Vulgata"],
        forbidden=["São Jerônimo RS", "São Jerônimo bairro"])


# --- o contexto chega ao prompt do NIM --------------------------------

def test_contexto_traz_a_forma_canonica_com_o_titulo():
    """A forma que identifica o padre da Igreja, não o prenome só."""
    ctx = EN.script_context(sao_jeronimo())
    assert "O SUJEITO DESTE VÍDEO É: São Jerônimo de Estrídia" in ctx


def test_contexto_traz_as_formas_contextuais():
    """O NIM pode encurtar, mas sabe o que é a mesma pessoa."""
    ctx = EN.script_context(sao_jeronimo())
    assert "São Jerônimo" in ctx
    assert "Jerônimo de Estrídia" in ctx
    assert "Eusébio Sofrônio Jerônimo" in ctx
    assert "mesma pessoa" in ctx


def test_contexto_traz_a_identidade_religiosa_sem_inventar_devocional():
    """Os marcadores vêm da resolução; a língua sagrada, não.

    A direção de arte pediu contexto preservado, não roteiro devocional.
    Um bloco que mandasse o modelo "inclua linguagem religiosa"
    produziria exatamente o oposto do desejado: invenção num vídeo
    documental.
    """
    ctx = EN.script_context(sao_jeronimo()).lower()
    assert "padre da igreja" in ctx
    for proibido in ("devocional", "oração", "rezar", "fé cristã",
                     "milagre", "sagrado"):
        assert proibido not in ctx, proibido


def test_contexto_traz_as_armadilhas_de_homonimo():
    ctx = EN.script_context(sao_jeronimo())
    assert "São Jerônimo RS" in ctx
    assert "NUNCA confunda" in ctx


def test_contexto_nao_substitui_a_resolucao_de_entidade():
    """Uma segunda fonte de verdade seria um problema, não uma feature.

    O bloco é derivado do MESMO TargetEntity que a pesquisa usou; nada
    aqui resolve, deduplica ou infere nome.
    """
    alvo = sao_jeronimo()
    ctx = EN.script_context(alvo)
    assert alvo.name in ctx
    for alias in alvo.aliases:
        assert alias in ctx


def test_tema_sem_entidade_nao_gera_bloco():
    """Sem nome canônico a preservar, o bloco só poluiria o prompt."""
    alvo = EN.TargetEntity(name="Por que o céu é azul?", is_entity=False,
                           topic_terms=["dispersão de rayleigh"])
    assert EN.script_context(alvo) == ""


def test_sem_alvo_nao_gera_bloco():
    assert EN.script_context(None) == ""


def test_contexto_ingles_quando_o_video_e_ingles():
    ctx = EN.script_context(sao_jeronimo(), "en-US")
    assert "THE SUBJECT OF THIS VIDEO IS: São Jerônimo de Estrídia" in ctx
    assert "same person as" in ctx
    assert "NEVER confuse" in ctx


def test_contexto_so_mente_quando_tem_oque_dizer():
    """Sem aliases nem discriminantes, o bloco é uma linha e não um muro."""
    alvo = EN.TargetEntity(name="Ana de Sousa")
    ctx = EN.script_context(alvo)
    assert ctx.count("\n") == 0
    assert "O SUJEITO DESTE VÍDEO É: Ana de Sousa" in ctx


# --- o NIM recebe de fato ---------------------------------------------

def _prompt_capturado(alvo, language="pt-BR"):
    msgs = []

    def espiao(messages, *a, **kw):
        msgs.extend(messages)
        raise RuntimeError("parou antes da rede")

    orig_chat, orig_any = N._chat, N.any_llm_available
    N._chat, N.any_llm_available = espiao, lambda: True
    try:
        N.generate_script("A história de São Jerônimo", "m", None, 10, 1200,
                          language=language,
                          entity_context=EN.script_context(alvo, language))
    except RuntimeError:
        pass
    finally:
        N._chat, N.any_llm_available = orig_chat, orig_any
    return next((m["content"] for m in msgs if m["role"] == "user"), "")


def test_o_nim_recebe_o_contexto_da_entidade():
    """O teste do §9: não a string final, o contexto que alimenta o NIM."""
    user = _prompt_capturado(sao_jeronimo())
    assert "O SUJEITO DESTE VÍDEO É: São Jerônimo de Estrídia" in user
    assert "São Jerônimo RS" in user


def test_a_ideia_continua_no_prompt():
    user = _prompt_capturado(sao_jeronimo())
    assert user.startswith("Escreva o roteiro de narração para a ideia:")
    assert "São Jerônimo" in user.splitlines()[0]


def test_o_contexto_vem_antes_das_fontes():
    """QUEM é o sujeito, depois O QUE dizer.

    A ordem importa para quem lê o prompt: a identidade vem antes do
    material de apoio, e o modelo Resolve quem antes de escolher o que
    contar.
    """
    from curio.stages import nvidia as NV
    msgs = []

    def espiao(messages, *a, **kw):
        msgs.extend(messages)
        raise RuntimeError("parou")

    orig_chat, orig_any = NV._chat, NV.any_llm_available
    NV._chat, NV.any_llm_available = espiao, lambda: True
    try:
        NV.generate_script("A história de São Jerônimo", "m", None, 10, 1200,
                           language="pt-BR",
                           entity_context=EN.script_context(sao_jeronimo()),
                           research="FONTES OBRIGATÓRIAS: [1] ...")
    except RuntimeError:
        pass
    finally:
        NV._chat, NV.any_llm_available = orig_chat, orig_any
    user = next(m["content"] for m in msgs if m["role"] == "user")
    assert user.index("O SUJEITO DESTE VÍDEO") < user.index("FONTES OBRIGATÓRIAS")


def test_sem_entidade_o_prompt_fica_como_era():
    user = _prompt_capturado(EN.TargetEntity(name="", is_entity=False))
    assert "O SUJEITO DESTE VÍDEO" not in user
    assert "Escreva o roteiro" in user
