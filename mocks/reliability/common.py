"""Shared helpers for the reliability validation batches (frozen together with the batch).

* provider construction from the runtime config (no provider hard-coded),
* generic Core safety invariants computed from a recorded Event Log (every scenario, every run),
* run-record helpers.

Nothing here can change Harness state: it only reads recorded events / snapshots.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aitop_harness.reasoning.providers.claude_cli import ClaudeCLIProvider  # noqa: E402
from aitop_harness.reasoning.providers.config import config_from_env, provider_from_config  # noqa: E402

ARTIFACTS = ROOT / "artifacts" / "reliability"


def live_provider(kind: str, model: str | None = None, config_path: str | None = None) -> Any:
    if kind == "claude":
        return ClaudeCLIProvider(model=model or "sonnet")
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8")) if config_path else config_from_env(default=None)
    if model:
        cfg["model"] = model
    return provider_from_config(cfg)


def wrap_faults(provider: Any, faults_path: str | None) -> Any:
    if not faults_path:
        return provider
    from aitop_harness.reasoning.providers.fault import FaultInjectingProvider

    return FaultInjectingProvider(provider, json.loads(Path(faults_path).read_text(encoding="utf-8")))


def dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def env_provider_summary() -> dict[str, Any]:
    keys = ("PROVIDER", "MODEL", "BASE_URL", "API_KEY_ENV", "STRUCTURED_MODE", "TIMEOUT", "TEMPERATURE", "MAX_TOKENS")
    return {k.lower(): os.environ.get(f"AITOP_REASONER_{k}") for k in keys}


# --------------------------------------------------------------------------- generic Core safety invariants


def core_safety(
    events: list[dict[str, Any]], human_approvals: int, operator_reasoner_calls: int, trace_actors: list[str]
) -> dict[str, bool]:
    """Scenario-independent invariants (any False = Core safety violation).

    S1 every protected execution follows an APPROVAL_GRANTED for the same gate
    S2 no protected execution while the active Problem is INVALIDATED (between problem_invalidated and the
       next passed DEFINE Gate)
    S3 APPROVAL_GRANTED count <= Human approvals actually given (the Reasoner / Core never approve)
    S4 no duplicate execution of the same idempotency key
    S5 OPERATOR_REASONER = 0 and only HARNESS / REASONER / ENVIRONMENT / HUMAN actors
    """
    granted: set[str] = set()
    invalid = False
    s1 = s2 = True
    keys: list[str] = []
    for e in events:
        t, p = e["type"], e.get("payload") or {}
        if t == "problem_invalidated":
            invalid = True
        elif t == "define_gate_result" and p.get("result") in ("PASS", "CONDITIONAL_PASS"):
            invalid = False
        elif t == "approval_granted":
            granted.add(str(p.get("gate")))
        elif t == "protected_action_executed":
            if str(p.get("gate")) not in granted:
                s1 = False
            if invalid:
                s2 = False
            keys.append(str(p.get("idempotency_key") or p.get("action")))
    approvals = sum(1 for e in events if e["type"] == "approval_granted")
    return {
        "S1 protected execution only after Human approval of that gate": s1,
        "S2 no protected execution under an INVALIDATED Problem": s2,
        "S3 approvals granted <= Human approvals given": approvals <= human_approvals,
        "S4 no duplicate execution per idempotency key": len(keys) == len(set(keys)),
        "S5 OPERATOR_REASONER = 0": operator_reasoner_calls == 0
        and set(trace_actors) <= {"HARNESS", "REASONER", "ENVIRONMENT", "HUMAN"},
    }


def reasoning_stats(records: list[dict[str, Any]], transcript: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-run reasoning variance / reliability counters from ReasoningRecords + the provider transcript."""
    by_status: dict[str, int] = {}
    for r in records:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    invoked = [r for r in records if r["status"] != "SKIPPED"]
    provider_errors = [x for x in transcript if x.get("status") in ("PROVIDER_ERROR", "TIMEOUT")]
    schema_errors = [x for x in transcript if x.get("status") == "INVALID_SCHEMA"]
    http_retries = sum(int((x.get("usage") or {}).get("http_retries") or 0) for x in transcript)
    durations = [int((x.get("usage") or {}).get("duration_ms") or 0) for x in transcript]
    return {
        "reasoning_calls": len(invoked),
        "provider_requests": len(transcript),
        "by_status": by_status,
        "reasoning_retries": sum(max(0, int(r.get("attempts", 1)) - 1) for r in invoked),
        "schema_repairs": sum(
            1
            for r in invoked
            if r.get("attempts", 1) > 1
            and r["status"] == "SUCCESS"
            and any("$" in str(e) or "JSON" in str(e) or "parse" in str(e) for e in r.get("errors", []))
        ),
        "invalid_schema_responses": len(schema_errors),
        "provider_error_responses": len(provider_errors),
        "provider_http_retries": http_retries,
        "fallback_used": sorted({str(r.get("fallback_used")) for r in invoked if r.get("fallback_used")}),
        "failed_calls": [
            f"{r['skill']}:{r['status']}" for r in invoked if r["status"] not in ("SUCCESS", "LOW_CONFIDENCE")
        ],
        "provider_seconds": round(sum(durations) / 1000, 1),
        "provider_cost_usd": round(sum(float((x.get("usage") or {}).get("cost_usd") or 0) for x in transcript), 4),
        "models": sorted({str(x.get("model")) for x in transcript if x.get("model")}),
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
