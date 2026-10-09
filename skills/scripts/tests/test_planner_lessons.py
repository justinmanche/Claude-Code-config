"""Tests for the lessons built into the lean planner after the 2026-10 run.

Covers: required_permissions / push_policy schema, executor step 1 permissions
block, base-commit preamble with a real SHA, denied-command rule on every
dispatch, worktree/wave-merge text, push policy messaging, and the review /
developer / live-verify rules (absence inventories, multi-step live sequences,
inline remote checks).

unittest-based so it runs without pytest:
    cd ~/.claude/skills/scripts && python3 -m unittest tests.test_planner_lessons
pytest collects it too.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

PLANNER = "skills.planner.orchestrator.planner"
EXECUTOR = "skills.planner.orchestrator.executor"
DENIED = "If a command is denied, stop and report exactly which command — do not work around it."

CONTEXT = {
    "task_spec": ["x"], "constraints": ["none confirmed"], "entry_points": ["greenfield"],
    "rejected_alternatives": ["none discussed"], "current_understanding": ["x"],
    "assumptions": ["none"], "invisible_knowledge": [], "reference_docs": ["none"],
    "verification_env": ["unit: npm test", "ship: ./deploy.sh", "live: driver"],
}

PERMS = [
    {"rule": "Bash(gh issue:*)", "why": "close the tracking issue"},
    {"rule": "Bash(az vm run-command:*)", "why": "read-only remote checks"},
]


def run(module: str, *args: str, cwd: Path = SCRIPTS) -> str:
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS)}  # cwd may be outside the scripts dir
    proc = subprocess.run([sys.executable, "-m", module, *args],
                          cwd=cwd, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"{module} {args} failed:\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "first")
    return repo


def make_plan(state_dir: Path, extra: dict | None = None, waves: list[list[str]] | None = None) -> None:
    (state_dir / "context.json").write_text(json.dumps(CONTEXT))
    if not (state_dir / "plan.json").exists():
        (state_dir / "plan.json").write_text(json.dumps(
            {"overview": {"problem": "p", "approach": ""}}))
    calls = []
    for n, (name, f) in enumerate([("One", "src/a.ts"), ("Two", "src/b.ts")], 1):
        calls.append({"method": "set-milestone",
                      "params": {"name": name, "files": f, "acceptance_criteria": f"{name} works"},
                      "id": 2 * n - 1})
        calls.append({"method": "set-intent",
                      "params": {"milestone": f"M-00{n}", "file": f, "behavior": "do it"},
                      "id": 2 * n})
    out = run("skills.planner.cli.plan", "--state-dir", str(state_dir), "batch", json.dumps(calls))
    assert '"error"' not in out, out
    plan = json.loads((state_dir / "plan.json").read_text())
    waves = waves or [["M-001", "M-002"]]
    plan["waves"] = [{"id": f"W-00{i}", "milestones": w} for i, w in enumerate(waves, 1)]
    plan.update(extra or {})
    (state_dir / "plan.json").write_text(json.dumps(plan))


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.repo = make_repo(self.root)


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from skills.planner.shared import schema
        if not schema.PYDANTIC_AVAILABLE:
            raise unittest.SkipTest("pydantic not installed")
        cls.schema = schema

    def plan(self, **extra):
        return self.schema.Plan.model_validate(
            {"overview": {"problem": "p", "approach": ""}, **extra})

    def test_defaults_keep_old_plans_valid(self):
        p = self.plan()
        self.assertEqual(p.push_policy, "at_end")
        self.assertEqual(p.required_permissions, [])
        self.assertIsNone(p.repo_path)

    def test_accepts_permissions_and_each_push_policy(self):
        for policy in ("after_each_wave", "at_end", "never"):
            p = self.plan(push_policy=policy, required_permissions=PERMS)
            self.assertEqual(p.push_policy, policy)
        self.assertEqual(p.required_permissions[0].rule, "Bash(gh issue:*)")

    def test_rejects_bad_push_policy(self):
        with self.assertRaises(Exception):
            self.plan(push_policy="sometimes")

    def test_rejects_bad_permissions(self):
        for bad in (["Bash(gh issue:*)"],                       # bare string
                    [{"rule": "Bash(gh issue:*)"}],             # no why
                    [{"rule": "Bash(gh issue:*)", "why": ""}],  # empty why
                    [{"rule": "not a rule", "why": "x"}],       # not a rule string
                    [{"rule": "", "why": "x"}]):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                self.plan(required_permissions=bad)

    def test_validate_state_rejects_bad_plan_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "plan.json").write_text(json.dumps(
                {"overview": {"problem": "p", "approach": ""}, "push_policy": "bogus"}))
            with self.assertRaises(self.schema.SchemaValidationError):
                self.schema.validate_state(d)

    def test_set_execution_policy_cli_upserts_and_validates(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "plan.json").write_text(json.dumps(
                {"overview": {"problem": "p", "approach": ""}}))
            sd = ["--state-dir", d]
            run("skills.planner.cli.plan", *sd, "set-execution-policy", "--push-policy", "never",
                "--permission", "Bash(gh issue:*) => close issue")
            run("skills.planner.cli.plan", *sd, "set-execution-policy",
                "--permission", "Bash(gh issue:*) => close the tracking issue",
                "--permission", "Bash(az vm run-command:*) => remote reads")
            plan = json.loads((Path(d) / "plan.json").read_text())
            self.assertEqual(plan["push_policy"], "never")
            self.assertEqual([p["rule"] for p in plan["required_permissions"]],
                             ["Bash(gh issue:*)", "Bash(az vm run-command:*)"])
            self.assertEqual(plan["required_permissions"][0]["why"], "close the tracking issue")
            bad = subprocess.run([sys.executable, "-m", "skills.planner.cli.plan", *sd,
                                  "set-execution-policy", "--permission", "no separator"],
                                 cwd=SCRIPTS, capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)


class ExecutorTests(TempCase):
    def init(self, extra=None, waves=None, repo=True) -> str:
        make_plan(self.state, extra, waves)
        args = ["--step", "1", "--plan", str(self.state / "plan.json"),
                "--state-dir", str(self.root / "exec")]
        if repo:
            args += ["--repo", str(self.repo)]
        return run(EXECUTOR, *args)

    @property
    def exec_dir(self) -> Path:
        return self.root / "exec"

    def test_step1_prints_permissions_block(self):
        out = self.init({"required_permissions": PERMS, "push_policy": "after_each_wave"})
        self.assertIn("/permissions", out)
        for p in PERMS:
            self.assertIn(p["rule"], out)
            self.assertIn(p["why"], out)
        self.assertIn("BEFORE DISPATCHING WAVE 1", out)
        self.assertIn("Do not edit", out)
        self.assertIn("PUSH POLICY: after_each_wave", out)
        self.assertIn(f"REPO: {self.repo.resolve()}", out)

    def test_step1_without_permissions_says_none(self):
        out = self.init()
        self.assertIn("none declared", out)
        self.assertIn("PUSH POLICY: at_end", out)

    def test_dispatch_names_real_sha_and_guards(self):
        self.init({"push_policy": "at_end"})
        sha = git(self.repo, "rev-parse", "main")
        out = run(EXECUTOR, "--step", "2", "--state-dir", str(self.exec_dir))
        self.assertIn(f"git merge-base --is-ancestor {sha} HEAD || git merge --ff-only main", out)
        self.assertEqual(out.count("BASE COMMIT (mandatory"), 2)  # one per parallel agent
        self.assertEqual(out.count(DENIED), 2)
        self.assertIn("isolation: worktree", out)
        self.assertIn("DISTINCT database/container port", out)
        self.assertIn("ISOLATION SLOT: 1 of 2", out)
        self.assertIn("ISOLATION SLOT: 2 of 2", out)
        self.assertIn("wave branch", out)

    def test_sha_tracks_new_main_tip(self):
        self.init(waves=[["M-001"], ["M-002"]])
        before = git(self.repo, "rev-parse", "main")
        (self.repo / "b.txt").write_text("b")
        git(self.repo, "add", "b.txt")
        git(self.repo, "commit", "-q", "-m", "wave 1")
        after = git(self.repo, "rev-parse", "main")
        self.assertNotEqual(before, after)
        out = run(EXECUTOR, "--step", "2", "--state-dir", str(self.exec_dir))
        self.assertIn(after, out)
        self.assertNotIn(before, out)

    def test_unresolved_repo_degrades_instead_of_failing(self):
        make_plan(self.state)
        # cwd outside any git repo, no --repo
        out = run(EXECUTOR, "--step", "1", "--plan", str(self.state / "plan.json"),
                  "--state-dir", str(self.exec_dir), cwd=self.root)
        self.assertIn("NOT RESOLVED", out)
        out = run(EXECUTOR, "--step", "2", "--state-dir", str(self.exec_dir), cwd=self.root)
        self.assertIn("BASE COMMIT: unknown", out)
        self.assertIn(DENIED, out)

    def test_wave_pass_pushes_only_when_policy_allows(self):
        for policy, expect, forbid in (
                ("after_each_wave", "push main to origin now", "do not push now"),
                ("at_end", "do not push now", "push main to origin now"),
                ("never", "do not push now", "push main to origin now")):
            with self.subTest(policy=policy):
                state = self.root / f"s-{policy}"
                state.mkdir()
                make_plan(state, {"push_policy": policy}, waves=[["M-001"], ["M-002"]])
                ex = self.root / f"e-{policy}"
                run(EXECUTOR, "--step", "1", "--plan", str(state / "plan.json"),
                    "--state-dir", str(ex), "--repo", str(self.repo))
                out = run(EXECUTOR, "--step", "5", "--state-dir", str(ex), "--qr-status", "pass")
                self.assertIn(expect, out)
                self.assertNotIn(forbid, out)
                self.assertIn("MERGE (if agents ran in isolated worktrees)", out)
                if policy != "after_each_wave":
                    self.assertIn("stale origin/main", out)

    def test_fix_live_and_docs_dispatches_carry_preamble_and_denied_rule(self):
        self.init()
        sha = git(self.repo, "rev-parse", "main")
        qr = {"phase": "impl-live", "iteration": 1, "awaiting_reverify": False, "items": [
            {"id": "live-M-001-1", "scope": "*", "check": "c", "status": "FAIL", "version": 1,
             "severity": "MUST", "finding": "f"}]}
        (self.exec_dir / "qr-impl-live.json").write_text(json.dumps(qr))
        for step in (8, 9):
            with self.subTest(step=step):
                out = run(EXECUTOR, "--step", str(step), "--state-dir", str(self.exec_dir))
                self.assertIn(f"git merge-base --is-ancestor {sha} HEAD", out)
                self.assertIn(DENIED, out)

    def test_live_verify_prints_permissions(self):
        make_plan(self.state, {"required_permissions": PERMS})
        plan = json.loads((self.state / "plan.json").read_text())
        plan["milestones"][0]["live_checks"] = ["as vendor, save then reload"]
        (self.state / "plan.json").write_text(json.dumps(plan))
        run(EXECUTOR, "--step", "1", "--plan", str(self.state / "plan.json"),
            "--state-dir", str(self.exec_dir), "--repo", str(self.repo))
        out = run(EXECUTOR, "--step", "6", "--state-dir", str(self.exec_dir))
        self.assertIn("/permissions", out)
        for p in PERMS:
            self.assertIn(p["rule"], out)
        self.assertIn(DENIED, out)  # the live checker's dispatch

    def test_retrospective_pushes_per_policy(self):
        self.init({"push_policy": "never"})
        out = run(EXECUTOR, "--step", "13", "--state-dir", str(self.exec_dir))
        self.assertIn("do not push", out)
        self.assertIn("Permissions requested mid-run", out)


class PlannerTests(unittest.TestCase):
    def test_planning_asks_owner_for_outside_actions(self):
        out1 = run(PLANNER, "--step", "1")
        self.assertIn("OUTSIDE_ACTIONS", out1)
        self.assertIn("after_each_wave | at_end | never", out1)
        state = re.search(r"STATE_DIR=(\S+)", out1).group(1)
        out2 = run(PLANNER, "--step", "2", "--state-dir", state)
        self.assertIn("set-execution-policy", out2)
        self.assertIn("--permission", out2)

    def test_planner_dispatch_carries_denied_rule(self):
        state = re.search(r"STATE_DIR=(\S+)", run(PLANNER, "--step", "1")).group(1)
        (Path(state) / "context.json").write_text(json.dumps(CONTEXT))
        self.assertIn(DENIED, run(PLANNER, "--step", "3", "--state-dir", state))

    def test_handoff_lists_permissions(self):
        from skills.planner.orchestrator.planner import format_handoff
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "plan.json").write_text(json.dumps(
                {"overview": {"problem": "p", "approach": ""},
                 "required_permissions": PERMS, "push_policy": "never"}))
            text = format_handoff(d, str(Path(d) / "plan.md"))
        self.assertIn("Bash(gh issue:*)", text)
        self.assertIn("PUSH POLICY: never", text)


class ChecklistTests(unittest.TestCase):
    def test_plan_design_review_rules(self):
        from skills.planner.quality_reviewer import plan_design_review as r
        concerns, severity = r.PHASE_PROMPTS[2], r.PHASE_PROMPTS[5]
        self.assertIn("single pattern", concerns)
        self.assertIn("inventory", concerns)
        self.assertIn("reload", concerns)
        self.assertIn("undo/clear", concerns)
        self.assertIn("required_permissions", concerns)
        self.assertIn("ABSENCE_UNPROVEN", severity)
        self.assertIn("LIVE_SEQUENCE_GAP", severity)
        self.assertIn("PERMISSION_GAP", severity)
        self.assertIn("ABSENCE CRITERIA", r.PHASE_PROMPTS[3])

    def test_architect_guidance_has_all_rules(self):
        from skills.planner.architect.plan_design_execute import get_step_guidance
        text = "\n".join(get_step_guidance(3, state_dir="x")["actions"]
                         + get_step_guidance(6, state_dir="x")["actions"])
        self.assertIn("INVENTORY", text)
        self.assertIn("MULTI-STEP", text)
        self.assertIn("INLINE", text)
        self.assertIn("required_permissions", text)

    def test_developer_reports_inventory_counts(self):
        from skills.planner.developer.exec_implement_execute import get_step_guidance
        verify = "\n".join(get_step_guidance(3)["actions"])
        ret = "\n".join(get_step_guidance(4)["actions"])
        self.assertIn("INVENTORY:", verify)
        self.assertIn("candidates", verify)
        self.assertIn("INVENTORY:", ret)

    def test_live_verify_sweep_and_inline_remote(self):
        from skills.planner.quality_reviewer.impl_live_verify import ImplLiveVerify
        from skills.planner.shared.qr.phases import get_phase_config
        text = "\n".join(ImplLiveVerify().get_verification_guidance({"id": "reg-01"}, "/s"))
        self.assertIn("docker exec", text)
        self.assertIn("INLINE", text)
        self.assertIn("reload", text)
        self.assertIn("undo", text)
        self.assertIn("do not work around it", " ".join(text.split()))
        sweep = get_phase_config("impl-live")["regression_check"]
        self.assertIn("save -> change -> save -> reload", sweep)


if __name__ == "__main__":
    unittest.main()
