"""Regressão de roteiro: gancho, explicação imediata e fato-âncora.

Casos reais:
- Buracos negros abriu com definição ("Um buraco negro é um objeto...") em
  vez de consequência extrema, e nunca explicou o estranho na hora.
- Marco Aurélio citou dois imperadores sem explicar como dividiam o poder
  (quem mandava no quê) e omitiu o fato-âncora (o último dos bons
  imperadores).
"""

from curio.stages import editorial as E
from curio.stages import nvidia


def test_gancho_proibe_definicao():
    for prompt in (nvidia.SCRIPT_SYSTEM_PROMPT, nvidia.SCRIPT_SYSTEM_PROMPT_EN):
        baixo = prompt.lower()
        assert "defini" in baixo  # a proibição existe nos dois idiomas
    assert "PROIBIDO abrir com definição" in nvidia.SCRIPT_SYSTEM_PROMPT
    assert "NEVER open with a definition" in nvidia.SCRIPT_SYSTEM_PROMPT_EN


def test_estranheza_pede_explicacao_imediata():
    assert "EXPLICAÇÃO IMEDIATA" in nvidia.SCRIPT_SYSTEM_PROMPT
    assert "como dividiam o poder" in nvidia.SCRIPT_SYSTEM_PROMPT
    assert "IMMEDIATE EXPLANATION" in nvidia.SCRIPT_SYSTEM_PROMPT_EN
    assert "who commanded what" in nvidia.SCRIPT_SYSTEM_PROMPT_EN


def test_fato_ancora_nunca_cortado():
    assert "FATO-ÂNCORA" in nvidia.SCRIPT_SYSTEM_PROMPT
    assert "LEGACY ANCHOR" in nvidia.SCRIPT_SYSTEM_PROMPT_EN
    for prompt in (nvidia.SCRIPT_SYSTEM_PROMPT, nvidia.SCRIPT_SYSTEM_PROMPT_EN):
        assert "nunca" in prompt.lower() or "never" in prompt.lower()


def test_final_retoma_o_gancho():
    assert "retomar a imagem do gancho" in nvidia.SCRIPT_SYSTEM_PROMPT.lower()
    assert "return" in nvidia.SCRIPT_SYSTEM_PROMPT_EN.lower()
    assert "hook" in nvidia.SCRIPT_SYSTEM_PROMPT_EN.lower()


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
