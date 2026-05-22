# repohealth-mcp

A custom Model Context Protocol (MCP) server for GitHub repository analytics. It loads public GitHub signals into a local SQLite database, then lets MCP clients answer repo-health questions by generating read-only SQL over cached data instead of repeatedly fetching the same API slices.

It covers PRs, issues, releases, commits, contributors, dependency SBOMs, CI workflow runs, star history, funding metadata, PR reviews, inline review comments, per-commit file diffs, cache freshness, cross-repo comparisons, and author activity.

```text
is tanstack/query still actively maintained?
compare axios/axios, sindresorhus/ky, and node-fetch/node-fetch
release cadence for vercel/next.js over the last year
who are the top contributors to facebook/react this quarter?
which files are hotspots in tanstack/query lately?
what is the CI pass rate for vercel/next.js?
what has sindresorhus been working on across his repos?
which authors maintain all of kubernetes/kubernetes, helm/helm, and istio/istio?
```

Works with any public GitHub repo.

## Architecture

The core idea is a stateful analytics layer for MCP clients: fetch GitHub data once, store it in SQLite, and answer follow-up questions with SQL.

```text
User question
  -> MCP client (Claude Code / Codex CLI)
  -> repohealth-mcp over stdio
  -> plan_data_load(question)              optional NL -> repos/entities/range
  -> check_coverage(repo, entity, range)   cache hit, miss, or stale
  -> load_repo / load_repos / load_author_activity when data is missing
  -> GitHub REST API                       auth, retries, pagination, 202 backoff
  -> local SQLite database                 partitioned by repo
  -> run_sql(query)                        read-only SELECT/WITH with pagination
  -> LLM answer from SQL rows
```

For cross-repo checks, call `load_repos` with a list of repos and compare them with SQL. For author activity, call `load_author_activity`; if `repos` is omitted, repohealth discovers recently touched repos through GitHub commit search, bounded by `max_repos` and the requested date range.

Cached slices are tracked by `(repo, entity, range_start, range_end)` and marked stale after 7 days. Follow-up queries over fresh cached slices can run from SQLite; call `refresh_repo` when a slice is stale or you want the latest GitHub state.

`pr_reviews`, `pr_review_comments`, and `commit_files` are opt-in because they fan out one API call per cached parent PR or commit. Parent entities are loaded first, and dependent loaders are skipped if their parent load fails.

## Install

Get `uv` if you do not have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Export a token for the 5000/hr GitHub rate limit. Unauthenticated requests are limited to 60/hr.

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

### Codex CLI

```bash
codex mcp add repohealth -- uvx --from git+https://github.com/brycekan123/repohealth-mcp repohealth-mcp
```

Verify with `codex mcp list`.

## Tools

| Tool | Purpose |
|---|---|
| `plan_data_load` | Parse a natural-language question into repos, entities, date range, and optional author. Requires `GEMINI_API_KEY`; load tools can be called directly without it. |
| `check_coverage` | Check whether a repo/entity/range slice is cached, how old it is, and whether it is stale. |
| `load_repo` | Fetch GitHub signals for one repo into SQLite. |
| `load_repos` | Load multiple repos in parallel for cross-repo comparison. |
| `load_author_activity` | Load a GitHub user's recent activity across explicit or discovered repos. |
| `search_repos` | Search GitHub repos before loading them. |
| `refresh_repo` | Drop cached rows for a slice and fetch it again. |
| `run_sql` | Query cached signals with read-only `SELECT` or `WITH`; defaults to 200 rows and supports `offset` pagination. |
| `get_loaded_tables` | List local tables, columns, and row counts. |
| `list_loaded_repos` | List cached `(repo, entity, range)` snapshots. |

Resources:

- `repo://schema` returns the SQLite table definitions.
- `repo://signals` returns canonical SQL recipes for activity, merge time, release cadence, bus factor, active maintainers, backlog, commits by author, CI pass rate, stars growth, dependency licenses, review responsiveness, file hotspots, review-comment volume, author commits across repos, author review load, and org active maintainers.

Prompts cover dependency health, repo comparison, release cadence, responsiveness, contributor health, commit history, CI health, dependency audit, star trajectory, review responsiveness, file hotspots, review-comment volume, author activity, maintainer overlap, and cross-repo activity comparison.

## Data Model

One SQLite file per user, partitioned by a `repo` column so cross-repo SQL can run in one query.

| Table | Source | Grain |
|---|---|---|
| `repos` | `/repos/{owner}/{name}` + `.github/FUNDING.yml` | one row per repo |
| `prs` | `/pulls` | one row per PR |
| `issues` | `/issues` (PRs filtered out) | one row per issue |
| `releases` | `/releases` | one row per release |
| `commit_activity` | `/stats/commit_activity` | one row per repo-week |
| `contributors` | `/stats/contributors` | one row per repo-author-week |
| `commits` | `/commits` | one row per commit |
| `commit_files` | `/commits/{sha}` | one row per file touched per commit |
| `pr_reviews` | `/pulls/{n}/reviews` | one row per review |
| `pr_review_comments` | `/pulls/{n}/comments` | one row per inline review comment |
| `dependencies` | `/dependency-graph/sbom` | one row per package |
| `star_history` | `/stargazers` with star media type | one row per star event |
| `workflow_runs` | `/actions/runs` | one row per CI run |
| `author_searches` | bookkeeping | one row per author discovery window |
| `snapshots` | bookkeeping | one row per cached `(repo, entity, range)` slice |

A `median()` aggregate UDF is registered for SQL.

Snapshot location: `~/Library/Application Support/repohealth-mcp/repohealth.sqlite` on macOS, with platform-appropriate paths elsewhere.

## GitHub Token

| Mode | Limit |
|---|---|
| Authenticated (`GITHUB_TOKEN`) | 5000 req/hr |
| Unauthenticated | 60 req/hr |

A fine-grained PAT with public-repo read access is enough. Each `load_repo` response includes a `rate_limit_summary`.
