"""Environment / Human boundary of the autonomous runner (what is *outside* the Harness).

* ``Environment`` = the world: tools (``registry``), stakeholders who answer interviews, documents, and
  messages that arrive on their own (``poll``). It also exposes the *affordance catalog* — which
  read-only operations / interviews / documents are reachable at a stage. Affordances are not reasoning:
  the Reasoner chooses among them and estimates their value; the Core ranks and executes.
* ``HumanInterface`` = the Human at the Mandatory Human Gate. Only a Human produces a decision text; the
  Reasoner never does (prompt §33).

``ScenarioEnvironment`` is a data-driven world used by the CLI and the tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.enums import EvidenceSourceType, ExecutionStatus, SourceAuthority
from ..core.serialization import from_dict
from ..phases.discover import DiscoveryActionKind
from ..phases.human_gate import ProtectedExecutor
from ..tools.base import ToolRegistry, ToolResult, ToolSpec
from ..tools.simulated import ScriptedTool
from .context import HarnessContext


@dataclass(frozen=True)
class Affordance:
    ref: str
    kind: DiscoveryActionKind
    target: str  # tool id / stakeholder id / document id
    operation: str  # tool operation / interview topic / document id
    description: str = ""
    read_only: bool = True


@dataclass
class ExternalInput:
    """Something the world delivers (stakeholder message, document). Always untrusted data."""

    source_type: EvidenceSourceType
    source_id: str
    content: str
    authority: SourceAuthority = SourceAuthority.NON_AUTHORITATIVE
    method: str = "message"
    label: str = ""


@dataclass
class GateView:
    gate_id: str
    packet: str
    explanation: str | None = None
    round: int = 0


class Environment(Protocol):
    registry: ToolRegistry

    def catalog(self, stage: str, ctx: HarnessContext) -> list[Affordance]: ...

    def interview(self, stakeholder_id: str, question: str) -> str: ...

    def review_document(self, ref: str) -> ExternalInput: ...

    def poll(self, ctx: HarnessContext) -> list[ExternalInput]: ...

    def executor(self, tool_id: str) -> ProtectedExecutor: ...


class HumanInterface(Protocol):
    def respond(self, gate: GateView) -> str | None:
        """Free-text Human answer for a WAITING_APPROVAL gate, or None (no decision yet)."""
        ...


@dataclass
class ScriptedHuman:
    """Test / rehearsal Human: answers from a script (None = no decision yet)."""

    script: list[str | None] = field(default_factory=list)
    seen: list[GateView] = field(default_factory=list)

    def respond(self, gate: GateView) -> str | None:
        self.seen.append(gate)
        if not self.script:
            return None
        return self.script.pop(0)


@dataclass
class ConsoleHuman:
    """Interactive Human for the CLI (empty input = no decision yet)."""

    def respond(self, gate: GateView) -> str | None:
        print(gate.packet)
        if gate.explanation:
            print(f"CONTEXT:\n{gate.explanation}")
        try:
            text = input(f"[{gate.gate_id}] approve / reject / question (empty = wait): ").strip()
        except EOFError:
            return None
        return text or None


# --------------------------------------------------------------------------- data-driven world


@dataclass
class _InboxItem:
    when: dict[str, Any]
    item: ExternalInput
    delivered: bool = False


class ScenarioEnvironment:
    """World defined in JSON (see ``examples/autonomous_scenario.json``)::

        "world": {
          "tools": [{"tool_id", "dependency", "read_only", "authority", "fallback_for", "describes",
                     "script": {"<op>": [ToolResult...]}}],
          "interviews": {"SH-X": "answer text"},
          "documents": {"DOC-1": {"source_type": "DOCUMENT", "source_id": "...", "content": "...",
                                  "authority": "AUTHORITATIVE"}},
          "inbox": [{"when": {"phase": "EXECUTE", "problem_version": 1, "waiting_approval": true,
                              "min_minute": 120, "after_executed": "tool:op"},
                     "input": {...ExternalInput}}],
          "catalog": {"discover": ["tool:op", "interview:SH-X", "document:DOC-1"],
                      "reprofile": [...], "execute": [...], "execute@v2": [...]}
        }

    A catalog stage may be suffixed with ``@v<N>`` to apply only while the Problem version is N.
    Without an explicit catalog every read-only operation of every tool is offered at every stage.
    """

    def __init__(self, world: dict[str, Any]) -> None:
        self.world = world
        self.registry = ToolRegistry()
        self.tools: dict[str, ScriptedTool] = {}
        self.describes: dict[str, str] = {}
        for t in world.get("tools", []):
            script = {
                op: [from_dict(ToolResult, r) for r in results] for op, results in t.get("script", {}).items()
            }
            tool = ScriptedTool(t["tool_id"], read_only=t.get("read_only", True), script=script)
            self.tools[tool.tool_id] = tool
            self.describes[tool.tool_id] = t.get("describes", "")
            self.registry.register(
                tool,
                ToolSpec(
                    t["tool_id"],
                    t.get("dependency", t["tool_id"]),
                    t.get("read_only", True),
                    SourceAuthority(t.get("authority", "UNKNOWN")),
                    t.get("fallback_for"),
                ),
            )
        self.interviews: dict[str, str] = dict(world.get("interviews", {}))
        self.documents: dict[str, ExternalInput] = {
            ref: _external(d) for ref, d in world.get("documents", {}).items()
        }
        self.inbox = [
            _InboxItem(dict(i.get("when", {})), _external(i["input"])) for i in world.get("inbox", [])
        ]
        self.executed: list[str] = []
        self.listeners: list[Callable[[str, HarnessContext], None]] = []

    # ------------------------------------------------------------------ catalog

    def _all(self) -> list[Affordance]:
        out: list[Affordance] = []
        for tid, tool in self.tools.items():
            if not tool.read_only:
                continue
            for op in tool.script:
                out.append(
                    Affordance(f"{tid}:{op}", DiscoveryActionKind.TOOL_QUERY, tid, op, self.describes[tid])
                )
        for sh in self.interviews:
            out.append(
                Affordance(f"interview:{sh}", DiscoveryActionKind.STAKEHOLDER_INTERVIEW, sh, "interview")
            )
        for ref in self.documents:
            out.append(Affordance(f"document:{ref}", DiscoveryActionKind.DOCUMENT_REVIEW, ref, ref))
        return out

    def catalog(self, stage: str, ctx: HarnessContext) -> list[Affordance]:
        everything = {a.ref: a for a in self._all()}
        spec = self.world.get("catalog")
        if not spec:
            return list(everything.values())
        pd = ctx.problem.problem_definition
        version = pd.version if pd else 1
        refs = list(spec.get(f"{stage}@v{version}", spec.get(stage, [])))
        return [everything[r] for r in refs if r in everything]

    # ------------------------------------------------------------------ world interactions

    def interview(self, stakeholder_id: str, question: str) -> str:
        return self.interviews.get(stakeholder_id, "(no answer)")

    def review_document(self, ref: str) -> ExternalInput:
        return self.documents[ref]

    def poll(self, ctx: HarnessContext) -> list[ExternalInput]:
        out = []
        for item in self.inbox:
            if not item.delivered and _due(item.when, ctx, self.executed):
                item.delivered = True
                out.append(item.item)
        return out

    def executor(self, tool_id: str) -> ProtectedExecutor:
        return self.tools[tool_id]

    def note_executed(self, ref: str) -> None:
        self.executed.append(ref)


def _external(d: dict[str, Any]) -> ExternalInput:
    return ExternalInput(
        source_type=EvidenceSourceType(d.get("source_type", "STAKEHOLDER")),
        source_id=d["source_id"],
        content=d["content"],
        authority=SourceAuthority(d.get("authority", "NON_AUTHORITATIVE")),
        method=d.get("method", "message"),
        label=d.get("label", ""),
    )


def _due(when: dict[str, Any], ctx: HarnessContext, executed: list[str]) -> bool:
    pd = ctx.problem.problem_definition
    if "phase" in when and ctx.runtime.phase.value != when["phase"]:
        return False
    if "problem_version" in when and (pd is None or pd.version != when["problem_version"]):
        return False
    if "problem_status" in when and (pd is None or pd.status.value != when["problem_status"]):
        return False
    if when.get("waiting_approval") and ctx.runtime.execution_status is not ExecutionStatus.WAITING_APPROVAL:
        return False
    if "min_minute" in when and ctx.clock.now() < float(when["min_minute"]):
        return False
    return not ("after_executed" in when and when["after_executed"] not in executed)
