#!/usr/bin/env python3
"""Impl code execution - single-milestone implementation workflow.

4-step workflow for ONE developer sub-agent implementing ONE milestone:
  1. Locate Milestone (read assignment from plan.json)
  2. Implement (from the milestone's code_intents; there are no planned diffs)
  3. Verify (tests + acceptance criteria)
  4. Return (single-word contract)

The orchestrator (executor.py step 2) dispatches one developer per milestone
in the current wave; parallelism lives at the orchestrator level, not here.
Sub-agents cannot spawn sub-agents, so this script never says "dispatch".

This is the EXECUTE script for first-time implementation.
For QR fix mode, see exec_implement_qr_fix.py.
Router (exec_implement.py) dispatches to appropriate script.
"""

from skills.planner.shared.constraints import format_state_banner


STEPS = {
    1: "Locate Milestone",
    2: "Implement",
    3: "Verify",
    4: "Return",
}


def get_step_guidance(
    step: int, module_path: str = None, **kwargs) -> dict:
    """Return guidance for the given step."""
    MODULE_PATH = module_path or "skills.planner.developer.exec_implement_execute"
    state_dir = kwargs.get("state_dir", "")
    state_dir_arg = f" --state-dir {state_dir}" if state_dir else ""
    plan_ref = f"{state_dir}/plan.json" if state_dir else "the PLAN_FILE named in your prompt"

    if step == 1:
        banner = format_state_banner("IMPLEMENTATION", 1, "work")
        return {
            "title": STEPS[1],
            "actions": [
                banner,
                "",
                "You are ONE developer implementing ONE milestone.",
                "Your prompt names the MILESTONE id. Read its spec:",
                "",
                f"  cat {plan_ref} | jq '.milestones[] | select(.id==\"<MILESTONE-ID>\")'",
                "",
                "Also read for context:",
                f"  cat {plan_ref} | jq '{{overview, planning_context, invisible_knowledge}}'",
                "",
                "UNDERSTAND before writing code:",
                "  - files: what you may create/modify",
                "  - code_intents: WHAT must change and why (decision_refs); YOU decide how",
                "  - acceptance_criteria: what done means",
                "  - tests: unit tests to write",
                "  - integration_tests: tests against the REAL dependency (database with",
                "    its access policies, etc.) -- required, not optional",
                "  - live_checks: what will be verified on the deployed system later;",
                "    make sure your change can actually produce that observation",
                "  - constraints (planning_context): MUST/SHOULD/MUST-NOT",
            ],
            "next": f"python3 -m {MODULE_PATH} --step 2{state_dir_arg}",
        }

    elif step == 2:
        return {
            "title": STEPS[2],
            "actions": [
                "IMPLEMENT the milestone.",
                "",
                "  - Implement each code_intent against the ACTUAL current code. Before",
                "    writing a query, read the migration that defines its tables/types;",
                "    before a guarded route, read the permission it must check; before a",
                "    cross-tenant read/write, check which identity it runs under.",
                "  - Add a WHY comment where a decision (DL-xxx) is not obvious from code.",
                "  - Write the unit tests AND the integration_tests listed in the milestone.",
                "",
                "SCOPE:",
                "  - Touch ONLY this milestone's files (plus new test files).",
                "  - Other milestones in this wave run in parallel agents --",
                "    do NOT implement or 'improve' their files.",
                "  - Deviations from plan are allowed when the code demands it;",
                "    record each deviation for your final report.",
            ],
            "next": f"python3 -m {MODULE_PATH} --step 3{state_dir_arg}",
        }

    elif step == 3:
        return {
            "title": STEPS[3],
            "actions": [
                "VERIFY your milestone.",
                "",
                "1. Run unit tests + typecheck for touched packages (commands in",
                "   context.json verification_env). 100% pass, zero warnings.",
                "2. Run this milestone's integration_tests against the real dependency.",
                "   Start the dependency if needed. A mocked substitute does not count.",
                "3. Check EVERY acceptance criterion explicitly.",
                "",
                "If tests or criteria fail: fix and re-verify. You ARE the",
                "developer -- do not report failures you can fix yourself.",
            ],
            "next": f"python3 -m {MODULE_PATH} --step 4{state_dir_arg}",
        }

    elif step == 4:
        return {
            "title": STEPS[4],
            "actions": [
                "RETURN to orchestrator.",
                "",
                "If all criteria met and tests pass, your complete response is exactly:",
                "  PASS",
                "Optionally followed by one line per deviation from the plan:",
                "  DEVIATION: <what and why>",
                "",
                "If blocked (criterion unattainable, contradiction in plan):",
                "  FAIL: <one-line reason>",
                "",
                "No summaries, no file lists, no other text.",
            ],
            "next": "",
        }

    return {"error": f"Invalid step {step}"}


if __name__ == "__main__":
    from skills.lib.workflow.cli import mode_main

    mode_main(
        __file__,
        get_step_guidance,
        "Exec-Implement-Execute: Single-milestone implementation workflow",
        extra_args=[
            (["--state-dir"], {"type": str, "help": "State directory path"}),
        ],
    )
