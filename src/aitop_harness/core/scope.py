"""Scope model used by blocking_scope, release scope, authorized/requested scope.

A scope is a set of ``(action, target)`` items. ``"*"`` is a wildcard in *patterns*
(blocking scopes, authorized scopes) — never in concrete requested/release items.

``Open VOB ≠ Global HOLD`` (Design Freeze §14) is implemented by intersecting
``VOB.blocking_scope`` with the concrete release / action scope.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

WILDCARD = "*"


@dataclass(frozen=True)
class ScopeItem:
    action: str
    target: str = WILDCARD

    def matches(self, concrete: ScopeItem) -> bool:
        """True if this (pattern) item covers the concrete item."""
        action_ok = self.action == WILDCARD or self.action == concrete.action
        target_ok = self.target == WILDCARD or self.target == concrete.target
        return action_ok and target_ok

    def __str__(self) -> str:
        return f"{self.action}:{self.target}"


@dataclass
class Scope:
    """A scope pattern.

    ``entire_solution=True`` means the scope covers everything (e.g. a critical unknown that is
    the premise of the whole solution). This is also the conservative default for a
    VerificationObligation whose blocking scope was not specified.
    """

    items: list[ScopeItem] = field(default_factory=list)
    entire_solution: bool = False

    @classmethod
    def entire(cls) -> Scope:
        return cls(items=[], entire_solution=True)

    @classmethod
    def of(cls, *pairs: tuple[str, str] | str) -> Scope:
        items = []
        for p in pairs:
            if isinstance(p, str):
                action, _, target = p.partition(":")
                items.append(ScopeItem(action, target or WILDCARD))
            else:
                items.append(ScopeItem(*p))
        return cls(items=items)

    def is_empty(self) -> bool:
        return not self.entire_solution and not self.items

    def covers(self, concrete: ScopeItem) -> bool:
        if self.entire_solution:
            return True
        return any(p.matches(concrete) for p in self.items)

    def intersect(self, concrete: Iterable[ScopeItem]) -> list[ScopeItem]:
        """Concrete items (e.g. release scope) that this pattern blocks/covers."""
        return [c for c in concrete if self.covers(c)]

    def contains_all(self, concrete: Iterable[ScopeItem]) -> tuple[bool, list[ScopeItem]]:
        """``requested ⊆ authorized`` check. Returns (ok, items outside this scope)."""
        outside = [c for c in concrete if not self.covers(c)]
        return (not outside, outside)

    def is_narrower_than(self, other: Scope) -> bool:
        """True if ``self`` covers strictly less than ``other`` (used to detect narrowing)."""
        if other.entire_solution and not self.entire_solution:
            return True
        if self.entire_solution:
            return False
        return any(not any(s.matches(o) or s == o for s in self.items) for o in other.items)
