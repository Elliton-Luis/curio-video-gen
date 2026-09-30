"""Inserções esparsas: 1–2 fotos complementares por VÍDEO, não por cena.

Contratos garantidos aqui (o resto é escolha estética):
- o orçamento é global: N inserções no vídeo inteiro, nunca N por cena;
- a foto de fundo (ordem 0) nunca é trocada nem vira cartão;
- abertura e fecho ficam limpos (a inserção vive no miolo);
- cada inserção cai no estilo pedido e marca o som no instante da entrada.
"""

import pytest

from curio.stages import visual as V
from curio.stages.scenes import Chapter


def _chapters(n: int, dur: float = 8.0) -> list[Chapter]:
    return [Chapter(id=i + 1, narration=f"cena {i + 1}",
                    duration_estimate=dur, start=i * dur, end=(i + 1) * dur)
            for i in range(n)]


def _asset(i: int) -> dict:
    return {"asset": {"asset_id": f"a{i}", "title": f"foto {i}",
                      "provider": "pixabay", "author": "", "license": "Pixabay",
                      "source_url": "u", "local_path": f"/tmp/f{i}.jpg",
                      "kind": "image"}}


def _scenes(chapters) -> list[dict]:
    """Cada cena com 2 candidatos: fundo + complementar."""
    return [{"chapter_id": c.id,
             "asset": _asset(0)["asset"],
             "assets": [{"asset": _asset(0)["asset"], "query": "a", "order": 0},
                        {"asset": _asset(1)["asset"], "query": "b", "order": 1}],
             "reused_from": None} for c in chapters]


def _overlays(timeline) -> list[dict]:
    return [im for t in timeline for im in t["images"] if im["order"] > 0]


# --- orçamento global ---------------------------------------------------

@pytest.mark.parametrize("n_scenes,budget", [(4, 1), (6, 1), (7, 2), (10, 2),
                                           (12, 2), (12, 3), (20, 2)])
def test_orcamento_global_respeitado(n_scenes, budget):
    chapters = _chapters(n_scenes)
    vt = V.build_visual_timeline(chapters, _scenes(chapters), 0.9, seed="s",
                                 insertions=budget)
    assert len(_overlays(vt)) == budget


def test_orcamento_zero_nunca_insere():
    chapters = _chapters(8)
    vt = V.build_visual_timeline(chapters, _scenes(chapters), 0.9, seed="s",
                                 insertions=0)
    assert _overlays(vt) == []
    assert all(len(t["images"]) == 1 for t in vt)


def test_mais_cenas_nao_vira_slideshow():
    """20 cenas com 2 de orçamento: 2 inserções, não 20 nem 40."""
    chapters = _chapters(20)
    vt = V.build_visual_timeline(chapters, _scenes(chapters), 0.9, seed="s",
                                 insertions=2)
    assert len(_overlays(vt)) == 2
    assert sum(len(t["images"]) for t in vt) == 22  # 20 fundos + 2 insertions


def test_cena_curta_nao_quebra_orcamento():
    chapters = [Chapter(id=i + 1, narration="x", duration_estimate=0.4,
                        start=i * 0.4, end=(i + 1) * 0.4) for i in range(6)]
    vt = V.build_visual_timeline(chapters, _scenes(chapters), 0.9, seed="s",
                                 insertions=2)
    assert len(_overlays(vt)) <= 2


# --- posição: abertura e fecho limpos, inserções espalhadas -----------

def test_abertura_e_fecho_nao_recebem_insercao():
    for n in (6, 8, 12, 20):
        picked = V.insertion_scenes(n, 2)
        assert 0 not in picked, f"abertura recebeu inserção (n={n})"
        assert (n - 1) not in picked, f"fecho recebeu inserção (n={n})"


def test_insercoes_espalhadas_nao_coladas():
    picked = sorted(V.insertion_scenes(12, 2))
    assert len(picked) == 2
    assert picked[1] - picked[0] >= 3, f"inserções coladas: {picked}"


def test_determinismo():
    """Mesmo tema, mesmo vídeo: a posição não muda entre execuções."""
    assert V.insertion_scenes(12, 2) == V.insertion_scenes(12, 2)


# --- conteúdo das inserções -------------------------------------------

def test_fundo_nunca_vira_cartao():
    chapters = _chapters(10)
    vt = V.build_visual_timeline(chapters, _scenes(chapters), 0.9, seed="s",
                                 insertions=2, insert_style="drop_in")
    for t in vt:
        base = t["images"][0]
        assert base["transition"] == "base"
        assert base["scale"] == 1.0
        assert base["rotation_deg"] == 0.0
        assert base["sfx"] is None  # o fundo nunca toca som


def test_insercao_usa_o_estilo_pedido():
    chapters = _chapters(10)
    vt = V.build_visual_timeline(chapters, _scenes(chapters), 0.9, seed="s",
                                 insertions=2, insert_style="drop_in")
    assert [im["transition"] for im in _overlays(vt)] == ["drop_in", "drop_in"]


def test_som_marca_o_instante_da_entrada():
    """O `at` do SFX é absoluto e coincide com o início da foto na cena."""
    chapters = _chapters(10)
    vt = V.build_visual_timeline(chapters, _scenes(chapters), 0.9, seed="s",
                                 insertions=2, insert_style="drop_in",
                                 insert_gain_db=-30)
    for t in vt:
        for im in t["images"]:
            sfx = im.get("sfx")
            if im["order"] == 0:
                assert sfx is None
                continue
            assert sfx is not None, "inserção sem som"
            assert sfx["gain_db"] == -30
            assert sfx["at"] == pytest.approx(round(t["start"] + im["start"], 3))
            assert 0 <= sfx["at"] < t["end"]


def test_som_desligado_nao_quebra_a_timeline():
    chapters = _chapters(8)
    vt = V.build_visual_timeline(chapters, _scenes(chapters), 0.9, seed="s",
                                 insertions=2, sfx=False)
    assert len(_overlays(vt)) == 2
    assert all(im["sfx"] is None for im in _overlays(vt))


def test_cena_sem_segunda_foto_nao_inventa_insercao():
    """Cena com 1 foto só não recebe cartaz — nada de imagem fantasma."""
    chapters = _chapters(6)
    scenes = [{"chapter_id": c.id, "asset": _asset(0)["asset"],
               "assets": [{"asset": _asset(0)["asset"], "query": "a", "order": 0}],
               "reused_from": None} for c in chapters]
    vt = V.build_visual_timeline(chapters, scenes, 0.9, seed="s", insertions=2)
    assert _overlays(vt) == []


def test_cena_sem_midia_continua_fallback():
    chapters = _chapters(6)
    scenes = _scenes(chapters)
    scenes[3] = {"chapter_id": chapters[3].id, "asset": None, "assets": [],
                 "reused_from": None}
    vt = V.build_visual_timeline(chapters, scenes, 0.9, seed="s", insertions=2)
    assert vt[3]["fallback"] is True
    assert vt[3]["images"] == []


# --- retiming preserva a decisão --------------------------------------

def test_retime_preserva_estilo_e_som():
    chapters = _chapters(10)
    vt = V.build_visual_timeline(chapters, _scenes(chapters), 0.9, seed="s",
                                 insertions=2, insert_style="drop_in")
    slower = [Chapter(id=c.id, narration=c.narration,
                      duration_estimate=20.0, start=c.start * 2.5,
                      end=c.end * 2.5) for c in chapters]
    out = V.retime_visual_timeline(vt, slower)
    ins = _overlays(out)
    assert len(ins) == 2, "retime furou o orçamento"
    assert all(im["transition"] == "drop_in" for im in ins)
    for t in out:
        for im in t["images"]:
            if im["order"] > 0:
                assert im["sfx"]["at"] == pytest.approx(
                    round(t["start"] + im["start"], 3))


# --- modo álbum cheio continua disponível ------------------------------

def test_none_mantem_album_por_cena():
    """`insertions=None` = comportamento antigo: álbum cheio, SFX ~1/3."""
    chapters = _chapters(6)
    scenes = [{"chapter_id": c.id, "asset": _asset(0)["asset"],
               "assets": [{"asset": _asset(k)["asset"], "query": "a", "order": k}
                          for k in range(3)], "reused_from": None}
              for c in chapters]
    vt = V.build_visual_timeline(chapters, scenes, 0.9, seed="s", insertions=None)
    assert len(_overlays(vt)) == 12  # 2 por cena, sem teto
