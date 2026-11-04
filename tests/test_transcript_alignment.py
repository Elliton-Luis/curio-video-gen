import pytest

from curio.stages.transcribe import align_to_script, TranscribeError


def test_script_corrections_keep_audio_timing_and_estimate_only_missing_word():
    words = [{"text": "Agustín", "start": 0.0, "end": .4},
             {"text": "olha", "start": .4, "end": .7},
             {"text": "para", "start": .7, "end": 1.0},
             {"text": "frente", "start": 1.0, "end": 1.4}]
    tail = "e pensa sobre tempo e memória."
    words.extend({"text": token, "start": 1.4 + index, "end": 2.4 + index}
                 for index, token in enumerate(tail.split()))
    text = "Agostinho olha para a frente, " + tail
    aligned = align_to_script(text, words)
    assert [word["text"] for word in aligned] == text.split()
    assert aligned[0] == {**words[0], "text": "Agostinho"}
    assert aligned[1] == words[1]
    assert aligned[4] == {**words[3], "text": "frente,"}
    assert .7 < aligned[2]["end"] == aligned[3]["start"] < 1.0
    assert aligned[3]["end"] == 1.0
    assert words[2]["end"] == 1.0


def test_unrelated_audio_is_rejected():
    with pytest.raises(TranscribeError, match="diverge"):
        align_to_script("Texto diferente.", [{"text": "Olá", "start": 0, "end": 1}])
