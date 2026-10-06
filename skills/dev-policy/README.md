# dev-policy

## Overview

A development policy for one developer working with an AI coding agent across several TypeScript/Node/React/PostgreSQL products. It exists because policy that lives only in a human's head is invisible to the agent, and policy that lives in one long file is ignored by it. The policy is split by topic, loaded by relevance, and backed by mechanical checks for everything that can be checked.

## Architecture

Three mechanisms, each doing what the others cannot:

- **Skill (`SKILL.md` + `policy/`)** — the rules and their reasons, loaded on demand. The router is short; sections are one level deep so they are read whole, not skimmed with `head`.
- **Hooks (`scripts/policy_hook.py`)** — zero-context-cost guarantees. SessionStart prints a digest; PostToolUse maps an edited file to its sections and injects a one-line pointer the first time each section applies in a session; Stop refuses to end a turn while code has changed since the last passing check. Hooks are wired per project in `.claude/settings.json`, so a project opts in deliberately.
- **Check script (`scripts/check.py`)** — the definition of done that does not depend on the agent's honesty: type check, lint, forbidden patterns on *added* lines only (legacy occurrences are not punished), weakened or missing tests, unknown dependencies, audit, secret scan, edited migrations. It writes a stamp keyed by a fingerprint of the changed code; the Stop hook compares fingerprints.

Path-scoped project rules (`.claude/rules/*.md` with `paths:`) are the fourth, optional layer: they load when a matching file is merely *read*, which the hook cannot do.

## Design decisions

- **Separate from `~/.claude/conventions/`.** Those files are review prompts: how a quality-reviewer agent detects smells, organised by cognitive mode and consumed by the planner's scripts through `REGISTRY.yaml`. This policy is the statement of what is required and why, written for whoever is doing the work. The code-quality section points at the conventions for detection detail rather than duplicating them.
- **Tier 3, below project docs.** A project's documented conventions win even where the policy prefers something else, because consistency inside a codebase is worth more than a marginally better pattern introduced once. Divergences are surfaced, not silently overridden either way.
- **Stable rule ids.** They make citations checkable and let a commit or plan name what it applied. They are never used as shorthand to the owner, who has said plainly that ids mean nothing without the words.
- **Added-lines-only pattern checks.** Legacy code carries `any` and lint-disables; failing the check on their mere presence would make it unusable. The check fails on what this change introduced.
- **Stop-hook gating by fingerprint, not by transcript grepping.** A transcript can be gamed or split across sessions; a fingerprint of `git diff <merge-base>` plus untracked files is a property of the repository.
- **Sources with dates.** Every section ends with where its rules came from, so a rule can be re-checked when the source moves (the OWASP Top 10, NIST password guidance and npm security all changed in 2025).

## Invariants

- A project opts in by wiring the hooks and creating `.claude/dev-policy.json`; nothing here runs in a repository that did not.
- `check.py` never modifies the repository. It reads, runs read-only commands, prints, and writes one stamp file under `.git/`.
- The hook never blocks on soft findings; only the absence of a passing check for the current code state blocks a Stop.
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

Every key is optional; `check.py` has defaults that work for a plain npm workspace repository.

## Change log

- 2026-10-07 — First version. Thirteen sections written from five research briefs (code principles and architecture; testing and review; security and privacy; delivery, DevOps and data; AI-assisted workflow) plus the Risky project's existing guidelines and the owner's recorded working preferences.
