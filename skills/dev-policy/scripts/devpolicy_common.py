"""Shared helpers for the dev-policy check script and hook.

Everything here is read-only against the repository except write_stamp(), which
writes one JSON file under the repository's git directory.
"""
import hashlib
import json
import os
import re
import subprocess

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATHS = os.path.join(SKILL_DIR, "paths.default.json")
STAMP_NAME = "dev-policy-check.json"

DEFAULT_CONFIG = {
    "overlay": [],
    "codePaths": [],  # empty = whole repo minus the exclusions below
    "excludePaths": ["node_modules/", "dist/", "build/", "coverage/", ".git/", "generated/"],
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
    """Run a command; return (exit_code, combined_output). Never raises."""
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
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
    for key in ("overlay", "codePaths", "excludePaths"):
        if key in user:
            cfg[key] = user[key]
    if "paths" in user:
        cfg["paths"] = list(user["paths"]) + cfg["paths"]
    if "checks" in user:
        cfg["checks"].update(user["checks"])
    return cfg


def relpath(root, path):
    try:
        rel = os.path.relpath(os.path.abspath(path), root)
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
    for ex in cfg.get("excludePaths", []):
        if rel.startswith(ex) or f"/{ex}" in f"/{rel}":
            return False
    inc = cfg.get("codePaths") or []
    if not inc:
        return True
    return any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in inc)


def merge_base(root):
    """The commit everything is compared against: merge-base with origin/main (or main), else HEAD."""
    for ref in ("origin/main", "origin/master", "main", "master"):
        code, _ = run(["git", "rev-parse", "--verify", "-q", ref], root)
        if code == 0:
            code, out = run(["git", "merge-base", "HEAD", ref], root)
            if code == 0 and out.strip():
                return out.strip()
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
