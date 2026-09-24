#!/usr/bin/env python3
"""Single deep review of post-implementation documentation (impl-docs gate).

Scope: CLAUDE.md indexes, README.md invisible knowledge, WHY comments and
project docs the change made stale -- all checked against the finished code.
NOT code correctness (impl-code gate) and NOT deployed behaviour (impl-live).
"""

from skills.planner.quality_reviewer.prompts.review import dispatch_review_step


PHASE = "impl-docs"


STEP_1_ABSORB = """\
Read plan.json from STATE_DIR (invisible_knowledge, decisions, milestones):
  cat $STATE_DIR/plan.json | jq '{invisible_knowledge, planning_context, milestones: [.milestones[] | {id, name, files}]}'

Read the documentation diff:
  git diff -- '*.md'     (and CLAUDE.md / README.md in modified directories)

Read context.json reference_docs: project docs that describe the changed
behaviour (API contract, data model, permission tables, runbooks).

SCOPE: are the docs now TRUE about the code, and is the non-obvious
knowledge written down where the next reader will look?"""


STEP_2_CONCERNS = """\
Brainstorm concerns:
  - A project doc still describes the old behaviour (API, schema, roles,
    permissions, lifecycle states, runbook steps)
  - Invisible knowledge (decisions, invariants, tradeoffs) not captured
    next to the code it governs
  - CLAUDE.md index missing a new file, or describing a removed one
  - Comments that restate WHAT instead of WHY; change-relative wording
    ("now", "previously", "replaced") that rots
  - Docs edited inside generated files that regeneration will erase"""


STEP_3_ENUMERATION = """\
Enumerate:

DIRECTORIES with modified files: CLAUDE.md present/updated? README needed?
PROJECT DOCS naming the changed behaviour (grep for endpoint paths, table
  names, role/permission names, state names the plan touched).
INVISIBLE KNOWLEDGE items in plan.json: where each now lives (or nowhere).
NEW COMMENTS in the diff: file:line."""


STEP_5_SEVERITY = """\
SEVERITY (impl-docs):

  MUST (blocks every iteration):
    - STALE_DOC: a project doc now states something false about the code
    - IK_TRANSFER_FAILURE: a decision/invariant from the plan recorded nowhere
    - Docs written into generated files

  SHOULD (iterations 1-3):
    - CLAUDE.md index gaps or format violations
    - WHAT-not-WHY comments on non-obvious code

  COULD (iterations 1-2):
    - Change-relative wording, formatting inconsistencies"""


PHASE_PROMPTS = {
    1: STEP_1_ABSORB,
    2: STEP_2_CONCERNS,
    3: STEP_3_ENUMERATION,
    5: STEP_5_SEVERITY,
}


def get_step_guidance(step: int, module_path: str = None, **kwargs) -> dict:
    module_path = module_path or "skills.planner.quality_reviewer.impl_docs_review"
    return dispatch_review_step(step, PHASE, module_path, PHASE_PROMPTS, kwargs.get("state_dir", ""))


if __name__ == "__main__":
    from skills.lib.workflow.cli import mode_main

    mode_main(
        __file__,
        get_step_guidance,
        "Impl-Docs-Review: single deep review of post-implementation documentation",
        extra_args=[
            (["--state-dir"], {"type": str, "required": True, "help": "State directory path"}),
        ],
    )
