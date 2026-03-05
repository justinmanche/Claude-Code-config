#!/usr/bin/env python3
"""
Site Review Inspect Agent - Deep per-page inspection sub-agent.

Four-step workflow:
  1. ORIENT   - Parse assigned pages, identify types and entities
  2. BROWSE   - Navigate to each page, screenshot, observe
  3. AUDIT    - Systematically check ALL standards and ALL categories
  4. REPORT   - Output structured findings with completion checklist

Each agent receives a batch of 1-4 pages to inspect thoroughly.
The agent MUST check every SaaS page standard and every issue category
for every assigned page -- nothing may be skipped.
"""

import argparse
import sys

from skills.lib.workflow.prompts import format_step


# ============================================================================
# CONFIGURATION
# ============================================================================

MODULE_PATH = "skills.site_review.inspect_agent"
TOTAL_STEPS = 4


# ============================================================================
# SHARED PROMPTS
# ============================================================================

# Import the full checklists from the parent module so they stay in sync
from skills.site_review.review import (
    EVIDENCE_FORMAT,
    INTERACTION_TESTING_PROTOCOL,
    ISSUE_CATEGORIES,
    SAAS_PAGE_STANDARDS,
)


# ============================================================================
# MESSAGE TEMPLATES
# ============================================================================

# --- STEP 1: ORIENT --------------------------------------------------------

ORIENT_INSTRUCTIONS = (
    "ORIENT - Parse your page assignment and prepare for inspection.\n"
    "\n"
    "Your assigned pages were specified in your launching prompt.\n"
    "\n"
    "ACTIONS:\n"
    "  1. Identify your assigned pages (routes and URLs)\n"
    "  2. For each page, determine its TYPE from:\n"
    "     Dashboard, List/Table, Detail/View, Create/Edit Form,\n"
    "     Settings, Auth, Profile, Search Results, Billing,\n"
    "     Audit Log, Integrations, Onboarding/Wizard,\n"
    "     Notification Center, Reports/Analytics, Calendar,\n"
    "     Kanban Board, Import/Export, Error Page, Other\n"
    "  3. Identify which entities (from the entity model) are\n"
    "     relevant to your assigned pages\n"
    "  4. Note any auth credentials or prerequisites needed\n"
    "  5. Note any Known Issues / Exclusions to respect\n"
    "\n"
    "OUTPUT:\n"
    "```\n"
    "PAGE ASSIGNMENT:\n"
    "  Page 1: [route] - Type: [type] - Entities: [list]\n"
    "  Page 2: [route] - Type: [type] - Entities: [list]\n"
    "  Auth needed: [yes/no] - Credentials: [if applicable]\n"
    "  Exclusions: [any known issues to skip]\n"
    "```"
)

# --- STEP 2: BROWSE --------------------------------------------------------

BROWSE_INSTRUCTIONS = (
    "BROWSE - Navigate to each assigned page and observe.\n"
    "\n"
    "For EACH assigned page:\n"
    "\n"
    "  1. Navigate to the page URL in the browser\n"
    "  2. If auth required, log in first (use credentials from ORIENT)\n"
    "  3. Wait for FULL page load (all spinners/skeletons must resolve)\n"
    "  4. Take a screenshot of the fully loaded page\n"
    "  5. Scroll the FULL page length -- screenshot the bottom too\n"
    "  6. If the page has tabs, sub-nav, or collapsible sections:\n"
    "     click each one and screenshot each state\n"
    "  7. If the page has modals or dropdowns, open each and screenshot\n"
    "  8. Note all interactive elements visible on the page\n"
    "\n"
    "RECORD for each page:\n"
    "```\n"
    "PAGE: [route]\n"
    "  Load time: [fast/medium/slow]\n"
    "  Data loaded: [automatically/requires action/empty]\n"
    "  States observed: [default, tab1, tab2, modal, etc.]\n"
    "  Interactive elements:\n"
    "    - [element type]: [description] - [location on page]\n"
    "  Console errors: [any JS errors visible]\n"
    "  Network errors: [any failed API calls]\n"
    "```\n"
    "\n"
    "Take thorough notes. The AUDIT step will reference these observations."
)

# --- STEP 3: AUDIT ---------------------------------------------------------

AUDIT_INSTRUCTIONS = (
    "AUDIT - Systematically check EVERY standard and EVERY category.\n"
    "\n"
    "This is the critical step. You MUST be exhaustive.\n"
    "Do NOT skip any checklist item. Check EVERY SINGLE ONE.\n"
    "\n"
    "For EACH assigned page, complete ALL three audits:\n"
    "\n"
    "═══════════════════════════════════════════════\n"
    "AUDIT 1: SaaS PAGE STANDARDS\n"
    "═══════════════════════════════════════════════\n"
    "\n"
    "Based on the page type identified in ORIENT, check EVERY standard\n"
    "feature listed below. You MUST also check NAVIGATION and GENERAL\n"
    "standards on every page regardless of type.\n"
    "\n"
    + SAAS_PAGE_STANDARDS + "\n"
    "\n"
    "For EACH standard feature for this page's type(s):\n"
    "  - EXPECTED features: check and record PASS or FINDING\n"
    "  - COMMON features: check and record PASS, FINDING, or N/A\n"
    "  - DOMAIN-SPECIFIC: only check if applicable\n"
    "\n"
    "OUTPUT per page (MANDATORY -- do not skip any line):\n"
    "```\n"
    "STANDARDS AUDIT: [route] (Type: [type])\n"
    "\n"
    "  NAVIGATION:\n"
    "    [x] Persistent primary nav visible\n"
    "    [x] Active state for current page in nav\n"
    "    [ ] Browser tab title reflects page -- FINDING\n"
    "    ... (check EVERY navigation standard)\n"
    "\n"
    "  GENERAL:\n"
    "    [x] Page renders without broken layout\n"
    "    [ ] No empty section without message -- FINDING\n"
    "    ... (check EVERY general standard)\n"
    "\n"
    "  [PAGE TYPE] (e.g., LIST/TABLE):\n"
    "    [x] Data loads automatically\n"
    "    [ ] Column headers sortable -- FINDING\n"
    "    ... (check EVERY standard for this type)\n"
    "```\n"
    "\n"
    "═══════════════════════════════════════════════\n"
    "AUDIT 2: ISSUE CATEGORIES\n"
    "═══════════════════════════════════════════════\n"
    "\n"
    "Check EVERY issue category below against what you observed.\n"
    "For each category, actively look for the listed symptoms.\n"
    "\n"
    + ISSUE_CATEGORIES + "\n"
    "\n"
    "OUTPUT per page (MANDATORY -- check every category):\n"
    "```\n"
    "CATEGORY AUDIT: [route]\n"
    "\n"
    "  BUGS: [N findings] / [checked]\n"
    "    - [finding description if any]\n"
    "  MISSING FUNCTIONALITY: [N findings] / [checked]\n"
    "    - [finding description if any]\n"
    "  NEGATIVE PATH HANDLING: [N findings] / [checked]\n"
    "  ORPHANED ELEMENTS: [N findings] / [checked]\n"
    "  FEEDBACK AND STATUS: [N findings] / [checked]\n"
    "  FORM VALIDATION AND INPUT: [N findings] / [checked]\n"
    "  UI/UX: [N findings] / [checked]\n"
    "  ACCESSIBILITY: [N findings] / [checked]\n"
    "  DESIGN CONSISTENCY: [N findings] / [checked]\n"
    "  PERFORMANCE: [N findings] / [checked]\n"
    "  ONBOARDING QUALITY: [N findings] / [checked]\n"
    "  INFORMATION ARCHITECTURE: [N findings] / [checked]\n"
    "  SECURITY AND TRUST: [N findings] / [checked]\n"
    "  REDUNDANCY: [N findings] / [checked]\n"
    "```\n"
    "\n"
    "═══════════════════════════════════════════════\n"
    "AUDIT 3: INTERACTION TESTING\n"
    "═══════════════════════════════════════════════\n"
    "\n"
    "For entities present on your assigned pages, test CRUD operations:\n"
    "\n"
    + INTERACTION_TESTING_PROTOCOL + "\n"
    "\n"
    "If a page does not contain entity CRUD (e.g., a static dashboard),\n"
    "still test all interactive elements: buttons, links, cards, forms.\n"
    "\n"
    "RECORDING FORMAT:\n"
    "\n"
    + EVIDENCE_FORMAT + "\n"
    "\n"
    "THOROUGHNESS RULES:\n"
    "  - Do NOT skip small issues. Record EVERYTHING.\n"
    "  - Do NOT self-censor findings you think might be intentional.\n"
    "  - Take screenshots BEFORE and AFTER interactions.\n"
    "  - If a page has multiple states, check EACH.\n"
    "  - Test with different data: empty, minimal, special characters."
)

# --- STEP 4: REPORT --------------------------------------------------------

REPORT_INSTRUCTIONS = (
    "REPORT - Compile findings with completion proof.\n"
    "\n"
    "OUTPUT FORMAT (REQUIRED):\n"
    "```\n"
    "INSPECTION REPORT\n"
    "Agent: [your agent description from launch prompt]\n"
    "Pages inspected: [count]\n"
    "\n"
    "═══════════════════════════════════════════════\n"
    "FINDINGS\n"
    "═══════════════════════════════════════════════\n"
    "\n"
    "Finding 1:\n"
    "  CATEGORY: [category]\n"
    "  SEVERITY: [CRITICAL|HIGH|MEDIUM|LOW]\n"
    "  PAGE: [route]\n"
    "  ELEMENT: [specific element]\n"
    "  OBSERVATION: [factual description]\n"
    "  EVIDENCE: [screenshot ref or visual description]\n"
    "  SUGGESTION: [improvement idea]\n"
    "\n"
    "[... repeat for all findings ...]\n"
    "\n"
    "═══════════════════════════════════════════════\n"
    "COMPLETION CHECKLIST\n"
    "═══════════════════════════════════════════════\n"
    "\n"
    "Page: [route 1]\n"
    "  Standards audited:\n"
    "    [x] NAVIGATION standards (all [N] items checked)\n"
    "    [x] GENERAL standards (all [N] items checked)\n"
    "    [x] [PAGE TYPE] standards (all [N] items checked)\n"
    "  Categories audited:\n"
    "    [x] BUGS\n"
    "    [x] MISSING FUNCTIONALITY\n"
    "    [x] NEGATIVE PATH HANDLING\n"
    "    [x] ORPHANED ELEMENTS\n"
    "    [x] FEEDBACK AND STATUS\n"
    "    [x] FORM VALIDATION AND INPUT\n"
    "    [x] UI/UX\n"
    "    [x] ACCESSIBILITY\n"
    "    [x] DESIGN CONSISTENCY\n"
    "    [x] PERFORMANCE\n"
    "    [x] ONBOARDING QUALITY\n"
    "    [x] INFORMATION ARCHITECTURE\n"
    "    [x] SECURITY AND TRUST\n"
    "    [x] REDUNDANCY\n"
    "  Interactions tested:\n"
    "    [x] All buttons clicked\n"
    "    [x] All links followed\n"
    "    [x] CRUD tested for: [entity names or N/A]\n"
    "    [x] Console/network checked\n"
    "\n"
    "[... repeat for each assigned page ...]\n"
    "\n"
    "ENTITY CRUD STATUS:\n"
    "  [Entity Name]:\n"
    "    CREATE: [TESTED/MISSING/N-A] - [notes]\n"
    "    READ:   [TESTED/MISSING/N-A] - [notes]\n"
    "    UPDATE: [TESTED/MISSING/N-A] - [notes]\n"
    "    DELETE: [TESTED/MISSING/N-A] - [notes]\n"
    "\n"
    "Total findings: [N]\n"
    "  CRITICAL: [N]\n"
    "  HIGH: [N]\n"
    "  MEDIUM: [N]\n"
    "  LOW: [N]\n"
    "```\n"
    "\n"
    "IMPORTANT: The COMPLETION CHECKLIST is mandatory. It proves\n"
    "that every standard and every category was checked for every page.\n"
    "If any item is not checked, explain why.\n"
    "\n"
    "COMPLETE - Return inspection report to orchestrator."
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
    1: ("Orient", ORIENT_INSTRUCTIONS),
    2: ("Browse", BROWSE_INSTRUCTIONS),
    3: ("Audit", AUDIT_INSTRUCTIONS),
    4: ("Report", REPORT_INSTRUCTIONS),
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
    return format_step(instructions, next_cmd or "", title=f"SITE REVIEW INSPECT - {title}")


# ============================================================================
# ENTRY POINT
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Site Review Inspect - Deep per-page inspection agent",
    )
    parser.add_argument("--step", type=int, required=True)
    args = parser.parse_args()

    if args.step < 1 or args.step > TOTAL_STEPS:
        sys.exit(f"ERROR: --step must be 1-{TOTAL_STEPS}")

    print(format_output(args.step))


if __name__ == "__main__":
    main()
