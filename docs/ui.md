# vmn-exp ui

`vmn-exp ui` serves a web dashboard and REST API over your vmn repos and
experiment stores. Reads go straight to git tags and `.vmn/` files (or the
store) and never take the repo lock; mutations run as real `vmn` / `vmn-exp`
subprocesses.

## Install

```sh
pip install "vmn-exp[ui]"
```

Without the extra, `vmn-exp ui` prints an install hint and exits.

## Localhost

```sh
cd your-project
vmn-exp ui                     # 127.0.0.1:8265, attaches this repo, opens a browser
vmn-exp ui --port 9000 --no-browser
```

With no `--repo`/`--store`, the repo enclosing the current directory becomes
the workspace.

## Flags

| Flag | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8265` | Port |
| `--token` | `VMN_UI_TOKEN` | Bearer token required on every `/api` request |
| `--read-only` | off | Mutations (actions, workspace and registry writes) answer 403 |
| `--allowed-host` | — | Extra hostname clients may use (repeatable; `*` allows any) |
| `--data-dir` | `~/.vmn-ui` | Workspace registry (`workspaces.yml`), index cache, managed clones |
| `--repo` | — | Attach a local checkout as a workspace (repeatable) |
| `--store` | — | Attach a read-only experiment store URI as a workspace |
| `--no-index` | off | Keep no on-disk index; git workspaces index in memory only |
| `--no-browser` | off | Don't open a browser (one opens only for a loopback `--host`) |

## Workspaces

A **workspace** is one isolated source of data:

- a **git checkout**, with its own working tree, `.vmn/`, lock and index; or
- a read-only experiment **store**: any store URI (`s3://`, `gs://`, `az://`,
  `file://`, plugin schemes; see
  [Storage](experiments.md#storage-local-s3-gcs-azure-plugins)).

One server hosts many. Several git workspaces may be clones of the same remote
(one per branch or per user, say); a stamp or restore in one never touches
another's working tree.

```sh
vmn-exp ui --data-dir /srv/vmn-ui \
       --repo /srv/checkouts/model-a --repo /srv/checkouts/model-b \
       --store gs://team-experiments/ml
vmn-exp ui --store "s3://team-experiments/ml?endpoint_url=http://minio:9000"   # MinIO
vmn-exp ui --store az://experiments/ml      # needs vmn-exp[azure]
```

Workspaces persist in `<data-dir>/workspaces.yml`; re-running with the same
`--repo` or `--store` reuses its workspace. A store workspace serves the
leaderboards, run pages, artifacts and registry with no checkout; repo actions
(stamp, goto, the version tree) need a git workspace (400 otherwise).

At runtime, `POST /api/v1/workspaces` attaches a checkout
(`{"name", "path"}`) or clones one (`{"name", "remote", "path"?}`, by default
into `<data-dir>/workspaces/<name>`). `DELETE /api/v1/workspaces/{ws}`
unregisters it and deletes the checkout only if the server cloned it.

## Remote deployment

```sh
vmn-exp ui --host 0.0.0.0 --token "$VMN_UI_TOKEN" --data-dir /srv/vmn-ui
```

- **Auth**: one shared bearer token; every `/api` request sends
  `Authorization: Bearer <token>`. Binding beyond loopback without a token
  refuses to start (the Host allowlist below is not authentication) unless
  `--read-only` is given, which still serves reads to anyone who can reach
  the port.
- **TLS and users**: put a reverse proxy (nginx, Caddy) in front; vmn does not
  terminate TLS or manage accounts.
- **Host allowlist** (no token only): `/api` answers only a `Host` of
  `localhost`, `127.0.0.1`, `[::1]`, a non-wildcard `--host`, or an
  `--allowed-host`; anything else is 403. This stops DNS-rebinding pages
  reaching a token-less server on your machine.
- **Cross-site writes**: a POST/PUT/PATCH/DELETE whose `Origin` (or `Referer`)
  names another site than `Host` is 403 unless that site is an
  `--allowed-host`, and mutating requests must send
  `Content-Type: application/json` (415 otherwise). curl and scripts that send
  neither header are unaffected.
- **Paths**: URL app names, verstrs and artifact paths are validated (400 on
  `..` and the like); the SPA fallback serves only files inside `static/`.

Behind a proxy that rewrites `Host`, or when users reach the server by another
name, list that name:

```sh
vmn-exp ui --host 0.0.0.0 --allowed-host vmn.example.com --token "$VMN_UI_TOKEN"
```

```nginx
location / {
    proxy_pass http://127.0.0.1:8265;
    proxy_set_header Host $host;
}
```

## Actions

Mutations on a git workspace are asynchronous jobs:

1. `POST /api/v1/workspaces/{ws}/apps/{app}/actions/{action}` with a JSON body
   answers `202` + the job (`{"id", "command", "status", "exit_code", "log"}`),
   `400` for a bad body, `409` while another action runs in that workspace.
2. `GET /api/v1/jobs/{id}` polls it: `status` is `running`, `succeeded` or
   `failed`, with the exit code and the captured log.

| Action | Body | Runs |
|---|---|---|
| `stamp` | `{"release_mode", "prerelease"?, "dry_run"?}` | `vmn stamp -r <mode> [--pr] [--dry-run]` |
| `release` | `{"verstr"?}` | `vmn release [-v]` |
| `goto` | `{"verstr"?}` | `vmn goto [-v]` |
| `restore` | `{"verstr"}` | `vmn-exp restore -v` |
| `prune` | `{"keep"}` or `{"older_than"}` | `vmn-exp prune --keep` / `--older-than` |
| `exp_create` | `{"note"?, "metrics"?: {k: v}}` | `vmn-exp create [--note] [--metrics]` |
| `exp_add` | `{"verstr", "note"?, "metrics"?}` (one of the two) | `vmn-exp add -v` |
| `note` | `{"verstr", "note"}` | `vmn-exp add -v --note` |
| `exp_tag` | `{"verstr", "set"?: {k: v}, "remove"?: [k]}` (at most 100) | `vmn-exp tag` |
| `exp_archive` / `exp_unarchive` | `{"verstrs": [...]}` (at most 500) | `vmn-exp archive` / `unarchive` |
| `exp_rewind` | `{"verstr", "step"}` | [`vmn-exp rewind`](experiments.md#rewind) |
| `exp_push` | `{"verstrs"?: [...]}` (empty: every local run) | [`vmn-exp push`](experiments.md#offline-recording-and-push) |

Each job runs in the workspace as a subprocess, so it takes the per-repo lock
like terminal use, and at most one runs per workspace. A job has stdin closed
and fails after 30 minutes; the server keeps the last 200 jobs and the last
1 MB of each log. A restore or goto over a dirty tree auto-saves the work
first, and the job log names the `vmn goto` that brings it back.

There is no Rerun action: [`vmn-exp rerun`](experiments.md#rerun) supervises
its command for as long as it runs. The run page's *reproduce* card shows the
`vmn-exp rerun` command and links to its reruns (`rerun_of = "<verstr>"`); a
rerun links back to its source.

## The index

The server keeps a SQLite cache per app under `<data-dir>/index/` (store
workspaces too, keyed by store URI), derived from the source files, so delete
it any time. `--no-index` keeps git workspaces' index in memory, rebuilt on
restart.

- **Incremental**: a refresh re-reads only what moved (a new run, a changed
  `metadata.yml`, the new bytes of a grown log, a heartbeat). On a store it is a
  LIST plus the changed objects (ranged GETs for grown logs). The version tree
  and dependency graphs are recomputed only after a stamp.
- **Background refresh**: requests never refresh the index. Each app requested
  within the last minute gets a thread that refreshes it about once a second,
  with a full listing every 30 seconds; requests read the latest snapshot, so
  the dashboard lags the files by about a second. Only an app's first request
  waits for the initial load. A failed refresh (say, the bucket is
  unreachable) is logged and the last snapshot keeps being served.
- **Per-snapshot work**: status, the run tree, filtering and sorting are
  computed once per index generation and paging is a slice. Live runs'
  status is re-derived per 2-second bucket, so `stuck` shows within seconds.
  The app list is cached per workspace for 5 seconds.

Embedding `create_app()` directly (tests, scripts) leaves the background
refresher off unless you pass `background_refresh=True`; each request then
refreshes first and sees every earlier write.

### Large stores: run the UI on free-threaded Python

With the GIL, every request and the refresher share one core. A free-threaded
Python (3.14t) uses all of them. The UI only reads the store, so it can run on
its own interpreter:

```sh
uvx --python 3.14t --from "vmn-exp[ui]" vmn-exp ui --repo .
uv tool install --python 3.14t "vmn-exp[ui]"     # or install it once
```

The load harness (`tests/uiload`, `--profile load`: 100k runs, 500 live jobs,
16 clients) measured:

| | 3.9 | 3.14 | 3.14t |
|---|---|---|---|
| requests/s | 25 | 42 | 299 |
| list p50 / p95 | 426 / 1278 ms | 247 / 761 ms | 3.5 / 70 ms |
| run detail p95 | 1534 ms | 977 ms | 21 ms |
| new run visible (p95) | 3.7 s | 3.1 s | 1.5 s |
| first load | 37 s | 27 s | 21 s |

`orjson` has no free-threaded wheel yet, so 3.14t encodes JSON with the
standard library (included above). With the GIL on and a watched app of
10,000+ runs, `vmn-exp ui` prints this hint once.

## Run status in the dashboard

Every run row has a status pill (`created`, `running` (pulsing), `stuck`,
`succeeded`, `failed`). Inner runs nest under their outer run, so a sweep is
one row whose status rolls up its subtree. Pages auto-refresh while anything
is unfinished. See [Run status](experiments.md#run-status-did-my-job-die) for
how statuses are derived.

## API

OpenAPI docs are served at `/api/docs` (`/api/openapi.json`). All paths are
under `/api/v1`; `{app}` is the app's tag form (`root_app-service1` for
`root_app/service1`), `{ws}` the workspace name. `ws/{ws}/apps/{app}` below
stands for `workspaces/{ws}/apps/{app}`.

| Method | Path | Answers |
|---|---|---|
| `GET` | `/meta` | `{"version", "read_only"}` |
| `GET` / `POST` | `/workspaces` | List / add a workspace ([Workspaces](#workspaces)) |
| `DELETE` | `/workspaces/{ws}` | Remove a workspace (204) |
| `GET` | `/workspaces/{ws}/apps` | Apps with experiments or versions |
| `GET` | `ws/{ws}/apps/{app}/experiments` | Run rows ([paging](#paging-sorting-and-order), [query](#filtering-with-a-query)) |
| `GET` | `ws/{ws}/apps/{app}/experiments/{verstr}` | [Run detail](#run-detail-is-bounded) (`latest`, `@N`, prefixes resolve) |
| `GET` | `.../experiments/{verstr}/log?offset=&limit=` | A page of the log, `{"entries", "total"}`, oldest first |
| `GET` | `.../experiments/{verstr}/artifacts/{path}` | [Artifact download](#diffs-and-artifacts) |
| `GET` | `.../experiments/{verstr}/table/{path}` | A page of a logged [table](#media) |
| `GET` | `.../experiments/{verstr}/histograms/{name}` | One histogram key's [steps](#media) |
| `GET` | `.../experiments/{verstr}/lineage` | [Run lineage](#lineage) |
| `GET` | `.../experiments/{verstr}/sweep` | The sweep's spec, summary and trials ([sweeps.md](sweeps.md#status)) |
| `GET` | `ws/{ws}/apps/{app}/experiments-columns` | [Whole-set chart columns](#columns-for-whole-set-charts) |
| `GET` | `ws/{ws}/apps/{app}/experiments-importance` | [Parameter importance](#parameter-importance) |
| `GET` | `ws/{ws}/apps/{app}/experiments-facets` | [Filter vocabulary](#facets) |
| `GET` | `ws/{ws}/apps/{app}/experiments-diff?v=&to=` | [Code diff of two runs](#diffs-and-artifacts) |
| `POST` | `ws/{ws}/apps/{app}/series` | [Series of many runs](#series-for-many-runs) |
| `GET` | `ws/{ws}/apps/{app}/metrics-schema` | The [effective metrics schema](#paging-sorting-and-order) |
| `POST` | `ws/{ws}/apps/{app}/actions/{action}` | Start a [job](#actions) |
| `GET` | `/jobs/{id}` | A job's status and log |
| `GET` | `ws/{ws}/apps/{app}/versions` | Stamped versions (git workspaces) |
| `GET` | `ws/{ws}/apps/{app}/tree` | Version DAG (git) |
| `GET` | `ws/{ws}/apps/{app}/tree/root` | Root app's service topology per root version (git) |
| `GET` | `ws/{ws}/apps/{app}/deps?v=&to=` | Dependency pins of `v` (default latest), or their drift to `to` (git) |
| `GET` | `ws/{ws}/apps/{app}/changelog?v=&from=` | Conventional commits grouped between `from` (default: `v`'s previous version) and `v` (default latest) (git) |
| `GET` | `ws/{ws}/apps/{app}/config?v=` | `{"conf", "text"}` of the app's `conf.yml`, from the working tree or as of version `v` (git) |
| | `/workspaces/{ws}/models/...` | [Model registry](#model-registry-api) |

Unknown `/api/...` paths are a JSON 404.

### Experiment status fields

Every row of `.../experiments` and the run detail carry:

| Field | Meaning |
|---|---|
| `status` | `created` / `running` / `stuck` / `succeeded` / `failed` (derived, never stored) |
| `exit_code` | the command's exit code once finished, else `null` |
| `started_at` / `finished_at` | ISO-8601 timestamps |
| `heartbeat` | last heartbeat refresh |
| `stale_sec` | seconds since the last proof of life (the fresher of the heartbeat and the store's write time of `run_state.yml`) |
| `duration_sec` | wall-clock run time once finished |
| `pid` / `host` / `command` | what ran, where |
| `last_metric_at` | when a metric was last logged, to spot a run that is alive but not progressing |
| `parent` / `children` | verstrs linking outer and inner jobs |
| `kind` | `outer`, `inner` or `single` |
| `depth` | nesting depth, for indenting the list |
| `tree_status` | rollup over the run and its subtree (`failed > stuck > running > created > succeeded`) |

The run detail also groups them under a top-level `status` object. The list
takes `status=running,stuck` (comma-separated) to filter:

```sh
curl -H "Authorization: Bearer $VMN_UI_TOKEN" \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments?status=running,stuck"
```

### Filtering with a query

`q` is an expression over row fields, metrics and params in the
[query language](sdk.md#the-query-language) that `list_runs(query=...)` and
`vmn-exp list --query` take:

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'q=metrics.loss < 0.5 and params.optimizer = "adam"' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments"
```

`q` and `status` combine with **and**. Filtering happens before paging, so
`total` counts matches. An invalid query is a 400 carrying the parser's
message and offset (`unknown field 'statuz' at offset 0`).

### Paging, sorting and order

- `offset` and `limit` (at most 1000) page the list; with `limit` the answer is
  `{"rows": [...], "total": N}`, without it a plain list of at most 1000 rows.
  `last=N` keeps only the N most recent runs before sorting and paging.
- `sort` is a metric name, `timestamp`, `started_at` or `finished_at` (dates
  sort newest first). `order=asc|desc` overrides the direction the metric's
  goal implies; runs without the metric stay last either way.
- `archived=1` includes archived runs, which `.../experiments`,
  `-columns`, `-importance` and `-facets` otherwise leave out (and out of
  `total`).
- Each response carries an `ETag` (index generation, parameters and, while runs
  are live, the status bucket); send it back as `If-None-Match` and an
  unchanged poll is an empty `304`.

The goal comes from the app's effective metrics schema,
`GET .../metrics-schema`: conf.yml's `experiment.metrics` plus the
`goal`/`hidden` runs declare for names conf.yml lacks (see
[Metrics schema](experiments.md#metrics-schema-sorting--goals)); a store
workspace has only the runs' declarations. It also decides which metrics the
dashboard hides by default (the column picker and a collapsed "hidden metrics"
section on the run page show them).

```sh
curl -H "Authorization: Bearer $VMN_UI_TOKEN" \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments?sort=loss&order=asc&limit=50"
```

### Columns for whole-set charts

`GET .../experiments-columns?keys=...` answers a few values for every matching
run, so a chart plots all of them, not the loaded page:

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

- `keys`: comma list of `metrics.<k>`, `params.<k>`, `timestamp`, `status`,
  `branch`, `name` (the run's name, else its note); anything else is a 400.
  Columns align with `verstrs` and `idx` (the `@N` index).
- Metric values are numbers or `null`; params are verbatim.
- `q`, `status`, `sort`, `order`, `archived` work as on the list, in the same
  order. `limit` (default 20000, at most 50000) caps the rows; `total` counts
  every match. ETag/304 like the list.

### Parameter importance

`GET .../experiments-importance?metric=<m>` answers which params drive a metric
over the matching runs (the leaderboard's **Importance** view; click a param
for its scatter or per-value mean table):

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'q=status = "succeeded"' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments-importance?metric=loss"
```

```json
[{"param": "lr", "importance": 0.91, "correlation": 0.95, "spearman": 0.94, "kind": "numeric", "n": 240},
 {"param": "opt", "importance": 0.06, "correlation": null, "spearman": null, "kind": "categorical", "n": 240}]
```

- Sorted by `importance` (a random-forest share summing to 1); `correlation`
  (Pearson) and `spearman` are `null` for categorical params; `n` counts runs
  with both the param and the metric; single-valued params are left out. See
  [`vmn-exp importance`](experiments.md#importance).
- Takes `q`, `status`, `archived`. `metric` is required; a metric no visible
  run carries, or a bad `q`, is a 400; no matching run answers `[]`.
- Past 5000 matching runs a deterministic sample of 5000 is scored. ETag/304.

### Facets

`GET .../experiments-facets[?archived=1]` answers the filter vocabulary, each
list sorted (`metric_keys` includes numeric params; `total` counts all runs),
with an ETag:

```json
{"branches": ["feat/x", "main"], "metric_keys": ["acc", "loss"], "param_keys": ["lr", "opt"], "total": 5000}
```

### Run detail is bounded

`GET .../experiments/{verstr}` costs the same however long the run logged.
Query params: `max_points` (default 2000, at most 20000), `keys=loss,acc`
(only those series), `series=0` (no series), `include_log=1` (whole log),
`x=<metric>` ([custom x axis](#custom-x-axis)).

| Field | Meaning |
|---|---|
| `log_tail` | the newest 200 log entries |
| `log_total` | how many entries the log holds |
| `log` | same as `log_tail`, or the whole log with `include_log=1` |
| `series` | each metric thinned to at most `max_points` with min/max buckets (spikes survive; first and last kept). At most 200,000 points per response: with many metrics `max_points` is lowered |
| `series_total` | `{metric: points before thinning}` |
| `step_metrics` | `{metric: x metric}` for every metric that declares a `step_metric` |
| `hidden_metrics` | the run's metrics marked hidden, sorted |
| `metric_summary` | `{metric: {last, min, max, first, mean}}` for metrics logged more than once |
| `outputs` | the run's outputs (see [Lineage](#lineage)) |
| `rerun_of` | the run this one reruns, if any |
| `patches` | which patch kinds the snapshot holds |
| `media` / `tables` / `histograms` | logged images, tables, histograms per name, one item per step ([Media](#media)); `histograms` is `{}` once they would serve more than 100 steps in all |
| `histograms_total` | `{name: steps logged}` for every histogram name |

Page older entries with `.../log`. A live run's poll parses only the log bytes
appended since the last one. Detail and log carry an `ETag` and
`Cache-Control: no-cache` (304 when unchanged).

### Series for many runs

A comparison chart fetches the same metrics from many runs at once:

```sh
curl -X POST -H "Content-Type: application/json" \
  -d '{"verstrs": ["1.0.0-dev.a", "1.0.0-dev.b"], "keys": ["loss"], "max_points": 500}' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/series"
```

→ `{"series": {verstr: {metric: [{"step", "ts", "value"}]}}, "series_total":
{verstr: {metric: n}}, "step_metrics": {verstr: {metric: x metric}},
"missing": [verstr, ...]}`. At most 200 runs per request; `keys: null` means
every metric; the runs share the 200,000-point cap. It is a read (allowed with
`--read-only`), but as a POST it needs `Content-Type: application/json` and a
same-site `Origin`.

### Custom x axis

Both series endpoints can key a metric by another metric's value: run detail
takes `?x=epoch`, the batch body `"x": "epoch"` or a per-metric map
`"x": {"val_loss": "epoch"}` (unmapped metrics come back plain). A joined
point is `{"step", "ts", "value", "x"}`, where `x` is the x metric's value at
the same step (for step-less points, the same `log_metrics` call); points
without a finite x are dropped. The join happens before thinning, and
`series_total` counts joined points.

In the dashboard, the run page and the overlay have an `x:` picker next to the
Step / Wall / Relative toggle (Step mode): `x: declared` (default) uses each
metric's declared `step_metric`, `x: step` ignores declarations, and a metric
name plots every other chart against it.

### Diffs and artifacts

`GET .../experiments-diff?v=&to=` materializes both runs and diffs their code.
Results are cached per pair, at most two diffs run at once (a third waits, then
gets 429), and the text is capped at 2 MB (`truncated: true`). A record with no
base commit (a git-free run) answers `diff: null` with the reason in
`diff_unavailable`.

`GET .../experiments/{verstr}/artifacts/{path}` downloads an artifact (`path`
may be nested, `a/b/c.txt`; `..`, `.`, empty parts and backslashes are a 400)
from local and remote stores alike; a remote object streams straight through.
Downloads are never gzipped, carry a `Content-Type` guessed from the name, and
an RFC 5987 `filename*`.

### Media

What `run.log_image` / `log_table` / `log_histogram` recorded (see
[sdk.md](sdk.md#tables-images-and-histograms)) shows in the run page's
**Media** section: an image grid with a step slider per key, a table viewer
(key and step pickers, server-side sort, 50 rows a page) and a histogram chart
per key, with an *over time* view stacking every step.

- Images download through the artifact route
  (`.../artifacts/media/<name>/<step>.png`, `image/png`).
- `GET .../table/{path}?offset=0&limit=100&sort=<column>&order=asc|desc`
  answers `{"columns": [{"name", "type"}], "rows": [[...]], "total", "offset",
  "truncated"}`. Sorting covers the whole table (missing cells last); `limit`
  is capped at 1000. Unknown path: 404; not a table, or an unknown column: 400.
- `GET .../histograms/{name}` answers `{"name", "steps": [{"step", "bins",
  "counts"}], "total"}`: at most 100 evenly spaced steps, first and last
  included, with an ETag. Names may contain `/` (`gradients/fc.weight`).
  Unknown run or name: 404. Run detail inlines steps only for small runs, so a
  model watched with [`torch_watch.watch`](sdk.md#pytorch--watch) (hundreds of
  keys) does not bloat each poll; the run page fetches the keys it shows.

### Lineage

`GET .../experiments/{verstr}/lineage?depth=1&limit=100` answers the same
object as the SDK's [`get_lineage`](sdk.md#lineage) (`upstream`,
`downstream`, `datasets`, `models`, `truncated`), from the index snapshot.
`depth` is 1..10 and `limit` 1..1000 (else 400); an unknown run is a 404. The
run page shows it as a **lineage** card with a depth picker and badges linking
each used model/dataset version to its registry page.

`GET /workspaces/{ws}/models/{name}/versions/{n}/lineage` is the version side,
[`version_lineage`](sdk.md#lineage): `{model, version, kind, status, producer,
consumers}`. Invalid name: 400; a version that never existed: 404. The model
page shows it with a version picker.

### Model registry API

Under `/api/v1/workspaces/{ws}/models` (concepts and rules in
[models.md](models.md)):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/models[?kind=model\|dataset]` | `{"models": [row...]}`, each row with its `kind`; any other `kind` is a 400 |
| `GET` | `/models/{name}` | `{name, kind, description, versions, aliases, audit}` |
| `GET` | `/models/{name}/versions/{n}/lineage` | Producer and consumer runs ([Lineage](#lineage)) |
| `POST` | `/models/{name}/versions` | Register a run-backed version; body `{"run": {"app", "verstr"}, "artifact_path"?, "alias"?, "description"?}` → `201 {"version": N}` |
| `POST` | `/models/{name}/aliases` | Move an alias; body `{"alias", "version", "expect"?}`; 409 on an `expect` mismatch |
| `DELETE` | `/models/{name}/aliases/{alias}` | Remove an alias |
| `POST` | `/models/{name}/versions/{n}/status` | Body `{"status": "active"\|"deprecated"\|"deleted"}`; 400 when deleting a version an alias points at |

Registry writes run in-process (no job, no repo lock) and are 403 with
`--read-only`. The TypeScript contract is
`packages/vmn-exp/webui/src/apiModels.ts`.

### Caching and compression

JSON is rendered with `orjson` (in the `ui` extra; NaN/inf become `null`) and
gzipped when the client accepts it. The web bundle (`/assets/*`, `index.html`
and client routes) is served `Cache-Control: no-cache` with ETags, so an
upgrade never serves a stale chunk and a reload revalidates to a bodiless 304.
