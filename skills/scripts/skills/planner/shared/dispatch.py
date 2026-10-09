"""Planner dispatch wrappers: every sub-agent prompt carries the same guard rails.

Wraps skills.lib.workflow.prompts.subagent_dispatch / template_dispatch (shared
with other skills, so they stay untouched) and adds, to EVERY planner agent:

  - DENIED_COMMAND_RULE: a denied command is reported, never worked around.
    Claude must not grant itself permissions, and an agent that routes around
    a denial (a different tool, a copied script) hides the missing permission
    from the owner until it fails somewhere worse.

and, for agents that write code or docs (pass base_preamble):

  - the base-commit preamble from shared/git_base.py, so an agent in an
    isolated worktree built from a stale origin/main catches up first.
"""

from __future__ import annotations

from skills.lib.workflow.prompts import subagent_dispatch, template_dispatch


DENIED_COMMAND_RULE = (
    "If a command is denied, stop and report exactly which command — "
    "do not work around it."
)


def _escape(text: str) -> str:
    """Make text safe inside a string.Template (template_dispatch substitutes $vars)."""
    return text.replace("$", "$$")


def with_guards(prompt: str, base_preamble: str = "", template: bool = False) -> str:
    """Compose preamble + task prompt + the denied-command rule.

    template=True escapes the injected text for template_dispatch; the caller's
    own prompt keeps its $var placeholders.
    """
    fix = _escape if template else (lambda s: s)
    parts = []
    if base_preamble:
        parts.append(fix(base_preamble))
    if prompt:
        parts.append(prompt)
    parts.append(fix(DENIED_COMMAND_RULE))
    return "\n\n".join(parts)


def agent_dispatch(agent_type: str, command: str, prompt: str = "",
                   model: str | None = None, base_preamble: str = "") -> str:
    """subagent_dispatch with the planner guard rails."""
    return subagent_dispatch(
        agent_type=agent_type,
        command=command,
        prompt=with_guards(prompt, base_preamble),
        model=model,
    )


def agents_dispatch(agent_type: str, template: str, targets: list[dict[str, str]],
                    command: str, model: str | None = None,
                    instruction: str | None = None, base_preamble: str = "") -> str:
    """template_dispatch with the planner guard rails."""
    return template_dispatch(
        agent_type=agent_type,
        template=with_guards(template, base_preamble, template=True),
        targets=targets,
        command=command,
        model=model,
        instruction=instruction,
    )
