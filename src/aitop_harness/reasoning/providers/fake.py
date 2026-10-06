"""Deterministic fake provider for tests (prompt §28): input pattern → predefined structured proposal.

A handler for a skill is one of:
* a callable ``(request, input_dict) -> dict | ReasoningResponse``,
* a list of outputs consumed in order (the last one repeats),
* a single output dict,
* a list of rules ``{"match": {"path.in.input": "substring", ...}, "output": {...}}`` (first match wins).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..interface import ReasoningRequest, ReasoningResponse, ReasoningStatus

Handler = (
    Callable[[ReasoningRequest, dict[str, Any]], "dict[str, Any] | ReasoningResponse"]
    | list[Any]
    | dict[str, Any]
)


def _lookup(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def _matches(rule: dict[str, Any], data: dict[str, Any]) -> bool:
    for path, needle in rule.get("match", {}).items():
        value = _lookup(data, path)
        hay = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        if str(needle) not in hay:
            return False
    return True


@dataclass
class FakeProvider:
    handlers: dict[str, Handler] = field(default_factory=dict)
    name: str = "fake"
    model: str = "deterministic-fake"
    calls: list[ReasoningRequest] = field(default_factory=list)
    _cursor: dict[str, int] = field(default_factory=dict)

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        self.calls.append(request)
        handler = self.handlers.get(request.skill)
        if handler is None:
            return ReasoningResponse(
                ReasoningStatus.PROVIDER_ERROR,
                provider=self.name,
                model=self.model,
                error=f"fake provider has no handler for skill {request.skill}",
            )
        data = json.loads(request.input_json)
        out: Any
        if callable(handler):
            out = handler(request, data)
        elif (
            isinstance(handler, list) and handler and isinstance(handler[0], dict) and "output" in handler[0]
        ):
            rule = next((r for r in handler if _matches(r, data)), None)
            if rule is None:
                return ReasoningResponse(
                    ReasoningStatus.PROVIDER_ERROR,
                    provider=self.name,
                    model=self.model,
                    error=f"no fake rule matched for {request.skill}",
                )
            out = rule["output"]
        elif isinstance(handler, list):
            i = self._cursor.get(request.skill, 0)
            self._cursor[request.skill] = i + 1
            out = handler[min(i, len(handler) - 1)]
        else:
            out = handler
        if isinstance(out, ReasoningResponse):
            return out
        return ReasoningResponse(
            ReasoningStatus.SUCCESS, output=copy.deepcopy(out), provider=self.name, model=self.model
        )

    def count(self, skill: str) -> int:
        return sum(1 for c in self.calls if c.skill == skill)
