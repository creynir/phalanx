"""Prompt injection of accumulated team context into agent prompts.

When spawning an agent for a skill step, the PromptInjector checks
for accumulated team context and appends a structured section to the
task prompt.
"""

from __future__ import annotations

import logging

from phalanx.learning.context_store import TeamContextStore

logger = logging.getLogger(__name__)

CONTEXT_SECTION_HEADER = "## Project Context (Learned)"


def inject_context(
    prompt: str,
    team_id: str,
    context_store: TeamContextStore,
    max_tokens: int = 2000,
) -> str:
    """Append accumulated team context to a prompt if available.

    Returns the prompt unchanged if no context exists.
    """
    context_text = context_store.get_context(team_id, max_tokens=max_tokens)
    if not context_text:
        return prompt

    section = (
        f"\n\n{CONTEXT_SECTION_HEADER}\n"
        "The following learnings were accumulated from previous steps "
        "in this skill run. Apply them to your work.\n\n"
        f"{context_text}\n"
    )

    return prompt + section
