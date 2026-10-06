"""Reasoner — invoke a skill through a provider with validation, bounded retry and fallback.

Pipeline per call (prompt §24-26):

    request → provider → schema validation → unsafe-output screen → confidence check → typed proposal

* INVALID_SCHEMA → bounded repair attempt with the validation errors (never committed).
* TIMEOUT / PROVIDER_ERROR → bounded retry, then the fallback provider if one is configured.
* UNSAFE_OUTPUT → not committed, not repaired (the Core sees only the failure record).
* Every outcome produces a ``ReasoningRecord`` (provenance) — the caller (Harness Core) writes it to the
  Event Log. The Reasoner has no access to the Harness state and cannot mutate it (IDR-REASON-02).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .interface import (
    ProviderTimeout,
    ReasoningProvider,
    ReasoningRequest,
    ReasoningResponse,
    ReasoningStatus,
)
from .models import PARSERS
from .prompts import INSTRUCTIONS, SYSTEM
from .schemas import SCHEMA_VERSION, schema_for, validate

# Strings a *proposal* must never contain: they are attempts to act / instruct, not to propose (§22).
_UNSAFE = re.compile(
    r"ignore (all |any |the )?(previous|prior|above) (instructions|prompts?)"
    r"|disregard (the )?(system|previous) (prompt|instructions)"
    r"|(i|we) (hereby )?(approve|authori[sz]e)d?\b"
    r"|\bapprov(e|ed|al) (granted|given)\b"
    r"|human (has )?approved"
    r"|\bexecute (the )?(tool|protected action|mutation)\b"
    r"|\bbypass (the )?(human gate|gate|approval|guard)",
    re.I,
)

LOW_CONFIDENCE_THRESHOLD = 0.2


@dataclass
class ReasoningRecord:
    """Provenance of one reasoning call (prompt §26). Stored in the Event Log by the Core."""

    reasoning_id: str
    skill: str
    status: ReasoningStatus
    provider: str
    model: str
    input_state_version: int
    schema_version: str
    order: int
    attempts: int
    input_digest: str
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float | None = None
    errors: list[str] = field(default_factory=list)
    output: dict[str, Any] | None = None
    fallback_used: str | None = None


@dataclass
class ReasoningResult:
    record: ReasoningRecord
    proposal: Any = None  # typed proposal (models.*) when status is SUCCESS / LOW_CONFIDENCE

    @property
    def ok(self) -> bool:
        return self.proposal is not None and self.record.status in (
            ReasoningStatus.SUCCESS,
            ReasoningStatus.LOW_CONFIDENCE,
            ReasoningStatus.SKIPPED,  # skipped with a deterministic fallback proposal
        )


_REF = re.compile(r"\b(?:E|H|CL|U|A|SC|M|VOB)-[A-Z0-9][A-Z0-9_.-]*")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def screen_unsafe(output: dict[str, Any]) -> list[str]:
    """Deterministic screen for outputs that try to act instead of propose."""
    return sorted({m.group(0) for s in _strings(output) for m in [_UNSAFE.search(s)] if m})


def cited_refs(output: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for s in _strings(output):
        refs += _REF.findall(s)
    return sorted(set(refs))


class Reasoner:
    """Skill invoker. Stateless with respect to the Harness; keeps only its own call log."""

    def __init__(
        self,
        provider: ReasoningProvider,
        *,
        fallback_provider: ReasoningProvider | None = None,
        max_attempts: int = 3,
        low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.provider = provider
        self.fallback_provider = fallback_provider
        self.max_attempts = max_attempts
        self.low_confidence_threshold = low_confidence_threshold
        self.records: list[ReasoningRecord] = []

    # ------------------------------------------------------------------ public

    def invoke(
        self,
        skill: str,
        payload: dict[str, Any],
        *,
        state_version: int,
        deterministic_fallback: Callable[[], dict[str, Any] | None] | None = None,
    ) -> ReasoningResult:
        input_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(f"{skill}\n{input_json}".encode()).hexdigest()[:16]
        order = len(self.records) + 1
        record = ReasoningRecord(
            reasoning_id=f"R-{order}",
            skill=skill,
            status=ReasoningStatus.PROVIDER_ERROR,
            provider=self.provider.name,
            model=self.provider.model,
            input_state_version=state_version,
            schema_version=SCHEMA_VERSION,
            order=order,
            attempts=0,
            input_digest=digest,
        )
        self.records.append(record)
        result = self._run(self.provider, skill, input_json, record)
        if (
            not result.ok
            and self.fallback_provider is not None
            and record.status
            in (
                ReasoningStatus.TIMEOUT,
                ReasoningStatus.PROVIDER_ERROR,
                ReasoningStatus.INVALID_SCHEMA,
            )
        ):
            record.fallback_used = f"provider:{self.fallback_provider.name}"
            record.provider, record.model = self.fallback_provider.name, self.fallback_provider.model
            result = self._run(self.fallback_provider, skill, input_json, record)
        if (
            not result.ok
            and deterministic_fallback is not None
            and record.status is not (ReasoningStatus.UNSAFE_OUTPUT)
        ):
            output = deterministic_fallback()
            if output is not None and not validate(output, schema_for(skill)):
                record.fallback_used = "deterministic"
                record.status = ReasoningStatus.SUCCESS
                record.output = output
                record.provider, record.model = "deterministic-fallback", "rules"
                result = ReasoningResult(record, PARSERS[skill](output))
        return result

    def skipped(self, skill: str, reason: str, *, state_version: int) -> ReasoningRecord:
        order = len(self.records) + 1
        record = ReasoningRecord(
            reasoning_id=f"R-{order}",
            skill=skill,
            status=ReasoningStatus.SKIPPED,
            provider=self.provider.name,
            model=self.provider.model,
            input_state_version=state_version,
            schema_version=SCHEMA_VERSION,
            order=order,
            attempts=0,
            input_digest="",
            errors=[reason],
        )
        self.records.append(record)
        return record

    # ------------------------------------------------------------------ internals

    def _run(
        self, provider: ReasoningProvider, skill: str, input_json: str, record: ReasoningRecord
    ) -> ReasoningResult:
        feedback: tuple[str, ...] = ()
        for attempt in range(1, self.max_attempts + 1):
            record.attempts += 1
            request = ReasoningRequest(
                skill=skill,
                system=SYSTEM,
                instruction=INSTRUCTIONS[skill],
                input_json=input_json,
                output_schema=schema_for(skill),
                schema_version=SCHEMA_VERSION,
                attempt=attempt,
                repair_feedback=feedback,
            )
            try:
                response = provider.reason(request)
            except ProviderTimeout as exc:
                response = ReasoningResponse(ReasoningStatus.TIMEOUT, error=str(exc))
            except Exception as exc:  # noqa: BLE001 — a provider failure is data for the Core, never a crash
                response = ReasoningResponse(
                    ReasoningStatus.PROVIDER_ERROR, error=f"{type(exc).__name__}: {exc}"
                )
            if response.status in (ReasoningStatus.TIMEOUT, ReasoningStatus.PROVIDER_ERROR):
                record.status = response.status
                record.errors.append(response.error or response.status.value)
                continue
            output = response.output
            errors = validate(output, schema_for(skill)) if output is not None else ["no structured output"]
            if errors:
                record.status = ReasoningStatus.INVALID_SCHEMA
                record.errors.extend(errors[:8])
                feedback = tuple(errors[:12])  # bounded repair prompt
                continue
            assert output is not None
            unsafe = screen_unsafe(output)
            if unsafe:
                record.status = ReasoningStatus.UNSAFE_OUTPUT
                record.errors.append(f"unsafe directives in output: {unsafe}")
                record.output = output
                return ReasoningResult(record)
            try:
                proposal = PARSERS[skill](output)
            except (KeyError, TypeError, ValueError) as exc:
                record.status = ReasoningStatus.INVALID_SCHEMA
                record.errors.append(f"parse: {exc}")
                feedback = (f"parse error: {exc}",)
                continue
            confidence = output.get("confidence")
            record.confidence = float(confidence) if isinstance(confidence, (int, float)) else None
            record.status = (
                ReasoningStatus.LOW_CONFIDENCE
                if record.confidence is not None and record.confidence < self.low_confidence_threshold
                else ReasoningStatus.SUCCESS
            )
            record.output = output
            record.evidence_refs = cited_refs(output)
            return ReasoningResult(record, proposal)
        return ReasoningResult(record)
