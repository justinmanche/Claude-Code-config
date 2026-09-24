---
name: planner-old
description: "Legacy (pre-2026-09) heavyweight planner: plan-design, plan-code and plan-docs review loops with parallel per-item verification. Use only when the user explicitly asks for planner-old; the default is planner."
---

## Activation

When this skill activates, IMMEDIATELY invoke the corresponding script. The
script IS the workflow.

| Mode      | Intent                             | Command                                                                                                          |
| --------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| planning  | "plan", "design", "architect"      | `<invoke working-dir=".claude/skills/scripts" cmd="python3 -m skills.planner_old.orchestrator.planner --step 1" />`  |
| execution | "execute", "implement", "run plan" | `<invoke working-dir=".claude/skills/scripts" cmd="python3 -m skills.planner_old.orchestrator.executor --step 1 --plan <path>" />` |

Execution step 1 needs the plan: pass `--plan <plan.md-or-plan.json>` (a .md
needs its sibling .json), or `--state-dir <planner STATE_DIR>` from the same
session. Add `--reconcile` when resuming work that may be partially complete.
