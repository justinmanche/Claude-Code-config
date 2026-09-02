# Site Review Architecture

An **exhaustive end-to-end test / fix / re-test loop** for a web app, combining
static code analysis (to know what *should* happen) with dynamic browser
automation (to see what *does* happen), then fixing and re-verifying until clean.

This is a rewrite of the older "audit and report" skill. It no longer stops at a
findings/plan file — it fixes issues and proves the fixes, and it leaves no
artifacts behind.

## Workflow

```
SCOPE -> UNDERSTAND -> INVENTORY -> TEST (loop) -> REMEDIATE (loop) -> CONVERGE -> CLEANUP
```

### Phases

1. **SCOPE** — Identify URL, the ship/deploy command, and the test-runner
   commands. Enumerate **every role** and how to get a session for each. Create
   the `.site-review/` working directory (git-ignored for the run) and
   establish/extend a `/goal` so the session runs until the app is clean.

2. **UNDERSTAND** — Explore agents build the **behaviour oracle**: every route,
   every API endpoint (with the auth + validation rules each enforces), every
   entity, every role, and every lifecycle state. This is what makes
   "works-but-wrong" behaviour catchable, not just crashes.

3. **INVENTORY** — Drive the browser as **every role** and enumerate **every**
   testable action — clicks, form submits, toggles, tabs, menus, bulk actions,
   sorts, filters, uploads, downloads, state transitions, reloads, logins, and
   every reachable **negative** and **authz-denial** variant — into the **Action
   Ledger** (`.site-review/ledger.md`). Missing expected features become rows
   too. If it is not in the ledger, it will not be tested, so it over-enumerates.

4. **TEST** *(loops)* — Fan out test-executor sub-agents over slices of untested
   ledger rows (grouped by role + entity so each holds one session). Each agent
   **performs** the action for real, applies the **INPUT TESTING MATRIX**
   (valid + invalid per field type), drives the negative/authz/reload/concurrency
   variants, compares against the oracle, sets the row's verdict, and appends
   findings. Loops until every row has a verdict.

5. **REMEDIATE** *(loops)* — Verify findings against code (kill false positives),
   group by root cause, **fix in real source with tests** (per the project's
   runners), **ship** via the deploy command, then **re-test** the affected rows
   plus regression surface. New issues surfaced by fixes are first-class. Loops
   until every confirmed issue is fixed and re-tested clean.

6. **CONVERGE** — A **fresh full sweep** with new personas/data, driving the
   primary journeys end to end across roles. Any new/recurring issue → back to
   REMEDIATE. A completely clean pass → done.

7. **CLEANUP** — Delete `.site-review/`, remove the `.gitignore` line the run
   added, verify `git status` shows only intended source/test changes, and
   report the outcome **in chat** (no report files).

## Key design decisions

### Exhaustiveness via a ledger, not vibes

Coverage is a concrete artifact: one ledger row per `(role × page × action ×
variant)`. The run is complete only when zero rows are `UNTESTED`, `FAIL`, or
`FIXED-RETEST`. New actions discovered mid-run are appended immediately.

### Positive **and** negative for everything

Every input-bearing action is driven with valid *and* invalid data via the
INPUT TESTING MATRIX (empty, oversized, XSS/SQL-ish, wrong type, boundary,
duplicate, cross-owner reference, double-submit, …). A single happy-path click
is not a completed test.

### Every role, including brand-new accounts

Roles/tenants are enumerated from code and each is provisioned (register /
invite-accept / seeded). The *same* action is tested positively for roles that
should have it and as a *must-be-blocked* negative for roles that should not —
including URL-tampering to another owner's record. Cross-side flows (e.g.
requester ↔ approver, customer ↔ vendor) are driven end to end.

### It fixes, then proves the fix

REMEDIATE implements fixes autonomously (pausing only for genuine product/UX or
destructive decisions), ships them, and re-tests. CONVERGE then does an
independent full sweep to catch regressions the fixes introduced.

### No artifacts

The ledger, findings, screenshots, and notes live under `.site-review/` and are
deleted at CLEANUP. The `.gitignore` entry the run adds is removed too. The only
lasting changes are the source/test fixes.

### Forced to completion by a Stop hook (not `/goal`)

Earlier versions *referenced* `/goal` as the backstop — but `/goal` is a user
command the assistant can't invoke, so nothing actually prevented an early stop,
and the run kept pausing for re-prompts. The fix: **SCOPE installs a real Stop
hook** (`.claude/hooks/site-review-gate.sh`, registered in
`.claude/settings.local.json`) that runs on every stop attempt, greps
`.site-review/ledger.md`, and — while any row is `UNTESTED` / `FAIL` /
`FIXED-RETEST` / `BLOCKED` — **prints a `{"decision":"block",…}` JSON envelope on
stdout and exits 0**, blocking the stop and feeding back "N rows remaining, keep
going." (It signals block via stdout JSON, *not* `exit 2`: in this harness a
non-zero exit from a Stop hook is surfaced to the user as "stop hook errored"
rather than a clean block.) The session literally cannot end until the ledger is all
`PASS`. CONVERGE runs the same mechanical count so "done" is a number, not a
judgment call. CLEANUP removes the hook **registration** + ledger but leaves the
gate script file in place: Claude Code snapshots the session's hook config, so a
still-running session keeps invoking the script's path even after the settings
entry is removed — deleting the file mid-session causes a "No such file or
directory" stop-hook error on every stop. The script is inert without a ledger
(exits 0 silently). Escape hatch: create `.site-review/ABORT`.

### Mandatory coverage matrix (not discretionary)

Every run must produce ledger rows for a fixed required surface before TEST:
**every role** (each customer + vendor role, unauthenticated, **and a provisioned
system-admin** — reset a seeded system user's DB password if needed), full CRUD
per role (positive + must-be-blocked 403), every lifecycle transition incl.
illegal ones, the **input-abuse matrix** on every endpoint (malformed-UUID id →
4xx, malformed JSON body → 400, invalid enum, oversized, XSS/SQLi, duplicate,
cross-tenant ref), **cross-tenant IDOR** per id-bearing endpoint, the whole
**admin panel** incl. impersonation, concurrency, and per-role UI hiding. Both
methods are required: fast API probing for the abuse/authz/500 surface *and*
browser driving for UI/rendering/journeys. This is why run 4 will cover what
runs 1–3 only reached piecemeal.

### The five shallow-bug checks (added after a review pass leaked them)

Certain classes of user-facing defect repeatedly escaped because the pass tested
happy paths on friendly seed data, trusted success toasts, never clicked links to
their destination, and never audited CRUD completeness. These are now **mandatory
coverage items 11–15**, encoded as the `SHALLOW_BUG_CHECKS` constants in
`review.py` and applied to every ledger row by the test executor:

1. **Display integrity** — no raw option value (`option1`), UUID, or `snake_case`
   enum may ever render to a user. Provoked with adversarial data (see below),
   not the app's already-human-readable seed data.
2. **Link integrity** — statically cross-check every constructed path (client
   `navigate`/`href` **and** server-built email/notification URLs) against the
   router's route table, **and** click every link/email button to its real
   destination. A path with no route 404s in production.
3. **Persistence verification** — a success toast is *not* proof. Every mutating
   action is verified by **hard-reload and re-read of every changed field**; a
   field the form accepts but the save silently drops is a HIGH finding.
4. **CRUD-completeness matrix** — an explicit `entity × {Create, Read, Update,
   Delete/Archive, lifecycle verbs}` matrix; any create-only entity is a finding
   unless the gap is a stated decision.
5. **Adversarial fixtures** — the run **manufactures** the data that provokes
   defects (value≠label options, blank-name records, import-path records, one
   record per lifecycle state, unicode/XSS carried through) and drives every
   downstream surface with *that* data — never the friendly defaults.

A **third method** joins API-probing and browser-driving: **static cross-checks**
(route table vs constructed links; endpoint list vs UI affordances; render code
vs value-mapping) catch broken deep-links, missing CRUD, and raw-value leakage
faster than either dynamic method alone, and get their own dedicated agents.

### The experience checks (from a retrospective over every user-filed issue)

A retrospective across all issues real users lodged found that after the
shallow-bug hardening, the biggest remaining catch-gap was **UX friction found
through sustained realistic use** (~40% of real issues), plus catastrophic-state
and viewport classes. These are now **mandatory coverage items 16–22**, encoded
as the `EXPERIENCE_CHECKS` constants in `review.py`:

1. **Realistic task journeys** — one journey agent per persona completes the
   product's real jobs-to-be-done at full scale with real content (e.g. author a
   30-question questionnaire from a source document) and harvests every friction
   point: repetition burden, bad defaults, forced irrelevant choices, cramped
   inputs, prefilled-value friction, missing preview, flow dead time. These are
   improvement-opportunity findings, first-class output.
2. **Resilience & recovery** — error **blast radius** (after any error, reload
   and navigate broadly: an error that follows you across pages is CRITICAL),
   **lockout-capable settings** (require-SSO, MFA, role downgrades) each applied
   + recovery path verified, settings round-trips, error-message persistence
   (toasts must be readable/copyable), mid-flow abandonment.
3. **Capability-parity matrix** — analogous entities (questionnaires vs
   frameworks vs report templates) compared across import/AI/export/preview/
   clone/versioning; unjustified asymmetries are findings.
4. **Action-precondition coherence** — every Export/bulk/Send/Generate action
   driven in the zero/empty state (no header-only CSV downloads).
5. **Global affordance availability** — feedback/help/nav reachable in every UI
   state, including with modals and drawers open.
6. **Viewport matrix** — key pages + one journey per role at ~375px / ~768px /
   1280px+.
7. **Third-party auth edges** — SSO account-switching (no silent auto-login),
   cancel-at-IdP, expired IdP session, redirect-loop failures.

### Aggressive parallel fan-out

TEST fans out many test-executor sub-agents **simultaneously** — grouped by
role+entity for browser slices, plus dedicated static-analysis agents for the
link/CRUD/display cross-checks, plus paired agents that hold **both sides** of a
cross-side flow (customer + vendor) at once so the handoff and its notifications
are observed live. Depth and coverage are the goal; agent count scales to the
surface, not to a speed budget.

## What it looks for

The full catalogue of issue categories (bugs, missing functionality, negative-
path handling, orphaned elements, feedback/status, form validation, UI/UX,
accessibility, design consistency, performance, onboarding, information
architecture, security/authz, redundancy), the per-page **expected-feature**
standards, the **input testing matrix**, and the **CRUD/interaction protocol**
are documented in-code as the constants `ISSUE_CATEGORIES`,
`SAAS_PAGE_STANDARDS`, `INPUT_TESTING_MATRIX`, and `INTERACTION_TESTING_PROTOCOL`
in `scripts/skills/site_review/review.py`. Each action is deliberately tested
against *many* of these so a single element is probed in several ways.

## Project configuration (optional but recommended)

Add a `Site Review` section to the project's CLAUDE.md so SCOPE finds context
automatically:

```markdown
## Site Review

| Key          | Value                                                    |
| ------------ | -------------------------------------------------------- |
| URL          | https://test.example.com  (or http://localhost:3000)     |
| Ship command | ./deploy/deploy-test.sh   (or "hot reload — none")        |
| Test command | npm test --workspace=backend && npm test --workspace=... |
| Roles        | admin: a@x.com/pw ; member: m@x.com/pw ; vendor: invite  |
| Focus        | Questionnaire lifecycle, remediation flow                |
| Exclusions   | Billing (stubbed), dark mode (WIP)                       |
```

If no URL/credentials are found and cannot be created, the skill asks. Otherwise
it runs unattended to convergence.

## Files

| File        | What                                                                            |
| ----------- | ------------------------------------------------------------------------------- |
| `SKILL.md`  | Invocation                                                                      |
| `README.md` | This document                                                                   |
| Python code | `scripts/skills/site_review/review.py` (orchestrator), `inspect_agent.py` (per-slice test executor), `verify_agent.py` (code verification) |
