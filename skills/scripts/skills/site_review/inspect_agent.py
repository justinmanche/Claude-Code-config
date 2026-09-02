#!/usr/bin/env python3
"""
Site Review Test Agent - Executes a slice of ledger actions in the browser.

This is NOT a passive inspector. It DRIVES each assigned action for real --
positive and negative -- compares the result against the behaviour oracle,
updates the action's row in the shared ledger, and appends findings.

Four-step workflow:
  1. ORIENT   - Parse the assigned ledger row IDs, role, and pages; log in
  2. EXERCISE - Perform each action for real, incl. the input matrix and
                negative/authz variants; screenshot before/after
  3. JUDGE    - Compare each result to the oracle; classify PASS/FAIL
  4. RECORD   - Update ledger rows and append findings; return a coverage report

The agent is assigned a coherent slice (one role + related pages/entity) so it
can hold a single session throughout.
"""

import argparse
import sys

from skills.lib.workflow.prompts import format_step

# Import the shared reference content from the orchestrator so both stay in sync.
from skills.site_review.review import (
    EVIDENCE_FORMAT,
    INPUT_TESTING_MATRIX,
    INTERACTION_TESTING_PROTOCOL,
    ISSUE_CATEGORIES,
    LEDGER_DIR,
    SAAS_PAGE_STANDARDS,
    SHALLOW_BUG_CHECKS,
    EXPERIENCE_CHECKS,
)


# ============================================================================
# CONFIGURATION
# ============================================================================

MODULE_PATH = "skills.site_review.inspect_agent"
TOTAL_STEPS = 4


# ============================================================================
# STEP 1: ORIENT
# ============================================================================

ORIENT_INSTRUCTIONS = (
    "ORIENT - Load your assigned slice and establish your session.\n"
    "\n"
    "Your launch prompt names: the ledger row IDs you own, the ROLE to act as,\n"
    "the credentials, and the pages involved. The site URL and the ledger +\n"
    f"findings file paths (under `{LEDGER_DIR}/`) are in shared context.\n"
    "\n"
    "ACTIONS:\n"
    f"  1. Read `{LEDGER_DIR}/ledger.md` and extract YOUR assigned rows (exact IDs).\n"
    "  2. For each row, note: Page, Action, Variant (positive vs which negative),\n"
    "     and the oracle expectation (from the model summary in shared context).\n"
    "  3. Open the browser and log in AS YOUR ASSIGNED ROLE (register / accept an\n"
    "     invite / use seeded creds as directed). If the slice is an\n"
    "     unauthenticated or cross-role authz slice, set up that state instead.\n"
    "  4. Confirm you are on the right site and identity before proceeding.\n"
    "\n"
    "OUTPUT:\n"
    "```\n"
    "SLICE: role=[role] rows=[A012..A039] pages=[/x, /y]\n"
    "Session: [logged in as .. / unauthenticated / role-B for authz denial]\n"
    "```"
)


# ============================================================================
# STEP 2: EXERCISE
# ============================================================================

EXERCISE_INSTRUCTIONS = (
    "EXERCISE - Perform every assigned action FOR REAL. Do not describe what\n"
    "would happen; make it happen and observe.\n"
    "\n"
    "For EACH assigned ledger row:\n"
    "  1. Navigate to the row's Page in the correct state.\n"
    "  2. Screenshot BEFORE the action.\n"
    "  3. Perform the action's Variant:\n"
    "     - POSITIVE variant: do the happy path with valid data; confirm success\n"
    "       feedback, THEN hard-reload and re-read every field — the toast is NOT\n"
    "       proof of persistence (see SHALLOW-BUG CHECKS).\n"
    "     - NEGATIVE / INPUT variant: drive the specific invalid input or edge\n"
    "       condition for this row from the matrix below; observe the response.\n"
    "     - AUTHZ variant: attempt the action as a role that should be denied,\n"
    "       incl. editing a URL id to another owner's record; confirm it is blocked.\n"
    "     - RELOAD/BACK/CONCURRENCY variants: perform the specific hazard.\n"
    "  4. Screenshot AFTER. Capture any console error and any failed network call\n"
    "     (open the network/console tools; a 4xx/5xx or JS error during a normal\n"
    "     action is itself a finding).\n"
    "  5. If performing the action reveals NEW actions not in your rows (a new\n"
    "     modal, a follow-up step), note them for RECORD to append to the ledger.\n"
    "\n"
    "INPUT TESTING MATRIX (apply the rows relevant to each field):\n"
    + INPUT_TESTING_MATRIX + "\n"
    "\n"
    "FULL CRUD / INTERACTION PROTOCOL (when your slice owns an entity's actions):\n"
    + INTERACTION_TESTING_PROTOCOL + "\n"
    "\n"
    "SHALLOW-BUG CHECKS (apply to EVERY row — these are the classes prior passes\n"
    "missed: raw values/ids/enums shown to users, broken deep-links/email links,\n"
    "toast-without-persistence, and missing CRUD; drive them with the adversarial\n"
    "fixtures named in shared context, not friendly seed data):\n"
    + SHALLOW_BUG_CHECKS + "\n"
    "\n"
    "EXPERIENCE CHECKS (journeys, resilience, parity, empty-state coherence,\n"
    "global affordances, viewports, auth edges — produce both bugs AND\n"
    "improvement-opportunity findings):\n"
    + EXPERIENCE_CHECKS + "\n"
    "\n"
    "EXPECTED-FEATURE REFERENCE (for MISSING-FUNCTIONALITY rows):\n"
    + SAAS_PAGE_STANDARDS + "\n"
    "\n"
    "AUTOMATION HYGIENE: browser flakiness (password-manager overlays intercepting\n"
    "clicks, element ref churn after re-render, transient waits) is NOT an app\n"
    "defect -- retry via refs/coordinates/JS and only record a FAIL when the APP\n"
    "misbehaves. Take your time; correctness over speed."
)


# ============================================================================
# STEP 3: JUDGE
# ============================================================================

JUDGE_INSTRUCTIONS = (
    "JUDGE - Turn observations into verdicts against the oracle.\n"
    "\n"
    "For each assigned row, decide PASS or FAIL:\n"
    "  - PASS: the app did what a correct app should (positive path worked and\n"
    "    persisted; OR the negative input was properly rejected with a clear,\n"
    "    field-adjacent message; OR the denied action was actually blocked).\n"
    "  - FAIL: wrong data, silent failure, crash/white-screen, raw error, missing\n"
    "    validation, missing feedback, broken authz, lost session on reload,\n"
    "    missing expected feature, or any symptom in the categories below.\n"
    "  - BLOCKED: you genuinely could not reach the action (missing prerequisite\n"
    "    state, needs another role to act first) -- say exactly what is needed.\n"
    "\n"
    "Check every observation against these categories -- a thing can 'work' yet\n"
    "still be wrong (wrong label, wrong count, no notification, poor a11y):\n"
    + ISSUE_CATEGORIES + "\n"
    "\n"
    "For every FAIL, prepare a finding in this format:\n"
    + EVIDENCE_FORMAT
)


# ============================================================================
# STEP 4: RECORD
# ============================================================================

RECORD_INSTRUCTIONS = (
    "RECORD - Persist verdicts to the shared ledger and findings files, then\n"
    "return a coverage report to the orchestrator.\n"
    "\n"
    f"  1. Update `{LEDGER_DIR}/ledger.md`: for each of YOUR rows, set Status to\n"
    "     PASS / FAIL / BLOCKED, add a one-line Verdict note, and link any Finding\n"
    "     IDs. Edit only your own rows (avoid clobbering other agents' rows --\n"
    "     change one row at a time by its unique ID).\n"
    f"  2. Append each FAIL to `{LEDGER_DIR}/findings.md` with a NEW sequential ID\n"
    "     (read the file first to find the highest existing Fxxx), the EVIDENCE\n"
    "     format, and STATE=OPEN.\n"
    f"  3. Append any newly-discovered actions to the ledger as UNTESTED rows.\n"
    f"  4. Save key screenshots under `{LEDGER_DIR}/` and reference them by path.\n"
    "\n"
    "RETURN to the orchestrator (concise -- the files hold the detail):\n"
    "```\n"
    "TEST SLICE REPORT\n"
    "  Rows assigned: [N]   PASS: [N]   FAIL: [N]   BLOCKED: [N]\n"
    "  New findings: [F0xx..F0yy]\n"
    "  New actions appended to ledger: [count + brief]\n"
    "  Blocked rows + what they need: [list or none]\n"
    "```\n"
    "\n"
    "COMPLETE - return the slice report."
)


# ============================================================================
# MESSAGE BUILDERS
# ============================================================================


def build_next_command(step: int) -> str | None:
    if step >= TOTAL_STEPS:
        return None
    return f"python3 -m {MODULE_PATH} --step {step + 1}"


STATIC_STEPS = {
    1: ("Orient", ORIENT_INSTRUCTIONS),
    2: ("Exercise", EXERCISE_INSTRUCTIONS),
    3: ("Judge", JUDGE_INSTRUCTIONS),
    4: ("Record", RECORD_INSTRUCTIONS),
}


def format_output(step: int) -> str:
    if step not in STATIC_STEPS:
        return f"ERROR: Invalid step {step}"
    title, instructions = STATIC_STEPS[step]
    next_cmd = build_next_command(step)
    return format_step(instructions, next_cmd or "", title=f"SITE REVIEW TEST - {title}")


def main():
    parser = argparse.ArgumentParser(
        description="Site Review Test - Executes a slice of ledger actions",
    )
    parser.add_argument("--step", type=int, required=True)
    args = parser.parse_args()

    if args.step < 1 or args.step > TOTAL_STEPS:
        sys.exit(f"ERROR: --step must be 1-{TOTAL_STEPS}")

    print(format_output(args.step))


if __name__ == "__main__":
    main()
