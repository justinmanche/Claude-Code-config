"""Shared step engine for the single deep reviewer (lean QR).

One reviewer agent both finds and judges. It writes qr-{phase}.json with
every item already carrying a verdict (PASS or FAIL + finding), so the
orchestrator can route straight to a fixer without a verification fan-out.

WHY one reviewer instead of decompose + N verifiers: measured on the
2026-09 Risky run, the decomposer found every defect the gate caught; the
first verify pass after it re-confirmed those findings (100% FAIL on 3 of 5
waves) and added none, at ~68% of all subagent tokens. Re-verification is
kept, but only after a fix, only for failed items, and by one agent
(see orchestrator verify steps).

Steps (REVIEW_TOTAL_STEPS = 7):
  1 absorb       phase-specific: what to read, what is in scope
  2 concerns     phase-specific: top-down list of what could be wrong
  3 enumerate    phase-specific: bottom-up list of what exists
  4 investigate  shared: gather evidence against the real artifact
  5 verdicts     shared + phase severity rules: items with PASS/FAIL
  6 challenge    shared: adversarial pass over own verdicts
  7 record       shared: write qr-{phase}.json, output one word

ORCHESTRATOR CONTRACT (same as the decompose scripts it replaces):
  get_step_guidance(step, module_path, **kwargs) -> {title, actions, next}
  invoked as: python3 -m {module_path} --step N --state-dir {dir}
"""

from skills.planner.shared.resources import get_context_path, render_context_file


INVESTIGATE_PROMPT = """\
INVESTIGATE every concern (step 2) and every element (step 3) against the
REAL artifact, not against your expectation of it.

EVIDENCE RULES:
  - Open the file. Quote file:line for every claim about code.
  - Where a claim depends on runtime behaviour (a query, a permission, a
    policy, a type), find the definition that decides it: the migration,
    the policy, the enum, the route guard. Do not infer it from a name.
  - Read-only commands are allowed (git diff, grep, jq, running the test
    suite). Do NOT edit any file.
  - Trace each changed boundary one hop OUT: who calls this, what reads
    what it writes, which identity/tenant/role it runs as.

PRIORITISE the defect classes that unit tests with mocks cannot see:
  - data layer: column/table names, types and casts, enum values, NULLs
  - access control: permission guards, row-level security, tenant scope,
    which identity a query runs under (esp. writes/reads across a
    tenant or ownership boundary)
  - contracts: API schema vs handler vs client, generated code in sync
  - lifecycle: hook/effect ordering, unmount/remount, retries, idempotency
  - tests that were weakened, skipped or reshaped to pass

OUTPUT: candidate findings, each with evidence (file:line or command output)
and the concrete failure it would cause (input -> wrong result).
Also list what you checked and found sound, with the evidence."""


VERDICT_PROMPT = """\
CONVERT your investigation into verdict items.

ONE ITEM PER CHECK you actually performed:
  - FAIL: a defect with evidence. "finding" states: evidence (file:line),
    the failure it causes, and the smallest fix. One paragraph.
  - PASS: a check you performed and found sound. No finding.

Coverage matters: record PASS items for the high-risk checks too, so the
record shows what was examined, not only what broke.

FORMAT each item:
  {{"id": "qa-NNN", "scope": "<* | milestone:M-001 | file:path>",
   "check": "<what was checked, one sentence>", "status": "PASS|FAIL",
   "version": 1, "severity": "MUST|SHOULD|COULD",
   "finding": "<FAIL only>"}}

{severity_rules}

DO NOT record style preferences or speculative risks without evidence as FAIL.
An unverifiable suspicion becomes a PASS item whose check names the residual
risk, or is omitted."""


CHALLENGE_PROMPT = """\
CHALLENGE your own verdicts before recording them.

For EACH FAIL:
  [ ] Re-open the evidence. Is the cited line really what executes?
  [ ] Would it actually produce the wrong result, or is it guarded elsewhere?
  [ ] Is the severity right? MUST = wrong behaviour, data loss, security,
      or an acceptance criterion unmet. Downgrade anything less.
  Drop FAILs that do not survive. A false FAIL costs a full fix round.

For EACH high-risk area you marked PASS (data layer, access control,
contracts, lifecycle):
  [ ] Did you open the deciding definition, or assume it?
  If you assumed it: go and look now, then keep or flip the verdict.

Then ask once: "What would break in production that I have not looked at?"
If the answer names something concrete, investigate it and add an item."""


RECORD_PROMPT = """\
WRITE {state_dir}/qr-{phase}.json with the Write tool:

{{
  "phase": "{phase}",
  "iteration": 1,
  "awaiting_reverify": false,
  "items": [ /* every item from step 6, with its verdict */ ]
}}

Validate it parses:
  python3 -c "import json; d=json.load(open('{state_dir}/qr-{phase}.json')); \\
print(len(d['items']), 'items', sum(i['status']=='FAIL' for i in d['items']), 'FAIL')"

Then your ENTIRE final response is ONE WORD:
  FAIL  -- if any item has status FAIL
  PASS  -- if no item has status FAIL
No headers, no summary, no explanation. Findings live in the file."""


def dispatch_review_step(
    step: int,
    phase: str,
    module_path: str,
    phase_prompts: dict[int, str],
    state_dir: str = "",
) -> dict:
    """Route a review step to its prompt.

    phase_prompts keys: 1 (absorb), 2 (concerns), 3 (enumerate),
    5 (severity rules inserted into the verdict prompt).
    """
    state_dir_arg = f" --state-dir {state_dir}" if state_dir else ""

    def next_cmd(s: int) -> str:
        return f"python3 -m {module_path} --step {s}{state_dir_arg}"

    if step == 1:
        context_display = render_context_file(get_context_path(state_dir)) if state_dir else ""
        return {
            "title": f"Review Step 1/7: Absorb ({phase})",
            "actions": [
                f"PHASE: {phase}",
                "",
                "You are the ONLY reviewer for this gate. Nobody re-checks your PASS",
                "verdicts, so a defect you miss ships. Be thorough and adversarial.",
                "",
                phase_prompts[1],
                "",
                "PLANNING CONTEXT:",
                context_display,
                "",
                "TASK: Read and understand. Summarize in 2-3 sentences:",
                "  - What is this change trying to accomplish?",
                "  - What would 'broken' look like for a real user?",
                "",
                "DO NOT judge yet.",
            ],
            "next": next_cmd(2),
        }

    if step == 2:
        return {
            "title": f"Review Step 2/7: Concerns ({phase})",
            "actions": [
                "THINKING TOP-DOWN: what could be wrong here?",
                "",
                phase_prompts[2],
                "",
                "OUTPUT: bulleted list. Capture everything; filter later.",
            ],
            "next": next_cmd(3),
        }

    if step == 3:
        return {
            "title": f"Review Step 3/7: Enumerate ({phase})",
            "actions": [
                "THINKING BOTTOM-UP: what EXISTS that must be checked?",
                "",
                phase_prompts[3],
                "",
                "OUTPUT: structured list with IDs (DL-001, M-001, file paths).",
                "This list is your coverage checklist for step 5.",
            ],
            "next": next_cmd(4),
        }

    if step == 4:
        return {
            "title": f"Review Step 4/7: Investigate ({phase})",
            "actions": [INVESTIGATE_PROMPT],
            "next": next_cmd(5),
        }

    if step == 5:
        return {
            "title": f"Review Step 5/7: Verdicts ({phase})",
            "actions": [VERDICT_PROMPT.format(severity_rules=phase_prompts[5])],
            "next": next_cmd(6),
        }

    if step == 6:
        return {
            "title": f"Review Step 6/7: Challenge ({phase})",
            "actions": [CHALLENGE_PROMPT],
            "next": next_cmd(7),
        }

    if step == 7:
        return {
            "title": f"Review Step 7/7: Record ({phase})",
            "actions": [RECORD_PROMPT.format(state_dir=state_dir or "$STATE_DIR", phase=phase)],
            "next": "",
        }

    return {"error": f"Unknown step {step}"}
