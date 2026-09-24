# Planner (lean) -- intent

Authoritative for the lean planner. Mechanics not restated here (step-script
contract, QR CLI locking, severity de-escalation, wave computation, fix
routers, reconciliation) are inherited unchanged from `../planner-old/INTENT.md`.

## Purpose

Turn a multi-milestone change into shipped, verified code with the fewest
agent-runs that still catch the defects that actually occur: data-layer
(columns, casts, enums), access control (permissions, row-level security,
tenant scope, which identity runs a query), contract drift, UI lifecycle, and
behaviour only visible on the running system.

## Gate model

Every gate is: **work -> review -> reverify -> route**.

- **review**: exactly one reviewer agent. It investigates against the real
  artifact and writes `qr-{phase}.json` with a verdict on every item
  (PASS, or FAIL + finding with evidence). It returns one word.
- **reverify**:
  - not `awaiting_reverify` -> no agent; Python reads the verdicts and prints
    the route command with the computed `--qr-status`.
  - `awaiting_reverify` (a fixer ran) -> increment iteration; add a
    `reg-NN` regression-sweep item (iteration >= 2); dispatch ONE agent for
    all blocking TODO/FAIL items; the agent's one word is the route status.
  - iteration already at `QR_ITERATION_LIMIT` -> escalate to the user
    without incrementing (`extra_round` set, `awaiting_reverify` kept). The
    user chooses: re-check the latest fix once more (re-run the same step;
    exactly one re-check runs, then the next fix round escalates again),
    accept the remaining items (route pass), or stop.
- **route**: `build_gate_output`, unchanged from planner-old.

The live gate has no reviewer: its items are the plan's `live_checks`,
written mechanically at iteration 0 with `awaiting_reverify` set, so the
first round is a check round and fix rounds count from 2 like every gate.

## Invariants

1. The orchestrator never reads or edits qr files; Python derives state.
2. `awaiting_reverify` is set only by a work/fix step that dispatched a fixer
   and cleared only by the reverify step that dispatched the re-check.
3. A re-check never re-examines PASS items; the regression sweep covers what
   a fix might have broken.
4. Every milestone that touches SQL, schema, access policies, tenant or
   ownership scope, or acts on behalf of another party declares
   `integration_tests` run against the real dependency as the production
   identity. Every user-visible milestone declares `live_checks`. The
   plan-design reviewer fails the plan (MUST) when either is missing.
5. The executor runs the wave's integration tests before code review, ships
   once after all waves, and does not document until live checks pass.
6. The orchestrator delegates everything except running the ship command.
7. No evidenced defect disappears silently. A gate can pass with FAIL items
   left (below the de-escalation threshold, or accepted at escalation);
   before a qr file is deleted they are copied to exec-state.json
   `known_issues` and listed in the retrospective; the planner's approval
   message lists plan-design leftovers.

## State files

| File | Written by | Notes |
| ---- | ---------- | ----- |
| `context.json` | orchestrator step 2 | adds `verification_env: [str]` (optional in schema for planner-old compatibility) |
| `plan.json` | architect via `cli.plan` | milestones add `integration_tests`, `live_checks` (`set-verification`); no `code_changes` are produced |
| `qr-{phase}.json` | reviewer (Write), re-checkers (`cli.qr update-item`), Python | phases: plan-design, impl-code, impl-live, impl-docs; adds `awaiting_reverify`, `extra_round` |
| `exec-state.json` | executor Python | adds `known_issues` (FAIL items that outlived their gate) |

## Evidence

2026-09 Risky run under planner-old: 31.1M subagent tokens; 68% spent in
per-item verifiers that added no findings beyond the decomposer's; plan-code
review 30% for catches `tsc` would make; live checks 1% of tokens and 7 real
defects that no other gate could observe. The lean gates keep every stage
that caught a defect and replace the rest.

## Rejected alternatives

- **Built-in Workflow tool instead of scripts**: needs explicit per-run user
  opt-in and loses the step-script contract other skills share.
- **Dropping re-verification entirely**: fixes do introduce regressions;
  the targeted re-check + regression sweep is the cheapest guard.
- **Keeping plan-code review "for hard milestones"**: its substantive catches
  (intent contradicts code) are cheaper to make in plan-design review by
  reading the code the intent names.
