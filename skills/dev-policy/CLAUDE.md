# dev-policy/

## Files

| File | What | When to read |
|---|---|---|
| `SKILL.md` | Router: tier hierarchy, non-negotiables, section map, definition of done, commands | Starting any code, test, infra or doc work |
| `README.md` | Why the policy is shaped this way; relation to `conventions/` and project docs; overlay template; change log | Modifying the policy, wiring a new project |
| `paths.default.json` | Regex → section map used by the hook | Adding a section or a project path pattern |

## Subdirectories

| Directory | What | When to read |
|---|---|---|
| `policy/` | The thirteen policy sections (00–12), each with contents and sources | The section named by the hook, the router or the task |
| `scripts/` | `check.py` (definition-of-done checks, writes the working-state and per-tree stamps), `policy_hook.py` (SessionStart / PostToolUse / Stop entry points), `policy_gate.py` (merge / push / deploy gates, agent self-check, the quiet Stop logic, git pre-push; shell-command parser), `devpolicy_common.py` (shared helpers, stamps) | Running checks, debugging a hook, wiring a project |

## Run

```sh
python3 ~/.claude/skills/dev-policy/scripts/check.py            # definition-of-done checks for the current repo
python3 ~/.claude/skills/dev-policy/scripts/policy_hook.py report   # what the SessionStart hook prints
DEV_POLICY_DEBUG=1 python3 ~/.claude/skills/dev-policy/scripts/policy_gate.py pre-bash < payload.json   # why a gate allowed or failed open
```
