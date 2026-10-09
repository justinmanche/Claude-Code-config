# 08 — Delivery and git

Applies to branching, committing, merging, releasing, deploying and rolling back. The measures that matter are DORA's: lead time, deployment frequency, time to recover from a failed deployment, change failure rate, and rework rate. Speed and stability are not a trade-off; AI-assisted work raises throughput and, without strong feedback loops, lowers stability.

Contents: 1 Batches and branches · 2 Gates · 3 Commits · 4 Merging · 5 Releasing and rollback · 6 Feature flags · 7 Repository hygiene · 8 Sources

## 1. Batches and branches

**DELIV-01** MUST work in small batches: a branch lives a day or two, each change is deployable and revertible on its own. A change that cannot be described in one sentence is two changes.

**DELIV-02** SHOULD branch from `main` into a separate worktree for anything beyond a one-line fix, so another session's checkout is never switched underneath it. Name branches `type/short-slug` (`fix/vendor-invite-expiry`, `feat/product-filter`, `chore/…`, `docs/…`).

**DELIV-03** AVOID long-lived feature branches and big-bang merges. If a branch is older than a week, split what is done and merge it.

## 2. Gates

**DELIV-04** MUST run the same automated gates before every merge and deploy, whether in CI or a local script: secret scan, type check, lint, unit suites, dependency audit, migration check, image build, post-deploy smoke test. The deploy script and the pipeline run the same commands.

**DELIV-05** MUST make any skipped gate explicit and logged (a flag on the command, recorded in the deploy output), never a silent default. The secret scan and the dependency audit are never skippable.

**DELIV-06** MUST keep every commit on `main` building and passing, so `git bisect` and `git revert` keep working.

**DELIV-21** MAY run the full suites only in CI on the pull request instead of locally, when the project sets `merge_via_pr` in `.claude/dev-policy.json`. Then every merge into `main` goes through a pull request whose required CI check passed on its current head, and locally you run only the tests covering your change (the changed or added test files, `jest --findRelatedTests`, `vitest related`). The hooks deny a local merge into `main`, a push that updates `main`, and `gh pr merge` while the check is pending, failed or missing (or `gh` cannot be asked). Where the host offers branch protection, use that too; the hook exists for plans that do not. Keep CI to one consolidated job and let a docs-only pull request finish green quickly inside the job (no workflow-level path filter, which would leave no status to read).

## 3. Commits

**DELIV-07** MUST write commit messages as Conventional Commits: `type(scope): imperative summary` with types `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `build`, `ci`; `!` or a `BREAKING CHANGE:` footer for breaking changes. Subject ≤ 72 characters.

**DELIV-08** MUST explain *why* and the user-visible effect in the body, not recap the diff. Reference the issue. A reader doing archaeology in a year has only this.

**DELIV-09** AVOID pushing "wip" or "fix typo" commits to `main`; squash them on the branch first. MUST NOT rewrite published history on `main`.

## 4. Merging

**DELIV-10** SHOULD pick one merge strategy per repository and write it down. `--no-ff` merges of a cleaned-up branch keep the grouping visible; squash merges give one commit per change. Either is fine; mixing them is not.

**DELIV-11** MUST delete the branch locally and on the remote in the same step as the merge, and remove its worktree. Only `main` and bot branches exist between pieces of work.

**DELIV-12** MUST self-review the whole diff before merging: read every hunk, run the tests, remove debug output, confirm the diff contains only the intended change, check the test diff before the code diff.

## 5. Releasing and rollback

**DELIV-13** MUST build once and promote the same immutable image (tagged by git SHA) through every environment. No per-environment builds.

**DELIV-14** MUST have a rehearsed rollback for application code (redeploy the previous image tag) and roll forward for the schema (`04-data-and-migrations.md`, DATA-08). Know which one applies before deploying, not during the incident.

**DELIV-15** SHOULD keep a human-readable changelog (Keep a Changelog sections) generated from the conventional commits. Version with semantic versioning only for things with external consumers; a single-deploy service can use the SHA or a date.

**DELIV-16** MUST verify every deploy at the user's layer (`06-testing.md`, TEST-32) and record what was verified.

## 6. Feature flags

**DELIV-17** SHOULD separate deploying code from releasing a feature with a flag when the work spans more than one deploy. Classify each flag (release, operational kill-switch, permission).

**DELIV-18** MUST give every release flag an owner and a removal condition at the point it is defined. Flags are debt; remove them once fully on.

## 7. Repository hygiene

**DELIV-19** MUST NOT leave work parked: no stashes at the end of a turn, no tags, no idle merged branches, no untracked files, no plan document without an active-plan header. Finished means closed (decisions explained beside the code, risks registered, leftovers in issues, files deleted).

**DELIV-20** MUST keep the repository in a state where a new session, human or agent, can start from the index files alone: build and test commands correct, docs matching the code, nothing described as "in progress" that is not.

## 8. Sources

- DORA metrics guide (2024–25): https://dora.dev/guides/dora-metrics/
- 2025 DORA report announcement, Google Cloud (Sep 2025): https://cloud.google.com/blog/products/ai-machine-learning/announcing-the-2025-dora-report
- Trunk-based development, DORA capability: https://dora.dev/capabilities/trunk-based-development/
- Conventional Commits 1.0.0: https://www.conventionalcommits.org/en/v1.0.0/
- How to write a git commit message, Beams (2014): https://cbea.ms/git-commit/
- Keep a Changelog 1.1.0: https://keepachangelog.com/en/1.1.0/
- Semantic Versioning 2.0.0: https://semver.org/
- Small CLs, Google engineering practices: https://google.github.io/eng-practices/review/developer/small-cls.html
- Feature toggles, Hodgson (2017): https://martinfowler.com/articles/feature-toggles.html
