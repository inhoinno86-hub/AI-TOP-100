"""CanonicalMapping construction rules (Design Freeze §9, v0.2.4 P28).

* textual equality ≠ canonical identity → textual-only basis is capped below HIGH
* non-unique source identifiers are never auto-resolved → UNRESOLVED + IDENTITY_CONFLICT
* authority / provenance are preserved on every mapping
"""

from __future__ import annotations

from ..core.enums import (
    ConflictType,
    Criticality,
    EvidenceSourceType,
    MappingConfidence,
    MappingStatus,
)
from ..core.events import EventType
from ..core.provenance import Provenance
from ..domain.epistemic import Conflict
from ..domain.identity import CanonicalMapping
from ..engine.context import HarnessContext

TEXTUAL_EQUALITY = "TEXTUAL_EQUALITY"
_CONFIDENCE_ORDER = [
    MappingConfidence.UNRESOLVED,
    MappingConfidence.LOW,
    MappingConfidence.MEDIUM,
    MappingConfidence.HIGH,
]


def propose_mapping(
    ctx: HarnessContext,
    mapping_id: str,
    *,
    entity_type: str,
    source_namespace: str,
    source_identifiers: dict[str, str],
    target_namespace: str,
    candidate_targets: list[dict[str, str]],
    basis: list[str],
    claimed_confidence: MappingConfidence,
    authority: str | None,
    derived_from: list[str],
) -> CanonicalMapping:
    """Create a mapping, applying the frozen identity rules before anything is committed."""
    confidence = claimed_confidence
    status = MappingStatus.PROPOSED
    targets: dict[str, str] = {}
    conflict_needed = False
    if len(candidate_targets) != 1:
        # non-unique source identifier (or no target) — never auto-resolve
        confidence, status, conflict_needed = MappingConfidence.UNRESOLVED, MappingStatus.UNRESOLVED, True
    else:
        targets = dict(candidate_targets[0])
        if set(basis) <= {TEXTUAL_EQUALITY} and _rank(confidence) > _rank(MappingConfidence.MEDIUM):
            confidence = MappingConfidence.MEDIUM
        if authority is None and confidence is MappingConfidence.HIGH:
            confidence = MappingConfidence.MEDIUM  # HIGH needs an authority (owner/registry/contract)
    mapping = CanonicalMapping(
        id=mapping_id,
        entity_type=entity_type,
        source_namespace=source_namespace,
        source_identifiers=dict(source_identifiers),
        target_namespace=target_namespace,
        target_identifiers=targets,
        confidence=confidence,
        authority=authority,
        provenance=Provenance(
            EvidenceSourceType.DATA,
            derived_from[0] if derived_from else "unknown",
            method="+".join(basis),
            derived_from=list(derived_from),
        ),
        status=status,
        basis=list(basis),
    )
    with ctx.commit(f"mapping {mapping_id}") as ps:
        ps.canonical_mappings[mapping_id] = mapping
        if conflict_needed:
            cid = ps.next_id("C", "conflicts")
            ps.conflicts[cid] = Conflict(
                id=cid,
                type=ConflictType.IDENTITY_CONFLICT,
                side_a=f"{source_namespace}:{source_identifiers}",
                side_b=f"{len(candidate_targets)} candidate targets in {target_namespace}",
                decision_impact=Criticality.HIGH,
                evidence_refs=[d for d in derived_from if d in ps.evidence],
            )
            mapping.conflicts.append(cid)
    if conflict_needed:
        ctx.emit(
            EventType.CONFLICT_DETECTED, {"mapping": mapping_id, "reason": "non-unique source identifier"}
        )
    return mapping


def _rank(c: MappingConfidence) -> int:
    return _CONFIDENCE_ORDER.index(c)
