"""Provenance (Design Freeze §5, v0.2.1 P7 Provenance-first)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import EvidenceSourceType


@dataclass
class Provenance:
    """Where a piece of knowledge came from.

    ``derived_from`` holds ids of upstream objects (evidence, data assets, mappings, events)
    so Raw Data → Transformation → Evidence → Problem Definition stays traceable.
    """

    source_type: EvidenceSourceType
    source_id: str
    method: str = ""
    derived_from: list[str] = field(default_factory=list)
    event_seq: int | None = None
    recorded_at_minute: float | None = None
