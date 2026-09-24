#!/usr/bin/env python3
"""Live verification of the deployed system (impl-live gate).

Items come from plan.json milestones[].live_checks (written mechanically to
qr-impl-live.json by the executor) plus a regression-sweep item after every
live-fix round. ONE agent verifies all pending items per round.

WHY this gate exists: on the 2026-09 Risky run, live checks were ~1% of
subagent tokens and found 7 real defects every earlier gate missed -- all at
the server/database or cross-tenant layer (an enum compared to text, RLS
silently dropping cross-tenant notifications, a vendor 404 from an inner join
the vendor could not see). Mocked unit tests and code review cannot observe
those; the running system can.
"""

from .qr_verify_base import VerifyBase


PHASE = "impl-live"
WORKFLOW = "executor"


class ImplLiveVerify(VerifyBase):
    """Verify one live check against the deployed system at the user's layer."""

    PHASE = "impl-live"

    def get_verification_guidance(self, item: dict, state_dir: str) -> list[str]:
        guidance = [
            "LIVE CHECK -- observe the DEPLOYED system as a real user would.",
            "",
            "HOW (from context.json verification_env; read it now):",
            f"  cat {state_dir}/context.json | jq '.verification_env'",
            "  Use the project's documented live-verification method (browser",
            "  driver, real logins for each role, API calls with real tokens).",
            "  Clear any cached client bundle first so you test the NEW build.",
            "",
            "RULES:",
            "  - Drive the full request chain the user drives. A passing unit",
            "    test or a direct DB query is NOT a live observation.",
            "  - For cross-party behaviour (tenant A acts, tenant B sees it),",
            "    sign in as BOTH parties and observe both sides.",
            "  - Record what you observed: URL, role, the exact text/status seen.",
            "  - PASS only on direct observation of the expected behaviour.",
            "  - FAIL finding: role, steps, expected vs observed, and any server",
            "    status/log line you saw. A fixer will reproduce from it.",
            "  - If the environment itself blocks the check (deploy down, login",
            "    impossible), FAIL with finding 'ENVIRONMENT: <what blocked>'.",
            "  - Leave no test data behind that would confuse a real user; reuse",
            "    the project's QA accounts and fixtures.",
        ]
        if item.get("id", "").startswith("reg-"):
            guidance.extend([
                "",
                "REGRESSION SWEEP: `git diff` the last live-fix round, list the user",
                "flows those files serve, and re-run each flow end to end.",
            ])
        return guidance


def get_step_guidance(step: int, module_path: str = None, **kwargs) -> dict:
    module_path = module_path or "skills.planner.quality_reviewer.impl_live_verify"
    qr_item = kwargs.get("qr_item")
    if qr_item:
        kwargs["qr_item"] = qr_item if isinstance(qr_item, list) else [qr_item]
        return ImplLiveVerify().get_step_guidance(step, module_path, **kwargs)
    return {
        "title": "Error: No Items",
        "actions": ["--qr-item required. Use: --qr-item a --qr-item b"],
        "next": "",
    }


if __name__ == "__main__":
    from skills.lib.workflow.cli import mode_main
    mode_main(
        __file__,
        get_step_guidance,
        "QR-Impl-Live: verify live checks against the deployed system",
        extra_args=[
            (["--state-dir"], {"type": str, "help": "State directory path"}),
            (["--qr-item"], {"action": "append", "help": "Item ID (repeatable)"}),
        ],
    )
