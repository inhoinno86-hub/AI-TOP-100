"""Skill / Reasoning Layer (Design Freeze §2 "Skill Layer"; IDR-REASON-01..08).

The Reasoning Layer is a *proposer / interpreter / planner*. It receives a read-only, JSON-serialised
view of the canonical state built by the Harness Core, and returns typed, schema-validated proposals.
It never receives a ``HarnessContext``, never commits, never transitions, never answers a Human Gate.
The Harness Core (``engine.proposals`` / ``engine.autonomous``) validates every proposal and is the only
committer.
"""
