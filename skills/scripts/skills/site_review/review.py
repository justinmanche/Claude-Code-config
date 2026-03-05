#!/usr/bin/env python3
"""
Site Review Skill - End-to-end site quality audit.

Seven-step workflow:
  1. SCOPE       - Parse intent, identify site URL and review goals
  2. UNDERSTAND  - Dispatch Explore agents for codebase comprehension
  3. MAP         - Navigate site, catalog all accessible pages/routes
  4. INSPECT     - Deep per-page review with screenshots (2-10 iterations)
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
INSPECT_MODULE_PATH = "skills.site_review.inspect_agent"
MAX_INSPECT_ITERATIONS = 10
TOTAL_STEPS = 7


# ============================================================================
# SHARED PROMPTS
# ============================================================================

SITE_MAP_FORMAT = (
    "The site map file uses this canonical structure:\n"
    "\n"
    "```markdown\n"
    "# Site Map\n"
    "\n"
    "## Base URL\n"
    "http://localhost:3000\n"
    "\n"
    "## Auth\n"
    "| Role  | Email             | Password |\n"
    "|-------|-------------------|----------|\n"
    "| Admin | admin@example.com | password |\n"
    "\n"
    "## Entities\n"
    "\n"
    "### [Entity Name]\n"
    "- **API Endpoints**\n"
    "  - `GET    /api/[entities]`          -- List\n"
    "  - `GET    /api/[entities]/:id`      -- Detail\n"
    "  - `POST   /api/[entities]`          -- Create\n"
    "  - `PUT    /api/[entities]/:id`      -- Update\n"
    "  - `DELETE /api/[entities]/:id`      -- Delete\n"
    "  - `POST   /api/[entities]/:id/[action]` -- Special action\n"
    "- **UI Pages**\n"
    "  - `/[entities]` -- List page\n"
    "  - `/[entities]/:id` -- Detail view\n"
    "  - `/[entities]/new` -- Create form\n"
    "  - `/[entities]/:id/edit` -- Edit form\n"
    "- **Relationships**: [belongs to X, has many Y]\n"
    "- **Notes**: [soft-delete only, archive not yet in UI, etc.]\n"
    "\n"
    "## Pages\n"
    "\n"
    "### [Section Name]\n"
    "| Route | Type | Description |\n"
    "|-------|------|-------------|\n"
    "| /path | Dashboard/List/Detail/Form/Settings/Auth | Brief description |\n"
    "\n"
    "## User Flows\n"
    "1. **Flow Name**: /step-1 -> /step-2 -> /step-3\n"
    "\n"
    "## Known Issues / Exclusions\n"
    "- [Things to skip or known WIP areas]\n"
    "```\n"
    "\n"
    "Key sections: Base URL, Auth, Entities (with API endpoints + UI pages),\n"
    "Pages (with types), User Flows, and Known Issues / Exclusions."
)

SITE_MAP_TRANSFORM = (
    "The user provided a file that contains site/API information but is NOT\n"
    "in canonical site map format. Extract and transform it:\n"
    "\n"
    "  1. READ the file thoroughly\n"
    "  2. EXTRACT: base URL, auth credentials, entities, API endpoints,\n"
    "     UI pages/routes, user flows, and any exclusions/known issues\n"
    "  3. IGNORE information not relevant to site review (deployment configs,\n"
    "     internal implementation details, CI/CD pipelines, etc.)\n"
    "  4. WRITE a new `site-map.md` in the project root using the canonical\n"
    "     format shown above\n"
    "  5. Use the newly written `site-map.md` going forward\n"
    "\n"
    "If the file is missing critical sections (e.g., no entities or no pages),\n"
    "fill gaps from code exploration in the UNDERSTAND step."
)

SITE_MAP_GENERATE = (
    "The user wants the site map generated from the codebase.\n"
    "\n"
    "  1. During UNDERSTAND, the Explore agents will discover entities,\n"
    "     API endpoints, UI pages, and routes\n"
    "  2. After UNDERSTAND completes, WRITE a `site-map.md` file in the\n"
    "     project root using the canonical format\n"
    "  3. Use that file as the authoritative checklist for MAP and INSPECT\n"
    "  4. Flag any gaps or ambiguities for the user to review later\n"
    "\n"
    "This is a DEFERRED action -- set a flag and execute after UNDERSTAND."
)

ISSUE_CATEGORIES = (
    "Issue categories to check (ordered by typical severity):\n"
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
    "  NEGATIVE PATH HANDLING (typically HIGH):\n"
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
    "\n"
    "  REDUNDANCY (typically LOW):\n"
    "    - Same action button appears in two locations on the same page\n"
    "    - Same data field displayed twice in same view without differentiation\n"
    "    - Two navigation paths lead to identical pages\n"
    "    - Confirmation dialog shown for low-risk reversible action\n"
    "    - Two settings controls affect the same behavior"
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

SAAS_PAGE_STANDARDS = (
    "Standard features expected by page type in enterprise SaaS.\n"
    "Feature labels: EXPECTED = absence is a finding; COMMON = absence\n"
    "is notable; DOMAIN-SPECIFIC = only if applicable to this vertical.\n"
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
    "  GENERAL (all pages -- check these on every page visited):\n"
    "    EXPECTED - Page renders without broken layout or clipped content\n"
    "    EXPECTED - No section visibly empty without message or loading indicator\n"
    "    EXPECTED - Every interactive element changes appearance on hover\n"
    "    EXPECTED - Every interactive element shows focus ring on Tab\n"
    "    EXPECTED - Tab key navigates elements in logical reading order\n"
    "    EXPECTED - Escape closes any open modal, dropdown, or flyout\n"
    "    EXPECTED - Modal/dialog traps focus (Tab cycles within, not behind)\n"
    "    EXPECTED - All user actions produce feedback within 1 second\n"
    "    EXPECTED - Destructive actions require confirmation step\n"
    "    EXPECTED - Success and error feedback visually distinguishable\n"
    "    EXPECTED - Page layout does not shift after initial render\n"
    "    EXPECTED - All text readable without clipping or overlap\n"
    "    EXPECTED - Page functional at 1280px width without horizontal scroll\n"
    "    EXPECTED - No sensitive data visible in plaintext\n"
    "    EXPECTED - Consistent header and nav across all authenticated pages\n"
    "\n"
    "  DASHBOARD:\n"
    "    EXPECTED - Metric cards/KPIs displayed above the fold\n"
    "    EXPECTED - Metric cards clickable (navigate to source list/detail)\n"
    "    EXPECTED - At least one data visualization (chart, graph, sparkline)\n"
    "    EXPECTED - Date/time range filter for data\n"
    "    EXPECTED - Loading skeleton while data loads\n"
    "    EXPECTED - Empty state with guidance for new accounts with no data\n"
    "    COMMON  - Trend indicators (up/down arrows) on metrics\n"
    "    COMMON  - Refresh/reload capability for live data\n"
    "    COMMON  - Customizable widget layout\n"
    "    COMMON  - Recently viewed or recent activity section\n"
    "\n"
    "  LIST/TABLE PAGE:\n"
    "    EXPECTED - Data loads automatically on page load\n"
    "    EXPECTED - Column headers with sortable click (sort indicator visible)\n"
    "    EXPECTED - Pagination or infinite scroll with record count\n"
    "    EXPECTED - Search/filter bar with 'Clear filters' option\n"
    "    EXPECTED - Active filters shown as dismissible chips\n"
    "    EXPECTED - Row click navigates to detail view\n"
    "    EXPECTED - Row hover state indicating interactivity\n"
    "    EXPECTED - Create/Add button prominently placed\n"
    "    EXPECTED - Checkbox column for row selection with bulk actions\n"
    "    EXPECTED - Empty state message with CTA when no items exist\n"
    "    EXPECTED - Loading state during data fetch\n"
    "    COMMON  - Export to CSV/Excel\n"
    "    COMMON  - Column visibility toggle (show/hide columns)\n"
    "    COMMON  - Saved views or named filter sets\n"
    "    COMMON  - Row-level action menu (ellipsis) for edit/delete\n"
    "    COMMON  - Inline editing on cell click\n"
    "\n"
    "  DETAIL/VIEW PAGE:\n"
    "    EXPECTED - Page title displays entity name or identifier\n"
    "    EXPECTED - Edit button prominently accessible\n"
    "    EXPECTED - Delete button with confirmation dialog\n"
    "    EXPECTED - Breadcrumb or Back button to parent list\n"
    "    EXPECTED - Related entities displayed as clickable links\n"
    "    EXPECTED - Created/modified timestamps visible\n"
    "    EXPECTED - Nonexistent entity ID shows 404 page, not blank\n"
    "    COMMON  - Activity timeline/history showing changes\n"
    "    COMMON  - Comments or notes section\n"
    "    COMMON  - Status indicator with visual distinction (badge, color)\n"
    "    COMMON  - Share or copy link to this record\n"
    "    COMMON  - File attachments section\n"
    "\n"
    "  CREATE/EDIT FORM:\n"
    "    EXPECTED - Title distinguishes Create from Edit\n"
    "    EXPECTED - Required fields marked with asterisk or label\n"
    "    EXPECTED - Inline validation on field blur\n"
    "    EXPECTED - Error messages adjacent to invalid field, not just top\n"
    "    EXPECTED - Submit button shows loading state during save\n"
    "    EXPECTED - Cancel button discards changes\n"
    "    EXPECTED - Unsaved changes warning on navigate away\n"
    "    EXPECTED - Success feedback after save (toast or redirect)\n"
    "    COMMON  - Character count for fields with length limits\n"
    "    COMMON  - Date picker for date fields (not free-text)\n"
    "    COMMON  - Type-ahead search for relationship fields\n"
    "    COMMON  - Auto-save draft with indicator\n"
    "\n"
    "  USER MANAGEMENT (admin):\n"
    "    EXPECTED - User list with search and filter by role/status\n"
    "    EXPECTED - View user details page\n"
    "    EXPECTED - Edit user role and permissions\n"
    "    EXPECTED - Reset password / send password reset email\n"
    "    EXPECTED - Activate / deactivate / suspend user\n"
    "    EXPECTED - Invite new user flow with role assignment\n"
    "    COMMON  - Last active date/time per user\n"
    "    COMMON  - Impersonate user (super admin)\n"
    "    COMMON  - Bulk invite via CSV upload\n"
    "    COMMON  - Resend invitation to pending invitees\n"
    "    COMMON  - Custom role creation with permission matrix\n"
    "\n"
    "  SETTINGS PAGE:\n"
    "    EXPECTED - Save button with confirmation feedback\n"
    "    EXPECTED - Sections organized by tabs, sidebar, or accordion\n"
    "    EXPECTED - Descriptions for non-obvious settings\n"
    "    EXPECTED - Danger zone separated for destructive settings\n"
    "    COMMON  - Reset to defaults option\n"
    "    COMMON  - Search within settings\n"
    "    COMMON  - Critical setting changes require re-authentication\n"
    "\n"
    "  AUTH PAGES:\n"
    "    EXPECTED - Login with email/password fields\n"
    "    EXPECTED - 'Forgot password?' link on login page\n"
    "    EXPECTED - Password strength indicator on signup/change password\n"
    "    EXPECTED - Show/hide password toggle\n"
    "    EXPECTED - Error for invalid credentials (without revealing if email exists)\n"
    "    EXPECTED - Redirect to intended page after login\n"
    "    EXPECTED - Logout accessible from every authenticated page\n"
    "    EXPECTED - Password reset shows generic success regardless of email existence\n"
    "    COMMON  - SSO/OAuth login option (Continue with Google/SSO)\n"
    "    COMMON  - MFA challenge screen with backup code option\n"
    "    COMMON  - Remember me / Keep me signed in checkbox\n"
    "\n"
    "  ONBOARDING/WIZARD:\n"
    "    EXPECTED - Step indicator showing current step and total steps\n"
    "    EXPECTED - Clear heading and description per step\n"
    "    EXPECTED - Next and Back navigation between steps\n"
    "    EXPECTED - Skip option for optional steps\n"
    "    EXPECTED - Summary/confirmation before final submission\n"
    "    EXPECTED - Progress persists if user abandons and returns\n"
    "    COMMON  - Checklist-style widget on dashboard (alternative to wizard)\n"
    "    COMMON  - Sample/demo data option to explore without real data\n"
    "    COMMON  - Team invitation step during onboarding\n"
    "\n"
    "  NOTIFICATION CENTER:\n"
    "    EXPECTED - Accessible from every page via bell icon or indicator\n"
    "    EXPECTED - Unread count badge on notification icon\n"
    "    EXPECTED - Reverse-chronological notification list\n"
    "    EXPECTED - Each notification shows actor, action, target, timestamp\n"
    "    EXPECTED - Mark as read per item and mark all as read\n"
    "    EXPECTED - Clicking notification navigates to relevant page\n"
    "    COMMON  - Filter by notification type\n"
    "    COMMON  - Link to notification preference settings\n"
    "    COMMON  - Real-time updates without page refresh\n"
    "\n"
    "  REPORTS/ANALYTICS:\n"
    "    EXPECTED - Report catalog listing available reports\n"
    "    EXPECTED - Create new report action\n"
    "    EXPECTED - Date range filter with relative options\n"
    "    EXPECTED - Export to CSV and/or PDF\n"
    "    EXPECTED - Last refreshed timestamp on report\n"
    "    COMMON  - Visualization type selector (table, chart, graph)\n"
    "    COMMON  - Drill-down: clicking chart segment shows source records\n"
    "    COMMON  - Share report link or schedule email delivery\n"
    "\n"
    "  PROFILE/ACCOUNT (personal settings):\n"
    "    EXPECTED - Editable display name and email\n"
    "    EXPECTED - Profile photo/avatar upload\n"
    "    EXPECTED - Change password form\n"
    "    EXPECTED - MFA setup and management\n"
    "    EXPECTED - Email notification preferences\n"
    "    COMMON  - Timezone and locale preferences\n"
    "    COMMON  - Active sessions list with remote logout\n"
    "    COMMON  - Theme selection (light/dark/system)\n"
    "    COMMON  - Connected OAuth apps with revoke option\n"
    "\n"
    "  SEARCH RESULTS:\n"
    "    EXPECTED - Search query displayed in input (editable)\n"
    "    EXPECTED - Total result count displayed\n"
    "    EXPECTED - Results grouped by entity type with labels\n"
    "    EXPECTED - Query terms highlighted in snippets\n"
    "    EXPECTED - Empty state with suggestions when no results\n"
    "    EXPECTED - Clicking result navigates to detail page\n"
    "    COMMON  - Filter by entity type (tabs or facets)\n"
    "    COMMON  - Did you mean suggestion for misspellings\n"
    "\n"
    "  BILLING/SUBSCRIPTION:\n"
    "    EXPECTED - Current plan name and billing cycle displayed\n"
    "    EXPECTED - Next billing date and amount\n"
    "    EXPECTED - Upgrade/downgrade plan option with comparison\n"
    "    EXPECTED - Invoice history with download PDF\n"
    "    EXPECTED - Current payment method (masked)\n"
    "    EXPECTED - Update payment method action\n"
    "    COMMON  - Seat count display (used/included)\n"
    "    COMMON  - Cancel subscription with retention step\n"
    "\n"
    "  AUDIT LOG:\n"
    "    EXPECTED - Entries show actor, action, target, timestamp, IP\n"
    "    EXPECTED - Date range filter\n"
    "    EXPECTED - Filter by actor and action type\n"
    "    EXPECTED - Export to CSV\n"
    "    COMMON  - Search log entries by keyword\n"
    "    COMMON  - Retention policy displayed\n"
    "\n"
    "  INTEGRATIONS/WEBHOOKS:\n"
    "    EXPECTED - Integration catalog with name, logo, status\n"
    "    EXPECTED - Connect/disconnect action per integration\n"
    "    EXPECTED - Connected integrations show status and account\n"
    "    COMMON  - Webhook management (create, configure, test)\n"
    "    COMMON  - Webhook delivery log with response codes\n"
    "    COMMON  - API key management (create, rotate, revoke)\n"
    "\n"
    "  ORG/TEAM MANAGEMENT:\n"
    "    EXPECTED - Team list with name and member count\n"
    "    EXPECTED - Create team action\n"
    "    EXPECTED - Add/remove members from team\n"
    "    COMMON  - Team-level role or permission assignment\n"
    "    COMMON  - Nested teams or department hierarchy\n"
    "\n"
    "  IMPORT/EXPORT:\n"
    "    EXPECTED - File upload (CSV minimum)\n"
    "    EXPECTED - Field mapping step (map columns to fields)\n"
    "    EXPECTED - Validation with error rows highlighted\n"
    "    EXPECTED - Import result summary (imported/failed/skipped)\n"
    "    COMMON  - Download template CSV with correct headers\n"
    "    COMMON  - Duplicate handling choice (skip/overwrite/create)\n"
    "\n"
    "  ERROR/MAINTENANCE PAGES:\n"
    "    EXPECTED - 404 page with brand styling and nav back to home\n"
    "    EXPECTED - 403/permission denied with clear explanation\n"
    "    EXPECTED - 500/server error with apology and support reference ID\n"
    "    COMMON  - Session expired page with re-login CTA\n"
    "    COMMON  - Error pages maintain consistent branding\n"
    "\n"
    "  CALENDAR VIEW (if applicable):\n"
    "    EXPECTED - Month, week, and day view toggle\n"
    "    EXPECTED - Navigate forward/backward with 'Today' button\n"
    "    EXPECTED - Click date/time to create event\n"
    "    EXPECTED - Click event to view/edit detail\n"
    "    COMMON  - Drag-and-drop to reschedule\n"
    "    COMMON  - Color coding by category or assignee\n"
    "\n"
    "  KANBAN BOARD (if applicable):\n"
    "    EXPECTED - Columns representing workflow stages\n"
    "    EXPECTED - Drag-and-drop cards between columns\n"
    "    EXPECTED - Card creation within each column\n"
    "    EXPECTED - Click card opens detail or slide-out panel\n"
    "    EXPECTED - Card count per column in header\n"
    "    COMMON  - WIP limit with visual alert when exceeded\n"
    "    COMMON  - Swimlanes by assignee or priority\n"
    "\n"
    "  APPROVAL WORKFLOW (if applicable):\n"
    "    EXPECTED - Clear submit-for-approval action\n"
    "    EXPECTED - Pending state visually distinct from draft and approved\n"
    "    EXPECTED - Approve and Reject actions with optional comment\n"
    "    EXPECTED - Rejection requires reason from approver\n"
    "    EXPECTED - Approval history on record (reviewer, decision, timestamp)\n"
    "    COMMON  - Multi-level approval chain\n"
    "\n"
    "  HELP/SUPPORT CENTER (if applicable):\n"
    "    EXPECTED - Help access from every page (? icon or menu)\n"
    "    EXPECTED - Context-sensitive help relevant to current page\n"
    "    EXPECTED - Search within help/documentation\n"
    "    COMMON  - In-app support ticket submission\n"
    "    COMMON  - Live chat or chatbot initiation"
)

INTERACTION_TESTING_PROTOCOL = (
    "Systematic interaction testing protocol:\n"
    "\n"
    "For EVERY entity/resource visible in the UI, test the full CRUD cycle:\n"
    "\n"
    "  PART A - CREATE:\n"
    "    1. Find the create/add button or link\n"
    "    2. If NO create mechanism exists, record MISSING FUNCTIONALITY\n"
    "    3. Open the create form\n"
    "    4. Screenshot the empty form\n"
    "    5. Submit with ALL fields empty -- check validation messages\n"
    "    6. Submit with invalid data per field type:\n"
    "       - Email fields: enter 'notanemail'\n"
    "       - Number fields: enter 'abc' or negative numbers\n"
    "       - Required fields: leave blank\n"
    "       - Text fields: enter extremely long string (200+ chars)\n"
    "       - Text fields: enter special characters (<script>, quotes, unicode)\n"
    "    7. Submit with valid data -- check success feedback\n"
    "    8. Verify new item appears in the list view\n"
    "\n"
    "  PART B - READ:\n"
    "    1. Navigate to list/table view for this entity\n"
    "    2. Does data load automatically on page load?\n"
    "    3. If data ONLY appears after clicking search/filter, record this\n"
    "       -- most SaaS apps load data on page load\n"
    "    4. Click into detail view for one item\n"
    "    5. Verify all fields from create form are displayed\n"
    "    6. Check for related entity links (are they clickable?)\n"
    "    7. Test search/filter if available\n"
    "    8. Test pagination if list has multiple items\n"
    "    9. Test column sorting if table has sortable headers\n"
    "\n"
    "  PART C - UPDATE:\n"
    "    1. Find the edit button/link (on list row or detail page)\n"
    "    2. If NO edit mechanism exists, record MISSING FUNCTIONALITY\n"
    "    3. Open the edit form\n"
    "    4. Verify form is pre-populated with current values\n"
    "    5. Change one field and save\n"
    "    6. Verify success feedback appears\n"
    "    7. Verify change persists (navigate away and back)\n"
    "    8. Test cancel/discard during edit\n"
    "\n"
    "  PART D - DELETE:\n"
    "    1. Find the delete button (on list row or detail page)\n"
    "    2. If NO delete mechanism exists, record MISSING FUNCTIONALITY\n"
    "    3. Click delete -- check for confirmation dialog\n"
    "    4. If NO confirmation dialog, record BEST PRACTICE violation\n"
    "    5. Confirm deletion\n"
    "    6. Verify item removed from list\n"
    "    7. Verify success feedback appears\n"
    "\n"
    "  PART E - NEGATIVE PATHS:\n"
    "    1. Navigate to entity detail with invalid/nonexistent ID\n"
    "       (e.g., /entity/99999999 or /entity/does-not-exist)\n"
    "    2. Check: proper 404 page? Blank page? Error? Redirect?\n"
    "    3. Navigate to entity detail for a just-deleted item\n"
    "    4. Attempt to access entity pages without auth (if applicable)\n"
    "    5. Test form submission with data that triggers server errors\n"
    "       (duplicate unique fields, referencing deleted entities)\n"
    "\n"
    "  PART F - UI HYGIENE:\n"
    "    1. Every button MUST have visible text or an accessible tooltip\n"
    "    2. Every table MUST show data or an empty state message\n"
    "    3. Every card that LOOKS clickable MUST be clickable\n"
    "    4. Dashboard metric cards that show counts SHOULD link to\n"
    "       the list they are counting\n"
    "    5. Every icon-only button MUST have a tooltip or aria-label\n"
    "    6. Disabled elements MUST have visual disabled state\n"
    "    7. Dropdown menus MUST close when clicking outside\n"
    "    8. Modals MUST close on escape key and overlay click\n"
    "    9. Form fields MUST have labels (not just placeholders)\n"
    "    10. Loading states MUST appear during async operations\n"
    "\n"
    "Track which entities have been CRUD-tested:\n"
    "```\n"
    "ENTITY TESTING STATUS:\n"
    "  [Entity Name]:\n"
    "    CREATE: [TESTED/MISSING/N-A] - [notes]\n"
    "    READ:   [TESTED/MISSING/N-A] - [notes]\n"
    "    UPDATE: [TESTED/MISSING/N-A] - [notes]\n"
    "    DELETE: [TESTED/MISSING/N-A] - [notes]\n"
    "    NEGATIVE: [TESTED/SKIPPED] - [notes]\n"
    "```"
)

API_UI_CROSS_REFERENCE = (
    "Cross-reference API capabilities with UI coverage:\n"
    "\n"
    "Using the API endpoints and entity model from UNDERSTAND:\n"
    "\n"
    "  1. For EACH API endpoint, verify a corresponding UI action exists:\n"
    "     - GET /api/entities -> List page exists?\n"
    "     - GET /api/entities/:id -> Detail page exists?\n"
    "     - POST /api/entities -> Create form exists?\n"
    "     - PUT/PATCH /api/entities/:id -> Edit form exists?\n"
    "     - DELETE /api/entities/:id -> Delete action exists?\n"
    "     - Any special endpoints -> Corresponding UI action?\n"
    "\n"
    "  2. Record MISSING FUNCTIONALITY for any API endpoint\n"
    "     without a corresponding UI action\n"
    "\n"
    "  3. Check for UI actions that call endpoints not in the API\n"
    "     (may indicate dead code or upcoming features)\n"
    "\n"
    "  4. Verify API error responses are handled gracefully in the UI\n"
    "     (not raw error objects or unhandled promises)"
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
    "DISCOVER SITE MAP:\n"
    "  Search for a site map file that lists pages, API endpoints,\n"
    "  entities, and routes. This is the AUTHORITATIVE checklist for\n"
    "  ensuring full coverage during MAP and INSPECT.\n"
    "\n"
    "  1. Check if the user provided a file path in their message\n"
    "  2. Glob for **/site-map.md in the project root\n"
    "  3. Also check for similar files: **/sitemap.md, **/api-reference.md,\n"
    "     **/routes.md, **/pages.md, **/endpoints.md\n"
    "\n"
    "  If a file is found:\n"
    "    - Read it and check whether it follows the canonical format\n"
    "      (has Entities with API Endpoints + UI Pages, and a Pages table)\n"
    "    - If canonical: use it directly as SITE_MAP_DATA\n"
    "    - If not canonical but contains useful route/endpoint/entity info:\n"
    "      transform it into canonical format and write site-map.md\n"
    "      (see SITE_MAP_TRANSFORM instructions below)\n"
    "\n"
    "  If NO file found:\n"
    "    Use AskUserQuestion:\n"
    "      question: 'No site map file found. A site map listing all pages,\n"
    "        API endpoints, and entities ensures thorough coverage.\n"
    "        Do you have one, or should I generate it from the codebase?'\n"
    "      header: 'Site Map'\n"
    "      options:\n"
    "        - label: 'I have a file - let me provide the path'\n"
    "          description: 'Any markdown/text file with routes, endpoints,\n"
    "            or page listings - does not need to be in a specific format'\n"
    "        - label: 'Generate from codebase'\n"
    "          description: 'Explore the code to build a site map automatically\n"
    "            (will be written to site-map.md for future runs)'\n"
    "        - label: 'Skip - just review what you can find'\n"
    "          description: 'Proceed without a site map (may miss pages)'\n"
    "\n"
    "    If user provides a file path:\n"
    "      Read it and apply SITE_MAP_TRANSFORM if not canonical format.\n"
    "    If user chooses 'Generate from codebase':\n"
    "      Set GENERATE_SITE_MAP = true. The UNDERSTAND step will build it.\n"
    "    If user chooses 'Skip':\n"
    "      Proceed without a site map (original behavior).\n"
    "\n"
    "  SITE MAP TRANSFORM (when file exists but is not canonical):\n"
    + SITE_MAP_TRANSFORM + "\n"
    "\n"
    "  CANONICAL FORMAT REFERENCE:\n"
    + SITE_MAP_FORMAT + "\n"
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
    "OUTPUT: Record whether a site map was found/generated/skipped.\n"
    "Pass SITE_MAP_STATUS (found | generated | transforming | skipped)\n"
    "and the file path (if any) to subsequent steps.\n"
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
    "  - Components, pages, and styling agent\n"
    "  - Routing, navigation, and page layouts agent\n"
    "  - State management, data fetching, and API client agent\n"
    "\n"
    "Full-stack project:\n"
    "  - Frontend architecture agent (components, pages, routing)\n"
    "  - API endpoints and route handlers agent\n"
    "  - Data model, schema, and entity relationships agent\n"
    "\n"
    "CRITICAL: Every agent must report back:\n"
    "  1. All routes/pages it finds (URL paths)\n"
    "  2. All entities/models/resources it finds (User, Product, etc.)\n"
    "  3. All API endpoints it finds (GET/POST/PUT/DELETE with paths)\n"
    "  4. All CRUD operations available per entity\n"
    "  5. Any admin/special actions (reset password, impersonate, export)\n"
    "\n"
    "This information is ESSENTIAL for cross-referencing API\n"
    "capabilities against UI coverage in later steps."
)

UNDERSTAND_PROCESSING = (
    "WAIT for Explore results.\n"
    "\n"
    "PROCESS code understanding into a structured model:\n"
    "\n"
    "PART A - ARCHITECTURE:\n"
    "  - Component hierarchy and reusable components\n"
    "  - Routing structure (ALL routes and pages, including dynamic routes)\n"
    "  - Layout patterns and shared wrappers\n"
    "  - Auth/permission guards on routes\n"
    "\n"
    "PART B - ENTITY MODEL:\n"
    "  If a SITE MAP file was found or provided in SCOPE:\n"
    "    - The site map is the AUTHORITATIVE source for entities, endpoints,\n"
    "      and pages. Use it as the primary entity model.\n"
    "    - SUPPLEMENT with any additional entities, endpoints, or routes\n"
    "      discovered by the Explore agents that are NOT in the site map.\n"
    "    - If the Explore agents find entities/routes missing from the site\n"
    "      map, ADD them to the working model and note the discrepancy.\n"
    "    - Respect 'Known Issues / Exclusions' from the site map -- do NOT\n"
    "      flag items the user has explicitly excluded.\n"
    "\n"
    "  If GENERATE_SITE_MAP was set in SCOPE:\n"
    "    - Build the entity model from Explore results (as below)\n"
    "    - WRITE site-map.md in the project root using canonical format\n"
    "    - Include all entities, API endpoints, UI pages, user flows,\n"
    "      and auth info discovered by the Explore agents\n"
    "    - This file becomes the authoritative checklist for MAP/INSPECT\n"
    "      and will be available for future re-runs\n"
    "\n"
    "  If NO site map (skipped):\n"
    "    Build a complete inventory of all entities/resources:\n"
    "    ```\n"
    "    ENTITY MODEL:\n"
    "      [Entity Name]:\n"
    "        API Endpoints:\n"
    "          - GET /api/[entities] (list)\n"
    "          - GET /api/[entities]/:id (detail)\n"
    "          - POST /api/[entities] (create)\n"
    "          - PUT /api/[entities]/:id (update)\n"
    "          - DELETE /api/[entities]/:id (delete)\n"
    "          - [any special endpoints]\n"
    "        UI Pages:\n"
    "          - /[entities] (list page)\n"
    "          - /[entities]/:id (detail page)\n"
    "          - /[entities]/new (create page)\n"
    "          - /[entities]/:id/edit (edit page)\n"
    "        Admin Actions: [reset password, impersonate, export, etc.]\n"
    "        Relationships: [belongs to X, has many Y]\n"
    "    ```\n"
    "\n"
    "  This model is CRITICAL. It drives the MAP and INSPECT steps.\n"
    "  Every API endpoint without a UI page is a potential finding.\n"
    "  Every entity without full CRUD UI is a potential finding.\n"
    "\n"
    "PART C - PATTERNS:\n"
    "  - Styling approach (CSS modules, Tailwind, styled-components, etc.)\n"
    "  - Component patterns (atomic, compound, etc.)\n"
    "  - Design system or UI library usage\n"
    "  - Form handling approach (controlled, uncontrolled, form library)\n"
    "  - Error handling patterns (error boundaries, toast, inline)\n"
    "\n"
    "PART D - DATA FLOW:\n"
    "  - Data fetching patterns (on mount, on action, SSR, etc.)\n"
    "  - Loading state handling (skeleton, spinner, none)\n"
    "  - Error state handling (error page, toast, inline, none)\n"
    "  - Empty state handling (message, illustration, none)\n"
    "  - Cache and optimistic update patterns\n"
    "\n"
    "This model directly feeds the browser review.\n"
    "Keep the ENTITY MODEL in context -- you will cross-reference it\n"
    "against what you find in the browser during MAP and INSPECT.\n"
    "\n"
    "ADVANCE: When code understanding and entity model complete, proceed to MAP."
)

# --- STEP 3: MAP -----------------------------------------------------------

MAP_INSTRUCTIONS = (
    "Navigate to the site URL identified in SCOPE.\n"
    "\n"
    "SITE MAP CHECKLIST:\n"
    "  If a site map file was found/generated/transformed in earlier steps,\n"
    "  use it as the AUTHORITATIVE navigation checklist:\n"
    "  - Every page listed in the Pages tables MUST be visited\n"
    "  - Every entity's UI pages MUST be verified\n"
    "  - Every user flow MUST be traced\n"
    "  - Auth credentials from the site map Auth table should be used\n"
    "  - Known Issues / Exclusions should be respected (skip flagged areas)\n"
    "  The site map ensures NO pages are missed. Navigation discovery below\n"
    "  is ADDITIVE -- it catches pages the site map might not list.\n"
    "\n"
    "PART A - OPEN AND NAVIGATE:\n"
    "  1. Navigate to the site URL in the browser\n"
    "     (use Base URL from site map if available)\n"
    "  2. Wait for full page load before taking action\n"
    "  3. Take a screenshot of the landing/home page\n"
    "  4. If auth is required, log in first\n"
    "     (check site map Auth table, then SCOPE for credentials)\n"
    "\n"
    "PART B - MAP THE SITE:\n"
    "  1. Identify ALL navigation elements (navbar, sidebar, footer, dropdowns)\n"
    "  2. Click through EVERY navigation link and record the page\n"
    "  3. On each page, identify sub-navigation (tabs, secondary nav)\n"
    "  4. Screenshot each major page for reference\n"
    "  5. Identify key user flows (login -> dashboard, browse -> detail, etc.)\n"
    "  6. Note pages requiring authentication or specific state/role\n"
    "  7. If site map exists: cross-check discovered pages against site map\n"
    "     pages -- flag any pages in the site map NOT reachable from nav\n"
    "     and navigate to them directly by URL\n"
    "\n"
    "PART C - CROSS-REFERENCE WITH CODE AND SITE MAP:\n"
    "  Using the ENTITY MODEL from UNDERSTAND (and site map if available):\n"
    "  1. Compare visible routes with ALL routes found in code and site map\n"
    "  2. For EACH entity in the entity model, verify:\n"
    "     - Is there a list/table page? Where?\n"
    "     - Is there a detail/view page? Where?\n"
    "     - Is there a create form? Where?\n"
    "     - Is there an edit form? Where?\n"
    "     - Is there a delete action? Where?\n"
    "  3. Note API endpoints with NO corresponding UI\n"
    "  4. Note routes in code or site map not reachable from navigation\n"
    "  5. Note visible links that seem broken or misconfigured\n"
    "\n"
    "PART D - BUILD ACTION INVENTORY:\n"
    "  For every page, list all interactive elements found:\n"
    "  ```\n"
    "  ACTION INVENTORY:\n"
    "    /dashboard:\n"
    "      - [Card] Revenue metric -> clickable? [YES/NO]\n"
    "      - [Card] Users count -> clickable? [YES/NO]\n"
    "      - [Button] 'Create New' -> links to: [destination]\n"
    "      - [Chart] Sales chart -> interactive? [YES/NO]\n"
    "    /users:\n"
    "      - [Table] User list -> row clickable? [YES/NO]\n"
    "      - [Button] 'Add User' -> present? [YES/NO]\n"
    "      - [Search] Search bar -> present? [YES/NO]\n"
    "      - [Filter] Filter controls -> present? [YES/NO]\n"
    "      - [Sort] Column sort -> present? [YES/NO]\n"
    "      - [Pagination] -> present? [YES/NO]\n"
    "      - [Bulk] Select all / bulk actions -> present? [YES/NO]\n"
    "  ```\n"
    "\n"
    "PART E - OUTPUT SITE MAP:\n"
    "  ```\n"
    "  SITE MAP:\n"
    "    URL: [base URL]\n"
    "    Total Pages Found: [N]\n"
    "    Pages:\n"
    "      - / (Home) - [loaded/broken]\n"
    "      - /dashboard - [status]\n"
    "      - /settings - [status]\n"
    "    Entity Coverage:\n"
    "      [Entity]: List[Y/N] Detail[Y/N] Create[Y/N] Edit[Y/N] Delete[Y/N]\n"
    "      [Entity]: List[Y/N] Detail[Y/N] Create[Y/N] Edit[Y/N] Delete[Y/N]\n"
    "    API Endpoints Without UI: [list]\n"
    "    User Flows:\n"
    "      - Onboarding: / -> /signup -> /onboarding -> /dashboard\n"
    "      - Settings: /dashboard -> /settings -> /settings/profile\n"
    "    Auth Required: [pages needing auth]\n"
    "    Unreachable Routes: [routes in code not in navigation]\n"
    "  ```\n"
    "\n"
    "PART F - PLAN INSPECTION ORDER:\n"
    "  Prioritize based on:\n"
    "  1. User-specified priority areas (from SCOPE)\n"
    "  2. Pages with the most interactive elements (highest finding potential)\n"
    "  3. Primary user flows (CRUD for main entities)\n"
    "  4. Admin/settings pages\n"
    "  5. Auth and edge-case pages (404, error states)\n"
    "\n"
    "  Plan which entities to CRUD-test in which iteration.\n"
    "  Every entity MUST be fully CRUD-tested by the final iteration.\n"
    "\n"
    "ADVANCE: When site map and action inventory complete, proceed to INSPECT."
)

# --- STEP 4: INSPECT -------------------------------------------------------

INSPECT_DISPATCH_CONTEXT = (
    "Site review context from prior steps:\n"
    "- Site URL, auth credentials, and review scope from SCOPE\n"
    "- Entity model, API endpoints, and UI pages from UNDERSTAND\n"
    "- Complete page list, action inventory, and site map from MAP\n"
    "\n"
    "Each inspect agent receives a batch of pages to thoroughly audit.\n"
    "The agent MUST check every SaaS page standard and every issue\n"
    "category for every assigned page -- nothing may be skipped."
)

INSPECT_DISPATCH_AGENTS = [
    "[Batch 1: e.g., 'Pages: /dashboard, /reports -- Types: Dashboard, Reports -- Entities: metrics, reports']",
    "[Batch 2: e.g., 'Pages: /users, /users/:id, /users/new -- Types: List, Detail, Form -- Entities: users']",
    "[Batch 3: e.g., 'Pages: /settings, /profile, /billing -- Types: Settings, Profile, Billing']",
    "[Batch N: based on total page count from MAP]",
]

INSPECT_DISPATCH_GUIDANCE = (
    "DISPATCH GUIDANCE:\n"
    "\n"
    "Assign ALL pages from the MAP step's site map and action inventory\n"
    "to inspect agents. Every page MUST be assigned to exactly one agent.\n"
    "\n"
    "PAGE BATCHING RULES:\n"
    "  - Group 1-4 related pages per agent (same entity or section)\n"
    "  - Keep entity CRUD pages together (list + detail + create + edit)\n"
    "    so one agent can test the full CRUD cycle\n"
    "  - Keep settings/profile/billing together (related admin pages)\n"
    "  - Auth pages (login, signup, forgot-password) go together\n"
    "  - Dashboard can go alone if complex, or with related pages\n"
    "\n"
    "AGENT COUNT:\n"
    "  - 1-4 pages: 1-2 agents\n"
    "  - 5-10 pages: 3-4 agents\n"
    "  - 11-20 pages: 4-6 agents\n"
    "  - 20+ pages: 6-8 agents (max)\n"
    "\n"
    "Each agent's unique task MUST specify:\n"
    "  1. Assigned pages (routes/URLs)\n"
    "  2. Page types for each page\n"
    "  3. Relevant entities and their CRUD endpoints\n"
    "  4. Auth credentials if pages require login\n"
    "  5. Any exclusions from the site map's Known Issues\n"
    "\n"
    "CRITICAL: Include the site URL in the shared context so agents\n"
    "can navigate to their assigned pages."
)

INSPECT_PROCESSING = (
    "WAIT for ALL inspect agents to return.\n"
    "\n"
    "AGGREGATE results from all agents:\n"
    "\n"
    "PART A - COLLECT FINDINGS:\n"
    "  1. Gather ALL findings from all agent reports\n"
    "  2. Deduplicate findings that appear in multiple reports\n"
    "     (e.g., navigation issues reported by multiple agents)\n"
    "  3. Assign sequential finding IDs across all reports\n"
    "  4. Preserve severity, category, page, element, and evidence\n"
    "\n"
    "PART B - VERIFY COMPLETION CHECKLISTS:\n"
    "  For each agent's COMPLETION CHECKLIST, verify:\n"
    "  - Every assigned page was actually inspected\n"
    "  - ALL SaaS page standards were checked (NAVIGATION + GENERAL +\n"
    "    page-type-specific) for every page\n"
    "  - ALL 14 issue categories were checked for every page\n"
    "  - CRUD testing was done for all relevant entities\n"
    "  If any agent's checklist shows unchecked items, note the gaps.\n"
    "\n"
    "PART C - COVERAGE ANALYSIS:\n"
    "  Cross-reference agent reports against the full page list:\n"
    "  ```\n"
    "  COVERAGE STATUS:\n"
    "    Pages inspected: [list] ([N] of [total])\n"
    "    Pages MISSING from reports: [list]\n"
    "    Entities CRUD-tested: [list] ([N] of [total])\n"
    "    Entities NOT CRUD-tested: [list]\n"
    "    Standards audit gaps: [any pages missing standards checks]\n"
    "    Category audit gaps: [any pages missing category checks]\n"
    "    Findings collected: [N]\n"
    "  ```\n"
    "\n"
    "PART D - API-UI CROSS-REFERENCE:\n"
    + API_UI_CROSS_REFERENCE + "\n"
    "\n"
    "PART E - NEGATIVE PATH TESTING:\n"
    "  Test paths that sub-agents may not have covered:\n"
    "  1. Navigate to nonexistent entity IDs (e.g., /entity/99999)\n"
    "  2. Navigate to invalid routes (e.g., /does-not-exist)\n"
    "  3. Test unauthorized access if applicable\n"
    "  4. Test at least 3 negative paths total\n"
    "\n"
    "PART F - INDUSTRY STANDARD COMPARISON:\n"
    "  For pages or features that seem incomplete:\n"
    "  1. Use WebSearch for best practices in well-known SaaS apps\n"
    "  2. Compare findings with industry standards\n"
    "  3. Record MISSING FUNCTIONALITY for significant gaps\n"
    "  4. Only flag genuinely useful missing features\n"
    "\n"
    "CONFIDENCE ASSESSMENT:\n"
    "  - CERTAIN: All pages inspected with full checklists completed,\n"
    "    all entities CRUD-tested, negative paths tested,\n"
    "    API-UI cross-reference done\n"
    "  - HIGH: 80%+ pages with full checklists, most entities CRUD-tested\n"
    "  - MEDIUM: Sub-agents returned but coverage gaps exist\n"
    "  - LOW: Significant gaps in agent reports\n"
    "\n"
    "IMPORTANT: Do NOT report CERTAIN until:\n"
    "  1. EVERY page has a completion checklist with all items checked\n"
    "  2. EVERY entity has been CRUD-tested\n"
    "  3. At least 3 negative paths tested\n"
    "  4. API-UI cross-reference completed\n"
    "  5. Every user flow from the site map tested (if one exists)\n"
    "\n"
    "If coverage gaps exist and iteration < {max_iter}:\n"
    "  Dispatch additional agents for uncovered pages only.\n"
    "\n"
    "ADVANCE:\n"
    "  - confidence == certain: Proceed to CATALOG\n"
    "  - confidence != certain AND iteration < {max_iter}: Continue INSPECT\n"
    "  - iteration >= {max_iter}: Force proceed to CATALOG"
)

# --- STEP 5: CATALOG -------------------------------------------------------

CATALOG_INSTRUCTIONS = (
    "COMPILE all findings from INSPECT sub-agent reports into a structured markdown file.\n"
    "\n"
    "READ back through ALL inspect agent reports and INSPECT aggregation.\n"
    "Gather EVERY finding. Do NOT skip findings you think are minor. Record everything.\n"
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
    "**Entities CRUD-Tested**: [count]\n"
    "**Total Findings**: [count]\n"
    "\n"
    "## Summary\n"
    "\n"
    "[2-3 sentence overview of overall site quality and main themes]\n"
    "\n"
    "## Entity CRUD Coverage\n"
    "\n"
    "| Entity | Create | Read | Update | Delete | Notes |\n"
    "|--------|--------|------|--------|--------|-------|\n"
    "| Users  | Y      | Y    | Y      | N      | No delete action found |\n"
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
    "### Missing Functionality\n"
    "[same table format]\n"
    "\n"
    "### Orphaned Elements\n"
    "[same table format]\n"
    "\n"
    "### Negative Path Handling\n"
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
    "\n"
    "## API-UI Coverage Gaps\n"
    "\n"
    "| API Endpoint | Method | UI Action | Status |\n"
    "|-------------|--------|-----------|--------|\n"
    "| /api/users/:id/reset-password | POST | None | MISSING |\n"
    "```\n"
    "\n"
    "RULES:\n"
    "  - Number findings sequentially across all categories (global IDs)\n"
    "  - Omit empty categories (no table if no findings)\n"
    "  - Include Entity CRUD Coverage table even if all entities are covered\n"
    "  - Include API-UI Coverage Gaps even if no gaps found (say 'None')\n"
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
    """Build INSPECT instructions with roster_dispatch() for page inspection.

    Dispatches inspect agents to thoroughly audit assigned pages.
    Each agent checks ALL SaaS page standards and ALL issue categories.
    """
    invoke_cmd = f'python3 -m {INSPECT_MODULE_PATH} --step 1'

    dispatch_text = roster_dispatch(
        agent_type="general-purpose",
        agents=INSPECT_DISPATCH_AGENTS,
        command=invoke_cmd,
        shared_context=INSPECT_DISPATCH_CONTEXT,
        instruction="Assign ALL pages from MAP to inspect agents. "
                    "Group related pages (same entity CRUD set) together. "
                    "Each agent's unique task specifies its assigned pages, "
                    "page types, relevant entities, and auth credentials. "
                    "Include the site URL in shared context.",
    )

    processing = INSPECT_PROCESSING.format(
        max_iter=MAX_INSPECT_ITERATIONS,
    )

    return (
        f"INSPECT - ITERATION {iteration} of {MAX_INSPECT_ITERATIONS}\n"
        f"\n"
        f"This step dispatches sub-agents for systematic page inspection.\n"
        f"Each agent thoroughly audits its assigned pages against ALL\n"
        f"SaaS page standards and ALL issue categories.\n"
        f"\n"
        f"{dispatch_text}\n"
        f"\n"
        f"{INSPECT_DISPATCH_GUIDANCE}\n"
        f"\n"
        f"{processing}"
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
