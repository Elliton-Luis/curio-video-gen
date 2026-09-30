"""Etapa 5 — estratégia visual: a cena nunca fica sem visual.

O ponto que este arquivo trava: quando não há fotografia adequada, a cena
troca de MEDIUM. Ela não fica vazia e não recebe imagem genérica. Um
diagrama ou um cartão é a cena certa mostrada do jeito certo, e por isso
não pode ser contado como falha nas métricas.
"""

import os

import pytest

from curio.stages import visuals
from curio.stages.scenes import Chapter

PIL = pytest.importorskip("PIL")


def _ch(vtype="mechanism", subject="thermal receipt paper", entities=(),
        narration="O calor altera o corante e a imagem aparece.",
        queries=()):
    return Chapter(id=1, narration=narration, duration_estimate=8.0,
                   visual_type=vtype, subject=subject,
                   visual_entities=list(entities), context=[], forbidden=[],
                   visual_queries=list(queries))


# --- a escada depende do tipo de visual -------------------------------

@pytest.mark.parametrize("vtype,primeira", [
    ("mechanism", "diagram"),      # processo: foto não mostra
    ("typographic", "card"),       # a ideia é uma palavra
    ("conceptual", "card"),
    ("historical_art", "art"),     # tenta arte de domínio público antes
    ("literal", "image"),
])
def test_escada_comeca_pela_estrategia_certa(vtype, primeira):
    assert visuals.strategies_for(_ch(vtype))[0] == primeira


def test_historico_nao_cai_em_diagrama_antes_do_cartao():
    """Um diagrama "fresco → monge → bird" não explica um santo."""
    escada = visuals.strategies_for(_ch("historical_art"))
    assert escada.index("card") < escada.index("diagram")


def test_mecanismo_nao_comeca_por_foto():
    escada = visuals.strategies_for(_ch("mechanism"))
    assert "image" not in escada[:1]
    assert escada[0] == "diagram"


def test_tipo_desconhecido_cai_na_escada_literal():
    assert visuals.strategies_for(_ch("banana")) == visuals.strategies_for(
        _ch("literal"))


# --- o visual produzido ------------------------------------------------

def test_mecanismo_vira_diagrama(tmp_path):
    a = visuals.visual_for_scene(_ch("mechanism",
                                     entities=["thermal printer", "heat",
                                               "dye change", "image appears"]),
                                 str(tmp_path))
    assert a is not None
    assert a.provider == "synth"
    assert a.kind == "image"
    assert "Diagrama" in a.title
    assert a.width == visuals.W and a.height == visuals.H
    assert os.path.getsize(a.local_path) > 10000


def test_tipografico_vira_cartao_com_a_palavra(tmp_path):
    a = visuals.visual_for_scene(
        _ch("typographic", subject="salarium", queries=["salarium", "sal"],
            narration="A palavra salário vem do latim salarium."), str(tmp_path))
    assert "Card" in a.title
    assert os.path.isfile(a.local_path)
    assert os.path.getsize(a.local_path) > 10000


def test_historico_sem_arte_cai_no_cartao(tmp_path):
    a = visuals.visual_for_scene(
        _ch("historical_art", subject="saint francis of assisi",
            entities=["fresco", "monk"]), str(tmp_path))
    assert "Card" in a.title, "histórico não deve virar diagrama"


def test_visual_e_licenca_livre_por_ser_nosso(tmp_path):
    """provider='synth' é o que faz classify_rights marcar como clear."""
    from curio.media.providers import classify_rights
    a = visuals.visual_for_scene(_ch("mechanism", entities=["a"]), str(tmp_path))
    assert a.rights_status == "clear"
    assert classify_rights(a.license, a.provider) == "clear"


def test_visual_tem_licenca_e_autor_declarados(tmp_path):
    a = visuals.visual_for_scene(_ch("mechanism", entities=["a"]), str(tmp_path))
    assert a.license
    assert a.used_in.startswith("cena ")


# --- determinismo e cache ---------------------------------------------

def test_mesma_cena_gera_o_mesmo_arquivo(tmp_path):
    ch = _ch("mechanism", entities=["a", "b"])
    a1 = visuals.visual_for_scene(ch, str(tmp_path))
    a2 = visuals.visual_for_scene(ch, str(tmp_path))
    assert a1.local_path == a2.local_path
    assert a1.asset_id == a2.asset_id


def test_cache_reaproveita_o_png(tmp_path):
    ch = _ch("mechanism", entities=["a", "b"])
    a1 = visuals.visual_for_scene(ch, str(tmp_path))
    mtime = os.path.getmtime(a1.local_path)
    visuals.visual_for_scene(ch, str(tmp_path))
    assert os.path.getmtime(a1.local_path) == mtime, "re-desenhou do zero"


def test_cenas_diferentes_geram_arquivos_diferentes(tmp_path):
    a1 = visuals.visual_for_scene(_ch("mechanism", subject="papel termico",
                                      entities=["x"]), str(tmp_path))
    a2 = visuals.visual_for_scene(_ch("mechanism", subject="bateria",
                                      entities=["y"]), str(tmp_path))
    assert a1.local_path != a2.local_path


# --- robustez: nada aqui pode quebrar o vídeo -------------------------

def test_cena_sem_nada_declarado_ainda_produz_visual(tmp_path):
    """Campos vazios (divisão local, IA sem os campos) não podem quebrar."""
    a = visuals.visual_for_scene(
        Chapter(id=1, narration="Uma cena qualquer.", duration_estimate=5.0,
                visual_type="mechanism"), str(tmp_path))
    assert a is not None
    assert os.path.getsize(a.local_path) > 10000


def test_texto_muito_longo_quebra_em_linhas(tmp_path):
    a = visuals.visual_for_scene(
        _ch("typographic",
            subject="uma expressao absurdamente longa para caber numa linha so",
            narration="palavra " * 60), str(tmp_path))
    assert os.path.getsize(a.local_path) > 10000


def test_build_visual_recusa_estrategia_desconhecida(tmp_path):
    assert visuals.build_visual(_ch("mechanism"), "video3d",
                                str(tmp_path)) is None


def test_cena_literal_tem_escada_ate_o_cartao(tmp_path):
    """Literal sem foto não pode ficar vazia: o cartão é o último chão."""
    escada = visuals.strategies_for(_ch("literal"))
    assert escada[-1] == "card"


# --- integração: o renderizador consome sem mudança -------------------

def test_visual_entra_no_render_sem_ajuste(tmp_path):
    """Prova de que a escada não exigiu tocar no renderizador: o PNG gerado
    é um MediaAsset comum e o collage o aceita como imagem normal."""
    from curio.config import CurioConfig
    from curio.stages import render as render_stage
    a = visuals.visual_for_scene(_ch("mechanism", entities=["a", "b"]),
                                 str(tmp_path))
    cfg = CurioConfig(render_backend="cpu", width=160, height=284, fps=12)
    seg = render_stage.render_image_segment(a.local_path, 1.5,
                                            str(tmp_path / "seg.mp4"), cfg, 0)
    assert os.path.isfile(seg)
    assert os.path.getsize(seg) > 1000
