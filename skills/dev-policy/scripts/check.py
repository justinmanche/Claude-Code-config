#!/usr/bin/env python3
"""dev-policy definition-of-done checks.

Runs read-only checks against everything changed since the merge base (committed
on this branch, staged, unstaged, untracked), limited to the project's code paths,
and writes a stamp keyed by a fingerprint of that change so the Stop hook can tell
whether the current code state has passed.

Checks (each reports PASS / WARN / FAIL; FAIL makes the exit code non-zero):
  typecheck    tsc on each workspace with changed TypeScript (project config or auto-detect)
  lint         eslint on changed source files, when an eslint config exists
  patterns     forbidden constructs on ADDED lines only (legacy occurrences are not punished)
  tests        tests weakened (.only, deleted test files, removed assertions) or missing for changed source
  deps         new dependencies verified to exist in the registry; audit at high when manifests changed
  secrets      gitleaks over the working tree when installed
  migrations   an already-applied migration edited; a new migration numbered below the current maximum
  contract     routes changed without the API contract changing (warn)

Usage:  python3 ~/.claude/skills/dev-policy/scripts/check.py [--no-typecheck] [--no-lint] [--json]
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import devpolicy_common as dp  # noqa: E402

SRC_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
TEST_RE = re.compile(r"(\.test\.|\.spec\.|(^|/)__tests__/|(^|/)__integration__/|(^|/)e2e/|(^|/)tests?/)")

# (name, regex on an added line, severity, applies-to-tests?, message)
LINE_PATTERNS = [
    ("any", re.compile(r"(:\s*any\b|\bas\s+any\b|<any>)"), "FAIL", False, "new `any` (CODE-26) — use `unknown` and narrow, or justify inline"),
    ("ts-ignore", re.compile(r"@ts-ignore"), "FAIL", False, "`@ts-ignore` (CODE-27) — fix the type or use @ts-expect-error with a reason"),
    ("lint-disable-no-reason", re.compile(r"eslint-disable(?:-next-line|-line)?(?![^\n]*--\s*\S)"), "FAIL", True, "lint rule disabled without `-- reason` (CODE-31)"),
    ("empty-catch", re.compile(r"catch\s*(\([^)]*\))?\s*\{\s*\}"), "FAIL", False, "empty catch block (CODE-14) — handle, log with context, or explain why it is ignorable"),
    ("swallowed-promise", re.compile(r"\.catch\(\s*\(\s*[A-Za-z_]*\s*\)\s*=>\s*\{\s*\}\s*\)"), "FAIL", False, "`.catch(() => {})` swallows a failure (CODE-14, SEC-43)"),
    ("todo-no-issue", re.compile(r"\bTODO\b(?![^\n]*#\d+)"), "WARN", True, "TODO without an issue reference (CODE-18)"),
    ("dangerous-html", re.compile(r"dangerouslySetInnerHTML"), "FAIL", False, "dangerouslySetInnerHTML (SEC-23, FE-25) — sanitise and justify, or remove"),
    ("test-only", re.compile(r"\b(it|test|describe)\.only\("), "FAIL", True, "`.only` left in a test (TEST-29)"),
    ("test-skip", re.compile(r"\b(it|test|describe)\.skip\((?![^\n]*#\d+)"), "WARN", True, "`.skip` without an issue reference (TEST-29)"),
    ("hardcoded-secret", re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][A-Za-z0-9+/_\-]{16,}['\"]"), "WARN", False, "looks like a hard-coded credential (SEC-31) — confirm it is a fixture"),
]


class Report:
    def __init__(self):
        self.rows = []  # (check, status, detail)

    def add(self, check, status, detail=""):
        self.rows.append((check, status, detail))

    @property
    def failed(self):
        return any(s == "FAIL" for _, s, _ in self.rows)

    def render(self):
        width = max((len(c) for c, _, _ in self.rows), default=8)
        out = []
        for check, status, detail in self.rows:
            head = f"  {status:4} {check.ljust(width)}"
            if detail:
                lines = detail.rstrip().splitlines()
                out.append(f"{head}  {lines[0]}")
                out.extend(f"{' ' * (len(head) + 2)}{l}" for l in lines[1:])
            else:
                out.append(head)
        return "\n".join(out)


def is_test_file(rel):
    return bool(TEST_RE.search(rel))


def check_typecheck(root, cfg, changed, rep):
    ts_changed = [f for f in changed if f.endswith((".ts", ".tsx"))]
    if not ts_changed:
        rep.add("typecheck", "PASS", "no TypeScript changed")
        return
    entries = cfg["checks"].get("typecheck") or []
    if not entries:
        tops = sorted({f.split("/")[0] for f in ts_changed if "/" in f})
        for top in tops:
            if os.path.exists(os.path.join(root, top, "tsconfig.json")):
                entries.append({"when": f"^{re.escape(top)}/", "cmd": f"npx tsc --noEmit -p {top}/tsconfig.json"})
        if not entries and os.path.exists(os.path.join(root, "tsconfig.json")):
            entries.append({"when": ".", "cmd": "npx tsc --noEmit"})
    ran = False
    for e in entries:
        if any(re.search(e["when"], f) for f in ts_changed):
            ran = True
            code, out = dp.run(e["cmd"], root, timeout=900)
            tail = "\n".join(out.strip().splitlines()[-8:])
            rep.add("typecheck", "PASS" if code == 0 else "FAIL", f"{e['cmd']}" + ("" if code == 0 else f"\n{tail}"))
    if not ran:
        rep.add("typecheck", "WARN", "TypeScript changed but no tsconfig/typecheck command matched (configure checks.typecheck)")


def check_lint(root, cfg, changed, rep):
    files = [f for f in changed if f.endswith(SRC_EXT) and os.path.exists(os.path.join(root, f))]
    if not files:
        rep.add("lint", "PASS", "no lintable files changed")
        return
    has_cfg = any(os.path.exists(os.path.join(root, n)) for n in (".eslintrc.cjs", ".eslintrc.js", ".eslintrc.json", "eslint.config.js", "eslint.config.mjs")) \
        or any(os.path.exists(os.path.join(root, f.split("/")[0], n)) for f in files for n in (".eslintrc.cjs", ".eslintrc.js", ".eslintrc.json", "eslint.config.js", "eslint.config.mjs"))
    if not has_cfg:
        rep.add("lint", "WARN", "no eslint config found")
        return
    cmd = f"{cfg['checks'].get('lint', 'npx eslint')} {' '.join(files)}"
    code, out = dp.run(cmd, root, timeout=600)
    tail = "\n".join(out.strip().splitlines()[-12:])
    rep.add("lint", "PASS" if code == 0 else "FAIL", f"{len(files)} file(s)" + ("" if code == 0 else f"\n{tail}"))


def check_patterns(root, cfg, base, changed, rep):
    server_re = re.compile(cfg["checks"]["serverCode"]) if cfg["checks"].get("serverCode") else None
    findings = {"FAIL": [], "WARN": []}
    for rel in changed:
        if not rel.endswith(SRC_EXT):
            continue
        lines = dp.added_lines(root, base, rel)
        if not lines:
            continue
        test = is_test_file(rel)
        joined = "\n".join(lines)
        for name, rx, sev, applies_to_tests, msg in LINE_PATTERNS:
            if test and not applies_to_tests:
                continue
            if name == "empty-catch":
                if rx.search(joined):
                    findings[sev].append(f"{rel}: {msg}")
                continue
            for i, line in enumerate(lines):
                if rx.search(line):
                    findings[sev].append(f"{rel} (+{i + 1}): {msg}")
                    break
        if server_re and not test and server_re.search(rel):
            for i, line in enumerate(lines):
                if re.search(r"\bconsole\.(log|error|warn|info|debug)\(", line):
                    findings["FAIL"].append(f"{rel} (+{i + 1}): console.* in server code (OPS-07) — use the structured logger")
                    break
    if findings["FAIL"]:
        rep.add("patterns", "FAIL", "\n".join(findings["FAIL"] + findings["WARN"]))
    elif findings["WARN"]:
        rep.add("patterns", "WARN", "\n".join(findings["WARN"]))
    else:
        rep.add("patterns", "PASS", "no forbidden constructs on added lines")


def check_tests(root, cfg, base, changed, rep):
    fails, warns = [], []
    # Deleted test files.
    code, out = dp.run(["git", "diff", "--name-status", base], root)
    if code == 0:
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].startswith("D") and is_test_file(parts[-1]) and dp.is_code_path(parts[-1], cfg):
                warns.append(f"test file deleted: {parts[-1]} (TEST-29) — say why in the change description")
    # Net removal of assertions / cases in changed test files.
    for rel in changed:
        if not (rel.endswith(SRC_EXT) and is_test_file(rel)):
            continue
        added = dp.added_lines(root, base, rel)
        removed = dp.removed_lines(root, base, rel)
        for label, rx in (("expect(", re.compile(r"\bexpect\(")), ("it(/test(", re.compile(r"\b(it|test)\("))):
            n_add = sum(1 for l in added if rx.search(l))
            n_rem = sum(1 for l in removed if rx.search(l))
            if n_rem > n_add:
                warns.append(f"{rel}: net removal of {n_rem - n_add} `{label}` line(s) (TEST-29) — tests weakened? justify")
    # Source changed without any test change.
    pairs = cfg["checks"].get("testPairs") or []
    if pairs:
        test_changed = [f for f in changed if is_test_file(f)]
        for p in pairs:
            src_re, test_re = re.compile(p["src"]), re.compile(p["test"])
            srcs = [f for f in changed if f.endswith(SRC_EXT) and src_re.search(f) and not is_test_file(f)]
            if srcs and not any(test_re.search(t) for t in test_changed):
                warns.append("source changed with no test change (TEST-15, AI-11): " + ", ".join(srcs[:5]) + (" …" if len(srcs) > 5 else ""))
    if fails:
        rep.add("tests", "FAIL", "\n".join(fails + warns))
    elif warns:
        rep.add("tests", "WARN", "\n".join(warns))
    else:
        rep.add("tests", "PASS", "no weakened or missing tests detected")


def _deps_at(root, ref, manifest):
    if ref is None:
        try:
            with open(os.path.join(root, manifest)) as fh:
                data = json.load(fh)
        except Exception:
            return {}
    else:
        code, out = dp.run(["git", "show", f"{ref}:{manifest}"], root)
        if code != 0:
            return {}
        try:
            data = json.loads(out)
        except Exception:
            return {}
    deps = {}
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        deps.update(data.get(key, {}) or {})
    return deps


def check_deps(root, cfg, base, changed, rep):
    manifests = [f for f in changed if f.endswith("package.json") and "node_modules" not in f]
    locks = [f for f in changed if f.endswith(("package-lock.json", "pnpm-lock.yaml", "yarn.lock"))]
    if not manifests and not locks:
        rep.add("deps", "PASS", "no manifest or lockfile changed")
        return
    fails, warns, info = [], [], []
    for m in manifests:
        before = _deps_at(root, base, m)
        after = _deps_at(root, None, m)
        new = sorted(set(after) - set(before))
        for name in new:
            code, out = dp.run(["npm", "view", name, "version"], root, timeout=30)
            if code != 0:
                fails.append(f"{m}: new dependency `{name}` not found in the registry (SEC-37) — invented or misspelled?")
            else:
                info.append(f"{m}: new dependency `{name}` @ {out.strip().splitlines()[-1] if out.strip() else '?'} (SEC-37: justify why an existing dependency or the stdlib does not do this)")
    code, out = dp.run("npm audit --omit=dev --workspaces --audit-level=high", root, timeout=300)
    if code == 127 or "ENOWORKSPACES" in out or "not a workspace" in out.lower():
        code, out = dp.run("npm audit --omit=dev --audit-level=high", root, timeout=300)
    summary = next((l for l in out.splitlines() if "vulnerabilit" in l), out.strip().splitlines()[-1] if out.strip() else "")
    if code != 0:
        fails.append(f"npm audit (production tree, high or worse) failed (SEC-35): {summary}")
    else:
        info.append(f"npm audit: {summary}")
    if fails:
        rep.add("deps", "FAIL", "\n".join(fails + warns + info))
    elif warns:
        rep.add("deps", "WARN", "\n".join(warns + info))
    else:
        rep.add("deps", "PASS", "\n".join(info) if info else "ok")


def check_secrets(root, cfg, rep):
    code, out = dp.run(["which", "gitleaks"], root)
    if code != 0:
        rep.add("secrets", "WARN", "gitleaks not installed — the deploy gate still runs it; install for local checks (SEC-31)")
        return
    code, out = dp.run("gitleaks detect --source . --no-git --redact --exit-code 1", root, timeout=300)
    if code == 0:
        rep.add("secrets", "PASS", "gitleaks found nothing")
    else:
        tail = "\n".join(out.strip().splitlines()[-8:])
        rep.add("secrets", "FAIL", f"gitleaks reported findings (SEC-31)\n{tail}")


def check_migrations(root, cfg, base, changed, rep):
    mdir = cfg["checks"].get("migrationsDir")
    if not mdir:
        rep.add("migrations", "PASS", "no migrationsDir configured")
        return
    mdir = mdir.rstrip("/") + "/"
    fails, warns = [], []
    code, out = dp.run(["git", "diff", "--name-status", base, "--", mdir.rstrip("/")], root)
    existing_at_base = set()
    c2, lst = dp.run(["git", "ls-tree", "-r", "--name-only", base, "--", mdir.rstrip("/")], root)
    if c2 == 0:
        existing_at_base = set(l.strip() for l in lst.splitlines() if l.strip())
    if code == 0:
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status, path = parts[0], parts[-1]
            if status.startswith("M") and path in existing_at_base and re.search(r"/\d{3,}_[^/]+\.sql$", path):
                fails.append(f"{path}: an already-committed migration was edited (DATA-06) — add a new migration instead")
    nums = [int(m.group(1)) for p in existing_at_base for m in [re.search(r"/(\d{3,})_[^/]+\.sql$", p)] if m]
    max_base = max(nums) if nums else 0
    for rel in changed:
        if rel.startswith(mdir) and rel not in existing_at_base:
            m = re.search(r"/(\d{3,})_[^/]+\.sql$", rel)
            if m and int(m.group(1)) <= max_base:
                fails.append(f"{rel}: new migration numbered {m.group(1)} is not above the current maximum {max_base:03d} (DATA-05/06)")
    if fails:
        rep.add("migrations", "FAIL", "\n".join(fails + warns))
    elif warns:
        rep.add("migrations", "WARN", "\n".join(warns))
    else:
        rep.add("migrations", "PASS", "no applied migration edited; numbering monotonic")


def check_contract(root, cfg, changed, rep):
    pairs = cfg["checks"].get("contractPairs") or []
    if not pairs:
        rep.add("contract", "PASS", "no contractPairs configured")
        return
    warns = []
    for p in pairs:
        src_re = re.compile(p["src"])
        if any(src_re.search(f) for f in changed) and p["doc"] not in changed:
            warns.append(f"files under {p['src']} changed but {p['doc']} did not (API-01) — confirm the contract is unchanged")
    rep.add("contract", "WARN" if warns else "PASS", "\n".join(warns) if warns else "contract and routes changed together, or neither")


def main():
    args = set(sys.argv[1:])
    root = dp.repo_root()
    if not root:
        print("dev-policy check: not inside a git repository")
        return 2
    cfg = dp.load_config(root)
    base, changed = dp.changed_files(root, cfg)
    fp, _ = dp.fingerprint(root, cfg)
    rep = Report()
    started = time.time()
    if not changed:
        print("dev-policy check: nothing changed since the merge base — nothing to check.")
        dp.write_stamp(root, {"fingerprint": fp, "status": "pass", "time": started, "files": []})
        return 0
    print(f"dev-policy check — {len(changed)} changed file(s) since {base[:10]}:")
    for f in changed[:30]:
        print(f"    {f}")
    if len(changed) > 30:
        print(f"    … and {len(changed) - 30} more")
    if "--no-typecheck" not in args:
        check_typecheck(root, cfg, changed, rep)
    if "--no-lint" not in args:
        check_lint(root, cfg, changed, rep)
    check_patterns(root, cfg, base, changed, rep)
    check_tests(root, cfg, base, changed, rep)
    check_deps(root, cfg, base, changed, rep)
    check_secrets(root, cfg, rep)
    check_migrations(root, cfg, base, changed, rep)
    check_contract(root, cfg, changed, rep)
    status = "fail" if rep.failed else "pass"
    print(rep.render())
    print(f"\nRESULT: {status.upper()}  ({time.time() - started:.0f}s)" + ("" if status == "pass" else "  — fix every FAIL above, then re-run"))
    dp.write_stamp(root, {"fingerprint": fp, "status": status, "time": started, "files": changed})
    if "--json" in args:
        print(json.dumps({"status": status, "rows": rep.rows}))
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
