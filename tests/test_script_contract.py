import pytest

from curio.config import CurioConfig
from curio.stages import script


def test_local_script_and_title_share_typed_artifact_contract(monkeypatch):
    monkeypatch.setattr(script.nvidia_stage, "any_llm_available", lambda: False)
    cfg = CurioConfig(language="en-US")
    generated = script.generate_script("Why is the sky red at sunset?", cfg)
    title = script.generate_title(generated.text, "Why is the sky red at sunset?", cfg)

    assert isinstance(generated, script.ScriptArtifact)
    assert generated.text.strip()
    assert generated.source == "template"
    assert isinstance(title, script.TitleArtifact)
    assert title.text.strip()
    assert title.source == "fallback"


@pytest.mark.parametrize("factory", [script.ScriptArtifact, script.TitleArtifact])
def test_text_artifacts_reject_empty_payload_or_provenance(factory):
    with pytest.raises(ValueError, match="text must be non-empty"):
        factory("  ", "template")
    with pytest.raises(ValueError, match="source is required"):
        factory("valid", "")
