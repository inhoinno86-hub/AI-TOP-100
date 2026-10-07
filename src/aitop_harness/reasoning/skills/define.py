"""DEFINE skill (prompt §13, §21): Problem Definition proposal. The DEFINE Gate decides, not the Reasoner."""

from __future__ import annotations

from typing import Any


def define_payload(
    view: dict[str, Any],
    *,
    tool_surface: list[dict[str, Any]],
    repair_request: dict[str, Any] | None = None,
    rejected: str | None = None,
    framing_repair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"state": view, "tool_surface": tool_surface}
    if repair_request:
        out["repair_request"] = repair_request  # typed DEFINE Gate findings (IDR-RV4-03), not free text
    if framing_repair:
        out["framing_repair"] = framing_repair  # typed anti-anchoring finding (IDR-RV5-02), not free text
    if rejected:
        out["previous_proposal_rejected"] = rejected
    return out
