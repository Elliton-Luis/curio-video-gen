"""Editorial ordering policy for configured media providers."""

from __future__ import annotations

from ..config import CurioConfig
from ..media import get_providers
from ..media.providers import MediaProvider
from . import editorial
from .visual_contracts import VisualPlan

PROVIDER_PRIORITY = ("pixabay", "pexels", "nasa", "wikimedia",
                     "openverse", "met", "aic", "unsplash")


def ordered_providers(
    cfg: CurioConfig,
    plan: VisualPlan,
    genre: str = "",
    providers: list[MediaProvider] | None = None,
) -> list[MediaProvider]:
    """Order available adapters for a prepared plan; never query or score."""
    available = list(providers) if providers is not None else get_providers(cfg)
    order = list(PROVIDER_PRIORITY)
    adapter = editorial.get(genre or getattr(cfg, "genre", ""))
    adapter_priority = list(adapter.media_provider_priority) if adapter else []

    if plan.historical_scene:
        museum_priority = ["met", "aic", "wikimedia", "openverse"]
        order = museum_priority + [name for name in order
                                   if name not in museum_priority]
    if plan.space_topic or plan.visual_type == "mechanism":
        order = ["nasa", "wikimedia", "openverse", "pixabay", "pexels",
                 "met", "aic", "unsplash"]
    if adapter_priority:
        preferred = [name for name in adapter_priority if name in order]
        order = preferred + [name for name in order if name not in preferred]

    ranks = {name: rank for rank, name in enumerate(order)}
    return sorted(available, key=lambda provider: ranks.get(provider.name, 999))
