# planner/

Lean planning and execution skill: one deep review per gate, real-dependency
integration tests, live verification on the deployed system.

## Files

| File        | What                                            | When to read                          |
| ----------- | ----------------------------------------------- | ------------------------------------- |
| `SKILL.md`  | Skill activation and invocation                 | Using the planner skill               |
| `INTENT.md` | Design rationale, invariants, state contracts   | Changing gates, steps or state files  |
| `README.md` | Flows, step tables, measured rationale, tests   | Understanding the planner             |

## Subdirectories

| Directory    | What                                   | When to read                  |
| ------------ | -------------------------------------- | ----------------------------- |
| `resources/` | Plan format and plan.json schema docs  | Editing plan structure        |

Python code: `scripts/skills/planner/` (orchestrator/, architect/, developer/,
technical_writer/, quality_reviewer/, shared/, cli/).
Tests: `scripts/tests/test_planner_lean.py`.
Previous workflow: `../planner-old/` (Python: `scripts/skills/planner_old/`).
