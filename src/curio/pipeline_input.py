"""Validated semantic and editorial input accepted by the pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PipelineInput:
    """Separate the subject used for research from optional presentation data."""

    topic: str
    script: str | None = None
    display_title: str | None = None

    def __post_init__(self) -> None:
        topic = str(self.topic or "").strip()
        if not topic:
            raise ValueError("pipeline topic is required")
        object.__setattr__(self, "topic", topic)

        if self.script is not None:
            script = str(self.script)
            if not script.strip():
                raise ValueError("provided script cannot be empty")
            object.__setattr__(self, "script", script)

        if self.display_title is not None:
            title = str(self.display_title).strip()
            if not title:
                raise ValueError("display title cannot be empty")
            object.__setattr__(self, "display_title", title)
