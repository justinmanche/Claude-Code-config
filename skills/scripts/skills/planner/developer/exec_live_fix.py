#!/usr/bin/env python3
"""Live-check fix - repair a defect observed on the deployed system.

3-step workflow for ONE developer sub-agent:
  1. Reproduce (below the UI, at the layer that failed)
  2. Fix + add the test that would have caught it
  3. Validate (full local gates) and return

Dispatched by executor step 8 when qr-impl-live.json has blocking FAIL items.
The orchestrator redeploys and re-verifies after this returns.
"""

from skills.planner.shared.constraints import format_state_banner
from skills.planner.shared.resources import validate_state_dir_requirement
from skills.planner.shared.qr.utils import (
    load_qr_state,
    format_failed_items_for_fix,
    get_qr_iteration,
)


PHASE = "impl-live"

STEPS = {
    1: "Reproduce Live Failures",
    2: "Fix and Add the Missing Test",
    3: "Validate and Return",
}


def get_step_guidance(step: int, module_path: str = None, **kwargs) -> dict:
    MODULE_PATH = module_path or "skills.planner.developer.exec_live_fix"
    state_dir = kwargs.get("state_dir", "")

    if step == 1:
        validate_state_dir_requirement(step, state_dir)
        iteration = get_qr_iteration(state_dir, PHASE)
        qr_state = load_qr_state(state_dir, PHASE)
        failed = format_failed_items_for_fix(qr_state) if qr_state else ""
        return {
            "title": STEPS[1],
            "actions": [
                format_state_banner("LIVE-FIX", iteration, "fix"),
                "",
                "The deployed system failed these user-layer checks:",
                "",
                failed or f"Read: {state_dir}/qr-impl-live.json (status FAIL items)",
                "",
                "Read verification_env for how the project runs and deploys:",
                f"  cat {state_dir}/context.json | jq '.verification_env'",
                "",
                "For EACH failure, find the ROOT CAUSE before editing anything:",
                "  - Reproduce below the UI: the API call, the query, the policy,",
                "    run as the same identity/role/tenant the user had.",
                "  - Server logs for the failing request are primary evidence.",
                "  - Findings starting 'ENVIRONMENT:' are not code defects: report",
                "    them instead of changing code (see step 3).",
                "",
                "Write down, per failure: root cause (file:line) and why every",
                "earlier gate (unit tests, code review) missed it.",
            ],
            "next": f"python3 -m {MODULE_PATH} --step 2 --state-dir {state_dir}",
        }

    if step == 2:
        return {
            "title": STEPS[2],
            "actions": [
                "FIX each root cause, smallest correct change.",
                "",
                "ADD THE TEST THAT WOULD HAVE CAUGHT IT, at the layer that failed:",
                "  - wrong column/type/cast, RLS/tenant denial, cross-party write:",
                "    an integration test against the REAL dependency (real database",
                "    with its policies), running as the identity that failed.",
                "  - UI behaviour: a component test that renders the real state",
                "    transition, not a mock of it.",
                "A fix without that test is incomplete: the next change will",
                "reintroduce the defect and nothing will notice.",
                "",
                "CONSTRAINT: fix only these failures. Do not refactor passing code.",
            ],
            "next": f"python3 -m {MODULE_PATH} --step 3 --state-dir {state_dir}",
        }

    if step == 3:
        return {
            "title": STEPS[3],
            "actions": [
                "VALIDATE locally before returning:",
                "  1. Unit tests + typecheck for the touched packages.",
                "  2. The new integration test(s) against the real dependency,",
                "     plus the plan's integration_tests for affected milestones.",
                "  3. Confirm the new test FAILS without your fix (revert-check),",
                "     then passes with it.",
                "",
                "Do NOT deploy; the orchestrator deploys and re-verifies live.",
                "",
                "RETURN exactly one of:",
                "  PASS",
                "  FAIL: ENVIRONMENT <what blocks the check; no code change made>",
                "  FAIL: <one-line reason a fix was not possible>",
            ],
            "next": "",
        }

    return {"error": f"Invalid step {step}"}


if __name__ == "__main__":
    from skills.lib.workflow.cli import mode_main

    mode_main(
        __file__,
        get_step_guidance,
        "Exec-Live-Fix: repair defects observed on the deployed system",
        extra_args=[
            (["--state-dir"], {"type": str, "required": True, "help": "State directory path"}),
        ],
    )
