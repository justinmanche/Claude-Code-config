---
description: Retell conversation flow JSON guardrails
---

When the user asks to create, review, fix, or modify a Retell conversation flow JSON:

- Prefer editing files over pasting JSON
- Keep JSON strictly valid
- Ensure start_node_id exists and destinations exist
- Avoid cycles unless explicitly requested
- After edits, run the retell lint + (optional) API validate scripts and fix failures

