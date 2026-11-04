import pytest

from curio.stages import subs


def timed_words(tokens):
    return [{"text": token, "start": index * 0.3, "end": index * 0.3 + 0.2}
            for index, token in enumerate(tokens)]


@pytest.mark.parametrize("ending", [".", "?", "!", "…", ",", ";", ":", '.”'])
@pytest.mark.parametrize("active", [False, True])
def test_short_boundary_never_contains_next_phrase(ending, active):
    words = timed_words(["encontraram" + ending, "Num", "belo", "dia"])
    cues = subs.cues_from_words(words, upper=False, highlight="word",
                                active_word=active)
    plain = [subs._strip_ass_tags(cue) for _, _, cue in cues]
    assert plain[0] == "encontraram" + ending
    assert cues[0][0] == words[0]["start"]
    assert cues[0][1] <= words[1]["start"]
    assert cues[1][0] == words[1]["start"]
    assert all(end <= following[0] for (_, end, _), following in zip(cues, cues[1:]))
    if active:
        assert [(start, end) for start, end, _ in cues
                if end - start > 0.15] == [(w["start"], w["end"]) for w in words]


def test_restore_punctuation_preserves_all_timestamps_and_input():
    words = timed_words(["e", "o", "encontraram", "Num", "belo", "dia"])
    restored = subs._restore_word_punctuation("e o encontraram. Num belo dia,", words)
    assert [w["text"] for w in restored] == ["e", "o", "encontraram.", "Num", "belo", "dia,"]
    assert [(w["start"], w["end"]) for w in restored] == [(w["start"], w["end"]) for w in words]
    assert words[2]["text"] == "encontraram"
    assert subs._restore_word_punctuation("Outra frase.", words) is words
    assert subs._restore_word_punctuation("e o perderam. Num belo dia,", words) is words


def test_write_subtitles_restores_same_boundaries_in_srt_and_ass(tmp_path):
    words = timed_words(["encontraram", "Num", "belo", "dia"])
    srt, ass = tmp_path / "subs.srt", tmp_path / "subs.ass"
    subs.write_subtitles("encontraram. Num belo dia.", 1.1, str(srt), str(ass),
                         1080, 1920, 64, 422, words=words,
                         fontname="Archivo Black", bold=0, upper=False)
    assert "encontraram.\n" in srt.read_text()
    assert "Num belo dia." in srt.read_text()
    dialogues = [line for line in ass.read_text().splitlines() if line.startswith("Dialogue:")]
    assert subs._strip_ass_tags(dialogues[0].split(",", 9)[9]) == "encontraram."
    assert dialogues[0].startswith("Dialogue: 0,0:00:00.00,0:00:00.20,")
    assert dialogues[1].startswith("Dialogue: 0,0:00:00.30,0:00:00.50,")
    assert "Style: Default,Archivo Black,64," in ass.read_text()
