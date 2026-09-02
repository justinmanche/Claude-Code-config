#!/usr/bin/env python3
"""
Plan Executor - 10-step execution orchestrator with parallel QR verification.

Mirrors orchestrator/planner.py: every step prints a prompt and the exact
command for the next step. Sub-agents run the scripts in developer/,
technical_writer/ and quality_reviewer/; the orchestrator LLM only dispatches.

Flow (step numbers match shared/qr/phases.py and shared/constants.py):
   1  exec-init               orchestrator  locate plan.json, build waves
   2  impl-code-work          developer xN  one per milestone in current wave
                                            (fix mode: one developer, via router)
   3  impl-code-qr-decompose  QR (opus)     qr-impl-code.json
   4  impl-code-qr-verify     QR xN         parallel item verification
   5  impl-code-qr-route      orchestrator  FAIL -> 2 | PASS+more waves -> 2 | PASS -> 6
   6  impl-docs-work          technical-writer
   7  impl-docs-qr-decompose  QR (opus)     qr-impl-docs.json
   8  impl-docs-qr-verify     QR xN
   9  impl-docs-qr-route      orchestrator  FAIL -> 6 | PASS -> 10
  10  retrospective           orchestrator  terminal

Wave state lives in STATE_DIR/exec-state.json (Python-managed; the LLM never
reads it). Code QR runs per wave so a broken foundation wave is caught before
dependent waves build on it. Documentation runs once, after all waves, because
exec_docs_execute.py documents finished implementation.

Why docs are not per-wave (deviation from the original INTENT.md sketch):
re-documenting after every wave re-does CLAUDE.md/README work N times for
one final state. One TW pass over the completed implementation is cheaper
and produces the same artifact.
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
from skills.planner.shared.qr.utils import (
    qr_file_exists,
    increment_qr_iteration,
    get_qr_iteration,
    has_qr_failures,
    load_qr_state,
    query_items,
    by_status,
    by_blocking_severity,
)
from skills.planner.shared.qr.phases import get_phase_config
from skills.planner.shared.resources import get_mode_script_path
from skills.planner.shared.builders import THINKING_EFFICIENCY, format_forbidden
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
    p = Path(state_dir) / f"qr-{phase}.json"
    if p.exists():
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
                "Proceeding to documentation.",
            ],
            "next": f"python3 -m {MODULE_PATH} --step 6 --state-dir {state_dir}",
        }

    actions = [
        f"PLAN: {state_dir}/plan.json",
        f"MILESTONES: {len(plan.get('milestones', []))} total, "
        f"{len(state['completed'])} already complete, {len(pending)} pending",
        "",
        "WAVES (milestones in one wave run in parallel; waves run in order):",
        *_format_wave_table(state["waves"], plan, state["wave_index"]),
        "",
        "WORKFLOW PER WAVE: developers -> tests -> Code QR -> route",
        "After the last wave passes Code QR: documentation -> Doc QR -> retrospective.",
        "",
        "This step is ANALYSIS ONLY. Set up TodoWrite tracking for the waves.",
        "Do NOT dispatch agents here.",
    ]
    return {
        "title": "exec-init",
        "actions": actions,
        "next": f"python3 -m {MODULE_PATH} --step 2 --state-dir {state_dir}",
    }


def step_impl_code_work(ctx: dict) -> dict:
    """Step 2: dispatch developers for the current wave (or one fixer)."""
    state_dir = ctx["state_dir"]
    qr = ctx["qr"]
    plan = _load_plan(state_dir)
    state = _load_exec_state(state_dir)
    invoke_cmd = f"python3 -m skills.planner.developer.exec_implement --step 1 --state-dir {state_dir}"

    if qr.state == LoopState.RETRY:
        # Router (exec_implement.py) detects FAIL items and runs the fix script.
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
                "FIX MODE: Code QR found issues.",
                "",
                ORCHESTRATOR_CONSTRAINT_EXTENDED,
                "",
                dispatch,
                "",
                "Developer reads qr-impl-code.json and fixes every FAIL item.",
                "After fixes complete, QR re-verifies the failed items.",
            ],
            "next": f"python3 -m {MODULE_PATH} --step 3 --state-dir {state_dir}",
        }

    waves = state.get("waves") or []
    idx = state.get("wave_index", 0)
    if idx >= len(waves):
        return {
            "title": "impl-code-work",
            "actions": ["No pending waves. Proceeding to documentation."],
            "next": f"python3 -m {MODULE_PATH} --step 6 --state-dir {state_dir}",
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
        })

    tmpl = (
        f"Implement MILESTONE $mid: $name\n"
        f"PLAN_FILE: {state_dir}/plan.json\n"
        f"FILES: $files\n"
        f"ACCEPTANCE CRITERIA:\n$criteria\n"
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
            "  1. Run the project's full test suite once (pytest / tsc / go test -race).",
            "     Pass criteria: 100% tests pass, zero warnings.",
            "  2. Tests fail -> dispatch a developer with the failure output (never fix yourself).",
            "     Unclear cause -> dispatch debugger first.",
            "  3. Tests pass -> next step (Code QR for this wave).",
        ],
        "next": f"python3 -m {MODULE_PATH} --step 3 --state-dir {state_dir}",
    }


def qr_decompose_step(title: str, phase: str, model: str | None = "opus"):
    """Steps 3, 7: dispatch one QR agent to write qr-{phase}.json.

    Runs once per QR cycle: if qr-{phase}.json already exists (fix loop),
    decomposition is skipped and the existing items are re-verified.
    """
    def handler(ctx: dict) -> dict:
        state_dir = ctx["state_dir"]
        qr = ctx["qr"]
        step = ctx["step"]

        if qr_file_exists(state_dir, phase):
            return {
                "title": f"{title} - Skipped (items already defined)",
                "actions": [
                    f"QR items for {phase} already defined.",
                    "Proceeding to verification of existing items.",
                ],
                "next": f"python3 -m {MODULE_PATH} --step {step + 1} --state-dir {state_dir}",
            }

        decompose_script = get_phase_config(phase)["decompose_script"]
        dispatch = subagent_dispatch(
            agent_type="quality-reviewer",
            command=f"python3 -m {decompose_script} --step 1 --state-dir {state_dir}",
            model=model,
        )
        return {
            "title": title,
            "actions": [
                format_state_banner(f"QR-{phase.upper()}-DECOMPOSE", qr.iteration, "decompose"),
                "",
                ORCHESTRATOR_CONSTRAINT_EXTENDED,
                "",
                dispatch,
                "",
                f"Expected output: qr-{phase}.json written to STATE_DIR.",
                "Orchestrator generates verification dispatch from this file.",
            ],
            "next": f"python3 -m {MODULE_PATH} --step {step + 1} --state-dir {state_dir}",
        }

    handler.phase = phase
    return handler


def _qr_item_flags(item_ids: list[str]) -> str:
    return " ".join(f"--qr-item {i}" for i in item_ids)


def qr_verify_step(title: str, phase: str):
    """Steps 4, 8: parallel verification, one agent per item group."""
    def handler(ctx: dict) -> dict:
        state_dir = ctx["state_dir"]
        qr = ctx["qr"]
        step = ctx["step"]

        qr_state = load_qr_state(state_dir, phase)
        if not qr_state or "items" not in qr_state:
            return {"error": f"qr-{phase}.json not found or malformed in {state_dir}"}

        if qr.state == LoopState.RETRY:
            increment_qr_iteration(state_dir, phase)

        iteration = qr_state.get("iteration", 1)
        items = query_items(qr_state, by_status("TODO", "FAIL"), by_blocking_severity(iteration))
        base_cmd = f"python3 -m {MODULE_PATH} --step {step + 1} --state-dir {state_dir}"
        if not items:
            return {
                "title": title,
                "actions": ["All items already verified. Proceeding with pass."],
                "if_pass": f"{base_cmd} --qr-status pass",
                "if_fail": f"{base_cmd} --qr-status pass",
            }

        verify_script = get_phase_config(phase)["verify_script"]
        groups: dict[str, list[dict]] = {}
        for item in items:
            groups.setdefault(item.get("group_id") or item["id"], []).append(item)

        targets = [{
            "group_id": gid,
            "item_ids": ",".join(i["id"] for i in gi),
            "qr_item_flags": _qr_item_flags([i["id"] for i in gi]),
            "item_count": str(len(gi)),
            "checks_summary": "; ".join(i.get("check", "")[:40] for i in gi[:3]),
        } for gid, gi in groups.items()]

        tmpl = (f"Verify QR group: $group_id ($item_count items)\n"
                f"Items: $item_ids\n"
                f"Checks: $checks_summary\n\n"
                f"Start: python3 -m {verify_script} --step 1 --state-dir {state_dir} $qr_item_flags")
        command = f"python3 -m {verify_script} --step 1 --state-dir {state_dir} $qr_item_flags"

        dispatch = template_dispatch(
            agent_type="quality-reviewer",
            template=tmpl,
            targets=targets,
            command=command,
            instruction=f"Verify {len(groups)} groups ({len(items)} items) in parallel.",
        )

        return {
            "title": title,
            "actions": [
                ORCHESTRATOR_CONSTRAINT_EXTENDED,
                "",
                "=== PHASE 1: DISPATCH (delegate to sub-agents) ===",
                "",
                f"VERIFY: {len(items)} items",
                "",
                dispatch,
                "",
                "=== PHASE 2: AGGREGATE (your action after all agents return) ===",
                "",
                f"After ALL {len(groups)} agents return, tally results mechanically:",
                "  ALL agents returned PASS  ->  invoke next step with --qr-status pass",
                "  ANY agent returned FAIL   ->  invoke next step with --qr-status fail",
                "",
                format_forbidden(
                    "Interpreting results beyond PASS/FAIL tallying",
                    "Claiming 'diminishing returns' or 'comprehensive enough'",
                    "Reading plan.json or any state files",
                    "Fixing code yourself",
                    "Skipping the next step command",
                    "Proceeding to a later step without QR PASS",
                ),
            ],
            "if_pass": f"{base_cmd} --qr-status pass",
            "if_fail": f"{base_cmd} --qr-status fail",
        }

    handler.phase = phase
    return handler


def step_impl_code_route(ctx: dict) -> GateResult:
    """Step 5: Code QR gate. PASS advances the wave; FAIL loops to step 2."""
    state_dir = ctx["state_dir"]
    qr = ctx["qr"]
    state = _load_exec_state(state_dir)
    waves = state.get("waves") or []
    idx = state.get("wave_index", 0)

    if qr.passed:
        # Guard against a re-run of a passed gate: only advance when the QR
        # file is still present (deleted exactly once, here).
        if _delete_qr_file(state_dir, "impl-code") and idx < len(waves):
            for mid in waves[idx]:
                if mid not in state["completed"]:
                    state["completed"].append(mid)
            state["wave_index"] = idx + 1
            _save_exec_state(state_dir, state)
            idx += 1

    more_waves = idx < len(waves)
    if more_waves:
        pass_step = 2
        pass_message = (f"Wave {idx}/{len(waves)} verified. "
                        f"Proceed to step 2 (next wave: {', '.join(waves[idx])}).")
    else:
        pass_step = 6
        pass_message = "All waves verified. Proceed to step 6 (documentation)."

    return build_gate_output(
        module_path=MODULE_PATH,
        script_name="executor",
        qr_name="impl-code-qr-route",
        qr=qr,
        step=ctx["step"],
        work_step=2,
        pass_step=pass_step,
        pass_message=pass_message,
        fix_target=AgentRole.DEVELOPER,
        state_dir=state_dir,
    )


def step_impl_docs_work(ctx: dict) -> dict:
    """Step 6: technical writer documents the finished implementation."""
    state_dir = ctx["state_dir"]
    qr = ctx["qr"]
    state = _load_exec_state(state_dir)
    invoke_cmd = f"python3 -m skills.planner.technical_writer.exec_docs --step 1 --state-dir {state_dir}"

    if qr.state == LoopState.RETRY:
        banner = [format_state_banner("DOCUMENTATION-FIX", qr.iteration, "fix"), "",
                  "FIX MODE: Doc QR found issues.", ""]
        prompt = f"PLAN_FILE: {state_dir}/plan.json\nFIX MODE: qr-impl-docs.json has FAIL items."
        title = "impl-docs-work - Fix Mode"
    else:
        banner = []
        prompt = (f"PLAN_FILE: {state_dir}/plan.json\n"
                  f"IMPLEMENTED MILESTONES: {', '.join(state.get('completed', [])) or '(see plan)'}\n"
                  f"Implementation is complete and Code QR has passed.")
        title = "impl-docs-work"

    dispatch = subagent_dispatch(agent_type="technical-writer", command=invoke_cmd, prompt=prompt)
    return {
        "title": title,
        "actions": [*banner, ORCHESTRATOR_CONSTRAINT_EXTENDED, "", dispatch],
        "next": f"python3 -m {MODULE_PATH} --step 7 --state-dir {state_dir}",
    }


def step_impl_docs_route(ctx: dict) -> GateResult:
    """Step 9: Doc QR gate. PASS -> retrospective; FAIL -> step 6."""
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
        work_step=6,
        pass_step=10,
        pass_message="Documentation verified. Proceed to step 10 (retrospective).",
        fix_target=AgentRole.TECHNICAL_WRITER,
        state_dir=state_dir,
    )


def step_retrospective(ctx: dict) -> dict:
    """Step 10: terminal. Present execution summary to the user."""
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
            "Reconciliation Summary: [if run]",
            "Plan Accuracy Issues: [if any]",
            "Deviations from Plan: [if any]",
            "Quality Review Summary: [counts by category, iterations per phase]",
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
    3: qr_decompose_step("impl-code-qr-decompose", "impl-code"),
    4: qr_verify_step("impl-code-qr-verify", "impl-code"),
    5: step_impl_code_route,
    6: step_impl_docs_work,
    7: qr_decompose_step("impl-docs-qr-decompose", "impl-docs"),
    8: qr_verify_step("impl-docs-qr-verify", "impl-docs"),
    9: step_impl_docs_route,
    10: step_retrospective,
}
validate_step_count(STEPS, EXECUTOR_TOTAL_STEPS, "executor")

# Phase for QR-state detection (fix mode / iteration) per step.
STEP_PHASE = {2: "impl-code", 3: "impl-code", 4: "impl-code", 5: "impl-code",
              6: "impl-docs", 7: "impl-docs", 8: "impl-docs", 9: "impl-docs"}


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
    return handler({"step": step, "qr": qr, "state_dir": state_dir, "args": args})


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
        description="Plan Executor (10-step orchestration workflow)",
        epilog="Step 1: init (needs --plan or --state-dir) | 2-5: code per wave | 6-9: docs | 10: retrospective",
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
        print("based on the aggregated QR output from the previous step.")
        sys.exit(0)

    result = format_output(args.step, args)
    print(result.output if isinstance(result, GateResult) else result)


if __name__ == "__main__":
    main()
