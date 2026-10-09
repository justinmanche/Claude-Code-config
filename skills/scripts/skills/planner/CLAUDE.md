# planner/ (lean)

Planning and execution workflows: one deep review per gate, real-dependency
integration tests, live verification. Design: `~/.claude/skills/planner/INTENT.md`.

## Files

| File        | What                                          | When to read                          |
| ----------- | --------------------------------------------- | ------------------------------------- |
| `README.md` | Module map and step-to-script wiring          | Finding which script a step runs      |

## Subdirectories

| Directory           | What                                                        | When to read                          |
| ------------------- | ----------------------------------------------------------- | ------------------------------------- |
| `orchestrator/`     | planner.py (6 steps), executor.py (13 steps)                | Changing flow or step numbers         |
| `architect/`        | plan-design work + fix scripts                              | Changing what plans contain           |
| `developer/`        | milestone implementation, code fix, live fix                | Changing how code is written/fixed    |
| `technical_writer/` | post-implementation docs work + fix                         | Changing documentation pass           |
| `quality_reviewer/` | single-reviewer scripts, re-verify scripts, reconcile       | Changing what a gate checks           |
| `shared/`           | schema, constants, gates, routing; `dispatch.py` (guard rails on every agent prompt), `git_base.py` (base-commit preamble), `permissions.py` (permission and push text); `qr/` loop state + steps | Changing state files, gate mechanics or dispatch text |
| `cli/`              | plan.json and qr-{phase}.json mutation CLIs                 | Adding plan fields or QR commands     |

## State Files

| File              | What                                                   | Mutability          |
| ----------------- | ------------------------------------------------------ | ------------------- |
| `context.json`    | Planning context incl. `verification_env`              | frozen after step 2 |
| `plan.json`       | Milestones, code_intents, decisions, waves, `integration_tests`, `live_checks`; optional `repo_path`, `required_permissions`, `push_policy` (`set-execution-policy`) | mutable during planning |
| `qr-{phase}.json` | Verdict items + `awaiting_reverify` per gate           | ephemeral           |
| `exec-state.json` | Wave progress, `known_issues`, `repo_path` (executor Python only) | executor-owned      |
