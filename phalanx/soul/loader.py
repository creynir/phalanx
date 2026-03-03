"""Soul file loading and dynamic variable injection."""

from __future__ import annotations

import re
from pathlib import Path


def load_soul_file(
    path: Path,
    *,
    variables: dict[str, str] | None = None,
) -> str:
    """Load a soul template file and optionally substitute ``{{VAR}}`` placeholders.

    Returns empty string when *path* does not exist.
    Placeholders without a matching key in *variables* are left intact.
    """
    if not path.exists():
        return ""

    content = path.read_text()

    if variables:

        def _replace(m: re.Match[str]) -> str:
            key = m.group(1)
            return variables.get(key, m.group(0))

        content = re.sub(r"\{\{(\w+)\}\}", _replace, content)

    return content
