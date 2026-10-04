"""State Diff (Design Freeze §27): NEW / CHANGED / RESOLVED / DEFERRED / DROPPED_FOR_BUDGET.

A fingerprint stores only ``(content hash, status)`` per item, so computing a diff never
duplicates the full state.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..core.enums import DiffKind, Importance
from ..core.serialization import to_json
from ..state.problem import TRACKED_COLLECTIONS, ProblemState
from ..state.supervision import StateDiff, StateDiffEntry

RESOLVED_STATUSES = frozenset({"RESOLVED", "CONFIRMED", "VALIDATED", "VERIFIED", "MANAGED"})
DEFERRED_STATUSES = frozenset({"DEFERRED"})

# Collections whose changes matter most for a human (importance defaults; refined by monitoring).
COLLECTION_IMPORTANCE = {
    "verification_obligations": Importance.HIGH,
    "conflicts": Importance.HIGH,
    "constraints": Importance.HIGH,
    "domain_authorizations": Importance.HIGH,
    "evidence_revisions": Importance.HIGH,
    "unknowns": Importance.NORMAL,
    "hypotheses": Importance.NORMAL,
    "canonical_mappings": Importance.NORMAL,
    "process_handoffs": Importance.NORMAL,
}


@dataclass(frozen=True)
class ItemPrint:
    digest: str
    status: str | None


Fingerprint = dict[str, dict[str, ItemPrint]]


def _status_of(item: object) -> str | None:
    status = getattr(item, "status", None)
    if status is None:
        return None
    return str(getattr(status, "value", status))


def fingerprint(state: ProblemState) -> Fingerprint:
    fp: Fingerprint = {}
    for name in TRACKED_COLLECTIONS:
        coll = getattr(state, name)
        fp[name] = {
            item_id: ItemPrint(hashlib.sha1(to_json(item).encode()).hexdigest(), _status_of(item))
            for item_id, item in coll.items()
        }
    return fp


def _importance(collection: str, item: object, kind: DiffKind) -> Importance:
    base = COLLECTION_IMPORTANCE.get(collection, Importance.LOW)
    crit = getattr(item, "criticality", None) or getattr(item, "decision_impact", None)
    if str(getattr(crit, "value", crit)) == "CRITICAL":
        return Importance.CRITICAL
    if kind is DiffKind.DEFERRED and base is not Importance.LOW:
        return Importance.HIGH
    return base


def compute_diff(
    before: Fingerprint,
    state: ProblemState,
    *,
    from_version: int,
    to_version: int,
    reason: str,
    dropped_for_budget: list[str] | None = None,
) -> StateDiff:
    after = fingerprint(state)
    diff = StateDiff(from_version=from_version, to_version=to_version, reason=reason)
    for name in TRACKED_COLLECTIONS:
        old, new, coll = before.get(name, {}), after[name], getattr(state, name)
        for item_id, p in new.items():
            item = coll[item_id]
            if item_id not in old:
                diff.entries.append(
                    StateDiffEntry(
                        DiffKind.NEW,
                        name,
                        item_id,
                        f"new {name} {item_id}",
                        _importance(name, item, DiffKind.NEW),
                        None,
                        p.status,
                    )
                )
                continue
            o = old[item_id]
            if o.digest == p.digest:
                continue
            kind = DiffKind.CHANGED
            if p.status != o.status:
                if p.status in RESOLVED_STATUSES:
                    kind = DiffKind.RESOLVED
                elif p.status in DEFERRED_STATUSES:
                    kind = DiffKind.DEFERRED
            diff.entries.append(
                StateDiffEntry(
                    kind,
                    name,
                    item_id,
                    f"{kind.value.lower()} {name} {item_id}",
                    _importance(name, item, kind),
                    o.status,
                    p.status,
                )
            )
    for work_id in dropped_for_budget or []:
        diff.entries.append(
            StateDiffEntry(
                DiffKind.DROPPED_FOR_BUDGET,
                "work_items",
                work_id,
                f"dropped for budget: {work_id}",
                Importance.NORMAL,
            )
        )
    return diff
