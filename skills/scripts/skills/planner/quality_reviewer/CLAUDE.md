# quality_reviewer/

Single-reviewer and re-verify scripts for every gate.

## Files

| File                     | What                                                      | When to read                        |
| ------------------------ | --------------------------------------------------------- | ----------------------------------- |
| `README.md`              | Review vs re-verify contract, item format                 | Changing how gates judge            |
| `prompts/review.py`      | Shared 7-step reviewer engine (investigate, verdicts, challenge, record) | Changing reviewer behaviour |
| `plan_design_review.py`  | Plan reviewed against the real code + verification coverage | Changing plan gate checks        |
| `impl_code_review.py`    | One wave's diff: SQL, access control, contracts, lifecycle, tests | Changing code gate checks   |
| `impl_docs_review.py`    | Docs true against code; invisible knowledge captured      | Changing docs gate checks           |
| `qr_verify_base.py`      | Re-verify step engine (per item analyze/confirm, one-word summary) | Changing re-check mechanics |
| `plan_design_qr_verify.py`, `impl_code_qr_verify.py`, `impl_docs_qr_verify.py` | Re-check failed items + regression sweep | Changing re-check guidance |
| `impl_live_verify.py`    | Live checks on the deployed system at the user's layer   | Changing live verification          |
| `exec_reconcile.py`      | Resume: is a pending milestone already satisfied?         | Changing reconciliation             |
