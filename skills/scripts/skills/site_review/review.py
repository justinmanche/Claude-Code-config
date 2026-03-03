#!/usr/bin/env python3
"""
Site Review Skill - End-to-end site quality audit.

Seven-step workflow:
  1. SCOPE       - Parse intent, identify site URL and review goals
  2. UNDERSTAND  - Dispatch Explore agents for codebase comprehension
  3. MAP         - Navigate site, catalog all accessible pages/routes
  4. INSPECT     - Deep per-page review with screenshots (2-6 iterations)
  5. CATALOG     - Write findings to structured markdown file
  6. ASSESS      - Verify findings against code, analyze, and prioritize
  7. PLAN        - Create and write remediation plan

Only INSPECT iterates based on coverage confidence. Other steps execute once.
"""

import argparse
import sys

from skills.lib.workflow.prompts import format_step, roster_dispatch


# ============================================================================
# CONFIGURATION
# ============================================================================

MODULE_PATH = "skills.site_review.review"
VERIFY_MODULE_PATH = "skills.site_review.verify_agent"
MAX_INSPECT_ITERATIONS = 6
TOTAL_STEPS = 7


# ============================================================================
# SHARED PROMPTS
# ============================================================================

ISSUE_CATEGORIES = (
    "Issue categories to check:\n"
    "\n"
    "  UI/UX:\n"
    "    Layout problems, confusing flows, poor affordances, readability,\n"
    "    unintuitive design elements, missing feedback, unclear CTAs\n"
    "\n"
    "  BUGS:\n"
    "    Broken elements, console errors, non-functional features,\n"
    "    visual glitches, incorrect data display, broken links\n"
    "\n"
    "  BEST PRACTICE:\n"
    "    Missing loading states, no error messages, poor form validation,\n"
    "    inconsistent patterns, missing empty states, no confirmation\n"
    "    dialogs for destructive actions\n"
    "\n"
    "  ACCESSIBILITY:\n"
    "    Missing alt text, poor contrast, keyboard navigation gaps,\n"
    "    focus management issues, missing ARIA labels, small touch targets\n"
    "\n"
    "  DESIGN CONSISTENCY:\n"
    "    Inconsistent spacing, typography, colors, component styles,\n"
    "    iconography, border radii, shadow usage across pages\n"
    "\n"
    "  PERFORMANCE:\n"
    "    Slow loads visible in browser, unnecessary layout shifts,\n"
    "    large unoptimized images, janky animations or transitions\n"
    "\n"
    "  REDUNDANCY:\n"
    "    Duplicate UI elements, repeated patterns that could be\n"
    "    consolidated, unnecessary complexity, features that overlap"
)

EVIDENCE_FORMAT = (
    "For EACH finding, record:\n"
    "  - CATEGORY: [from categories above]\n"
    "  - SEVERITY: CRITICAL | HIGH | MEDIUM | LOW\n"
    "  - PAGE: [route/URL where found]\n"
    "  - ELEMENT: [specific UI element or area]\n"
    "  - OBSERVATION: [what you see - factual, not judgmental]\n"
    "  - EVIDENCE: [screenshot reference or visual description]\n"
    "  - SUGGESTION: [brief improvement idea]"
)


# ============================================================================
# MESSAGE TEMPLATES
# ============================================================================

# --- STEP 1: SCOPE ---------------------------------------------------------

SCOPE_INSTRUCTIONS = (
    "PARSE project context:\n"
    "  1. What project/codebase is being reviewed?\n"
    "  2. What is the site URL? Check in order:\n"
    "     a. User's message (explicit URL)\n"
    "     b. Project CLAUDE.md or README.md (look for dev server URL,\n"
    "        Site Review section, or localhost references)\n"
    "     c. package.json scripts (dev/start commands, port numbers)\n"
    "     d. .env files (PORT, URL, HOST variables)\n"
    "     e. If not found: use AskUserQuestion to ask\n"
    "  3. Are there specific focus areas mentioned?\n"
    "  4. Is this a re-run? Check for existing site-review-findings.md\n"
    "\n"
    "CHECK for prior findings:\n"
    "  - Glob for **/site-review-findings.md in project root\n"
    "  - If found, read it and note existing findings\n"
    "  - On re-runs, instruct INSPECT to focus on:\n"
    "    * Pages not yet reviewed\n"
    "    * New issues on previously reviewed pages\n"
    "    * Deeper interaction testing\n"
    "    * Edge cases (empty states, error states, long content)\n"
    "\n"
    "DEFINE review scope:\n"
    "  - Pages/sections to prioritize\n"
    "  - Issue types to focus on (default: all categories)\n"
    "  - User flows to test (e.g., signup, checkout, settings)\n"
    "\n"
    "If URL not determinable, use AskUserQuestion:\n"
    "  question: 'What is the URL for your local dev server?'\n"
    "  header: 'Site URL'\n"
    "  options:\n"
    "    - label: 'http://localhost:3000'\n"
    "      description: 'Default for Next.js, Create React App'\n"
    "    - label: 'http://localhost:5173'\n"
    "      description: 'Default for Vite'\n"
    "    - label: 'http://localhost:8080'\n"
    "      description: 'Default for Vue CLI, webpack-dev-server'\n"
    "\n"
    "DO NOT seek user confirmation of scope. Scope is internal guidance.\n"
    "\n"
    "ADVANCE: When URL and scope defined, proceed to UNDERSTAND."
)

# --- STEP 2: UNDERSTAND ----------------------------------------------------

UNDERSTAND_DISPATCH_CONTEXT = (
    "Review scope from SCOPE step:\n"
    "- Project codebase and technology stack\n"
    "- Site URL and pages to review\n"
    "- Focus areas and user flows identified"
)

UNDERSTAND_DISPATCH_AGENTS = [
    "[Focus 1: e.g., 'UI component architecture and styling patterns']",
    "[Focus 2: e.g., 'Routing structure and page layouts']",
    "[Focus 3: e.g., 'State management and data fetching patterns']",
    "[Focus N: based on project structure and technology]",
]

UNDERSTAND_DISPATCH_GUIDANCE = (
    "DISPATCH GUIDANCE:\n"
    "\n"
    "Generate 2-4 Explore agents based on project structure:\n"
    "\n"
    "Frontend-focused project:\n"
    "  - Components and styling agent\n"
    "  - Routing and navigation agent\n"
    "  - State and data-fetching agent\n"
    "\n"
    "Full-stack project:\n"
    "  - Frontend architecture agent\n"
    "  - API and backend agent\n"
    "  - Data model and schema agent\n"
    "\n"
    "Each agent should focus on understanding code relevant\n"
    "to what you will see in the browser."
)

UNDERSTAND_PROCESSING = (
    "WAIT for Explore results.\n"
    "\n"
    "PROCESS code understanding:\n"
    "\n"
    "ARCHITECTURE:\n"
    "  - Component hierarchy and reusable components\n"
    "  - Routing structure (all routes and pages)\n"
    "  - Layout patterns and shared wrappers\n"
    "\n"
    "PATTERNS:\n"
    "  - Styling approach (CSS modules, Tailwind, styled-components, etc.)\n"
    "  - Component patterns (atomic, compound, etc.)\n"
    "  - Design system or UI library usage\n"
    "\n"
    "STATE:\n"
    "  - Data fetching patterns\n"
    "  - Loading and error state handling\n"
    "  - Form management approach\n"
    "\n"
    "This understanding informs the browser review. Keep it in context.\n"
    "\n"
    "ADVANCE: When code understanding complete, proceed to MAP."
)

# --- STEP 3: MAP -----------------------------------------------------------

MAP_INSTRUCTIONS = (
    "Navigate to the site URL identified in SCOPE.\n"
    "\n"
    "OPEN the site:\n"
    "  1. Navigate to the site URL in the browser\n"
    "  2. Wait for full page load before taking action\n"
    "  3. Take a screenshot of the landing/home page\n"
    "\n"
    "MAP the site structure:\n"
    "  1. Identify all visible navigation elements (navbar, sidebar, footer)\n"
    "  2. List all accessible pages/routes from navigation\n"
    "  3. Identify key user flows (login -> dashboard, browse -> detail, etc.)\n"
    "  4. Note any pages requiring authentication or specific state\n"
    "\n"
    "Cross-reference with code understanding:\n"
    "  - Compare visible routes with routes found in code (UNDERSTAND step)\n"
    "  - Note routes in code not accessible from navigation\n"
    "  - Note visible links that seem broken or misconfigured\n"
    "\n"
    "OUTPUT a navigation map:\n"
    "```\n"
    "SITE MAP:\n"
    "  URL: [base URL]\n"
    "  Pages Found:\n"
    "    - / (Home) - [loaded/broken]\n"
    "    - /dashboard - [status]\n"
    "    - /settings - [status]\n"
    "  User Flows:\n"
    "    - Onboarding: / -> /signup -> /onboarding -> /dashboard\n"
    "    - Settings: /dashboard -> /settings -> /settings/profile\n"
    "  Auth Required: [pages needing auth]\n"
    "  Unreachable Routes: [routes in code not in navigation]\n"
    "```\n"
    "\n"
    "PLAN inspection order based on:\n"
    "  1. User-specified priority areas (from SCOPE)\n"
    "  2. Primary user flows first\n"
    "  3. Settings and secondary pages last\n"
    "\n"
    "ADVANCE: When site map complete, proceed to INSPECT."
)

# --- STEP 4: INSPECT -------------------------------------------------------

INSPECT_INSTRUCTIONS = (
    "INSPECT pages from the navigation map.\n"
    "\n"
    "ITERATION {iteration} of {max_iter}\n"
    "\n"
    "For each page or section in this iteration:\n"
    "\n"
    "  1. NAVIGATE to the page\n"
    "  2. WAIT for full load (check for loading spinners, skeleton screens)\n"
    "  3. SCREENSHOT the fully loaded page\n"
    "  4. ANALYZE the screenshot and page state:\n"
    "\n"
    + ISSUE_CATEGORIES + "\n"
    "\n"
    "  5. CHECK browser console for errors (if accessible)\n"
    "  6. TEST interactions:\n"
    "     - Click buttons and links\n"
    "     - Fill forms with test data\n"
    "     - Test edge cases (empty states, long text, special characters)\n"
    "     - Screenshot after interactions to capture state changes\n"
    "  7. RECORD every finding, no matter how small\n"
    "\n"
    + EVIDENCE_FORMAT + "\n"
    "\n"
    "THOROUGHNESS RULES:\n"
    "  - Do NOT skip small issues. Record everything.\n"
    "  - Do NOT self-censor findings you think might be intentional.\n"
    "  - Take screenshots before AND after interactions.\n"
    "  - If a page has multiple states (tabs, modals, dropdowns), check each.\n"
    "  - Scroll the full page length, not just above the fold.\n"
    "\n"
    "COVERAGE TRACKING:\n"
    "  After inspecting pages in this iteration, assess:\n"
    "  - Pages inspected so far: [list]\n"
    "  - Pages remaining: [list]\n"
    "  - Coverage percentage: [N% of mapped pages]\n"
    "\n"
    "CONFIDENCE ASSESSMENT:\n"
    "  - CERTAIN: All mapped pages inspected, key flows tested\n"
    "  - HIGH: 80%+ pages inspected, primary flows tested\n"
    "  - MEDIUM: 50-80% pages inspected\n"
    "  - LOW: Under 50% pages inspected\n"
    "  - EXPLORING: Just starting inspection\n"
    "\n"
    "ADVANCE:\n"
    "  - confidence == certain: Proceed to CATALOG\n"
    "  - confidence != certain AND iteration < {max_iter}: Continue INSPECT\n"
    "  - iteration >= {max_iter}: Force proceed to CATALOG"
)

# --- STEP 5: CATALOG -------------------------------------------------------

CATALOG_INSTRUCTIONS = (
    "COMPILE all findings from INSPECT iterations into a structured markdown file.\n"
    "\n"
    "READ back through ALL your INSPECT outputs. Gather EVERY finding.\n"
    "Do NOT skip findings you think are minor. Record everything.\n"
    "\n"
    "WRITE the file site-review-findings.md in the project root.\n"
    "\n"
    "FILE FORMAT:\n"
    "```markdown\n"
    "# Site Review Findings\n"
    "\n"
    "**Date**: [today's date]\n"
    "**URL**: [site URL]\n"
    "**Pages Reviewed**: [count]\n"
    "**Total Findings**: [count]\n"
    "\n"
    "## Summary\n"
    "\n"
    "[2-3 sentence overview of overall site quality and main themes]\n"
    "\n"
    "## Findings by Category\n"
    "\n"
    "### UI/UX\n"
    "\n"
    "| # | Severity | Page | Element | Observation | Suggestion |\n"
    "|---|----------|------|---------|-------------|------------|\n"
    "| 1 | HIGH     | /dashboard | Header nav | ... | ... |\n"
    "\n"
    "### Bugs\n"
    "[same table format]\n"
    "\n"
    "### Best Practices\n"
    "[same table format]\n"
    "\n"
    "### Accessibility\n"
    "[same table format]\n"
    "\n"
    "### Design Consistency\n"
    "[same table format]\n"
    "\n"
    "### Performance\n"
    "[same table format]\n"
    "\n"
    "### Redundancy\n"
    "[same table format]\n"
    "\n"
    "## Pages Reviewed\n"
    "\n"
    "| Route | Status | Finding Count |\n"
    "|-------|--------|---------------|\n"
    "| /     | Reviewed | 3 |\n"
    "```\n"
    "\n"
    "RULES:\n"
    "  - Number findings sequentially across all categories (global IDs)\n"
    "  - Omit empty categories (no table if no findings)\n"
    "  - If re-run: append new findings with IDs continuing from prior file\n"
    "\n"
    "WRITE this file using the Write tool.\n"
    "After writing, read back the file to verify completeness.\n"
    "\n"
    "ADVANCE: When findings file written and verified, proceed to ASSESS."
)

# --- STEP 6: ASSESS --------------------------------------------------------

ASSESS_DISPATCH_CONTEXT = (
    "Site review findings from the CATALOG step.\n"
    "The findings are written to site-review-findings.md in the project root.\n"
    "Each agent should read this file first for full context."
)

ASSESS_DISPATCH_AGENTS = [
    "[Group 1: e.g., 'Verify UI/UX and Design Consistency findings against component code']",
    "[Group 2: e.g., 'Verify Bug and Best Practice findings against implementation code']",
    "[Group 3: e.g., 'Verify Accessibility and Performance findings against code patterns']",
]

ASSESS_DISPATCH_GUIDANCE = (
    "DISPATCH GUIDANCE:\n"
    "\n"
    "Dispatch 2-4 verification agents based on finding categories.\n"
    "\n"
    "Each agent:\n"
    "  1. Reads site-review-findings.md from project root\n"
    "  2. Searches codebase for relevant components and code\n"
    "  3. Verifies each finding is genuine (not a design choice or WIP)\n"
    "  4. Identifies the specific code responsible\n"
    "  5. Reports: CONFIRMED / DESIGN_CHOICE / FALSE_POSITIVE for each\n"
    "\n"
    "Group findings by affinity (UI together, bugs together) so each\n"
    "agent has a coherent search scope.\n"
    "\n"
    "If fewer than 6 total findings, use a single verification agent."
)

ASSESS_PROCESSING = (
    "WAIT for verification results.\n"
    "\n"
    "PROCESS verification:\n"
    "  - Remove FALSE_POSITIVE findings\n"
    "  - Note DESIGN_CHOICE items (mention in plan but lower priority)\n"
    "  - Keep all CONFIRMED findings\n"
    "\n"
    "DEEP ANALYSIS:\n"
    "\n"
    "1. ROOT CAUSE GROUPING:\n"
    "   Group findings that share the same root cause.\n"
    "   Example: 5 inconsistent button styles -> 1 root cause: no design tokens\n"
    "\n"
    "2. IMPACT ASSESSMENT:\n"
    "   For each root cause group:\n"
    "   - User impact: How many users affected? How severe?\n"
    "   - Technical debt: Does this block other improvements?\n"
    "   - Effort estimate: Quick fix / Medium / Major refactor\n"
    "\n"
    "3. PRIORITY MATRIX:\n"
    "   Score each group: impact (1-5) x effort_inverse (1-5)\n"
    "   - Quick wins: high impact, low effort (do first)\n"
    "   - Strategic: high impact, high effort (plan carefully)\n"
    "   - Incremental: low impact, low effort (batch together)\n"
    "   - Deprioritize: low impact, high effort (defer or skip)\n"
    "\n"
    "4. DEPENDENCY MAPPING:\n"
    "   Which fixes depend on others?\n"
    "   Example: Design token system must exist before button consistency fix\n"
    "\n"
    "OUTPUT: Prioritized assessment with root cause groups.\n"
    "\n"
    "ADVANCE: When assessment complete, proceed to PLAN."
)

# --- STEP 7: PLAN ----------------------------------------------------------

PLAN_INSTRUCTIONS = (
    "CREATE a remediation plan based on the ASSESS output.\n"
    "\n"
    "STRUCTURE the plan into implementation phases:\n"
    "\n"
    "Phase 1: Quick Wins (high impact, low effort)\n"
    "  - Items fixable in a single session\n"
    "  - No architectural changes required\n"
    "\n"
    "Phase 2: Foundational Improvements\n"
    "  - Changes that enable other fixes (design tokens, shared components)\n"
    "  - Infrastructure that multiple fixes depend on\n"
    "\n"
    "Phase 3: Feature-Level Fixes\n"
    "  - Page-specific or flow-specific improvements\n"
    "  - Medium-effort items building on Phase 2 foundation\n"
    "\n"
    "Phase 4: Strategic Improvements\n"
    "  - Major refactors or redesigns\n"
    "  - Items requiring significant planning\n"
    "\n"
    "For EACH item in the plan:\n"
    "  - TITLE: Clear, actionable title\n"
    "  - FINDINGS: Which finding IDs from site-review-findings.md this addresses\n"
    "  - ROOT CAUSE: The underlying code issue\n"
    "  - FILES: Specific files to modify (from code understanding)\n"
    "  - APPROACH: Brief implementation approach\n"
    "  - EFFORT: Estimated scope (S/M/L)\n"
    "  - DEPENDS ON: Prerequisites from other items (if any)\n"
    "\n"
    "WRITE the plan to site-review-plan.md in the project root.\n"
    "\n"
    "FILE FORMAT:\n"
    "```markdown\n"
    "# Site Review Remediation Plan\n"
    "\n"
    "**Date**: [today's date]\n"
    "**Based on**: site-review-findings.md\n"
    "**Total Items**: [count]\n"
    "**Phases**: 4\n"
    "\n"
    "## Overview\n"
    "\n"
    "[2-3 sentence summary of the remediation approach]\n"
    "\n"
    "## Phase 1: Quick Wins\n"
    "\n"
    "### 1.1 [Title]\n"
    "- **Findings**: #1, #5, #12\n"
    "- **Root Cause**: [description]\n"
    "- **Files**: `src/components/Button.tsx`, `src/styles/globals.css`\n"
    "- **Approach**: [implementation notes]\n"
    "- **Effort**: S\n"
    "\n"
    "## Phase 2: Foundational Improvements\n"
    "[same format per item]\n"
    "\n"
    "## Phase 3: Feature-Level Fixes\n"
    "[same format per item]\n"
    "\n"
    "## Phase 4: Strategic Improvements\n"
    "[same format per item]\n"
    "\n"
    "## Dependency Graph\n"
    "\n"
    "[Text-based dependency visualization showing item relationships]\n"
    "```\n"
    "\n"
    "WRITE this file using the Write tool.\n"
    "\n"
    "After writing, present a summary to the user:\n"
    "  - Total findings: [N]\n"
    "  - Confirmed after verification: [N]\n"
    "  - Quick wins: [N items]\n"
    "  - Findings file: site-review-findings.md\n"
    "  - Plan file: site-review-plan.md\n"
    "\n"
    "Suggest next steps:\n"
    "  - To implement Phase 1 quick wins, use the planner skill\n"
    "  - To deep-dive a specific finding, use deepthink\n"
    "  - To find more issues, re-run site-review"
)


# ============================================================================
# MESSAGE BUILDERS
# ============================================================================


def build_understand_body() -> str:
    """Build UNDERSTAND instructions with roster_dispatch().

    Dispatches Explore agents to build UI-relevant codebase comprehension.
    Reuses the codebase_analysis subagent script for structured exploration.
    """
    invoke_cmd = 'python3 -m skills.codebase_analysis.subagent --step 1'

    dispatch_text = roster_dispatch(
        agent_type="general-purpose",
        agents=UNDERSTAND_DISPATCH_AGENTS,
        command=invoke_cmd,
        shared_context=UNDERSTAND_DISPATCH_CONTEXT,
        model="haiku",
        instruction="Determine 2-4 focus areas based on the project's tech stack. "
                    "Focus on UI-relevant code: components, styles, routing, layouts. "
                    "Each agent's unique task is its focus area description. "
                    "The subagent script refers to 'your focus area' -- "
                    "the agent knows it from prompt context.",
    )

    return f"{dispatch_text}\n\n{UNDERSTAND_DISPATCH_GUIDANCE}\n\n{UNDERSTAND_PROCESSING}"


def build_assess_body() -> str:
    """Build ASSESS instructions with roster_dispatch() for verification.

    Dispatches verification agents to cross-reference browser findings
    against the codebase. Each agent verifies a group of findings.
    """
    invoke_cmd = f'python3 -m {VERIFY_MODULE_PATH} --step 1'

    dispatch_text = roster_dispatch(
        agent_type="general-purpose",
        agents=ASSESS_DISPATCH_AGENTS,
        command=invoke_cmd,
        shared_context=ASSESS_DISPATCH_CONTEXT,
        model="haiku",
        instruction="Group findings by category affinity. "
                    "Each agent verifies its assigned group against codebase code. "
                    "Agent reads site-review-findings.md first, then searches code.",
    )

    return f"{dispatch_text}\n\n{ASSESS_DISPATCH_GUIDANCE}\n\n{ASSESS_PROCESSING}"


def build_inspect_body(iteration: int) -> str:
    """Build INSPECT instructions with iteration context."""
    return INSPECT_INSTRUCTIONS.format(
        iteration=iteration,
        max_iter=MAX_INSPECT_ITERATIONS,
    )


# Pre-computed bodies (all inputs are module-level constants)
_UNDERSTAND_BODY = build_understand_body()
_ASSESS_BODY = build_assess_body()


def build_next_command(step: int, confidence: str, iteration: int) -> str | None:
    """Build the invoke command for the next step."""
    base_cmd = f'python3 -m {MODULE_PATH}'

    if step == 1:
        return f'{base_cmd} --step 2'
    if step == 2:
        return f'{base_cmd} --step 3'
    if step == 3:
        return f'{base_cmd} --step 4 --iteration 1 --confidence exploring'
    if step == 4:
        if confidence == "certain" or iteration >= MAX_INSPECT_ITERATIONS:
            return f'{base_cmd} --step 5'
        return (
            f'{base_cmd} --step 4 --iteration {iteration + 1} '
            f'--confidence {{exploring|low|medium|high|certain}}'
        )
    if step == 5:
        return f'{base_cmd} --step 6'
    if step == 6:
        return f'{base_cmd} --step 7'
    if step == 7:
        return None
    return None


# ============================================================================
# STEP DEFINITIONS
# ============================================================================

STATIC_STEPS = {
    1: ("Scope", SCOPE_INSTRUCTIONS),
    2: ("Understand", _UNDERSTAND_BODY),
    3: ("Map", MAP_INSTRUCTIONS),
    5: ("Catalog", CATALOG_INSTRUCTIONS),
    6: ("Assess", _ASSESS_BODY),
    7: ("Plan", PLAN_INSTRUCTIONS),
}


def _format_step_4(confidence: str, iteration: int) -> tuple[str, str]:
    """Dynamic formatter for INSPECT step -- handles iteration and exit logic."""
    if confidence == "certain":
        return ("Inspect Complete", "Full coverage achieved.\n\nPROCEED to CATALOG step.")
    if iteration >= MAX_INSPECT_ITERATIONS:
        return (
            "Inspect Complete",
            f"Maximum INSPECT iterations reached ({iteration}/{MAX_INSPECT_ITERATIONS}).\n\n"
            "FORCE transition to CATALOG.",
        )
    return (
        f"Inspect (Iteration {iteration} of {MAX_INSPECT_ITERATIONS})",
        build_inspect_body(iteration),
    )


DYNAMIC_STEPS = {
    4: _format_step_4,
}


# ============================================================================
# OUTPUT FORMATTING
# ============================================================================


def format_output(step: int, confidence: str, iteration: int) -> str:
    """Format output for the given step."""
    if step in STATIC_STEPS:
        title, instructions = STATIC_STEPS[step]
    elif step in DYNAMIC_STEPS:
        title, instructions = DYNAMIC_STEPS[step](confidence, iteration)
    else:
        return f"ERROR: Invalid step {step}"

    next_cmd = build_next_command(step, confidence, iteration)
    return format_step(instructions, next_cmd or "", title=f"SITE REVIEW - {title}")


# ============================================================================
# ENTRY POINT
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Site Review - End-to-end site quality audit",
        epilog="Steps: SCOPE (1) -> UNDERSTAND (2) -> MAP (3) -> INSPECT (4) -> CATALOG (5) -> ASSESS (6) -> PLAN (7)",
    )
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument(
        "--confidence",
        type=str,
        choices=["exploring", "low", "medium", "high", "certain"],
        default="exploring",
        help="Current coverage confidence (INSPECT step only)",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        default=1,
        help="Iteration count (INSPECT step only, max 6)",
    )
    args = parser.parse_args()

    if args.step < 1 or args.step > TOTAL_STEPS:
        sys.exit(f"ERROR: --step must be 1-{TOTAL_STEPS}")
    if args.iteration < 1:
        sys.exit("ERROR: --iteration must be >= 1")

    print(format_output(args.step, args.confidence, args.iteration))


if __name__ == "__main__":
    main()
