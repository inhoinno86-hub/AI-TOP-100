"""DataAsset + quality / issue semantics (v0.2.1 §12-14)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import DataIssueType, QualityLevel, ResultCompleteness, SourceAuthority
from ..core.provenance import Provenance


@dataclass
class DataQuality:
    completeness: QualityLevel = QualityLevel.UNKNOWN
    validity: QualityLevel = QualityLevel.UNKNOWN
    consistency: QualityLevel = QualityLevel.UNKNOWN
    uniqueness: QualityLevel = QualityLevel.UNKNOWN
    timeliness: QualityLevel = QualityLevel.UNKNOWN
    interpretability: QualityLevel = QualityLevel.UNKNOWN


@dataclass
class DataIssue:
    type: DataIssueType
    description: str
    record_refs: list[str] = field(default_factory=list)
    field_name: str | None = None
    count: int = 1


@dataclass
class Transformation:
    id: str
    description: str
    destructive: bool = False
    input_ref: str | None = None
    output_ref: str | None = None
    validated: bool = False


@dataclass
class DataAsset:
    id: str
    name: str
    organization_id: str | None = None
    source: str = ""
    source_type: str = ""
    format: str = ""
    acquisition: str = ""
    raw_reference: str | None = None
    schema: dict[str, str] = field(default_factory=dict)  # field -> type name
    quality: DataQuality = field(default_factory=DataQuality)
    issues: list[DataIssue] = field(default_factory=list)
    transformations: list[Transformation] = field(default_factory=list)
    normalized_reference: str | None = None
    validation: dict[str, str] = field(default_factory=dict)
    provenance: Provenance | None = None
    used_by: list[str] = field(default_factory=list)
    # runtime-observed acquisition facts that matter to decisions
    completeness: ResultCompleteness = ResultCompleteness.UNKNOWN
    authority: SourceAuthority = SourceAuthority.UNKNOWN
    is_fallback: bool = False
