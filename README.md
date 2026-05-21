# repohealth-mcp

A Model Context Protocol (MCP) server that answers **dep-health and repo-analytics** questions about public GitHub repos. It plans → fetches → caches GitHub data into a local SQLite snapshot, then runs read-only SQL aggregations on it.

```text
is tanstack/query still actively maintained?
compare react-query, swr, and tanstack-query
release cadence for vercel/next.js over the last year
who are the top contributors to facebook/react this quarter?
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

The server exposes four MCP surfaces that a client uses in sequence:

1. **`plan_data_load(question)`** — LLM parses NL into `{repos, entities, range}`.
2. **`check_coverage(repo, entity, range)`** — does the local snapshot already cover this slice?
3. **`load_repo(repo, entities, range)`** — fetch what's missing from GitHub into local SQLite.
4. **`run_sql(query)`** — read-only `SELECT` / `WITH` against the snapshot (1000-row cap).

Follow-up questions on the same repo skip GitHub entirely. Call `refresh_repo` to force-refetch.

## 🧰 Tools

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

## 🗄 Data model

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
   │         └─► Gemini → { repos, entities, range_spec }        │
   │                                                             │
   │   2.  check_coverage(repo, entity, range)                   │
   │         └─► SELECT from snapshots → hit / miss              │
   │                                                             │
   │   3.  load_repo(repo, entities, range)        [on miss]     │
   │         ├─► repo_meta loader                                │
   │         └─► ThreadPoolExecutor  (5 workers, parallel)       │
   │               ├─► prs loader         ─┐                     │
   │               ├─► issues loader      ─┤                     │
   │               ├─► releases loader    ─┤── GitHub REST API   │
   │               ├─► commit_activity    ─┤   (auth, retries,   │
   │               └─► contributors       ─┘    202 backoff,     │
   │                          │                 pagination)      │
   │                          ▼                                  │
   │                  Local SQLite snapshot                      │
   │                  (one file, partitioned by repo)            │
   │                                                             │
   │   4.  run_sql(query)                                        │
   │         └─► read-only SELECT / WITH  →  rows                │
   └─────────────────────────────────────────────────────────────┘
                                │
                                ▼
            LLM composes the answer from the SQL rows
```

**Walk-through — `is tanstack/query still actively maintained?`**

1. `plan_data_load` →
   ```json
   { "repos": ["tanstack/query"],
     "entities": ["prs","issues","releases","commit_activity","contributors"],
     "range_spec": "6mo" }
   ```
2. `check_coverage("tanstack/query", "prs", "2025-11-21", "2026-05-21")` → miss.
3. `load_repo(...)` opens a fresh `GitHubClient` and one SQLite connection per worker. The five entity loaders run **concurrently**: PRs and issues paginate `sort=created&direction=desc` and break at the range boundary (no wasted pages); the two `/stats/*` endpoints handle `202 still computing` with bounded retries. Loader failures land in `result["errors"]` without aborting the whole load.
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
