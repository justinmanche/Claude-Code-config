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

While planning, the planner asks the owner which outside actions the plan needs
(GitHub writes, cloud CLIs, remote commands, credential or database reads,
deploys, pushes) and records them in the plan as `required_permissions`
(exact Claude Code permission rules, each with the reason) together with a
`push_policy` (`after_each_wave`, `at_end` or `never`; default `at_end`).
Execution step 1 prints those rules as a paste-ready `/permissions` list; the
orchestrator asks the owner to add them before wave 1 and never edits settings
itself. Every dispatched agent is told to stop and report a denied command
instead of working around it, and agents that write code or docs are told which
commit they must be on top of (see README.md).

Execution step 1 needs the plan: pass `--plan <plan.md-or-plan.json>` (a .md
needs its sibling .json), or `--state-dir <planner STATE_DIR>` from the same
session. Add `--reconcile` when resuming work that may be partially complete.

The previous, heavier workflow (plan-code and plan-docs review phases,
parallel per-item verification) is still available as `planner-old`.
