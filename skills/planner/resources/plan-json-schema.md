# Plan JSON Schema v2

JSON-IR-first architecture. `plan.json` remains authoritative until TW phase translates to Markdown.

## Schema Overview

```
plan.json
  plan_id: uuid
  created_at: ISO-8601
  frozen_at: null | ISO-8601

  overview:
    title: string
    problem: string
    approach: string

  planning_context:
    decision_log: [DecisionLogEntry]
    rejected_alternatives: [RejectedAlternative]
    constraints: [Constraint]
    known_risks: [KnownRisk]

  invisible_knowledge:
    architecture: Diagram
    data_flow: Diagram
    structure_rationale: string
    invariants: [string]
    tradeoffs: [string]

  milestones: [Milestone]
  milestone_dependencies: MilestoneDependencies
```

---

## Decision Log Entry

Architect populates. Multi-step reasoning required.

```json
{
  "id": "DL-001",
  "decision": "What was decided",
  "reasoning_chain": "premise -> implication -> conclusion",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

ID format: `DL-###` (sequential)

---

## Rejected Alternative

Link to decision that led to rejection.

```json
{
  "id": "RA-001",
  "alternative": "Use Redis for caching",
  "rejection_reason": "Team has no Redis ops experience",
  "decision_ref": "DL-001"
}
```

---

## Constraint

```json
{
  "id": "C-001",
  "type": "technical|organizational|dependency",
  "description": "Must use Python 3.10+",
  "source": "user-specified|doc-derived|inferred"
}
```

---

## Known Risk

```json
{
  "id": "R-001",
  "risk": "API rate limits may cause timeouts",
  "mitigation": "Implement exponential backoff",
  "anchor": "src/client.py:L45-L60",
  "decision_ref": "DL-002"
}
```

---

## Invisible Knowledge

Knowledge that should transfer to future LLM sessions.

```json
{
  "architecture": {
    "diagram_ascii": "Client --> Gateway --> Services",
    "description": "Request routing pattern..."
  },
  "data_flow": {
    "diagram_ascii": "Input -> Validate -> Transform -> Store",
    "description": "Data pipeline..."
  },
  "structure_rationale": "Why we organized code this way...",
  "invariants": [
    "All public APIs must validate input before processing",
    "Database connections must use connection pooling"
  ],
  "tradeoffs": [
    "Chose simplicity over performance for initial implementation",
    "Using sync IO to avoid complexity; can migrate to async later"
  ]
}
```

---

## Milestone

```json
{
  "id": "M-001",
  "number": 1,
  "name": "Implement rate limiter",
  "files": ["src/ratelimit.py", "tests/test_ratelimit.py"],
  "flags": ["error-handling", "needs-rationale"],
  "requirements": ["Limit to 100 requests per minute per client"],
  "acceptance_criteria": ["Test demonstrates rate limiting behavior"],

  "tests": [
    "unit: under limit requests succeed",
    "unit: exactly at limit is allowed; one over returns 429"
  ],
  "integration_tests": [
    "against the real Redis: two app instances share one client's window"
  ],
  "live_checks": [
    "as an API client on the deployed service, the 101st request in a minute returns 429 with Retry-After"
  ],

  "code_intents": [...],

  "is_documentation_only": false,
  "delegated_to": null
}
```

---

## Code Intent

Architect populates. Describes WHAT, not HOW.

```json
{
  "id": "CI-M-001-001",
  "file": "src/ratelimit.py",
  "function": "check_rate_limit",
  "behavior": "Return True if request allowed, False if rate limited. Use sliding window algorithm.",
  "decision_refs": ["DL-001"],
  "params": {
    "window_size": {
      "value": 60,
      "unit": "seconds",
      "decision_ref": "DL-002"
    }
  }
}
```

ID format: `CI-{milestone_id}-###`

---

## Verification fields

Set with `set-verification` (repeatable `--integration-test` / `--live-check`,
or JSON lists in batch mode).

- `tests`: unit scenarios. Free-form strings.
- `integration_tests`: tests against the REAL dependency, run as the identity
  production uses. Required when a milestone touches SQL, schema, access
  policies, tenant/ownership scope, or acts on behalf of another party.
  These catch what mocked unit tests cannot: wrong column names, missing
  casts, enum/text comparisons, row-level-security denials.
- `live_checks`: observable, role-specific steps on the deployed system
  ("as <role>, do X, see Y"). Required when a user can see or do anything
  differently. The executor turns each into one item of qr-impl-live.json.

There are no `code_changes` (planned diffs) or planned `documentation` in the
lean planner: developers implement from `code_intents`, and documentation is
written once, after implementation (executor steps 9-12).

---

## Milestone Dependencies

```json
{
  "diagram_ascii": "M-001 --> M-002\n        \\--> M-003\nM-002 --> M-004\nM-003 --> M-004",
  "waves": [
    { "wave": 1, "milestones": ["M-001"] },
    { "wave": 2, "milestones": ["M-002", "M-003"] },
    { "wave": 3, "milestones": ["M-004"] }
  ]
}
```

---

## Validation Rules

### Reference Integrity

1. `code_intent.decision_refs[]` entries must exist (below)
2. `inline_comment.decision_ref` must point to existing `decision_log.id`
3. `code_intent.decision_refs[]` must point to existing `decision_log.id`
4. `rejected_alternative.decision_ref` must point to existing `decision_log.id`
5. `known_risk.decision_ref` must point to existing `decision_log.id`
6. `inline_comment.decision_ref` must point to existing `decision_log.id`

### Phase Completeness

**plan-design** (Architect) -- the only planning phase:

- `overview.problem` required
- At least one milestone
- Each milestone (unless documentation-only) has at least one `code_intent`
- Each milestone has `acceptance_criteria`
- Verification coverage (integration_tests / live_checks) is judged by the
  plan-design reviewer, not by the validator

---

## Temporal Contamination

All string fields must avoid:

1. **Change-relative**: "will be added", "new function", "modified to"
2. **Baseline reference**: "original", "existing", "current"
3. **Location directive**: "see below", "above section"
4. **Planning artifact**: "TODO", "FIXME", "implement later"
5. **Intent leakage**: "should", "needs to", "must be implemented"

Write as if code already exists in final state.
