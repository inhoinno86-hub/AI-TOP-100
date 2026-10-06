"""Real model provider: Claude via the ``claude`` CLI in print mode with native structured output.

No SDK dependency (the Harness core stays dependency-free). Each request runs
``claude -p --output-format json --json-schema <schema> --system-prompt <system> --tools ""`` in an
isolated working directory with no tools, no MCP servers, no session persistence and no settings, so the
model sees only the Reasoner's system instruction and the request. The CLI's ``structured_output`` is
returned; the Harness re-validates it against the same schema anyway.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any

from ..interface import ProviderTimeout, ReasoningRequest, ReasoningResponse, ReasoningStatus


def _child_env() -> dict[str, str]:
    """Isolate the reasoning call from any parent Claude Code session (effort, session ids, sockets)."""
    drop = ("CLAUDE_CODE_", "CLAUDECODE", "CLAUDE_EFFORT", "CLAUDE_PID", "CLAUDE_PLUGIN", "ANTHROPIC_LOG")
    return {k: v for k, v in os.environ.items() if not k.startswith(drop)}


@dataclass
class ClaudeCLIProvider:
    model: str = "sonnet"
    executable: str = "claude"
    timeout_seconds: float = 420.0
    effort: str | None = "medium"
    name: str = "claude-cli"
    usage_log: list[dict[str, Any]] = field(default_factory=list)

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def _command(self, request: ReasoningRequest) -> list[str]:
        cmd = [
            self.executable,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(request.output_schema),
            "--system-prompt",
            request.system,
            "--tools",
            "",
            "--model",
            self.model,
            "--no-session-persistence",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--disable-slash-commands",
        ]
        if self.effort:
            cmd += ["--effort", self.effort]
        return cmd

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        if not self.available():
            return ReasoningResponse(
                ReasoningStatus.PROVIDER_ERROR,
                provider=self.name,
                model=self.model,
                error=f"{self.executable} not found on PATH",
            )
        with tempfile.TemporaryDirectory(prefix="aitop-reasoner-") as cwd:
            try:
                proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
                    self._command(request),
                    input=request.prompt(),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    cwd=cwd,
                    env=_child_env(),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ProviderTimeout(f"claude CLI exceeded {self.timeout_seconds}s") from exc
        if proc.returncode != 0 and not proc.stdout.strip():
            return ReasoningResponse(
                ReasoningStatus.PROVIDER_ERROR,
                provider=self.name,
                model=self.model,
                error=f"exit {proc.returncode}: {proc.stderr.strip()[:500]}",
            )
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return ReasoningResponse(
                ReasoningStatus.PROVIDER_ERROR,
                provider=self.name,
                model=self.model,
                error="CLI output is not JSON",
                raw=proc.stdout[:2000],
            )
        usage = {
            "cost_usd": envelope.get("total_cost_usd"),
            "duration_ms": envelope.get("duration_ms"),
            "models": list((envelope.get("modelUsage") or {}).keys()),
        }
        self.usage_log.append(usage)
        if envelope.get("is_error"):
            return ReasoningResponse(
                ReasoningStatus.PROVIDER_ERROR,
                provider=self.name,
                model=self.model,
                error=str(envelope.get("result") or envelope.get("subtype"))[:500],
                usage=usage,
            )
        output = envelope.get("structured_output")
        if output is None:
            text = envelope.get("result") or ""
            try:
                output = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return ReasoningResponse(
                    ReasoningStatus.INVALID_SCHEMA,
                    provider=self.name,
                    model=self.model,
                    error="no structured output",
                    raw=str(text)[:2000],
                    usage=usage,
                )
        resolved = usage["models"][0] if usage["models"] else self.model
        return ReasoningResponse(
            ReasoningStatus.SUCCESS, output=output, provider=self.name, model=resolved, usage=usage
        )
