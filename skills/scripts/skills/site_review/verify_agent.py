#!/usr/bin/env python3
"""
Site Review Verify Agent - Cross-references browser findings with codebase.

Three-step workflow:
  1. PARSE    - Read findings file and identify assigned group
  2. SEARCH   - Search codebase for relevant code
  3. VERIFY   - Cross-reference each finding and classify
"""

import argparse
import sys

from skills.lib.workflow.prompts import format_step


# ============================================================================
# CONFIGURATION
# ============================================================================

MODULE_PATH = "skills.site_review.verify_agent"
TOTAL_STEPS = 3


# ============================================================================
# MESSAGE TEMPLATES
# ============================================================================

# --- STEP 1: PARSE ---------------------------------------------------------

PARSE_INSTRUCTIONS = (
    "PARSE - Read findings and identify your assigned group.\n"
    "\n"
    "Your focus group was specified in your launching prompt.\n"
    "\n"
    "ACTIONS:\n"
    "  1. Read site-review-findings.md from the project root\n"
    "  2. Identify findings matching your assigned category group\n"
    "  3. List each finding with its ID, page, element, and observation\n"
    "\n"
    "OUTPUT:\n"
    "```\n"
    "ASSIGNED FINDINGS:\n"
    "  Group: [your focus group]\n"
    "  Count: [N findings]\n"
    "  Findings:\n"
    "    - #[id]: [page] - [element] - [brief observation]\n"
    "```"
)

# --- STEP 2: SEARCH --------------------------------------------------------

SEARCH_INSTRUCTIONS = (
    "SEARCH - Find relevant code for each assigned finding.\n"
    "\n"
    "For each finding:\n"
    "  1. Identify likely component or file based on page route and element\n"
    "  2. Use Glob to find candidate files\n"
    "  3. Use Grep to search for element names, CSS classes, route handlers\n"
    "  4. Read relevant code sections\n"
    "\n"
    "SEARCH STRATEGIES:\n"
    "  - Route-based: Search for route path string to find page component\n"
    "  - Element-based: Search for component name, className, or id\n"
    "  - Style-based: Search for CSS class names visible in the finding\n"
    "  - Text-based: Search for visible text content to find the template\n"
    "\n"
    "MAP each finding to specific code:\n"
    "```\n"
    "CODE MAPPING:\n"
    "  Finding #[id]:\n"
    "    Files: [list of relevant files]\n"
    "    Code: [brief description of relevant code]\n"
    "    Confidence: HIGH | MEDIUM | LOW\n"
    "```"
)

# --- STEP 3: VERIFY --------------------------------------------------------

VERIFY_INSTRUCTIONS = (
    "VERIFY - Cross-reference each finding with code.\n"
    "\n"
    "For each finding, determine one classification:\n"
    "\n"
    "CONFIRMED:\n"
    "  - The code supports the observation\n"
    "  - The issue is genuine and fixable\n"
    "  - Note the specific code responsible\n"
    "\n"
    "DESIGN_CHOICE:\n"
    "  - The code intentionally implements this behavior\n"
    "  - Evidence: comments, config, or deliberate pattern\n"
    "  - May still warrant review but is not a bug\n"
    "\n"
    "FALSE_POSITIVE:\n"
    "  - The observation was incorrect or misleading\n"
    "  - The code actually handles this correctly\n"
    "  - Or the behavior is expected and correct\n"
    "\n"
    "OUTPUT FORMAT (REQUIRED):\n"
    "```\n"
    "VERIFICATION REPORT\n"
    "Group: [your focus group]\n"
    "\n"
    "Results:\n"
    "  Finding #[id]: CONFIRMED\n"
    "    Code: [file:line] - [brief explanation]\n"
    "    Fix hint: [what to change]\n"
    "\n"
    "  Finding #[id]: DESIGN_CHOICE\n"
    "    Evidence: [file:line] - [why intentional]\n"
    "\n"
    "  Finding #[id]: FALSE_POSITIVE\n"
    "    Reason: [why incorrect]\n"
    "\n"
    "Summary:\n"
    "  Confirmed: [N]\n"
    "  Design Choice: [N]\n"
    "  False Positive: [N]\n"
    "```\n"
    "\n"
    "COMPLETE - Return verification report to orchestrator."
)


# ============================================================================
# MESSAGE BUILDERS
# ============================================================================


def build_next_command(step: int) -> str | None:
    """Build invoke command for next step."""
    if step >= TOTAL_STEPS:
        return None
    return f"python3 -m {MODULE_PATH} --step {step + 1}"


# ============================================================================
# STEP DEFINITIONS
# ============================================================================

STATIC_STEPS = {
    1: ("Parse", PARSE_INSTRUCTIONS),
    2: ("Search", SEARCH_INSTRUCTIONS),
    3: ("Verify", VERIFY_INSTRUCTIONS),
}


# ============================================================================
# OUTPUT FORMATTING
# ============================================================================


def format_output(step: int) -> str:
    """Format output for given step."""
    if step not in STATIC_STEPS:
        return f"ERROR: Invalid step {step}"

    title, instructions = STATIC_STEPS[step]
    next_cmd = build_next_command(step)
    return format_step(instructions, next_cmd or "", title=f"SITE REVIEW VERIFY - {title}")


# ============================================================================
# ENTRY POINT
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Site Review Verify - Cross-reference findings with code",
    )
    parser.add_argument("--step", type=int, required=True)
    args = parser.parse_args()

    if args.step < 1 or args.step > TOTAL_STEPS:
        sys.exit(f"ERROR: --step must be 1-{TOTAL_STEPS}")

    print(format_output(args.step))


if __name__ == "__main__":
    main()
