"""Tool abstraction (Design Freeze §2 Tool Registry).

``ToolResult.status == SUCCESS`` is transport-level only. Completeness is assessed separately
(``phases.execute.assess_completeness``) — ``SUCCESS ≠ COMPLETE``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.enums import ResultStatus, SourceAuthority

TRANSIENT_ERROR_CLASSES = frozenset({"TIMEOUT", "RATE_LIMIT", "CONNECTION_RESET", "SERVICE_BUSY", "HTTP_503"})


@dataclass
class ToolResult:
    status: ResultStatus
    records: list[dict[str, Any]] = field(default_factory=list)
    error_class: str | None = None
    retryable_hint: bool | None = None
    partial_side_effect_possible: bool = False
    expected_count: int | None = None
    returned_count: int | None = None
    pagination_complete: bool | None = None
    missing_fields: list[str] = field(default_factory=list)
    coverage_period: str | None = None
    required_coverage_period: str | None = None
    source_authority: SourceAuthority = SourceAuthority.UNKNOWN
    snapshot_age_minutes: float | None = None
    time_cost: float = 1.0
    is_mutation: bool = False
    message: str = ""

    def __post_init__(self) -> None:
        if self.returned_count is None and self.status is ResultStatus.SUCCESS and not self.is_mutation:
            self.returned_count = len(self.records)


class ToolAdapter(Protocol):
    tool_id: str
    read_only: bool

    def call(self, operation: str, params: dict[str, Any]) -> ToolResult: ...


@dataclass
class ToolSpec:
    tool_id: str
    dependency: str  # underlying dependency (for failure signatures)
    read_only: bool = True
    authority: SourceAuthority = SourceAuthority.UNKNOWN
    fallback_for: str | None = None


class ToolRegistry:
    """Available tools. Availability ≠ authorization (Design Freeze §11)."""

    def __init__(self) -> None:
        self._adapters: dict[str, ToolAdapter] = {}
        self._specs: dict[str, ToolSpec] = {}

    def register(self, adapter: ToolAdapter, spec: ToolSpec) -> None:
        if adapter.tool_id != spec.tool_id:
            raise ValueError("adapter/spec tool_id mismatch")
        self._adapters[spec.tool_id] = adapter
        self._specs[spec.tool_id] = spec

    def adapter(self, tool_id: str) -> ToolAdapter:
        return self._adapters[tool_id]

    def spec(self, tool_id: str) -> ToolSpec:
        return self._specs[tool_id]

    def fallbacks_for(self, tool_id: str) -> list[ToolSpec]:
        return [s for s in self._specs.values() if s.fallback_for == tool_id]

    def __contains__(self, tool_id: object) -> bool:
        return tool_id in self._specs
