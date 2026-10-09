"""Authorization scope contract (IDR-RV5-01): syntax normalization, separate from authorization semantics.

An authorization candidate names the scope a document grants through a typed ``scope_kind``:

    RESOURCE         the grant covers the action on the candidate's ``resource``
    INTENDED_TARGET  the grant covers the action on one target id (``scope_target``)
    ANY_TARGET       the grant covers the action on every target (``*``)

``normalize_scope_target`` only turns equivalent *spellings* into the canonical target: the ScopeItem string
form ``action:target`` (the ``action`` prefix is the candidate's own action), ``resource/action`` mixtures,
surrounding quotes and case variants of a known id. It never chooses a broader or different target than the
one written, never maps free text to an id, and never decides whether the grant is valid — the existing
Core authorization rules (document grounding, holder, constraint actor, accepted targets) still do that.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..core.scope import WILDCARD
from ..reasoning.schemas import SCOPE_KINDS

_SEP = re.compile(r"\s*[:/@|]\s*")
_QUOTES = "\"'`[]()<> "


@dataclass
class NormalizedScope:
    target: str | None  # canonical target (WILDCARD for ANY_TARGET); None = no target could be read
    kind: str  # the typed kind used ("" = legacy free scope_target)
    notes: list[str] = field(default_factory=list)  # syntax adjustments (recorded, never semantic)
    refusal: str | None = None  # why no canonical target could be read


def normalize_scope_target(
    action: str,
    resource: str,
    scope_kind: str,
    scope_target: str,
    *,
    known_ids: Iterable[str] = (),
) -> NormalizedScope:
    kind = (scope_kind or "").strip().upper()
    raw = (scope_target or "").strip().strip(_QUOTES)
    if kind and kind not in SCOPE_KINDS:
        return NormalizedScope(
            None, kind, refusal=f"scope_kind {scope_kind!r} is not one of {list(SCOPE_KINDS)}"
        )
    if kind == "ANY_TARGET":
        notes = (
            [f"scope_target {scope_target!r} ignored: scope_kind ANY_TARGET"]
            if raw not in ("", WILDCARD)
            else []
        )
        return NormalizedScope(WILDCARD, kind, notes)
    if kind == "RESOURCE":
        # RV-7: the grant covers the action wherever it runs through this resource — not only requests whose
        # scope target happens to spell the resource's own id. intended_scope / requested_scope normally
        # target a data asset / handoff id (a different id space than the resource/tool id); reading RESOURCE
        # as "target == resource" made such a grant unmatchable against any real request (A-15 pattern).
        same = not raw or _canonical(raw, action, resource, known_ids) == resource
        notes = [] if same else [f"scope_target {scope_target!r} ignored: scope_kind RESOURCE"]
        return NormalizedScope(WILDCARD, kind, notes)
    if raw in ("", WILDCARD):
        if kind == "INTENDED_TARGET":
            return NormalizedScope(None, kind, refusal="scope_kind INTENDED_TARGET needs a scope_target id")
        return NormalizedScope(WILDCARD, kind)
    target = _canonical(raw, action, resource, known_ids)
    if target is None:
        return NormalizedScope(
            None, kind, refusal=f"scope_target {scope_target!r} is not an id (free text is not a scope)"
        )
    notes = [] if target == raw else [f"scope_target {scope_target!r} normalized to {target!r} (syntax only)"]
    return NormalizedScope(target, kind, notes)


def _canonical(raw: str, action: str, resource: str, known_ids: Iterable[str]) -> str | None:
    """The single non-action id written in ``raw`` (case-insensitive spelling of a known id), else None."""
    tokens = [t.strip(_QUOTES) for t in _SEP.split(raw) if t.strip(_QUOTES)]
    rest = [t for t in tokens if t.lower() != action.lower()] if len(tokens) > 1 else tokens
    if len(rest) != 1:
        return None
    token = rest[0]
    if token == WILDCARD:
        return WILDCARD
    if any(ch.isspace() for ch in token):
        return None  # a phrase, not an id
    known = {k.lower(): k for k in (resource, *known_ids) if k}
    return known.get(token.lower(), token)


def accepted_targets(resource: str, intended: Iterable[str]) -> list[str]:
    """The canonical targets a repair-path grant may name (for the refusal feedback; not a decision)."""
    return [WILDCARD, resource, *sorted({t for t in intended if t and t != WILDCARD})]
