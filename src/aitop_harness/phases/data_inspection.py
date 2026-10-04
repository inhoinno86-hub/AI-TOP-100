"""Data quality / completeness inspection (kickoff PHASE C, v0.2.1 §12-13).

Duplicate semantics are distinguished, never naively deduped:
identical rows → EXACT_RECORD_DUPLICATE; same key with status change → STATUS_PROGRESSION;
same key with event version change → EVENT_VERSION; same key, other differences → DUPLICATE_BUSINESS_KEY.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..core.enums import DataIssueType, QualityLevel, ResultCompleteness
from ..core.events import EventType
from ..domain.data import DataIssue, DataQuality
from ..engine.context import HarnessContext
from ..supervision.monitoring import SignalKind

_TYPES: dict[str, tuple[type, ...]] = {
    "str": (str,),
    "int": (int,),
    "float": (int, float),
    "bool": (bool,),
    "datetime": (str,),
}


@dataclass
class InspectionReport:
    quality: DataQuality
    issues: list[DataIssue] = field(default_factory=list)
    completeness: ResultCompleteness = ResultCompleteness.UNKNOWN
    record_count: int = 0

    def issue_types(self) -> set[DataIssueType]:
        return {i.type for i in self.issues}

    def count(self, t: DataIssueType) -> int:
        return sum(i.count for i in self.issues if i.type is t)


def inspect_records(
    records: list[dict[str, Any]],
    *,
    schema: dict[str, str] | None = None,
    required_fields: list[str] | None = None,
    key_fields: list[str] | None = None,
    status_field: str | None = None,
    version_field: str | None = None,
    timestamp_field: str | None = None,
    entity_field: str | None = None,
    expected_count: int | None = None,
    pagination_complete: bool | None = None,
) -> InspectionReport:
    issues: list[DataIssue] = []
    schema = schema or {}
    required = required_fields or list(schema)

    # missing / type / timestamp
    missing = unexpected = malformed_ts = 0
    for i, r in enumerate(records):
        for f in required:
            if r.get(f) in (None, ""):
                missing += 1
                issues.append(DataIssue(DataIssueType.MISSING, f"row {i} missing {f}", [str(i)], f))
        for f, tname in schema.items():
            v = r.get(f)
            if v is None:
                continue
            ok_types = _TYPES.get(tname)
            if ok_types and (not isinstance(v, ok_types) or (tname != "bool" and isinstance(v, bool))):
                unexpected += 1
                issues.append(
                    DataIssue(DataIssueType.UNEXPECTED_TYPE, f"row {i} {f} not {tname}", [str(i)], f)
                )
        if timestamp_field and r.get(timestamp_field) is not None:
            try:
                datetime.fromisoformat(str(r[timestamp_field]))
            except ValueError:
                malformed_ts += 1
                issues.append(
                    DataIssue(DataIssueType.MALFORMED, f"row {i} bad timestamp", [str(i)], timestamp_field)
                )

    # duplicates vs event semantics
    exact_dupes = progression = versions = dup_key = 0
    seen_rows: dict[str, int] = {}
    by_key: dict[tuple[Any, ...], list[int]] = {}
    for i, r in enumerate(records):
        canon = json.dumps(r, sort_keys=True, default=str)
        if canon in seen_rows:
            exact_dupes += 1
            issues.append(
                DataIssue(
                    DataIssueType.EXACT_RECORD_DUPLICATE,
                    f"row {i} == row {seen_rows[canon]}",
                    [str(seen_rows[canon]), str(i)],
                )
            )
            continue
        seen_rows[canon] = i
        if key_fields:
            by_key.setdefault(tuple(r.get(k) for k in key_fields), []).append(i)
    for key, idxs in by_key.items():
        if len(idxs) < 2:
            continue
        rows = [records[i] for i in idxs]
        refs = [str(i) for i in idxs]
        statuses = {r.get(status_field) for r in rows} if status_field else set()
        vers = {r.get(version_field) for r in rows} if version_field else set()
        entities = {r.get(entity_field) for r in rows} if entity_field else set()
        if entity_field and len(entities) > 1:
            dup_key += 1
            issues.append(
                DataIssue(
                    DataIssueType.KEY_COLLISION,
                    f"key {key} refers to different entities {sorted(map(str, entities))}",
                    refs,
                )
            )
        elif version_field and len(vers) > 1:
            versions += 1
            issues.append(
                DataIssue(
                    DataIssueType.EVENT_VERSION, f"key {key} has versions {sorted(map(str, vers))}", refs
                )
            )
        elif status_field and len(statuses) > 1:
            progression += 1
            issues.append(
                DataIssue(
                    DataIssueType.STATUS_PROGRESSION, f"key {key} statuses {sorted(map(str, statuses))}", refs
                )
            )
        else:
            dup_key += 1
            issues.append(
                DataIssue(DataIssueType.DUPLICATE_BUSINESS_KEY, f"key {key} repeated with differences", refs)
            )

    # completeness: SUCCESS ≠ COMPLETE
    if expected_count is None or pagination_complete is False:
        completeness = (
            ResultCompleteness.PARTIAL if pagination_complete is False else ResultCompleteness.UNKNOWN
        )
    else:
        completeness = (
            ResultCompleteness.COMPLETE if len(records) >= expected_count else ResultCompleteness.PARTIAL
        )

    n = max(len(records), 1)

    def level(bad: int) -> QualityLevel:
        if bad == 0:
            return QualityLevel.GOOD
        return QualityLevel.ACCEPTABLE if bad / n < 0.05 else QualityLevel.PROBLEMATIC

    quality = DataQuality(
        completeness={
            ResultCompleteness.COMPLETE: level(missing),
            ResultCompleteness.PARTIAL: QualityLevel.PROBLEMATIC,
        }.get(completeness, QualityLevel.UNKNOWN),
        validity=level(unexpected + malformed_ts),
        consistency=level(dup_key + versions),
        uniqueness=level(exact_dupes),
        timeliness=QualityLevel.UNKNOWN,  # freshness is lazy
        interpretability=level(dup_key),
    )
    return InspectionReport(
        quality=quality, issues=issues, completeness=completeness, record_count=len(records)
    )


def apply_inspection(ctx: HarnessContext, data_asset_id: str, report: InspectionReport) -> None:
    with ctx.commit(f"data inspection {data_asset_id}") as ps:
        asset = ps.data_assets[data_asset_id]
        asset.quality = report.quality
        asset.issues = list(report.issues)
        asset.completeness = report.completeness
    warnings = [f"{data_asset_id}: {t.value} x{report.count(t)}" for t in sorted(report.issue_types())]
    ctx.supervision.data_quality_warnings.extend(warnings)
    event = ctx.emit(
        EventType.DATA_INSPECTED,
        {"asset": data_asset_id, "completeness": report.completeness.value, "issues": warnings},
    )
    if not report.issues and report.completeness is ResultCompleteness.COMPLETE:
        ctx.signal(SignalKind.ROUTINE_VALIDATION_SUCCESS, f"{data_asset_id} clean", event_seq=event.seq)
    else:
        ctx.signal(
            SignalKind.STATE_DIFF, "; ".join(warnings) or f"{data_asset_id} incomplete", event_seq=event.seq
        )
