"""Scripted tools for mocks/tests. A script is a queue of results per operation."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from ..core.enums import ResultStatus
from .base import ToolResult


@dataclass
class ScriptedTool:
    tool_id: str
    read_only: bool = True
    script: dict[str, list[ToolResult]] = field(default_factory=dict)
    default: ToolResult | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    store: dict[str, Any] = field(default_factory=dict)  # mutation target for read-back

    def __post_init__(self) -> None:
        self._queues: dict[str, deque[ToolResult]] = defaultdict(deque)
        for op, results in self.script.items():
            self._queues[op].extend(results)

    def call(self, operation: str, params: dict[str, Any]) -> ToolResult:
        self.calls.append((operation, dict(params)))
        queue = self._queues.get(operation)
        if queue:
            result = queue.popleft() if len(queue) > 1 else queue[0]
        elif self.default is not None:
            result = self.default
        else:
            return ToolResult(ResultStatus.ERROR, error_class="UNSUPPORTED_OPERATION", retryable_hint=False)
        if result.status is ResultStatus.SUCCESS and result.is_mutation:
            key = params.get("idempotency_key") or operation
            self.store[str(key)] = dict(params)
        return result

    def read_back(self, key: str) -> dict[str, Any] | None:
        return self.store.get(key)

    def count(self, operation: str) -> int:
        return sum(1 for op, _ in self.calls if op == operation)
