"""Soul file loading and dynamic variable injection."""

from __future__ import annotations

from pathlib import Path


def load_soul_file(
    path: Path,
    variables: dict[str, str] | None = None,
) -> str:
    """Load a soul file and substitute template variables.

    Variables like {{TEAM_ID}}, {{AGENT_ID}} are replaced.
    """
    if not path.exists():
        return ""

    content = path.read_text(encoding="utf-8")

    if variables:
        for key, value in variables.items():
            content = content.replace(f"{{{{{key}}}}}", value)

    return content
