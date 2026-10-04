"""Contest clock. Injected so budget logic is deterministic and testable."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SimulatedClock:
    """Minutes elapsed since contest start (00:00)."""

    elapsed_minutes: float = 0.0

    def now(self) -> float:
        return self.elapsed_minutes

    def advance(self, minutes: float) -> float:
        if minutes < 0:
            raise ValueError("clock cannot move backwards")
        self.elapsed_minutes += minutes
        return self.elapsed_minutes
