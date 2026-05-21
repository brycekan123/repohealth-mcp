"""Natural language question to data-load plan conversion."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable

DEFAULT_ENTITIES = ["prs", "issues", "releases", "commit_activity", "contributors"]
ALLOWED_PLAN_ENTITIES = {
    "prs",
    "issues",
    "releases",
    "commit_activity",
    "contributors",
    "commits",
}
DEFAULT_RANGE = "6mo"

PLANNER_SYSTEM_PROMPT = """\
You parse a user's natural-language question about GitHub repos or maintainers into a fetch plan.

Return ONLY a single JSON object with these keys:
  - "repos": list of "owner/name" strings mentioned in the question. May be empty
    if the question is author-centric and names no repos.
  - "entities": list, subset of:
        ["prs", "issues", "releases", "commit_activity", "contributors", "commits"].
  - "range": one of "30d", "90d", "6mo", "1y", "all", or "YYYY-MM-DD..YYYY-MM-DD".
  - "author": optional string. If the question names a GitHub user, set this to
    their login. Omit or set to null otherwise.

Default to ["prs","issues","releases","commit_activity","contributors"] entities
and "6mo" range if the question is general.
"""

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class PlanResult:
    repos: list[str]
    entities: list[str]
    range_spec: str
    author: str | None = None


def extract_plan_from_text(text: str) -> PlanResult:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        raise ValueError(f"could not find JSON object in LLM output: {text[:200]}")

    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON from LLM: {exc}") from exc

    repos = obj.get("repos") or []
    if not isinstance(repos, list) or not all(isinstance(repo, str) for repo in repos):
        raise ValueError("plan repos must be a list of strings")

    entities = obj.get("entities") or DEFAULT_ENTITIES
    if not isinstance(entities, list) or not all(isinstance(entity, str) for entity in entities):
        raise ValueError("plan entities must be a list of strings")
    unknown_entities = set(entities) - ALLOWED_PLAN_ENTITIES
    if unknown_entities:
        raise ValueError(f"unknown entities in plan: {sorted(unknown_entities)}")

    range_spec = obj.get("range") or DEFAULT_RANGE
    if not isinstance(range_spec, str):
        raise ValueError("plan range must be a string")

    author = obj.get("author")
    if author is not None and not isinstance(author, str):
        raise ValueError("plan author must be a string or null")
    if isinstance(author, str):
        author = author.strip() or None

    if not repos and author is None:
        raise ValueError("plan requires at least one repo or author")

    return PlanResult(
        repos=list(repos),
        entities=list(entities),
        range_spec=range_spec,
        author=author,
    )


def _default_llm(prompt: str) -> str:
    from google import genai

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-001")
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text or ""


def plan_data_load(question: str, llm: Callable[[str], str] | None = None) -> PlanResult:
    llm = llm or _default_llm
    prompt = f"{PLANNER_SYSTEM_PROMPT}\n\nQ: {question}\nA:"
    return extract_plan_from_text(llm(prompt))
