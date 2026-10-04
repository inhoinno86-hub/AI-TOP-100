"""EntityIdentity / CanonicalMapping — lazy, evidence-bound (Design Freeze §9, v0.2.4 P28)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import MappingConfidence, MappingStatus
from ..core.provenance import Provenance


@dataclass
class Identifier:
    namespace: str
    value: str
    unique_in_namespace: bool | None = None  # None = not established


@dataclass
class EntityIdentity:
    id: str
    entity_type: str
    canonical_id: str | None = None
    organization_ids: list[str] = field(default_factory=list)
    identifiers: list[Identifier] = field(default_factory=list)
    mapping_ids: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    status: str = "PROVISIONAL"
    provenance: Provenance | None = None


@dataclass
class CanonicalMapping:
    """Source identifier(s) in one namespace → target identifier(s) in another.

    * composite keys allowed (``source_identifiers`` holds several fields)
    * textual equality alone never yields HIGH confidence
    * a non-unique source identifier is never auto-resolved
    * created only when identity resolution affects a decision/action
    """

    id: str
    entity_type: str
    source_namespace: str
    source_identifiers: dict[str, str]
    target_namespace: str
    target_identifiers: dict[str, str] = field(default_factory=dict)
    confidence: MappingConfidence = MappingConfidence.UNRESOLVED
    authority: str | None = None
    provenance: Provenance | None = None
    validity: str | None = None
    conflicts: list[str] = field(default_factory=list)
    status: MappingStatus = MappingStatus.PROPOSED
    basis: list[str] = field(default_factory=list)  # e.g. ["TEXTUAL_EQUALITY", "REGISTRY_LOOKUP"]

    def source_key(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self.source_identifiers.items()))

    def is_resolved(self) -> bool:
        return self.confidence is not MappingConfidence.UNRESOLVED and bool(self.target_identifiers)
