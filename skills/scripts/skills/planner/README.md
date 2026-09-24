# planner/ (lean) -- module map

Flows, rationale and invariants live in `~/.claude/skills/planner/README.md`
and `INTENT.md`. This file maps steps to scripts.

## Planner (`orchestrator/planner.py`)

| Step | Handler | Dispatches |
| ---- | ------- | ---------- |
| 1 | `init_step` | - (creates STATE_DIR) |
| 2 | `verify_step` | - (orchestrator writes context.json) |
| 3 | `execute_dispatch_step` | architect -> `architect/plan_design.py` (router: execute or `plan_design_qr_fix`) |
| 4 | `shared/qr/loop.review_step` | quality-reviewer -> `quality_reviewer/plan_design_review.py` |
| 5 | `shared/qr/loop.reverify_step` | none, or quality-reviewer -> `plan_design_qr_verify.py` |
| 6 | `qr_route_step` -> `shared/gates.build_gate_output` | - |

## Executor (`orchestrator/executor.py`)

| Step | Handler | Dispatches |
| ---- | ------- | ---------- |
| 1 | `step_init` | optional reconcile -> `quality_reviewer/exec_reconcile.py` |
| 2 | `step_impl_code_work` | developers -> `developer/exec_implement.py` (router: execute or `exec_implement_qr_fix`) |
| 3 | `review_step` | quality-reviewer -> `quality_reviewer/impl_code_review.py` |
| 4 | `reverify_step` | none, or quality-reviewer -> `impl_code_qr_verify.py` |
| 5 | `step_impl_code_route` | - (advances waves) |
| 6 | `step_impl_live_verify` | orchestrator ships; quality-reviewer -> `impl_live_verify.py` |
| 7 | `step_impl_live_route` | - |
| 8 | `step_impl_live_fix` | developer -> `developer/exec_live_fix.py` |
| 9 | `step_impl_docs_work` | technical-writer -> `technical_writer/exec_docs.py` |
| 10 | `review_step` | quality-reviewer -> `impl_docs_review.py` |
| 11 | `reverify_step` | none, or quality-reviewer -> `impl_docs_qr_verify.py` |
| 12 | `step_impl_docs_route` | - |
| 13 | `step_retrospective` | - |

Phase registry (step numbers, scripts, regression-sweep text): `shared/qr/phases.py`.
Route targets for verify scripts' RESULT lines: `shared/qr/constants.QR_ROUTING`.
