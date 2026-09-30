"""User-Agent único para tudo que o curio baixa da internet.

Existe por um motivo concreto: a Wikimedia (API da Wikipedia e Commons
inteira) aplica uma política de User-Agent que exige um contato — uma URL
ou um e-mail — no parênteses. Sem contato, a resposta não é um erro
claro: é HTTP 429 em toda requisição. A ferramenta então afirma que "a
Wikipedia está indisponível, verifique a rede", quando a rede está
perfeita, e ainda por cima engole a falha nas imagens do Commons, que
caem silenciosamente no provedor seguinte.

Por isso o contato é configuração, não constante. Defina uma vez:

    export CURIO_CONTACT="seu-email@exemplo.com"
    # ou, para trocar a linha inteira:
    export CURIO_WIKI_UA="curio/0.1 (https://seu.site) python-urllib/3"

Sem nenhum dos dois, o padrão ainda identifica a ferramenta, e o
`doctor` avisa que a Wikimedia pode responder 429.
"""

from __future__ import annotations

import os
import sys

VERSION = "0.1"
PLACEHOLDER = "contato não configurado (defina CURIO_CONTACT)"


def _python_ua() -> str:
    name = "python-urllib"
    ver = ".".join(str(p) for p in sys.version_info[:2])
    return f"{name}/{ver}"


def user_agent() -> str:
    """O User-Agent a ser enviado, com o contato que o usuário configurou."""
    inteiro = os.environ.get("CURIO_WIKI_UA", "").strip()
    if inteiro:
        return inteiro
    contato = os.environ.get("CURIO_CONTACT", "").strip() or PLACEHOLDER
    return f"curio/{VERSION} ({contato}) {_python_ua()}"


def tem_contato() -> bool:
    """Diz se há um contato real — ou seja, se a Wikimedia vai aceitar."""
    if os.environ.get("CURIO_WIKI_UA", "").strip():
        return True
    return bool(os.environ.get("CURIO_CONTACT", "").strip())


def aviso_contato() -> str:
    """Mensagem para o doctor. Vazia quando está tudo certo."""
    if tem_contato():
        return ""
    return (
        "A Wikimedia exige contato no User-Agent e vai responder 429 sem "
        "ele. A pesquisa e as imagens do Commons podem falhar. Defina:\n"
        "    export CURIO_CONTACT=\"seu-email@exemplo.com\"")
