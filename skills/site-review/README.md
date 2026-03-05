# Site Review Architecture

End-to-end site quality audit combining static code analysis with dynamic
browser-based review.

## Workflow

```
SCOPE -> UNDERSTAND -> MAP -> INSPECT (iterative) -> CATALOG -> ASSESS -> PLAN
```

### Phases

1. **SCOPE**: Identifies project, URL, and review goals. Checks for prior run
   findings to focus on undiscovered areas.

2. **UNDERSTAND**: Dispatches Explore agents to build codebase comprehension,
   focusing on UI-relevant code (components, routing, styles).

3. **MAP**: Navigates to the site in browser, screenshots homepage, catalogs
   all accessible pages and user flows.

4. **INSPECT**: Dispatches parallel sub-agents for systematic page inspection.
   Each sub-agent receives a batch of 1-4 related pages and runs a 4-step
   workflow (Orient, Browse, Audit, Report). Every sub-agent MUST check ALL
   SaaS page standards (Navigation + General + page-type-specific) and ALL
   14 issue categories for every assigned page. Sub-agents return structured
   findings with mandatory completion checklists proving full coverage. The
   orchestrator aggregates results, verifies checklists, handles API-UI
   cross-reference, negative path testing, and industry standard comparison.
   Coverage confidence requires ALL pages inspected with complete checklists,
   ALL entities CRUD-tested, and negative paths tested before reporting CERTAIN.
   If gaps exist, additional sub-agents are dispatched for uncovered pages.

5. **CATALOG**: Compiles all findings into `site-review-findings.md` with
   structured tables by category.

6. **ASSESS**: Dispatches verification agents to cross-reference findings with
   code. Removes false positives, groups by root cause, builds priority matrix.

7. **PLAN**: Writes `site-review-plan.md` with four implementation phases:
   Quick Wins, Foundational, Feature-Level, Strategic.

## Design Decisions

### Browser-first, code-second

The skill navigates the site as a real user would, then maps observations back
to code. This catches issues that static analysis misses (visual regressions,
interaction bugs, UX flow problems).

### Iterative inspection

Like codebase-analysis DEEPEN, the INSPECT step iterates based on coverage
confidence. This ensures thorough coverage without artificial page limits.

### Verification sub-agents

ASSESS dispatches parallel agents to verify browser findings against code.
This eliminates false positives and identifies the exact code responsible for
each issue, producing actionable remediation items.

### Re-run awareness

SCOPE checks for existing findings files. On re-runs, the workflow focuses on
uncovered areas and new issues, making repeated runs productive.

## Output Files

- `site-review-findings.md`: Raw findings organized by category
- `site-review-plan.md`: Prioritized remediation plan with phases

## Site Map File

For thorough coverage, provide a `site-map.md` in your project root listing
all pages, API endpoints, entities, and user flows. The SCOPE step searches
for this file automatically and uses it as the authoritative navigation
checklist.

If no site map exists, the skill will ask whether to generate one from the
codebase or proceed without it. You can also provide any file containing
route/endpoint information (API docs, route configs, etc.) and the skill
will transform it into canonical format.

See the canonical format in `scripts/skills/site_review/review.py`
(`SITE_MAP_FORMAT` constant).

## Project Configuration

Add a `Site Review` section to your project's CLAUDE.md for automatic context:

```markdown
## Site Review

| Key          | Value                                          |
| ------------ | ---------------------------------------------- |
| Dev URL      | http://localhost:3000                           |
| Routes       | /, /dashboard, /settings, /profile, /login     |
| Auth         | Login with test@example.com / password          |
| Focus        | Onboarding flow, dashboard usability           |
| Known Issues | Dark mode is WIP, mobile nav has bugs          |
| Design Refs  | Link to Figma or style guide                   |
```

## Integration

After review, the user can:
- Use the **planner** skill to execute specific remediation phases
- Use **deepthink** for complex architectural decisions surfaced by findings
- Re-run site-review to discover additional issues
