import pytest

from curio.config import CurioConfig
from curio.stages import script


@pytest.mark.parametrize("title", ["O agora já virou passado!", "Onde foi parar o agora?"])
def test_title_is_first_spoken_sentence_without_another_llm_request(title, monkeypatch):
    monkeypatch.setattr(script.nvidia_stage, "complete_json",
                        lambda *args, **kwargs: pytest.fail("title already exists in narration"))
    narration = title + " Enquanto você pensa nele, já virou lembrança."
    result = script.generate_title(narration, "Santo Agostinho", CurioConfig())
    assert result.text == title


def test_different_display_title_is_rejected():
    with pytest.raises(ValueError, match="primeira frase"):
        script._validate_title("Onde está o tempo?", "Tente segurar este instante. Depois pense nele.")


def test_long_opening_requires_editorial_revision():
    with pytest.raises(ValueError, match="curto"):
        script.generate_title("Uma abertura com tantas palavras que não cabe nos primeiros três segundos.",
                              "Tema", CurioConfig())
