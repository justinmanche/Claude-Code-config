---
name: planner
description: Interactive planning and execution for complex tasks, with one deep review per gate, real-dependency integration tests and live verification on the deployed system. IMMEDIATELY invoke when user asks to use planner.
---

## Activation

When this skill activates, IMMEDIATELY invoke the corresponding script. The
script IS the workflow.

| Mode      | Intent                             | Command                                                                                                          |
| --------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| planning  | "plan", "design", "architect"      | `<invoke working-dir=".claude/skills/scripts" cmd="python3 -m skills.planner.orchestrator.planner --step 1" />`  |
| execution | "execute", "implement", "run plan" | `<invoke working-dir=".claude/skills/scripts" cmd="python3 -m skills.planner.orchestrator.executor --step 1 --plan <path>" />` |

Planning ends by saving `<DEST>.md`, `<DEST>.json` and `<DEST>.context.json`
together and giving the user a paste-ready prompt for a fresh session (the
usual flow is plan -> clear session -> execute). Present that prompt last.

Execution step 1 needs the plan: pass `--plan <plan.md-or-plan.json>` (a .md
needs its sibling .json), or `--state-dir <planner STATE_DIR>` from the same
session. Add `--reconcile` when resuming work that may be partially complete.

The previous, heavier workflow (plan-code and plan-docs review phases,
parallel per-item verification) is still available as `planner-old`.
