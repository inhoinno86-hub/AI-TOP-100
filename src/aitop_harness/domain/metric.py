"""Metric MINIMAL / EXTENDED profiles (Design Freeze §10, v0.2.2 §16)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import MetricProfile, MetricType

# Semantic fields that the metric *type* itself requires, even in MINIMAL profile.
TYPE_REQUIRED_FIELDS: dict[MetricType, tuple[str, ...]] = {
    MetricType.DURATION: ("start_event", "end_event"),
    MetricType.RATE: ("numerator", "denominator"),
    MetricType.POPULATION_RATE: ("population", "numerator", "denominator"),
    MetricType.WINDOWED_TREND: ("measurement_window",),
    MetricType.HANDOFF_FRESHNESS: ("related_handoff",),
}

EXTENDED_FIELDS = (
    "start_event",
    "end_event",
    "population",
    "numerator",
    "denominator",
    "aggregation",
    "measurement_window",
    "exclusions",
    "owner",
    "current_value",
    "target_value",
)


@dataclass
class Metric:
    id: str
    name: str
    metric_type: MetricType = MetricType.OTHER
    purpose: str = ""
    definition: str = ""
    measurement_source: str = ""
    reliability: str = "UNKNOWN"
    profile: MetricProfile = MetricProfile.MINIMAL
    organization_id: str | None = None
    # EXTENDED / type-required semantics
    start_event: str | None = None
    end_event: str | None = None
    population: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    aggregation: str | None = None
    measurement_window: str | None = None
    exclusions: list[str] = field(default_factory=list)
    owner: str | None = None
    current_value: float | None = None
    target_value: float | None = None
    related_handoff: str | None = None
    current_value_is_speculative: bool = False

    def missing_type_semantics(self) -> list[str]:
        return [f for f in TYPE_REQUIRED_FIELDS.get(self.metric_type, ()) if not getattr(self, f)]

    def semantic_signature(self) -> tuple[str | None, ...]:
        """Same name ≠ same metric: compare by semantics, not by name."""
        return (
            self.metric_type.value,
            self.start_event,
            self.end_event,
            self.population,
            self.numerator,
            self.denominator,
            self.measurement_window,
        )

    def promote(self, **semantics: object) -> None:
        """MINIMAL → EXTENDED. Metric id is preserved (promotion is in-place)."""
        for key, value in semantics.items():
            if key not in EXTENDED_FIELDS and key not in ("related_handoff", "definition"):
                raise ValueError(f"unknown metric semantic field: {key}")
            setattr(self, key, value)
        self.profile = MetricProfile.EXTENDED
