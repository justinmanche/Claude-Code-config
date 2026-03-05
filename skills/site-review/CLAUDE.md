# site-review/

End-to-end site quality audit skill. Combines codebase analysis with browser
navigation to find UI/UX issues, bugs, and improvement opportunities.

## Files

| File        | What                              | When to read             |
| ----------- | --------------------------------- | ------------------------ |
| `SKILL.md`  | Skill invocation                  | Using this skill         |
| `README.md` | Architecture, workflow, rationale | Understanding the design |

Python code: `scripts/skills/site_review/review.py` (orchestrator),
`inspect_agent.py` (per-page inspection sub-agent),
`verify_agent.py` (code verification sub-agent)
