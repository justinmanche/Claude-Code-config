# site-review/

Exhaustive end-to-end **test / fix / re-test** skill. Enumerates every UI action
across every role, tests each with positive and negative inputs, fixes confirmed
issues (with tests), re-tests, and loops until a fresh sweep is clean. Leaves no
artifacts (its `.site-review/` working dir is deleted at the end).

## Files

| File        | What                              | When to read             |
| ----------- | --------------------------------- | ------------------------ |
| `SKILL.md`  | Skill invocation                  | Using this skill         |
| `README.md` | Architecture, workflow, rationale | Understanding the design |

Python code: `scripts/skills/site_review/review.py` (orchestrator: SCOPE →
UNDERSTAND → INVENTORY → TEST → REMEDIATE → CONVERGE → CLEANUP; TEST/REMEDIATE/
CONVERGE loop), `inspect_agent.py` (per-slice browser **test executor** — drives
each assigned ledger action positive+negative, updates the ledger, appends
findings), `verify_agent.py` (verifies findings against code before fixing).

Reusable reference constants live in `review.py`: `ISSUE_CATEGORIES`,
`SAAS_PAGE_STANDARDS`, `INPUT_TESTING_MATRIX`, `INTERACTION_TESTING_PROTOCOL`,
`ACTION_LEDGER_FORMAT`, and the five **shallow-bug checks** —
`DISPLAY_INTEGRITY`, `LINK_INTEGRITY`, `PERSISTENCE_VERIFICATION`, `CRUD_MATRIX`,
`ADVERSARIAL_FIXTURES` (bundled as `SHALLOW_BUG_CHECKS`, wired into the mandatory
coverage matrix and every test agent). Edit those to tune what the review hunts
for. The shallow-bug checks exist because those classes — raw values/ids/enums
shown to users, broken deep/email links, toast-without-persistence, and missing
CRUD — repeatedly escaped happy-path passes on friendly seed data. A second
retrospective over every user-filed issue added the **experience checks**
(`EXPERIENCE_CHECKS`: `REALISTIC_TASK_JOURNEYS`, `RESILIENCE_AND_RECOVERY`,
`CAPABILITY_PARITY`, `ACTION_PRECONDITION_COHERENCE`,
`GLOBAL_AFFORDANCE_AVAILABILITY`, `VIEWPORT_MATRIX`, `THIRD_PARTY_AUTH_EDGES`)
— mandatory items 16–22 — because ~40% of real issues were UX friction surfaced
only by sustained realistic use, plus error-cascade/lockout and mobile classes.
