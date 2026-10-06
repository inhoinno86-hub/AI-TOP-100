"""Record / replay providers: make a real-model run reproducible and auditable.

``RecordingProvider`` wraps any provider and appends every exchange (skill, ordinal, input digest,
output) to a JSONL transcript. ``ReplayProvider`` answers from such a transcript by (skill, ordinal);
with ``strict=True`` it also requires the same input digest. When the transcript is exhausted (or a
strict digest mismatches) it delegates to ``fallback`` if given, else reports PROVIDER_ERROR.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..interface import ReasoningProvider, ReasoningRequest, ReasoningResponse, ReasoningStatus


def request_digest(request: ReasoningRequest) -> str:
    return hashlib.sha256(f"{request.skill}\n{request.input_json}".encode()).hexdigest()[:16]


@dataclass
class RecordingProvider:
    inner: ReasoningProvider
    path: Path
    _ordinals: dict[str, int] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def model(self) -> str:
        return self.inner.model

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        response = self.inner.reason(request)
        ordinal = self._ordinals.get(request.skill, 0)
        if request.attempt == 1:
            self._ordinals[request.skill] = ordinal + 1
        else:
            ordinal = max(0, ordinal - 1)
        entry = {
            "skill": request.skill,
            "ordinal": ordinal,
            "attempt": request.attempt,
            "digest": request_digest(request),
            "status": response.status.value,
            "provider": response.provider or self.inner.name,
            "model": response.model or self.inner.model,
            "output": response.output,
            "error": response.error,
            "usage": response.usage,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return response


@dataclass
class ReplayProvider:
    entries: list[dict[str, Any]]
    strict: bool = False
    fallback: ReasoningProvider | None = None
    name: str = "replay"
    model: str = "transcript"
    misses: list[str] = field(default_factory=list)
    _ordinals: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path, **kw: Any) -> ReplayProvider:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        return cls([json.loads(x) for x in lines if x.strip()], **kw)

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        ordinal = self._ordinals.get(request.skill, 0)
        if request.attempt == 1:
            self._ordinals[request.skill] = ordinal + 1
        else:
            ordinal = max(0, ordinal - 1)
        candidates = [
            e
            for e in self.entries
            if e["skill"] == request.skill and e["ordinal"] == ordinal and e["status"] == "SUCCESS"
        ]
        hit = next((e for e in candidates if e.get("attempt", 1) >= request.attempt), None) or (
            candidates[-1] if candidates else None
        )
        if hit is not None and self.strict and hit["digest"] != request_digest(request):
            hit = None
            self.misses.append(f"{request.skill}#{ordinal}: digest mismatch")
        if hit is None:
            if not candidates:
                self.misses.append(f"{request.skill}#{ordinal}: not in transcript")
            if self.fallback is not None:
                return self.fallback.reason(request)
            return ReasoningResponse(
                ReasoningStatus.PROVIDER_ERROR,
                provider=self.name,
                model=self.model,
                error=f"replay transcript has no entry for {request.skill}#{ordinal}",
            )
        return ReasoningResponse(
            ReasoningStatus.SUCCESS,
            output=hit["output"],
            provider=f"replay:{hit.get('provider', '')}",
            model=hit.get("model", ""),
        )
