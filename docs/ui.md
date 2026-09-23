# vmn ui

`vmn ui` serves a web dashboard and REST API over your vmn repos and experiment
stores. Reads go straight to git tags and `.vmn/` files (or S3) — lock-free and
always consistent with the CLI. Mutations run as real `vmn` subprocesses.

## Install

The UI ships inside the wheel but pulls in a couple of extra runtime deps, so it
lives behind an extra:

```sh
pip install "vmn[ui]"
```

Without the extra, `vmn ui` prints an install hint and exits.

## Localhost

```sh
cd your-project
vmn ui                     # 127.0.0.1:8265, auto-attaches this repo, opens a browser
vmn ui --port 9000 --no-browser
```

The current repo becomes an implicit workspace. Open the printed URL.

## Workspaces

A **workspace** is an isolated source of data:

- a **git checkout** — its own working tree, `.vmn/`, lock, and derived index; or
- a read-only **S3** experiment bucket.

The server hosts many. Several git workspaces may be clones of the *same* remote
(e.g. one per branch or per user) — a stamp or restore in one never touches
another's working tree.

Register sources at startup:

```sh
vmn ui --data-dir /srv/vmn-ui \
       --repo /srv/checkouts/model-a \
       --repo /srv/checkouts/model-b \
       --s3-bucket team-experiments --s3-prefix ml --endpoint-url http://minio:9000
```

or at runtime via the API (`POST /api/v1/workspaces` with `{"name","path"}`).
The registry persists in `<data-dir>/workspaces.yml` (default `~/.vmn-ui`).

### S3-only (no git repo)

```sh
vmn ui --s3-bucket team-experiments --s3-prefix ml
```

Experiment browsing (leaderboards, run detail, artifacts) works with no local
checkout. Repo actions (stamp/goto) are naturally unavailable for S3 sources.

## Remote deployment

```sh
vmn ui --host 0.0.0.0 --port 8265 --token "$VMN_UI_TOKEN" --data-dir /srv/vmn-ui
```

- **Auth**: a single shared bearer token (`--token` or the `VMN_UI_TOKEN` env).
  Every `/api` request must send `Authorization: Bearer <token>`. Binding beyond
  localhost without a token logs a warning.
- **TLS & users**: put a reverse proxy (nginx/Caddy) in front — vmn does not
  terminate TLS or manage accounts.
- **`--read-only`**: disables all mutation endpoints (stamp/restore/goto/…),
  returning 403. Good for a shared read-only dashboard.
- **Host allowlist**: without a token, `/api` answers only requests whose `Host`
  is `localhost`, `127.0.0.1`, `[::1]`, the `--host` you bound (unless it is a
  wildcard like `0.0.0.0`) or an `--allowed-host` (repeatable; `*` allows any).
  Anything else gets 403. This stops a DNS-rebinding page from reaching a
  token-less server on your machine. With `--token` set, Host is not checked.
- **Cross-site writes**: a POST/PUT/PATCH/DELETE whose `Origin` (or `Referer`,
  when there is no Origin) names a different site than the request's `Host` is
  refused with 403, unless that site is an `--allowed-host`. Mutating requests
  must also send `Content-Type: application/json` (415 otherwise), so a page on
  another site cannot trigger `vmn release` with a plain form or `no-cors` fetch.
  Clients that send neither header (curl, scripts) are unaffected.
- **Paths**: app names and versions in URLs are validated (400 on `..` segments
  and the like), and the SPA fallback only serves files inside the bundled
  `static/` directory.
- **Jobs**: each action has stdin closed and is failed after 30 minutes, which
  frees its workspace. The server remembers the last 200 jobs and the last 1 MB
  of each job's log.

Behind a proxy that rewrites `Host`, or when users reach the server by a name
other than `--host`, list that name:

```sh
vmn ui --host 0.0.0.0 --allowed-host vmn.example.com --token "$VMN_UI_TOKEN"
```

Example nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8265;
    proxy_set_header Host $host;
}
```

## Actions

Mutations are asynchronous jobs:

1. `POST /api/v1/workspaces/{ws}/apps/{app}/actions/{stamp|restore|goto|release|prune|note}`
   with a JSON body → `202` + `{"id": ...}`.
2. `GET /api/v1/jobs/{id}` → status (`running`/`succeeded`/`failed`), exit code,
   and the captured log.

Each job runs `vmn <cmd>` as a subprocess in the workspace, so it acquires the
per-repo lock (serializing correctly against terminal use) and at most one
mutation runs per workspace at a time. Restores/gotos over a dirty tree
auto-snapshot your work first (the safety net) — the job log tells you the
recovery command.

## The index

By default the server keeps a small SQLite cache under `<data-dir>/index/` to
make leaderboards and the stamp tree instant over large repos. It is derived
from the source files — delete it any time — and `--no-index` reads directly.

Experiments are indexed incrementally. Each leaderboard request lists the
experiment files once (sizes and mtimes) and re-reads only what moved: a new
run, a changed `metadata.yml`, the new bytes of a grown log, a rewritten
`run_state.yml` (a heartbeat). So a live run appending metrics, or a hundred
runs heartbeating, costs those files, not a re-read of every experiment. S3
workspaces get the same index in memory, keyed by bucket and prefix, so a poll
is one LIST plus the objects that changed (ranged GETs for grown logs). The
stamp tree is cached by the app's tag list.

## Run status in the dashboard

Every run row carries a color-coded status pill — `created`, `running`, `stuck`,
`succeeded`, `failed`. `running` pulses; `stuck` (a run whose heartbeat went
stale with no exit code — the node died and nothing recorded it) is flagged.
Inner runs are nested under their outer run, so a sweep collapses to one row
whose status is the rollup over its whole subtree. The page auto-refreshes while
anything is unfinished. See
[docs/experiments.md](experiments.md#run-status-did-my-job-die) for how the
statuses are derived.

## API

Full OpenAPI/Swagger docs at `/api/docs`. Everything is scoped by workspace:
`/api/v1/workspaces`, `.../apps`, `.../apps/{app}/experiments`,
`.../experiments/{verstr}`, `.../experiments-diff`, `.../versions`, `.../tree`,
`.../tree/root`, `.../deps`, `.../snapshots`, and `/api/v1/jobs/{id}`.

### Experiment status fields

Every experiment row from `GET .../apps/{app}/experiments` and the
`.../experiments/{verstr}` detail response carries:

| Field | Meaning |
|---|---|
| `status` | `created` / `running` / `stuck` / `succeeded` / `failed` (derived, never stored) |
| `exit_code` | the command's exit code once finished, else `null` |
| `started_at` / `finished_at` | ISO-8601 timestamps |
| `heartbeat` | last heartbeat refresh |
| `stale_sec` | seconds since the last heartbeat |
| `duration_sec` | wall-clock run time once finished |
| `pid` / `host` / `command` | what ran, where |
| `last_metric_at` | when a metric was last logged — use it to spot a run that is alive but no longer progressing |
| `parent` / `children` | verstrs linking outer and inner jobs |
| `kind` | `outer`, `inner` or `single` |
| `depth` | nesting depth, for indenting the list |
| `tree_status` | rollup over the run and its subtree (`failed > stuck > running > created > succeeded`) |

On the detail response these are also grouped under a top-level `status` object.

The list endpoint accepts a `status` query parameter (comma-separated) to filter:

```sh
curl -H "Authorization: Bearer $VMN_UI_TOKEN" \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments?status=running,stuck"
```

### Filtering with a query

The same endpoint takes `q`, an expression over the row fields, metrics and
params — the same [query language](sdk.md#the-query-language) the Python SDK's
`list_runs(query=...)` takes:

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'q=metrics.loss < 0.5 and params.optimizer = "adam"' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments"
```

- `q` and `status` compose as **and** when both are given.
- Filtering happens **before** pagination, so `offset`/`limit` page through the
  matches and the `total` in the response counts matches, not all runs.
- An invalid query is a **400** carrying the parser's message and character
  offset (`unknown field 'statuz' at offset 0`).

### Paging, sorting and order

`GET .../apps/{app}/experiments` takes `offset` and `limit` (capped at 1000
rows per response) and answers `{"rows": [...], "total": N}` when `limit` is
given — the dashboard always pages. `sort` is a metric name or `timestamp`
(newest first); `order=asc|desc` overrides the direction the metric's schema
goal implies. Runs without the metric stay last in either direction.

```sh
curl -H "Authorization: Bearer $VMN_UI_TOKEN" \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments?sort=loss&order=asc&limit=50"
```

### Run detail is bounded

`GET .../experiments/{verstr}` costs the same however long the run logged:

| Field | Meaning |
|---|---|
| `log_tail` | the newest 200 log entries |
| `log_total` | how many entries the log holds |
| `log` | same as `log_tail`; pass `include_log=1` to get the whole log |
| `series` | each metric thinned independently to at most `max_points` points (default 2000, max 20000) with min/max buckets, so spikes survive; first and last point always kept |
| `series_total` | `{metric: points before thinning}` |
| `patches` | which patch kinds the snapshot holds, read from its metadata flags |

Older log entries page through `GET .../experiments/{verstr}/log?offset=&limit=`,
which answers `{"entries": [...], "total": N}` oldest first.

Artifacts download from `GET .../experiments/{verstr}/artifacts/{name}` for
local and S3 workspaces alike; with a token set the request needs the
`Authorization` header like every other API call.
