#!/usr/bin/env python3
"""
Lean Sequential Planner - context, design, one deep review gate.

6-step planning workflow:

Flow:
  1. plan-init            orchestrator captures context categories
  2. context-verify       orchestrator writes context.json (incl. verification_env)
  3. plan-design-work     architect sub-agent (fix mode on QR FAIL)
  4. plan-design-review   ONE quality-reviewer (opus) -> verdicts in qr-plan-design.json
  5. plan-design-reverify no agent on first pass; ONE re-check agent after a fix
  6. plan-design-route    FAIL -> 3 | PASS -> PLAN APPROVED

Differences from planner-old (see ~/.claude/skills/planner/README.md):
  - No plan-code phase: developers implement from code_intents directly;
    the plan-design reviewer checks each intent against the real code.
  - No plan-docs phase: documentation is written once, after implementation.
  - One reviewer records verdicts; re-verification only after a fix.
  - Milestones carry integration_tests and live_checks, consumed by the
    executor's real-dependency test step and live-verification gate.
"""

import argparse
import sys
import tempfile
from datetime import datetime

from skills.lib.workflow.types import AgentRole, Dispatch
from skills.lib.workflow.constants import (
    SUB_AGENT_QUESTION_FORMAT,
    QUESTION_RELAY_HANDLER,
)
from skills.lib.workflow.prompts import subagent_dispatch, template_dispatch
from skills.lib.workflow.prompts.step import format_step
from skills.planner.shared.qr.types import QRState, QRStatus, LoopState
from skills.planner.shared.gates import build_gate_output, GateResult
from skills.planner.shared.qr.cli import add_qr_args
from skills.planner.shared.resources import get_mode_script_path, PlannerResourceProvider
from skills.planner.shared.builders import THINKING_EFFICIENCY, format_forbidden
from skills.planner.shared.constraints import (
    ORCHESTRATOR_CONSTRAINT_EXTENDED,
    format_state_banner,
)
from skills.planner.shared.qr.loop import mark_fix_dispatched, review_step, reverify_step
from skills.planner.shared.constants import PLANNER_TOTAL_STEPS, validate_step_count


MODULE_PATH = "skills.planner.orchestrator.planner"


def _translate_plan(state_dir: str) -> str | None:
    """Mechanical translation: plan.json -> plan.md.

    Returns path to plan.md on success, None on failure.

    Why non-fatal: plan.json is the source of truth (the IR).
    plan.md is a convenience rendering. If translation fails,
    the workflow should still complete -- QR already approved
    the plan.json content.
    """
    from pathlib import Path
    from skills.planner.cli.plan_commands import PlanContext, _translate

    try:
        plan_md = str(Path(state_dir) / "plan.md")
        ctx = PlanContext(state_dir=Path(state_dir))
        _translate(ctx, plan_md)
        return plan_md
    except Exception as e:
        import sys
        print(f"Warning: plan.md translation failed: {e}", file=sys.stderr)
        return None

_provider = PlannerResourceProvider()

QUESTION_RELAY_INSTRUCTION = SUB_AGENT_QUESTION_FORMAT

def get_plan_format() -> str:
    """Read the plan format template from resources."""
    return _provider.get_resource("plan-format.md")


def _build_fix_mode_output(title, agent, agent_role, script, mode_total_steps, qr, ctx):
    """Build output for execute step in fix mode."""
    state_dir = ctx["state_dir"]

    action_children = []

    # The re-verify step re-checks only after it sees this flag.
    mark_fix_dispatched(state_dir, ctx["phase"])

    action_children.append(format_state_banner("PLAN-FIX", qr.iteration, "fix"))
    action_children.append("")
    action_children.append("FIX MODE: QR found issues.")
    action_children.append("")

    action_children.append(ORCHESTRATOR_CONSTRAINT_EXTENDED)
    action_children.append("")

    mode_script = get_mode_script_path(script)
    invoke_cmd = f"python3 -m {mode_script} --step 1 --state-dir {state_dir}"

    dispatch_prompt = subagent_dispatch(
        agent_type=agent,
        command=invoke_cmd,
    )
    action_children.append(dispatch_prompt)
    action_children.append("")
    action_children.append(f"{agent.title()} reads QR report and fixes issues.")
    action_children.append("After fixes complete, re-run QR for fresh verification.")

    next_step = ctx["step"] + 1
    next_cmd = f"python3 -m {MODULE_PATH} --step {next_step} --state-dir {state_dir}"

    return {
        "title": f"{title} - Fix Mode",
        "actions": action_children,
        "next": next_cmd,
    }


# =============================================================================
# Step Pattern Functions
# =============================================================================

def init_step(title, actions):
    """Step 1: creates state_dir, writes plan.json skeleton."""
    def handler(ctx):
        import json
        from pathlib import Path

        state_dir = tempfile.mkdtemp(prefix="planner-")

        plan_skeleton = {
            "schema_version": 2,
            "overview": {"problem": "", "approach": ""},
            "planning_context": {
                "decisions": [],
                "rejected_alternatives": [],
                "constraints": [],
                "risks": [],
            },
            "invisible_knowledge": {
                "system": "",
                "invariants": [],
                "tradeoffs": [],
            },
            "milestones": [],
            "waves": [],
        }
        plan_path = Path(state_dir) / "plan.json"
        plan_path.write_text(json.dumps(plan_skeleton, indent=2))

        print(f"STATE_DIR={state_dir}")

        return {
            "title": title,
            "actions": actions,
            "next": f"python3 -m {MODULE_PATH} --step 2 --state-dir {state_dir}",
        }

    return handler


def verify_step(title, actions):
    """Step 2: context verification."""
    def handler(ctx):
        from skills.planner.shared.resources import validate_state_dir_requirement

        state_dir = ctx["state_dir"]

        validate_state_dir_requirement(2, state_dir)

        return {
            "title": title,
            "actions": actions,
            "next": f"python3 -m {MODULE_PATH} --step 3 --state-dir {state_dir}",
        }

    return handler


def execute_dispatch_step(title, agent, agent_role, script, mode_total_steps, post_dispatch=None, phase=None):
    """Steps 3, 7, 11: work execution dispatch."""
    def handler(ctx):
        from skills.planner.shared.resources import validate_state_dir_requirement

        state_dir = ctx["state_dir"]
        qr = ctx["qr"]
        step = ctx["step"]

        validate_state_dir_requirement(step, state_dir)

        if qr.state == LoopState.RETRY:
            return _build_fix_mode_output(title, agent, agent_role, script, mode_total_steps, qr, ctx)

        action_children = []

        action_children.append(ORCHESTRATOR_CONSTRAINT_EXTENDED)
        action_children.append("")

        mode_script = get_mode_script_path(script)
        invoke_cmd = f"python3 -m {mode_script} --step 1 --state-dir {state_dir}"

        dispatch_prompt = subagent_dispatch(
            agent_type=agent,
            command=invoke_cmd,
        )
        action_children.append(dispatch_prompt)
        action_children.append("")

        if post_dispatch:
            action_children.extend(post_dispatch)

        next_step = step + 1
        next_cmd = f"python3 -m {MODULE_PATH} --step {next_step} --state-dir {state_dir}"

        return {
            "title": title,
            "actions": action_children,
            "next": next_cmd,
        }

    handler.phase = phase
    return handler


def qr_route_step(title, phase, work_step, pass_step, pass_message, fix_target=None):
    """Steps 6, 10, 14: Route based on aggregated QR results.

    PASS: delete qr file, proceed to pass_step
    FAIL: loop to work_step (fix mode detected via qr-{phase}.json inspection)
    """
    def handler(ctx):
        from skills.planner.shared.qr.utils import unresolved_items

        qr = ctx["qr"]
        state_dir = ctx.get("state_dir", "")
        step = ctx["step"]

        message = pass_message
        leftover = unresolved_items(state_dir, phase) if (qr.passed and state_dir) else []
        if leftover:
            # Passed with below-threshold or user-accepted FAIL items: the
            # user approves the plan knowing about them.
            message += "\n\nACCEPTED KNOWN ISSUES (still FAIL; tell the user each one):\n" + \
                "\n".join(f"  [{i.get('id')} {i.get('severity', 'SHOULD')}] {i.get('check', '')}"
                          f"\n      {i.get('finding', '')}" for i in leftover)

        return build_gate_output(
            module_path=MODULE_PATH,
            script_name="planner",
            qr_name=title,
            qr=qr,
            step=step,
            work_step=work_step,
            pass_step=pass_step,
            pass_message=message,
            fix_target=fix_target,
            state_dir=state_dir,
        )

    handler.phase = phase
    return handler


# =============================================================================
# Step Definitions (1-6)
# =============================================================================

STEPS = {
    1: init_step(
        title="plan-init",
        actions=[
            "CONTEXT CAPTURE: Structure these categories from conversation:",
            "",
            "1. TASK_SPEC: what the plan is ABOUT, not how to write the plan (orchestration)",
            "   - SUBJECT: the user's underlying goal (what they want to accomplish)",
            "   - EXCLUDE: output instructions ('write to file X', 'create a plan for')",
            "   - CORRECT: 'OAuth-based authorization for the REST API'",
            "   - WRONG: 'Write plan to plans/foo-plan.md'",
            "   - Then: scope (directories/modules), out-of-scope",
            "2. CONSTRAINTS: MUST/SHOULD/MUST-NOT with sources -- or 'none confirmed'",
            "3. ENTRY_POINTS: file:function + why relevant -- or 'greenfield'",
            "4. REJECTED_ALTERNATIVES: what dismissed + why -- or 'none discussed'",
            "5. CURRENT_UNDERSTANDING: how system works; for bugs: symptom + reproduction",
            "6. ASSUMPTIONS: unverified inferences with confidence H/M/L -- or 'none'",
            "7. INVISIBLE_KNOWLEDGE: design rationale, invariants, accepted tradeoffs",
            "8. REFERENCE_DOCS: paths to project docs sub-agents should read (doc/*.md, specs/*) -- or 'none'",
            "9. VERIFICATION_ENV: how this project proves a change works, per layer:",
            "   - unit + typecheck commands",
            "   - real-dependency integration command (e.g. tests against a real DB",
            "     with its access policies) and how to start that dependency",
            "   - ship/deploy command and any env it needs",
            "   - live check method: how to observe the deployed system as each role",
            "     (driver, accounts, cache clearing) -- or 'none: <reason>'",
            "",
            "FORMAT: High signal-to-noise. File refs over content. No ASCII diagrams.",
            "",
            "Mentally organize this context; you will write it to context.json in step 2.",
        ],
    ),
    2: verify_step(
        title="context-verify",
        actions=[
            "CONTEXT PERSISTENCE: Write context to STATE_DIR/context.json",
            "",
            "JSON SCHEMA:",
            "{",
            '  "task_spec": ["subject (not orchestration)", "scope: dir/module", "out-of-scope: X"],',
            '  "constraints": ["MUST: X", "SHOULD: Y"] or ["none confirmed"],',
            '  "entry_points": ["file:function - why relevant"] or ["greenfield"],',
            '  "rejected_alternatives": ["alternative - why dismissed"] or ["none discussed"],',
            '  "current_understanding": ["how system works", "bug: symptom + repro"],',
            '  "assumptions": ["inference (H/M/L confidence)"] or ["none"],',
            '  "invisible_knowledge": ["design rationale", "invariants", "tradeoffs"],',
            '  "reference_docs": ["doc/spec.md - what it specifies"] or ["none"],',
            '  "verification_env": ["unit: <cmd>", "integration: <cmd + dependency>", "ship: <cmd>", "live: <method>"]',
            "}",
            "",
            "ACTION: Use Write tool to create STATE_DIR/context.json with populated values.",
            "",
            "SELF-VERIFICATION (all must pass before proceeding to step 3):",
            "[ ] 1. Subject (what plan is ABOUT) statable in one sentence",
            "[ ] 2. At least one out-of-scope item explicit",
            "[ ] 3. At least one constraint OR explicit 'none confirmed'",
            "[ ] 4. Entry points identified OR 'greenfield'",
            "[ ] 5. Someone unfamiliar would understand why we're building this",
            "[ ] 6. Reference documentation paths captured or explicit 'none'",
            "[ ] 7. verification_env names unit, integration, ship and live methods",
            "       (or 'none: <reason>' per layer) -- the executor's gates run these",
            "",
            "IF ANY CHECK FAILS: gather missing context via AskUserQuestion or exploration.",
        ],
    ),
    # Plan-design phase (steps 3-6)
    3: execute_dispatch_step(
        title="plan-design-work",
        agent="architect",
        agent_role="architect",
        script="architect/plan_design.py",
        mode_total_steps=6,
        phase="plan-design",
        post_dispatch=[
            QUESTION_RELAY_HANDLER,
        ],
    ),
    4: review_step(
        module_path=MODULE_PATH,
        title="plan-design-review",
        phase="plan-design",
        model="opus",
    ),
    5: reverify_step(
        module_path=MODULE_PATH,
        title="plan-design-reverify",
        phase="plan-design",
    ),
    6: qr_route_step(
        title="plan-design-qr-route",
        phase="plan-design",
        work_step=3,
        pass_step=None,
        pass_message="PLAN APPROVED. Ready for execution.",
        fix_target=AgentRole.ARCHITECT,
    ),
}
validate_step_count(STEPS, PLANNER_TOTAL_STEPS, "planner")


def get_step_guidance(step: int, qr_status, state_dir) -> dict | str:
    """Returns guidance for a step.

    Iteration and fix mode derived from qr-{phase}.json file state.
    Phase derived from handler attribute set by step factory.
    """
    from skills.planner.shared.qr.utils import get_qr_iteration, has_qr_failures

    handler = STEPS.get(step)
    if not handler:
        return {"error": f"Invalid step {step}"}

    # Phase stored as handler attribute by step factory.
    # None for non-QR steps (1, 2).
    phase = getattr(handler, 'phase', None)
    iteration = get_qr_iteration(state_dir, phase) if state_dir and phase else 1

    status = QRStatus(qr_status) if qr_status else None
    is_fix_mode = state_dir and phase and has_qr_failures(state_dir, phase)
    state = LoopState.RETRY if is_fix_mode else LoopState.INITIAL
    qr = QRState(iteration=iteration, state=state, status=status)

    ctx = {
        "step": step,
        "qr": qr,
        "state_dir": state_dir,
        "phase": phase,
    }

    return handler(ctx)


def format_output(step: int, qr_status, state_dir) -> str | GateResult:
    """Format output for display."""
    guidance = get_step_guidance(step, qr_status, state_dir=state_dir)

    if isinstance(guidance, GateResult):
        return guidance
    if isinstance(guidance, str):
        return guidance
    if "error" in guidance:
        return f"Error: {guidance['error']}"

    body_parts = []
    if step == 1:
        body_parts.append(THINKING_EFFICIENCY)
        body_parts.append("")

    for action in guidance["actions"]:
        body_parts.append(str(action))

    body = "\n".join(body_parts)
    title = guidance["title"]

    if_pass = guidance.get("if_pass")
    if_fail = guidance.get("if_fail")
    next_cmd = guidance.get("next", "")

    if if_pass and if_fail:
        return format_step(body, title=title, if_pass=if_pass, if_fail=if_fail)
    return format_step(body, next_cmd, title=title)


HANDOFF_TEMPLATE = """
PLAN APPROVED -- HANDOFF FOR A FRESH SESSION
============================================
Rendered: {plan_md}

The usual flow is: plan here, clear the session, execute in a new one. The
STATE_DIR is a temp directory, so first make the plan durable:

1. SAVE the three plan files together (use the user's requested path if they
   gave one; otherwise docs/plans/<short-kebab-name> in the project repo):
     cp {plan_md}      <DEST>.md
     cp {plan_json}    <DEST>.json
     cp {context_json} <DEST>.context.json
   (<DEST>.context.json carries verification_env: the unit, integration,
   ship and live-check commands the executor's gates run.)
   Commit them if the project keeps plans in git.

2. PRESENT to the user, as the LAST thing in your reply, this prompt in a
   fenced code block, with <DEST> replaced by the absolute path you used:

```
Use the planner skill to execute the approved plan at <DEST>.md
(plan JSON: <DEST>.json, context: <DEST>.context.json).

Start execution with:
  python3 -m skills.planner.orchestrator.executor --step 1 --plan <DEST>.json
(working directory ~/.claude/skills/scripts), then follow each step's
printed next command exactly. If some milestones were already implemented
in an earlier session, add --reconcile to step 1.
```

   Add below the block, in one or two sentences, anything the fresh session
   cannot learn from the plan files (e.g. credentials the user must export,
   services that must be running). Say nothing else about the plan's content.
"""


def format_handoff(state_dir: str, plan_md: str) -> str:
    """Terminal-pass instructions: persist the plan and print the execute prompt.

    WHY: planning and execution normally run in separate sessions (the user
    clears context between them). Everything execution needs must survive in
    files, and the user needs a paste-ready prompt that starts the executor.
    """
    from pathlib import Path
    sd = Path(state_dir)
    return HANDOFF_TEMPLATE.format(
        plan_md=plan_md,
        plan_json=sd / "plan.json",
        context_json=sd / "context.json",
    )


def main():
    """CLI entry point for planner orchestration."""
    parser = argparse.ArgumentParser(
        description="Lean Sequential Planner (6-step orchestration workflow)",
        epilog="Step 1: init | 2: context-verify | 3: design | 4: review | 5: reverify | 6: route",
    )

    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--state-dir", type=str, default=None, help="State directory path (for retry mode)")
    add_qr_args(parser)

    args = parser.parse_args()

    from skills.planner.shared.constants import PLANNER_GATE_STEPS, PLANNER_TOTAL_STEPS

    if args.step < 1:
        sys.exit("Error: step must be >= 1")

    # Validate state before running step (skip for step 1 which creates state)
    if args.step > 1 and args.state_dir:
        from skills.planner.shared.schema import validate_state, SchemaValidationError
        try:
            validate_state(args.state_dir)
        except SchemaValidationError as e:
            sys.exit(f"Schema validation failed: {e}")

    # Route steps require --qr-status; provide helpful output if missing
    if args.step in PLANNER_GATE_STEPS and not args.qr_status:
        gate_names = {6: "plan-design-qr-route"}
        print(f"PLANNER - Step {args.step}/{PLANNER_TOTAL_STEPS}: {gate_names[args.step]}")
        print()
        print("This is a route step. Re-invoke with --qr-status pass or --qr-status fail")
        print("based on the aggregated QR output from the previous step.")
        sys.exit(0)

    result = format_output(args.step, args.qr_status, state_dir=args.state_dir)

    if isinstance(result, GateResult):
        # Why translate on terminal_pass: plan.json is the IR (modified by
        # QR fix cycles). plan.md is a rendered view. Terminal gate approval
        # signals plan.json is stable -- safe to regenerate the markdown.
        print(result.output)
        if result.terminal_pass and args.state_dir:
            plan_path = _translate_plan(args.state_dir)
            if plan_path:
                print(format_handoff(args.state_dir, plan_path))
    else:
        print(result)


if __name__ == "__main__":
    main()
