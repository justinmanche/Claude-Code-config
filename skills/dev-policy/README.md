# dev-policy

## Overview

A development policy for one developer working with an AI coding agent across several TypeScript/Node/React/PostgreSQL products. It exists because policy that lives only in a human's head is invisible to the agent, and policy that lives in one long file is ignored by it. The policy is split by topic, loaded by relevance, and backed by mechanical checks for everything that can be checked.

## Architecture

Three mechanisms, each doing what the others cannot:

- **Skill (`SKILL.md` + `policy/`)** — the rules and their reasons, loaded on demand. The router is short; sections are one level deep so they are read whole, not skimmed with `head`.
- **Hooks (`scripts/policy_hook.py`)** — zero-context-cost guarantees. SessionStart prints a digest; PostToolUse maps an edited file to its sections and injects a one-line pointer the first time each section applies in a session; the hard gates (`policy_gate.py`) deny merge-into-main, push and deploy until the check has passed on the exact committed tree (and, in the opt-in merge-via-PR mode, merge into main only through a pull request whose CI check passed); SubagentStop checks a subagent that changed code and blocks it once; one quiet Stop hook speaks only after a reply in which the main session itself edited code with nothing running. A git `pre-push` hook applies the push rule to anyone. Hooks are wired per project in `.claude/settings.json`, so a project opts in deliberately.
- **Check script (`scripts/check.py`)** — the definition of done that does not depend on the agent's honesty: type check, lint, forbidden patterns on *added* lines only (legacy occurrences are not punished), weakened or missing tests, unknown dependencies, audit, secret scan, edited migrations. It writes a stamp keyed by a fingerprint of the changed code (for the working state) and, for a clean tree, one keyed by the git tree hash of HEAD, shared by every worktree through the common git directory (for the gates).

Path-scoped project rules (`.claude/rules/*.md` with `paths:`) are the fourth, optional layer: they load when a matching file is merely *read*, which the hook cannot do.

## Design decisions

- **Separate from `~/.claude/conventions/`.** Those files are review prompts: how a quality-reviewer agent detects smells, organised by cognitive mode and consumed by the planner's scripts through `REGISTRY.yaml`. This policy is the statement of what is required and why, written for whoever is doing the work. The code-quality section points at the conventions for detection detail rather than duplicating them.
- **Tier 3, below project docs.** A project's documented conventions win even where the policy prefers something else, because consistency inside a codebase is worth more than a marginally better pattern introduced once. Divergences are surfaced, not silently overridden either way.
- **Stable rule ids.** They make citations checkable and let a commit or plan name what it applied. They are never used as shorthand to the owner, who has said plainly that ids mean nothing without the words.
- **Added-lines-only pattern checks.** Legacy code carries `any` and lint-disables; failing the check on their mere presence would make it unusable. The check fails on what this change introduced.
- **Gate at hand-off, by tree hash, not at every reply.** The first design blocked the end of every reply until the check had passed on the current working state. An orchestrating session whose background agents keep editing the shared checkout changes that state between runs and was blocked ~10 status replies in a row. The gates now sit at the moments code leaves the owner's hands (merge into main, push, deploy) and ask a question that has a stable answer: has this exact committed tree passed? That is why `check.py` records the git tree hash of HEAD for a clean tree. Running the check on main before a merge is meaningless (no diff), so the merge gate looks up the incoming branch's tree. A transcript can be gamed or split across sessions; a tree hash is a property of the repository. Transcripts are still used where they are the right witness: whether the session itself edited code or ran a test command.
- **The end-of-reply hook is quiet by design.** No reminders or advice: it blocks only when the main session edited code since the last user message, nothing is running in the background, and the check is stale / tests were not run / a hygiene must-fix exists; it never repeats a block for a state it already reported. Agents running is read from the Stop payload's `background_tasks`, falling back to a locked worktree under `.claude/worktrees` whose recorded process is alive.
- **Agent self-check once, then let it report.** A subagent that changed code is checked on its own working directory (its sidecar `agent-<id>.meta.json` names the worktree) and blocked once with the failures. Blocking it again would loop on a failure it may not be allowed to fix; the second stop passes so the failure reaches the caller in its report. Subagents that report through `SubagentHandback` have already delivered by the time SubagentStop fires, so the same check also runs as a PreToolUse hook on that tool.
- **Opt-in merge-via-pull-request mode (2026-10-09).** Some projects want the full suites to run only in CI and every merge to go through a pull request, but sit on a plan where the host offers no branch protection (a private GitHub Free repository: the rulesets API answers 403). `merge_via_pr` in `.claude/dev-policy.json` turns the local gate into the enforcement. With it set: `git merge <ref>` while on the protected branch is denied (merging the remote copy of the branch, `origin/main`, to sync after a PR merge is allowed); a `git push` that updates the protected branch is denied (explicit name, `HEAD:main`, `feature:main`, `--all`/`--mirror`, or a bare push while on it), in the Bash gate and in the git `pre-push` hook; `gh pr merge [<number|branch>]` is allowed only when `gh pr view --json headRefOid,statusCheckRollup,...` shows the required check concluded `SUCCESS` on the PR's current head (the newest run wins when a check was re-run), and denied with the state named (pending / failed / missing) otherwise. It fails CLOSED: if `gh` is missing, unauthenticated, offline, times out or returns anything unparseable, the merge is denied, unlike the other gates which fail open when the hook itself breaks. A pull request into some other branch, or one that is not open, is not this gate's business. Pushing any other branch keeps the check.py rule. The gate is a guard rail for agents and habit, not a security boundary (a person at a plain terminal can still run git or `--no-verify`). The test reminders change with the mode only in wording: run the tests that cover your change; the full suites run in CI.
- **Fail open.** A gate that crashes allows the action silently (set `DEV_POLICY_DEBUG=1` to see why); a hook error on every command would be worse than a missed check. The git hook is bypassed deliberately with `--no-verify`.
- **Sources with dates.** Every section ends with where its rules came from, so a rule can be re-checked when the source moves (the OWASP Top 10, NIST password guidance and npm security all changed in 2025).

## Invariants

- A project opts in by wiring the hooks and creating `.claude/dev-policy.json`; nothing here runs in a repository that did not.
- `check.py` never modifies the repository. It reads, runs read-only commands, prints, and writes one stamp file under `.git/`.
- Hooks never block on soft findings (WARN). Gates deny only on a missing or failing check for the exact tree, a dirty or worktree-littered deploy, or implementation code with no test run on record.
- `.claude/worktrees/` is never part of the change: it is excluded from the check's file list, fingerprint and cleanliness test whatever a project configures.
- Policy text states rules; project overlays state overrides; neither restates the other.

## Project overlay template (`.claude/dev-policy.json`)

```json
{
  "overlay": [
    { "doc": "docs/development-guidelines.md", "note": "Tier-2 project rules; they override the policy's generic preferences" }
  ],
  "codePaths": ["backend/src", "frontend/src", "e2e", "infra", "deploy", "openapi.yaml"],
  "paths": [
    { "pattern": "^backend/src/ai/", "sections": ["05-security", "12-privacy-and-compliance"] }
  ],
  "checks": {
    "typecheck": [
      { "when": "^backend/", "cmd": "npx tsc --noEmit -p backend/tsconfig.json" },
      { "when": "^frontend/", "cmd": "npx tsc --noEmit -p frontend/tsconfig.json" }
    ],
    "serverCode": "^backend/src/(?!scripts/)",
    "testPairs": [
      { "src": "^backend/src/(?!__tests__|__integration__|migrations|scripts)", "test": "^backend/src/(__tests__|__integration__)/" },
      { "src": "^frontend/src/(?!.*(test|spec))", "test": "^frontend/src/.*(test|spec)" }
    ],
    "migrationsDir": "backend/src/migrations",
    "contractPairs": [ { "src": "^backend/src/routes/", "doc": "openapi.yaml" } ]
  }
}
```

Every key is optional; `check.py` has defaults that work for a plain npm workspace repository. `implPaths` (regex) names the implementation code that must have a test run on record (default: any `src/` directory). `merge_via_pr` (default off) is `{"branch": "main", "required_check": "validate"}`: merges into `branch` only via a pull request whose CI check `required_check` passed (see Design decisions).

## Change log

- 2026-10-09 — Opt-in merge-via-pull-request mode (`merge_via_pr`): deny `git merge` into and `git push` to the protected branch, allow `gh pr merge` only when the required CI check succeeded on the PR head (fail closed). Test reminders reworded to "run the tests that cover your change; the full suites run in CI" (a test command must still be on record after an implementation edit). `gh` is mocked through PATH in the Risky hook tests.

- 2026-10-07 (later) — Enforcement moved from "every reply" to the hand-off boundaries: `policy_gate.py` (PreToolUse gate on merge/push/deploy, SubagentStop and SubagentHandback self-check, the single quiet Stop hook, git `pre-push`), tree-hash stamps in `check.py`, `.claude/worktrees/` excluded from checks, `implPaths` config key. Tests live in the project (Risky: `scripts/test-policy-hooks.sh`).
- 2026-10-07 — First version. Thirteen sections written from five research briefs (code principles and architecture; testing and review; security and privacy; delivery, DevOps and data; AI-assisted workflow) plus the Risky project's existing guidelines and the owner's recorded working preferences.
