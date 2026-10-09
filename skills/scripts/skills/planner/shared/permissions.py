"""Required-permissions and push-policy text for the executor and planner.

plan.json carries two owner-approved execution settings (see schema.Plan):
  required_permissions: [{rule, why}]  outside-system actions the run needs
  push_policy: after_each_wave | at_end | never

WHY: in auto mode, outside-system writes (closing a GitHub issue, a command
on a remote machine, a credential read) were blocked one at a time mid-run,
each costing a round trip to the owner. The owner approves the whole list once,
up front, through /permissions. The orchestrator never edits settings itself:
Claude must not grant itself permissions.
"""

from __future__ import annotations

PUSH_POLICIES = ("after_each_wave", "at_end", "never")
DEFAULT_PUSH_POLICY = "at_end"

NEVER_SELF_GRANT = (
    "Never edit settings files, never add these rules yourself, never retry a "
    "denied command another way. Only the owner grants permissions."
)


def permissions_of(plan: dict) -> list[dict]:
    return [p for p in (plan.get("required_permissions") or []) if isinstance(p, dict)]


def push_policy_of(plan: dict) -> str:
    return plan.get("push_policy") or DEFAULT_PUSH_POLICY


def permissions_block(plan: dict, heading: str = "REQUIRED PERMISSIONS") -> list[str]:
    """Ready-to-paste /permissions list, one allow rule per line with its reason."""
    perms = permissions_of(plan)
    if not perms:
        return [
            f"{heading}: none declared in plan.json.",
            "  If any command is denied during the run, stop and report exactly which",
            "  command; do not work around it. " + NEVER_SELF_GRANT,
        ]
    width = max(len(p.get("rule", "")) for p in perms)
    lines = [
        f"{heading} ({len(perms)}) -- ready to paste into /permissions (Allow rules):",
        "",
    ]
    for p in perms:
        lines.append(f"  {p.get('rule', ''):<{width}}   # {p.get('why', '')}")
    lines.extend([
        "",
        "  " + NEVER_SELF_GRANT,
        "  A command denied later: stop and report exactly which one.",
    ])
    return lines


def permissions_gate_actions(plan: dict) -> list[str]:
    """Executor step 1: ask the owner for the list BEFORE any agent is dispatched."""
    perms = permissions_of(plan)
    lines = [*permissions_block(plan), ""]
    if perms:
        lines.extend([
            "BEFORE DISPATCHING WAVE 1: ask the owner (AskUserQuestion) to add the rules",
            "above through /permissions, and wait for their confirmation. Do not edit",
            "settings.json / settings.local.json yourself and do not proceed without it.",
            "If the owner declines a rule, ask which milestone or check to drop or",
            "change; do not continue with a gap you know about.",
        ])
    return lines


def push_policy_line(plan: dict) -> str:
    return f"PUSH POLICY: {push_policy_of(plan)}"


def wave_push_actions(plan: dict, more_waves: bool) -> list[str]:
    """After a wave's gate passed and was merged: push main, or say why not."""
    policy = push_policy_of(plan)
    if policy == "after_each_wave":
        return [
            "PUSH (policy after_each_wave): push main to origin now, so the next wave's",
            "isolated worktrees start from current code. If the push is denied, stop and",
            "report the exact command (the plan's required_permissions should cover it).",
        ]
    reason = "never" if policy == "never" else "at_end"
    tail = ("Later worktrees will start from a stale origin/main; the BASE COMMIT "
            "preamble in each dispatch brings them up to date, so this is safe.")
    return [
        f"PUSH: policy is {reason} -- do not push now. " + (tail if more_waves else
            "No later waves remain."),
    ]


def final_push_actions(plan: dict) -> list[str]:
    """Run end (retrospective): the push the policy allows, or the reminder."""
    policy = push_policy_of(plan)
    if policy == "never":
        return ["PUSH (policy never): do not push. Tell the owner main exists only locally."]
    return [
        f"PUSH (policy {policy}): push main to origin now so docs and live fixes land",
        "with the waves. If the push is denied, stop and report the exact command.",
    ]
