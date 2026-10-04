"""ProcessHandoff health evaluation — delivery / semantic validity / freshness kept independent.

Freshness is lazy (Design Freeze §8): it is evaluated only when a downstream decision depends on it.
"""

from __future__ import annotations

from ..core.enums import AckLayer, AckStatus, DeliveryStatus, FreshnessStatus, SemanticValidity
from ..core.events import EventType
from ..domain.organization import Acknowledgment
from ..engine.context import HarnessContext


def record_acknowledgment(ctx: HarnessContext, handoff_id: str, ack: Acknowledgment) -> None:
    """Add/replace one ACK layer and derive delivery / semantic validity from the layers that exist."""
    with ctx.commit(f"ack {handoff_id} {ack.layer.value}") as ps:
        h = ps.process_handoffs[handoff_id]
        h.acknowledgments = [a for a in h.acknowledgments if a.layer is not ack.layer] + [ack]
        transport = h.ack(AckLayer.TRANSPORT)
        if transport is not None:
            h.delivery_status = {
                AckStatus.ACCEPTED: DeliveryStatus.HEALTHY,
                AckStatus.REJECTED: DeliveryStatus.FAILED,
            }.get(transport.status, DeliveryStatus.UNKNOWN)
        business = h.ack(AckLayer.BUSINESS_ACCEPTANCE) or h.ack(AckLayer.SCHEMA_VALIDATION)
        if business is not None and business.status is AckStatus.REJECTED:
            h.semantic_validity = SemanticValidity.BROKEN  # delivered ≠ accepted
        elif business is not None and business.status is AckStatus.ACCEPTED:
            h.semantic_validity = SemanticValidity.VALID


def evaluate_freshness(
    ctx: HarnessContext,
    handoff_id: str,
    *,
    observed_age_minutes: float,
    max_age_minutes: float,
    decision_relevant: bool,
) -> FreshnessStatus:
    """Evaluate freshness only when a decision depends on it; otherwise leave NOT_EVALUATED."""
    h = ctx.problem.process_handoffs[handoff_id]
    if not decision_relevant:
        return h.freshness_status
    status = FreshnessStatus.FRESH if observed_age_minutes <= max_age_minutes else FreshnessStatus.STALE
    with ctx.commit(f"freshness {handoff_id}") as ps:
        ho = ps.process_handoffs[handoff_id]
        ho.freshness_requirement = f"<= {max_age_minutes:.0f}m"
        ho.observed_data_age = f"{observed_age_minutes:.0f}m"
        ho.freshness_status = status
    ctx.emit(EventType.DATA_INSPECTED, {"handoff": handoff_id, "freshness": status.value})
    return status
