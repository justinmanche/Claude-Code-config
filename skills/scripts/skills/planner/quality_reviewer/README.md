# quality_reviewer/ -- review and re-verify contract

## Review (one agent per gate cycle)

`prompts/review.py` drives 7 steps: absorb, concerns, enumerate (phase
prompts), investigate, verdicts, challenge (shared), record. The reviewer
writes `qr-{phase}.json` itself with every item already judged:

```json
{"phase": "impl-code", "iteration": 1, "awaiting_reverify": false,
 "items": [{"id": "qa-001", "scope": "file:src/a.ts", "check": "...",
            "status": "FAIL", "version": 1, "severity": "MUST",
            "finding": "evidence (file:line) -> failure -> smallest fix"}]}
```

It records PASS items for high-risk checks too, so the file shows coverage,
and returns one word (FAIL if any item failed). Severity rules per phase are
in each `*_review.py` (MUST blocks always, SHOULD iterations 1-3, COULD 1-2).

## Re-verify (one agent, only after a fix)

Dispatched by `shared/qr/loop.reverify_step` with `--qr-item` for every
blocking TODO/FAIL item plus the `reg-NN` regression sweep. Each item shows
its `previous_finding`; PASS requires that finding to be resolved. Results go
through `cli/qr.py update-item` (file-locked; PASS is terminal).

## Why not decompose + parallel verify

The planner-old decomposer already found every defect; the parallel first
verify pass re-confirmed them at ~68% of total subagent tokens. See
`~/.claude/skills/planner/INTENT.md` (Evidence).
