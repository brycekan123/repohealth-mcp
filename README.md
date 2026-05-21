# repohealth-mcp

A Model Context Protocol (MCP) server that answers **dep-health and repo-analytics** questions about public GitHub repos. It plans → fetches → caches GitHub data into a local SQLite snapshot, then runs read-only SQL aggregations on it.

It covers the usual maintenance signals (PRs, issues, releases, commit activity, contributors) plus commit metadata, per-commit file diffs, PR reviews, inline review comments, dependency SBOMs, star history, workflow runs, funding metadata, and cache freshness.

```text
is tanstack/query still actively maintained?
compare axios/axios, sindresorhus/ky, and node-fetch/node-fetch
release cadence for vercel/next.js over the last year
who are the top contributors to facebook/react this quarter?
which files are hotspots in tanstack/query lately?
what is the CI pass rate for vercel/next.js?
is gaearon still shipping code lately?
what has sindresorhus been working on across his repos?
compare maintainer activity across rails/rails, django/django, and laravel/laravel
which authors maintain all of kubernetes/kubernetes, helm/helm, and istio/istio?
```

Works with any public GitHub repo.

## 🛠 Install

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

### Codex CLI

```bash
codex mcp add repohealth -- uvx --from git+https://github.com/brycekan123/repohealth-mcp repohealth-mcp
```

Verify with `codex mcp list`.

## ⚡ How it works

The server exposes MCP surfaces that a client uses in sequence:

1. **`plan_data_load(question)`** — LLM parses NL into `{repos, entities, range, author}`.
2. **`check_coverage(repo, entity, range)`** — does the local snapshot already cover this slice, and is it stale?
3. **`load_repo(repo, entities, range)`** — fetch what's missing from GitHub into local SQLite.
4. **`load_repos(...)` / `load_author_activity(...)`** — fan out across repos or discover a user's active repos.
5. **`run_sql(query)`** — read-only `SELECT` / `WITH` against the snapshot (1000-row cap).

Follow-up questions on the same repo skip GitHub entirely. Call `refresh_repo` to force-refetch.

## 🧰 Tools

| Tool | Purpose |
|---|---|
| `plan_data_load` | NL question → repos, entities, date range |
| `check_coverage` | Is `(repo, entity, range)` cached locally, how old is it, and is it stale? |
| `load_repo` | Fetch missing data from GitHub into local SQLite |
| `load_repos` | Fan-out version of `load_repo` — load multiple repos in parallel |
| `load_author_activity` | Load a GitHub user's recent activity across one or many repos; discovers repos automatically via `/search/commits` by default |
| `search_repos` | Wrap GitHub `/search/repositories` for repo discovery before loading |
| `refresh_repo` | Drop cached rows for a slice and re-load |
| `run_sql` | Read-only `SELECT` / `WITH` against the snapshot (1000-row cap) |
| `get_loaded_tables` | Current tables, columns, row counts |
| `list_loaded_repos` | All cached `(repo, entity, range)` snapshots |

**Resources:** `repo://schema`, `repo://signals` (canonical SQL recipes for activity, merge time, release cadence, bus factor, active maintainers, backlog, commits by author, CI pass rate, stars growth, dependency licenses, review responsiveness, file hotspots, review-comment volume, author commits across repos, author review load, and org active maintainers).

**Prompts:** `dep_health_query`, `compare_repos_query`, `release_cadence_query`, `responsiveness_query`, `contributor_health_query`, `commit_history_query`, `ci_health_query`, `dep_audit_query`, `star_trajectory_query`, `review_responsiveness_query`, `file_hotspots_query`, `review_comment_volume_query`, `author_activity_query`, `maintainer_overlap_query`, `compare_repos_activity_query`.

## 🗄 Data model

One SQLite file per user, partitioned by a `repo` column so cross-repo SQL is free:

| Table | Source | Grain |
|---|---|---|
| `repos` | `/repos/{owner}/{name}` + `.github/FUNDING.yml` | one row per repo |
| `prs` | `/pulls` | one row per PR |
| `issues` | `/issues` (PRs filtered out) | one row per issue |
| `releases` | `/releases` | one row per release |
| `commit_activity` | `/stats/commit_activity` | one row per repo-week |
| `contributors` | `/stats/contributors` | one row per repo-author-week |
| `commits` | `/commits` | one row per commit |
| `commit_files` | `/commits/{sha}` | one row per file touched per commit (opt-in) |
| `pr_reviews` | `/pulls/{n}/reviews` | one row per review (opt-in) |
| `pr_review_comments` | `/pulls/{n}/comments` | one row per inline review comment (opt-in) |
| `dependencies` | `/dependency-graph/sbom` | one row per package |
| `star_history` | `/stargazers` (star+json) | one row per star event |
| `workflow_runs` | `/actions/runs` | one row per CI run |
| `author_searches` | bookkeeping | one row per author discovery window |
| `snapshots` | bookkeeping | one row per `(repo, entity, range)` slice |

A `median()` aggregate UDF is registered for SQL.

Snapshot location: `~/Library/Application Support/repohealth-mcp/repohealth.sqlite` on macOS (platform-appropriate elsewhere).

## 🏗 Architecture

The agentic pipeline from a natural-language question to a cited answer:

```
                           User question
                                │
                                ▼
        ┌───────────────────────────────────────────────┐
        │   MCP client  (Claude Code / Codex CLI)       │
        └───────────────────────────────────────────────┘
                                │  JSON-RPC over stdio
                                ▼
   ┌─────────────────────────────────────────────────────────────┐
   │   repohealth-mcp server  (FastMCP, stdio)                   │
   │                                                             │
   │   1.  plan_data_load(question)                              │
   │         └─► Gemini → { repos, entities, range_spec, author }│
   │                                                             │
   │   2.  check_coverage(repo, entity, range)                   │
   │         └─► SELECT from snapshots → hit / miss              │
   │                                                             │
   │   3.  load_repo(repo, entities, range)        [on miss]     │
   │         ├─► repo_meta + funding loader                      │
   │         └─► ThreadPoolExecutor  (parallel phases)           │
   │               ├─► prs / issues / releases                   │
   │               ├─► commit_activity / contributors            │
   │               ├─► commits / dependencies / stars / CI       │
   │               └─► opt-in dependent loaders                  │
   │                    (commit_files, reviews, review comments) │
   │                              │                              │
   │                              ▼                              │
   │                    GitHub REST API                          │
   │                    (auth, retries, 202 backoff, pagination) │
   │                          ▼                                  │
   │                  Local SQLite snapshot                      │
   │                  (one file, partitioned by repo)            │
   │                                                             │
   │   4.  load_repos / load_author_activity                     │
   │         └─► multi-repo fan-out or author repo discovery      │
   │                                                             │
   │   5.  run_sql(query)                                        │
   │         └─► read-only SELECT / WITH  →  rows                │
   └─────────────────────────────────────────────────────────────┘
                                │
                                ▼
            LLM composes the answer from the SQL rows
```

`pr_reviews`, `pr_review_comments`, and `commit_files` are opt-in. Include them in `entities=[...]` explicitly when calling `load_repo`. Each fans out one API call per cached parent row, so `load_repo` stages parent loaders first (`prs` or `commits`) and then runs dependent loaders concurrently. If a requested parent fails, its dependent entity is skipped rather than writing a misleading fresh snapshot from stale parent rows.

**Walk-through — `is tanstack/query still actively maintained?`**

1. `plan_data_load` →
   ```json
   { "repos": ["tanstack/query"],
     "entities": ["prs","issues","releases","commit_activity","contributors"],
     "range_spec": "6mo" }
   ```
2. `check_coverage("tanstack/query", "prs", "2025-11-21", "2026-05-21")` → miss, or hit with `age_seconds` / `stale`.
3. `load_repo(...)` opens a fresh `GitHubClient` and one SQLite connection per worker. Entity loaders run concurrently where possible: PRs and issues paginate `sort=created&direction=desc` and break at the range boundary; `/stats/*` endpoints handle `202 still computing` with bounded retries; commit metadata, dependencies, stars, workflow runs, reviews, review comments, file diffs, and funding metadata plug into the same cache. Loader failures land in `result["errors"]` without aborting the whole load.
4. `run_sql` opens a read-only connection (URI `mode=ro`), enforces a `SELECT`/`WITH` allowlist + denylist for `INSERT/UPDATE/DELETE/DROP/ATTACH/PRAGMA`, runs the query, and caps the result at 1000 rows.
5. The LLM turns the rows into prose, citing the signals it used.

**Follow-up questions** on the same `(repo, entity, range)` skip step 3 entirely — `check_coverage` is a hit and `run_sql` answers from local SQLite in milliseconds.

## 🔐 GitHub token

| Mode | Limit |
|---|---|
| Authenticated (`GITHUB_TOKEN`) | 5000 req/hr |
| Unauthenticated | 60 req/hr — useful only for tiny experiments |

A fine-grained PAT with public-repo read access is enough. Each `load_repo` response includes a `rate_limit_summary`.

## 📄 License

MIT
