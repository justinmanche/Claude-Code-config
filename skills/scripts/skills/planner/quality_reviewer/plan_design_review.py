#!/usr/bin/env python3
"""Single deep review of plan.json (plan-design gate).

Scope: is this plan correct against the real codebase, and does it say how
each milestone will be proven to work?
  - Decisions and constraints (logged, reasoned, user-backed policy)
  - Code intents checked against the code they name (the substantive
    catches of the retired plan-code phase: missing enum values, queries
    that RLS would silently empty, unregistered audit actions, contracts
    the change contradicts)
  - Verification coverage (integration_tests on every data/access-control
    change; live_checks on every user-visible change)
NOT code style (there is no code yet) and NOT documentation wording.
"""

from skills.planner.quality_reviewer.prompts.review import dispatch_review_step


PHASE = "plan-design"


STEP_1_ABSORB = """\
Read plan.json and context.json from STATE_DIR:
  cat $STATE_DIR/plan.json | jq '.'
  cat $STATE_DIR/context.json | jq '.'

Read every file listed in context.json reference_docs and the project
CLAUDE.md. Then read the CODE each milestone names (milestones[].files and
code_intents[].file) -- this plan is reviewed against reality, not in the
abstract. There is no later phase that reviews proposed code: developers
implement straight from code_intents, so an intent that is wrong against
the codebase is caught here or ships.

SCOPE: plan correctness against the codebase + verification coverage."""


STEP_2_CONCERNS = """\
Brainstorm concerns for THIS plan:
  - An intent assumes something the code contradicts (a column, an enum
    value, a permission, a function signature, an existing behaviour)
  - A query/write that crosses a tenant or ownership boundary but would run
    under an identity the access rules deny (silently empty, not an error)
  - A new state, action or event type not registered where the codebase
    requires registration (enums, audit registries, API schema, generated
    clients)
  - Two milestones in the same wave touching the same file or contract
  - Non-obvious choices with no decision logged; policy defaults the user
    never confirmed
  - Acceptance criteria that cannot be checked pass/fail
  - Missing verification: a data-layer or access-control change with no
    integration_tests; a user-visible change with no live_checks; tests
    described only as mocked unit tests where mocks would hide the defect"""


STEP_3_ENUMERATION = """\
Enumerate:

MILESTONES: each (ID, name, wave), with
  - code_intents (ID, file, behaviour)
  - acceptance_criteria count
  - tests / integration_tests / live_checks counts

DECISIONS / CONSTRAINTS / RISKS: IDs and whether each has reasoning,
backing, mitigation.

BOUNDARIES touched: each DB table/column, permission, tenant scope, API
contract, generated artefact, migration named by any intent.

WAVES: which milestones run in parallel; any shared files between them."""


STEP_5_SEVERITY = """\
SEVERITY (plan-design):

  MUST (blocks every iteration):
    - INTENT_CONTRADICTS_CODE: an intent relies on something the code
      does not have or does differently (cite file:line)
    - BOUNDARY_UNSAFE: a cross-tenant/ownership read or write that the
      access rules would deny or leak
    - VERIFICATION_GAP: data-layer/access-control change without an
      integration test against the real dependency; user-visible change
      without a live check
    - DECISION_LOG_MISSING / POLICY_UNJUSTIFIED: non-trivial choice or
      policy default without logged, user-backed rationale
    - WAVE_CONFLICT: parallel milestones touch the same file/contract

  SHOULD (iterations 1-3):
    - Acceptance criterion not objectively checkable
    - Risk without mitigation; shallow reasoning chain

  COULD (iterations 1-2):
    - Naming, ordering, cosmetic plan issues"""


PHASE_PROMPTS = {
    1: STEP_1_ABSORB,
    2: STEP_2_CONCERNS,
    3: STEP_3_ENUMERATION,
    5: STEP_5_SEVERITY,
}


def get_step_guidance(step: int, module_path: str = None, **kwargs) -> dict:
    module_path = module_path or "skills.planner.quality_reviewer.plan_design_review"
    return dispatch_review_step(step, PHASE, module_path, PHASE_PROMPTS, kwargs.get("state_dir", ""))


if __name__ == "__main__":
    from skills.lib.workflow.cli import mode_main

    mode_main(
        __file__,
        get_step_guidance,
        "Plan-Design-Review: single deep review of plan.json against the codebase",
        extra_args=[
            (["--state-dir"], {"type": str, "required": True, "help": "State directory path"}),
        ],
    )
