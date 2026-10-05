"""Contracts for scene-specific synthetic fallback and media scoring."""

import os
from dataclasses import replace

import pytest

from curio.config import CurioConfig
from curio.stages import scoring, visuals
from curio.stages.scene_projection import Chapter
from curio.stages.scene_contract import SemanticScene
from curio.stages.visual_contracts import VisualRepresentation
from curio.stages.visual_fallback_planning import (
    VisualDiversityState, build_visual_fallback_plan,
)
from curio.stages.visual_planning import build_visual_plan

PIL = pytest.importorskip("PIL")


def _fallback(*, scene_id=1, visual_type="literal", subject="scene subject",
              topic="global topic", visual_entities=(), visual_steps=(),
              representations=(), text_role="", period="", event="",
              intent="", narration="Scene narration is preserved."):
    scene = SemanticScene(
        id=scene_id, narration=narration, visual_type=visual_type,
        subject=subject, visual_entities=tuple(visual_entities),
        visual_steps=tuple(visual_steps),
        representations=tuple(VisualRepresentation.from_value(rep)
                              for rep in representations),
        text_role=text_role, period=period, event=event,
        visual_intent_structured=intent,
        video_context={"topic": topic},
    )
    return build_visual_fallback_plan(build_visual_plan(scene), narration)


def test_repeated_scene_uses_specific_approved_representation():
    plan = _fallback(subject="global topic", topic="global topic",
                     representations=[{"query": "Ottoman Janissaries",
                                       "kind": "army",
                                       "source": "scene_planner"}])
    assert plan.subject == "Ottoman Janissaries"
    assert plan.subject_source == "approved_representation"
    assert plan.strategy == "form"


def test_mechanism_diagram_requires_explicit_ordered_steps():
    no_steps = _fallback(visual_type="mechanism", visual_entities=("a", "b"))
    ordered = _fallback(visual_type="mechanism",
                        visual_steps=("antibody binds hCG", "line appears"))
    assert no_steps.strategy == "form" and no_steps.steps == ()
    assert ordered.strategy == "diagram"
    assert ordered.steps == ("antibody binds hCG", "line appears")


def test_person_date_form_uses_scene_contract():
    person = _fallback(visual_type="historical_art", subject="São Bento",
                       text_role="person", period="c. 480 — 547")
    empire = _fallback(visual_type="historical_art", subject="Roman Empire",
                       text_role="term", period="century V")
    assert person.form == "dated"
    assert empire.form != "dated"


def test_visual_variety_state_tracks_repetition_and_form_usage():
    state = VisualDiversityState()
    state.record("São Bento name origin question", "definition")
    assert state.subject_repeated("Lack of São Bento name origin information")
    assert state.least_used_form(("spotlight", "definition")) == "spotlight"


def test_fallback_plan_renderer_generates_reusable_asset(tmp_path):
    from curio.stages.visuals import render_fallback_plan
    plan = _fallback(visual_entities=("black hole event horizon",))
    first = render_fallback_plan(plan, str(tmp_path), genre="science")
    second = render_fallback_plan(plan, str(tmp_path), genre="science")
    assert first.provider == "synth"
    assert first.asset_id == second.asset_id
    assert os.path.getsize(first.local_path) > 10000


# --- pontuação: núcleo prova o assunto, apoio só desempata ------------

def _ch_score(subject, entities=(), queries=()):
    return Chapter(id=1, narration="n", duration_estimate=5.0,
                   visual_type="literal", subject=subject,
                   visual_entities=list(entities), context=[],
                   visual_queries=list(queries))


def test_titulo_de_acervo_nao_perde_a_primeira_palavra():
    """'File:Saint Francis' não pode virar 'file:saint' e não casar.

    Separar token só por espaço colava o prefixo do Wikimedia na
    primeira palavra — ou seja, todo título de acervo perdia um termo, e
    justamente nos provedores sem chave que guardam a arte pública.
    """
    ch = _ch_score("saint francis of assisi")
    nota = scoring.base_score(
        {"title": "File:Saint Francis of Assisi - Allori.jpg"}, ch)
    # cobertura total do núcleo = CORE_MAX (o bônus de apoio é que leva
    # até 100; aqui a cena não pediu apoio)
    assert nota["score"] == scoring.CORE_MAX
    assert nota["matched"] == ["saint", "francis", "assisi"]


def test_uma_palavra_do_assunto_nao_basta_para_entrar():
    """'thermal' contra o sujeito 'thermal receipt paper' não é o tema."""
    ch = _ch_score("thermal receipt paper",
                   entities=["thermal printer", "heat", "dye change"])
    nota = scoring.base_score({"title": "thermal power station at dusk"}, ch)
    assert nota["score"] < scoring.DEFAULT_THRESHOLD
    ok, _low = scoring.below_threshold([{"score": nota["score"]}])
    assert not ok, "a usina voltou a passar"


def test_bonus_de_apoio_nao_compra_imagem_errada():
    ch = _ch_score("thermal receipt paper",
                   entities=["thermal", "power", "station"])
    # casaria com apoio, mas o núcleo não prova nada
    nota = scoring.base_score({"title": "thermal power station"}, ch)
    assert nota["support"], "o título casa com as entidades"
    assert nota["score"] < scoring.DEFAULT_THRESHOLD


def test_entidade_presente_desempata_a_favor():
    """Duas imagens do mesmo assunto: vence a que tem o apoio pedido."""
    ch = _ch_score("saint francis of assisi", entities=["fresco", "monk"])
    sem = scoring.base_score({"title": "saint francis of assisi statue"}, ch)
    com = scoring.base_score(
        {"title": "saint francis of assisi fresco with monk"}, ch)
    assert com["score"] > sem["score"]
    assert "fresco" in com["support"]


def test_assunto_dominina_as_consultas():
    """Consultas são busca, não identidade: não podem diluir o sujeito."""
    ch = _ch_score("saint francis of assisi",
                   queries=["saint francis assisi", "franciscan friar"])
    nota = scoring.base_score(
        {"title": "File:Saint Francis in Ecstasy.jpg"}, ch)
    # 2 de 3 palavras do assunto: as consultas NÃO entraram no denominador,
    # então a nota é 2/3 do núcleo, bem acima do corte
    assert nota["score"] == pytest.approx(scoring.CORE_MAX * 2 / 3, abs=1)
    ok, _low = scoring.below_threshold([{"score": nota["score"]}])
    assert ok


def test_narracao_sem_plano_semantico_nao_vira_termos_de_scoring():
    ch = Chapter(id=1, narration="Rome preserved food with salt.",
                 duration_estimate=5.0, visual_type="literal")
    nota = scoring.base_score({"title": "Rome preserved food with salt"}, ch)
    assert nota["score"] == 0


def test_representacao_materializada_forma_nucleo_de_scoring():
    ch = Chapter(id=1, narration="Rome preserved food with salt.",
                 duration_estimate=5.0, visual_type="literal",
                 representations=[{"query": "Roman food preservation",
                                   "kind": "artifact"}])
    nota = scoring.base_score({"title": "Roman food preservation with salt"}, ch)
    assert nota["score"] > 0


def test_arte_historica_passa_e_foto_moderna_nao():
    """Critério de aceite 2: a arte entra, a foto de banco não."""
    ch = _ch_score("saint francis of assisi", entities=["fresco", "monk"])
    arte = scoring.base_score(
        {"title": "File:Saint Francis in Ecstasy - Zurbaran.jpg"}, ch)
    foto = scoring.base_score(
        {"title": "File:Assisi Basilica - modern tourist photo"}, ch)
    assert arte["score"] > foto["score"]
    ok_arte, _ = scoring.below_threshold([{"score": arte["score"]}])
    ok_foto, _ = scoring.below_threshold([{"score": foto["score"]}])
    assert ok_arte and not ok_foto


# --- a concatenação precisa produzir UMA série de codec ---------------
# O sintoma era: vídeo falhava em ~14,9 s (fronteira do 2º segmento) com
# "Error reinitializing filters!" e -38, deixando um final.mp4 truncado
# como se tivesse funcionado. Causa: -c copy do demuxer concat justapõe
# N séries de codec, e o segundo encode precisa reiniciar o filtergraph ao
# atravessar cada fronteira — o que o hwupload do VA-API não implementa.

def _segmentos(tmp_path, n=3):
    from PIL import Image
    import subprocess
    segs = []
    for i in range(n):
        p = str(tmp_path / f"seg{i}.mp4")
        src = str(tmp_path / f"img{i}.png")
        Image.new("RGB", (480, 854), (40 + i * 30, 90, 140)).save(src)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1",
                        "-framerate", "24", "-t", "2", "-i", src,
                        "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", p], check=True)
        segs.append(p)
    return segs


def _n_series(path):
    """Conta trocas de série observing os keyframes do stream."""
    import subprocess
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout
    return sum(1 for ln in out.splitlines() if ",K" in ln or ln.endswith("K"))


def test_concat_copy_normaliza_quando_o_encode_final_e_vaapi(tmp_path):
    from curio.stages import render as R
    cfg = CurioConfig(render_backend="vaapi")
    out = str(tmp_path / "silent.mp4")
    R.concat_copy(_segmentos(tmp_path), out, cfg)
    assert os.path.isfile(out)
    assert _n_series(out) <= 1, "o concat precisa sair com série única"


def test_concat_copy_nao_paga_passe_extra_no_caminho_software(tmp_path):
    from curio.stages import render as R
    cfg = CurioConfig(render_backend="cpu")
    out = str(tmp_path / "silent.mp4")
    R.concat_copy(_segmentos(tmp_path), out, cfg)
    assert os.path.isfile(out)
    assert not os.path.exists(out + ".norm.mp4"), "normalizou sem precisar"


def test_concat_copy_sem_cfg_comporta_se_como_antes(tmp_path):
    from curio.stages import render as R
    out = str(tmp_path / "silent.mp4")
    R.concat_copy(_segmentos(tmp_path), out)
    assert os.path.isfile(out) and os.path.getsize(out) > 1000


def test_needs_single_sequence_depende_do_encoder(tmp_path):
    from curio.stages import render as R
    assert R._needs_single_sequence(CurioConfig(render_backend="vaapi"))
    assert R._needs_single_sequence(CurioConfig(render_backend="arc"))
    assert not R._needs_single_sequence(CurioConfig(render_backend="cpu"))


# --- low-level form rendering (policy is tested above as a contract) ---


def _ch2(vtype="conceptual", subject="assunto", entities=(), narration="Uma frase de narração com pelo menos quatro palavras para o rodapé.", context=()):
    return Chapter(id=1, narration=narration, duration_estimate=6.0,
                   visual_type=vtype, subject=subject,
                   visual_entities=list(entities), context=list(context),
                   visual_queries=[])


def test_cada_forma_e_visualmente_diferente(tmp_path):
    vistos = set()
    for forma in visuals.FORMS:
        plan = _fallback(text_role="quote")
        plan = replace(plan, strategy="form", form=forma,
                       contrast_sides=("A", "B") if forma == "contrast" else (),
                       quote_text="A quoted phrase for this visual." if forma == "quote" else "")
        asset = visuals.render_form(plan, str(tmp_path), "pt-BR")
        assert asset is not None and os.path.getsize(asset.local_path) > 10000
        vistos.add(asset.local_path)
    assert len(vistos) == len(visuals.FORMS)


def test_todas_as_formas_aceitam_cena_vazia(tmp_path):
    for forma in visuals.FORMS:
        plan = _fallback(subject="", visual_entities=(), text_role="quote",
                         narration="A quote which can be displayed here.")
        plan = replace(plan, strategy="form", form=forma,
                       contrast_sides=("A", "B") if forma == "contrast" else (),
                       quote_text="A quote which can be displayed here." if forma == "quote" else "")
        asset = visuals.render_form(plan, str(tmp_path), "pt-BR")
        assert asset is not None
        from PIL import Image
        with Image.open(asset.local_path) as image:
            assert image.size == (visuals.W, visuals.H)
            assert image.format == "PNG"


def test_dated_renderer_receives_declared_person_and_period(tmp_path):
    from curio.stages.typography import for_genre
    scene = _fallback(subject="São Bento de Núrsia", visual_type="historical_art",
                      text_role="person", period="c. 480 — 547")
    asset = visuals.render_form(scene, str(tmp_path),
                                "pt-BR", for_genre("people"))
    assert asset is not None and os.path.getsize(asset.local_path) > 10000
