"""Shared helpers for the dev-policy check script and hook.

Everything here is read-only against the repository except write_stamp(), which
writes one JSON file under the repository's git directory.
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATHS = os.path.join(SKILL_DIR, "paths.default.json")
STAMP_NAME = "dev-policy-check.json"
TREE_STAMPS_NAME = "dev-policy-tree-stamps.json"
TREE_STAMPS_KEEP = 300
# Agent worktrees live here. Their files are a second copy of the repository (plus
# run-generated files such as e2e login state); they are never part of the change
# being checked, whatever codePaths/excludePaths a project configures.
WORKTREES_PREFIX = ".claude/worktrees/"

DEFAULT_CONFIG = {
    "overlay": [],
    "codePaths": [],  # empty = whole repo minus the exclusions below
    "implPaths": "",  # regex: implementation (non-test) code that must have a test run on record; empty = any src/ directory
    "merge_via_pr": None,  # opt-in {"branch": "main", "required_check": "validate"}: merges only via a PR whose CI check passed
    "excludePaths": ["node_modules/", "dist/", "build/", "coverage/", ".git/", "generated/", ".claude/worktrees/"],
    "paths": [],
    "checks": {
        "typecheck": [],      # [{"when": regex, "cmd": "..."}]; empty = auto-detect tsconfig.json per top-level dir
        "lint": "npx eslint",  # applied to changed .ts/.tsx/.js/.mjs/.cjs files when an eslint config exists
        "serverCode": "",     # regex for server code where console.log is forbidden; empty = skip that pattern
        "testPairs": [],      # [{"src": regex, "test": regex}]
        "migrationsDir": "",  # e.g. backend/src/migrations
        "contractPairs": [],  # [{"src": regex, "doc": path}]
    },
}


def run(cmd, cwd, timeout=600):
    """Run a command; return (exit_code, combined_output). Never raises.

    stdin is closed: no check command reads input, and inheriting the hook's stdin made
    a child that drains it (repo-hygiene.sh) wait out its read timeout on every call.
    """
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except Exception as exc:
        return 1, str(exc)


def repo_root(cwd=None):
    code, out = run(["git", "rev-parse", "--show-toplevel"], cwd or os.getcwd())
    return out.strip() if code == 0 and out.strip() else None


def git_dir(root):
    code, out = run(["git", "rev-parse", "--git-dir"], root)
    gd = out.strip()
    return gd if os.path.isabs(gd) else os.path.join(root, gd)


def load_config(root):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(DEFAULT_PATHS) as fh:
            cfg["paths"] = json.load(fh).get("paths", [])
    except Exception:
        pass
    proj = os.path.join(root, ".claude", "dev-policy.json")
    try:
        with open(proj) as fh:
            user = json.load(fh)
    except Exception:
        return cfg
    for key in ("overlay", "codePaths", "excludePaths", "implPaths", "merge_via_pr"):
        if key in user:
            cfg[key] = user[key]
    if "paths" in user:
        cfg["paths"] = list(user["paths"]) + cfg["paths"]
    if "checks" in user:
        cfg["checks"].update(user["checks"])
    return cfg


def relpath(root, path):
    try:
        # realpath on both sides: git reports the resolved top-level (/private/var on macOS)
        # while tool inputs may carry the symlinked spelling (/var).
        rel = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    return rel.replace(os.sep, "/")


def sections_for(rel, cfg):
    out = []
    for entry in cfg.get("paths", []):
        try:
            if re.search(entry["pattern"], rel):
                for s in entry.get("sections", []):
                    if s not in out:
                        out.append(s)
        except re.error:
            continue
    return out


def is_code_path(rel, cfg):
    if rel.startswith(WORKTREES_PREFIX) or f"/{WORKTREES_PREFIX}" in f"/{rel}":
        return False
    for ex in cfg.get("excludePaths", []):
        if rel.startswith(ex) or f"/{ex}" in f"/{rel}":
            return False
    inc = cfg.get("codePaths") or []
    if not inc:
        return True
    return any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in inc)


def _nearest_base(root, tip):
    """Merge-base of `tip` with the most recent of origin/main, origin/master, main, master.

    Taking origin/main first was wrong whenever local main is ahead of it (merged but not
    pushed): every unpushed merge then counted as a change of the branch being checked.
    """
    bases = []
    for ref in ("origin/main", "origin/master", "main", "master"):
        code, _ = run(["git", "rev-parse", "--verify", "-q", ref], root)
        if code == 0:
            code, out = run(["git", "merge-base", tip, ref], root)
            if code == 0 and out.strip():
                bases.append(out.strip())
    best = None
    for b in bases:
        # b is newer than best when best is an ancestor of b.
        if best is None or run(["git", "merge-base", "--is-ancestor", best, b], root)[0] == 0:
            best = b
    return best


def merge_base(root):
    """The commit everything is compared against: merge-base with the newest main, else HEAD."""
    base = _nearest_base(root, "HEAD")
    if base:
        return base
    code, out = run(["git", "rev-parse", "HEAD"], root)
    return out.strip() if code == 0 else "HEAD"


def changed_files(root, cfg):
    """Files changed since the merge base (committed, staged, unstaged) plus untracked, limited to code paths."""
    base = merge_base(root)
    files = set()
    code, out = run(["git", "diff", "--name-only", base], root)
    if code == 0:
        files |= set(l.strip() for l in out.splitlines() if l.strip())
    code, out = run(["git", "ls-files", "--others", "--exclude-standard"], root)
    if code == 0:
        files |= set(l.strip() for l in out.splitlines() if l.strip())
    rel = sorted(f for f in files if is_code_path(f, cfg))
    return base, rel


def added_lines(root, base, rel):
    """Lines added by this change for one file (untracked files count whole)."""
    full = os.path.join(root, rel)
    code, out = run(["git", "ls-files", "--error-unmatch", rel], root)
    if code != 0:  # untracked
        try:
            with open(full, errors="replace") as fh:
                return [l.rstrip("\n") for l in fh]
        except OSError:
            return []
    code, out = run(["git", "diff", base, "--", rel], root)
    if code != 0:
        return []
    return [l[1:] for l in out.splitlines() if l.startswith("+") and not l.startswith("+++")]


_REASONED_ANY_DISABLE = re.compile(r"eslint-disable(?:-next-line|-line)?\b[^\n]*no-explicit-any[^\n]*--\s*\S")


def _added_line_numbers(root, base, rel):
    """1-based line numbers of the file's current text that this change added (None = whole file)."""
    code, _ = run(["git", "ls-files", "--error-unmatch", rel], root)
    if code != 0:
        return None
    code, out = run(["git", "diff", "-U0", base, "--", rel], root)
    if code != 0:
        return set()
    added = set()
    for m in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", out, re.M):
        start, count = int(m.group(1)), int(m.group(2) or "1")
        added.update(range(start, start + count))
    return added


def first_unjustified_any(root, base, rel, rx):
    """Line number of the first added line matching `rx` that no reasoned no-explicit-any
    disable covers (same line `eslint-disable-line`, or the line above `-next-line`), else None."""
    try:
        with open(os.path.join(root, rel), errors="replace") as fh:
            lines = fh.read().split("\n")
    except OSError:
        return None
    added = _added_line_numbers(root, base, rel)
    for n, line in enumerate(lines, start=1):
        if added is not None and n not in added:
            continue
        if not rx.search(line):
            continue
        prev = lines[n - 2] if n >= 2 else ""
        if _REASONED_ANY_DISABLE.search(line) or ("next-line" in prev and _REASONED_ANY_DISABLE.search(prev)):
            continue
        return n
    return None


def multiline_matches_on_added(root, base, rel, rx):
    """True when `rx` matches somewhere in the file's current text AND the match covers an added line.

    Multi-line patterns (an empty `catch {}` split over lines) cannot be matched on the added
    lines alone: joining them glued an added `} catch (e) {` to an unrelated added `}` further
    down, and a match whose closing brace is an unchanged line was missed entirely.
    """
    try:
        with open(os.path.join(root, rel), errors="replace") as fh:
            text = fh.read()
    except OSError:
        return False
    code, _ = run(["git", "ls-files", "--error-unmatch", rel], root)
    if code != 0:  # untracked: every line is new
        return rx.search(text) is not None
    code, out = run(["git", "diff", "-U0", base, "--", rel], root)
    if code != 0:
        return False
    added = set()
    for m in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", out, re.M):
        start, count = int(m.group(1)), int(m.group(2) or "1")
        added.update(range(start, start + count))
    if not added:
        return False
    for m in rx.finditer(text):
        first = text.count("\n", 0, m.start()) + 1
        last = first + m.group(0).count("\n")
        if any(n in added for n in range(first, last + 1)):
            return True
    return False


def removed_lines(root, base, rel):
    code, out = run(["git", "diff", base, "--", rel], root)
    if code != 0:
        return []
    return [l[1:] for l in out.splitlines() if l.startswith("-") and not l.startswith("---")]


def fingerprint(root, cfg):
    """Hash of the full diff since the merge base plus untracked code files. Empty string if nothing changed."""
    base, files = changed_files(root, cfg)
    if not files:
        return "", []
    h = hashlib.sha1()
    code, out = run(["git", "diff", base, "--", *files], root)
    h.update(out.encode("utf-8", "replace"))
    for rel in files:
        code, _ = run(["git", "ls-files", "--error-unmatch", rel], root)
        if code != 0:
            h.update(rel.encode())
            try:
                with open(os.path.join(root, rel), "rb") as fh:
                    h.update(fh.read())
            except OSError:
                pass
    return h.hexdigest(), files


def stamp_path(root):
    return os.path.join(git_dir(root), STAMP_NAME)


def read_stamp(root):
    try:
        with open(stamp_path(root)) as fh:
            return json.load(fh)
    except Exception:
        return None


def write_stamp(root, data):
    try:
        with open(stamp_path(root), "w") as fh:
            json.dump(data, fh)
    except OSError:
        pass


# --- tree stamps -------------------------------------------------------------------
# The per-checkout stamp above answers "has the CURRENT working state passed?". The
# merge / push / deploy gates need a different question: "has this exact committed
# tree passed?", asked about a branch that may live in another worktree. So check.py
# also records, for a CLEAN working tree, the git tree hash of HEAD in a map shared by
# every worktree of the repository (the common git directory).

def git_common_dir(root):
    code, out = run(["git", "rev-parse", "--git-common-dir"], root)
    gd = out.strip()
    if code != 0 or not gd:
        return git_dir(root)
    return gd if os.path.isabs(gd) else os.path.normpath(os.path.join(root, gd))


def tree_of(root, ref):
    """Tree hash of a commit-ish, or "" when it does not resolve."""
    code, out = run(["git", "rev-parse", "--verify", "-q", f"{ref}^{{tree}}"], root)
    return out.strip() if code == 0 else ""


def head_tree(root):
    return tree_of(root, "HEAD")


def is_clean(root):
    """True when nothing differs from HEAD (tracked or untracked), ignoring agent worktrees."""
    code, out = run(["git", "status", "--porcelain", "--untracked-files=normal", "--",
                     ".", f":(exclude){WORKTREES_PREFIX.rstrip('/')}"], root)
    return code == 0 and not out.strip()


def merge_base_for(root, tip):
    """Like merge_base() but for an arbitrary tip instead of HEAD."""
    base = _nearest_base(root, tip)
    if base:
        return base
    code, out = run(["git", "rev-parse", tip], root)
    return out.strip() if code == 0 else tip


def code_files_between(root, cfg, base, tip):
    """Code-path files that differ between two commits."""
    code, out = run(["git", "diff", "--name-only", base, tip], root)
    if code != 0:
        return []
    return sorted(f for f in (l.strip() for l in out.splitlines()) if f and is_code_path(f, cfg))


def _tree_stamps_path(root):
    return os.path.join(git_common_dir(root), TREE_STAMPS_NAME)


def read_tree_stamps(root):
    try:
        with open(_tree_stamps_path(root)) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def lookup_tree_stamp(root, tree):
    return read_tree_stamps(root).get(tree)


def record_tree_stamp(root, tree, record):
    """Add or replace the stamp for one tree. Atomic; keeps only the newest TREE_STAMPS_KEEP."""
    if not tree:
        return
    path = _tree_stamps_path(root)
    try:
        import fcntl
        lock = open(path + ".lock", "a")
        fcntl.flock(lock, fcntl.LOCK_EX)
    except Exception:
        lock = None
    try:
        data = read_tree_stamps(root)
        data[tree] = record
        if len(data) > TREE_STAMPS_KEEP:
            newest = sorted(data.items(), key=lambda kv: kv[1].get("time", 0), reverse=True)[:TREE_STAMPS_KEEP]
            data = dict(newest)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tree-stamps-")
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except OSError:
        pass
    finally:
        if lock is not None:
            lock.close()


def passing(stamp):
    """A stamp that counts for a gate: a complete (typecheck + lint included) PASS."""
    return bool(stamp) and stamp.get("status") == "pass" and stamp.get("complete", True)
