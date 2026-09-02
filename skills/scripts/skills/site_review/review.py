#!/usr/bin/env python3
"""
Site Review Skill - Exhaustive end-to-end test / fix / re-test loop.

This is NOT an audit-and-report tool. It drives a closed loop that keeps
going until the site is provably clean:

  1. SCOPE      - URL, roles/credentials, project; create the run ledger
                  (.site-review/), wrap the run in a /goal, promise zero artifacts
  2. UNDERSTAND - Explore the codebase: entities, ALL routes, ALL API
                  endpoints, ALL roles/permissions
  3. INVENTORY  - Drive the browser as EVERY role and enumerate EVERY
                  interactive action, in every state, into the Action Ledger
  4. TEST       - Fan out; exercise each un-tested action with the full
                  positive + negative input matrix; update the ledger; collect
                  findings. Loops until every ledger action has a verdict.
  5. REMEDIATE  - Verify findings against code, FIX confirmed issues (with
                  tests, per project convention), build/deploy, then re-test the
                  affected + regression paths. Loops until every confirmed issue
                  is fixed and re-tested clean.
  6. CONVERGE   - One fresh full sweep. Any new issue -> back to REMEDIATE.
                  Zero outstanding -> proceed.
  7. CLEANUP    - Delete .site-review/, remove its .gitignore entry, report
                  a summary IN CHAT. No files left in the repo.

TEST, REMEDIATE, and CONVERGE iterate. The exit condition for the whole run:
every action in the ledger is PASS and a fresh sweep surfaces nothing new.
"""

import argparse
import sys

from skills.lib.workflow.prompts import format_step, roster_dispatch


# ============================================================================
# CONFIGURATION
# ============================================================================

MODULE_PATH = "skills.site_review.review"
VERIFY_MODULE_PATH = "skills.site_review.verify_agent"
TEST_MODULE_PATH = "skills.site_review.inspect_agent"  # per-page test executor
MAX_TEST_ITERATIONS = 12
MAX_REMEDIATE_ITERATIONS = 12
TOTAL_STEPS = 7

# The run ledger lives here (project-root, deleted at CLEANUP). Sub-agents are
# told this path in their launch prompt so every agent reads/writes the same
# authoritative coverage record.
LEDGER_DIR = ".site-review"


# ============================================================================
# REUSABLE REFERENCE CONTENT (kept verbatim -- the value of this skill)
# ============================================================================

ISSUE_CATEGORIES = (
    "Issue categories to check (ordered by typical severity). Each bullet is a\n"
    "SYMPTOM to actively hunt for -- test every action against every relevant one:\n"
    "\n"
    "  BUGS (typically CRITICAL/HIGH):\n"
    "    - Interactive element produces no response when clicked\n"
    "    - Data displayed is clearly wrong (negative counts, wrong names, future dates on past events)\n"
    "    - Broken or missing images (alt text shown or empty image box)\n"
    "    - Link navigates to 404, blank page, or raw error\n"
    "    - Form submission silently fails (no error, no success, page unchanged)\n"
    "    - Infinite loading spinner that never resolves\n"
    "    - Modal or dialog cannot be closed (no X, Escape does nothing)\n"
    "    - Page content disappears or resets unexpectedly during interaction\n"
    "    - Duplicate rows or duplicate content rendering on the same page\n"
    "    - Count mismatch: summary shows N but list has different number of items\n"
    "    - Dropdown contains deleted or archived options that should not be selectable\n"
    "    - Double-submit: clicking submit twice creates duplicate records\n"
    "    - Browser back button shows deleted/stale record from cache\n"
    "    - Optimistic UI shows success but the change did not persist (reload reverts it)\n"
    "    - A 4xx/5xx from the API renders a raw error object or white screen\n"
    "    - React/JS runtime error in console during a normal interaction\n"
    "\n"
    "  DISPLAY INTEGRITY (typically HIGH -- hunt on EVERY render surface):\n"
    "    - A stored option VALUE ('option1', a slug) shown instead of its label ('Yes')\n"
    "    - A raw UUID / database id shown where a name/title belongs (blank-name fallback)\n"
    "    - A snake_case / SCREAMING_CASE enum ('in_progress', 'single_select') shown verbatim\n"
    "    - '[object Object]', 'undefined', 'null', 'NaN', 'Invalid Date' rendered as text\n"
    "    - A bare ISO timestamp or raw JSON shown where formatted/human text was meant\n"
    "    - An editable field whose save silently drops it (toast says saved, reload reverts)\n"
    "    - A constructed link/deep-link/email button that resolves to no route (404)\n"
    "\n"
    "  UX FRICTION (typically MEDIUM — improvement opportunities; harvest during\n"
    "  realistic task journeys, these are first-class findings not noise):\n"
    "    - Work repeated per item with no default/template/duplicate/bulk affordance\n"
    "    - A default value the majority of users must change every time\n"
    "    - A picker forcing a distinction users don't care about (choice overload)\n"
    "    - Input too small to comfortably see/edit realistic content (no auto-grow)\n"
    "    - Input pre-filled with text that must be selected-and-deleted (should be placeholder)\n"
    "    - Author->consumer artifact (questionnaire/email/report) with no preview\n"
    "    - Error toast vanishes before it can be read/screenshotted; not copyable\n"
    "    - Data-dependent action (Export, Send, bulk) enabled on empty data and\n"
    "      producing a useless result (header-only CSV, empty send)\n"
    "    - Global affordance (feedback/help/nav) unreachable while a modal/drawer is open\n"
    "    - A capability a sibling entity has (import/AI/export/preview/clone) missing here\n"
    "\n"
    "  RESILIENCE (typically CRITICAL/HIGH):\n"
    "    - An error on one action leaves OTHER pages broken (error cascade) —\n"
    "      reload + navigate elsewhere after every provoked error to check\n"
    "    - A settings change can lock the admin out with no warning or recovery path\n"
    "    - Half-written state after cancel/refresh mid-wizard or mid-OAuth\n"
    "    - Page unusable at mobile/tablet widths (nav, dialogs, tables broken)\n"
    "\n"
    "  MISSING FUNCTIONALITY (typically HIGH):\n"
    "    - Entity has no Create mechanism (no Add/New button)\n"
    "    - Entity has no Edit mechanism (no Edit button on detail or list)\n"
    "    - Entity has no Delete mechanism (no Delete option anywhere)\n"
    "    - List/table has no search or filter controls\n"
    "    - List with 10+ rows has no pagination, infinite scroll, or item count\n"
    "    - Dashboard card/metric has no click-through to detail or list\n"
    "    - Detail page has no Back button or breadcrumb\n"
    "    - Flow reaches terminal state with no next step offered\n"
    "    - API endpoint exists with no corresponding UI action\n"
    "    - Admin panel missing: reset password, activate/deactivate user, or login history\n"
    "    - No export option (CSV/Excel) on data-heavy tables\n"
    "    - No bulk actions on list page with multiple selectable items\n"
    "\n"
    "  NEGATIVE PATH HANDLING (typically HIGH -- exercise these directly):\n"
    "    - Navigating to nonexistent entity ID shows blank page instead of 404\n"
    "    - Submitting form with all required fields empty shows no error messages\n"
    "    - Submitting invalid email format shows no inline error\n"
    "    - Search with no matches shows no 'no results' message\n"
    "    - Filter matching nothing shows no empty state message\n"
    "    - Unauthorized access shows blank screen instead of access-denied or redirect\n"
    "    - Session expiry causes silent failure instead of redirect to login\n"
    "    - Deleting entity while viewing it leaves user on broken detail page\n"
    "    - Uploading unsupported file type shows no error explaining accepted formats\n"
    "    - Back button after delete shows stale data without refresh\n"
    "    - Concurrent edit in two tabs: second save silently overwrites first\n"
    "    - Refreshing after POST resubmits without warning\n"
    "    - A hard page reload mid-session logs the user out or loses state\n"
    "    - Cross-tenant / cross-role access to another owner's record is not blocked\n"
    "\n"
    "  ORPHANED ELEMENTS (typically MEDIUM/HIGH):\n"
    "    - Button with no visible label, icon, or tooltip\n"
    "    - Icon that conveys no meaning without tooltip or label\n"
    "    - Disabled element with no explanation of why disabled\n"
    "    - Empty table or list with no empty-state message\n"
    "    - Card or section containing only placeholder text or no content\n"
    "    - Menu item or tab that does nothing when clicked\n"
    "    - Form field that accepts input but never validates or saves\n"
    "    - Link styled as clickable but navigates nowhere\n"
    "    - Section heading with no content beneath it\n"
    "    - UI element completely covered by another element (z-index issue)\n"
    "\n"
    "  FEEDBACK AND STATUS (typically MEDIUM/HIGH):\n"
    "    - Async action (save, delete, send) shows no loading indicator\n"
    "    - Operation completes with no success notification\n"
    "    - File upload or import shows no progress indicator\n"
    "    - Background task has no status visible anywhere in UI\n"
    "    - Unsaved changes not indicated (no dirty state marker or nav warning)\n"
    "    - Multi-step wizard does not show current step or progress\n"
    "    - Bulk selection count not displayed\n"
    "    - Active filters not shown as visible chips or indicators\n"
    "    - Toast notifications disappear too fast to read (under 3 seconds)\n"
    "    - Success and error notifications are not visually distinguishable\n"
    "    - An event that should notify the counterparty (submit, approve, assign) fires no notification\n"
    "\n"
    "  FORM VALIDATION AND INPUT (typically MEDIUM/HIGH):\n"
    "    - Validation fires only on submit, not on field blur\n"
    "    - Error message says only 'Invalid' without explaining the rule\n"
    "    - Required fields not marked with asterisk or 'Required' label\n"
    "    - Form uses placeholder text as only field label (disappears on focus)\n"
    "    - Extremely long input (200+ chars) accepted without truncation or error\n"
    "    - Special characters (<script>, quotes) accepted and rendered unsafely\n"
    "    - Negative numbers accepted in positive-only fields\n"
    "    - Form submit button remains enabled during save (allows double-submit)\n"
    "    - Server-side validation errors not displayed inline next to field\n"
    "    - Free-text input used where dropdown/select would be appropriate\n"
    "    - No cancel/discard option to abandon form changes\n"
    "    - Leading/trailing whitespace or unicode look-alikes accepted silently\n"
    "\n"
    "  UI/UX (typically MEDIUM):\n"
    "    - Primary action (CTA) not visually prominent or hard to find\n"
    "    - Two buttons with identical labels perform different actions\n"
    "    - Click target area smaller than visible label\n"
    "    - Related actions grouped inconsistently (some in menu, some as buttons)\n"
    "    - Long option list presented without search/autocomplete\n"
    "    - Date/time picker requires mouse only (no keyboard input)\n"
    "    - Form with 10+ fields has no grouping or sections\n"
    "    - 7+ primary actions visible above the fold (cognitive overload)\n"
    "    - Acronyms or jargon used in labels without explanation\n"
    "    - Ambiguous date format (01/02/03) without locale context\n"
    "    - A control's label does not match what it actually does\n"
    "\n"
    "  ACCESSIBILITY (typically HIGH; WCAG 2.2 A/AA visual checks only):\n"
    "    Perceivable:\n"
    "    - Image conveys information but has no adjacent caption or text explanation\n"
    "    - Text is visibly hard to read due to low contrast against background\n"
    "    - Color is the SOLE indicator of state (no icon, text, or shape difference)\n"
    "    - Content at 200% browser zoom overflows, clips, or becomes inaccessible\n"
    "    - Auto-playing audio or video has no visible pause/stop/mute control\n"
    "    Operable:\n"
    "    - Interactive element cannot be reached or activated via Tab + Enter/Space\n"
    "    - Keyboard focus gets trapped (cannot Tab out of element or modal)\n"
    "    - No visible focus indicator on interactive elements during Tab navigation\n"
    "    - Focused element hidden behind sticky header, footer, or floating widget\n"
    "    - No 'Skip to main content' link as first focusable element\n"
    "    - Drag-and-drop has no single-click alternative\n"
    "    - Click/tap targets appear smaller than ~24x24 CSS pixels at 100% zoom\n"
    "    Understandable:\n"
    "    - Receiving focus on an element triggers unexpected navigation or popup\n"
    "    - Changing a checkbox/select value auto-submits without prior disclosure\n"
    "    - Navigation link order differs across pages\n"
    "    - Form error does not identify which field failed or what went wrong\n"
    "    - Form field has no visible label (only placeholder text)\n"
    "    - Multi-step form requires re-entering info from a previous step\n"
    "    - CAPTCHA has no accessible alternative (audio, magic link)\n"
    "\n"
    "  DESIGN CONSISTENCY (typically LOW/MEDIUM):\n"
    "    - Same action type uses different button styles across pages\n"
    "    - Spacing between similar components differs visibly across pages\n"
    "    - Different fonts or font sizes for identical text levels across pages\n"
    "    - Modal dialog layouts differ (title position, button order) across app\n"
    "    - Icon set is mixed (filled vs outlined) within same functional context\n"
    "    - Destructive button is red on some pages, gray on others\n"
    "    - Success toast style differs from success inline message style\n"
    "    - Date/time format differs across pages (12h vs 24h, different separators)\n"
    "    - Hardcoded currency symbol ($) that should be dynamic\n"
    "    - Hardcoded date format (MM/DD/YYYY) that assumes US locale\n"
    "\n"
    "  PERFORMANCE (typically MEDIUM):\n"
    "    - Page content shifts visibly after initial render (layout shift from async load)\n"
    "    - Images appear blurry or pixelated at display size\n"
    "    - Page not fully rendered after 3+ seconds of navigation\n"
    "    - Scrolling produces visible lag or jank\n"
    "    - Heavy table renders all rows at once (no virtualization for 1000+ rows)\n"
    "    - Auto-refresh causes visible flicker, layout shift, or scroll jump\n"
    "\n"
    "  ONBOARDING QUALITY (typically HIGH for first-run experience):\n"
    "    - First login shows blank dashboard with no guidance or getting-started prompt\n"
    "    - No product tour, onboarding checklist, or contextual help for new accounts\n"
    "    - Account setup has no step indicator showing progress\n"
    "    - Key feature not discoverable without documentation\n"
    "    - All list views empty on first use with no sample/demo data option\n"
    "    - Invitation or signup flow asks for information without explaining why\n"
    "    - Expired activation link shows raw error instead of 'request new link'\n"
    "\n"
    "  INFORMATION ARCHITECTURE (typically MEDIUM):\n"
    "    - Cannot determine location in site hierarchy from current page alone\n"
    "    - Primary navigation has 8+ top-level items visible simultaneously\n"
    "    - Feature requires 4+ clicks from main navigation to reach\n"
    "    - No global search when app has 5+ entity types\n"
    "    - Search results show mixed entity types with no grouping or labels\n"
    "    - Page heading does not match the nav label that led to this page\n"
    "    - Related entities not linked from each other's detail pages\n"
    "\n"
    "  SECURITY AND TRUST (typically CRITICAL/HIGH):\n"
    "    - Password field value visible in plaintext (no masking)\n"
    "    - Sensitive data (API keys, tokens, SSNs, card numbers) shown without masking\n"
    "    - API key or secret displayed in full without reveal toggle\n"
    "    - Session token or API key visible in URL query parameters\n"
    "    - Console errors reveal internal file paths, stack traces, or server details\n"
    "    - Source maps accessible in production (visible in DevTools Sources)\n"
    "    - External links open in same tab without warning, navigating away from app\n"
    "    - Mixed content warnings (HTTPS page loading HTTP resources)\n"
    "    - A role can reach an action or record it should not (broken access control)\n"
    "    - IDOR: editing a URL id lets one tenant read/modify another's data\n"
    "\n"
    "  REDUNDANCY (typically LOW):\n"
    "    - Same action button appears in two locations on the same page\n"
    "    - Same data field displayed twice in same view without differentiation\n"
    "    - Two navigation paths lead to identical pages\n"
    "    - Confirmation dialog shown for low-risk reversible action\n"
    "    - Two settings controls affect the same behavior"
)

INPUT_TESTING_MATRIX = (
    "INPUT TESTING MATRIX -- for EVERY input-bearing action, exercise BOTH the\n"
    "positive (happy) path and the negative paths below. One action is not\n"
    "'tested' until it has been driven with valid AND invalid input and the\n"
    "response to each observed. Choose the rows that match each field's type.\n"
    "\n"
    "  ALL FIELDS:\n"
    "    + valid, in-range value -> expect accept + success feedback + RELOAD-\n"
    "      VERIFIED persistence (re-read after hard reload; the toast is not proof)\n"
    "    - empty when required    -> expect inline 'required' error, no submit\n"
    "    - only whitespace        -> expect trim + treated as empty, not accepted\n"
    "    - 5000-char value        -> expect max-length enforcement or graceful handling\n"
    "    - leading/trailing spaces-> expect trim or explicit handling\n"
    "\n"
    "  TEXT / FREE-TEXT:\n"
    "    - <script>alert(1)</script> and \"><img src=x onerror=alert(1)> -> rendered inert, never executed\n"
    "    - SQL-ish: ' OR 1=1 --   -> stored/escaped, no server error\n"
    "    - unicode / emoji / RTL  -> stored and displayed correctly\n"
    "    - newlines in single-line field -> handled, not broken layout\n"
    "\n"
    "  EMAIL:\n"
    "    + user@example.com\n"
    "    - notanemail / user@ / @x.com / user@x -> inline format error\n"
    "    - duplicate of an existing account -> clear 'already exists' error (without leaking existence on auth)\n"
    "\n"
    "  NUMBER / CURRENCY / QUANTITY:\n"
    "    + a normal positive value\n"
    "    - abc (non-numeric)      -> rejected inline\n"
    "    - negative in positive-only field -> rejected\n"
    "    - 0 and boundary values  -> behaves per business rule\n"
    "    - very large (1e15)      -> no overflow / no NaN rendered\n"
    "    - decimals where integer expected -> rejected or rounded per rule\n"
    "\n"
    "  DATE / TIME:\n"
    "    + a valid date\n"
    "    - past date where future required (or vice versa) -> validated\n"
    "    - end date before start date -> validated\n"
    "    - impossible date (Feb 30) -> rejected\n"
    "\n"
    "  SELECT / DROPDOWN / RADIO:\n"
    "    + each selectable option in turn\n"
    "    - no selection when required -> validated\n"
    "    - archived/deleted option must NOT appear\n"
    "\n"
    "  FILE UPLOAD:\n"
    "    + an accepted type within size limit\n"
    "    - disallowed type (.exe, wrong mime) -> rejected with explanation\n"
    "    - oversized file        -> rejected with size limit shown\n"
    "    - empty / 0-byte file    -> handled\n"
    "    - file with a spoofed extension (png bytes as .pdf) -> magic-byte check\n"
    "\n"
    "  RELATIONSHIP / REFERENCE (pick another entity):\n"
    "    + a valid related entity\n"
    "    - reference a since-deleted entity -> handled, no crash\n"
    "    - reference an entity owned by another tenant/role -> blocked\n"
    "\n"
    "  AUTH / IDENTITY:\n"
    "    + correct credentials -> login\n"
    "    - wrong password        -> generic 'invalid credentials' (no user-exists leak)\n"
    "    - locked/expired/unverified account -> correct branch, not a white screen\n"
    "    - reused / tampered token, expired session -> clean redirect to login\n"
    "\n"
    "  IDEMPOTENCY / CONCURRENCY (for state-changing actions):\n"
    "    - double-click submit    -> exactly one record created\n"
    "    - re-POST via refresh     -> warned or de-duplicated\n"
    "    - same action from two tabs -> no silent overwrite / lost update\n"
    "\n"
    "Record, for each action, WHICH matrix rows were exercised and the observed\n"
    "result of each. A single happy-path click is NOT a completed test."
)

INTERACTION_TESTING_PROTOCOL = (
    "Systematic interaction testing protocol.\n"
    "\n"
    "For EVERY entity/resource visible in the UI, test the full CRUD cycle AS\n"
    "EACH ROLE that can reach it, using the INPUT TESTING MATRIX for every form:\n"
    "\n"
    "  PART A - CREATE:\n"
    "    1. Find the create/add button or link\n"
    "    2. If NO create mechanism exists, record MISSING FUNCTIONALITY\n"
    "    3. Open the create form; screenshot the empty form\n"
    "    4. Run the INPUT TESTING MATRIX: empty submit, invalid per field type,\n"
    "       oversized, special characters, THEN valid data\n"
    "    5. On valid submit: note the success feedback, THEN hard-reload and re-\n"
    "       read EVERY field you entered — a success toast is NOT proof (see\n"
    "       PERSISTENCE VERIFICATION). A field the form accepted but the save\n"
    "       dropped is a HIGH finding.\n"
    "    6. Verify the new item appears in the list view and counts update, and\n"
    "       that its name/values render as human labels, not raw values/ids\n"
    "       (see DISPLAY-INTEGRITY CHECK)\n"
    "\n"
    "  PART B - READ:\n"
    "    1. Navigate to list/table view for this entity\n"
    "    2. Does data load automatically on page load?\n"
    "    3. Click into detail view; verify all fields display correctly\n"
    "    4. Check related-entity links are present and clickable\n"
    "    5. Test search (match + no-match), filter (match + empty), sort, pagination\n"
    "    6. Reload the detail page (hard refresh) -- state and session must survive\n"
    "\n"
    "  PART C - UPDATE:\n"
    "    1. Find the edit affordance; if none, record MISSING FUNCTIONALITY\n"
    "    2. Verify the form is pre-populated with current values\n"
    "    3. Run relevant INPUT TESTING MATRIX rows, then a valid change to EVERY\n"
    "       editable field (not just one) -- some saves silently drop a subset\n"
    "    4. Verify success feedback, THEN hard-reload and re-read EVERY changed\n"
    "       field -- the toast is not proof (see PERSISTENCE VERIFICATION). An\n"
    "       editable field whose new value reverts on reload is a HIGH finding.\n"
    "    5. Test cancel/discard, and unsaved-changes warning on navigate away\n"
    "\n"
    "  PART D - DELETE:\n"
    "    1. Find the delete affordance; if none, record MISSING FUNCTIONALITY\n"
    "    2. Confirm a confirmation step exists (else BEST-PRACTICE finding)\n"
    "    3. Confirm deletion; verify removal from list + success feedback\n"
    "    4. Then hit Back / re-open the deleted record's URL -> must not show stale data or crash\n"
    "\n"
    "  PART E - NEGATIVE / AUTHZ PATHS:\n"
    "    1. Nonexistent id (/entity/99999999) -> proper 404, not blank/raw error\n"
    "    2. Just-deleted id -> handled gracefully\n"
    "    3. Access this entity's pages as a role that should NOT have access\n"
    "       (and by editing the URL id to another owner's record) -> blocked\n"
    "    4. Unauthenticated access to an authed page -> redirect to login\n"
    "    5. Server-error triggers (duplicate unique field, FK to deleted entity) -> friendly error\n"
    "\n"
    "  PART F - UI HYGIENE (every page):\n"
    "    1. Every button has visible text or an accessible tooltip/aria-label\n"
    "    2. Every table shows data or an empty-state message\n"
    "    3. Every card that LOOKS clickable IS clickable\n"
    "    4. Metric cards with counts link to the list they count\n"
    "    5. Disabled elements have a visible disabled state (and ideally a reason)\n"
    "    6. Dropdowns close on outside-click; modals close on Escape and overlay click\n"
    "    7. Form fields have real labels (not placeholder-only)\n"
    "    8. Loading states appear during async operations\n"
    "    9. A hard reload of the page keeps the user logged in and on-page\n"
    "\n"
    "  PART G - SHALLOW-BUG SWEEP (per entity, the classes prior passes missed):\n"
    "    1. DISPLAY INTEGRITY: view this entity everywhere it renders (list cell,\n"
    "       detail field, chip, dialog, diff, notification, email, export). No raw\n"
    "       option value, UUID, or snake_case enum may appear. Use the adversarial\n"
    "       records (value!=label, blank-name, imported) — not friendly seed data.\n"
    "    2. LINK INTEGRITY: click every link OUT of this entity's pages, and every\n"
    "       email/notification this entity's actions send, to its real destination.\n"
    "    3. PERSISTENCE: for every save on this entity, hard-reload and re-read;\n"
    "       the toast is not proof.\n"
    "    4. CRUD COMPLETENESS: confirm this entity has Create, Read, Update, and\n"
    "       Delete-or-Archive affordances (or an explicit reason one is absent)."
)

EVIDENCE_FORMAT = (
    "For EACH finding, record:\n"
    "  - CATEGORY: [from the issue categories]\n"
    "  - SEVERITY: CRITICAL | HIGH | MEDIUM | LOW\n"
    "  - ROLE: [which role/persona hit it]\n"
    "  - PAGE: [route/URL where found]\n"
    "  - ACTION: [the ledger action id + description being exercised]\n"
    "  - INPUT: [the matrix row / value that triggered it, if input-related]\n"
    "  - OBSERVATION: [what happened -- factual]\n"
    "  - EXPECTED: [what a correct app would have done]\n"
    "  - EVIDENCE: [screenshot ref, console/network error, or visual description]\n"
    "  - SUGGESTION: [brief fix direction]"
)

API_UI_CROSS_REFERENCE = (
    "Cross-reference API capabilities with UI coverage:\n"
    "\n"
    "Using the API endpoints and entity model from UNDERSTAND:\n"
    "  1. For EACH API endpoint, verify a corresponding UI action exists and is\n"
    "     in the Action Ledger:\n"
    "     - GET  /api/entities        -> List page action\n"
    "     - GET  /api/entities/:id     -> Detail page action\n"
    "     - POST /api/entities         -> Create form action\n"
    "     - PUT/PATCH /api/entities/:id -> Edit form action\n"
    "     - DELETE /api/entities/:id    -> Delete action\n"
    "     - special endpoints          -> corresponding UI action\n"
    "  2. Record MISSING FUNCTIONALITY for any endpoint with no UI action.\n"
    "  3. For each endpoint, also confirm its NEGATIVE responses (400/401/403/404/409)\n"
    "     surface as friendly UI states, not raw errors -- add a ledger action to\n"
    "     drive each reachable negative response.\n"
    "  4. Note UI actions calling endpoints not in the API (dead code / future)."
)

SAAS_PAGE_STANDARDS = (
    "Standard features expected by page type in enterprise SaaS. During INVENTORY,\n"
    "the ABSENCE of an EXPECTED feature is itself a MISSING-FUNCTIONALITY action to\n"
    "record (a row asserting it should exist). During TEST, use these to know what\n"
    "each page type ought to offer.\n"
    "Labels: EXPECTED = absence is a finding; COMMON = absence is notable;\n"
    "DOMAIN-SPECIFIC = only if applicable to this vertical.\n"
    "\n"
    "  NAVIGATION (global -- check on every page):\n"
    "    EXPECTED - Persistent primary nav visible on all authenticated pages\n"
    "    EXPECTED - Active/selected state for current page in nav\n"
    "    EXPECTED - Browser tab title reflects current page content\n"
    "    EXPECTED - Breadcrumbs on pages 2+ levels deep\n"
    "    EXPECTED - User profile/avatar in header with dropdown menu\n"
    "    EXPECTED - Global search accessible from every page\n"
    "    EXPECTED - Help or support access point (? icon, help menu)\n"
    "    COMMON  - Notification indicator with unread count badge\n"
    "    COMMON  - Keyboard shortcut for search (/ or Cmd+K)\n"
    "    COMMON  - Org/workspace switcher if multi-tenant product\n"
    "    COMMON  - Mobile-responsive navigation (hamburger/drawer)\n"
    "\n"
    "  GENERAL (all pages):\n"
    "    EXPECTED - Page renders without broken layout or clipped content\n"
    "    EXPECTED - No section visibly empty without message or loading indicator\n"
    "    EXPECTED - Interactive elements change appearance on hover and show focus ring on Tab\n"
    "    EXPECTED - Escape closes any open modal, dropdown, or flyout; modal traps focus\n"
    "    EXPECTED - All user actions produce feedback within 1 second\n"
    "    EXPECTED - Destructive actions require confirmation\n"
    "    EXPECTED - Success and error feedback visually distinguishable\n"
    "    EXPECTED - No layout shift after initial render; no clipped/overlapping text\n"
    "    EXPECTED - Functional at 1280px width without horizontal scroll\n"
    "    EXPECTED - No sensitive data visible in plaintext\n"
    "    EXPECTED - Hard reload keeps the user logged in and on-page\n"
    "\n"
    "  DASHBOARD: metric cards above fold + clickable through; >=1 chart; date-range\n"
    "    filter; loading skeleton; empty state for new accounts.\n"
    "  LIST/TABLE: auto-load; sortable headers; pagination + record count; search/\n"
    "    filter + clear + active-filter chips; row-click to detail; create button;\n"
    "    row selection + bulk actions; empty state; (COMMON) export, column toggle.\n"
    "  DETAIL/VIEW: title = entity name; Edit; Delete + confirm; breadcrumb/Back;\n"
    "    related entities as links; timestamps; nonexistent id -> 404 not blank.\n"
    "  CREATE/EDIT FORM: title distinguishes create vs edit; required markers;\n"
    "    inline validation on blur; errors adjacent to field; submit loading state;\n"
    "    cancel discards; unsaved-changes warning; success feedback.\n"
    "  USER MGMT (admin): list + search/filter; view; edit role; reset password;\n"
    "    activate/deactivate/suspend; invite flow; (COMMON) resend invite, impersonate.\n"
    "  SETTINGS: save + confirmation; sectioned; descriptions; danger zone separated.\n"
    "  AUTH: email/password; forgot-password; strength meter on set; show/hide toggle;\n"
    "    generic invalid-credentials error; redirect after login; logout everywhere;\n"
    "    reset shows generic success regardless of email existence.\n"
    "  ONBOARDING/WIZARD: step indicator; per-step heading; next/back; skip optional;\n"
    "    confirmation before submit; progress persists on abandon.\n"
    "  NOTIFICATION CENTER: reachable every page; unread badge; reverse-chron list;\n"
    "    actor/action/target/time per item; mark read + mark all; click navigates.\n"
    "  REPORTS/ANALYTICS: catalog; create; date-range; export; last-refreshed.\n"
    "  PROFILE/ACCOUNT: editable name/email; avatar; change password; MFA; email prefs.\n"
    "  SEARCH RESULTS: editable query; total count; grouped by type; highlighted terms;\n"
    "    empty state with suggestions; result click navigates.\n"
    "  APPROVAL WORKFLOW: submit-for-approval; pending distinct from draft/approved;\n"
    "    approve/reject + comment; rejection requires reason; approval history on record.\n"
    "  ERROR PAGES: branded 404 with nav home; 403 with explanation; 500 with apology\n"
    "    + support reference id; session-expired with re-login CTA.\n"
    "  IMPORT/EXPORT: file upload; field mapping; validation with error rows; result\n"
    "    summary (imported/failed/skipped); (COMMON) template download, dup handling.\n"
    "  Also applicable if present: BILLING, AUDIT LOG, INTEGRATIONS/WEBHOOKS,\n"
    "  ORG/TEAM MGMT, CALENDAR, KANBAN, HELP CENTER -- check their standard controls."
)


# ============================================================================
# NEW REFERENCE CONTENT
# ============================================================================

# ----------------------------------------------------------------------------
# The five "shallow-bug" checks. These encode classes of defect that repeatedly
# escaped past review passes because the pass tested happy paths on friendly seed
# data, trusted success toasts, never clicked links to their destination, and
# never audited CRUD completeness. Each is MANDATORY, not discretionary.
# ----------------------------------------------------------------------------

DISPLAY_INTEGRITY = (
    "DISPLAY-INTEGRITY CHECK — no raw machine value may ever reach a user's eyes.\n"
    "This class hides on happy paths because friendly seed data is already human-\n"
    "readable; it only appears with real/imported/edge data. On EVERY page, in\n"
    "EVERY list cell, detail field, chip, dialog, diff, tooltip, notification, and\n"
    "email, actively hunt for:\n"
    "  - A stored OPTION VALUE shown instead of its label — e.g. 'option1',\n"
    "    'opt_3', a slug — where a human label ('Yes', 'Partial') was meant. Any\n"
    "    select/multi-select answer, status, or enum rendered as its wire value.\n"
    "  - A raw UUID / database id shown as if it were a name — e.g. a question,\n"
    "    entity, or row that falls back to its id when a title is blank. To a user\n"
    "    this reads as 'some sort of code'. Empty-name fallbacks MUST render a\n"
    "    friendly placeholder ('Untitled …'), never the id.\n"
    "  - A snake_case / SCREAMING_CASE enum shown verbatim — 'in_progress',\n"
    "    'single_select', 'NEEDS_REVIEW' — instead of humanized text.\n"
    "  - '[object Object]', 'undefined', 'null', 'NaN', 'Invalid Date', a bare\n"
    "    ISO timestamp, or JSON rendered into visible text.\n"
    "  - A machine key in a URL the user is expected to read/share.\n"
    "  To PROVOKE this class (do not wait for it): seed at least one record whose\n"
    "  option values differ from their labels, one entity/question with a BLANK\n"
    "  name/prompt, and one AI-/file-imported record — then view every surface that\n"
    "  renders them (list, detail, review, diff, request-changes, export, email).\n"
    "  Finding = any raw value/id/enum visible to a non-technical user."
)

LINK_INTEGRITY = (
    "LINK-INTEGRITY CHECK — every link and deep-link must resolve to a real,\n"
    "correct destination, and every link must actually be FOLLOWED. Broken links\n"
    "hide because reviews read the button, not the page it lands on.\n"
    "  STATIC (fast, do first): enumerate EVERY client-side navigation target\n"
    "    (navigate(...), href, <Route> `to`, window.location) AND EVERY URL built\n"
    "    server-side (email templates, notification links, redirects — grep the\n"
    "    backend for the frontend base URL). Cross-check each path against the\n"
    "    router's actual route table. A constructed path with no matching route\n"
    "    (e.g. /questionnaires/templates/:id when only /questionnaires/builder/:id\n"
    "    exists) is a HIGH finding — it 404s in production.\n"
    "  DYNAMIC (must do, not optional): CLICK every one to its destination —\n"
    "    every nav item, breadcrumb, metric-card click-through, row link, related-\n"
    "    entity link, notification-center item, AND every button inside every\n"
    "    transactional EMAIL (open the mail viewer / Mailpit, copy the link,\n"
    "    load it). Landing on a 404, a blank page, a login loop, or the wrong\n"
    "    record is a finding. Email/verification/invite/reminder/approval links\n"
    "    are the highest-risk because no happy-path UI click ever exercises them."
)

PERSISTENCE_VERIFICATION = (
    "PERSISTENCE VERIFICATION — a success toast is NOT proof of success. Several\n"
    "escaped bugs SHOWED 'Saved!' while silently discarding the change. For EVERY\n"
    "mutating action (create, edit, rename, toggle, reorder, publish, delete,\n"
    "status change, settings save), the action is NOT verified until you:\n"
    "  1. Perform it and observe the success feedback; THEN\n"
    "  2. Hard-reload the page (or navigate fully away and back — not an in-memory\n"
    "     tab switch); THEN\n"
    "  3. Re-read the value from the reloaded page and confirm the change actually\n"
    "     stuck — every field you changed, not just the one the toast mentioned.\n"
    "  A change that reverts on reload, or a field that the form lets you edit but\n"
    "  the save silently drops (e.g. an editable name/description the publish call\n"
    "  never sends), is a HIGH finding — doubly so because the UI CLAIMED success.\n"
    "  Also confirm the change propagates to every OTHER surface that shows it\n"
    "  (list row, detail header, related counts, the counterparty's view)."
)

CRUD_MATRIX = (
    "CRUD-COMPLETENESS MATRIX — build and check an explicit matrix, do not eyeball\n"
    "it. Rows = every user-facing entity (from the entity model in UNDERSTAND).\n"
    "Columns = Create, Read/List, Update/Edit, Delete-or-Archive, plus any domain\n"
    "lifecycle verbs (Publish, Send, Approve, Clone, Restore). For EACH cell:\n"
    "  - Is there a UI affordance AND a backend endpoint? A backend endpoint with\n"
    "    no UI is MISSING FUNCTIONALITY; a UI control with no endpoint is dead.\n"
    "  - If a cell is deliberately absent (e.g. immutable audit records), say so\n"
    "    explicitly — a blank must be a decision, never an oversight.\n"
    "  The lesson: entities shipped Create-only for a long time (vendors could not\n"
    "  be edited or deleted; templates could not be deleted or renamed) precisely\n"
    "  because nobody checked completeness as a matrix. Any entity a user can\n"
    "  create but cannot then edit OR remove is a HIGH finding. Write the finished\n"
    "  matrix into the ledger as one row per (entity × operation)."
)

ADVERSARIAL_FIXTURES = (
    "ADVERSARIAL FIXTURES — the review must MANUFACTURE the data that provokes\n"
    "defects; it must not rely on the app's friendly seed data, which is exactly\n"
    "why prior passes stayed green. During SCOPE/UNDERSTAND, before TEST, create\n"
    "(via the UI where possible, else API/DB) a small adversarial dataset:\n"
    "  - a select / multi-select question whose stored option VALUES differ from\n"
    "    their labels (values 'option1..n', labels 'Yes/No/Partial/N/A'), then a\n"
    "    submitted response choosing them — to expose value-vs-label rendering;\n"
    "  - an entity/question with a BLANK name/prompt — to expose id/placeholder\n"
    "    fallbacks;\n"
    "  - a record created via each IMPORT path (AI import, file/Excel import) —\n"
    "    imported content uses canonical machine shapes real users hit but seed\n"
    "    data does not;\n"
    "  - one record of every lifecycle STATE (draft, sent, in-progress, submitted,\n"
    "    changes-requested, approved, rejected, archived) so every status render\n"
    "    and transition guard is reachable;\n"
    "  - free-text fields containing unicode, emoji, very long strings, and inert\n"
    "    XSS payloads, carried THROUGH the whole flow (entry → list → detail →\n"
    "    review → export → email) to see where they render wrong.\n"
    "  Drive every downstream surface with THIS data, not the defaults."
)

SHALLOW_BUG_CHECKS = (
    DISPLAY_INTEGRITY + "\n\n"
    + LINK_INTEGRITY + "\n\n"
    + PERSISTENCE_VERIFICATION + "\n\n"
    + CRUD_MATRIX + "\n\n"
    + ADVERSARIAL_FIXTURES
)


# ----------------------------------------------------------------------------
# Experience checks. A retrospective over every issue real users lodged found
# that ~40% were UX-FRICTION findings surfaced by one user doing sustained,
# realistic authoring work — a class per-action testing structurally misses —
# plus two whole-class gaps: catastrophic state (one bad settings save bricked
# every page in the tenant) and viewport coverage ("does not work well on
# mobile"). These checks close those gaps. They produce both BUGS and
# IMPROVEMENT-OPPORTUNITY findings; the latter are first-class output, not noise.
# ----------------------------------------------------------------------------

REALISTIC_TASK_JOURNEYS = (
    "REALISTIC TASK JOURNEYS — per persona, COMPLETE the product's core jobs end\n"
    "to end at REALISTIC SCALE, and harvest every friction point as a finding.\n"
    "Action-level testing exercises each control once with test data; it cannot\n"
    "feel what a real user feels doing the job for 30 minutes. Most suggestion-\n"
    "class issues real users filed came from exactly this (authoring a real\n"
    "questionnaire surfaced: fields too small for real question text, a prefilled\n"
    "value that had to be deleted every time, a required-toggle default that was\n"
    "wrong for the majority case, a forced choice between two text types nobody\n"
    "cares about, no way to reuse options across questions, no preview of what\n"
    "the counterparty sees, and a missing import for an analogous entity).\n"
    "  HOW: pick the product's 2-4 real jobs-to-be-done (e.g. 'author a complete\n"
    "  30-question security questionnaire with options and rules from a real\n"
    "  source document', 'run a full vendor assessment start to finish', 'import\n"
    "  and publish a real framework'). Do each AS the persona, at full size, with\n"
    "  REAL content (long question text, many options, many sections) — not 3\n"
    "  toy records. While working, record EVERY friction as a finding:\n"
    "    - REPETITION BURDEN: work repeated per item with no default/template/\n"
    "      duplicate/bulk affordance (count the wasted actions);\n"
    "    - BAD DEFAULTS: any default the majority of users must change every time;\n"
    "    - FORCED IRRELEVANT CHOICES: pickers demanding distinctions users don't\n"
    "      care about;\n"
    "    - CRAMPED INPUTS: fields that cannot comfortably show/edit realistic\n"
    "      content (no auto-grow/wrap; long text hidden);\n"
    "    - PREFILLED-VALUE FRICTION: inputs pre-filled with text the user must\n"
    "      select-and-delete (should be a placeholder);\n"
    "    - MISSING PREVIEW: any author->consumer artifact (questionnaire, email,\n"
    "      report, portal page) with no way to see what the consumer will see;\n"
    "    - FLOW DEAD TIME: waits, re-navigation, or lost context between steps.\n"
    "  Severity: these are IMPROVEMENT OPPORTUNITIES unless they block the job.\n"
    "  A journey that produces zero friction findings is suspicious — look harder."
)

RESILIENCE_AND_RECOVERY = (
    "RESILIENCE & RECOVERY — errors must not cascade, and no setting may brick\n"
    "the tenant without a recovery path. (Real incident: enabling 'require SSO'\n"
    "threw an error, and after it EVERY page in the app showed the same error —\n"
    "one bad settings write corrupted the whole session/tenant experience.)\n"
    "  1. BLAST RADIUS AFTER ERRORS: whenever an action errors (or you force an\n"
    "     error via the abuse matrix), do not stop at observing the message —\n"
    "     hard-reload and visit several unrelated pages to confirm the app is\n"
    "     still fully usable. An error that persists, follows you across pages,\n"
    "     or requires clearing storage to escape is CRITICAL.\n"
    "  2. LOCKOUT-CAPABLE SETTINGS: enumerate every setting that can restrict\n"
    "     access (require SSO, disable local login, MFA enforcement, IP rules,\n"
    "     role downgrades, tenant suspend). For each: apply it, verify the\n"
    "     expected restriction, then verify a RECOVERY PATH exists (another\n"
    "     admin, break-glass, support flow) and that the UI warns before locking.\n"
    "     Test the self-lockout case explicitly: can the admin lock THEMSELVES\n"
    "     out with no way back?\n"
    "  3. SETTINGS ROUND-TRIP: every security-relevant toggle is driven BOTH\n"
    "     directions with a hard-reload verification after each save, and the\n"
    "     app remains usable after each state.\n"
    "  4. ERROR FEEDBACK ERGONOMICS: error messages persist until dismissed (or\n"
    "     long enough to read and screenshot), are copyable, and carry a\n"
    "     reference id. A toast that vanishes in ~2s carrying information the\n"
    "     user needs to act on or report is a finding.\n"
    "  5. MID-FLOW ABANDONMENT: cancel/back/refresh in the middle of wizards,\n"
    "     OAuth redirects, and payment-like flows -> clean state, no half-writes."
)

CAPABILITY_PARITY = (
    "CAPABILITY-PARITY MATRIX — analogous entities should offer analogous\n"
    "capabilities; asymmetries are findings (users filed 'frameworks should have\n"
    "AI import like questionnaires do' — predictable from the matrix). Build it:\n"
    "rows = the product's authorable/managed entities (e.g. questionnaires,\n"
    "frameworks, report templates); columns = capabilities any of them has\n"
    "(create, import-file, import-AI, export, preview, clone, versioning/diff,\n"
    "archive, bulk actions, search/filter, templates/defaults). For every cell\n"
    "where a SIBLING entity has the capability and this one lacks it, record a\n"
    "MISSING-FUNCTIONALITY or IMPROVEMENT finding unless the asymmetry is\n"
    "obviously justified. Write the matrix into the ledger."
)

ACTION_PRECONDITION_COHERENCE = (
    "ACTION-PRECONDITION COHERENCE — for EVERY action whose usefulness depends\n"
    "on data being present (Export CSV, bulk actions, Send, Generate, Compare,\n"
    "print), drive it in the ZERO/EMPTY state: empty list, empty filter result,\n"
    "brand-new tenant. The control must be disabled (with a visible reason) or\n"
    "handle the empty case gracefully. (Real issue: Export CSV on an empty\n"
    "vendor list happily downloaded a header-only file — 'looks broken'.)\n"
    "Also the inverse of the disabled-state check: anything ENABLED must do\n"
    "something sensible right now."
)

GLOBAL_AFFORDANCE_AVAILABILITY = (
    "GLOBAL AFFORDANCE AVAILABILITY — the app's ambient affordances (feedback/\n"
    "bug-report widget, help, nav, notifications, search) must remain reachable\n"
    "in EVERY UI state: with each modal open, with side drawers open, during\n"
    "wizards, in full-screen editors, on error pages. (Real issue: the feedback\n"
    "widget was unreachable while a dialog was open — precisely when the user\n"
    "had a bug to report.) Check z-order/occlusion state by state."
)

VIEWPORT_MATRIX = (
    "VIEWPORT MATRIX — drive the key pages and at least one end-to-end journey\n"
    "per role at THREE widths: mobile ~375px, tablet ~768px, desktop 1280px+\n"
    "(resize the browser window/viewport). At each width check: no horizontal\n"
    "scroll, nav usable (drawer/hamburger works), tables adapt or scroll within\n"
    "their container, dialogs fit and their buttons are reachable, forms usable,\n"
    "touch targets not overlapping. ('The site does not work well on mobile' was\n"
    "a real filed issue; desktop-only sweeps structurally cannot catch it.)"
)

THIRD_PARTY_AUTH_EDGES = (
    "THIRD-PARTY AUTH EDGES — for each external identity flow (Microsoft/Google\n"
    "SSO, OIDC/SAML): fresh login; RE-login when already IdP-authenticated (can\n"
    "the user pick a DIFFERENT account, or are they silently auto-logged-in? —\n"
    "real issue: no account selection prompt); cancel at the IdP mid-flow;\n"
    "expired IdP session; logout then login as another account; IdP-side\n"
    "failure -> friendly error, not a stuck redirect loop."
)

EXPERIENCE_CHECKS = (
    REALISTIC_TASK_JOURNEYS + "\n\n"
    + RESILIENCE_AND_RECOVERY + "\n\n"
    + CAPABILITY_PARITY + "\n\n"
    + ACTION_PRECONDITION_COHERENCE + "\n\n"
    + GLOBAL_AFFORDANCE_AVAILABILITY + "\n\n"
    + VIEWPORT_MATRIX + "\n\n"
    + THIRD_PARTY_AUTH_EDGES
)


ACTION_LEDGER_FORMAT = (
    "THE ACTION LEDGER is the authoritative, exhaustive record of every testable\n"
    "action in the app and its current verdict. It is a Markdown table at\n"
    f"`{LEDGER_DIR}/ledger.md`. Nothing is 'done' until every row is PASS.\n"
    "\n"
    "One row per (role x page x action x variant). 'Action' means anything a\n"
    "user can DO: click a button/link/tab/menu-item, submit a form, toggle a\n"
    "control, open/close a modal, select a row, run a bulk action, drag, sort,\n"
    "filter, paginate, upload, download, navigate via URL, reload, log in/out,\n"
    "switch role/tenant, and every REACHABLE negative variant of the above.\n"
    "\n"
    "```markdown\n"
    "# Action Ledger\n"
    "\n"
    "Base URL: <url>   Generated: <iso date passed in>   Roles: <list>\n"
    "\n"
    "| ID | Role | Page | Action | Variant | Status | Verdict notes | Finding IDs |\n"
    "|----|------|------|--------|---------|--------|---------------|-------------|\n"
    "| A001 | admin | /users | Click 'Invite user' | opens dialog | UNTESTED | | |\n"
    "| A002 | admin | /users | Submit invite | +valid email | UNTESTED | | |\n"
    "| A003 | admin | /users | Submit invite | -empty email | UNTESTED | | |\n"
    "| A004 | admin | /users | Submit invite | -dupe email | UNTESTED | | |\n"
    "| A005 | viewer| /users | Open /users (authz) | should be blocked | UNTESTED | | |\n"
    "```\n"
    "\n"
    "Status values: UNTESTED | PASS | FAIL | BLOCKED (couldn't reach) | FIXED-RETEST\n"
    "(fixed, awaiting re-test) | SKIP (excluded, with reason in notes).\n"
    "\n"
    "Rules:\n"
    "  - Every discovered action gets a row BEFORE testing begins (INVENTORY),\n"
    "    and new actions discovered mid-run are appended immediately.\n"
    "  - A FAIL row links to the finding id(s) it produced.\n"
    "  - When a fix lands, flip affected rows to FIXED-RETEST so CONVERGE re-runs them.\n"
    "  - The run is complete only when zero rows are UNTESTED / FAIL / FIXED-RETEST."
)

FINDINGS_FILE_FORMAT = (
    f"Findings accumulate in `{LEDGER_DIR}/findings.md` -- an append-only log with\n"
    "stable sequential IDs (F001, F002, ...). Each entry uses the EVIDENCE format\n"
    "and carries a STATE: OPEN | CONFIRMED | FALSE_POSITIVE | DESIGN_CHOICE |\n"
    "FIXED | VERIFIED (fixed AND re-tested clean). Never renumber; only append or\n"
    "update STATE. This file is deleted at CLEANUP -- the summary goes to chat."
)

ROLE_COVERAGE = (
    "ROLE / PERSONA COVERAGE -- exhaustiveness means every role, not just admin.\n"
    "  - Enumerate EVERY distinct role/permission level and multi-tenant boundary\n"
    "    from UNDERSTAND (e.g. owner-admin, member, read-only, vendor/external,\n"
    "    unauthenticated, super-admin/impersonator).\n"
    "  - Provision or obtain a login for each (register, invite-accept, or seeded\n"
    "    credentials). A brand-new account is itself a critical test surface\n"
    "    (first-run/onboarding, empty states, permission bootstrapping).\n"
    "  - The SAME action must be tested per role: a positive test for roles that\n"
    "    SHOULD have it, and a NEGATIVE (must-be-blocked) test for roles that\n"
    "    should NOT -- including URL-tampering to another owner's record.\n"
    "  - Cross-side flows (e.g. customer<->vendor, requester<->approver) must be\n"
    "    driven end to end, switching accounts, verifying BOTH sides see the\n"
    "    correct state and notifications."
)

STOP_GATE = (
    "THE STOP GATE (this is what makes the run actually finish, not stop early).\n"
    "\n"
    "A Stop hook is the ONLY thing that reliably prevents this session from ending\n"
    "before coverage is complete. Referencing /goal does NOT work (it is a user\n"
    "command the assistant cannot invoke). So SCOPE installs a real Stop hook that\n"
    "BLOCKS stopping while the ledger has any unfinished row, and CLEANUP removes it.\n"
    "\n"
    "INSTALL IT NOW (idempotent). Write the gate script and register it in the\n"
    "project's LOCAL settings (never the committed settings.json):\n"
    "\n"
    "  1. Write `.claude/hooks/site-review-gate.sh` (mkdir -p .claude/hooks; a\n"
    "     matching script may already exist from a previous run — overwrite it with\n"
    "     the current version below) with:\n"
    "     ```sh\n"
    "     #!/usr/bin/env bash\n"
    "     # site-review completion gate — installed by the site-review skill,\n"
    "     # removed at CLEANUP. Blocks Stop while the Action Ledger is unfinished.\n"
    "     #\n"
    "     # CONTRACT: a Stop hook in this harness signals BLOCK by printing the\n"
    "     # canonical {\\\"decision\\\":\\\"block\\\",\\\"reason\\\":...} JSON on stdout and exiting\n"
    "     # 0 — NEVER by `exit 2` (a non-zero exit is surfaced to the user as \\\"stop\n"
    "     # hook errored\\\", not a clean block) and NEVER with a non-schema envelope like\n"
    "     # {\\\"ok\\\":false} (unrecognized keys are also surfaced as an error). So: exit 0\n"
    "     # with no output = allow stop; exit 0 with the block JSON = keep going.\n"
    "     set -uo pipefail\n"
    "     ROOT=\"$(git rev-parse --show-toplevel 2>/dev/null || pwd)\"\n"
    "     LEDGER=\"$ROOT/.site-review/ledger.md\"\n"
    "     [ -f \"$ROOT/.site-review/ABORT\" ] && exit 0   # user escape hatch — allow stop\n"
    "     [ -f \"$LEDGER\" ] || exit 0                     # no run in progress — allow stop\n"
    "     # Only real table rows (start with '|') — excludes the legend line; grep -c prints 0 when none match.\n"
    "     REMAINING=$(grep -E '^\\|' \"$LEDGER\" 2>/dev/null | grep -cE '\\|[[:space:]]*(UNTESTED|FAIL|FIXED-RETEST|BLOCKED)[[:space:]]*\\|' 2>/dev/null)\n"
    "     REMAINING=${REMAINING:-0}\n"
    "     [ \"$REMAINING\" -eq 0 ] 2>/dev/null && exit 0  # ledger all PASS — allow stop\n"
    "     REASON=\"SITE REVIEW INCOMPLETE — $REMAINING ledger row(s) still UNTESTED/FAIL/FIXED-RETEST/BLOCKED in .site-review/ledger.md. Do NOT stop. Continue the site-review loop: take the next unfinished rows, TEST them (positive + the full negative/abuse matrix), FIX every failure (with tests, then ship), RE-TEST, and update each row to PASS. Only when EVERY row is PASS may you run CLEANUP (which removes this gate). To abort deliberately: create the file .site-review/ABORT\"\n"
    "     # JSON-encode the reason safely (handles the em-dash and any quoting), print the\n"
    "     # block envelope on stdout, and exit 0 — this is what BLOCKS the stop.\n"
    "     REASON=\"$REASON\" python3 -c 'import json,os; r=os.environ[\"REASON\"]; print(json.dumps({\"decision\":\"block\",\"reason\":r}))'\n"
    "     exit 0\n"
    "     ```\n"
    "     Then `chmod +x .claude/hooks/site-review-gate.sh`.\n"
    "\n"
    "  2. Merge a Stop-hook entry into `.claude/settings.local.json` (create it if\n"
    "     absent; it is git-ignored and per-user). Read any existing JSON, ADD (do\n"
    "     not overwrite other hooks) under hooks.Stop an entry:\n"
    "       {\"hooks\":[{\"type\":\"command\",\n"
    "         \"command\":\"bash \\\"$(git rev-parse --show-toplevel)/.claude/hooks/site-review-gate.sh\\\"\",\n"
    "         \"timeout\":15}]}\n"
    "     Write it back with the rest of the file intact.\n"
    "\n"
    "  3. Verify: with a ledger containing an UNTESTED row, the gate prints a\n"
    "     {\"decision\":\"block\",...} JSON line and exits 0 (block); with an all-PASS or\n"
    "     absent ledger it prints nothing and exits 0 (allow). This is the mechanism\n"
    "     that forces the whole run to completion. If the gate\n"
    "     cannot be installed (no write access / non-git dir), say so explicitly and\n"
    "     fall back to driving the loop manually to completion in ONE turn.\n"
    "\n"
    "ZERO ARTIFACTS: the only files this skill leaves during the run live under\n"
    f"`{LEDGER_DIR}/` plus the gate script + settings entry above — the ledger dir\n"
    "and settings entry are removed at CLEANUP (the inert gate script stays: the\n"
    "session's hook snapshot keeps invoking its path, so deleting it mid-session\n"
    "causes a stop-hook error). Never write findings/plan/site-map files to the\n"
    "project root. Real source/test fixes are the intended lasting output."
)

MANDATORY_COVERAGE = (
    "MANDATORY COVERAGE MATRIX — every run MUST produce ledger rows for ALL of the\n"
    "following before TEST begins. This is not a menu; it is the required minimum.\n"
    "A run is not 'exhaustive' until every cell below is a PASS row. Past runs that\n"
    "stopped early skipped whole blocks (admin panel, malformed-input abuse, per-\n"
    "role authz) — those are now mandatory, not discretionary.\n"
    "\n"
    "  1. ROLES — provision AND drive EVERY role, including privileged ones:\n"
    "     - every customer role (admin, and each lesser role: manager/reviewer/\n"
    "       viewer) via invite-accept;\n"
    "     - every vendor role (admin + contributor) via invite-accept;\n"
    "     - unauthenticated;\n"
    "     - SYSTEM ADMIN — do NOT skip because 'no login'. Obtain one: try seeded\n"
    "       creds; else reset a seeded system user's password directly in the DB;\n"
    "       else create one. The admin panel is a first-class surface.\n"
    "     - a SECOND tenant of each type (for cross-tenant/IDOR tests).\n"
    "  2. EVERY entity: full CRUD as each role — POSITIVE for roles that may, and a\n"
    "     NEGATIVE must-be-blocked (403) row for roles that may not.\n"
    "  3. EVERY lifecycle transition, per role, INCLUDING illegal transitions\n"
    "     (submit-after-approve, re-send approved, resolve-unanswered, any->any).\n"
    "  4. INPUT-ABUSE MATRIX on EVERY input-bearing endpoint (drive via API too —\n"
    "     it is faster and catches the 500s the UI hides). For each: valid; empty-\n"
    "     required; MALFORMED-UUID path id (expect 4xx, a 500 is a bug); MALFORMED\n"
    "     JSON body (expect 400); invalid-enum value (expect 400); oversized (5000+\n"
    "     chars); XSS/SQLi payload; negative number in positive field; duplicate/\n"
    "     unique-violation; reference to a since-deleted or other-tenant entity.\n"
    "  5. AUTHZ / IDOR: for EVERY id-bearing endpoint, access another tenant's id\n"
    "     (expect 404/403, never 200/500) as each role; URL-tamper across tenants.\n"
    "  6. ADMIN PANEL: every /admin endpoint + UI page; create/suspend/reactivate\n"
    "     tenant; user deactivate/reactivate/reset-password/role-change; audit log;\n"
    "     settings edit; AI providers/routing CRUD + test-connection; impersonation\n"
    "     start -> act-as -> stop end to end.\n"
    "  7. UI-PER-ROLE: on each page, for each role, verify the UI HIDES actions the\n"
    "     role cannot perform (a shown button that 403s is a finding).\n"
    "  8. CONCURRENCY/IDEMPOTENCY: double-submit, refresh-after-POST, two-tab edit.\n"
    "  9. RUNTIME/VISUAL per page per role: console errors during render, layout\n"
    "     overflow, broken images, unlabeled controls, missing empty/loading states.\n"
    " 10. CROSS-SIDE FLOWS end to end (customer<->vendor, requester<->approver),\n"
    "     switching accounts, verifying both sides + notifications/emails fire.\n"
    " 11. DISPLAY INTEGRITY on every render surface — no raw option value, UUID,\n"
    "     or snake_case enum shown to a user (see DISPLAY-INTEGRITY CHECK). Drive\n"
    "     with adversarial data, not friendly seed data.\n"
    " 12. LINK INTEGRITY — statically cross-check every constructed path (client\n"
    "     navigate + server-built email/notification URLs) against the route table,\n"
    "     AND click every link/email button to its destination (see LINK-INTEGRITY\n"
    "     CHECK). A path with no route, or a link that 404s, is a finding.\n"
    " 13. PERSISTENCE — every mutating action is verified by HARD-RELOAD and re-\n"
    "     read, never by the success toast alone (see PERSISTENCE VERIFICATION).\n"
    " 14. CRUD-COMPLETENESS MATRIX — one ledger row per (entity × operation);\n"
    "     any create-only entity (no edit or no delete/archive) is a finding\n"
    "     unless the gap is an explicit, justified decision (see CRUD-COMPLETENESS\n"
    "     MATRIX).\n"
    " 15. ADVERSARIAL FIXTURES seeded before TEST (value!=label options, blank-\n"
    "     name records, import-path records, every lifecycle state, unicode/XSS\n"
    "     carried through) — the run drives THIS data, not the defaults (see\n"
    "     ADVERSARIAL FIXTURES).\n"
    " 16. REALISTIC TASK JOURNEYS per persona at full scale — complete the real\n"
    "     jobs-to-be-done with real content and harvest every friction point as\n"
    "     an improvement finding (see REALISTIC TASK JOURNEYS). ~40% of real\n"
    "     user-filed issues were this class.\n"
    " 17. RESILIENCE & RECOVERY — error blast radius (app still usable everywhere\n"
    "     after any error), lockout-capable settings + recovery paths, settings\n"
    "     round-trips, error-message persistence, mid-flow abandonment (see\n"
    "     RESILIENCE & RECOVERY).\n"
    " 18. CAPABILITY-PARITY MATRIX across analogous entities — asymmetries in\n"
    "     import/AI/export/preview/clone/versioning are findings (see\n"
    "     CAPABILITY-PARITY MATRIX).\n"
    " 19. ACTION-PRECONDITION COHERENCE — every export/bulk/send/generate action\n"
    "     driven in the zero/empty state (see ACTION-PRECONDITION COHERENCE).\n"
    " 20. GLOBAL AFFORDANCE AVAILABILITY — feedback/help/nav reachable in every\n"
    "     UI state incl. open modals/drawers (see GLOBAL AFFORDANCE AVAILABILITY).\n"
    " 21. VIEWPORT MATRIX — key pages + one journey per role at ~375px, ~768px,\n"
    "     and 1280px+ (see VIEWPORT MATRIX).\n"
    " 22. THIRD-PARTY AUTH EDGES — SSO account-switching, cancel-at-IdP, expired\n"
    "     IdP session, redirect-loop failures (see THIRD-PARTY AUTH EDGES).\n"
    "\n"
    + SHALLOW_BUG_CHECKS + "\n"
    "\n"
    + EXPERIENCE_CHECKS + "\n"
    "\n"
    "Both METHODS are required, not either/or: fast API probing (curl/fetch with a\n"
    "token per role) for the abuse/authz/500 matrix, AND browser driving for UI,\n"
    "rendering, client validation, and real user journeys. And a THIRD: STATIC\n"
    "cross-checks (route table vs constructed links; endpoint list vs UI actions;\n"
    "render code vs value-mapping) catch whole classes — broken deep links, missing\n"
    "CRUD, raw-value leakage — faster than either dynamic method alone."
)


# ============================================================================
# STEP 1: SCOPE
# ============================================================================

SCOPE_INSTRUCTIONS = (
    "Establish scope for an EXHAUSTIVE test / fix / re-test run.\n"
    "\n"
    + STOP_GATE + "\n"
    "\n"
    + MANDATORY_COVERAGE + "\n"
    "\n"
    "PARSE project context:\n"
    "  1. What project/codebase is being reviewed?\n"
    "  2. Site URL. Check in order: user message; project CLAUDE.md / README\n"
    "     (dev URL, 'Site Review' section, deployed test URL); package.json\n"
    "     scripts; .env (PORT/URL/HOST). If not found, AskUserQuestion.\n"
    "  3. How is the app built/deployed and how are changes shipped to the URL\n"
    "     under test? (local dev server with hot reload, or a build+deploy step?)\n"
    "     Record the exact command(s) -- REMEDIATE needs them to ship fixes before\n"
    "     re-testing. Check CLAUDE.md for a deploy/ship command or Stop-hook.\n"
    "  4. How are tests run in this project (per workspace/runner)? Record the\n"
    "     commands -- every fix must ship with tests and the suites must pass.\n"
    "  5. Any explicit focus areas or exclusions?\n"
    "\n"
    "ENUMERATE ROLES & CREDENTIALS (drives exhaustive coverage):\n"
    + ROLE_COVERAGE + "\n"
    "  Record every role and how to obtain a session for it (seeded creds,\n"
    "  self-register, invite-accept). If credentials are unknown and cannot be\n"
    "  created, AskUserQuestion.\n"
    "\n"
    "CREATE THE RUN LEDGER DIRECTORY:\n"
    f"  1. Create `{LEDGER_DIR}/` in the project root (mkdir -p).\n"
    f"  2. Ensure it is ignored by git for the duration: if a `.gitignore` exists\n"
    f"     and does not already list it, append a line `{LEDGER_DIR}/` and REMEMBER\n"
    "     that you added it (CLEANUP removes the line too). If there is no\n"
    "     .gitignore, create one containing only that line and remember you created it.\n"
    f"  3. Seed `{LEDGER_DIR}/ledger.md` and `{LEDGER_DIR}/findings.md` with headers.\n"
    f"  4. Screenshots and per-agent notes also go under `{LEDGER_DIR}/`.\n"
    "\n"
    "INSTALL THE STOP GATE NOW (see THE STOP GATE above) — write the hook script,\n"
    "register it in .claude/settings.local.json, and confirm it blocks on an\n"
    "unfinished ledger. Without this the run will stop early. Do it before TEST.\n"
    "\n"
    "PROVISION EVERY ROLE UP FRONT (per the MANDATORY COVERAGE MATRIX) — obtain a\n"
    "working session for each customer role, each vendor role, unauthenticated, a\n"
    "SYSTEM ADMIN (reset a seeded system user's password via the DB if needed), and\n"
    "a second tenant of each type for cross-tenant tests. Record all credentials in\n"
    f"`{LEDGER_DIR}/scope.md`. A missing role = a coverage hole, not an excuse to skip.\n"
    "\n"
    "SEED ADVERSARIAL FIXTURES UP FRONT (do NOT rely on the app's friendly seed\n"
    "data — that is why prior passes stayed green). Per ADVERSARIAL FIXTURES below,\n"
    "create the value!=label records, blank-name records, import-path records, one\n"
    "record per lifecycle state, and unicode/XSS-carrying text, THEN drive every\n"
    "downstream surface with THIS data. Record what you seeded in\n"
    f"`{LEDGER_DIR}/scope.md` so TEST agents reuse it.\n"
    "\n"
    "REFERENCE FORMATS (used by later steps and every sub-agent):\n"
    + ACTION_LEDGER_FORMAT + "\n"
    "\n"
    + FINDINGS_FILE_FORMAT + "\n"
    "\n"
    "DO NOT seek user confirmation of scope -- scope is internal guidance. The only\n"
    "things worth an AskUserQuestion are a missing URL, missing credentials that\n"
    "cannot be created, or a genuinely ambiguous product decision.\n"
    "\n"
    "ADVANCE: when URL, ship/test commands, roles+credentials, and the ledger\n"
    "directory are ready, proceed to UNDERSTAND."
)


# ============================================================================
# STEP 2: UNDERSTAND
# ============================================================================

UNDERSTAND_DISPATCH_CONTEXT = (
    "Exhaustive-test scope from SCOPE:\n"
    "- Project codebase and technology stack\n"
    "- Site URL, ship command, test commands\n"
    "- The full list of roles/permissions to cover"
)

UNDERSTAND_DISPATCH_AGENTS = [
    "[Focus 1: e.g., 'Routing map: every route/page incl. dynamic + guarded routes']",
    "[Focus 2: e.g., 'Every API endpoint: method, path, auth/role required, validation rules']",
    "[Focus 3: e.g., 'Entities, relationships, lifecycle/state machines, and per-role permissions']",
    "[Focus N: components/forms and their validation/error-handling patterns]",
]

UNDERSTAND_DISPATCH_GUIDANCE = (
    "DISPATCH GUIDANCE:\n"
    "\n"
    "Generate 2-4 Explore agents. Collectively they MUST return, exhaustively:\n"
    "  1. EVERY route/page (including dynamic and auth/role-guarded routes)\n"
    "  2. EVERY entity/model/resource\n"
    "  3. EVERY API endpoint (method + path) and the validation rules + role/\n"
    "     permission each enforces (this is the negative-test and authz oracle)\n"
    "  4. EVERY CRUD + special action per entity\n"
    "  5. EVERY role/permission level and multi-tenant boundary\n"
    "  6. Lifecycle/state machines (draft->sent->approved, etc.) so state-\n"
    "     transition actions are enumerated, not just CRUD\n"
    "  7. Form field types + validation rules (drives the INPUT TESTING MATRIX)\n"
    "  8. THE ROUTE TABLE verbatim (every client-side <Route> path) AND every\n"
    "     constructed link — client navigate()/href targets and every URL built\n"
    "     SERVER-side (email templates, notification links, redirects). This is\n"
    "     the LINK-INTEGRITY oracle: any constructed path absent from the route\n"
    "     table is a broken deep-link finding, catchable statically here.\n"
    "  9. VALUE->LABEL mappings: for every select/enum/status field, the stored\n"
    "     wire value vs the human label, and which render sites map vs show raw.\n"
    "     This is the DISPLAY-INTEGRITY oracle.\n"
    " 10. The CRUD-COMPLETENESS view: for each entity, which of Create/Read/\n"
    "     Update/Delete-or-Archive has BOTH an endpoint and a UI affordance.\n"
    "\n"
    "This model is the oracle: it tells you what each action SHOULD do, so a\n"
    "wrong-but-not-crashing behaviour is still caught. Items 8-10 let TEST catch\n"
    "broken links, raw-value leakage, and missing CRUD by static cross-check —\n"
    "before ever opening the browser."
)

UNDERSTAND_PROCESSING = (
    "WAIT for Explore results, then build a structured model (kept in context and\n"
    f"summarised into `{LEDGER_DIR}/model.md`):\n"
    "\n"
    "  ARCHITECTURE: component hierarchy, routing (ALL routes), layout wrappers,\n"
    "    auth/permission guards per route.\n"
    "\n"
    "  ENTITY / ENDPOINT / ROLE MODEL (the coverage oracle):\n"
    "    For each entity: API endpoints (with the role each requires and the\n"
    "    validation rules each enforces), UI pages (list/detail/create/edit),\n"
    "    special/admin actions, lifecycle states + transitions, relationships.\n"
    "    For each role: which routes/actions it may and may NOT perform.\n"
    "    EVERY endpoint without a UI action, and EVERY entity without full per-role\n"
    "    CRUD, is a candidate finding to confirm in the browser.\n"
    "\n"
    "  PATTERNS: styling system, form handling, error handling (boundary/toast/\n"
    "    inline), loading/empty/error state conventions, notification mechanism.\n"
    "\n"
    "This model directly drives INVENTORY (what actions must exist) and TEST\n"
    "(what each action should do, incl. negative responses).\n"
    "\n"
    "ADVANCE: when the model is complete, proceed to INVENTORY."
)


# ============================================================================
# STEP 3: INVENTORY  (exhaustive action enumeration -> ledger)
# ============================================================================

INVENTORY_INSTRUCTIONS = (
    "Build the EXHAUSTIVE Action Ledger by driving the browser as EVERY role and\n"
    "enumerating every testable action. This is the checklist the whole run is\n"
    "measured against -- if an action is not in the ledger, it will not be tested,\n"
    "so err toward over-enumeration. The MANDATORY COVERAGE MATRIX (from SCOPE) is\n"
    "the required minimum -- EVERY numbered block there must become ledger rows now,\n"
    "including the admin panel, the malformed-input/abuse matrix, per-role authz,\n"
    "and concurrency. The Stop gate will not let the run finish until they are PASS.\n"
    "\n"
    + MANDATORY_COVERAGE + "\n"
    "\n"
    + ACTION_LEDGER_FORMAT + "\n"
    "\n"
    "PROCEDURE (repeat for EACH role from SCOPE):\n"
    "  1. Obtain a session for the role (log in / register / accept invite).\n"
    "  2. Visit every route from the model AND every page reachable by clicking\n"
    "     through all navigation (navbar, sidebar, footer, menus, tabs, sub-nav).\n"
    "     Navigate to model routes not linked from nav directly by URL.\n"
    "  3. On each page and each of its states (default, each tab, each opened\n"
    "     modal/dropdown/expander, empty vs populated, each row-level menu),\n"
    "     enumerate EVERY interactive element and the intent behind it.\n"
    "  4. For each element add ledger row(s): a positive variant, plus every\n"
    "     REACHABLE negative variant (invalid input per the INPUT TESTING MATRIX,\n"
    "     empty/no-match states, unauthorized-from-this-role, URL-tampering,\n"
    "     reload/back, double-submit, cancel/discard).\n"
    "  5. Add rows for state-machine TRANSITIONS from the model (submit, approve,\n"
    "     reject, send, close, reopen...) as first-class actions, per role.\n"
    "  6. Add rows for global concerns once per role: login, logout, hard reload\n"
    "     (session survives), 404 route, unauthorized route, global search, each\n"
    "     command-palette / keyboard action.\n"
    "\n"
    "CROSS-REFERENCE (nothing missed):\n"
    + API_UI_CROSS_REFERENCE + "\n"
    "  Add a ledger row for every endpoint's reachable negative responses too.\n"
    "\n"
    "EXPECTED-FEATURE SWEEP (missing things are actions too):\n"
    "  For each page, compare against the standard features for its type. Any\n"
    "  EXPECTED feature that is absent becomes a ledger row asserting it should\n"
    "  exist (Status UNTESTED -> it will be confirmed as a MISSING-FUNCTIONALITY\n"
    "  finding in TEST, or PASS if actually present).\n"
    + SAAS_PAGE_STANDARDS + "\n"
    "\n"
    "COVERAGE GUARANTEE before leaving this step (all MANDATORY):\n"
    "  - Every route in the model appears on >=1 ledger row per role that can reach it.\n"
    "  - Every entity has Create/Read/Update/Delete rows (or a MISSING finding).\n"
    "  - Every role has both positive rows (allowed) and negative authz rows (denied).\n"
    "  - Every form/endpoint has the full INPUT-ABUSE MATRIX rows (valid, empty,\n"
    "    malformed-uuid id, malformed JSON body, invalid enum, oversized, XSS/SQLi,\n"
    "    negative number, duplicate, deleted/other-tenant ref).\n"
    "  - Every id-bearing endpoint has a cross-tenant IDOR row.\n"
    "  - The ADMIN PANEL (every endpoint + page + write flow + impersonation) has rows.\n"
    "  - Concurrency (double-submit / refresh-POST / two-tab) rows exist.\n"
    "  - Write the full ledger to the ledger file. Report the row count by role and\n"
    "    by matrix block, and confirm every block from the MANDATORY COVERAGE MATRIX\n"
    "    is represented. Missing blocks = go back and add them before TEST.\n"
    "\n"
    "ADVANCE: when the ledger is written and the coverage guarantee holds, proceed to TEST."
)


# ============================================================================
# STEP 4: TEST  (iterative: exercise every un-tested ledger action)
# ============================================================================

TEST_DISPATCH_CONTEXT = (
    "Exhaustive test context from prior steps:\n"
    "- Site URL, per-role credentials, ship/test commands (SCOPE)\n"
    "- Entity/endpoint/role model = the behaviour oracle (UNDERSTAND)\n"
    f"- The Action Ledger at `{LEDGER_DIR}/ledger.md` (INVENTORY)\n"
    f"- Findings log at `{LEDGER_DIR}/findings.md`\n"
    "\n"
    "Each test agent is assigned a SLICE of UNTESTED ledger rows (grouped by role\n"
    "+ page/entity so it can hold a coherent session) and must EXECUTE each one\n"
    "for real in the browser -- positive and negative -- then update the ledger\n"
    "row's Status and append any findings. Do not merely inspect; drive it.\n"
    "\n"
    "METHOD INTEGRITY (do not drift): the browser-driving slices are the CORE of\n"
    "this step and are NON-NEGOTIABLE. Static code-analysis agents exist ONLY as a\n"
    "supplement for the link/CRUD/display cross-checks -- they can NEVER replace\n"
    "browser driving of a row. A run whose TEST step is entirely code-reading\n"
    "sub-agents has FAILED this step regardless of how many findings it produced;\n"
    "code review cannot observe runtime/rendering/UI defects (a broken download, a\n"
    "blank page, a mis-wired response shape) and will silently mark them 'clean'.\n"
    "If browser automation is blocked, STOP and surface it -- do not fall back to\n"
    "code-only auditing."
)

TEST_DISPATCH_AGENTS = [
    "[Slice 1: e.g., 'Role admin, pages /users + /users/:id + create/edit -- ledger rows A001-A030']",
    "[Slice 2: e.g., 'Role vendor, questionnaire respond + evidence upload -- rows A031-A060']",
    "[Slice 3: e.g., 'Unauthenticated + cross-role authz negative rows across all pages']",
    "[Slice N: by remaining UNTESTED rows]",
]

TEST_DISPATCH_GUIDANCE = (
    "DISPATCH GUIDANCE:\n"
    "\n"
    "Partition the UNTESTED (and FIXED-RETEST) ledger rows across test agents.\n"
    "Fan out AGGRESSIVELY and run agents SIMULTANEOUSLY — this is a wide, parallel\n"
    "sweep, not a serial crawl. Depth and coverage matter far more than speed or\n"
    "token cost; prefer more agents and more probing over finishing quickly.\n"
    "  - Group rows by (role + page/entity) so one agent keeps one session.\n"
    "  - Keep an entity's full CRUD + its negative/authz rows in one agent.\n"
    "  - Put cross-role authz-denial rows into a dedicated agent.\n"
    "  - Dedicate agents to the STATIC cross-checks that need no browser: one for\n"
    "    LINK INTEGRITY (route table vs every constructed client + email URL), one\n"
    "    for the CRUD-COMPLETENESS MATRIX (endpoint list vs UI affordances), one\n"
    "    for DISPLAY INTEGRITY (grep render sites for raw value/id/enum output).\n"
    "    These run in parallel with the browser agents and catch whole classes\n"
    "    fast.\n"
    "  - Drive CROSS-SIDE flows with TWO agents at once where useful — e.g. one\n"
    "    holding the customer session and one the vendor session for a\n"
    "    send->respond->review->request-changes->resubmit handoff — so both sides\n"
    "    (and the notifications/emails between them) are observed live.\n"
    "  - Dedicate ONE JOURNEY AGENT PER PERSONA to the REALISTIC TASK JOURNEYS:\n"
    "    it completes the persona's real job at full scale with real content and\n"
    "    harvests friction findings (repetition burden, bad defaults, cramped\n"
    "    inputs, missing preview/parity). This runs alongside — not instead of —\n"
    "    the row-driving agents; its findings are improvement opportunities.\n"
    "  - Dedicate an agent to RESILIENCE & RECOVERY (error blast radius, lockout\n"
    "    settings + recovery, mid-flow abandonment) and one to the VIEWPORT\n"
    "    MATRIX sweep (~375px / ~768px / 1280px+ across key pages).\n"
    "  - 1 agent per ~15-30 rows; scale the agent count to the work — dozens of\n"
    "    simultaneous agents across a large surface is expected, not excessive.\n"
    "\n"
    "Each agent's unique task MUST specify: its exact ledger row IDs, the role +\n"
    "credentials to use, the pages involved, and WHICH adversarial fixtures to\n"
    "drive with. Put the site URL, the ledger and findings file paths, the\n"
    "behaviour oracle summary, and the SHALLOW-BUG CHECKS in shared context.\n"
    "\n"
    "Every agent MUST, for each assigned row: perform the action, apply the\n"
    "INPUT TESTING MATRIX where relevant, run the PART G shallow-bug sweep\n"
    "(display integrity, link integrity, reload-verified persistence, CRUD\n"
    "completeness), compare against the oracle, set the row Status (PASS/FAIL/\n"
    "BLOCKED), and append findings with the EVIDENCE format and stable IDs.\n"
    "Browser-automation flakiness (1Password overlays, ref churn) must be retried,\n"
    "not recorded as app FAILs."
)

TEST_PROCESSING = (
    "WAIT for all test agents, then reconcile:\n"
    "\n"
    "  1. Re-read the ledger. Recompute counts: UNTESTED / PASS / FAIL /\n"
    "     BLOCKED / FIXED-RETEST, overall and per role.\n"
    "  2. De-duplicate findings that multiple agents reported (same page+action+\n"
    "     symptom -> one finding id; note all occurrences).\n"
    "  3. For BLOCKED rows, determine why (missing seed data, needs another role's\n"
    "     action first, automation issue) and either unblock now or add the\n"
    "     prerequisite as its own row.\n"
    "  4. Discovered-mid-test actions: ensure they were appended as new UNTESTED rows.\n"
    "\n"
    "COVERAGE ASSESSMENT (confidence):\n"
    "  - certain: ZERO rows remain UNTESTED or BLOCKED-without-reason; every\n"
    "    entity CRUD-tested per role; every endpoint's negative responses driven;\n"
    "    every role's authz-denial rows exercised.\n"
    "  - otherwise: gaps remain.\n"
    "\n"
    "ADVANCE:\n"
    "  - confidence == certain: proceed to REMEDIATE (fix what TEST found).\n"
    "  - confidence != certain AND iteration < {max_iter}: run TEST again on the\n"
    "    remaining UNTESTED/BLOCKED rows only.\n"
    "  - iteration >= {max_iter}: log the still-uncovered rows explicitly in the\n"
    "    ledger (do NOT silently drop them) and proceed to REMEDIATE."
)


# ============================================================================
# STEP 5: REMEDIATE  (iterative: verify -> fix with tests -> ship -> re-test)
# ============================================================================

REMEDIATE_INSTRUCTIONS = (
    "Turn FAIL findings into fixes, then PROVE the fixes by re-testing. This step\n"
    "loops until every confirmed issue is VERIFIED (fixed AND re-tested clean).\n"
    "\n"
    "PART A - VERIFY (kill false positives before touching code):\n"
    f"  Read OPEN findings in `{LEDGER_DIR}/findings.md`. For each, confirm against\n"
    "  the codebase that it is a real defect and locate the responsible code.\n"
    "  Dispatch verification sub-agents for breadth when there are many findings\n"
    "  (each reads findings.md + the oracle model, searches code, and classifies\n"
    "  CONFIRMED / DESIGN_CHOICE / FALSE_POSITIVE with the exact file:line).\n"
    "  Update each finding's STATE. Drop FALSE_POSITIVE; keep DESIGN_CHOICE noted\n"
    "  but unfixed unless clearly wrong.\n"
    "\n"
    "PART B - GROUP BY ROOT CAUSE:\n"
    "  Cluster CONFIRMED findings that share a cause (e.g. one shared component,\n"
    "  one mis-typed enum, one missing guard) so a single fix clears many rows.\n"
    "  Order by severity, then by how many ledger rows each unblocks.\n"
    "\n"
    "PART C - FIX (autonomously; with tests):\n"
    "  For each root-cause group, implement the fix in real source code following\n"
    "  the project's conventions. EVERY fix ships with tests (unit/route/component\n"
    "  per the project's runners from SCOPE) and the relevant suites MUST pass.\n"
    "  Prefer parallel developer sub-agents for independent groups; keep\n"
    "  interdependent changes sequential. Pause ONLY for a genuine product/UX\n"
    "  decision or a destructive/irreversible action -- everything mechanical is\n"
    "  fixed without asking. Mark each fixed finding STATE=FIXED and flip the\n"
    "  ledger rows it touches to FIXED-RETEST (include rows for any code the fix\n"
    "  shares, i.e. regression surface).\n"
    "\n"
    "PART D - SHIP:\n"
    "  Run the project's ship/deploy command from SCOPE so the fixes are live at\n"
    "  the URL under test. Confirm the deploy/build succeeded (health check /\n"
    "  smoke test) before re-testing. If hot-reload, just confirm it recompiled.\n"
    "\n"
    "PART E - RE-TEST:\n"
    "  Re-run the FIXED-RETEST ledger rows in the browser (dispatch test agents as\n"
    "  in TEST). For each: PASS -> set row PASS and finding STATE=VERIFIED; still\n"
    "  FAIL or a NEW symptom -> keep/append an OPEN finding. Fixing code often\n"
    "  surfaces new issues -- treat them as first-class: add ledger rows + findings.\n"
    "\n"
    "ADVANCE:\n"
    "  - If any OPEN/CONFIRMED finding or FIXED-RETEST row remains AND iteration <\n"
    "    {max_iter}: run REMEDIATE again (verify new -> fix -> ship -> re-test).\n"
    "  - If everything is VERIFIED/PASS: proceed to CONVERGE.\n"
    "  - iteration >= {max_iter}: proceed to CONVERGE but list every unresolved\n"
    "    item explicitly (do not hide them)."
)


# ============================================================================
# STEP 6: CONVERGE  (fresh full sweep -> zero new issues, or back to REMEDIATE)
# ============================================================================

CONVERGE_INSTRUCTIONS = (
    "Prove the app is clean with a FRESH, independent full sweep -- not just a\n"
    "re-check of known failures. Fixes can regress untouched areas; this catches that.\n"
    "\n"
    "PROCEDURE:\n"
    "  1. Reset verdicts for a fresh pass: conceptually treat the whole ledger as\n"
    "     needing one more confirmation. In practice, re-run a representative\n"
    "     FULL pass: every entity's core CRUD per role, every state transition,\n"
    "     every authz-denial row, every previously-FAILed row, plus a random\n"
    "     sample of the rest. Use fresh personas/data where feasible so you are\n"
    "     not just replaying cached state.\n"
    "  2. Drive the primary end-to-end user journeys start to finish, switching\n"
    "     roles/accounts, verifying BOTH sides of every cross-side flow and that\n"
    "     notifications/emails fire where the model says they should.\n"
    "  3. Re-confirm the global invariants: hard reload keeps session on every\n"
    "     authed page; 404/403/500 render friendly states; no console/network\n"
    "     errors during happy paths; no cross-tenant leakage.\n"
    "  4. Re-run the SHALLOW-BUG CHECKS with the adversarial fixtures: spot-check\n"
    "     that no raw value/id/enum leaked back in, every link (incl. email\n"
    "     buttons) still resolves, edited fields still persist across reload, and\n"
    "     the CRUD-completeness matrix has no unjustified blanks.\n"
    "\n"
    "MECHANICAL COMPLETION CHECK (do NOT eyeball this -- run it):\n"
    f"  grep -E '^\\|' {LEDGER_DIR}/ledger.md | grep -cE '\\|[[:space:]]*(UNTESTED|FAIL|FIXED-RETEST|BLOCKED)[[:space:]]*\\|'\n"
    "  If that count is > 0, the run is NOT done -- go back and finish those rows.\n"
    "  The installed Stop gate runs exactly this check and will refuse to let the\n"
    "  session end while the count is non-zero. 'Done' is a number, not a feeling.\n"
    "\n"
    "BROWSER-COVERAGE PROOF (a ledger count of zero is necessary but NOT\n"
    "sufficient -- rows can be marked PASS by a code-only pass that never opened\n"
    "the app):\n"
    "  Emit a coverage report proving the fresh sweep was driven in the BROWSER:\n"
    "  for each role x primary page x core action actually exercised this pass,\n"
    "  cite the evidence (a screenshot/GIF reference, or the console/network\n"
    "  capture) recorded under `.site-review/`. A cell with no browser evidence is\n"
    "  NOT covered -- go drive it. Convergence is coverage-complete-WITH-EVIDENCE\n"
    "  first, then zero findings -- in that order, never the reverse.\n"
    "\n"
    "OUTCOME:\n"
    "  - ANY new or recurring issue, count > 0, OR any matrix cell lacking browser\n"
    "    evidence -> append findings, add/flip ledger rows, GO BACK to REMEDIATE\n"
    "    (fix -> ship -> re-test), then CONVERGE.\n"
    "  - count == 0 AND every matrix cell has browser evidence AND a completely\n"
    "    clean fresh browser sweep -> proceed to CLEANUP.\n"
    "\n"
    "Do NOT declare done on a partial sweep or a code-only sweep. 'No issues\n"
    "discovered' requires a full clean BROWSER pass AFTER the last fix, with the\n"
    "mechanical count at zero and the coverage matrix evidenced end to end."
)


# ============================================================================
# STEP 7: CLEANUP  (delete artifacts, report in chat)
# ============================================================================

CLEANUP_INSTRUCTIONS = (
    "Leave the repo exactly as you found it (minus the real source fixes) and\n"
    "report the outcome IN CHAT -- no report files.\n"
    "\n"
    "BEFORE deleting, extract everything you need for the summary from the ledger\n"
    "and findings files (counts, the list of fixed issues, any deliberately\n"
    "deferred items).\n"
    "\n"
    "REMOVE ARTIFACTS (order matters -- remove the Stop gate registration FIRST so\n"
    "it can't leave the project unable to stop):\n"
    "  1. REMOVE THE STOP GATE REGISTRATION: delete the hooks.Stop entry the skill\n"
    "     added to `.claude/settings.local.json` (leave every other hook/entry intact;\n"
    "     if the file becomes empty or the skill created it solely for this, remove\n"
    "     the file if it was skill-created, else leave an empty {}). Remove any\n"
    "     `.site-review/ABORT` sentinel.\n"
    "     DO NOT DELETE `.claude/hooks/site-review-gate.sh` ITSELF: Claude Code\n"
    "     snapshots the session's hook config, so the current session keeps invoking\n"
    "     that path on every stop even after the registration is removed — deleting\n"
    "     the script causes a 'No such file or directory' stop-hook error for the\n"
    "     rest of the session. The script is inert without a ledger (exits 0\n"
    "     silently), so leaving it is safe and costs nothing; the next run reuses it.\n"
    f"  2. Delete the `{LEDGER_DIR}/` directory entirely (ledger, findings,\n"
    "     screenshots, notes, model).\n"
    f"  3. If SCOPE added a `{LEDGER_DIR}/` line to an existing .gitignore, remove\n"
    "     just that line. If SCOPE created the .gitignore solely for this, delete\n"
    "     the file. Leave any pre-existing .gitignore content untouched.\n"
    "  4. Verify `git status` shows only intended source/test changes -- no\n"
    "     review bookkeeping, no settings entry, no screenshots. (The inert\n"
    "     `.claude/hooks/site-review-gate.sh` stays, per step 1.)\n"
    "\n"
    "REPORT IN CHAT (concise):\n"
    "  - Roles covered (incl. system-admin) and total actions exercised (ledger counts).\n"
    "  - Issues found -> fixed -> verified, grouped by severity, each with the\n"
    "    one-line what/where/fix and the finding id.\n"
    "  - Any items deliberately NOT fixed (design choices, product decisions) and why.\n"
    "  - Confirmation that the mechanical ledger count is ZERO, the final fresh sweep\n"
    "    was clean, and the gate + working directory were removed.\n"
    "  - The source/test files changed and how fixes were shipped/verified.\n"
    "\n"
    "Only now -- gate removed, ledger zero, artifacts gone -- is the session allowed\n"
    "to stop. This is the end of the run."
)


# ============================================================================
# MESSAGE BUILDERS
# ============================================================================


def build_understand_body() -> str:
    """UNDERSTAND: dispatch Explore agents to build the coverage oracle."""
    invoke_cmd = "python3 -m skills.codebase_analysis.subagent --step 1"

    dispatch_text = roster_dispatch(
        agent_type="general-purpose",
        agents=UNDERSTAND_DISPATCH_AGENTS,
        command=invoke_cmd,
        shared_context=UNDERSTAND_DISPATCH_CONTEXT,
        model="haiku",
        instruction="Determine 2-4 focus areas by tech stack. Collectively the "
                    "agents must enumerate EVERY route, endpoint (with auth + "
                    "validation rules), entity, role, and lifecycle state -- this "
                    "is the behaviour oracle for negative and authz testing. "
                    "Each agent's unique task is its focus area.",
    )

    return f"{dispatch_text}\n\n{UNDERSTAND_DISPATCH_GUIDANCE}\n\n{UNDERSTAND_PROCESSING}"


def build_test_body(iteration: int) -> str:
    """TEST: dispatch test-executor agents over UNTESTED ledger rows."""
    invoke_cmd = f"python3 -m {TEST_MODULE_PATH} --step 1"

    dispatch_text = roster_dispatch(
        agent_type="general-purpose",
        agents=TEST_DISPATCH_AGENTS,
        command=invoke_cmd,
        shared_context=TEST_DISPATCH_CONTEXT,
        instruction="Partition the UNTESTED/FIXED-RETEST ledger rows across "
                    "agents, grouped by role + page/entity so each holds one "
                    "session. Each agent's unique task lists its exact row IDs, "
                    "its role + credentials, and its pages. Agents EXECUTE each "
                    "action (positive + negative), update the ledger row status, "
                    "and append findings.",
    )

    processing = TEST_PROCESSING.format(max_iter=MAX_TEST_ITERATIONS)

    return (
        f"TEST - ITERATION {iteration} of {MAX_TEST_ITERATIONS}\n"
        f"\n"
        f"Exercise every UNTESTED ledger action for real -- positive and negative.\n"
        f"\n"
        f"{dispatch_text}\n"
        f"\n"
        f"{TEST_DISPATCH_GUIDANCE}\n"
        f"\n"
        f"{processing}"
    )


# Pre-computed static bodies
_UNDERSTAND_BODY = build_understand_body()


def build_next_command(step: int, confidence: str, iteration: int) -> str | None:
    """Build the invoke command for the next step."""
    base_cmd = f"python3 -m {MODULE_PATH}"

    if step == 1:
        return f"{base_cmd} --step 2"
    if step == 2:
        return f"{base_cmd} --step 3"
    if step == 3:
        return f"{base_cmd} --step 4 --iteration 1 --confidence exploring"
    if step == 4:
        if confidence == "certain" or iteration >= MAX_TEST_ITERATIONS:
            return f"{base_cmd} --step 5 --iteration 1 --confidence exploring"
        return (
            f"{base_cmd} --step 4 --iteration {iteration + 1} "
            f"--confidence {{exploring|low|medium|high|certain}}"
        )
    if step == 5:
        # REMEDIATE loops on itself until clean, then CONVERGE.
        if confidence == "certain" or iteration >= MAX_REMEDIATE_ITERATIONS:
            return f"{base_cmd} --step 6"
        return (
            f"{base_cmd} --step 5 --iteration {iteration + 1} "
            f"--confidence {{exploring|low|medium|high|certain}}"
        )
    if step == 6:
        # CONVERGE either sends us back to REMEDIATE or forward to CLEANUP.
        return (
            f"CLEAN SWEEP -> {base_cmd} --step 7   |   "
            f"NEW ISSUES -> {base_cmd} --step 5 --iteration 1 --confidence exploring"
        )
    if step == 7:
        return None
    return None


# ============================================================================
# STEP DEFINITIONS
# ============================================================================

STATIC_STEPS = {
    1: ("Scope", SCOPE_INSTRUCTIONS),
    2: ("Understand", _UNDERSTAND_BODY),
    3: ("Inventory", INVENTORY_INSTRUCTIONS),
    7: ("Cleanup", CLEANUP_INSTRUCTIONS),
}


def _format_step_4(confidence: str, iteration: int) -> tuple[str, str]:
    """TEST -- iterate until every ledger action has a verdict."""
    if confidence == "certain":
        return ("Test Coverage Complete",
                "Every ledger action has a verdict.\n\nPROCEED to REMEDIATE.")
    if iteration >= MAX_TEST_ITERATIONS:
        return ("Test Coverage Capped",
                f"Max TEST iterations reached ({iteration}/{MAX_TEST_ITERATIONS}). "
                "Log any still-uncovered rows in the ledger, then PROCEED to REMEDIATE.")
    return (f"Test (Iteration {iteration} of {MAX_TEST_ITERATIONS})",
            build_test_body(iteration))


def _format_step_5(confidence: str, iteration: int) -> tuple[str, str]:
    """REMEDIATE -- verify, fix (with tests), ship, re-test; loop until clean."""
    body = REMEDIATE_INSTRUCTIONS.format(max_iter=MAX_REMEDIATE_ITERATIONS)
    if confidence == "certain":
        return ("Remediation Complete",
                "All confirmed issues fixed and re-tested clean.\n\nPROCEED to CONVERGE.")
    if iteration >= MAX_REMEDIATE_ITERATIONS:
        return ("Remediation Capped",
                f"Max REMEDIATE iterations reached ({iteration}/{MAX_REMEDIATE_ITERATIONS}). "
                "List every unresolved item, then PROCEED to CONVERGE.\n\n" + body)
    return (f"Remediate (Iteration {iteration} of {MAX_REMEDIATE_ITERATIONS})", body)


DYNAMIC_STEPS = {
    4: _format_step_4,
    5: _format_step_5,
    6: lambda confidence, iteration: ("Converge", CONVERGE_INSTRUCTIONS),
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
        description="Site Review - Exhaustive test / fix / re-test loop",
        epilog=("Steps: SCOPE (1) -> UNDERSTAND (2) -> INVENTORY (3) -> "
                "TEST (4, loops) -> REMEDIATE (5, loops) -> CONVERGE (6) -> "
                "CLEANUP (7)"),
    )
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument(
        "--confidence",
        type=str,
        choices=["exploring", "low", "medium", "high", "certain"],
        default="exploring",
        help="Coverage/remediation confidence (TEST and REMEDIATE steps)",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        default=1,
        help="Iteration count (looping steps only)",
    )
    args = parser.parse_args()

    if args.step < 1 or args.step > TOTAL_STEPS:
        sys.exit(f"ERROR: --step must be 1-{TOTAL_STEPS}")
    if args.iteration < 1:
        sys.exit("ERROR: --iteration must be >= 1")

    print(format_output(args.step, args.confidence, args.iteration))


if __name__ == "__main__":
    main()
