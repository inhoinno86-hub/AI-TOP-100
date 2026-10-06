"""VERIFY skills: Layer 2 semantic judge (advisory) and the final explanation for the Human."""

from __future__ import annotations

from typing import Any


def judge_payload(view: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {"state": view, "layer1": report}


def summary_payload(view: dict[str, Any], release: dict[str, Any]) -> dict[str, Any]:
    return {"state": view, "release": release}


def summary_fallback(view: dict[str, Any], release: dict[str, Any]) -> dict[str, Any]:
    pd = view.get("problem_definition") or {}
    return {
        "summary": f"Release decision {release.get('decision')} for {pd.get('id')} v{pd.get('version')}: "
        f"{pd.get('root_problem', '')}"[:2000],
        "key_points": [f"evidence: {', '.join(pd.get('evidence_refs', []))}"[:600]],
        "limitations_explained": [str(x)[:600] for x in release.get("limitations", [])][:8],
    }
