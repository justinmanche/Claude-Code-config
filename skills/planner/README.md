# Planner (lean)

Plans and executes multi-milestone changes behind quality gates. Same
mechanics as `planner-old` -- Python step scripts that print a prompt and the
exact next command, a STATE_DIR with `context.json` / `plan.json` /
`qr-{phase}.json`, the locked QR CLI, review -> fix -> re-verify -> route
gates with progressive severity de-escalation, waves of parallel developers,
fix routers -- with the gates rebuilt around what measurably catches defects.

**Design rationale and invariants**: INTENT.md.

## Planning (6 steps)

```
  1 init -> 2 context (+ verification_env) -> 3 architect
                                                  |
                         +------------------------+
                         v
                    4 review (1 agent, verdicts) -> 5 reverify -> 6 route
                         ^                                           |
                         +------------- FAIL: 3 (fix mode) <---------+
                                        PASS: PLAN APPROVED
```

| Step | Who | Output |
| ---- | --- | ------ |
| 1 plan-init | orchestrator | STATE_DIR, plan.json skeleton |
| 2 context-verify | orchestrator | context.json, including `verification_env` (unit, integration, ship, live commands) |
| 3 plan-design-work | architect | milestones, code_intents, decisions, waves, **integration_tests**, **live_checks** |
| 4 plan-design-review | 1 quality-reviewer (opus) | qr-plan-design.json with a verdict per item, intents checked against the real code |
| 5 plan-design-reverify | none, or 1 quality-reviewer after a fix | route status; after a fix: failed items + regression sweep re-checked |
| 6 plan-design-route | orchestrator | FAIL -> 3, PASS -> plan.md rendered + handoff: save `<DEST>.{md,json,context.json}`, print a fresh-session execute prompt |

## Execution (13 steps)

```
  1 init
  per wave:  2 developers + unit/integration gates -> 3 review -> 4 reverify -> 5 route
  once:      6 ship + live checks -> 7 route --FAIL--> 8 live fix -> 6
  once:      9 technical writer -> 10 review -> 11 reverify -> 12 route
             13 retrospective
```

| Gate | Items come from | Re-check after a fix |
| ---- | --------------- | -------------------- |
| impl-code (per wave) | 1 reviewer reading the wave's diff | failed items + `git diff` regression sweep, 1 agent |
| impl-live (once) | `milestones[].live_checks`, mechanically | redeploy; failed items + regression sweep of the fix's flows, 1 agent |
| impl-docs (once) | 1 reviewer | failed items + regression sweep, 1 agent |

## What changed from planner-old, and why

Measured on the 2026-09 Risky run (issues #180-#203, 281 subagent runs, 31.1M
subagent tokens):

| planner-old stage | Cost | Caught | Lean planner |
| ----------------- | ---- | ------ | ------------ |
| plan-design review | 1.9M | RLS-silent-pass, missing enum value, unregistered audit action | **kept**, now also checks intents against real code |
| plan-code review of planned diffs | 9.3M (30%) | mostly imports/typos tsc would catch; one round mostly false positives | **removed**; its real catches moved into plan-design review |
| plan-docs review | 3.1M | one migration-marker defect (only exists because of planned diffs) | **removed**; docs written once after the code |
| per-wave decomposer | ~1.4M total | every crash- and SQL-class defect before deploy | **kept** as the single reviewer that records verdicts |
| per-wave verify fan-out | ~15M | nothing the decomposer had not already found | **replaced** by 1 re-check agent, only after a fix |
| live checks on TEST | 0.4M (1%) | 7 defects no other gate could see | **made a mandatory gate** (steps 6-8) |
| unit tests / typecheck | - | nothing that was shipping (can't see columns, casts, RLS) | kept, plus **mandatory real-dependency integration tests** per milestone |

## Running the tests

```sh
cd ~/.claude/skills/scripts
python3 -m pytest tests/test_planner_lean.py     # needs pytest + pydantic
```

The tests drive both orchestrators through every route (review fail -> fix ->
re-check -> pass, wave advance, live fail -> fix -> redeploy -> pass, live
gate skipped, iteration-limit escalation) by playing the sub-agents.
