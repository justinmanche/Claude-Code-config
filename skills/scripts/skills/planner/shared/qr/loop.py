"""Review and re-verify step builders shared by planner.py and executor.py.

The lean QR loop per gate:

  work ──> review (1 agent, writes verdicts) ──> reverify ──> route
    ^                                               │            │
    └──────── fix (work step, RETRY) <──────────────┴── FAIL ────┘

  reverify, first pass after review : no agent; Python reads the verdicts
                                      and emits the route command itself.
  reverify, after a fix             : ONE agent re-checks the blocking FAIL
                                      items plus a fresh regression-sweep item.

State lives in qr-{phase}.json: `awaiting_reverify` is set by the work step
when it dispatches a fixer and cleared here when the re-check is dispatched.
Iteration increments only on a re-check, so severity de-escalation
(shared/qr/constants.get_blocking_severities) counts fix rounds.
"""

from __future__ import annotations

from skills.lib.workflow.prompts import subagent_dispatch
from skills.planner.shared.builders import format_forbidden
from skills.planner.shared.constraints import ORCHESTRATOR_CONSTRAINT_EXTENDED, format_state_banner
from skills.planner.shared.qr.constants import QR_ITERATION_LIMIT
from skills.planner.shared.qr.phases import get_phase_config
from skills.planner.shared.qr.utils import (
    add_regression_item,
    blocking_failures,
    by_blocking_severity,
    by_status,
    increment_qr_iteration,
    is_awaiting_reverify,
    load_qr_state,
    qr_file_exists,
    query_items,
    set_awaiting_reverify,
    set_qr_flag,
)


def mark_fix_dispatched(state_dir: str, phase: str) -> None:
    """Call from a work step when it dispatches a fixer (RETRY mode)."""
    set_awaiting_reverify(state_dir, phase, True)


def review_step(module_path: str, title: str, phase: str, model: str | None = "opus",
                extra_prompt=None):
    """Dispatch the single deep reviewer. Skipped when verdicts already exist.

    extra_prompt: optional callable(ctx) -> str appended to the dispatch
    (the executor passes the current wave's milestone IDs).
    """
    def handler(ctx: dict) -> dict:
        state_dir = ctx["state_dir"]
        step = ctx["step"]
        next_cmd = f"python3 -m {module_path} --step {step + 1} --state-dir {state_dir}"

        if qr_file_exists(state_dir, phase):
            return {
                "title": f"{title} - Skipped (verdicts already recorded)",
                "actions": [f"qr-{phase}.json exists. Proceeding to re-verify/route."],
                "next": next_cmd,
            }

        review_script = get_phase_config(phase)["review_script"]
        prompt = extra_prompt(ctx) if extra_prompt else ""
        dispatch = subagent_dispatch(
            agent_type="quality-reviewer",
            command=f"python3 -m {review_script} --step 1 --state-dir {state_dir}",
            prompt=prompt,
            model=model,
        )
        return {
            "title": title,
            "actions": [
                format_state_banner(f"QR-{phase.upper()}-REVIEW", 1, "review"),
                "",
                ORCHESTRATOR_CONSTRAINT_EXTENDED,
                "",
                dispatch,
                "",
                f"The reviewer writes qr-{phase}.json with a verdict on every item",
                "and returns one word. Whatever it returns, invoke the next step:",
                "the next step reads the verdicts from the file.",
            ],
            "next": next_cmd,
        }

    handler.phase = phase
    return handler


def reverify_step(module_path: str, title: str, phase: str, pre_actions=None):
    """First pass: route on recorded verdicts. After a fix: one re-check agent.

    pre_actions: optional callable(ctx) -> list[str] of actions that must run
    before a re-check agent is dispatched (the live gate redeploys here).
    Returned as-is when the re-check needs no agent.
    """
    def handler(ctx: dict) -> dict:
        state_dir = ctx["state_dir"]
        step = ctx["step"]
        route_cmd = f"python3 -m {module_path} --step {step + 1} --state-dir {state_dir}"

        qr_state = load_qr_state(state_dir, phase)
        if not qr_state or "items" not in qr_state:
            return {"error": f"qr-{phase}.json not found or malformed in {state_dir}"}

        if not is_awaiting_reverify(state_dir, phase):
            # Verdicts were just recorded by the reviewer (or by a previous
            # re-check): route on them mechanically, no agent.
            failing = blocking_failures(state_dir, phase)
            status = "fail" if failing else "pass"
            lines = [f"  {i['id']} [{i.get('severity', 'SHOULD')}]: {i.get('check', '')[:70]}"
                     for i in failing]
            return {
                "title": f"{title} - Verdicts recorded",
                "actions": [
                    f"qr-{phase}.json: {len(qr_state['items'])} items, "
                    f"{len(failing)} blocking FAIL at iteration {qr_state.get('iteration', 1)}.",
                    *lines,
                    "",
                    f"Invoke the next step with --qr-status {status} (computed; do not change it).",
                ],
                "next": f"{route_cmd} --qr-status {status}",
            }

        # A fixer ran since the last verdicts: re-check -- unless the fix-round
        # budget is spent, in which case the user decides first. Escalation
        # does not increment the iteration and leaves awaiting_reverify set,
        # so "one more round" re-enters this step and re-checks the fix that
        # already ran, instead of re-escalating on stale findings.
        current = qr_state.get("iteration", 1)
        if current >= QR_ITERATION_LIMIT and not qr_state.get("extra_round"):
            set_qr_flag(state_dir, phase, "extra_round", True)
            failing = blocking_failures(state_dir, phase)
            return {
                "title": f"{title} - ESCALATE",
                "actions": [
                    f"Fix-round limit ({QR_ITERATION_LIMIT}) reached with "
                    f"{len(failing)} blocking FAIL item(s) in qr-{phase}.json:",
                    *[f"  {i['id']}: {i.get('finding', '')[:160]}" for i in failing],
                    "",
                    "STOP. Present these to the user (AskUserQuestion) and follow their choice:",
                    "  Re-check the latest fix once more -> re-run THIS step:",
                    f"      python3 -m {module_path} --step {step} --state-dir {state_dir}",
                    "  Accept the remaining items as known issues -> --qr-status pass",
                    "  Stop the workflow -> do nothing further",
                    f"      (accept: {route_cmd} --qr-status pass)",
                ],
                # No default next command: the user must choose.
                "next": "",
            }
        if qr_state.get("extra_round"):
            set_qr_flag(state_dir, phase, "extra_round", False)
        iteration = increment_qr_iteration(state_dir, phase) or 1

        # Iteration 1 here is the live gate's first check round (nothing was
        # fixed yet); every later re-check follows a fix and sweeps its diff.
        regression_check = get_phase_config(phase).get("regression_check")
        if regression_check and iteration >= 2:
            add_regression_item(state_dir, phase, regression_check)
        set_awaiting_reverify(state_dir, phase, False)

        qr_state = load_qr_state(state_dir, phase)
        items = query_items(qr_state, by_status("TODO", "FAIL"), by_blocking_severity(iteration))
        if not items:
            return {
                "title": title,
                "actions": ["No blocking items left to re-check. Proceeding with pass."],
                "next": f"{route_cmd} --qr-status pass",
            }

        verify_script = get_phase_config(phase)["verify_script"]
        flags = " ".join(f"--qr-item {i['id']}" for i in items)
        dispatch = subagent_dispatch(
            agent_type="quality-reviewer",
            command=f"python3 -m {verify_script} --step 1 --state-dir {state_dir} {flags}",
        )
        pre = pre_actions(ctx) if pre_actions else []
        return {
            "title": f"{title} - Iteration {iteration}",
            "actions": [
                format_state_banner(f"QR-{phase.upper()}-REVERIFY", iteration, "reverify"),
                "",
                ORCHESTRATOR_CONSTRAINT_EXTENDED,
                "",
                *pre,
                (f"RE-CHECK {len(items)} item(s) with ONE agent "
                 f"(failed items + regression sweep):" if iteration >= 2 else
                 f"CHECK {len(items)} item(s) with ONE agent (first round):"),
                "",
                dispatch,
                "",
                "The agent's final response is one word:",
                "  PASS  ->  invoke next step with --qr-status pass",
                "  FAIL  ->  invoke next step with --qr-status fail",
                "",
                format_forbidden(
                    "Interpreting the result beyond PASS/FAIL",
                    "Dispatching more than one re-check agent",
                    "Reading or editing qr files yourself",
                    "Fixing issues yourself",
                ),
            ],
            "if_pass": f"{route_cmd} --qr-status pass",
            "if_fail": f"{route_cmd} --qr-status fail",
        }

    handler.phase = phase
    return handler
