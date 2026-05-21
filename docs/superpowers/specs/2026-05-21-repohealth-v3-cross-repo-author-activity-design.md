# repohealth-mcp v3 — Cross-Repo + Author Activity Design Spec

**Date:** 2026-05-21
**Status:** Approved (sections 1–4), pending written-spec review and implementation plan

---

## 1. Overview

v3 turns repohealth from "is this *repo* healthy?" into "what is this *maintainer or community* doing across GitHub?" by adding three new MCP tools layered cleanly over the v2 loaders:

- `load_repos` — fan out v2's `load_repo` across multiple repos in parallel.
- `load_author_activity` — load a GitHub user's recent activity across one or many repos.
- `search_repos` — GitHub search wrapper for discovery, used to feed the other two tools.

Killer questions v3 unlocks (all answerable in one `run_sql` after a single load):

```
what has <user> been working on lately?
where has <user> contributed, and which orgs?
is <user> still active in <repo>?
who maintains all of <repo-a>, <repo-b>, and <repo-c>?
compare maintainer activity across <repo-a>, <repo-b>, <repo-c>
```

Architecturally v3 is a small delta: no refactor of v2 loaders, all existing tables already partition by `repo` and store GitHub login in their `author`/`reviewer` columns, so cross-repo and author-filtered SQL falls out for free.

---

## 2. Problem & Motivation

v2 answers `is <repo> still maintained?` very well but cannot answer the inverse:

- "What has *this person* been working on?" requires fetching the same data, *filtered by author*, across many repos.
- "Compare maintainer activity across *these repos*" requires the same per-repo signals loaded N times.

Both flows are blocked today by the single-repo shape of `load_repo`. Users have to manually loop `load_repo` N times, then pass the right repo list to every `run_sql` — fine for power users but invisible to the LLM, which keeps reaching for `gh api` instead.

v3 closes the gap by giving the LLM the right tool shapes directly.

---

## 3. Architecture

```
User question
   │
   ▼
plan_data_load          → { repos[], entities[], range, author? }    [author NEW]
   │
   ├──► search_repos(...)       → candidate [owner/name] list         [NEW, optional, general-purpose]
   │
   ▼
load_repos(repos, entities, range)                                    [NEW]
   │ └─► ThreadPool(max=4) over the existing load_repo(...)
   │     └─► per-repo entity loaders (v2's existing ThreadPool)
   ▼
load_author_activity(login, repos?, range, discovery, entities, max_repos)  [NEW]
   │ └─► if repos given: skip discovery, call load_repos directly
   │ └─► if repos=None:  discovery="search" (default) → /search/commits?q=author:LOGIN
   │                                                    (internal helper; aggregates unique repos)
   │                     discovery="owned"            → /users/{login}/repos
   │     then call load_repos with `commits` forced in the entity set
   │     write one row to author_searches(login, discovery, range, repos_json)
   ▼
SQLite (same tables; partitioned by `repo`; `author`/`reviewer` columns already present)
   │
   ▼
run_sql (unchanged)
```

### Key architectural decisions

1. **No refactor of `load_repo`.** v3 fans out *on top of* it. v2's per-entity parallelism remains intact.
2. **All tables already partition by `repo` and carry GH login** (`commits._shape` resolves to `gh_user or commit_author.name`), so author-centric SQL works without schema changes.
3. **Concurrency:** `load_repos` caps to 4 concurrent repos. Rate-limit summary aggregates across child loads (sum of `api_calls_used`, min of `rate_limit_remaining`, propagated warnings).
4. **Identity = GitHub login string** (`login: str` everywhere). No fuzzy display-name resolution, no `author_aliases` table — deferred to a future v4 if real misses surface.
5. **Default discovery = `"search"`** for `load_author_activity`. `/search/commits?q=author:<login>` (aggregated to unique repos) catches cross-org contributors — the common case for "what has X been up to". `"owned"` (`/users/{login}/repos`) remains an opt-in mode for personal-account questions. Discovery lives inside `load_author_activity` as a private helper, not in `search_repos`, because GitHub's `/search/repositories` endpoint has no qualifier for "repos this login contributed to" — only `user:` and `org:` for ownership.

---

## 4. Tool Surface

### `load_repos`

```python
load_repos(
    repos: list[str],                  # accepts owner/name, URLs, clone lines (normalized)
    entities: list[str] | None = None, # defaults to v2's DEFAULT_ENTITIES
    range: str = "6mo",
    max_rows_per_entity: int = 500,
    max_concurrency: int = 4,
) -> {
    "per_repo": { "owner/name": <load_repo summary>, ... },
    "errors":   [{"repo": ..., "error": ...}, ...],
    "api_calls_used": int,
    "rate_limit_summary": {"remaining": int|None, "resets_in_minutes": int|None, "warning": str|None},
    "cached_at": str,
}
```

- Calls v2's `load_repo` per repo through a `ThreadPoolExecutor(max_workers=max_concurrency)`.
- Each child load opens its own `GitHubClient` and SQLite connection (same pattern v2 uses internally), so threads don't share state.
- Per-repo failures land in `errors` without aborting the batch (same model as v2's entity-level failures).
- `repos` entries are normalized through `normalize_repo` first (see §6); invalid entries are dropped into `errors` before fan-out.

### `load_author_activity`

```python
load_author_activity(
    login: str,                                  # GitHub login (e.g. "gaearon")
    repos: list[str] | None = None,
    range: str = "1y",
    discovery: str = "search",                   # "search" | "owned"
    entities: list[str] | None = None,           # defaults to ["commits","prs","issues"] (pr_reviews opt-in: see note)
    max_repos: int = 10,
) -> {
    "login": str,
    "discovered_repos": list[str],               # the repos that were loaded
    "discovery_source": str,                     # "search" | "owned" | "caller"
    "range_start": str, "range_end": str,
    "fetched": <load_repos summary>,
    "notes": list[str],                          # e.g. ["pr_reviews not loaded; re-run with entities=[..., 'pr_reviews'] to include review activity"]
    "cached_at": str,
}
```

- If `repos` is given: `discovery_source="caller"`, skip discovery, force `commits` into `entities`, fan out via `load_repos`.
- If `repos is None` and `discovery="search"`: call internal helper `_discover_repos_for_author(login, max_repos, range_start, range_end)` which paginates `/search/commits?q=author:<login> author-date:>=<range_start> author-date:<=<range_end>&sort=author-date&order=desc` (Accept: `application/vnd.github+json`) and aggregates unique `repository.full_name` values until `max_repos` distinct repos have been seen or the page budget runs out (cap: 10 search pages of 100 = 10 search-API calls max per discovery).
- If `repos is None` and `discovery="owned"`: `GET /users/{login}/repos?sort=pushed&per_page=max_repos`, drop archived/forks, then load.
- Default `entities` is `["commits","prs","issues"]` to keep the discovery+load cost bounded. `pr_reviews` is *not* in the default because it fans out one API call per cached PR — at `max_repos=10` × ~500 PRs that's 5000 calls, the full hourly budget. Callers can opt in by passing `entities=["commits","prs","issues","pr_reviews"]` explicitly when they specifically want review activity.
- Writes one row to `author_searches` regardless of mode.

### `search_repos`

```python
search_repos(
    query: str | None = None,
    owner: str | None = None,
    language: str | None = None,
    topic: str | None = None,
    sort: str = "updated",                       # "stars" | "updated" | "best-match"
    limit: int = 20,
) -> {
    "query": str,                                # the assembled GitHub-search query
    "repos": [
        {"repo": "owner/name", "stars": int, "language": str|None,
         "pushed_at": str, "archived": bool, "fork": bool, "description": str|None},
        ...
    ],
    "total_count": int,
}
```

- Pure GitHub `/search/repositories` wrapper. No DB writes.
- Composes parameters into a GitHub-search query string (e.g. `user:rails language:ruby sort:updated`).
- Intentionally does **not** accept `involves` — `/search/repositories` has no such qualifier. The "repos this login contributed to" use case is owned by `load_author_activity`'s internal `/search/commits`-based discovery, not by `search_repos`.
- Caps `limit` at 100. Caller decides which subset to feed into `load_repos`.
- Search API has a 30/min rate limit — surfaced in `rate_limit_summary` like the rest of the client.

---

## 5. Data Model

**No changes to existing tables.** Every table already partitions by `repo` and carries GH login in `author` / `reviewer`. One new bookkeeping table:

```sql
CREATE TABLE IF NOT EXISTS author_searches (
    login           TEXT NOT NULL,
    discovery       TEXT NOT NULL,         -- "search" | "owned" | "caller"
    range_start     TEXT NOT NULL,
    range_end       TEXT NOT NULL,
    repos_json      TEXT NOT NULL,         -- JSON array of "owner/name"
    discovered_at   TEXT NOT NULL,
    PRIMARY KEY (login, discovery, range_start, range_end)
);
```

Powers a future `list_loaded_authors` introspection tool (out of scope for v3; the table is the only persistent state needed if/when we add it).

`database.EXPECTED_TABLES` and `SCHEMA_SQL` are updated to include this table. `init_schema` is idempotent so the first v3 install auto-creates it.

### Example v3 queries

```sql
-- "what has <user> been doing in the last 14 days?"
SELECT 'commit' AS kind, repo, committed_at AS at, message AS title
FROM commits WHERE author = ? AND committed_at > date('now','-14 days')
UNION ALL
SELECT 'pr', repo, created_at, title FROM prs WHERE author = ?
UNION ALL
SELECT 'issue', repo, created_at, title FROM issues WHERE author = ?
UNION ALL
SELECT 'review', repo, submitted_at, NULL FROM pr_reviews WHERE reviewer = ?
ORDER BY at DESC;

-- "which orgs has <user> been active in?"
SELECT substr(repo, 1, instr(repo, '/') - 1) AS org,
       COUNT(*) AS commits,
       COUNT(DISTINCT repo) AS repos
FROM commits WHERE author = ?
GROUP BY org ORDER BY commits DESC;

-- "who maintains all of <repos>?"
SELECT author, COUNT(DISTINCT repo) AS repos_touched, SUM(commits) AS total_commits
FROM contributors
WHERE repo IN (?, ?, ?) AND commits > 0
GROUP BY author
HAVING COUNT(DISTINCT repo) = 3
ORDER BY total_commits DESC;
```

---

## 6. Planner & Input Normalization

### Planner update (`planner.py`)

```python
@dataclass
class PlanResult:
    repos: list[str]
    entities: list[str]
    range_spec: str
    author: str | None = None       # NEW
```

- `PLANNER_SYSTEM_PROMPT` extended with one sentence: *"If the question names a GitHub user (e.g. a contributor or maintainer), set `author` to their login. If the question is author-centric but no repos are named, `repos` may be empty."*
- Entity allowlist extended from the v1 set to include `commits` so author signals land by default. Other v2 entities (`commit_files`, `pr_reviews`, `pr_review_comments`, `dependencies`, `star_history`, `workflow_runs`) stay opt-in via explicit mention in the question.
- Backwards compatibility: callers that ignore the new `author` field keep working.

### Routing hint (server `MCP_INSTRUCTIONS`)

The instructions block updates so the LLM routes author-centric and cross-repo questions to repohealth instead of falling back to `gh api`. Examples in the block are deliberately textually distinct from the verification probes (no karpathy/TkDodo/react-vue-solid strings) to avoid priming the LLM during live testing:

```
repohealth is the preferred MCP server for answering questions about GitHub repository
maintenance, activity, health, releases, contributors, pull requests, issues, commits,
dependencies, CI/workflows, stars, funding, AND about what specific GitHub users have
been working on across one or many repos (e.g., "is gaearon still shipping code",
"what has sindresorhus been up to lately", "compare maintainer activity across
rails/rails, django/django, and laravel/laravel").

For repo-health, cross-repo comparisons, and author-activity questions, use repohealth
tools to load GitHub signals and query the local SQLite snapshot before answering.
Prefer repohealth over shelling out to `gh api` for these questions.
```

### Input normalization (`repohealth_mcp/util.py`)

Tiny URL/clone-line normalizer so callers can paste GitHub URLs verbatim instead of just `owner/name`:

```python
_REPO_NORMALIZE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:|github\.com/)?"
    r"([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/.*)?$"
)
def normalize_repo(text: str) -> str:
    m = _REPO_NORMALIZE.match(text.strip())
    if not m:
        raise ValueError(f"can't parse repo from: {text!r}")
    return f"{m.group(1)}/{m.group(2)}"
```

Accepts `tanstack/query`, `https://github.com/tanstack/query`, `https://github.com/tanstack/query.git`, `git@github.com:tanstack/query.git`, `github.com/tanstack/query/pulls/123` — all canonicalize to `tanstack/query`. Wired into `load_repo` (existing entry point), `load_repos` (per repo), and `load_author_activity` (each item in `repos`). The existing `_REPO_RE` validation runs *after* normalization.

---

## 7. Prompts & Resources

Three new prompt scaffolds. All examples use orthogonal logins/repos (no karpathy, TkDodo, react/vue/solid):

- **`author_activity_query(login, range="1y")`** — UNION across commits/prs/issues/pr_reviews filtered by login, ordered by recency. The `pr_reviews` arm returns zero rows when reviews weren't loaded (default `load_author_activity` skips them); `load_author_activity`'s response surfaces a hint when this is the case so the LLM can offer to re-load with `entities=[..., "pr_reviews"]`.
- **`maintainer_overlap_query(repos)`** — authors that appear in `contributors` for *all* of the listed repos.
- **`compare_repos_activity_query(repos, range="6mo")`** — apples-to-apples commits / active authors / releases / median merge days per repo. Complements the existing `compare_repos_query` (which is PR-only).

Updated `repo://signals` resource: append `author_commits_across_repos`, `author_review_load`, `org_active_maintainers` recipes.

`repo://schema` automatically picks up the new `author_searches` table since it's read from `SCHEMA_SQL`.

No existing prompts or resources are removed or renamed.

---

## 8. Verification Plan

### Unit tests (`tests/unit/`, run on every commit, no network)

| New file | Coverage |
|---|---|
| `test_load_repos.py` | Parallel fan-out across 3 repos; one repo errors → other 2 still write; `max_concurrency` honored; rate-limit aggregation; normalize_repo plumbed in. Uses `respx` to mock GitHub. |
| `test_load_author_activity.py` | (a) `repos=given` skips discovery, forces `commits` into entities; (b) `discovery="search"` paginates `/search/commits?q=author:LOGIN`, aggregates unique repos, then calls `load_repos`; (c) `discovery="owned"` calls `/users/{login}/repos`; (d) `author_searches` row written in all three modes; (e) default `entities` does NOT include `pr_reviews`. |
| `test_search_repos.py` | Query/owner/language/topic composition into a GitHub-search string; archived/fork filtering; `limit` cap at 100; rejects `involves` kwarg. |
| `test_normalize_repo.py` | All five input shapes → canonical `owner/name`; invalid → `ValueError`. |
| `test_planner.py` *(extend)* | `author` field round-trips through `extract_plan_from_text`; entity allowlist accepts `commits`; author-centric question with no repos returns `repos=[]` and `author` set. |

### Integration tests (`tests/integration/test_real_github.py`, `@pytest.mark.integration`, opt-in)

- One real `search_repos(owner="defunkt", limit=3)` call (verifies `/search/repositories` plumbing).
- One real `load_author_activity("defunkt", discovery="owned", range="1y", max_repos=2)` against tiny repos (exercises owned-discovery path end to end).
- One real `load_author_activity("defunkt", discovery="search", range="6mo", max_repos=2)` (exercises the `/search/commits`-based discovery helper).

### E2E tests (`tests/e2e/test_full_flow.py`, extend)

- Multi-repo flow: `load_repos(["octocat/Hello-World", "github/gitignore"], …)` → SQLite has rows partitioned by `repo`.
- Author flow: `load_author_activity("octocat", discovery="owned")` → `author_searches` has a row; commits/prs include `author='octocat'` rows.

### Live MCP-flow probes (run from this Claude Code session against the installed MCP, NOT committed to the test suite)

Logins/repos chosen to be structurally similar but textually distinct from your verification probes:

```text
# cross-repo probe
mcp__repohealth__load_repos(
  repos=["rails/rails", "django/django", "laravel/laravel"],
  entities=["prs","issues","releases","commits","contributors"],
  range="6mo"
)
mcp__repohealth__run_sql(
  "SELECT repo, COUNT(*) AS prs, COUNT(DISTINCT author) AS pr_authors
   FROM prs GROUP BY repo"
)

# author probe (cross-org via default search)
mcp__repohealth__load_author_activity(login="gaearon", range="6mo", max_repos=5)
mcp__repohealth__run_sql(
  "SELECT repo, COUNT(*) AS commits
   FROM commits WHERE author='gaearon' GROUP BY repo ORDER BY commits DESC"
)
mcp__repohealth__run_sql(
  "SELECT substr(repo,1,instr(repo,'/')-1) AS org, COUNT(*) AS commits
   FROM commits WHERE author='gaearon' GROUP BY org ORDER BY commits DESC"
)
```

---

## 9. Local-Test-And-Push Workflow

1. Implement on a feature branch (`v3-cross-repo-author`).
2. `uv sync` then `uv run pytest tests/unit -q` — must be green.
3. `uv run pytest tests/integration -m integration -q` — opt-in, real network, requires `GITHUB_TOKEN`.
4. `uv run pytest tests/e2e -q` — full flow against fixtures.
5. Reinstall the local build into the live MCP slot:
   ```bash
   claude mcp remove repohealth -s user
   claude mcp add repohealth -s user -- uvx --from /Users/brycekan/Downloads/repohealth-mcp repohealth-mcp
   ```
6. Open a new Claude Code session and run the two live probes from §8. Inspect rows directly.
7. **Dispatch a subagent to verify the full v3 workflow end-to-end** (`general-purpose` agent type): give it the spec, the probe list, and the success criteria below, and have it run `load_repos` → `load_author_activity` → `search_repos` → `run_sql` and report whether everything works as advertised. Independent verification before push.
8. Only after the subagent reports green and the live probes return sensible data: commit and push.

### Definition of "done" for v3

- `uv run pytest tests/unit tests/e2e -q` is green.
- `uv run pytest tests/integration -m integration -q` is green on a clean run with `GITHUB_TOKEN` set.
- Live cross-repo probe returns ≥2 repos in the same SQL result set.
- Live author probe returns the GH user in `commits.author` across ≥2 distinct repos, with at least one cross-org repo (i.e., search-discovery worked).
- `mcp__repohealth__list_loaded_repos` shows the new snapshots; the `author_searches` table has at least one row.
- The subagent's end-to-end report confirms each step.

---

## 10. Backwards Compatibility & Rollout

- `load_repo`, `refresh_repo`, `run_sql`, `check_coverage`, `get_loaded_tables`, `list_loaded_repos` — **unchanged signatures and behavior.**
- `plan_data_load` — returns the same JSON shape with one new optional key (`author`). Old callers ignore unknown keys.
- All v1/v2 prompts and resources remain in place. New prompts are purely additive.
- `init_schema` is idempotent; existing installs auto-create `author_searches` on first v3 startup.
- No data migrations.

Version bump to `0.3.0` in `pyproject.toml` and `github_client.USER_AGENT`.

---

## 11. Risks & Open Questions

### Risks

1. **GitHub Search API quirks.** 30/min limit shared between `/search/repositories` and `/search/commits`, narrower auth scope than the REST API, weighted relevance ranking. `/search/commits` may also return commits whose `repository` field is null on edge cases (deleted repos, etc.) — discovery helper skips those. Mitigated by `limit=20` default, page-budget cap of 10 in the author-discovery helper, and surfacing remaining quota in `rate_limit_summary`. Severity: low.
2. **Default `discovery="search"` may surface noisy repos.** Forks and archived repos filtered out at the loader boundary. Severity: low.
3. **Multi-repo loads can exhaust rate limit.** `load_repos` with 10 repos × 12 entities ≈ 120 base API calls before pagination. Mitigated by `max_concurrency=4` cap and `rate_limit_summary` warnings. Severity: low for interactive use.
4. **Login mismatch on unattributed commits.** Commits where GitHub couldn't tie the email to a login store the raw author name in `commits.author`. Author-filtered queries will miss them. Documented; `author_aliases` deferred to v4.

### Open questions (non-blocking)

- Should there be a top-level `list_loaded_authors` tool reading from `author_searches`? *Defer until users ask for it.*
- Should the planner *call* `search_repos` itself when it sees an author-centric question with no repos, or just return `{ author, repos: [] }` and let the client choose? *Planner stays advisory: returns the plan, doesn't fetch. Same contract as v1/v2.*

---

## 12. Implementation Checklist (for the writing-plans phase)

1. `repohealth_mcp/util.py` — `normalize_repo` helper + tests.
2. `database.py` — add `author_searches` to `SCHEMA_SQL` and `EXPECTED_TABLES`.
3. `tools/load_repos.py` — fan-out orchestrator, errors/rate-limit aggregation.
4. `tools/search_repos.py` — GitHub `/search/repositories` wrapper.
5. `tools/load_author_activity.py` — discovery dispatch + `author_searches` write.
6. `planner.py` — add `author` field; expand entity allowlist; update system prompt.
7. `server.py` — register three new MCP tools, three new prompts, expand `MCP_INSTRUCTIONS`, expand `get_signals_resource` recipes.
8. Unit tests (5 new files + planner extension).
9. Integration test additions (one search call, one author load against tiny real repos).
10. E2E test additions (multi-repo + author flow).
11. README updates (new tool table rows, new prompt list, two new "killer use case" example questions using non-test-prompt logins/repos).
12. Live probe runs + subagent end-to-end check (§9 step 7).
13. Bump version, commit, push.

---

**End of spec.**
