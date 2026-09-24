"""Single source of truth for QR phase configurations.

Definition locality: understanding a phase's configuration requires
reading only THIS file. Scripts import from here instead of duplicating
phase-specific knowledge across 4+ files per phase.

This works by:
1. QR_PHASES dict defines all phase configurations
2. get_phase_config() provides single entry point
3. Scripts import from here, not from each other
4. Changes to phase config require editing only THIS file

Invariants:
- Each phase has exactly one entry in QR_PHASES
- Step numbers match orchestrator STEPS dict
- Script paths are valid Python module paths
- Artifact paths are relative to state_dir
"""

from __future__ import annotations


# Phase configuration registry - ALL phase definitions in ONE place
#
# Keys: phase name as used in qr-{phase}.json filename
# Values: dict with:
#   workflow: "planner" or "executor"
#   work_step: orchestrator step that dispatches work agent
#   review_step: orchestrator step that dispatches the single deep reviewer
#   verify_step: orchestrator step that re-verifies failed items after a fix
#                (one agent, failed items + a regression sweep)
#   route_step: orchestrator step that routes based on QR result
#   artifact: primary artifact being reviewed (relative to state_dir)
#   review_script: Python module for the reviewer (None: items are derived)
#   verify_script: Python module for item verification
#   regression_check: check text added as a fresh item on every re-verify,
#                     so a fix cannot silently break what it did not touch

QR_PHASES: dict[str, dict] = {
    "plan-design": {
        "workflow": "planner",
        "work_step": 3,
        "review_step": 4,
        "verify_step": 5,
        "route_step": 6,
        "artifact": "plan.json",
        "review_script": "skills.planner.quality_reviewer.plan_design_review",
        "verify_script": "skills.planner.quality_reviewer.plan_design_qr_verify",
        "regression_check": (
            "REGRESSION SWEEP: the edits the architect made to plan.json in the last "
            "fix round introduce no new contradiction -- with the codebase (re-read the "
            "code each changed intent names), with other milestones, or with a decision."
        ),
    },
    "impl-code": {
        "workflow": "executor",
        "work_step": 2,
        "review_step": 3,
        "verify_step": 4,
        "route_step": 5,
        "artifact": "plan.json",
        "review_script": "skills.planner.quality_reviewer.impl_code_review",
        "verify_script": "skills.planner.quality_reviewer.impl_code_qr_verify",
        "regression_check": (
            "REGRESSION SWEEP: read `git diff` of the files the last fix round touched. "
            "No new defect: callers still match changed signatures; SQL still names real "
            "columns and types; no permission or tenant-scope check removed; no test "
            "weakened, skipped or reshaped to pass; the milestone's integration_tests still run."
        ),
    },
    "impl-live": {
        "workflow": "executor",
        "work_step": 8,
        "review_step": None,  # items come from plan.json live_checks, not a reviewer
        "verify_step": 6,
        "route_step": 7,
        "artifact": "plan.json",
        "review_script": None,
        "verify_script": "skills.planner.quality_reviewer.impl_live_verify",
        "regression_check": (
            "REGRESSION SWEEP: read `git diff` of the last live-fix round, then re-run on the "
            "deployed system every user flow those files serve (not only the failed check). "
            "None regressed."
        ),
    },
    "impl-docs": {
        "workflow": "executor",
        "work_step": 9,
        "review_step": 10,
        "verify_step": 11,
        "route_step": 12,
        "artifact": "plan.json",
        "review_script": "skills.planner.quality_reviewer.impl_docs_review",
        "verify_script": "skills.planner.quality_reviewer.impl_docs_qr_verify",
        "regression_check": (
            "REGRESSION SWEEP: the documentation edits of the last fix round are accurate "
            "against the code and did not drop previously correct content."
        ),
    },
}


def get_phase_config(phase: str) -> dict:
    """Single entry point for phase configuration.

    Understanding a phase's configuration requires reading only THIS file.
    Scripts import from here instead of hardcoding phase-specific values.

    Args:
        phase: Phase name (e.g., "plan-design", "impl-code")

    Returns:
        Phase configuration dict

    Raises:
        ValueError: If phase is unknown
    """
    if phase not in QR_PHASES:
        valid = ", ".join(sorted(QR_PHASES.keys()))
        raise ValueError(f"Unknown QR phase: {phase}. Valid phases: {valid}")
    return QR_PHASES[phase]


def get_all_phases() -> list[str]:
    """Return list of all phase names."""
    return list(QR_PHASES.keys())


def get_phases_for_workflow(workflow: str) -> list[str]:
    """Return phases belonging to a specific workflow.

    Args:
        workflow: "planner" or "executor"

    Returns:
        List of phase names for that workflow
    """
    return [
        phase for phase, config in QR_PHASES.items()
        if config["workflow"] == workflow
    ]


def get_orchestrator_module(phase: str) -> str:
    """Get orchestrator module path for a phase.

    Args:
        phase: Phase name

    Returns:
        Python module path for the orchestrator
    """
    config = get_phase_config(phase)
    workflow = config["workflow"]
    return f"skills.planner.orchestrator.{workflow}"


def get_route_step_info(phase: str) -> tuple[int, str, int]:
    """Get routing info for returning to orchestrator after QR.

    Replaces QR_ROUTING constant lookup with phase-based derivation.

    Args:
        phase: Phase name

    Returns:
        (route_step, module_path, total_steps)
    """
    config = get_phase_config(phase)
    workflow = config["workflow"]
    module_path = f"skills.planner.orchestrator.{workflow}"

    # Total steps depends on workflow
    if workflow == "planner":
        total_steps = 6
    else:  # executor
        total_steps = 13

    return (config["route_step"], module_path, total_steps)
