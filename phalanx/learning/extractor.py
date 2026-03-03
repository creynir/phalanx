"""Learning extraction from completed step artifacts.

Analyzes artifact output and extracts reusable context entries
(conventions, patterns, constraints, discoveries) for injection
into subsequent steps.

In v1.0.0, extraction uses simple heuristic parsing. A future version
may use lightweight LLM calls for richer extraction.
"""

from __future__ import annotations

import logging
import re

from phalanx.learning.context_store import ContextEntry

logger = logging.getLogger(__name__)

EXTRACTABLE_TYPES = ("convention", "pattern", "constraint", "discovery")

_KEYWORD_MAP = {
    "convention": [
        "naming convention",
        "style guide",
        "always use",
        "must use",
        "standard",
        "prefer",
        "convention",
    ],
    "pattern": [
        "pattern",
        "approach",
        "technique",
        "method",
        "strategy",
        "workaround",
        "solution",
    ],
    "constraint": [
        "constraint",
        "limitation",
        "cannot",
        "must not",
        "do not",
        "avoid",
        "never",
        "breaks",
        "crashes",
        "incompatible",
    ],
    "discovery": [
        "discovered",
        "found that",
        "turns out",
        "note:",
        "important:",
        "learned",
        "observation",
        "finding",
    ],
}


def extract(
    artifact_output: str | dict,
    step_name: str | None = None,
    source_agent_id: str | None = None,
    skill_run_id: str | None = None,
    context_types: list[str] | None = None,
) -> list[ContextEntry]:
    """Extract learning entries from a completed step artifact.

    Uses keyword-based heuristics to identify context types.
    """
    types_to_extract = context_types or list(EXTRACTABLE_TYPES)

    if isinstance(artifact_output, dict):
        text = _flatten_dict(artifact_output)
    else:
        text = str(artifact_output)

    if not text or len(text) < 20:
        return []

    entries = []
    sentences = _split_sentences(text)

    for sentence in sentences:
        lower = sentence.lower()
        for ctx_type in types_to_extract:
            keywords = _KEYWORD_MAP.get(ctx_type, [])
            if any(kw in lower for kw in keywords):
                entry = ContextEntry(
                    context_type=ctx_type,
                    content=sentence.strip()[:500],
                    step_name=step_name,
                    source_agent_id=source_agent_id,
                    skill_run_id=skill_run_id,
                )
                entries.append(entry)
                break

    return entries


def extract_from_failure(
    failure_output: str,
    step_name: str | None = None,
    source_agent_id: str | None = None,
    skill_run_id: str | None = None,
) -> list[ContextEntry]:
    """Extract constraint-type learnings from a failure output.

    Failures often reveal constraints (e.g., "API v1 requires auth")
    that should persist even when the step is retried.
    """
    if not failure_output or len(failure_output) < 10:
        return []

    entries = []
    sentences = _split_sentences(failure_output)

    for sentence in sentences:
        lower = sentence.lower()
        constraint_indicators = [
            "error",
            "failed",
            "cannot",
            "must",
            "required",
            "not found",
            "denied",
            "refused",
            "timeout",
            "crashes",
            "breaks",
            "incompatible",
        ]
        if any(ind in lower for ind in constraint_indicators):
            entries.append(
                ContextEntry(
                    context_type="constraint",
                    content=f"[From failure] {sentence.strip()[:500]}",
                    step_name=step_name,
                    source_agent_id=source_agent_id,
                    skill_run_id=skill_run_id,
                )
            )

    return entries[:5]


def _split_sentences(text: str) -> list[str]:
    """Split text into rough sentence-level chunks."""
    chunks = re.split(r"(?<=[.!?\n])\s+", text)
    return [c for c in chunks if len(c) > 15]


def _flatten_dict(d: dict, prefix: str = "") -> str:
    """Flatten a dict into readable text."""
    parts = []
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            parts.append(_flatten_dict(value, full_key))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    parts.append(_flatten_dict(item, f"{full_key}[{i}]"))
                else:
                    parts.append(f"{full_key}[{i}]: {item}")
        else:
            parts.append(f"{full_key}: {value}")
    return "\n".join(parts)
