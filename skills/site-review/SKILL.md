---
name: site-review
description: End-to-end site quality audit - analyzes codebase and navigates site in browser to find UI/UX issues, bugs, best practice violations, and improvement opportunities. Invoke when user wants to review, audit, inspect, or check their site/app in the browser.
---

# Site Review

When this skill activates, IMMEDIATELY invoke the script. The script IS the workflow.

Invoke:

<invoke working-dir=".claude/skills/scripts" cmd="python3 -m skills.site_review.review --step 1" />

Do NOT explore or analyze first. Run the script and follow its output.
