#!/usr/bin/env python3
"""Single deep review of one wave's implemented code (impl-code gate).

Scope: does the code of the milestones completed in this wave meet their
acceptance criteria without breaking anything around them?
The dispatch prompt names the wave's milestone IDs; review those, and
everything their changes touch one hop out.
NOT documentation (impl-docs gate) and NOT deployed behaviour (impl-live gate).
"""

from skills.planner.quality_reviewer.prompts.review import dispatch_review_step


PHASE = "impl-code"


STEP_1_ABSORB = """\
Read plan.json from STATE_DIR and select the milestones named in your
dispatch prompt:
  cat $STATE_DIR/plan.json | jq '.milestones[] | select(.id=="M-00X")'

Read the diff for this wave, not just the final files:
  git status --short && git diff        (uncommitted work)
  git log --oneline -5 && git show HEAD (if the wave was committed)

SCOPE: the wave's code changes, their acceptance criteria, and their
integration_tests (which must exist and exercise the real dependency)."""


STEP_2_CONCERNS = """\
Brainstorm concerns for THIS diff:
  - Acceptance criterion unmet or only met in the happy path
  - SQL naming a column/table/type that does not exist, a missing cast,
    an enum compared to text, NULL handling
  - Permission guard or tenant scope missing, weakened, or applied to the
    wrong identity; cross-boundary reads/writes running as the wrong party
  - API contract drift: schema vs handler vs generated client vs caller
  - UI lifecycle: hooks after early returns, inputs remounting on each
    keystroke, stale state after mutation, filters that reset partially
  - Error paths swallowed (catch -> empty state; 4xx rendered as nothing)
  - Tests that mock away the defect, were reshaped to pass, or are missing;
    integration_tests from the plan not written or not runnable
  - Changes outside the milestone's files; debug leftovers"""


STEP_3_ENUMERATION = """\
Enumerate:

MILESTONES in this wave: ID, acceptance criteria (each), integration_tests.
FILES changed: path, what changed (one line each), callers of changed
  functions/endpoints (grep them).
QUERIES added or changed: each, with the tables/columns/types it names.
GUARDS added or changed: route permission, row-level policy, tenant filter.
TESTS added or changed: unit vs integration; what each actually exercises."""


STEP_5_SEVERITY = """\
SEVERITY (impl-code):

  MUST (blocks every iteration):
    - Acceptance criterion not met
    - Runtime failure: nonexistent column, type/enum mismatch, crash path,
      hook-order violation, unhandled rejection
    - Access-control defect: missing/weakened guard, wrong identity,
      cross-tenant leak or silent denial
    - Contract drift between schema, handler, generated client, caller
    - Planned integration test missing, not hitting the real dependency,
      or failing; a test weakened to pass

  SHOULD (iterations 1-3):
    - Swallowed error path; misleading empty state on failure
    - Convention violation documented in the project; duplicated logic
    - Function >50 lines or nesting >3 introduced by this diff

  COULD (iterations 1-2):
    - Dead code, naming, formatter-fixable style"""


PHASE_PROMPTS = {
    1: STEP_1_ABSORB,
    2: STEP_2_CONCERNS,
    3: STEP_3_ENUMERATION,
    5: STEP_5_SEVERITY,
}


def get_step_guidance(step: int, module_path: str = None, **kwargs) -> dict:
    module_path = module_path or "skills.planner.quality_reviewer.impl_code_review"
    return dispatch_review_step(step, PHASE, module_path, PHASE_PROMPTS, kwargs.get("state_dir", ""))


if __name__ == "__main__":
    from skills.lib.workflow.cli import mode_main

    mode_main(
        __file__,
        get_step_guidance,
        "Impl-Code-Review: single deep review of one wave's implementation",
        extra_args=[
            (["--state-dir"], {"type": str, "required": True, "help": "State directory path"}),
        ],
    )
