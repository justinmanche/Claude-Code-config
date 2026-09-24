#!/usr/bin/env python3
"""
Lean Plan Executor - 13-step execution orchestrator.

Every step prints a prompt and the exact command for the next step.
Sub-agents run the scripts in developer/, technical_writer/ and
quality_reviewer/; the orchestrator LLM only dispatches (and ships, step 6).

Flow (step numbers match shared/qr/phases.py and shared/constants.py):
   1  exec-init              orchestrator  locate plan.json, build waves
   2  impl-code-work         developer xN  one per milestone in current wave,
                                           then unit + integration gates
                                           (fix mode: one developer, via router)
   3  impl-code-review       QR (opus) x1  verdicts in qr-impl-code.json
   4  impl-code-reverify     none | QR x1  re-check failed items after a fix
   5  impl-code-route        orchestrator  FAIL -> 2 | PASS+more waves -> 2 | PASS -> 6
   6  impl-live-verify       ship + QR x1  live_checks on the deployed system
   7  impl-live-route        orchestrator  FAIL -> 8 | PASS -> 9
   8  impl-live-fix          developer x1  reproduce, fix, add the missing test -> 6
   9  impl-docs-work         technical-writer
  10  impl-docs-review       QR (opus) x1
  11  impl-docs-reverify     none | QR x1
  12  impl-docs-route        orchestrator  FAIL -> 9 | PASS -> 13
  13  retrospective          orchestrator  terminal

Wave state lives in STATE_DIR/exec-state.json (Python-managed; the LLM never
reads it). Code review runs per wave so a broken foundation wave is caught
before dependent waves build on it. The live gate runs once, after all waves,
against one deploy of the finished change. Documentation runs once, last, so
it describes what actually shipped (including live fixes).
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from skills.lib.workflow.types import AgentRole
from skills.lib.workflow.prompts import subagent_dispatch, template_dispatch
from skills.lib.workflow.prompts.step import format_step
from skills.planner.shared.qr.types import QRState, QRStatus, LoopState
from skills.planner.shared.gates import build_gate_output, GateResult
from skills.planner.shared.qr.cli import add_qr_args
from skills.planner.shared.qr.loop import mark_fix_dispatched, review_step, reverify_step
from skills.planner.shared.qr.utils import (
    get_qr_iteration,
    has_qr_failures,
    qr_file_exists,
    write_live_items,
)
from skills.planner.shared.builders import THINKING_EFFICIENCY
from skills.planner.shared.constraints import (
    ORCHESTRATOR_CONSTRAINT_EXTENDED,
    format_state_banner,
)
from skills.planner.shared.constants import (
    EXECUTOR_TOTAL_STEPS,
    EXECUTOR_GATE_STEPS,
    validate_step_count,
)


MODULE_PATH = "skills.planner.orchestrator.executor"
EXEC_STATE_FILE = "exec-state.json"

STEP_CODE_WORK = 2
STEP_LIVE_VERIFY = 6
STEP_LIVE_FIX = 8
STEP_DOCS_WORK = 9
STEP_RETRO = 13


# =============================================================================
# State helpers (Python-side; invisible to the orchestrator LLM)
# =============================================================================

def _plan_path(state_dir: str) -> Path:
    return Path(state_dir) / "plan.json"


def _load_plan(state_dir: str) -> dict:
    return json.loads(_plan_path(state_dir).read_text())


def _exec_state_path(state_dir: str) -> Path:
    return Path(state_dir) / EXEC_STATE_FILE


def _load_exec_state(state_dir: str) -> dict:
    p = _exec_state_path(state_dir)
    if p.exists():
        return json.loads(p.read_text())
    return {"waves": [], "wave_index": 0, "completed": []}


def _save_exec_state(state_dir: str, state: dict) -> None:
    _exec_state_path(state_dir).write_text(json.dumps(state, indent=2))


def _compute_waves(plan: dict, completed: list[str]) -> list[list[str]]:
    """Wave list from plan.json, minus completed milestones.

    Falls back to one milestone per wave (sequential, in `number` order)
    when the plan carries no waves -- the safe default when dependency
    information is absent.
    """
    done = set(completed)
    if plan.get("waves"):
        waves = [[m for m in w.get("milestones", []) if m not in done]
                 for w in plan["waves"]]
    else:
        ordered = sorted(plan.get("milestones", []), key=lambda m: m.get("number", 0))
        waves = [[m["id"]] for m in ordered if m["id"] not in done]
    return [w for w in waves if w]


def _milestone(plan: dict, mid: str) -> dict:
    for m in plan.get("milestones", []):
        if m.get("id") == mid:
            return m
    return {"id": mid, "name": "(not found in plan.json)", "number": 0,
            "files": [], "acceptance_criteria": []}


def _resolve_state_dir(state_dir: str | None, plan: str | None) -> str:
    """Return a state dir containing plan.json, creating one from --plan if needed.

    Accepts the planner's STATE_DIR directly, a plan.json path, or a plan.md
    path with a sibling .json (same basename, or plan.json in the same dir).
    """
    if state_dir and _plan_path(state_dir).exists():
        return state_dir

    if not plan:
        sys.exit(
            "Error: step 1 needs a plan.\n"
            "  --state-dir <dir>   planner STATE_DIR containing plan.json, or\n"
            "  --plan <path>       plan.json, or plan.md with a sibling .json\n"
            "(Planning mode prints STATE_DIR=... and renders plan.md next to plan.json.)"
        )

    src = Path(plan).expanduser().resolve()
    if not src.exists():
        sys.exit(f"Error: plan not found: {src}")

    if src.suffix == ".json":
        plan_json = src
    else:
        candidates = [src.with_suffix(".json"), src.parent / "plan.json"]
        plan_json = next((c for c in candidates if c.exists()), None)
        if plan_json is None:
            sys.exit(
                f"Error: no plan.json found next to {src}.\n"
                f"  Looked for: {', '.join(str(c) for c in candidates)}\n"
                "  Execution needs the JSON plan (milestones, waves, acceptance criteria).\n"
                "  Copy plan.json from the planner STATE_DIR alongside the .md, or pass --state-dir."
            )

    new_dir = state_dir or tempfile.mkdtemp(prefix="executor-")
    Path(new_dir).mkdir(parents=True, exist_ok=True)
    shutil.copy(plan_json, _plan_path(new_dir))
    if src.suffix != ".json":
        shutil.copy(src, Path(new_dir) / "plan.md")
    return new_dir


def _ensure_context(state_dir: str, plan: dict) -> None:
    """Create context.json when missing (executor started from --plan alone).

    QR decompose agents read context.json for handover context. A planner
    STATE_DIR already has it; a state dir built from a bare plan.json does
    not, so synthesize one from the plan's own fields.
    """
    path = Path(state_dir) / "context.json"
    if path.exists():
        return
    overview = plan.get("overview", {})
    pc = plan.get("planning_context", {})
    ik = plan.get("invisible_knowledge", {})

    def _texts(entries, *keys):
        out = []
        for e in entries:
            if isinstance(e, str):
                out.append(e)
            elif isinstance(e, dict):
                out.append(" -- ".join(str(e[k]) for k in keys if e.get(k)) or json.dumps(e))
        return out

    ik_lines = ([ik["system"]] if ik.get("system") else []) \
        + ik.get("invariants", []) + ik.get("tradeoffs", [])
    context = {
        "task_spec": [v for v in (overview.get("problem"), overview.get("approach")) if v]
                     or ["execute approved plan"],
        "constraints": pc.get("constraints") or ["none confirmed"],
        "entry_points": sorted({f for m in plan.get("milestones", []) for f in m.get("files", [])})
                        or ["greenfield"],
        "rejected_alternatives": _texts(pc.get("rejected_alternatives", []), "alternative", "reason")
                                 or ["none discussed"],
        "current_understanding": ["executing approved plan.json; see milestones for detail"],
        "assumptions": ["none"],
        "invisible_knowledge": ik_lines or [],
        "reference_docs": ["none"],
    }
    path.write_text(json.dumps(context, indent=2))


def _delete_qr_file(state_dir: str, phase: str) -> bool:
    """Delete qr-{phase}.json, first recording any item still FAIL.

    A gate passes with below-threshold FAIL items left in the file (severity
    de-escalation), or with items the user accepted at escalation. They are
    real, evidenced defects: copy them into exec-state.json known_issues so
    the retrospective reports them instead of losing them with the file.
    """
    from skills.planner.shared.qr.utils import unresolved_items
    p = Path(state_dir) / f"qr-{phase}.json"
    if p.exists():
        leftover = unresolved_items(state_dir, phase)
        if leftover:
            state = _load_exec_state(state_dir)
            known = state.setdefault("known_issues", [])
            for item in leftover:
                entry = {"phase": phase, "id": item.get("id"),
                         "severity": item.get("severity", "SHOULD"),
                         "check": item.get("check", ""), "finding": item.get("finding", "")}
                if entry not in known:
                    known.append(entry)
            _save_exec_state(state_dir, state)
        p.unlink()
        return True
    return False


def _format_wave_table(waves: list[list[str]], plan: dict, wave_index: int) -> list[str]:
    lines = []
    for i, wave in enumerate(waves, 1):
        marker = "<- current" if i - 1 == wave_index else ""
        names = ", ".join(f"{mid} ({_milestone(plan, mid).get('name', '')})" for mid in wave)
        mode = "parallel" if len(wave) > 1 else "sequential"
        lines.append(f"  Wave {i}: [{names}] ({mode}) {marker}".rstrip())
    return lines


# =============================================================================
# Step handlers
# =============================================================================

def step_init(ctx: dict) -> dict:
    """Step 1: locate plan.json, compute waves, write exec-state.json."""
    args = ctx["args"]
    state_dir = _resolve_state_dir(args.state_dir, args.plan)

    from skills.planner.shared.schema import validate_state, SchemaValidationError
    try:
        validate_state(state_dir)
    except SchemaValidationError as e:
        sys.exit(f"Schema validation failed for {state_dir}/plan.json: {e}")

    plan = _load_plan(state_dir)
    _ensure_context(state_dir, plan)
    state = _load_exec_state(state_dir)
    for mid in (args.done or []):
        if mid not in state["completed"]:
            state["completed"].append(mid)
    state["waves"] = _compute_waves(plan, state["completed"])
    state["wave_index"] = min(state.get("wave_index", 0), max(len(state["waves"]) - 1, 0))
    _save_exec_state(state_dir, state)

    print(f"STATE_DIR={state_dir}")

    pending = [mid for w in state["waves"] for mid in w]

    if args.reconcile and pending:
        # Resume path: verify existing code against each pending milestone
        # before spending developer agents on it.
        targets = [{
            "mid": mid,
            "number": str(_milestone(plan, mid).get("number", 0)),
            "name": _milestone(plan, mid).get("name", ""),
        } for mid in pending]
        tmpl = (f"RECONCILE milestone $mid ($name).\n"
                f"PLAN_FILE: {state_dir}/plan.json\n"
                f"Report exactly one of: SATISFIED | NOT_SATISFIED | PARTIALLY_SATISFIED")
        command = "python3 -m skills.planner.quality_reviewer.exec_reconcile --step 1 --milestone $number"
        dispatch = template_dispatch(
            agent_type="quality-reviewer",
            template=tmpl,
            targets=targets,
            command=command,
            instruction="Validate existing code against plan requirements BEFORE executing.",
        )
        done_flags = " ".join(f"[--done {mid}]" for mid in pending)
        return {
            "title": "exec-init - Reconciliation",
            "actions": [
                ORCHESTRATOR_CONSTRAINT_EXTENDED,
                "",
                dispatch,
                "",
                "AFTER ALL AGENTS RETURN:",
                "  Re-run step 1 WITHOUT --reconcile, adding --done <id> for every",
                "  milestone reported SATISFIED. PARTIALLY_SATISFIED and NOT_SATISFIED",
                "  milestones stay pending and will be executed.",
            ],
            "next": f"python3 -m {MODULE_PATH} --step 1 --state-dir {state_dir} {done_flags}",
        }

    if not state["waves"]:
        return {
            "title": "exec-init",
            "actions": [
                "All milestones already completed (nothing pending).",
                "Proceeding to ship + live verification.",
            ],
            "next": f"python3 -m {MODULE_PATH} --step {STEP_LIVE_VERIFY} --state-dir {state_dir}",
        }

    actions = [
        f"PLAN: {state_dir}/plan.json",
        f"MILESTONES: {len(plan.get('milestones', []))} total, "
        f"{len(state['completed'])} already complete, {len(pending)} pending",
        "",
        "WAVES (milestones in one wave run in parallel; waves run in order):",
        *_format_wave_table(state["waves"], plan, state["wave_index"]),
        "",
        "WORKFLOW PER WAVE: developers -> unit + integration gates -> 1 reviewer -> route",
        "After the last wave: ship -> live checks -> documentation -> 1 reviewer -> retrospective.",
        "",
        "This step is ANALYSIS ONLY. Set up TodoWrite tracking for the waves.",
        "Do NOT dispatch agents here.",
    ]
    return {
        "title": "exec-init",
        "actions": actions,
        "next": f"python3 -m {MODULE_PATH} --step 2 --state-dir {state_dir}",
    }


def _context(state_dir: str) -> dict:
    p = Path(state_dir) / "context.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _verification_env_lines(state_dir: str) -> list[str]:
    env = _context(state_dir).get("verification_env") or []
    return [f"  - {line}" for line in env] or ["  - (none recorded in context.json)"]


def step_impl_code_work(ctx: dict) -> dict:
    """Step 2: dispatch developers for the current wave (or one fixer)."""
    state_dir = ctx["state_dir"]
    qr = ctx["qr"]
    plan = _load_plan(state_dir)
    state = _load_exec_state(state_dir)
    invoke_cmd = f"python3 -m skills.planner.developer.exec_implement --step 1 --state-dir {state_dir}"

    if qr.state == LoopState.RETRY:
        # Router (exec_implement.py) detects FAIL items and runs the fix script.
        mark_fix_dispatched(state_dir, "impl-code")
        dispatch = subagent_dispatch(
            agent_type="developer",
            command=invoke_cmd,
            prompt=f"PLAN_FILE: {state_dir}/plan.json\nFIX MODE: qr-impl-code.json has FAIL items.",
        )
        return {
            "title": "impl-code-work - Fix Mode",
            "actions": [
                format_state_banner("IMPLEMENTATION-FIX", qr.iteration, "fix"),
                "",
                "FIX MODE: Code review found issues.",
                "",
                ORCHESTRATOR_CONSTRAINT_EXTENDED,
                "",
                dispatch,
                "",
                "Developer reads qr-impl-code.json and fixes every FAIL item.",
                "Then run the SAME gates as after a wave (below) before continuing.",
                *_wave_gate_actions(state_dir, fix_mode=True),
            ],
            "next": f"python3 -m {MODULE_PATH} --step 3 --state-dir {state_dir}",
        }

    waves = state.get("waves") or []
    idx = state.get("wave_index", 0)
    if idx >= len(waves):
        return {
            "title": "impl-code-work",
            "actions": ["No pending waves. Proceeding to live verification."],
            "next": f"python3 -m {MODULE_PATH} --step {STEP_LIVE_VERIFY} --state-dir {state_dir}",
        }

    wave = waves[idx]
    targets = []
    for mid in wave:
        m = _milestone(plan, mid)
        targets.append({
            "mid": mid,
            "name": m.get("name", ""),
            "files": ", ".join(m.get("files", [])) or "(see plan)",
            "criteria": "\n".join(f"  - {c}" for c in m.get("acceptance_criteria", [])) or "  - (see plan)",
            "integration": "\n".join(f"  - {c}" for c in m.get("integration_tests", [])) or "  - (none planned)",
        })

    tmpl = (
        f"Implement MILESTONE $mid: $name\n"
        f"PLAN_FILE: {state_dir}/plan.json\n"
        f"FILES: $files\n"
        f"ACCEPTANCE CRITERIA:\n$criteria\n"
        f"INTEGRATION TESTS (real dependency, required):\n$integration\n"
        f"Implement ONLY this milestone. Other milestones in this wave run in parallel."
    )
    dispatch = template_dispatch(
        agent_type="developer",
        template=tmpl,
        targets=targets,
        command=invoke_cmd,
        instruction=f"Wave {idx + 1}/{len(waves)}: {len(wave)} milestone(s).",
    )

    return {
        "title": f"impl-code-work - Wave {idx + 1}/{len(waves)}",
        "actions": [
            ORCHESTRATOR_CONSTRAINT_EXTENDED,
            "",
            dispatch,
            "",
            "AFTER ALL DEVELOPERS RETURN:",
            *_wave_gate_actions(state_dir, fix_mode=False),
        ],
        "next": f"python3 -m {MODULE_PATH} --step 3 --state-dir {state_dir}",
    }


def _wave_gate_actions(state_dir: str, fix_mode: bool) -> list[str]:
    """Local gates every wave (and every code fix) must pass before review."""
    return [
        "  GATES (run the commands from verification_env; one at a time):",
        *_verification_env_lines(state_dir),
        "  1. Unit tests + typecheck for every touched package.",
        "  2. The wave's integration_tests against the REAL dependency (start it",
        "     if needed). Mocked tests cannot see wrong columns, casts or access",
        "     policies; these can. A missing or skipped integration test is a failure.",
        "  3. Any failure -> dispatch a developer with the failure output",
        "     (unclear cause -> dispatch debugger first). Never fix it yourself.",
        "  4. All green -> invoke the next step" + (" (re-check)." if fix_mode else " (code review)."),
    ]


def _wave_milestones_prompt(ctx: dict) -> str:
    state = _load_exec_state(ctx["state_dir"])
    waves = state.get("waves") or []
    idx = state.get("wave_index", 0)
    wave = waves[idx] if idx < len(waves) else []
    return (f"PLAN_FILE: {ctx['state_dir']}/plan.json\n"
            f"REVIEW WAVE MILESTONES: {', '.join(wave) or '(all)'}")


def step_impl_code_route(ctx: dict) -> GateResult:
    """Step 5: code gate. PASS advances the wave; FAIL loops to step 2."""
    state_dir = ctx["state_dir"]
    qr = ctx["qr"]
    state = _load_exec_state(state_dir)
    waves = state.get("waves") or []
    idx = state.get("wave_index", 0)

    if qr.passed:
        # Guard against a re-run of a passed gate: only advance when the QR
        # file is still present (deleted exactly once, here).
        if _delete_qr_file(state_dir, "impl-code") and idx < len(waves):
            # Reload: _delete_qr_file may have recorded known_issues.
            state = _load_exec_state(state_dir)
            for mid in waves[idx]:
                if mid not in state["completed"]:
                    state["completed"].append(mid)
            state["wave_index"] = idx + 1
            _save_exec_state(state_dir, state)
            idx += 1

    if idx < len(waves):
        pass_step = STEP_CODE_WORK
        pass_message = (f"Wave {idx}/{len(waves)} verified. "
                        f"Proceed to step 2 (next wave: {', '.join(waves[idx])}).")
    else:
        pass_step = STEP_LIVE_VERIFY
        pass_message = "All waves verified. Proceed to step 6 (ship + live verification)."

    return build_gate_output(
        module_path=MODULE_PATH,
        script_name="executor",
        qr_name="impl-code-qr-route",
        qr=qr,
        step=ctx["step"],
        work_step=STEP_CODE_WORK,
        pass_step=pass_step,
        pass_message=pass_message,
        fix_target=AgentRole.DEVELOPER,
        state_dir=state_dir,
    )


def _ship_actions(ctx: dict) -> list[str]:
    state_dir = ctx["state_dir"]
    return [
        "SHIP FIRST (the one exception to delegate-only: run it yourself via Bash):",
        *_verification_env_lines(state_dir),
        "  - Run the ship command from verification_env; capture output to a log",
        "    file and the exit code (never pipe through tail/head, it hides failures).",
        "  - Confirm the deployed build is the one you just built (health/version).",
        "  - Ship fails -> dispatch debugger with the log; do not verify an old build.",
        "",
    ]


def step_impl_live_verify(ctx: dict) -> dict:
    """Step 6: ship, then one agent verifies live checks on the deployed system."""
    state_dir = ctx["state_dir"]
    step = ctx["step"]
    plan = _load_plan(state_dir)

    if not qr_file_exists(state_dir, "impl-live"):
        count = write_live_items(state_dir, plan)
        if count == 0:
            _delete_qr_file(state_dir, "impl-live")
            return {
                "title": "impl-live-verify - Skipped",
                "actions": [
                    "No milestone declares live_checks: nothing to verify on a deployed system.",
                    "Record this in the retrospective (Verification Gaps).",
                ],
                "next": f"python3 -m {MODULE_PATH} --step {STEP_DOCS_WORK} --state-dir {state_dir}",
            }

    return _live_reverify(ctx)


def _live_prestep(ctx: dict) -> list[str]:
    return _ship_actions(ctx)


_live_reverify = reverify_step(MODULE_PATH, "impl-live-verify", "impl-live",
                               pre_actions=_live_prestep)


def step_impl_live_route(ctx: dict) -> GateResult:
    """Step 7: live gate. PASS -> docs; FAIL -> live fix (8)."""
    state_dir = ctx["state_dir"]
    qr = ctx["qr"]
    if qr.passed:
        _delete_qr_file(state_dir, "impl-live")
    return build_gate_output(
        module_path=MODULE_PATH,
        script_name="executor",
        qr_name="impl-live-qr-route",
        qr=qr,
        step=ctx["step"],
        work_step=STEP_LIVE_FIX,
        pass_step=STEP_DOCS_WORK,
        pass_message="Live checks verified on the deployed system. Proceed to step 9 (documentation).",
        fix_target=AgentRole.DEVELOPER,
        state_dir=state_dir,
    )


def step_impl_live_fix(ctx: dict) -> dict:
    """Step 8: one developer reproduces and fixes live failures, then back to 6."""
    state_dir = ctx["state_dir"]
    qr = ctx["qr"]
    mark_fix_dispatched(state_dir, "impl-live")
    dispatch = subagent_dispatch(
        agent_type="developer",
        command=f"python3 -m skills.planner.developer.exec_live_fix --step 1 --state-dir {state_dir}",
        prompt=f"PLAN_FILE: {state_dir}/plan.json\nFIX MODE: qr-impl-live.json has FAIL items.",
    )
    return {
        "title": "impl-live-fix",
        "actions": [
            format_state_banner("LIVE-FIX", qr.iteration, "fix"),
            "",
            ORCHESTRATOR_CONSTRAINT_EXTENDED,
            "",
            dispatch,
            "",
            "Developer returns PASS, or FAIL: ENVIRONMENT/<reason>.",
            "  FAIL: ENVIRONMENT -> fix the environment with the user (AskUserQuestion),",
            "                       then continue; do not change code for it.",
            "  PASS -> invoke the next step: it redeploys and re-checks the failed",
            "          items plus a regression sweep of the fix.",
        ],
        "next": f"python3 -m {MODULE_PATH} --step {STEP_LIVE_VERIFY} --state-dir {state_dir}",
    }


def step_impl_docs_work(ctx: dict) -> dict:
    """Step 9: technical writer documents the finished, live-verified change."""
    state_dir = ctx["state_dir"]
    qr = ctx["qr"]
    state = _load_exec_state(state_dir)
    invoke_cmd = f"python3 -m skills.planner.technical_writer.exec_docs --step 1 --state-dir {state_dir}"

    if qr.state == LoopState.RETRY:
        mark_fix_dispatched(state_dir, "impl-docs")
        banner = [format_state_banner("DOCUMENTATION-FIX", qr.iteration, "fix"), "",
                  "FIX MODE: Doc review found issues.", ""]
        prompt = f"PLAN_FILE: {state_dir}/plan.json\nFIX MODE: qr-impl-docs.json has FAIL items."
        title = "impl-docs-work - Fix Mode"
    else:
        banner = []
        prompt = (f"PLAN_FILE: {state_dir}/plan.json\n"
                  f"IMPLEMENTED MILESTONES: {', '.join(state.get('completed', [])) or '(see plan)'}\n"
                  f"Implementation is complete, code review passed, live checks passed.")
        title = "impl-docs-work"

    dispatch = subagent_dispatch(agent_type="technical-writer", command=invoke_cmd, prompt=prompt)
    return {
        "title": title,
        "actions": [*banner, ORCHESTRATOR_CONSTRAINT_EXTENDED, "", dispatch],
        "next": f"python3 -m {MODULE_PATH} --step 10 --state-dir {state_dir}",
    }


def step_impl_docs_route(ctx: dict) -> GateResult:
    """Step 12: doc gate. PASS -> retrospective; FAIL -> step 9."""
    state_dir = ctx["state_dir"]
    qr = ctx["qr"]
    if qr.passed:
        _delete_qr_file(state_dir, "impl-docs")
    return build_gate_output(
        module_path=MODULE_PATH,
        script_name="executor",
        qr_name="impl-docs-qr-route",
        qr=qr,
        step=ctx["step"],
        work_step=STEP_DOCS_WORK,
        pass_step=STEP_RETRO,
        pass_message="Documentation verified. Proceed to step 13 (retrospective).",
        fix_target=AgentRole.TECHNICAL_WRITER,
        state_dir=state_dir,
    )


def _known_issue_lines(state: dict) -> list[str]:
    known = state.get("known_issues") or []
    if not known:
        return ["Accepted Known Issues: none"]
    lines = [f"Accepted Known Issues ({len(known)}) -- gates passed with these still FAIL;",
             "  list EVERY one to the user with its finding:"]
    for k in known:
        lines.append(f"  [{k['phase']} {k['id']} {k['severity']}] {k['check']}")
        if k.get("finding"):
            lines.append(f"      {k['finding']}")
    return lines


def step_retrospective(ctx: dict) -> dict:
    """Step 13: terminal. Present execution summary to the user."""
    state_dir = ctx["state_dir"]
    state = _load_exec_state(state_dir)
    return {
        "title": "retrospective",
        "actions": [
            "EXECUTION COMPLETE.",
            "",
            "PRESENT retrospective to user (do not write to file):",
            "",
            "EXECUTION RETROSPECTIVE",
            "=======================",
            f"Plan: {state_dir}/plan.json",
            f"Milestones completed: {', '.join(state.get('completed', [])) or 'none'}",
            "Status: COMPLETED | BLOCKED | ABORTED",
            "",
            "Milestone Outcomes: | Milestone | Status | Notes |",
            "Deviations from Plan: [if any]",
            "Defects Caught, by gate: plan review | code review (per wave) |",
            "  integration tests | live checks -- one line each, with what escaped",
            "  to a later gate and why the earlier one could not see it",
            "Verification Gaps: [milestones without integration_tests/live_checks]",
            *_known_issue_lines(state),
            "Review Iterations: [per gate]",
            "Feedback for Future Plans: [actionable suggestions]",
        ],
        "next": "",
    }


# =============================================================================
# Step table
# =============================================================================

STEPS = {
    1: step_init,
    2: step_impl_code_work,
    3: review_step(MODULE_PATH, "impl-code-review", "impl-code", model="opus",
                   extra_prompt=_wave_milestones_prompt),
    4: reverify_step(MODULE_PATH, "impl-code-reverify", "impl-code"),
    5: step_impl_code_route,
    6: step_impl_live_verify,
    7: step_impl_live_route,
    8: step_impl_live_fix,
    9: step_impl_docs_work,
    10: review_step(MODULE_PATH, "impl-docs-review", "impl-docs", model="opus"),
    11: reverify_step(MODULE_PATH, "impl-docs-reverify", "impl-docs"),
    12: step_impl_docs_route,
    13: step_retrospective,
}
validate_step_count(STEPS, EXECUTOR_TOTAL_STEPS, "executor")

# Phase for QR-state detection (fix mode / iteration) per step.
STEP_PHASE = {2: "impl-code", 3: "impl-code", 4: "impl-code", 5: "impl-code",
              6: "impl-live", 7: "impl-live", 8: "impl-live",
              9: "impl-docs", 10: "impl-docs", 11: "impl-docs", 12: "impl-docs"}


def get_step_guidance(step: int, args) -> dict | GateResult:
    handler = STEPS.get(step)
    if not handler:
        return {"error": f"Invalid step {step}"}

    state_dir = args.state_dir
    phase = STEP_PHASE.get(step)
    iteration = get_qr_iteration(state_dir, phase) if state_dir and phase else 1
    is_fix_mode = bool(state_dir and phase and has_qr_failures(state_dir, phase))
    qr = QRState(
        iteration=iteration,
        state=LoopState.RETRY if is_fix_mode else LoopState.INITIAL,
        status=QRStatus(args.qr_status) if args.qr_status else None,
    )
    return handler({"step": step, "qr": qr, "state_dir": state_dir, "args": args, "phase": phase})


def format_output(step: int, args) -> str | GateResult:
    guidance = get_step_guidance(step, args)
    if isinstance(guidance, GateResult):
        return guidance
    if "error" in guidance:
        return f"Error: {guidance['error']}"

    body_parts = [THINKING_EFFICIENCY, ""] if step == 1 else []
    body_parts.extend(str(a) for a in guidance["actions"])
    body = "\n".join(body_parts)

    if guidance.get("if_pass") and guidance.get("if_fail"):
        return format_step(body, title=guidance["title"],
                           if_pass=guidance["if_pass"], if_fail=guidance["if_fail"])
    return format_step(body, guidance.get("next", ""), title=guidance["title"])


def main():
    parser = argparse.ArgumentParser(
        description="Lean Plan Executor (13-step orchestration workflow)",
        epilog="1: init | 2-5: code per wave | 6-8: ship + live | 9-12: docs | 13: retrospective",
    )
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--state-dir", type=str, default=None,
                        help="State directory (planner STATE_DIR, or one created by step 1)")
    parser.add_argument("--plan", type=str, default=None,
                        help="Step 1 only: plan.json, or plan.md with a sibling .json")
    parser.add_argument("--reconcile", action="store_true",
                        help="Step 1 only: verify existing code against pending milestones first")
    parser.add_argument("--done", action="append", default=[],
                        help="Step 1 only: milestone ID already satisfied (repeatable)")
    add_qr_args(parser)
    args = parser.parse_args()

    if args.step < 1 or args.step > EXECUTOR_TOTAL_STEPS:
        sys.exit(f"Error: step must be 1-{EXECUTOR_TOTAL_STEPS}")

    if args.step > 1:
        if not args.state_dir:
            sys.exit(f"Error: --state-dir required for step {args.step} (printed by step 1 as STATE_DIR=...)")
        from skills.planner.shared.schema import validate_state, SchemaValidationError
        try:
            validate_state(args.state_dir)
        except SchemaValidationError as e:
            sys.exit(f"Schema validation failed: {e}")

    if args.step in EXECUTOR_GATE_STEPS and not args.qr_status:
        print(f"EXECUTOR - Step {args.step}/{EXECUTOR_TOTAL_STEPS}: route step")
        print()
        print("Re-invoke with --qr-status pass or --qr-status fail")
        print("based on the previous step's output.")
        sys.exit(0)

    result = format_output(args.step, args)
    print(result.output if isinstance(result, GateResult) else result)


if __name__ == "__main__":
    main()
