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
    """Cenas com assunto declarado: a inserção só entra se for mais
    precisa que o fundo, e a precisão é medida contra este vocabulário."""
    out = []
    for i in range(n):
        ch = Chapter(id=i + 1, narration=f"cena {i + 1}",
                     duration_estimate=dur, start=i * dur, end=(i + 1) * dur)
        ch.visual_queries = ["thermal paper receipt"]
        out.append(ch)
    return out


def _asset(i: int, title: str = "") -> dict:
    return {"asset": {"asset_id": f"a{i}", "title": title or f"foto {i}",
                      "provider": "pixabay", "author": "", "license": "Pixabay",
                      "source_url": "u", "local_path": f"/tmp/f{i}.jpg",
                      "kind": "image"}}


def _scenes(chapters) -> list[dict]:
    """Cada cena com 2 candidatos: fundo genérico + complementar preciso.

    O fundo é genérico de propósito (não casa com o assunto) e a
    complementar é a que fala do tema — é ela que tem de virar inserção.
    """
    return [{"chapter_id": c.id,
             "asset": _asset(0, "soft blurred background")["asset"],
             "assets": [{"asset": _asset(0, "soft blurred background")["asset"],
                         "query": "a", "order": 0},
                        {"asset": _asset(1, "thermal paper receipt roll")["asset"],
                         "query": "b", "order": 1}],
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
                                 insert_gain_db=-15)
    for t in vt:
        for im in t["images"]:
            sfx = im.get("sfx")
            if im["order"] == 0:
                assert sfx is None
                continue
            assert sfx is not None, "inserção sem som"
            assert sfx["gain_db"] == -15
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
    scenes = [{"chapter_id": c.id,
               "asset": _asset(0, "thermal paper receipt")["asset"],
               "assets": [{"asset": _asset(0, "thermal paper receipt")["asset"],
                           "query": "a", "order": 0}],
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
    scenes = [{"chapter_id": c.id,
               "asset": _asset(0, "background")["asset"],
               "assets": [{"asset": _asset(0, "background")["asset"],
                           "query": "a", "order": 0},
                          {"asset": _asset(1, "thermal paper receipt")["asset"],
                           "query": "b", "order": 1},
                          {"asset": _asset(2, "thermal paper receipt roll")["asset"],
                           "query": "c", "order": 2}],
               "reused_from": None} for c in chapters]
    vt = V.build_visual_timeline(chapters, scenes, 0.9, seed="s", insertions=None)
    assert len(_overlays(vt)) == 12  # 2 por cena, sem teto


# --- a inserção tem de ser a MAIS PRECISA sobre o assunto -------------

def _entry(i, title):
    return {"asset": dict(_asset(i)["asset"], title=title),
            "query": title, "order": 0}


def _ch(*queries, narration="cena"):
    return Chapter(id=1, narration=narration, duration_estimate=8.0,
                   visual_queries=list(queries), start=0.0, end=8.0)


def test_insercao_vence_o_fundo_em_precisao():
    """A genérica fica de fundo; a específica vira inserção."""
    ch = _ch("thermal paper receipt")
    entries = [_entry(0, "power plant cooling towers"),
               _entry(1, "thermal paper receipt roll")]
    bg, ins = V.order_for_insertion(entries, ch)
    assert bg[0]["asset"]["title"] == "power plant cooling towers"
    assert ins[0]["asset"]["title"] == "thermal paper receipt roll"


def test_ordem_da_busca_nao_decide_o_papel_da_foto():
    """A genérica veio primeiro da busca e mesmo assim não é a inserção."""
    ch = _ch("thermal paper receipt printer")
    entries = [_entry(0, "steam and smoke background"),
               _entry(1, "thermal paper receipt printer")]
    bg, ins = V.order_for_insertion(entries, ch)
    assert ins[0]["asset"]["title"] == "thermal paper receipt printer"
    assert bg[0]["asset"]["title"] == "steam and smoke background"


def test_nada_mais_preciso_que_o_fundo_nao_insere():
    """Empate = repetição, não aprofundamento: a cena fica só com o fundo."""
    ch = _ch("thermal paper receipt")
    entries = [_entry(0, "thermal paper receipt roll"),
               _entry(1, "thermal paper receipt sheet")]
    bg, ins = V.order_for_insertion(entries, ch)
    assert len(ins) == 0
    assert len(bg) == 1


def test_nada_relevante_alguma_nao_insere():
    ch = _ch("thermal paper receipt")
    entries = [_entry(0, "starry night sky"),
               _entry(1, "day of the dead woman")]
    bg, ins = V.order_for_insertion(entries, ch)
    assert ins == [] and len(bg) == 1


def test_uma_imagem_so_nunca_insere():
    ch = _ch("thermal paper receipt")
    assert V.order_for_insertion([_entry(0, "thermal paper")], ch)[1] == []


def test_sem_termos_de_assunto_nao_insere():
    ch = Chapter(id=1, narration="", duration_estimate=8.0,
                 visual_queries=[], start=0.0, end=8.0)
    entries = [_entry(0, "a"), _entry(1, "b")]
    assert V.order_for_insertion(entries, ch)[1] == []


def test_tres_candidatos_escolhe_o_melhor_dos_tres():
    ch = _ch("thermal paper receipt roll")
    entries = [_entry(0, "power plant"), _entry(1, "generic paper"),
               _entry(2, "thermal paper receipt roll closeup")]
    bg, ins = V.order_for_insertion(entries, ch)
    assert ins[0]["asset"]["title"] == "thermal paper receipt roll closeup"
    assert bg[0]["asset"]["title"] == "generic paper"


def test_timeline_marca_a_cena_que_ficou_sem_insercao():
    chapters = [Chapter(id=i + 1, narration="x", duration_estimate=8.0,
                        start=i * 8.0, end=(i + 1) * 8.0)
                for i in range(6)]
    scenes = []
    for c in chapters:
        c.visual_queries = ["thermal paper receipt"]
        if c.id == 3:  # esta cena não tem nada mais preciso
            scenes.append({"chapter_id": c.id,
                           "assets": [_entry(0, "thermal paper receipt"),
                                      _entry(1, "thermal paper receipt roll")],
                           "reused_from": None})
        else:
            scenes.append({"chapter_id": c.id,
                           "assets": [_entry(0, "steam smoke"),
                                      _entry(1, "thermal paper receipt roll")],
                           "reused_from": None})
    vt = V.build_visual_timeline(chapters, scenes, 0.9, seed="s", insertions=2)
    por_cena = {t["chapter_id"]: t for t in vt}
    assert "no_insertion" in por_cena[3], "cena sem inserção não foi sinalizada"
    assert all("no_insertion" not in por_cena[i] for i in (2, 4))


def test_titulo_vazio_nunca_vira_insercao():
    """Sem título não há descrição: não dá para provar precisão, então a
    foto sem título fica de fundo (ou fora) e nunca é promovida."""
    ch = _ch("thermal paper receipt")
    entries = [_entry(0, "thermal paper receipt"), _entry(1, "")]
    bg, ins = V.order_for_insertion(entries, ch)
    assert ins[0]["asset"]["title"] == "thermal paper receipt"
    assert bg[0]["asset"]["title"] == ""

    # o inverso: se a única descrita é a genérica, nada é promovido
    entries = [_entry(0, ""), _entry(1, "power plant cooling tower")]
    bg, ins = V.order_for_insertion(entries, ch)
    assert ins == []
