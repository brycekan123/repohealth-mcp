# repohealth-mcp — Design Spec

**Date:** 2026-05-20
**Status:** Approved by user (sections 1–6), pending written-spec review

---

## 1. Overview

`repohealth-mcp` is a Model Context Protocol (MCP) server that lets an LLM client (Claude Code, Codex CLI, any MCP-aware tool) answer **dep-health and repo-analytics questions** about any public GitHub repo by loading repo data into a local SQLite snapshot and running SQL aggregations.

It is architected as a sibling to `cityops-mcp`: same skeleton (NL → plan → coverage-check → load → SQL → synthesize), same install UX (`uvx --from git+...`), same read-only SQL contract — but pointed at GitHub instead of Open-Meteo.

### Killer use cases

```
"is tanstack/query still actively maintained?"
"compare react-query, swr, and tanstack-query"
"release cadence for vercel/next.js over the last year"
"who are the top contributors to facebook/react this quarter?"
```

The cross-repo comparison case is the **primary differentiator** from existing GitHub MCPs.

---

## 2. Problem & Motivation

### The gap in the existing landscape

| Existing tool | What it does | Gap |
|---|---|---|
| Official `github/github-mcp-server` | Per-call API proxy (get this PR, list those issues) | No aggregation, no caching, no cross-repo, no SQL |
| `@modelcontextprotocol/server-github` | Simpler API proxy | Same as above |
| GitHub Insights tab | Pre-built dashboards in the web UI | Fixed questions only; can't ask in NL; can't join across repos |

**The unfilled niche:** *analytics + caching + SQL over GitHub data, surfaced through MCP so any LLM client can query it in natural language and answer follow-ups instantly.*

### Why caching is essential

SQL queries need data in a table. Every question is **fetch → load to SQLite → run SQL**. The "cache" is the SQLite file itself; without it, every follow-up question burns hundreds of API calls and 30+ seconds.

For v1 we use a **snapshot model**: load once per `(repo, entity, range)` key, follow-ups in the same conversation are instant, manual `refresh_repo` is the escape hatch when the user wants fresh data. ETag / TTL / delta-sync complexity is **deferred to v2**.

---

## 3. Architecture

Four-layer flow, mirroring cityops-mcp:

```
User question
   │
   ▼
┌──────────────┐
│  planner.py  │  NL → {repos: [...], entities: [...], date_range: ...}
└──────────────┘
   │
   ▼
┌──────────────┐
│  coverage    │  For each (repo, entity, range): is it already in SQLite?
└──────────────┘
   │
   ▼
┌────────────────────────────┐
│  loaders/{prs,issues,...}  │  Fetch missing data from GitHub REST API,
│  github_client.py          │  paginate, write rows to SQLite
└────────────────────────────┘
   │
   ▼
┌──────────────┐
│  run_sql     │  Read-only SELECT/WITH against SQLite, 1000-row cap
└──────────────┘
   │
   ▼
Answer (LLM synthesizes from rows)
```

### Key architectural decisions

1. **REST, not GraphQL.** Simpler for v1. GraphQL migration is a v2 option if compound queries become a bottleneck.
2. **Snapshot model.** Load once per `(repo, entity, range)`, follow-ups hit cache. Every response carries `cached_at`. `refresh_repo` forces re-fetch. No ETag/TTL in v1.
3. **Shared tables partitioned by `repo` column.** Cross-repo SQL falls out of the schema design — no special "compare" path required.
4. **Token from env (`GITHUB_TOKEN`).** Same dev-tool UX as `gh` CLI. Unauthenticated mode supported with loud warning (60/hr limit).
5. **6-month default fetch window.** User-configurable per query.
6. **Python + FastMCP + uv-buildable**, mirroring cityops install UX.
7. **Stats endpoints over raw commits.** `/repos/{repo}/stats/commit_activity` and `/stats/contributors` give us aggregated truth in 1 call each — vastly cheaper than fetching raw commits. Raw commits deferred to v2 if power users need them.

---

## 4. Tool Surface

Seven MCP tools, two resources, five prompts.

### Tools

| Tool | Inputs | Output |
|---|---|---|
| `plan_data_load` | `question: str` | `{repos: [...], entities: [...], range: {start, end}}` — LLM-parsed fetch plan |
| `check_coverage` | `repo, entity, range` | `{cached: bool, cached_at: ts \| null, rows: int}` — UX hint |
| `load_repo` | `repo, entities=[all 5], range="6mo", max_rows_per_entity=500` | Idempotent — fetches only missing rows, writes to SQLite. Returns counts + rate-limit summary. |
| `refresh_repo` | `repo, entities, range` | Drops + reloads, forces fresh snapshot. |
| `run_sql` | `query: str` | Read-only `SELECT`/`WITH` only, 1000-row cap. Returns rows + column names. |
| `get_loaded_tables` | — | Schema + row counts per table |
| `list_loaded_repos` | — | All `(repo, entity, range)` snapshots with `cached_at` timestamps |

### Resources (read-only data the client can inspect)

- `repo://schema` — full SQL schema for `prs`, `issues`, `releases`, `commit_activity`, `contributors`
- `repo://signals` — documented health signals with canonical SQL recipes (a curated menu of pre-vetted queries)

### Prompts (SQL scaffolds, mirroring cityops' 5-prompt pattern)

- `dep_health_query` — single-repo "is X maintained?" template
- `compare_repos_query` — cross-repo apples-to-apples comparison
- `release_cadence_query` — release timing patterns
- `responsiveness_query` — issue/PR first-response and merge times
- `contributor_health_query` — maintainer concentration / bus factor

### Design notes

- **`load_repo` is idempotent on purpose.** Internally calls `check_coverage` and only fetches what's missing. `check_coverage` stays as a separate tool so the LLM can warn users of long fetches *before* calling.
- **`run_sql` is read-only and capped at 1000 rows.** Same safety contract as cityops.
- **Singular vs plural:** `plan_data_load` returns a `repos: [...]` list because user questions can name multiple. `load_repo` is singular and called N times (parallelizable) for multi-repo questions.

---

## 5. Data Model (SQLite Schema)

Five entity tables + one bookkeeping table. All entity tables partitioned by `repo` column (composite PKs starting with `repo`). All loaders use UPSERT for idempotent reloads.

### `repos` — one row per loaded repo

```sql
CREATE TABLE repos (
    repo            TEXT PRIMARY KEY,
    description     TEXT,
    default_branch  TEXT,
    stars           INTEGER,
    forks           INTEGER,
    open_issues_count INTEGER,
    created_at      TEXT,
    pushed_at       TEXT,
    archived        INTEGER,
    disabled        INTEGER,
    license         TEXT,
    cached_at       TEXT NOT NULL
);
```

### `prs` — one row per PR (capped at 500 most recent in range)

```sql
CREATE TABLE prs (
    repo            TEXT NOT NULL,
    number          INTEGER NOT NULL,
    title           TEXT,
    author          TEXT,
    state           TEXT,                      -- "open" | "closed"
    draft           INTEGER,
    created_at      TEXT,
    updated_at      TEXT,
    closed_at       TEXT,
    merged_at       TEXT,                      -- NULL if closed unmerged
    comments_count  INTEGER,
    base_branch     TEXT,
    PRIMARY KEY (repo, number)
);
CREATE INDEX idx_prs_repo_merged ON prs(repo, merged_at);
CREATE INDEX idx_prs_repo_author ON prs(repo, author);
```

> No `first_review_at` in v1. Fetching reviews per-PR would add ~500 API calls per repo. Median time-to-merge (`merged_at - created_at`) is a strong proxy and free.

### `issues` — one row per issue, excluding PRs

GitHub's `/issues` endpoint conflates issues and PRs; loader filters where `pull_request IS NULL`.

```sql
CREATE TABLE issues (
    repo            TEXT NOT NULL,
    number          INTEGER NOT NULL,
    title           TEXT,
    author          TEXT,
    state           TEXT,
    state_reason    TEXT,                      -- "completed" | "not_planned" | NULL
    labels          TEXT,                      -- JSON array
    created_at      TEXT,
    updated_at      TEXT,
    closed_at       TEXT,
    comments_count  INTEGER,
    PRIMARY KEY (repo, number)
);
CREATE INDEX idx_issues_repo_state ON issues(repo, state);
CREATE INDEX idx_issues_repo_created ON issues(repo, created_at);
```

### `releases` — one row per release (usually <100, no cap)

```sql
CREATE TABLE releases (
    repo            TEXT NOT NULL,
    id              INTEGER NOT NULL,
    tag_name        TEXT,
    name            TEXT,
    author          TEXT,
    published_at    TEXT,
    created_at      TEXT,
    draft           INTEGER,
    prerelease      INTEGER,
    PRIMARY KEY (repo, id)
);
CREATE INDEX idx_releases_repo_published ON releases(repo, published_at);
```

### `commit_activity` — one row per week (from `/stats/commit_activity`, 52 weeks)

```sql
CREATE TABLE commit_activity (
    repo            TEXT NOT NULL,
    week_start_at   TEXT NOT NULL,             -- ISO, Sunday-aligned
    total_commits   INTEGER,
    mon INTEGER, tue INTEGER, wed INTEGER, thu INTEGER,
    fri INTEGER, sat INTEGER, sun INTEGER,
    PRIMARY KEY (repo, week_start_at)
);
```

### `contributors` — one row per (repo, author, week) (from `/stats/contributors`)

```sql
CREATE TABLE contributors (
    repo            TEXT NOT NULL,
    author          TEXT NOT NULL,
    week_start_at   TEXT NOT NULL,
    commits         INTEGER,
    additions       INTEGER,
    deletions       INTEGER,
    PRIMARY KEY (repo, author, week_start_at)
);
CREATE INDEX idx_contributors_repo_author ON contributors(repo, author);
```

### `snapshots` — bookkeeping for the cache layer

Distinguishes *"never loaded this slice"* from *"loaded it, got zero rows"*. Every successful loader writes one row here. Powers `check_coverage` and `list_loaded_repos`.

```sql
CREATE TABLE snapshots (
    repo            TEXT NOT NULL,
    entity          TEXT NOT NULL,             -- "prs"|"issues"|"releases"|...
    range_start     TEXT NOT NULL,
    range_end       TEXT NOT NULL,
    cached_at       TEXT NOT NULL,
    row_count       INTEGER NOT NULL,
    PRIMARY KEY (repo, entity, range_start, range_end)
);
```

### Example queries the schema enables

```sql
-- Median time-to-merge for last 6 months, single repo
SELECT median(julianday(merged_at) - julianday(created_at)) AS days_to_merge
FROM prs
WHERE repo = 'vercel/next.js' AND merged_at > date('now', '-6 months');

-- Cross-repo comparison of merge speed and activity
SELECT repo,
       COUNT(*) AS merged_prs,
       ROUND(AVG(julianday(merged_at) - julianday(created_at)), 1) AS avg_days,
       COUNT(DISTINCT author) AS distinct_authors
FROM prs
WHERE merged_at > date('now', '-6 months')
GROUP BY repo;

-- Bus factor: % of commits from top contributor
SELECT repo,
       MAX(author_commits) * 100.0 / SUM(author_commits) AS top_contrib_pct
FROM (SELECT repo, author, SUM(commits) AS author_commits
      FROM contributors GROUP BY repo, author)
GROUP BY repo;

-- Release cadence: median days between releases
WITH ordered AS (
  SELECT repo, published_at,
         LAG(published_at) OVER (PARTITION BY repo ORDER BY published_at) AS prev
  FROM releases WHERE published_at IS NOT NULL
)
SELECT repo, median(julianday(published_at) - julianday(prev)) AS median_days_between
FROM ordered WHERE prev IS NOT NULL GROUP BY repo;
```

### Schema caveats

1. **SQLite has no built-in `median()`.** Register a Python UDF at connection time. Same pattern works for `percentile_cont`.
2. **`/stats/*` endpoints may return HTTP 202** on first hit while GitHub computes. Loader retries with exponential backoff (2s, 4s, 8s, give up).

---

## 6. End-to-End Data Flow

### Example A — single-repo dep-health

> **User:** *"Is `tanstack/query` still actively maintained?"*

1. `plan_data_load(question=...)` → `{repos: ["tanstack/query"], entities: [...all 5...], range: 2025-11-20..2026-05-20}`
2. `check_coverage(...)` → `{cached: false}` — Claude tells user "loading, ~15s"
3. `load_repo("tanstack/query", entities=[...], range="6mo")` fires loaders in parallel:
   - PRs: `GET /repos/tanstack/query/pulls?state=all&per_page=100` × N pages → 287 rows
   - Issues: similar → 412 rows
   - Releases: 1 call → 38 rows
   - Commit activity: 1 call → 52 rows
   - Contributors: 1 call → 73 rows
   - Total: ~14 API calls, returns `{fetched: {...}, api_calls: 14, rate_limit_remaining: 4986, cached_at: ...}`
4. `run_sql("SELECT ... maintenance signals ...")` → one row of aggregated facts
5. Claude synthesizes: *"Yes, tanstack/query is actively maintained. 47 contributors in last 6 months, last release 12 days ago, PRs typically merge in ~3 days, 387 commits in last 90 days."*

**Wall-clock:** ~10–15s first time, <1s on all follow-ups.

### Example B — cross-repo compare (the killer demo)

> **User:** *"Compare maintainership of react-query, swr, and tanstack-query"*

1. `plan_data_load` → `{repos: [3 repos], entities: [...], range: 6mo}`
2. Claude fires `load_repo` three times **in parallel** — rows from all three land in same tables, partitioned by `repo` column.
3. `run_sql("SELECT repo, ... GROUP BY repo ...")` → three rows side-by-side.
4. Claude synthesizes the verdict.

**Wall-clock:** ~20s first time, <1s on follow-ups.

### What this flow proves

1. Cross-repo comparison falls out for free from the `repo` column partitioning.
2. Follow-up questions are instant (no API calls).
3. Parallel loads keep multi-repo time roughly constant.
4. The LLM does narrative synthesis; tools return facts.

---

## 7. Auth, Errors, and Safety

### Auth — token discovery

Read `GITHUB_TOKEN` from env at server startup. Fallback chain:

```
1. GITHUB_TOKEN env var                          ← preferred
2. ~/.config/gh/hosts.yml (gh CLI's token)       ← convenient fallback
3. None — unauthed mode with loud warning        ← 60/hr limit
```

README recommends a **fine-grained PAT with "Public repositories — Read"** scope: essentially harmless even if leaked.

### Rate-limit budget (real math)

| Scenario | API calls | Within 5000/hr budget |
|---|---|---|
| Single-repo question | ~15 | 333 such questions/hr |
| Cross-repo compare (3 repos) | ~45 | 111/hr |
| Cross-repo compare (10 repos) | ~150 | 33/hr |
| Follow-up on loaded data | **0** | Infinite |
| Whole-`package.json` audit (50 deps) | ~750 | 6/hr |

Comfortable margin for any realistic single-user workflow.

### Error matrix

| Condition | Behavior |
|---|---|
| **401** (bad token) | Fail loud — "your `GITHUB_TOKEN` is invalid or expired" |
| **403 + rate-limited** (`x-ratelimit-remaining: 0`) | Surface `reset_at`, no retry, return partial results |
| **403 + abuse-detected** | Honor `Retry-After`, single retry, then fail |
| **404** | Fail with clear message — distinguish "doesn't exist" vs "private, need scope" |
| **422** | Fail with API error body — likely planner bug |
| **202** (stats computing) | Retry with backoff: 2s, 4s, 8s, give up after 3 |
| **5xx / timeout** | Retry with backoff: 1s, 2s, 4s, give up after 3 |
| **Partial pagination failure** | Commit pages we got, mark snapshot partial, surface count |

**Principle:** partial success is OK and explicit. User can `refresh_repo` to retry.

### `run_sql` safety

1. **Parse-level allowlist:** only `SELECT` / `WITH` statements pass.
2. **Connection mode:** SQLite opened with `mode=ro` URI param — connection can't write.
3. **Row cap:** hard-coded `LIMIT 1000` wrapper.
4. **Statement timeout:** 30-second wall.
5. **No `ATTACH DATABASE`, no `PRAGMA`** — filtered at parse time.

Errors returned structured so the LLM can self-correct (planner→actor→judge loop, same pattern as cityops).

### Input validation

- `repo`: regex `^[\w.-]+/[\w.-]+$`, max 100 chars
- `range`: `"6mo"` / `"30d"` / `"1y"` / `"all"` / explicit ISO date pair
- `entities`: must be subset of the 5 known
- `max_rows_per_entity`: clamp to `[1, 5000]`

### Logging & diagnostics

`--debug` flag enables verbose stderr logging (off by default — MCP clients don't want noise):

```
[load_repo] tanstack/query → fetching prs (range 2025-11-20..2026-05-20)
[github_client] GET /repos/tanstack/query/pulls?... → 200 (47ms, 100 rows, rate_remaining=4994)
[load_repo] tanstack/query → wrote 287 prs, 412 issues, 38 releases (14 API calls, 9.2s)
```

### `load_repo` response shape

Every response includes a rate-limit summary so the LLM (and user) can see budget:

```json
{
  "repo": "tanstack/query",
  "fetched": { "prs": 287, "issues": 412, "releases": 38, "commit_activity": 52, "contributors": 73 },
  "api_calls_used": 14,
  "rate_limit_summary": {
    "remaining": 4986,
    "resets_in_minutes": 47,
    "warning": null
  },
  "cached_at": "2026-05-20T22:55:00Z"
}
```

When `remaining < 500`, `warning` populates so the LLM can warn the user before another big load.

---

## 8. Testing & Packaging

### Testing strategy

| Layer | What | Tools | When |
|---|---|---|---|
| **Unit** | Loader JSON parsing, SQL builder, planner output validation | `pytest` + recorded JSON fixtures | Every commit (<1s) |
| **Integration** | One loader actually hits `api.github.com` for `octocat/Hello-World` | `pytest` + real network | CI on main + nightly |
| **End-to-end** | Full MCP flow against `tanstack/query` | `pytest` + MCP test client | Pre-release manual + nightly |

**Fixtures:** record GitHub responses for `octocat/Hello-World` and `tanstack/query` once, commit JSON to `tests/fixtures/`. Re-record yearly or on API drift.

**Not tested:** rate-limit exhaustion in CI (synthetic 403 unit test instead); LLM planner accuracy (model concern, not ours).

### Project structure

```
repohealth-mcp/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE
├── .python-version
├── src/repohealth_mcp/
│   ├── __init__.py
│   ├── server.py               # FastMCP server, registers tools/resources/prompts
│   ├── github_client.py        # HTTP client (auth, pagination, retries, rate-limit tracking)
│   ├── planner.py              # NL → fetch plan (uses LLM)
│   ├── database.py             # SQLite connection mgmt, schema, UDFs
│   ├── coverage.py             # snapshot table logic
│   ├── loaders/
│   │   ├── __init__.py
│   │   ├── base.py             # shared pagination + retry + UPSERT helpers
│   │   ├── prs.py
│   │   ├── issues.py
│   │   ├── releases.py
│   │   ├── commit_activity.py
│   │   └── contributors.py
│   └── tools/
│       ├── plan_data_load.py
│       ├── check_coverage.py
│       ├── load_repo.py
│       ├── refresh_repo.py
│       ├── run_sql.py
│       ├── get_loaded_tables.py
│       └── list_loaded_repos.py
├── tests/
│   ├── fixtures/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-05-20-repohealth-mcp-design.md   ← this file
```

### `pyproject.toml` (key fields)

```toml
[project]
name = "repohealth-mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.0.0",
    "httpx>=0.27",
    "google-genai>=0.3",
    "platformdirs>=4.0",
]

[project.scripts]
repohealth-mcp = "repohealth_mcp.server:main"
```

**SQLite file location:** `platformdirs.user_data_dir("repohealth-mcp") / "repohealth.sqlite"` — cross-platform user-data dir, same as cityops.

### Install UX (README one-liner)

```bash
# Claude Code
claude mcp add repohealth -s user -- \
  uvx --from git+https://github.com/brycekan123/repohealth-mcp repohealth-mcp

# Codex CLI
codex mcp add repohealth -- \
  uvx --from git+https://github.com/brycekan123/repohealth-mcp repohealth-mcp
```

Plus one extra step beyond cityops:

```bash
export GITHUB_TOKEN=$(gh auth token)
```

(Documented loudly — it's the only material UX difference.)

### CI — GitHub Actions

| Workflow | Trigger | What |
|---|---|---|
| `ci.yml` | PR + push to main | Lint (`ruff`), unit, integration, build wheel |
| `nightly.yml` | Cron daily | Full e2e, refresh fixtures, alert on API shape drift |

### Versioning

Semver. Start at `0.1.0`. Tag `v0.1.0` once first public install works end-to-end.

### Docker

**Skipped for v1.** MCP servers run locally via `uvx`; Docker adds friction without value for the primary install path. Add later if there's demand.

---

## 9. Deferred to v2

Explicit out-of-scope for v1:

- **ETag conditional requests** — 304 responses don't count against rate limit; cleanest invalidation
- **TTL / background refresh policies** — auto-expire snapshots after N hours
- **GraphQL endpoint** — compound queries count cheaper than equivalent REST sequences
- **Webhook-based real-time invalidation** — for active repos that change minute-to-minute
- **Private repo support** — works incidentally if user's token has scope, but not documented or tested
- **Raw `commits` table** — sha-level commit detail; for v1, `commit_activity` + `contributors` (stats) suffice
- **PR review-times** — fetching reviews per PR is +500 calls per repo; defer until needed
- **Docker image** — local `uvx` install is the primary path

---

## 10. Risks & Open Questions

### Risks

1. **GitHub API shape drift.** Mitigated by nightly e2e + fixture refresh alerts. Severity: low (GitHub is conservative with breaking changes).
2. **`/stats/*` 202 retries fail.** First-fetch on a never-queried repo can stall. Mitigated by 3-attempt backoff; loader returns partial snapshot with a clear note. Severity: medium.
3. **Cache staleness in long sessions.** Snapshot age grows during long conversations; user may unknowingly answer with old data. Mitigated by `cached_at` in every response. Severity: low for v1's intended use cases.
4. **Rate-limit exhaustion under audit-style use.** A user analyzing 100+ deps in one session could approach 1500+ calls. Within budget but no headroom. Mitigated by `rate_limit_summary` warnings. Severity: low.
5. **SQL injection via `run_sql`.** Mitigated by read-only mode + parse-level allowlist + statement timeout. Severity: very low (the connection itself can't write).

### Open questions (for future iteration, not blocking v1)

- Should the `dep_health_query` prompt produce a single rolled-up "health score" (0–100) or just return raw signals? *Lean toward raw signals — let the LLM narrate.*
- Should `list_loaded_repos` show stale snapshots distinctly (e.g., "loaded > 1 hr ago")? *Probably yes, low cost to add.*
- Do we need an opt-in `load_repo_reviews` tool that fetches PR review timelines on demand for users who specifically want first-response metrics? *Defer to v2 based on user feedback.*

---

## 11. Implementation Checklist (for the plan-writing phase)

Order of build:

1. Project scaffold (`pyproject.toml`, src layout, empty modules)
2. `database.py` — schema, UPSERT helpers, `median()` UDF
3. `github_client.py` — httpx wrapper with auth, pagination, retries, rate-limit headers
4. `loaders/base.py` — shared pagination loop, snapshot bookkeeping
5. One loader end-to-end (`releases.py` — smallest, simplest)
6. Remaining four loaders
7. `coverage.py` and `check_coverage` tool
8. `load_repo` and `refresh_repo` tools
9. `planner.py` — LLM call, structured-output parsing
10. `run_sql` tool with safety layer
11. `get_loaded_tables`, `list_loaded_repos`
12. Resources (`repo://schema`, `repo://signals`)
13. Prompts (5 SQL scaffolds)
14. `server.py` — FastMCP wiring
15. Tests (unit → integration → e2e)
16. README + install instructions
17. CI workflows
18. Tag `v0.1.0`

---

**End of spec.**
