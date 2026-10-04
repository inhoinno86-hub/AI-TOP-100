"""Local file-system adapter for mocks and rehearsal. NOT the official contest interface."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..core.enums import ResultStatus
from ..tools.base import ToolResult, ToolSpec
from .base import ContestAdapter


class LocalDirectoryAdapter(ContestAdapter):
    def __init__(self, scenario_path: str | Path, workdir: str | Path) -> None:
        self.scenario_path = Path(scenario_path)
        self.workdir = Path(workdir)
        self._submitted: dict[str, dict[str, Any]] = {}

    def load_scenario(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.scenario_path.read_text(encoding="utf-8"))
        return data

    def allowed_tools(self) -> list[ToolSpec]:
        return []

    def package(self, artifacts: dict[str, str]) -> str:
        pkg = self.workdir / "package"
        pkg.mkdir(parents=True, exist_ok=True)
        for name, content in artifacts.items():
            (pkg / name).write_text(content, encoding="utf-8")
        return str(pkg)

    def submit(self, package_ref: str, idempotency_key: str) -> ToolResult:
        target = self.workdir / "submissions" / idempotency_key
        if target.exists():  # idempotent: never submit twice
            return ToolResult(ResultStatus.SUCCESS, is_mutation=True, message="already submitted")
        shutil.copytree(package_ref, target)
        self._submitted[idempotency_key] = {"package": package_ref}
        return ToolResult(ResultStatus.SUCCESS, is_mutation=True)

    def read_back(self, idempotency_key: str) -> dict[str, Any] | None:
        target = self.workdir / "submissions" / idempotency_key
        return (
            {"scope": ["submit:package"], "files": sorted(p.name for p in target.iterdir())}
            if target.exists()
            else None
        )
