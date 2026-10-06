"""DEFINE skill (prompt §13, §21): Problem Definition proposal. The DEFINE Gate decides, not the Reasoner."""

from __future__ import annotations

from typing import Any


def define_payload(
    view: dict[str, Any],
    *,
    tool_surface: list[dict[str, Any]],
    gate_findings: list[str] | None = None,
    rejected: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"state": view, "tool_surface": tool_surface}
    if gate_findings:
        out["gate_findings"] = gate_findings
    if rejected:
        out["previous_proposal_rejected"] = rejected
    return out
