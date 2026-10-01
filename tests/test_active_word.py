from curio.stages import subs, nvidia


def test_exact_highlight_uses_boundaries_not_uniform_duration():
    words = [{"text": text, "start": start, "end": end} for text, start, end in
             [("O", .09, .14), ("império", .2, .65), ("romano", .7, 1.2),
              ("caiu.", 1.3, 1.55), ("Em", 2., 2.1), ("476!", 2.2, 2.8)]]
    cues = subs.cues_from_words(words, active_word=True, upper=False)
    active = [cue for cue in cues if "\\c" in cue[2]]
    assert [(s, e) for s, e, _ in active] == [(w["start"], w["end"]) for w in words]
    for cue, word in zip(active, words):
        assert "}" + word["text"] + r"{\r}" in cue[2]
    assert all("\\c" not in text for start, end, text in cues if start == .14)


def test_generation_prompt_recovers_topic_related_cta_without_weak_preamble():
    assert "opinião ou experiência" in nvidia.SCRIPT_SYSTEM_PROMPT
    assert "sem preâmbulos" in nvidia.SCRIPT_SYSTEM_PROMPT
    assert "fontes" in nvidia.SCRIPT_SYSTEM_PROMPT.lower()


def test_generation_preserves_sources_and_genre_in_actual_request(monkeypatch):
    captured = []
    monkeypatch.setattr(nvidia, "any_llm_available", lambda: True)
    def chat(messages, *args, **kwargs):
        captured.extend(messages)
        return {"choices": [{"finish_reason": "stop", "message": {
            "content": "Texto falado fundamentado. " * 8}}]}, "groq:test"
    monkeypatch.setattr(nvidia, "_chat", chat)
    nvidia.generate_script("Ideia", "test", "https://test", 5, None,
                           research="FONTE REAL", genre_directive="GENERO HISTORIA")
    assert "GENERO HISTORIA" in captured[0]["content"]
    assert "FONTE REAL" in captured[1]["content"]
    assert "convite breve a comentar" in captured[0]["content"]
