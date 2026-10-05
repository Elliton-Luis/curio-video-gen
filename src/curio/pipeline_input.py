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
        if not isinstance(self.topic, str):
            raise TypeError("pipeline topic must be text")
        topic = self.topic.strip()
        if not topic:
            raise ValueError("pipeline topic is required")
        object.__setattr__(self, "topic", topic)

        if self.script is not None:
            if not isinstance(self.script, str):
                raise TypeError("provided script must be text")
            if not self.script.strip():
                raise ValueError("provided script cannot be empty")

        if self.display_title is not None:
            if not isinstance(self.display_title, str):
                raise TypeError("display title must be text")
            title = self.display_title.strip()
            if not title:
                raise ValueError("display title cannot be empty")
            object.__setattr__(self, "display_title", title)
