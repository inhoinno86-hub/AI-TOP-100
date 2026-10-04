"""Harness errors. Failures are raised, never swallowed (kickoff §13)."""

from __future__ import annotations


class HarnessError(Exception):
    """Base class for harness errors."""


class IllegalTransitionError(HarnessError):
    """A phase/runtime transition that the frozen flow does not allow."""


class DesignOrderError(HarnessError):
    """DESIGN steps attempted out of the frozen order (Structural Remedy before Agent)."""


class ProtectedActionBlocked(HarnessError):
    """A protected action was attempted outside the Mandatory Human Gate flow."""


class ScopeNarrowingRejected(HarnessError):
    """blocking_scope narrowing attempted without committed evidence."""


class StateIntegrityError(HarnessError):
    """Canonical state invariant violated."""
