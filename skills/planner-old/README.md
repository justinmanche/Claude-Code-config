# Planner

LLM-generated plans have gaps. I have seen missing error handling, vague
acceptance criteria, specs that nobody can implement. I built this skill with
two workflows -- planning and execution -- connected by quality gates that catch
these problems early.

**Authoritative specification**: See INTENT.md for complete design rationale, invariants, and state file schemas. This README provides operational overview; INTENT.md is the source of truth for architectural decisions.

## Planning Workflow

```
  Planning ----+
      |        |
      v        |
     QR -------+  [fail: restart planning]
      |
      v
     TW -------+
      |        |
      v        |
   QR-Docs ----+  [fail: restart TW]
      |
      v
   APPROVED
```

| Step                    | Actions                                                                    |
| ----------------------- | -------------------------------------------------------------------------- |
| Context & Scope         | Confirm path, define scope, identify approaches, list constraints          |
| Decision & Architecture | Evaluate approaches, select with reasoning, diagram, break into milestones |
| Refinement              | Document risks, add uncertainty flags, specify paths and criteria          |
| Final Verification      | Verify completeness, check specs, write to file                            |
| QR-Completeness         | Verify Decision Log complete, policy defaults confirmed, plan structure    |
| QR-Code                 | Read codebase, verify diff context, apply RULE 0/1/2 to proposed code      |
| Technical Writer        | Scrub temporal comments, add WHY comments, enrich rationale                |
| QR-Docs                 | Verify no temporal contamination, comments explain WHY not WHAT            |

So, why all the feedback loops? QR-Completeness and QR-Code run before TW to
catch structural issues early. QR-Docs runs after TW to validate documentation
quality. Doc issues restart only TW; structure issues restart planning. The loop
runs until both pass.

## Execution Workflow

```
  Init --> Wave: Devs --> Code-QR --> route --+--> next wave (loop)
             ^               |                |
             +--- [fail] ----+                +--> Docs --> Doc-QR --> route --> Retrospective
                                                    ^                   |
                                                    +------ [fail] -----+
```

After planning completes and context clears (`/clear`), execution proceeds
(10 steps; step 1 needs `--plan <plan.md-or-plan.json>` or the planner's
`--state-dir`, plus `--reconcile` when resuming partial work):

| Step | Name                   | Purpose                                                       |
| ---- | ---------------------- | ------------------------------------------------------------- |
| 1    | exec-init              | Locate plan.json, build waves, write exec-state.json          |
| 2    | impl-code-work         | One developer per milestone in current wave (parallel)        |
| 3    | impl-code-qr-decompose | QR agent writes qr-impl-code.json verification items          |
| 4    | impl-code-qr-verify    | N QR agents verify items in parallel                          |
| 5    | impl-code-qr-route     | FAIL: fix loop to 2. PASS: next wave (2) or docs (6)          |
| 6    | impl-docs-work         | Technical writer updates CLAUDE.md/README.md                  |
| 7-9  | impl-docs QR block     | Same decompose/verify/route pattern for documentation         |
| 10   | Retrospective          | Present execution summary                                     |

Code QR runs per wave so a broken foundation wave is caught before dependent
waves build on it; documentation runs once over the finished implementation.

I designed the coordinator to never write code directly -- it delegates to
developers. Separating coordination from implementation produces cleaner
results. The coordinator:

- Parallelizes independent milestones within a wave (one developer each)
- Runs Code QR after every wave, before dependent waves start
- Loops work -> decompose -> verify -> route until QR passes (max 5 iterations,
  with progressive severity de-escalation)
- Invokes technical writer only after all waves pass Code QR

**Reconciliation** handles resume scenarios. Invoke step 1 with `--reconcile`
when the request contains signals like "already implemented", "resume", or
"partially complete": quality reviewers validate existing code against each
pending milestone, and SATISFIED milestones are marked `--done` before
execution. Building on unverified code means rework.

**Issue Resolution** is automatic: the route step loops to the work step,
whose router detects FAIL items in qr-impl-code.json and dispatches the fix
workflow (exec_implement_qr_fix.py / exec_docs_qr_fix.py) instead of execute.

## Invisible Knowledge

### Why session.yaml was removed

Initial design included session.yaml to track workflow state across invocations. Removed because context.json already captures task and architecture decisions -- the critical state that sub-agents need. Session-level tracking (current step, timestamps) belongs in the orchestrator's context window, not persisted state. Adding a separate file created redundancy without value.

### Why 6-field decision schema

Early design used 11 fields per decision (id, question, status, raised_at, decided_at, decided_by, answer, rationale, options, blocking, superseded_by). Reduced to 6 fields (id, question, status, decided_by, answer, rationale) because:

- raised_at/decided_at: Timestamps added noise without improving decision reasoning
- options: Better captured in findings.json during EXPLORING phase
- blocking: Implicit in status=READY with orchestrator waiting for user input
- superseded_by: Trackable via status=SUPERSEDED + new decision with same question

Simpler schema means less for LLMs to get wrong when writing decisions.

### Why per-phase qr-<phase>.json instead of single qa.json

Separate qr-<phase>.json files (qr-plan-structure.json, qr-plan-code.json, qr-plan-docs.json, qr-impl-code.json, qr-impl-docs.json) prevent cross-phase contamination. With a single qa.json:

- Plan QR items mix with implementation QR items (confusing for fixers)
- Verification scope unclear (which phase is this item checking?)
- Cannot isolate QR results per phase (plan QR should be independent from implementation QR)

Per-phase files allow independent verification cycles with clear boundaries. Each file is deleted when its phase passes QR gate.

## Plan Schema

Key fields in plan.json:

- milestones[].documentation.function_blocks[] (Tier 2 function-level rationale)
- milestones[].documentation.inline_comments[] (Tier 1 WHY comments)
- readme_entries[] (cross-cutting architecture spanning milestones)
