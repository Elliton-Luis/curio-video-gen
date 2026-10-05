from PIL import ImageDraw

from curio.stages.scene_contract import SemanticScene
from curio.stages.visuals import render_card


def test_science_fallback_card_does_not_turn_search_entities_into_a_chain(
        monkeypatch, tmp_path):
    original_draw = ImageDraw.Draw
    visible_text = []
    boxes = []

    class RecordingDraw:
        def __init__(self, image):
            self.draw = original_draw(image)

        def text(self, xy, text, **kwargs):
            visible_text.append(str(text))
            boxes.append(self.draw.textbbox(
                xy, str(text), font=kwargs.get("font"),
                anchor=kwargs.get("anchor")))
            return self.draw.text(xy, text, **kwargs)

        def __getattr__(self, name):
            return getattr(self.draw, name)

    monkeypatch.setattr(ImageDraw, "Draw", RecordingDraw)
    scene = SemanticScene(
        id=2,
        narration=("O Telescópio Event Horizon, usando redes de radio telescópios, "
                   "capturou a primeira imagem de Sagitário A e de Messier, "
                   "encerrando uma observação direta sem precedentes."),
        visual_type="literal",
        subject="Event Horizon Telescope",
        visual_entities=("Event Horizon Telescope logo", "radio telescope array",
                         "Sagittarius A* image"),
    )
    asset = render_card(scene.subject, [], scene.narration,
                        str(tmp_path), scene_id=scene.id)

    assert asset is not None
    assert len(visible_text) <= 5  # kicker, wrapped title, and at most two footer lines
    assert not any("radio telescope array" in text for text in visible_text)
    assert visible_text[-1].endswith("…")
    for index, first in enumerate(boxes):
        for second in boxes[index + 1:]:
            assert not (first[0] < second[2] and second[0] < first[2]
                        and first[1] < second[3] and second[1] < first[3])


def test_typographic_chain_and_narration_have_separate_vertical_regions(
        monkeypatch, tmp_path):
    original_draw = ImageDraw.Draw
    boxes = []

    class RecordingDraw:
        def __init__(self, image):
            self.draw = original_draw(image)

        def text(self, xy, text, **kwargs):
            boxes.append(self.draw.textbbox(
                xy, str(text), font=kwargs.get("font"),
                anchor=kwargs.get("anchor")))
            return self.draw.text(xy, text, **kwargs)

        def __getattr__(self, name):
            return getattr(self.draw, name)

    monkeypatch.setattr(ImageDraw, "Draw", RecordingDraw)
    scene = SemanticScene(
        id=1, narration="A palavra salário vem do latim e descreve uma origem antiga.",
        visual_type="typographic", subject="salarium",
        visual_entities=("sal", "romano", "uso antigo"))
    asset = render_card(scene.subject, ["sal", "romano", "uso antigo"],
                        scene.narration, str(tmp_path), scene_id=scene.id,
                        word_card=True)

    assert asset is not None
    for index, first in enumerate(boxes):
        for second in boxes[index + 1:]:
            assert not (first[0] < second[2] and second[0] < first[2]
                        and first[1] < second[3] and second[1] < first[3])
