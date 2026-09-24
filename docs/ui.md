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

Experiments are indexed incrementally: a refresh re-reads only what moved — a
new run, a changed `metadata.yml`, the new bytes of a grown log, a rewritten
`run_state.yml` (a heartbeat). So a live run appending metrics, or a hundred
runs heartbeating, costs those files, not a re-read of every experiment. S3
workspaces get the same index, keyed by bucket and prefix and persisted next to
the others (`<data-dir>/index/s3-*.sqlite`), so a restarted server does not
re-read every record; a refresh is a LIST plus the objects that changed (ranged
GETs for grown logs). The stamp tree, root topology and dependency graphs are
cached by the app's tag list, so they are recomputed only after a stamp.

### Background refresh

Requests never refresh the index themselves. Each app someone is looking at
(any experiment request within the last minute) gets a daemon thread that
refreshes its index about once a second; an app nobody asks about stops being
refreshed until the next request. A refresh lists record names and directory
signatures, the live (unfinished) runs and whatever changed recently; every
30 seconds it lists everything, which catches edits a signature cannot show. A
request serves the latest snapshot at once, so the dashboard is at most about a
second behind the files; only an app's very first request waits for its initial
load (fast when the index was persisted by an earlier run). A refresh that
fails — say the bucket is unreachable — is logged and the last snapshot keeps
being served.

A list, facets or run page then costs a slice of work memoized per index
generation: status, the run tree, filtering and sorting are derived once per
generation, paging is a slice. Live runs' status is re-derived once per
2-second bucket (so `stuck` shows within seconds), and only those rows move:
their ancestors' `tree_status` is rolled up again and they are re-filtered and
bisected into the cached order of the finished runs, so a poll while a run is
live costs O(live runs · log N), not a re-sort of every run (`last=` alone
still re-runs the full pipeline per bucket). The metrics schema is re-read only when the app's
`conf.yml` changes (its mtime or size). Run detail resolves
`latest`/`@N`/prefixes, the run tree and the subtree's run states from the
snapshot, without listing the storage. The app list (`.../apps`) is cached per
workspace for 5 seconds.

Embedding `create_app()` directly (tests, scripts) leaves the background
refresher off unless you pass `background_refresh=True`: every request then
refreshes the index first and sees every write made before it, at the cost of a
full listing per request.

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
`.../experiments/{verstr}`, `.../experiments-columns`, `.../experiments-facets`, `.../series`, `.../experiments-diff`, `.../versions`, `.../tree`,
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
given — the dashboard always pages. Without `limit` it answers a plain list of
at most 1000 rows from `offset`. `sort` is a metric name or `timestamp`
(newest first); `order=asc|desc` overrides the direction the metric's schema
goal implies. Runs without the metric stay last in either direction.

```sh
curl -H "Authorization: Bearer $VMN_UI_TOKEN" \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments?sort=loss&order=asc&limit=50"
```

Each list response carries an `ETag` derived from the index generation, the
query parameters and — while runs are live — the status time bucket. Send it
back as `If-None-Match`: an unchanged poll is an empty `304` that costs no row
work at all.

### Archived runs

Rows with a truthy `archived` field (soft-deleted runs) are left out of
`.../experiments`, `.../experiments-columns` and `.../experiments-facets` —
including their `total` — unless the request passes `archived=1`. Rows without
the field count as not archived. The flag is part of the ETag.

### Columns for whole-set charts

`GET .../apps/{app}/experiments-columns?keys=...` answers a few values per run
for every run the filters match, so a chart can plot all of them instead of
the loaded page:

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'keys=metrics.loss,params.lr,status' \
  --data-urlencode 'q=metrics.loss < 0.5' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments-columns?sort=loss"
```

```json
{"verstrs": ["...r0003", "...r0001"], "idx": [4, 2],
 "columns": {"metrics.loss": [0.1, 0.3], "params.lr": [0.01, "auto"], "status": ["succeeded", "running"]},
 "total": 2}
```

- `keys` is a comma list of `metrics.<k>`, `params.<k>`, `timestamp`, `status`
  and `name` (the row's `name`, else its `note`); any other key is a **400**.
  Every column is aligned with `verstrs`/`idx` (the `@N` storage index).
- Metric values are numbers or `null` (missing or non-finite); params are
  served verbatim.
- `q`, `status`, `sort`, `order` and `archived` mean what they mean on the list;
  the rows come in the list's order. `limit` (default 20000, at most 50000)
  caps the rows returned; `total` counts every match.
- Memoized per index snapshot (and status bucket while runs are live), with an
  `ETag`/`304` like the list.

### Facets

`GET .../apps/{app}/experiments-facets` answers the app's filter vocabulary,
computed once per index generation:

```json
{"branches": ["feat/x", "main"], "metric_keys": ["acc", "loss"], "param_keys": ["lr", "opt"], "total": 5000}
```

Every list is sorted; `metric_keys` includes numeric params (they fold into
`metrics`), `total` counts all runs. It carries an `ETag` like the other reads.

### Run detail is bounded

`GET .../experiments/{verstr}` costs the same however long the run logged:

| Field | Meaning |
|---|---|
| `log_tail` | the newest 200 log entries |
| `log_total` | how many entries the log holds |
| `log` | same as `log_tail`; pass `include_log=1` to get the whole log |
| `series` | each metric thinned independently to at most `max_points` points (default 2000, max 20000) with min/max buckets, so spikes survive; first and last point always kept. `keys=loss,acc` returns only those metrics, `series=0` none. A response carries at most 200,000 points in all: with many metrics, `max_points` is lowered for each |
| `series_total` | `{metric: points before thinning}` (restricted by `keys` like `series`) |
| `patches` | which patch kinds the snapshot holds, read from its metadata flags |

Older log entries page through `GET .../experiments/{verstr}/log?offset=&limit=`,
which answers `{"entries": [...], "total": N}` oldest first.

A live run's poll costs its new log lines: the server keeps each parsed log and,
when a local log file only grew, parses just the bytes appended since the last
poll. Detail and log responses carry an `ETag` and `Cache-Control: no-cache`;
send it back as `If-None-Match` and an unchanged answer is an empty `304`.

### Series for many runs

A comparison chart fetches the same metrics from many runs in one request:

```sh
curl -X POST -H "Content-Type: application/json" \
  -d '{"verstrs": ["1.0.0-dev.a", "1.0.0-dev.b"], "keys": ["loss"], "max_points": 500}' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/series"
```

→ `{"series": {verstr: {metric: [{"step", "ts", "value"}]}}, "series_total":
{verstr: {metric: n}}, "missing": [verstr, ...]}`. At most 200 runs per request;
`keys: null` means every metric. The runs share the 200,000-point cap. It is a
read, so `--read-only` servers answer it, but as a POST it needs
`Content-Type: application/json` and a same-site `Origin` like any other.

### Diffs

`GET .../experiments-diff?v=&to=` materializes both runs and diffs them. Results
are cached per pair (a changed record is diffed again), at most two diffs run
at once (a third waits, then gets `429`), and the text is capped at 2 MB —
`truncated: true` says it was cut. A record with no base commit (a git-free
experiment) answers `diff: null` with the reason in `diff_unavailable`.

Artifacts download from `GET .../experiments/{verstr}/artifacts/{name}` for
local and S3 workspaces alike (an S3 object is streamed straight through, never
staged on the server's disk); with a token set the request needs the
`Authorization` header like every other API call. Downloads are sent as stored
(never gzipped by the server) with an RFC 5987 `filename*` so any file name
survives.

### Caching and compression

JSON responses are rendered with `orjson` (part of the `ui` extra) and gzipped
at a moderate level. The web bundle's hashed `/assets/*` files are served with
`Cache-Control: public, max-age=31536000, immutable`; `index.html` and client
routes with `no-cache`. An unknown `/api/...` path is a JSON `404`.
