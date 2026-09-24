"""End-to-end routing tests for the lean planner/executor.

Each test drives the orchestrator scripts exactly as the orchestrator LLM
would (python3 -m ... --step N), and plays the sub-agents by writing the
files they write (qr-{phase}.json verdicts) or calling the CLIs they call
(cli.qr update-item, cli.plan batch). Assertions are on the printed next
command and on state files -- the contract the LLM actually follows.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
PLANNER = "skills.planner.orchestrator.planner"
EXECUTOR = "skills.planner.orchestrator.executor"


def run(module: str, *args: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=SCRIPTS, capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"{module} {args} failed:\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout


def step(module: str, n: int, state_dir: Path, *extra: str) -> str:
    return run(module, "--step", str(n), "--state-dir", str(state_dir), *extra)


def next_step(output: str) -> int | None:
    m = re.findall(r"--step (\d+)", output.split("NEXT STEP")[-1] if "NEXT STEP" in output else output)
    return int(m[-1]) if m else None


def qr(state_dir: Path, phase: str) -> dict:
    return json.loads((state_dir / f"qr-{phase}.json").read_text())


def write_verdicts(state_dir: Path, phase: str, items: list[dict]) -> None:
    """Play the single reviewer: write qr-{phase}.json with verdicts."""
    full = [{"version": 1, "scope": "*", "severity": "MUST", **i} for i in items]
    (state_dir / f"qr-{phase}.json").write_text(json.dumps(
        {"phase": phase, "iteration": 1, "awaiting_reverify": False, "items": full}))


def verify(state_dir: Path, phase: str, item_id: str, status: str, finding: str | None = None) -> None:
    """Play the re-check agent: record one verdict through the locked CLI."""
    args = ["--state-dir", str(state_dir), "--qr-phase", phase, "update-item", item_id, "--status", status]
    if finding:
        args += ["--finding", finding]
    run("skills.planner.cli.qr", *args)


CONTEXT = {
    "task_spec": ["fix vendor notifications"], "constraints": ["none confirmed"],
    "entry_points": ["src/a.ts:f - sends"], "rejected_alternatives": ["none discussed"],
    "current_understanding": ["x"], "assumptions": ["none"], "invisible_knowledge": [],
    "reference_docs": ["none"],
    "verification_env": ["unit: npm test", "integration: npm run test:integration",
                         "ship: ./deploy.sh", "live: playwright driver as each role"],
}


def make_plan(state_dir: Path, live: bool = True) -> None:
    (state_dir / "context.json").write_text(json.dumps(CONTEXT))
    calls = [
        {"method": "set-milestone", "params": {"name": "Notify", "files": "src/a.ts",
                                               "acceptance_criteria": "vendor user gets a row"}, "id": 1},
        {"method": "set-intent", "params": {"milestone": "M-001", "file": "src/a.ts",
                                            "behavior": "lookup under system context"}, "id": 2},
        {"method": "set-milestone", "params": {"name": "Nav", "files": "src/b.ts",
                                               "acceptance_criteria": "vendor sees nav item"}, "id": 3},
        {"method": "set-intent", "params": {"milestone": "M-002", "file": "src/b.ts",
                                            "behavior": "add nav entry"}, "id": 4},
        {"method": "set-verification", "params": {
            "milestone": "M-001",
            "integration_tests": ["vendor submit, customer row exists, as vendor identity"],
            "live_checks": (["as vendor, submit; as customer, see bell item, with link"] if live else [])},
         "id": 5},
    ]
    if live:
        calls.append({"method": "set-verification", "params": {
            "milestone": "M-002", "live_checks": "as vendor, see Remediations || open one"}, "id": 6})
    out = run("skills.planner.cli.plan", "--state-dir", str(state_dir), "batch", json.dumps(calls))
    assert '"error"' not in out, out
    plan = json.loads((state_dir / "plan.json").read_text())
    plan["waves"] = [{"id": "W-001", "milestones": ["M-001"]}, {"id": "W-002", "milestones": ["M-002"]}]
    (state_dir / "plan.json").write_text(json.dumps(plan))


@pytest.fixture
def planner_state() -> Path:
    out = run(PLANNER, "--step", "1")
    return Path(re.search(r"STATE_DIR=(\S+)", out).group(1))


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

def test_planner_has_six_steps_and_asks_for_verification_env(planner_state):
    out = step(PLANNER, 2, planner_state)
    assert "verification_env" in out
    assert next_step(out) == 3


def test_planner_review_fail_fix_reverify_pass(planner_state):
    make_plan(planner_state)

    out = step(PLANNER, 4, planner_state)
    assert "plan_design_review" in out and "opus" in out
    assert next_step(out) == 5

    write_verdicts(planner_state, "plan-design", [
        {"id": "qa-001", "check": "intent matches enum", "status": "FAIL", "finding": "no such enum value"},
        {"id": "qa-002", "check": "integration test planned", "status": "PASS"},
    ])

    # First pass after review: no agent, status computed from the file.
    out = step(PLANNER, 5, planner_state)
    assert "--qr-status fail" in out
    assert "quality-reviewer" not in out
    out = step(PLANNER, 6, planner_state, "--qr-status", "fail")
    assert next_step(out) == 3

    # Fix mode marks the file so the next reverify re-checks.
    out = step(PLANNER, 3, planner_state)
    assert "Fix Mode" in out
    assert qr(planner_state, "plan-design")["awaiting_reverify"] is True

    out = step(PLANNER, 4, planner_state)
    assert "Skipped" in out

    out = step(PLANNER, 5, planner_state)
    state = qr(planner_state, "plan-design")
    assert state["iteration"] == 2 and state["awaiting_reverify"] is False
    assert "--qr-item qa-001" in out and "--qr-item reg-02" in out
    assert "--qr-item qa-002" not in out, "passed items are not re-checked"
    assert out.count("plan_design_qr_verify") >= 1

    verify(planner_state, "plan-design", "qa-001", "PASS")
    verify(planner_state, "plan-design", "reg-02", "PASS")
    out = step(PLANNER, 6, planner_state, "--qr-status", "pass")
    assert "PLAN APPROVED" in out
    md = (planner_state / "plan.md").read_text()
    assert "Integration tests (real dependencies)" in md and "Live checks" in md


def test_planner_escalation_then_one_more_round_is_rechecked(planner_state):
    make_plan(planner_state)
    write_verdicts(planner_state, "plan-design",
                   [{"id": "qa-001", "check": "c", "status": "FAIL", "finding": "f"}])
    rounds = 0
    while True:
        step(PLANNER, 3, planner_state)            # fix dispatched
        out = step(PLANNER, 5, planner_state)      # re-check or escalate
        if "ESCALATE" in out:
            break
        rounds += 1
        verify(planner_state, "plan-design", "qa-001", "FAIL", "still broken")
        assert rounds < 10, "never escalated"
    assert qr(planner_state, "plan-design")["iteration"] == 5
    assert "Re-check the latest fix once more" in out and "--qr-status pass" in out
    assert "NEXT STEP" not in out or "Execute this command" not in out, "user must choose"

    # User: re-check once more -> the SAME step now dispatches a re-check.
    out = step(PLANNER, 5, planner_state)
    assert "ESCALATE" not in out and "--qr-item qa-001" in out
    assert qr(planner_state, "plan-design")["iteration"] == 6

    # Still failing -> next fix round escalates again instead of looping forever.
    verify(planner_state, "plan-design", "qa-001", "FAIL", "still broken")
    step(PLANNER, 3, planner_state)
    out = step(PLANNER, 5, planner_state)
    assert "ESCALATE" in out
    assert qr(planner_state, "plan-design")["iteration"] == 6

    # User accepts: the approval lists the known issue.
    out = step(PLANNER, 6, planner_state, "--qr-status", "pass")
    assert "PLAN APPROVED" in out and "ACCEPTED KNOWN ISSUES" in out and "qa-001" in out


def test_executor_retrospective_reports_below_threshold_failures(planner_state):
    make_plan(planner_state, live=False)
    sd = planner_state
    run(EXECUTOR, "--step", "1", "--state-dir", str(sd))
    step(EXECUTOR, 2, sd)
    write_verdicts(sd, "impl-code", [
        {"id": "qa-009", "check": "naming", "status": "FAIL", "finding": "bad name", "severity": "COULD"}])
    # Simulate de-escalation: at iteration 3 COULD no longer blocks.
    data = qr(sd, "impl-code"); data["iteration"] = 3
    (sd / "qr-impl-code.json").write_text(json.dumps(data))
    out = step(EXECUTOR, 4, sd)
    assert "--qr-status pass" in out
    step(EXECUTOR, 5, sd, "--qr-status", "pass")
    known = json.loads((sd / "exec-state.json").read_text())["known_issues"]
    assert known[0]["id"] == "qa-009" and known[0]["finding"] == "bad name"
    out = step(EXECUTOR, 13, sd)
    assert "Accepted Known Issues (1)" in out and "bad name" in out


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def test_executor_full_route_with_live_fix(planner_state):
    make_plan(planner_state)
    sd = planner_state
    run(EXECUTOR, "--step", "1", "--state-dir", str(sd))

    for wave, mid in enumerate(["M-001", "M-002"]):
        out = step(EXECUTOR, 2, sd)
        assert mid in out and "INTEGRATION TESTS" in out
        assert "real dependency" in out.lower()
        out = step(EXECUTOR, 3, sd)
        assert "impl_code_review" in out and f"REVIEW WAVE MILESTONES: {mid}" in out
        write_verdicts(sd, "impl-code", [{"id": "qa-001", "check": "ok", "status": "PASS"}])
        out = step(EXECUTOR, 4, sd)
        assert "--qr-status pass" in out
        out = step(EXECUTOR, 5, sd, "--qr-status", "pass")
        assert next_step(out) == (2 if wave == 0 else 6)

    # Live gate, first round: ship + one agent, all live items, no regression item.
    out = step(EXECUTOR, 6, sd)
    assert "SHIP FIRST" in out and "./deploy.sh" in out
    live = qr(sd, "impl-live")
    ids = [i["id"] for i in live["items"]]
    assert ids == ["live-M-001-1", "live-M-002-1", "live-M-002-2"]
    assert live["iteration"] == 1
    assert all(f"--qr-item {i}" in out for i in ids) and "reg-" not in out

    verify(sd, "impl-live", "live-M-001-1", "PASS")
    verify(sd, "impl-live", "live-M-002-1", "FAIL", "404 on open")
    verify(sd, "impl-live", "live-M-002-2", "PASS")
    out = step(EXECUTOR, 7, sd, "--qr-status", "fail")
    assert next_step(out) == 8

    out = step(EXECUTOR, 8, sd)
    assert "exec_live_fix" in out
    assert next_step(out) == 6

    out = step(EXECUTOR, 6, sd)
    assert "SHIP FIRST" in out
    assert "--qr-item live-M-002-1" in out and "--qr-item reg-02" in out
    assert "--qr-item live-M-001-1" not in out
    verify(sd, "impl-live", "live-M-002-1", "PASS")
    verify(sd, "impl-live", "reg-02", "PASS")
    out = step(EXECUTOR, 7, sd, "--qr-status", "pass")
    assert next_step(out) == 9
    assert not (sd / "qr-impl-live.json").exists()

    out = step(EXECUTOR, 9, sd)
    assert "technical-writer" in out and "live checks passed" in out
    out = step(EXECUTOR, 10, sd)
    assert "impl_docs_review" in out
    write_verdicts(sd, "impl-docs", [{"id": "qa-001", "check": "docs true", "status": "PASS"}])
    out = step(EXECUTOR, 11, sd)
    assert "--qr-status pass" in out
    out = step(EXECUTOR, 12, sd, "--qr-status", "pass")
    assert next_step(out) == 13
    out = step(EXECUTOR, 13, sd)
    assert "Defects Caught, by gate" in out


def test_executor_code_fix_loop_rechecks_only_failures(planner_state):
    make_plan(planner_state)
    sd = planner_state
    run(EXECUTOR, "--step", "1", "--state-dir", str(sd))
    step(EXECUTOR, 2, sd)
    step(EXECUTOR, 3, sd)
    write_verdicts(sd, "impl-code", [
        {"id": "qa-001", "check": "sql columns exist", "status": "FAIL", "finding": "no column title"},
        {"id": "qa-002", "check": "guard", "status": "PASS"},
        {"id": "qa-003", "check": "style", "status": "FAIL", "finding": "naming", "severity": "COULD"},
    ])
    out = step(EXECUTOR, 4, sd)
    assert "--qr-status fail" in out
    out = step(EXECUTOR, 5, sd, "--qr-status", "fail")
    assert next_step(out) == 2
    out = step(EXECUTOR, 2, sd)
    assert "Fix Mode" in out and "GATES" in out
    out = step(EXECUTOR, 4, sd)
    assert "--qr-item qa-001" in out and "--qr-item qa-003" in out and "--qr-item reg-02" in out
    assert "--qr-item qa-002" not in out
    # Wave does not advance on FAIL.
    assert json.loads((sd / "exec-state.json").read_text())["wave_index"] == 0


def test_executor_skips_live_gate_without_live_checks(planner_state):
    make_plan(planner_state, live=False)
    sd = planner_state
    run(EXECUTOR, "--step", "1", "--state-dir", str(sd))
    out = step(EXECUTOR, 6, sd)
    assert "Skipped" in out and next_step(out) == 9
    assert not (sd / "qr-impl-live.json").exists()


def test_set_verification_cli_flags(planner_state):
    make_plan(planner_state)
    run("skills.planner.cli.plan", "--state-dir", str(planner_state), "set-verification",
        "--milestone", "M-002", "--integration-test", "a, with comma", "--integration-test", "b")
    ms = json.loads((planner_state / "plan.json").read_text())["milestones"][1]
    assert ms["integration_tests"] == ["a, with comma", "b"]
    assert ms["live_checks"] == ["as vendor, see Remediations", "open one"], "unchanged when omitted"


def test_planner_old_still_runs():
    out = run("skills.planner_old.orchestrator.planner", "--step", "1")
    assert "STATE_DIR=" in out
    import importlib
    importlib.import_module("skills.planner_old.orchestrator.executor")
