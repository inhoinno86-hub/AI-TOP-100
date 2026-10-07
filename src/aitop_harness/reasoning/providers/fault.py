"""Controlled provider-failure injection (reliability validation, Batch D).

``FaultInjectingProvider`` wraps any provider and replaces selected calls with a failure. It never
touches the Harness: it only changes what the Reasoner receives, exactly like a misbehaving real
provider would. Rules are matched in order against each call; a call that matches no rule (or whose
rule is exhausted) goes to the inner provider.

Rule fields: ``fault`` (kind below), and any of ``call`` (1-based ordinal over all calls), ``skill``,
``attempt`` (request attempt number), ``times`` (how many matching calls fail; default 1, ``-1`` = all).

Fault kinds: ``timeout``, ``invalid_json``, ``schema_mismatch``, ``rate_limit``, ``provider_error``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..interface import (
    ProviderTimeout,
    ReasoningProvider,
    ReasoningRequest,
    ReasoningResponse,
    ReasoningStatus,
)

FAULT_KINDS = ("timeout", "invalid_json", "schema_mismatch", "rate_limit", "provider_error")


@dataclass
class FaultInjectingProvider:
    inner: ReasoningProvider
    rules: list[dict[str, Any]] = field(default_factory=list)
    injected: list[dict[str, Any]] = field(default_factory=list)
    calls: int = 0

    def __post_init__(self) -> None:
        for r in self.rules:
            if r.get("fault") not in FAULT_KINDS:
                raise ValueError(f"unknown fault kind {r.get('fault')!r}")
            r.setdefault("times", 1)

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def model(self) -> str:
        return self.inner.model

    def _match(self, request: ReasoningRequest) -> dict[str, Any] | None:
        for r in self.rules:
            if r["times"] == 0:
                continue
            if "call" in r and r["call"] != self.calls:
                continue
            if "skill" in r and r["skill"] != request.skill:
                continue
            if "attempt" in r and r["attempt"] != request.attempt:
                continue
            return r
        return None

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        self.calls += 1
        rule = self._match(request)
        if rule is None:
            return self.inner.reason(request)
        if rule["times"] > 0:
            rule["times"] -= 1
        kind = rule["fault"]
        self.injected.append(
            {"call": self.calls, "skill": request.skill, "attempt": request.attempt, "fault": kind}
        )
        tag = f"[injected:{kind}]"
        if kind == "timeout":
            raise ProviderTimeout(f"{tag} provider did not answer in time")
        if kind == "invalid_json":
            return ReasoningResponse(
                ReasoningStatus.INVALID_SCHEMA,
                provider=self.name,
                model=self.model,
                error=f"{tag} output is not JSON",
                raw='{"interpretation": "truncated',
            )
        if kind == "schema_mismatch":
            return ReasoningResponse(
                ReasoningStatus.SUCCESS,
                output={"unexpected_field": True, "confidence": "high"},
                provider=self.name,
                model=self.model,
            )
        if kind == "rate_limit":
            return ReasoningResponse(
                ReasoningStatus.PROVIDER_ERROR,
                provider=self.name,
                model=self.model,
                error=f"{tag} HTTP 429 (rate_limited)",
            )
        return ReasoningResponse(
            ReasoningStatus.PROVIDER_ERROR,
            provider=self.name,
            model=self.model,
            error=f"{tag} HTTP 503 (http_error): temporary provider error",
        )
