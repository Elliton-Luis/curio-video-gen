"""Regressão de roteiro: gancho, explicação imediata e fato-âncora.

Casos reais:
- Buracos negros abriu com definição ("Um buraco negro é um objeto...") em
  vez de consequência extrema, e nunca explicou o estranho na hora.
- Marco Aurélio citou dois imperadores sem explicar como dividiam o poder
  (quem mandava no quê) e omitiu o fato-âncora (o último dos bons
  imperadores).
"""

from curio.stages import editorial as E
from curio.stages import prompts


def test_gancho_proibe_definicao():
    assert "PROIBIDO" in prompts.SCRIPT_SYSTEM_PROMPT
    assert "definições" in prompts.SCRIPT_SYSTEM_PROMPT
    assert "FORBIDDEN" in prompts.SCRIPT_SYSTEM_PROMPT_EN
    assert "textbook definitions" in prompts.SCRIPT_SYSTEM_PROMPT_EN


def test_estranheza_pede_explicacao_imediata():
    assert "frase seguinte" in prompts.SCRIPT_SYSTEM_PROMPT
    assert "explicação clara" in prompts.SCRIPT_SYSTEM_PROMPT
    assert "next sentence" in prompts.SCRIPT_SYSTEM_PROMPT_EN
    assert "plain-language explanation" in prompts.SCRIPT_SYSTEM_PROMPT_EN


def test_fato_ancora_e_obrigatorio():
    assert "FATO-ÂNCORA" in prompts.SCRIPT_SYSTEM_PROMPT
    assert "LEGACY ANCHOR" in prompts.SCRIPT_SYSTEM_PROMPT_EN


def test_final_retoma_o_gancho():
    assert "conectando com a imagem do gancho" in prompts.SCRIPT_SYSTEM_PROMPT.lower()
    assert "looping back to the opening hook image" in prompts.SCRIPT_SYSTEM_PROMPT_EN.lower()


def test_roteiro_deixa_aprendizado_claro_e_contavel():
    assert "sem rever o vídeo" in prompts.SCRIPT_SYSTEM_PROMPT
    assert "contá-la a alguém" in prompts.SCRIPT_SYSTEM_PROMPT
    assert "without replaying" in prompts.SCRIPT_SYSTEM_PROMPT_EN
    assert "tell someone what they learned" in prompts.SCRIPT_SYSTEM_PROMPT_EN


def test_genero_pessoa_explica_instituicao_e_ancora_legado():
    p = E.get("people")
    assert "quem mandava no quê" in p.narrative.direction
    assert "fato-âncora" in p.narrative.direction
    assert "instituição estranha" in p.narrative.avoid
    # continuidade da pessoa nas imagens
    assert "A PESSOA" in p.visual.scene_direction


def test_genero_ciencia_abre_no_extremo_e_fecha_no_gancho():
    s = E.get("science")
    assert "nunca por definição" in s.narrative.direction
    assert "última coisa a existir" in s.narrative.direction
    assert "gancho" in s.ending


def test_pesquisa_de_pessoa_inclui_governo():
    assert "governo" in E.get("people").research.queries
    assert "biografia" in E.get("people").research.queries
