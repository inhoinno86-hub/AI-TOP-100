"""Contest Adapter boundary (Design Freeze §2, §36.3; kickoff §12).

The core never depends on contest specifics. Everything here is an *interface*; the official
submission format, problem-page interface, I/O contract, allowed tools, auth, hidden tests,
artifact format, launch command and network rules are unknown until the official guide and
must not be guessed into the core.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..tools.base import ToolResult, ToolSpec


class ContestAdapter(ABC):
    """Implement once the official contest interface is published."""

    @abstractmethod
    def load_scenario(self) -> dict[str, Any]:
        """Return scenario input in the harness scenario format (see ``aitop_harness.scenario``)."""

    @abstractmethod
    def allowed_tools(self) -> list[ToolSpec]:
        """Tools the contest allows. Availability ≠ authorization."""

    @abstractmethod
    def package(self, artifacts: dict[str, str]) -> str:
        """Build the submission package; returns a package reference."""

    @abstractmethod
    def submit(self, package_ref: str, idempotency_key: str) -> ToolResult:
        """Submit. Always called through the Mandatory Human Gate (submission/publish)."""

    @abstractmethod
    def read_back(self, idempotency_key: str) -> dict[str, Any] | None:
        """Confirm a submission landed (read-back validation)."""


class SubmissionExecutor:
    """Adapts a ContestAdapter to the ProtectedExecutor protocol used by the Human Gate."""

    def __init__(
        self, adapter: ContestAdapter, package_ref: str, tool_id: str = "contest-submission"
    ) -> None:
        self.adapter = adapter
        self.package_ref = package_ref
        self.tool_id = tool_id

    def call(self, operation: str, params: dict[str, Any]) -> ToolResult:
        return self.adapter.submit(self.package_ref, str(params["idempotency_key"]))

    def read_back(self, key: str) -> dict[str, Any] | None:
        return self.adapter.read_back(key)
