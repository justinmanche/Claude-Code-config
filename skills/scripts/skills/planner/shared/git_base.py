"""Base-commit preamble for agents that may run in an isolated git worktree.

WHY: Claude Code creates a subagent's isolated worktree from the remote default
branch (origin/main). Nothing is pushed during a run by default, so an agent
dispatched for wave 3 starts from code that lacks waves 1 and 2. The dispatch
text therefore carries the exact commit the agent must be on top of, computed
from the LOCAL main tip at the moment the step prints, plus the command that
brings a stale worktree up to it (or stops the agent if it cannot).

Git is invoked with list arguments (no shell) and never mutates the repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

BASE_BRANCH_CANDIDATES = ("main", "master")


def _git(repo: str, *args: str) -> str | None:
    """Run a read-only git command in repo; None on any failure."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def git_toplevel(path: str) -> str | None:
    """Repository root containing path, or None when path is not in a repo."""
    if not path or not Path(path).is_dir():
        return None
    return _git(path, "rev-parse", "--show-toplevel")


def resolve_repo_path(explicit: str | None, plan: dict, cwd: str) -> str | None:
    """Pick the plan's repository: --repo, then plan.json repo_path, then cwd's repo."""
    for candidate in (explicit, plan.get("repo_path"), cwd):
        if candidate:
            top = git_toplevel(str(Path(candidate).expanduser()))
            if top:
                return top
    return None


def base_tip(repo: str) -> tuple[str, str] | None:
    """(branch, sha) of the local main tip in repo; main preferred over master."""
    for branch in BASE_BRANCH_CANDIDATES:
        sha = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}")
        if sha:
            return branch, sha
    return None


BASE_COMMIT_PREAMBLE = """\
BASE COMMIT (mandatory; do this BEFORE the invoke command below, in your own
repository worktree, not in the skills directory):
  FIRST: `git merge-base --is-ancestor {sha} HEAD || git merge --ff-only {branch}`
  You must be on top of {sha} (the tip of local {branch} when this was dispatched).
  Re-run the merge-base check after any merge; it must succeed. If the
  fast-forward fails, STOP and report -- do not start the task."""

BASE_COMMIT_UNKNOWN = """\
BASE COMMIT: unknown -- the plan's repository was not resolved, so no commit
could be named. If you were started in an isolated worktree, verify you can see
the work of earlier waves (git log --oneline -5) before you start; if not,
STOP and report."""


def base_commit_preamble(repo: str | None) -> str:
    """Mandatory preamble naming the commit the agent must be on top of.

    Falls back to BASE_COMMIT_UNKNOWN (never raises) when the repository or its
    main branch cannot be resolved, so a dispatch is never blocked by this check.
    """
    tip = base_tip(repo) if repo else None
    if not tip:
        return BASE_COMMIT_UNKNOWN
    branch, sha = tip
    return BASE_COMMIT_PREAMBLE.format(sha=sha, branch=branch)
