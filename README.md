# repohealth-mcp

A Model Context Protocol (MCP) server that answers **dep-health and repo-analytics** questions about public GitHub repos. It plans → fetches → caches GitHub data into a local SQLite snapshot, then runs read-only SQL aggregations on it.

```text
is tanstack/query still actively maintained?
compare react-query, swr, and tanstack-query
release cadence for vercel/next.js over the last year
who are the top contributors to facebook/react this quarter?
```

Works with any public GitHub repo.

## Install

Get `uv` if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Export a token for the 5000/hr GitHub rate limit (vs 60/hr unauthenticated):

```bash
export GITHUB_TOKEN=$(gh auth token)
```

### Claude Code

```bash
claude mcp add repohealth -s user -- uvx --from git+https://github.com/brycekan123/repohealth-mcp repohealth-mcp
```

Verify with `claude mcp list`, then open a new session and ask:

```text
is tanstack/query still actively maintained?
```

> Paste the `claude mcp add` command on a single line — terminal soft-wraps can register a truncated entry. If that happens, run `claude mcp remove repohealth -s user` and retry.

### Codex CLI

```bash
codex mcp add repohealth -- uvx --from git+https://github.com/brycekan123/repohealth-mcp repohealth-mcp
```

Verify with `codex mcp list`.

## How it works

The server exposes four MCP surfaces that a client uses in sequence:

1. **`plan_data_load(question)`** — LLM parses NL into `{repos, entities, range}`.
2. **`check_coverage(repo, entity, range)`** — does the local snapshot already cover this slice?
3. **`load_repo(repo, entities, range)`** — fetch what's missing from GitHub into local SQLite.
4. **`run_sql(query)`** — read-only `SELECT` / `WITH` against the snapshot (1000-row cap).

Follow-up questions on the same repo skip GitHub entirely. Call `refresh_repo` to force-refetch.

## Tools

| Tool | Purpose |
|---|---|
| `plan_data_load` | NL question → repos, entities, date range |
| `check_coverage` | Is `(repo, entity, range)` already cached locally? |
| `load_repo` | Fetch missing data from GitHub into local SQLite |
| `refresh_repo` | Drop cached rows for a slice and re-load |
| `run_sql` | Read-only `SELECT` / `WITH` against the snapshot (1000-row cap) |
| `get_loaded_tables` | Current tables, columns, row counts |
| `list_loaded_repos` | All cached `(repo, entity, range)` snapshots |

**Resources:** `repo://schema`, `repo://signals` (canonical SQL recipes for activity, merge time, release cadence, bus factor, active maintainers, backlog).

**Prompts:** `dep_health_query`, `compare_repos_query`, `release_cadence_query`, `responsiveness_query`, `contributor_health_query`.

## Data model

One SQLite file per user, partitioned by a `repo` column so cross-repo SQL is free:

| Table | Source | Grain |
|---|---|---|
| `repos` | `/repos/{owner}/{name}` | one row per repo |
| `prs` | `/pulls` | one row per PR |
| `issues` | `/issues` (PRs filtered out) | one row per issue |
| `releases` | `/releases` | one row per release |
| `commit_activity` | `/stats/commit_activity` | one row per repo-week |
| `contributors` | `/stats/contributors` | one row per repo-author-week |
| `snapshots` | bookkeeping | one row per `(repo, entity, range)` slice |

A `median()` aggregate UDF is registered for SQL.

Snapshot location: `~/Library/Application Support/repohealth-mcp/repohealth.sqlite` on macOS (platform-appropriate elsewhere).

## GitHub token

| Mode | Limit |
|---|---|
| Authenticated (`GITHUB_TOKEN`) | 5000 req/hr |
| Unauthenticated | 60 req/hr — useful only for tiny experiments |

A fine-grained PAT with public-repo read access is enough. Each `load_repo` response includes a `rate_limit_summary`.

## Examples

```text
Is vercel/next.js still actively maintained?
I'm picking between react-query, swr, and tanstack-query. Which is best maintained?
What's the median PR review time for facebook/react in the last 6 months?
How often does microsoft/vscode release?
Show me the top 10 contributors to django/django this year.
```

## Development

```bash
uv sync --all-extras
uv run pytest                                 # 122 unit + e2e tests
GITHUB_TOKEN=$(gh auth token) uv run pytest -m integration   # hits real GitHub
uv run ruff check src tests
```

## License

MIT
