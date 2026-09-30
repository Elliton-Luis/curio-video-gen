"""Grounding: o aviso continua, e agora diz onde olhar.

O aviso de "2 dado(s) sem correspondência: 135, 393" não levava ninguém a
lugar nenhum — 135 é um número, não um identificador, e um texto de
dois minutos tem dezenas. Estes testes verificam duas coisas separadas:

1. o gate NÃO mudou: a mesma contagem, a mesma cobertura, as mesmas
   afirmações reprovadas;
2. o diagnóstico passou a ter endereço — a afirmação, onde ela está, as
   fontes avaliadas e uma causa provável.
"""

import pytest

from curio.stages import research as R


def fontes(*snippets):
    return [R.ResearchSource(title=f"Fonte {i+1}", url=f"u{i}",
                             snippet=s) for i, s in enumerate(snippets)]


ROTEIRO = ("São Jerônimo nasceu por volta de 347 e morreu em 420. "
           "A Vulgata traduziu a Bíblia e o trabalho levou 135 anos. "
           "Ele fundou o mosteio em 393 e recebeu 400 presentes.")


# --- o gate não mudou -------------------------------------------------

def test_afirmacoes_sem_fonte_continuam_sendo_detectadas():
    g = R.verify_grounding(ROTEIRO,
                           fontes("Nasceu em 347 e morreu em 420. "
                                  "Traduziu a Vulgata ao latim."))
    assert g["unverified"], "o aviso não pode sumir"


def test_a_contagem_e_a_cobertura_nao_mudaram():
    """O diagnóstico é acréscimo. O gate é o mesmo de sempre."""
    g = R.verify_grounding(ROTEIRO,
                           fontes("Nasceu em 347 e morreu em 420. "
                                  "Traduziu a Vulgata ao latim."))
    assert g["checked"] == 6
    assert g["coverage"] == pytest.approx(0.333, abs=0.01)
    assert set(g["unverified"]) == {"135", "135 anos", "393", "400"}


def test_grounded_continua_funcionando():
    g = R.verify_grounding("Ele nasceu em 347 e morreu em 420.",
                           fontes("Nasceu em 347, morreu em 420."))
    assert not g["unverified"]
    assert g["checked"] == 2


def test_roteiro_sem_numeros_nao_avisa():
    g = R.verify_grounding("A história de uma vida.", fontes("nada numérico"))
    assert g["unverified"] == []
    assert g["checked"] == 0


def test_aumento_de_fontes_nao_some_com_o_aviso():
    """O aviso não pode ser calado por material melhor — nem por material
    pior. O gate decide; o diagnóstico informa."""
    sem = R.verify_grounding(ROTEIRO, fontes("Nada numérico aqui."))
    com = R.verify_grounding(ROTEIRO, fontes(
        "Nasceu em 347 e morreu em 420. Traduziu a Vulgata."))
    assert sem["checked"] == com["checked"] == 6
    assert sem["coverage"] < com["coverage"]


# --- o diagnóstico tem endereço ---------------------------------------

def test_o_diagnostico_traz_a_afirmacao():
    g = R.verify_grounding(ROTEIRO, fontes("Nasceu em 347. Vulgata."))
    textos = " ".join(d["claim"] for d in g["unverified_detail"])
    assert "135 anos" in textos
    assert "levou 135 anos" in textos


def test_o_diagnostico_aponta_o_trecho_certa():
    """A janela tem que conter o número e a frase em volta, senão é ruído."""
    g = R.verify_grounding(ROTEIRO, fontes("Nasceu em 347. Vulgata."))
    por_fato = {d["fact"]: d for d in g["unverified_detail"]}
    assert "levou 135 anos" in por_fato["135 anos"]["claim"]
    assert "fundou o mosteio em 393" in por_fato["393"]["claim"]


def test_o_diagnostico_lista_as_fontes_avaliadas():
    g = R.verify_grounding(ROTEIRO, fontes("a", "b", "c"))
    assert g["sources_checked"] == ["Fonte 1", "Fonte 2", "Fonte 3"]


def test_a_causa_distingue_fonte_com_outro_valor():
    """Mesma unidade com número diferente é um problema diferente de
    "não existe número nenhum aqui"."""
    g = R.verify_grounding(
        "O texto diz que o trabalho levou 135 anos.",
        fontes("O trabalho levou 20 anos."))

    # A entrada que carrega a UNIDADE é a que pode achar o irmão: o
    # número solto "135" não tem com que comparar, porque não diz o quê.
    d = next(x for x in g["unverified_detail"] if x["fact"] == "135 anos")
    assert d["cause"].startswith("fonte_presente_valor_diferente")
    assert "20" in d["cause"]
    solto = next(x for x in g["unverified_detail"] if x["fact"] == "135")
    assert solto["cause"] == "valor_ausente_das_fontes"


def test_a_causa_distingue_fontes_sem_numero():
    g = R.verify_grounding(
        "O texto diz que o trabalho levou 135 anos.",
        fontes("Ele traduziu a Bíblia."))
    assert all(d["cause"] == "fontes_sem_dado_numerico"
               for d in g["unverified_detail"])


def test_a_causa_padrao_e_valor_ausente():
    g = R.verify_grounding(
        "O texto diz que o trabalho levou 135 anos.",
        fontes("Ele nasceu em 347 e recebeu 900 cartas."))
    assert all(d["cause"] == "valor_ausente_das_fontes"
               for d in g["unverified_detail"])


def test_numeros_solto_e_com_unidade_nao_viram_dois_itens_na_exibicao():
    """135 e "135 anos" são o mesmo dado; o log mostra uma vez, com unidade."""
    g = R.verify_grounding(ROTEIRO, fontes("Nasceu em 347. Vulgata."))
    exibidos = [d["fact"] for d in g["unverified_display"]]
    assert "135 anos" in exibidos
    assert "135" not in exibidos
    # o gate continua contando os dois
    assert "135" in g["unverified"]


def test_o_relatorio_lista_a_afirmacao_e_a_causa(tmp_path):
    from curio.stages import sources as S
    g = R.verify_grounding(ROTEIRO, fontes("Nasceu em 347. Vulgata."))
    reg = S.SourceRegistry(slug="proj")
    out = str(tmp_path / "FONTES.md")
    S.write_report(out, reg, research=fontes("Nasceu em 347. Vulgata."),
                   grounding=g)
    md = open(out, encoding="utf-8").read()
    assert "Não encontrados nas fontes" in md
    assert "135 anos" in md
    assert "levou 135 anos" in md
    assert "valor_ausente_das_fontes" in md
    assert "Fonte 1" in md


def test_relatorio_com_grounding_vazio_nao_quebra(tmp_path):
    from curio.stages import sources as S
    g = R.verify_grounding("Sem números.", fontes("nada"))
    reg = S.SourceRegistry(slug="proj")
    out = str(tmp_path / "F.md")
    S.write_report(out, reg, research=fontes("nada"), grounding=g)
    assert "Conferência anti-invenção" in open(out, encoding="utf-8").read()


# --- o que o usuário lê no terminal -----------------------------------

def test_o_aviso_no_terminal_aponta_a_afirmacao(capsys):
    """A frase sozinha não basta: o console tem que dizer o que olhar.

    Este é o teste que faltava — todos os outros olham `verify_grounding`,
    que é a estrutura. O que a pessoa lê no terminal é a string, e uma
    string que volta a dizer "135, 393" resolve o problema que o aviso
    existe para resolver.
    """
    from curio import pipeline as P
    g = R.verify_grounding(ROTEIRO, fontes("Nasceu em 347. Vulgata."))
    msg = P._print_grounding_warning(g)
    err = capsys.readouterr().err
    assert msg == ("5 afirmações do roteiro sem correspondência nas fontes")
    assert "135 anos" in err and "levou 135 anos" in err
    assert "possível causa: valor_ausente_das_fontes" in err
    assert "Fontes avaliadas: Fonte 1" in err
    assert "sources/FONTES.md" in err
    # e o número continua fora do padrão "135, 393": o id não é a informação
    assert "sem correspondência nas fontes: 135" not in err


def test_o_aviso_conta_cada_afirmacao_uma_vez(capsys):
    """135 e "135 anos" são um dado só no texto exibido."""
    from curio import pipeline as P
    g = R.verify_grounding(ROTEIRO, fontes("Nasceu em 347. Vulgata."))
    P._print_grounding_warning(g)
    err = capsys.readouterr().err
    assert err.count("  - ") == len(g["unverified_display"])


def test_uma_afirmacao_so_fala_no_singular(capsys):
    from curio import pipeline as P
    g = R.verify_grounding("Ele recebeu 400 presentes em 393.",
                           fontes("Nada disso aparece."))
    msg = P._print_grounding_warning(g)
    capsys.readouterr()
    assert msg.startswith("2 afirmações")
