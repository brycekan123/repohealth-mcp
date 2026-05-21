"""Small input-normalization helpers shared across tools."""

from __future__ import annotations

import re

_REPO_NORMALIZE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:|github\.com/)?"
    r"([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/.*)?$"
)


def normalize_repo(text: str) -> str:
    """Canonicalize a GitHub repo reference to ``owner/name``."""
    if not isinstance(text, str):
        raise ValueError(f"normalize_repo expects a string, got {type(text).__name__}")
    stripped = text.strip()
    if not stripped:
        raise ValueError("normalize_repo got empty string")
    match = _REPO_NORMALIZE.match(stripped)
    if not match:
        raise ValueError(f"can't parse repo from: {text!r}")
    owner, name = match.group(1), match.group(2)
    if not owner or not name:
        raise ValueError(f"can't parse repo from: {text!r}")
    return f"{owner}/{name}"
