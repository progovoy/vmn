# vmn-exp ui

`vmn-exp ui` serves a web dashboard and REST API over your vmn repos and experiment
stores. Reads go straight to git tags and `.vmn/` files (or S3) — lock-free and
always consistent with the CLI. Mutations run as real `vmn` subprocesses.

## Install

The UI ships inside the wheel but pulls in a couple of extra runtime deps, so it
lives behind an extra:

```sh
pip install "vmn-exp[ui]"
```

Without the extra, `vmn-exp ui` prints an install hint and exits.

## Localhost

```sh
cd your-project
vmn-exp ui                     # 127.0.0.1:8265, auto-attaches this repo, opens a browser
vmn-exp ui --port 9000 --no-browser
```

The current repo becomes an implicit workspace. Open the printed URL.

## Workspaces

A **workspace** is an isolated source of data:

- a **git checkout** — its own working tree, `.vmn/`, lock, and derived index; or
- a read-only experiment **store**: any store URI (`s3://`, `gs://`, `az://`,
  `file://`, plugin schemes — see
  [Storage](experiments.md#storage-local-s3-gcs-azure-plugins)).

The server hosts many. Several git workspaces may be clones of the *same* remote
(e.g. one per branch or per user) — a stamp or restore in one never touches
another's working tree.

Register sources at startup:

```sh
vmn-exp ui --data-dir /srv/vmn-ui \
       --repo /srv/checkouts/model-a \
       --repo /srv/checkouts/model-b \
       --store gs://team-experiments/ml
```

A custom S3 endpoint (MinIO, say) rides in the URI:
`--store "s3://team-experiments/ml?endpoint_url=http://minio:9000"`.
Re-running with the same `--store` reuses its workspace.

or at runtime via the API (`POST /api/v1/workspaces` with `{"name","path"}`).
The registry persists in `<data-dir>/workspaces.yml` (default `~/.vmn-ui`).

### Store-only (no git repo)

```sh
vmn-exp ui --store s3://team-experiments/ml
vmn-exp ui --store az://experiments/ml      # needs vmn-exp[azure]
```

Experiment browsing (leaderboards, run detail, artifacts) works with no local
checkout. Repo actions (stamp/goto) are naturally unavailable for store sources.

## Remote deployment

```sh
vmn-exp ui --host 0.0.0.0 --port 8265 --token "$VMN_UI_TOKEN" --data-dir /srv/vmn-ui
```

- **Auth**: a single shared bearer token (`--token` or the `VMN_UI_TOKEN` env).
  Every `/api` request must send `Authorization: Bearer <token>`. Binding beyond
  localhost without a token refuses to start — the Host-header allowlist below
  is not authentication, so anything reachable over the network could forge an
  allowed `Host` and get full read-write access. Add `--read-only` to allow this
  combination anyway (mutations stay blocked; the Host allowlist still limits,
  but does not authenticate, reads), pass `--token`/`VMN_UI_TOKEN`, or bind to
  loopback.
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
vmn-exp ui --host 0.0.0.0 --allowed-host vmn.example.com --token "$VMN_UI_TOKEN"
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

1. `POST /api/v1/workspaces/{ws}/apps/{app}/actions/{action}` with a JSON body
   → `202` + `{"id": ...}`. Actions: `stamp`, `release`, `goto`, `restore`,
   `prune`, `note`, `exp_create`, `exp_add`, `exp_tag`, `exp_archive`,
   `exp_unarchive` and `exp_rewind` (body `{"verstr", "step"}`; runs
   [`vmn-exp rewind`](experiments.md#rewind)).
2. `GET /api/v1/jobs/{id}` → status (`running`/`succeeded`/`failed`), exit code,
   and the captured log.

Each job runs `vmn <cmd>` or `vmn-exp <cmd>` as a subprocess in the workspace, so it acquires the
per-repo lock (serializing correctly against terminal use) and at most one
mutation runs per workspace at a time. Restores/gotos over a dirty tree
auto-save your work first (the safety net) — the job log tells you the
`vmn goto` that recovers it.

## The index

By default the server keeps a small SQLite cache under `<data-dir>/index/` to
make leaderboards and the stamp tree instant over large repos. It is derived
from the source files — delete it any time. `--no-index` keeps no on-disk cache
for git workspaces: their index lives in the server's memory, so a restart
rebuilds it from the files.

Experiments are indexed incrementally: a refresh re-reads only what moved — a
new run, a changed `metadata.yml`, the new bytes of a grown log, a rewritten
`run_state.yml` (a heartbeat). So a live run appending metrics, or a hundred
runs heartbeating, costs those files, not a re-read of every experiment. Store
workspaces get the same index, keyed by store URI and persisted next to
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

### Large stores: run the UI on free-threaded Python

With the GIL, every request and the background refresher share one core. On a
store of tens of thousands of runs, a busy dashboard queues behind that core.
A free-threaded Python (3.14t) runs them on every core. The UI only reads the
store, so it can run on its own interpreter, apart from your jobs'
environment:

```sh
uvx --python 3.14t --from "vmn-exp[ui]" vmn-exp ui --repo .
# or install it as a tool once
uv tool install --python 3.14t "vmn-exp[ui]"
```

The load harness (`tests/uiload`, `--profile load`: 100k runs, 500 live jobs,
16 concurrent clients) measured the same code on each interpreter:

| | 3.9 | 3.14 | 3.14t |
|---|---|---|---|
| requests/s | 25 | 42 | 299 |
| list p50 / p95 | 426 / 1278 ms | 247 / 761 ms | 3.5 / 70 ms |
| run detail p95 | 1534 ms | 977 ms | 21 ms |
| new run visible (p95) | 3.7 s | 3.1 s | 1.5 s |
| first load | 37 s | 27 s | 21 s |

`orjson` has no free-threaded wheel yet; on 3.14t the UI encodes JSON with the
standard library instead, which the numbers above already include. When a
watched app has 10,000 runs or more and the GIL is on, `vmn-exp ui` prints this
hint once.

## Run status in the dashboard

Every run row carries a color-coded status pill — `created`, `running`, `stuck`,
`succeeded`, `failed`. `running` pulses; `stuck` (a run whose heartbeat went
stale with no exit code — the node died and nothing recorded it) is flagged.
Staleness is judged on both the writer's heartbeat timestamp and the store's
write time of `run_state.yml`, so a writer with a lagging clock never shows `stuck`.
Inner runs are nested under their outer run, so a sweep collapses to one row
whose status is the rollup over its whole subtree. The page auto-refreshes while
anything is unfinished. See
[docs/experiments.md](experiments.md#run-status-did-my-job-die) for how the
statuses are derived.

## API

Full OpenAPI/Swagger docs at `/api/docs`. Everything is scoped by workspace:
`/api/v1/workspaces`, `.../apps`, `.../apps/{app}/experiments`,
`.../experiments/{verstr}`, `.../experiments/{verstr}/lineage`, `.../experiments/{verstr}/sweep` (see docs/sweeps.md), `.../experiments-columns`, `.../experiments-importance`, `.../experiments-facets`, `.../series`, `.../experiments-diff`, `.../versions`, `.../tree`,
`.../tree/root`, `.../deps`, and `/api/v1/jobs/{id}`.

### Experiment status fields

Every experiment row from `GET .../apps/{app}/experiments` and the
`.../experiments/{verstr}` detail response carries:

| Field | Meaning |
|---|---|
| `status` | `created` / `running` / `stuck` / `succeeded` / `failed` (derived, never stored) |
| `exit_code` | the command's exit code once finished, else `null` |
| `started_at` / `finished_at` | ISO-8601 timestamps |
| `heartbeat` | last heartbeat refresh |
| `stale_sec` | seconds since the last proof of life: the fresher of the heartbeat timestamp and the store's write time of `run_state.yml` |
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
at most 1000 rows from `offset`. `sort` is a metric name, `timestamp`, or
the run's own `started_at`/`finished_at` (dates sort newest first); `order=asc|desc` overrides the direction the metric's schema
goal implies. Runs without the metric stay last in either direction.

That schema is the app's *effective* metrics schema, which
`GET .../apps/{app}/metrics-schema` returns: conf.yml's `experiment.metrics`
plus the `goal`/`hidden` runs declare with `run.define_metric()` for names
conf.yml does not declare (the latest run wins; exact names beat globs). A
store workspace has no conf.yml, so there it is just the runs' declarations.
It sets sort direction and which metrics the dashboard hides by default
(leaderboard columns — toggle one in the column picker to show it — and a
collapsed "hidden metrics" section of the run's training curves); each run's
`metrics` values still follow only its own definitions and conf.yml.

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
`.../experiments`, `.../experiments-columns`, `.../experiments-importance` and `.../experiments-facets` —
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

- `keys` is a comma list of `metrics.<k>`, `params.<k>`, `timestamp`, `status`, `branch`
  and `name` (the row's `name`, else its `note`); any other key is a **400**.
  Every column is aligned with `verstrs`/`idx` (the `@N` storage index).
- Metric values are numbers or `null` (missing or non-finite); params are
  served verbatim.
- `q`, `status`, `sort`, `order` and `archived` mean what they mean on the list;
  the rows come in the list's order. `limit` (default 20000, at most 50000)
  caps the rows returned; `total` counts every match.
- Memoized per index snapshot (and status bucket while runs are live), with an
  `ETag`/`304` like the list.

### Parameter importance

`GET .../apps/{app}/experiments-importance?metric=<m>` answers which params
drive a metric over every run the filters match — what the leaderboard's
**Importance** chart shows (pick the target metric, it defaults to the sort
metric; click a param to open its scatter against the metric, or a per-value
mean table for a categorical/bool param):

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'q=status = "succeeded"' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments-importance?metric=loss"
```

```json
[{"param": "lr", "importance": 0.91, "correlation": 0.95, "spearman": 0.94, "kind": "numeric", "n": 240},
 {"param": "opt", "importance": 0.06, "correlation": null, "spearman": null, "kind": "categorical", "n": 240}]
```

- Sorted by `importance`, a random-forest share that sums to 1; `correlation`
  (Pearson) and `spearman` are `null` for categorical params; `n` counts the runs
  carrying both the param and the metric. Params with a single value are left out.
  See [`vmn-exp importance`](experiments.md#importance) for the algorithm.
- `q`, `status` and `archived` mean what they mean on the list. `metric` is
  required; one no visible run carries is a **400**, as is a bad `q`. A filter
  matching no run answers `[]`.
- Past 5000 matching runs a deterministic sample of 5000 is scored (well under
  a second). Memoized per index snapshot (and status bucket while runs are
  live), with an `ETag`/`304` like the list.

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
| `step_metrics` | `{metric: x metric}` for every metric that declares one (`run.define_metric(..., step_metric=)` or `step_metric:` in the conf.yml metrics schema) |
| `hidden_metrics` | the run's metrics marked hidden (`run.define_metric(..., hidden=True)`, else `hidden:` in the conf.yml metrics schema), sorted |
| `metric_summary` | `{metric: {last, min, max, first, mean}}` for every metric logged more than once |
| `patches` | which patch kinds the snapshot holds, read from its metadata flags |
| `media` / `tables` / `histograms` | logged images, tables and histograms per name, one item per step (see [Media](#media)) |
| `histograms_total` | `{name: steps logged}`; `histograms` keeps at most 100 evenly spaced steps per name |

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
{verstr: {metric: n}}, "step_metrics": {verstr: {metric: x metric}}, "missing":
[verstr, ...]}`. At most 200 runs per request;
`keys: null` means every metric. The runs share the 200,000-point cap. It is a
read, so `--read-only` servers answer it, but as a POST it needs
`Content-Type: application/json` and a same-site `Origin` like any other.

### Custom x axis

Both series endpoints can key a metric by another metric's value. The run
detail takes `?x=epoch` (every other metric joined on `epoch`); the batch body
takes `"x": "epoch"` or a per-metric map `"x": {"val_loss": "epoch"}` (unmapped
metrics come back plain). A joined point is `{"step", "ts", "value", "x"}`,
where `x` is the x metric's value at the same step (step-less points: the same
`log_metrics` call); points without a finite x are dropped. The join happens
before thinning, so downsampling still applies and `series_total` counts the
joined points.

In the dashboard, the Run page and the overlay have an `x:` picker next to the
Step / Wall / Relative toggle: `x: declared` (the default) plots each metric
against its declared `step_metric`, `x: step` ignores declarations, and any
metric name plots every other chart against it. It applies in Step mode.

### Diffs

`GET .../experiments-diff?v=&to=` materializes both runs and diffs them. Results
are cached per pair (a changed record is diffed again), at most two diffs run
at once (a third waits, then gets `429`), and the text is capped at 2 MB —
`truncated: true` says it was cut. A record with no base commit (a git-free
experiment) answers `diff: null` with the reason in `diff_unavailable`.

Artifacts download from `GET .../experiments/{verstr}/artifacts/{name}` (`{name}` may be a nested `a/b/c.txt` path; `..`, `.`, empty parts and backslashes are a 400) for
local and S3 workspaces alike (an S3 object is streamed straight through, never
staged on the server's disk); with a token set the request needs the
`Authorization` header like every other API call. Downloads are sent as stored
(never gzipped by the server) with an RFC 5987 `filename*` so any file name
survives.

### Media

What `run.log_image` / `log_table` / `log_histogram` recorded (see
[docs/sdk.md](sdk.md#tables-images-and-histograms)) shows in the run page's
**Media** section: an image grid with a step slider per key, a table viewer
(key and step pickers, server-side sort by clicking a column, 50 rows a page)
and a histogram chart per key for the chosen step, with an *over time* view
that stacks every step on a shared x range.

- Images download through the artifact route above
  (`.../artifacts/media/<name>/<step>.png`) as `image/png`; every artifact is
  served with a `Content-Type` guessed from its name, S3 ones included.
- `GET .../experiments/{verstr}/table/{path}?offset=0&limit=100&sort=<column>&order=asc|desc`
  answers one page of a logged table:
  `{"columns": [{"name", "type"}], "rows": [[...]], "total", "offset", "truncated"}`.
  Sorting covers the whole table (missing cells last in both orders);
  `limit` is capped at 1000. An unknown path is a `404`; a file that is not a
  logged table, or an unknown sort column, a `400`.

### Lineage

`GET .../experiments/{verstr}/lineage?depth=1&limit=100` answers the runs linked
to one run through what it consumed and produced — the same object as the SDK's
[`get_lineage`](sdk.md#lineage): `{app, verstr, upstream, downstream, models,
truncated}`, each node `{app, verstr, name, timestamp, status, depth, found,
links}`. It is answered from the app's index snapshot: the digest and
`vmn://` URI maps are built once per snapshot and shared by every request, so a
lookup costs the linked runs, not the workspace. `depth` is 1..10 and `limit`
1..1000 (else 400); an unknown run is a 404. The run page shows it as a
**lineage** card (upstream/downstream runs linked to their pages, registered
models, a depth picker).

### Model registry API

Under `/api/v1/workspaces/{ws}/models/`:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `.../models` | List all registered models (`{"models": [ModelRow...]}`) |
| `GET` | `.../models/{name}` | Full model detail: versions, aliases, audit log |
| `POST` | `.../models/{name}/versions` | Register a new version; body `{"run": {"app", "verstr"}, "artifact_path"?, "alias"?, "description"?}`; returns `{"version": N}` (201) |
| `POST` | `.../models/{name}/aliases` | Move alias; body `{"alias", "version", "expect"?}`; 409 on expect mismatch |
| `DELETE` | `.../models/{name}/aliases/{alias}` | Remove an alias |
| `POST` | `.../models/{name}/versions/{n}/status` | Set version status; body `{"status": "active"\|"deprecated"\|"deleted"}` |

All mutations return 403 in `--read-only` mode.  The complete TypeScript
contract (types and fetch helpers) is in `webui/src/apiModels.ts`.

The `/api/v1/meta` response now includes `"read_only": bool` so the web UI
can hide write controls when the server is started with `--read-only`.

### Caching and compression

JSON responses are rendered with `orjson` (part of the `ui` extra) and gzipped
at a moderate level. The whole web bundle is served `Cache-Control: no-cache` —
`/assets/*` as well as `index.html` and client routes — so an upgrade is never
served a stale chunk. Assets carry an ETag, so a reload revalidates and gets a
bodiless `304` while the file is unchanged. An unknown `/api/...` path is a
JSON `404`.
