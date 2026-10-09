"""Shared string builders for planner output.

Constants for static text, functions for parameterized output.
"""


THINKING_EFFICIENCY = (
    "THINKING EFFICIENCY:\n"
    "  Max 5 words per step. Symbolic notation preferred.\n"
    "  -> for implies | for alternatives ; for sequence\n"
    '  Example: "QR failed -> route step 8 | iteration++"'
)

PEDANTIC_ENFORCEMENT = (
    "QR exists to catch problems BEFORE they reach production.\n"
    "ALL issues must be fixed before proceeding."
)

SCRIPT_MODE_RULES = (
    "SCRIPT-MODE DISPATCH RULES:\n"
    "\n"
    "Your Task prompt contains ONLY the exact invoke command.\n"
    "\n"
    "FORBIDDEN in Task prompt:\n"
    "  - Task descriptions or summaries\n"
    "  - Goals or objectives\n"
    "  - Context from conversation\n"
    "  - Explanations of what the sub-agent should do\n"
    "  - Environment variables or STATE_DIR values\n"
    "\n"
    "The script tells the sub-agent what to do. You just invoke it."
)


# --- Lessons from executed plans, shared by planning, review and implementation text ---

# "Nothing like X remains" was once checked with a regex sweep, and three rounds in
# a row each missed a form the previous pattern could not see.
ABSENCE_INVENTORY_RULE = (
    "ABSENCE CRITERIA ('no X remains', 'grep returns nothing'): back each with an\n"
    "INVENTORY, not one pattern. Enumerate EVERY candidate occurrence (every string\n"
    "literal, call site or file of the kind) and classify each as removed, kept (with\n"
    "the reason) or out of scope -- or back it with a test that FAILS when a new\n"
    "occurrence appears. A single regex proves only that one spelling is gone."
)

# A data-loss bug appeared only in a multi-step sequence on the live system:
# save a short answer -> lengthen it past a new limit -> save -> reload, and the
# earlier saved value was gone.
LIVE_SEQUENCE_RULE = (
    "DATA-CHANGING MILESTONES (anything that changes how data is saved, edited,\n"
    "limited, validated or deleted) need, in live_checks, at least one MULTI-STEP\n"
    "sequence -- create/save -> change -> save -> reload -> verify the EARLIER state\n"
    "is intact -- plus an undo/clear path. A single save-and-look check cannot see\n"
    "a later edit erasing an earlier value."
)

# Remote checks that copy a script onto the machine need a file-write permission
# and leave residue; code passed inline needs neither.
REMOTE_INLINE_RULE = (
    "REMOTE CHECKS: for a read-only check on a remote machine, pass the code INLINE\n"
    "(e.g. docker exec <container> <runtime> -e '...' through the cloud CLI's\n"
    "run-command) instead of writing or copying a script onto the machine. Do not run\n"
    "any command that writes files remotely when an inline form exists."
)

# Developers report the evidence behind an absence claim.
INVENTORY_REPORT_RULE = (
    "When an acceptance criterion says something no longer exists or must never\n"
    "appear, enumerate every candidate (not one regex) and report the counts:\n"
    "  INVENTORY: <criterion> -- <N> candidates; <a> removed, <b> kept (reason), <c> out of scope"
)


def format_forbidden(*items: str) -> str:
    """Forbidden block. Dynamic args because each gate has different items."""
    lines = "\n".join(f"  - {item}" for item in items)
    return f"FORBIDDEN:\n{lines}"


def format_gate_result(passed: bool) -> str:
    """Gate result banner.

    WHY no iteration count: Prevents LLM from rationalizing "small enough"
    issues after multiple fix cycles. Only pass/fail state matters.
    """
    return "GATE RESULT: PASS" if passed else "GATE RESULT: FAIL"
