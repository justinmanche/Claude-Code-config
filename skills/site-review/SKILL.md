---
name: site-review
description: Exhaustive end-to-end browser test-fix-retest loop. Drives the live app as EVERY role, enumerates and tests EVERY UI action with positive AND negative inputs, fixes every confirmed issue (with tests), re-tests, and repeats until a fresh full sweep finds nothing. Leaves no artifacts. Invoke when the user wants to exhaustively test, QA, harden, validate end-to-end, or "test everything and fix it" in the browser.
---

# Site Review — Exhaustive Test / Fix / Re-test

This skill does not merely audit and report. It runs a closed loop that keeps
going until the app is provably clean: enumerate every action → test each with
positive and negative inputs → fix confirmed issues (with tests) → ship →
re-test → repeat until a fresh sweep finds nothing new. All bookkeeping lives in
a `.site-review/` working directory that is deleted at the end — the only lasting
output is real source/test fixes.

When this skill activates, IMMEDIATELY invoke the script. The script IS the
workflow. At SCOPE it installs a **Stop hook** (`.claude/hooks/site-review-gate.sh`,
registered in `.claude/settings.local.json`) that physically BLOCKS the session
from ending while the Action Ledger has any unfinished row — this is what forces
the run to completion instead of stopping early. It also enforces a **mandatory
coverage matrix** every run (all roles incl. system-admin, full CRUD + lifecycle,
the malformed-input/abuse matrix, cross-tenant IDOR, the admin panel, concurrency,
per-role UI). CLEANUP removes the gate's settings registration and the ledger
(the inert gate script file stays — the session's hook snapshot keeps invoking
its path, so deleting it causes stop-hook errors). To abort a run deliberately,
create the file `.site-review/ABORT` (the gate then lets the session stop).

## Method integrity — non-negotiable (re-read this section before EVERY loop iteration)

This loop is **method-constrained, not outcome-constrained**. Over a long run the
concrete method drifts while the abstract goal ("find bugs") persists — so
re-anchor on these each iteration:

1. **Drive the LIVE APP in a browser.** TEST must exercise each ledger row by
   actually performing it in the running app as the specified role, with valid
   AND malformed inputs. Static code analysis is a *supplement* for the
   link/CRUD/display cross-checks **only** — it can NEVER replace browser driving.
   If you are dispatching sub-agents that only READ CODE and never open the app,
   you have drifted: STOP and run the browser TEST step.

2. **Invoke the script; don't hand-roll the loop.** Re-run
   `python3 -m skills.site_review.review --step N` and follow its output each
   phase. Do NOT substitute ad-hoc sub-agent orchestration for the script's
   phases — the script is what keeps the method honest.

3. **"Clean" = coverage-complete WITH EVIDENCE, not "an audit found nothing."**
   A sweep that did not actually drive a page/role/action in the browser cannot
   count that cell as covered. CONVERGE requires the coverage matrix exercised
   end-to-end with per-row evidence (screenshots / console / network), THEN a
   zero-finding fresh browser sweep — in that order.

4. **Friction is a STOP-AND-SURFACE signal, never an off-ramp to code review.**
   If browser automation is blocked (login/1Password overlay, account lockout,
   missing role credentials, session loss), retry; if still blocked, STOP and
   tell the user how to unblock it. Do NOT silently fall back to reading code —
   that is the exact failure this section exists to prevent.

5. **Every role, provisioned for real** — unauthenticated, each customer role,
   each vendor role, and a WORKING system-admin. If a role's credentials are
   missing, provision them (register / invite-accept / reset a seeded DB
   password); never skip a role or audit it "from code."

## Reaching every role WITHOUT browser-switching (impersonation strategy)

To run continuously in the background, do NOT depend on juggling multiple
signed-in Chrome profiles (each `list_connected_browsers` with >1 browser forces
an interactive selection prompt, which stalls an unattended run). Instead:

- **Drive ONE authenticated session — the system-admin — and reach other roles
  by impersonating them** (User Search → open a user → Impersonate). This needs
  no credentials and no browser switch. Never call `list_connected_browsers`
  mid-run unless the single session is genuinely lost.
- **Know impersonation's permission ceiling.** It grants a fixed subset
  (`backend/src/services/AdminService.ts` → `IMPERSONATION_ALLOWED_PERMISSIONS`):
  read across all domains **plus** the vendor-side writes
  `questionnaires:respond`, `evidence:submit`, `remediation:respond`. So
  impersonation covers **every role's read/display flows and all vendor write
  flows**. It does NOT grant customer-side writes (vendor create, questionnaire
  build/send, risk/report/evidence-request management, user management) — those
  require a genuinely authenticated customer session. Cover them from a real
  customer login (once, up front), then use impersonation for everything else.
- Always **Exit impersonation** before starting the next role so sessions don't
  nest, and verify the banner + countdown appear (they also exercise F041/F091).

Invoke:

<invoke working-dir=".claude/skills/scripts" cmd="python3 -m skills.site_review.review --step 1" />

Do NOT explore, test, or map first. Run the script and follow its output. Each
step prints the next command to run; the TEST, REMEDIATE, and CONVERGE steps
loop until their exit conditions are met.
