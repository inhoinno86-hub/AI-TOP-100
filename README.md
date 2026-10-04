# AI TOP 100 Harness v0.3

Implementation of the frozen v0.3 core design
(`docs/AI_TOP_100_Harness_v0.3_Design_Freeze_설계문서.md`). Implementation notes live in
`docs/implementation/`.

```bash
python3 -m pytest                                   # 103 tests incl. Mock #1~#5 and REQUEST_CONTEXT regression
PYTHONPATH=src python3 -m aitop_harness slice examples/rehearsal_scenario.json
uvx ruff check src tests && uvx mypy                # lint / type check
```

No runtime dependencies (Python ≥ 3.11 standard library only).
