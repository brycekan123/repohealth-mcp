from unittest.mock import MagicMock

import pytest

from repohealth_mcp.planner import PlanResult, extract_plan_from_text, plan_data_load


def test_extract_plan_from_text_parses_clean_json() -> None:
    text = '{"repos": ["o/r"], "entities": ["prs"], "range": "6mo"}'
    result = extract_plan_from_text(text)
    assert result.repos == ["o/r"]
    assert result.entities == ["prs"]
    assert result.range_spec == "6mo"
    assert result.author is None


def test_extract_plan_from_text_strips_code_fences() -> None:
    text = '```json\n{"repos": ["o/r"], "entities": ["prs"], "range": "30d"}\n```'
    result = extract_plan_from_text(text)
    assert result.repos == ["o/r"]


def test_extract_plan_from_text_multi_repo() -> None:
    text = '{"repos": ["a/b", "c/d", "e/f"], "entities": ["prs", "issues"], "range": "1y"}'
    result = extract_plan_from_text(text)
    assert len(result.repos) == 3
    assert "issues" in result.entities


def test_extract_plan_from_text_defaults_entities_if_missing() -> None:
    text = '{"repos": ["o/r"], "range": "6mo"}'
    result = extract_plan_from_text(text)
    assert set(result.entities) == {"prs", "issues", "releases", "commit_activity", "contributors"}


def test_extract_plan_from_text_defaults_range_if_missing() -> None:
    text = '{"repos": ["o/r"], "entities": ["prs"]}'
    result = extract_plan_from_text(text)
    assert result.range_spec == "6mo"


def test_extract_plan_from_text_rejects_empty_repos_without_author() -> None:
    text = '{"repos": [], "entities": ["prs"], "range": "6mo"}'
    with pytest.raises(ValueError, match="repo or author"):
        extract_plan_from_text(text)


def test_extract_plan_from_text_rejects_malformed_json() -> None:
    text = "not json at all"
    with pytest.raises(ValueError):
        extract_plan_from_text(text)


def test_extract_plan_from_text_rejects_malformed_field_types() -> None:
    text = '{"repos": ["o/r"], "entities": "prs", "range": {}}'
    with pytest.raises(ValueError):
        extract_plan_from_text(text)


def test_plan_data_load_invokes_llm_and_parses() -> None:
    fake_llm = MagicMock()
    fake_llm.return_value = '{"repos": ["o/r"], "entities": ["prs"], "range": "6mo"}'
    result = plan_data_load("is o/r maintained?", llm=fake_llm)
    assert isinstance(result, PlanResult)
    assert result.repos == ["o/r"]
    assert fake_llm.call_count == 1


def test_plan_data_load_passes_question_to_llm() -> None:
    fake_llm = MagicMock()
    fake_llm.return_value = '{"repos": ["o/r"], "entities": ["prs"], "range": "6mo"}'
    plan_data_load("compare a/b and c/d", llm=fake_llm)
    prompt_arg = fake_llm.call_args.args[0]
    assert "compare a/b and c/d" in prompt_arg


def test_planner_round_trips_author_field():
    plan = extract_plan_from_text(
        '{"repos": [], "entities": ["commits"], "range": "6mo", "author": "gaearon"}'
    )
    assert plan.author == "gaearon"
    assert plan.repos == []
    assert plan.entities == ["commits"]


def test_planner_author_defaults_to_none():
    plan = extract_plan_from_text(
        '{"repos": ["facebook/react"], "entities": ["prs"], "range": "6mo"}'
    )
    assert plan.author is None


def test_planner_accepts_commits_in_entities():
    plan = extract_plan_from_text(
        '{"repos": ["facebook/react"], "entities": ["prs", "commits"], "range": "6mo"}'
    )
    assert "commits" in plan.entities
