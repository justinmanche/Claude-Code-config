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

## Lessons built in from executed plans

Each of these came from a real run and is now generated into the step text, not
left to the orchestrator to remember.

| Lesson | What the planner does now |
| ------ | ------------------------- |
| Agents in isolated git worktrees started from stale code (Claude Code builds the worktree from origin/main and nothing had been pushed) | Every developer, technical-writer, live-fix and doc-fix dispatch begins with a base-commit preamble: the exact SHA of the local `main` tip (read with `git rev-parse` in the plan's repo when the step prints) and the command `git merge-base --is-ancestor <sha> HEAD \|\| git merge --ff-only main`. The agent must be on top of that SHA or stop and report. Parallel waves recommend `isolation: worktree` per agent with a distinct database/container port each; the orchestrator merges agent branches into a wave branch, then into main after the gate passes. After a wave merges, the gate output says to push main if `push_policy` is `after_each_wave`, otherwise it reminds that later worktrees start from stale origin/main and the preamble covers it. The repo comes from `--repo`, else the plan's `repo_path`, else the git repo of the working directory, and is stored in `exec-state.json`. |
| "Nothing like X remains" was checked with regex sweeps that each missed a form, three rounds running | Planning guidance requires an absence criterion to be backed by an inventory (every candidate occurrence enumerated and classified) or a test that fails on a new occurrence. The plan-design review flags a single-pattern absence criterion (MUST), and developers report `INVENTORY:` counts. |
| A data-loss bug showed up only in a multi-step sequence on the live system (save short answer, lengthen past a new limit, save, reload: the earlier value was gone) | Planning guidance requires every milestone that changes how data is saved, edited, limited, validated or deleted to have a multi-step live sequence plus an undo/clear path. The plan-design review flags the gap (MUST) and the live regression sweep runs save/modify/reload sequences over changed code. |
| Required permissions were discovered mid-run, one blocked command at a time | Plans carry `required_permissions` and `push_policy`. The planner asks the owner during planning. Executor step 1 and the live-verify step print the rules as a `/permissions` list; the orchestrator asks the owner to add them before wave 1 and never edits settings. Every dispatched agent prompt says: if a command is denied, stop and report exactly which command. |
| A developer ran every full suite (unit, integration, e2e) itself and the wave gate then ran them all again; on a loaded machine the e2e run failed at random and one milestone took 4.5 hours (Risky, Node 24 upgrade) | Developers run only targeted tests: the test files they changed or wrote and the named integration specs. A criterion that names a full suite is reported as `LEFT-TO-GATE:` and does not block PASS. The wave gate is the one full run, and it checks the machine load (`uptime`) first so load-induced failures are not read as real. The architect names each `integration_test` by the file or spec it lives in, not "the full suite is green". |
| Agents copied scripts onto a VM to run read-only checks | Live-verify guidance says to pass read-only remote checks inline (for example `docker exec <container> <runtime> -e '...'` through the cloud CLI's run-command). |

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

`tests/test_planner_lessons.py` (unittest-based, also collected by pytest; run
it with `python3 -m unittest tests.test_planner_lessons`) covers the lessons
above: schema accept/reject for `required_permissions` and `push_policy`, the
permissions block in executor step 1 and the live-verify step, the base-commit
preamble with a real SHA, the push-policy messages, and the review, developer
and live-verify rules.

The tests drive both orchestrators through every route (review fail -> fix ->
re-check -> pass, wave advance, live fail -> fix -> redeploy -> pass, live
gate skipped, iteration-limit escalation) by playing the sub-agents.
