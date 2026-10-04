"""Organization / Stakeholder / BusinessProcess / ProcessHandoff (Design Freeze §7-8)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import (
    AckLayer,
    AckStatus,
    DeliveryStatus,
    FreshnessStatus,
    SemanticValidity,
)


@dataclass
class Organization:
    id: str
    name: str
    role: str = ""
    objectives: list[str] = field(default_factory=list)
    stakeholders: list[str] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)
    process_handoffs: list[str] = field(default_factory=list)
    data_assets: list[str] = field(default_factory=list)
    external_dependencies: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)


@dataclass
class Stakeholder:
    id: str
    organization_id: str
    role: str = ""
    responsibilities: list[str] = field(default_factory=list)
    process_steps: list[str] = field(default_factory=list)
    knowledge_scope: list[str] = field(default_factory=list)
    # What this stakeholder may *authorize*. A request from someone without authority_scope
    # is not authorization (Design Freeze §11: Stakeholder Request ≠ Stakeholder Authority).
    authority_scope: list[str] = field(default_factory=list)
    incentives: list[str] = field(default_factory=list)
    potential_bias: list[str] = field(default_factory=list)
    interview_status: str = "NOT_INTERVIEWED"
    information_topics: list[str] = field(default_factory=list)


@dataclass
class BusinessProcess:
    id: str
    name: str
    organization_ids: list[str] = field(default_factory=list)
    purpose: str = ""
    trigger: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)
    systems: list[str] = field(default_factory=list)
    data_assets: list[str] = field(default_factory=list)
    handoff_ids: list[str] = field(default_factory=list)
    wait_points: list[str] = field(default_factory=list)
    manual_steps: list[str] = field(default_factory=list)
    duplicate_steps: list[str] = field(default_factory=list)
    failure_points: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    pain_points: list[str] = field(default_factory=list)


@dataclass
class Acknowledgment:
    """One ACK layer. Multiple layers only when their meanings actually differ (v0.2.4 §7)."""

    layer: AckLayer
    meaning: str
    status: AckStatus = AckStatus.UNKNOWN
    timestamp: str | None = None
    evidence_ref: str | None = None


@dataclass
class ProcessHandoff:
    """Cross-actor handoff.

    ``delivery_status``, ``semantic_validity`` and ``freshness_status`` are independent
    dimensions (DELIVERY ≠ SEMANTIC VALIDITY ≠ FRESHNESS). ``status`` is an overall
    workflow label and must never be used as a substitute for any of them.
    Freshness is lazy: ``NOT_EVALUATED`` unless decision-relevant.
    """

    id: str
    process_id: str | None = None
    from_org: str | None = None
    from_actor: str | None = None
    to_org: str | None = None
    to_actor: str | None = None
    accountable_owner: str | None = None
    trigger: str = ""
    payload: str = ""
    payload_schema: str | None = None
    entity_identity_refs: list[str] = field(default_factory=list)
    channel: str = ""
    cadence: str = ""
    acknowledgments: list[Acknowledgment] = field(default_factory=list)
    delivery_status: DeliveryStatus = DeliveryStatus.UNKNOWN
    semantic_validity: SemanticValidity = SemanticValidity.UNKNOWN
    expected_latency: str | None = None
    actual_latency: str | None = None
    freshness_requirement: str | None = None
    observed_data_age: str | None = None
    version_lag: str | None = None
    freshness_status: FreshnessStatus = FreshnessStatus.NOT_EVALUATED
    manual_or_automated: str = ""
    authority_boundary: str | None = None
    failure_modes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    metric_refs: list[str] = field(default_factory=list)
    status: str = "ACTIVE"

    def ack(self, layer: AckLayer) -> Acknowledgment | None:
        for a in self.acknowledgments:
            if a.layer is layer:
                return a
        return None
