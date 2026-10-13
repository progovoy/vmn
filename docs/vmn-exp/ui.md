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
the workspace. With `--repo`, `--store` or `--config`, `vmn-exp ui` runs from
any directory, inside a git checkout or not.

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

The sidebar remembers, per workspace and browser tab, the last app you opened
there: on workspace pages (Models, Reports, Apps) its app switcher keeps that
app and the App nav (Experiments, Stamp tree, Actions) still points to it. A
workspace where no app was opened yet shows "choose app".

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

## Signing in

When the server needs auth, a page load that gets a 401 shows a sign-in page
in place of the page (the sidebar stays). It offers what the 401 body's
[`auth` hints](server.md#authentication) name: **Continue with SSO** (OIDC;
you come back to the page you were on) and/or a **Token** field for the
`--token` / `VMN_UI_TOKEN` value or a `vmnx_…` API token. The token is kept in
`sessionStorage` for the tab. A 401 on a mutation instead shows a
**Session ended** banner above the page, which stays mounted so typed input
survives; the action is not replayed, retry it after signing in. A 403 is not
a sign-in case: the page shows the server's message (`Requires role 'editor'`).

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
its command for as long as it runs. The run header's **Reproduce** menu copies
the `vmn-exp restore`, `rerun` (runs that recorded a command) and `export`
commands (`--store` added in a store workspace), links to the run's reruns
(`rerun_of = "<verstr>"`) and, in a writable git workspace, runs `vmn goto -v
<verstr> <app>` as a job after a confirm dialog that shows the command. **Copy
link** copies the run's canonical `/ws/<ws>/app/<app>/run/<verstr>` URL. A
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

The load harness (`packages/vmn-exp/tests/uiload`, `--profile load`: 100k runs, 500 live jobs,
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
one row whose status rolls up its subtree. While any run on the page is
running, the leaderboard and the run page poll on their own and show
`● live · updated Ns ago` with a Pause button (Resume restarts it); with
nothing running they show a Refresh button instead. On the leaderboard this
sits in the table's caption, under the board, with the "best in column" legend
and the sort; below 640px, where the caption follows every card, the page head
also shows `live · updated Ns ago` (or `paused`) as plain text after the run
count. Above the board, an attention strip (`⚠ 2 stuck · 3 failed in 24h
· 4 running`, from `experiments-status`) appears while a run is stuck or one
failed in the last 24 hours; each part links to the board filtered to exactly
those runs (`status=stuck`; the failures also get a `finished_at >= "<24h
ago>"` token, newest first), replacing the other filters. Under a filter, an
inner run whose outer is not among the matches is listed on its own, so the
rows behind a link are as many as it counts. App tiles count runs the same way
(archived runs left out). See [Run status](experiments.md#run-status-did-my-job-die) for
how statuses are derived.

## The run page

A run's page reads top to bottom in the order of the questions it answers:
the header (name, verstr, branch, the Reproduce / Copy link / Add to report
actions and the live indicator, then a line with `@N`, the status pill, the
base version, and for an outer run its tree status with `N/M inner`); the note
and tags; the failure card (failed runs); training curves; Changes; Fleet and
Sweep (outer runs); Parameters (those that vary across the app's loaded runs
first) | Metrics (params folded into `metrics` stay under Parameters); Similar
runs | Lineage; the output log and artifacts. Last come sections collapsed by
default: **Status details** (exit code, duration, pid, host, heartbeat,
command, parent, and the run's code metadata), **Log** (closed, it shows its
last 10 entries), **Environment** (Python, platform, packages, inputs),
**Media** (open when the run logged any) and **Comments** (open when there
are any). Each section's heading is a button (`aria-expanded`); the open or
closed choice is remembered per browser (localStorage `vmn-exp:disclosures`).

An outer run's page lists its children once, in the Fleet card (Status
details has no `children` row): status counts, a bar, and a table of `@N name`,
status, the params that vary among the children (at most six), the goal metric
(the conf's primary metric, else the first child metric with a declared or
name-inferred goal; best marked) and progress (`step / of`), a column shown
only when some child's progress is known. Every header sorts (a button, so
Enter/Space work too, with `aria-sort`); a metric starts toward its goal,
missing values sort last. A sweep's trials are that table inside the Sweep
card instead (with the trial number and the sweep metric), followed by a
parallel-coordinates chart of the metric and the varying params.

## Leaderboard columns

By default the leaderboard shows `#`, status, experiment, the metrics whose
`goal` the schema declares (pinned after the experiment column; every metric
when none declares one), up to six params whose values vary across the loaded
runs (as many as fit the window), the inner-run count columns `total`,
`waiting`, `running`, `done` and `failed` under an "Inner runs" header while
an outer run is loaded (each turned on/off on its own with `show=`/`hide=`
`c:total` etc.; a `c:inner` key from views saved while the counts were one
column shows or hides all five; an incomplete sweep's total reads
`16/20 · incomplete`; with all five hidden the experiment cell says
`N inner`), and `when`. Note, tags, the run's
`started`/`ended` dates and the rest come from the Columns picker. The choices
live in the URL (`show=`/`hide=`, e.g. `show=m:train_loss`, `hide=p:seed`;
`hide=` always hides, except that it still shows a schema-hidden metric, as
before; `pin=`; `pin=-` pins nothing), and dragged
widths/order in the browser. A fade on the table's right edge shows there are
more columns to scroll to.

## Compare

`.../app/<app>/compare-runs` is the one Compare page. Its tabs live in
`?tab=`: `curves` (default; the selected runs' training curves overlaid),
`table` (params and metrics side by side, up to 50 runs) and `code` (the
metric delta and source diff of two runs). All three share the repeated
`?sel=` selection, shown as chips you can remove or add to, so switching tabs
keeps the runs. With more than two selected, the code tab diffs the first run
against a picker that defaults to the second (`?to=`). When a run's code can't
be materialized (422 `code_missing`/`no_code`/`restore_failed`), it shows the
reason, keeps both pickers and prints the `vmn-exp diff` line.

Runs are named `@N name` everywhere on the page (the curves legend, the table's
run columns, the code tab's delta columns), with the verstr in the tooltip and
a copy button next to it. The table tab opens with **Only differing** on
(`?diff=0` turns it off); its Metrics section leaves out params that were folded
into `metrics` without ever being logged as a metric, and its Params section
says how many params changed. A best value is marked only for a metric with a
goal (declared, or a loss/accuracy-like name). The curves tab has one labelled
x axis control (Step, Wall, Relative, or a metric), a Log y chip and a
smoothing slider that reads `off` or its value.

On the leaderboard, selecting runs shows a bar with one primary **Compare (N)**
(it says why it is disabled below two runs) that opens
`compare-runs?tab=curves&sel=...`, plus Archive/Unarchive.

The old `overlay?runs=a,b` and `compare?v=a&to=b` URLs redirect to
`compare-runs?tab=curves&sel=a&sel=b` and `?tab=code&sel=a&sel=b`, so
bookmarks and links in reports keep working.

## Keyboard

- **Skip to content**: the first Tab stop jumps past the sidebar to the page.
- **⌘K / Ctrl+K** toggles the command palette anywhere. It reads CLI grammar
  (a leading `vmn-exp`/`vmn`/`exp` is dropped, so a pasted command works):
  `@54` or `show [app] -v <ref>` opens a run, `list [app] <query>` (or any
  input with `metrics.`/`params.` or a comparison) filters the leaderboard,
  `compare @3 @7`, `diff a b`, `overlay a b`, `tree [version]`,
  `status stuck`, `create`, a page (`models`, `reports`, `tokens`, `actions`,
  `apps`, `docs`, ...) or an app/workspace name. `goto <version>` only fills
  the Actions goto form, and `restore`/`rerun <ref>` copy the command: the
  palette never runs a mutation. Without an app in the input, the current one
  (or the workspace's only one) is used. Keys: ↑↓ move, Home/End, PageUp/PageDown
  between sections, ↵ open, ⌘↵ new tab, ⇧↵ copy the row's CLI equivalent, Tab
  completes the verb or app, Esc clears the input, then closes.
- **Leaderboard headers**: each sortable header is a button (Enter/Space
  sorts, again reverses; the cell carries `aria-sort`). Dragging (reorder)
  and the right-edge grip (resize) are mouse-only; the `⋮` column menu on
  each header gives the keyboard equivalents: Sort, Hide column, Pin/Unpin
  column (metrics and params), Move left/right (a pinned column moves among
  the pinned ones; `#`, status and experiment stay put).
- **Narrow windows** (below 900 px): the sidebar becomes a drawer opened from
  the topbar's menu button; it focuses the first nav link, and Esc, a click
  outside or a navigation closes it and returns focus to the button.

## API

OpenAPI docs are served at `/api/docs` (`/api/openapi.json`). All paths are
under `/api/v1`; `{app}` is the app's tag form (`root_app-service1` for
`root_app/service1`), `{ws}` the workspace name. `ws/{ws}/apps/{app}` below
stands for `workspaces/{ws}/apps/{app}`.

| Method | Path | Answers |
|---|---|---|
| `GET` | `/meta` | [Server meta](#server-meta-and-roles): versions, `read_only`, `mode`, `auth`, `principal`, `role` |
| `GET` / `POST` | `/workspaces` | List (each item with the caller's `role`, [roles](#server-meta-and-roles)) / add a workspace ([Workspaces](#workspaces)) |
| `DELETE` | `/workspaces/{ws}` | Remove a workspace (204) |
| `GET` | `/workspaces/{ws}/git` | [Branch, HEAD, dirty, store](#git-context) of a git workspace |
| `GET` | `/workspaces/{ws}/apps` | Apps with experiments or versions |
| `GET` | `ws/{ws}/apps/{app}/experiments` | Run rows ([paging](#paging-sorting-and-order), [query](#filtering-with-a-query)); with `group=`, [groups of runs](#grouped-runs) |
| `GET` | `ws/{ws}/apps/{app}/experiments/{verstr}` | [Run detail](#run-detail-is-bounded) (`latest`, `@N`, prefixes resolve) |
| `GET` | `.../experiments/{verstr}/log?offset=&limit=` | A page of the log, `{"entries", "total"}`, oldest first |
| `GET` | `.../experiments/{verstr}/artifacts/{path}` | [Artifact download](#diffs-and-artifacts) |
| `GET` | `.../experiments/{verstr}/table/{path}` | A page of a logged [table](#media) |
| `GET` | `.../experiments/{verstr}/histograms/{name}` | One histogram key's [steps](#media) |
| `GET` | `.../experiments/{verstr}/lineage` | [Run lineage](#lineage) |
| `GET` | `.../experiments/{verstr}/patch?max_bytes=` | [The run's patch and changed files](#run-code-patch-and-baselines) |
| `GET` | `.../experiments/{verstr}/baselines` | [Runs to diff it against](#run-code-patch-and-baselines) |
| `GET` | `.../experiments/{verstr}/sweep` | The sweep's spec, summary and trials ([sweeps.md](sweeps.md#status)) |
| `GET` | `.../experiments/{verstr}/similar?top=&all_apps=&archived=&q=` | [Runs most like this one](#similar-runs) |
| `GET` | `ws/{ws}/apps/{app}/similar?text=&top=&all_apps=&archived=&q=` | [Runs matching a text](#similar-runs) |
| `GET` | `ws/{ws}/apps/{app}/experiments-columns` | [Whole-set chart columns](#columns-for-whole-set-charts) |
| `GET` | `ws/{ws}/apps/{app}/experiments-importance` | [Parameter importance](#parameter-importance) |
| `GET` | `ws/{ws}/apps/{app}/experiments-facets` | [Filter vocabulary](#facets) |
| `GET` | `ws/{ws}/apps/{app}/experiments-status` | [Status counts and rollup](#status-counts-and-rollup) |
| `GET` | `ws/{ws}/apps-status` | [Every app's status counts](#status-counts-and-rollup), one request |
| `GET` | `ws/{ws}/apps/{app}/experiments-diff?v=&to=` | [Code diff of two runs](#diffs-and-artifacts) |
| `POST` | `ws/{ws}/apps/{app}/series` | [Series of many runs](#series-for-many-runs) |
| `GET` | `.../experiments/{verstr}/metric-keys?prefix=&offset=&limit=` | [A run's metric names, paged](#zoom-and-many-keys) |
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

Routes that resolve a run ref (run detail, its log page, `experiments-diff`)
answer a ref they cannot resolve with `{"detail": "<message>", "code": "<code>"}`:
`run_not_found` (no such verstr or prefix, `@N` out of range, no runs) is a
404, `ambiguous_ref` (a prefix matching several runs) a 409, `invalid_ref`
(a malformed ref such as `@x`) a 400. Clients branch on `code`, never on the
message.

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
| `tree_status` | rollup over the run and its subtree (`failed > stuck > running > created > succeeded`); a container outer's own `created` is left out, an incomplete sweep adds `created` |
| `sweep_planned` / `sweep_trials` | a sweep outer's planned trials (grid size, else `run_cap`) and the trial slots its inner runs fill; absent for other runs and uncapped random/bayes sweeps. While `sweep_trials < sweep_planned` the UI reads `16/20 · incomplete`, and the detail's `status.fleet.expected` is the planned size |
| `signal` / `end_reason` | the signal that ended the run (`SIGTERM`), `stopped` for an early-stopped sweep trial |
| `error_summary` | `Type: message` of a failed run's recorded `error`, else `null` |

The run detail also groups them under a top-level `status` object, which also
carries `error`: the run's full `error` mapping (`type`, `message`,
`traceback`, `source`, `output_tail`) or `null` — never on list rows. An
outer run's `status.fleet` is `{expected, counts, children}`; each of its first
50 children is `{verstr, status, idx, name, params, metrics, progress,
progress_total, last_step}`, where `last_step` is `{step, of}` (`of` from
`params.epochs`/`max_steps`, else null) read from the child's log on a local
store, and `null` on a remote store or when it logged no step. The list
takes `status=running,stuck` (comma-separated) to filter:

```sh
curl -H "Authorization: Bearer $VMN_UI_TOKEN" \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments?status=running,stuck"
```

### Server meta and roles

`GET /meta`:

| Field | Meaning |
|---|---|
| `version` / `vmn_exp_version` | vmn's version, the installed `vmn-exp` package's (`null` when not installed as a package) |
| `read_only` | `--read-only` |
| `mode` | `configured` with `--config` or a control plane, else `standalone` |
| `control_plane` | whether a control plane (API tokens) is configured |
| `auth` | `{enabled, token, oidc, login_url}`: the sign-in methods offered (`login_url` is `/auth/login` with OIDC, else `null`); never a secret |
| `principal` | `{id, name}` of the caller, or `null` |
| `role` | the caller's role in `*`, or `null`. With auth on, `null` means no global role (per-workspace roles may still apply); with auth off, everything is allowed |

Each `/workspaces` item carries `role` (`viewer`/`editor`/`admin`, the `*`
role included), `null` with auth off or no role there.

### Git context

`GET /workspaces/{ws}/git` (git workspaces only: a store workspace is 400):

```json
{"branch": "main", "detached": false, "head": "<40-hex>", "head_short": "e71c74d", "dirty": true, "store": ".vmn/store"}
```

One `git --no-optional-locks status --porcelain=v2 --branch
--untracked-files=no` (2 s timeout), so it never takes `index.lock` and
untracked files are not dirty. Detached: `branch: null, detached: true`. On a
failure it still answers 200 with `branch`/`head`/`head_short`/`dirty` `null`
and an `error` (the first stderr line, or `timeout`). Cached 5 s per workspace.

The topbar's breadcrumb root shows the workspace and `branch @ head_short`
(plus `dirty`); `store` and the checkout path sit behind its Data source
button, not in the trail. When the workspace is named after its app, the
trail leaves the app crumb out.

### Status counts and rollup

`GET ws/{ws}/apps/{app}/experiments-status`:

```json
{"total": 53,
 "counts": {"created": 0, "running": 2, "stuck": 1, "succeeded": 41, "failed": 9},
 "failed_recent": 1, "rollup": "stuck"}
```

Counts the non-archived runs by derived status (all five keys always present).
`failed_recent` counts failures that finished within the last 24 hours. `rollup` is
`stuck` if any run is stuck, else `failed` if `failed_recent > 0`, else
`running` if any runs, else `null`. A known app with no runs answers zeros; an
unknown app is a 404 `{"detail", "code": "app_not_found"}`, checked against the
checkout (`.vmn/<app>/conf.yml`) and the store (any run or snapshot record),
not the cached app list. ETag/304, accurate to the hour for `failed_recent`.

`GET ws/{ws}/apps-status` answers `{"<app tag>": <the same summary>, ...}` for
every app of the workspace in one request (tags use `-` for `/`), memoized
like the per-app route; ETag/304.

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

### Grouped runs

`GET .../experiments?group=<field>` answers groups instead of a page. The
field is a link between runs, `parent`, `forked_from`, `rerun_of` (the run
pointed at heads the group and is not one of its rows) or `code_verstr` (the
code state), or a row field: `branch`, `status`, `tags.<key>`, `params.<key>`.

```
{"groups": [{"key", "label",
             "target": {verstr, idx, name, status, tree_status, metrics} | null,
             "counts": {total, running, waiting, done, failed, stuck},
             "aggregates": {"<metric>": {mean, best, median, min, max, n}},
             "rows": [...], "rows_total": 16}],
 "total_groups": 3, "total_rows": 48}
```

- `target` is the header run of a `parent`/`forked_from`/`rerun_of` group. A
  target missing from the index (pruned, another app) groups under its verstr
  with `target: null` and the label `<verstr> (not found)`. Runs without a
  value form the `(none)` group, always last (labelled `(no parent run)` for
  `parent`).
- Filters (`q`, `status`, `archived`) select rows; a group shows when one of
  its rows passes, and its counts and aggregates cover the passing rows. A
  link group keeps its `target` even when the target fails the filter. A
  `rerun_of` group's aggregates include the original's own value.
- `aggregates` cover each metric's finite values, by each run's summary
  policy; `best` follows the metric's goal and is null without one.
- `sort`/`order` order rows within a group as on the flat list. Groups order
  by `agg=mean|best|median|min|max` of the sort metric (`best` without a goal
  is the mean; groups without a value after the others), and by their first
  row for a date or no metric sort. `agg` defaults to conf.yml's
  `experiment.ui.group_aggregate`, else `mean`; every aggregate is in the
  payload either way.
- `offset`/`limit` page groups (default 50); `rows_per_group` (1..100, default
  10) caps each group's `rows`. `group_key=<key>&offset=&limit=` answers that
  one group with its rows paged (404 for an unknown key).
- An unknown field or aggregate, `last` or a `rows_per_group` out of range is
  a 400. Groupings are kept per index generation and moved along with it, so a
  grouped page costs about what a flat one does.

```sh
curl -H "Authorization: Bearer $VMN_UI_TOKEN" \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments?group=parent&sort=loss&agg=best&limit=50"
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
`x=<metric>` ([custom x axis](#custom-x-axis)), `step_min`/`step_max`
([zoom](#zoom-and-many-keys)).

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
| `compacted` | whether every metrics writer of the run has its compacted `.vmx` (the UI shows a "not compacted" badge otherwise) |
| `output_tail` | failed/stuck runs only: `{lines, truncated}`, the last 40 lines of `outputs/output.log` (one range read of at most 16 KB; a partial first line is dropped, a `\r`-rewritten line keeps its last rewrite), `null` without one |
| `last_step` | failed/stuck only: `{step, of}`, the highest step of the metrics' newest points; `of` = numeric `params.epochs`, else `params.max_steps`, else `null`; `null` without a stepped metric |
| `last_good` | failed/stuck only: `{verstr, idx, name}` of the latest earlier succeeded run of the same command (unarchived), else `null` |
| `idx` / `name` | the run's `@N` index and its name (from its index row, else `name` from its metadata); `null` when unknown |

Page older entries with `.../log`. A live run's poll parses only the log bytes
appended since the last one. Detail and log carry an `ETag` and
`Cache-Control: no-cache` (304 when unchanged).

### Run code: patch and baselines

`GET .../experiments/{verstr}/patch?max_bytes=200000` is `vmn-exp show
--patch --json`'s `patch` object plus `files`:

```json
{"text": "=== working_tree ===\ndiff --git ...", "truncated": false,
 "files": [{"path": "train.py", "added": 3, "removed": 1}]}
```

`files` counts each path's hunk lines in the served (possibly truncated) text,
summed over its sections; dep paths read `deps/<dep>/<path>`. Without text it
is `{"text": null, "reason": "no_code"|"code_missing"|"untracked_only", "files": []}`
(`untracked_only` adds `untracked_files`). `max_bytes` must be >= 1 (400) and is
capped at 10 MB. The ETag is the run's code identity, so a 304 never loads the
code object (none on `code_missing`, whose object may still be pushed).

`GET .../experiments/{verstr}/baselines` names the runs the Changes card can
diff against, from the index snapshot (no git, no lock). Each key is present
only when it exists, each `{verstr, idx, name, status}`:

| Key | Run |
|---|---|
| `base` | the run itself, when it captured a working-tree or local-commits patch |
| `parent` / `forked_from` / `rerun_of` | its origins, when indexed |
| `previous` | the latest earlier unarchived run on the same `branch` with the same `command` |
| `best` | the best other run on the primary declared goal (`primary: true` with a goal, else the first exactly named schema metric with one); absent without a declared goal |

A run not indexed yet answers `{}`; an unknown run is 404. Both are viewer
reads with a body-digest ETag.

The run page's **Changes** card (`#changes`, below the training curves, in
read-only workspaces too) offers these baselines as a picker. It defaults to
`base` when present, else `previous`, else the first that exists. `base` shows
the `/patch` files and text. Any other baseline is diffed through
`experiments-diff` (baseline → this run): it shows the top 5 metrics by |Δ|
(goal metrics first, then "+N more"), a *Params changed* block (count + one
row per param), the changed files and the diff behind *Show diff*, with *Open in Compare →*
(`compare-runs?tab=code&sel=<baseline>&sel=<run>`). Without code or
baselines, it shows one line with the reason. The picked baseline is kept in
the page's `?baseline=` param. Its value is a baseline key or any run ref,
and a ref that is not a baseline gets its own `vs <ref>` choice. So
`/ws/<ws>/app/<app>/run/<verstr>?baseline=<ref>#changes` links straight to
a diff against that run.

A failed run's **Error** card uses the failure fields of the run detail:
`stopped at step N[ of M]` (`last_step`), "Since it last worked: @N name →
Changes" (`last_good`; the link is this run's page with
`?baseline=<last_good>#changes`), and under *last output* the
`output_tail` lines (the error's own captured tail when there are none),
scrolled to the end, with *open full output* pointing at the Output card.

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

### Zoom and many keys

Both series endpoints take `step_min`/`step_max` (query params on run detail,
body fields on the batch; either may be omitted, neither combines with `x`).
The range is read straight from the metric files: on a compacted `.vmx` that is
the level-of-detail slice covering it, so a zoom into a 1M-step run reads a few
small byte ranges, not the run. The UI refetches on a chart zoom (debounced)
and keeps the coarse series drawn meanwhile.

`GET .../experiments/{verstr}/metric-keys?prefix=&offset=&limit=` →
`{"keys": [{"name", "count"}], "total", "offset", "limit"}` pages a run's
metric names (sorted; `prefix` filters), for runs with thousands of keys; the
run page's key picker uses it.

### Custom x axis

Both series endpoints can key a metric by another metric's value: run detail
takes `?x=epoch`, the batch body `"x": "epoch"` or a per-metric map
`"x": {"val_loss": "epoch"}` (unmapped metrics come back plain). A joined
point is `{"step", "ts", "value", "x"}`, where `x` is the x metric's value at
the same step (for step-less points, the same `log_metrics` call); points
without a finite x are dropped. The join happens before thinning, and
`series_total` counts joined points.

In the dashboard, the run page's training curves and the Compare page's
curves tab share one x axis control: Step (each metric's declared
`step_metric`, else the step), Wall, Relative, or `x = <metric>` for every
chart. `Log y` is an on/off chip; a log axis labels each tick with its own
value (`1e-4`, `0.001`, `10`).

### Diffs and artifacts

`GET .../experiments-diff?v=&to=` materializes both runs and diffs their code.
Results are cached per pair, at most two diffs run at once (a third waits, then
gets 429), and the text is capped at 2 MB (`truncated: true`). A record with no
base commit (a git-free run) answers `diff: null` with the reason in
`diff_unavailable`.

`metrics_delta` maps each key of the two runs' folded `metrics` whose value
differs to `{from, to, goal, param}` (`from`/`to` are `null` on a run without
the key). `param: true` marks a numeric param folded into `metrics`: every run
holding the key holds it as a param with no `metric_summary` entry, so a param
only one run set is still a param. The Compare *Code* tab and the run page's
*Changes* card list those under *Params changed*, the rest as metrics.

`GET .../experiments/{verstr}/artifacts/{path}` downloads an artifact, and
`.../outputs/{path}` one of vmn's own outputs (`output.log`, media, tables;
`path` may be nested, `a/b/c.txt`; `..`, `.`, empty parts and backslashes are a 400)
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
  (`.../outputs/media/<name>/<step>.png`, `image/png`).
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

### Similar runs

`GET .../experiments/{verstr}/similar?top=10&all_apps=0&archived=0` answers the
runs most like that run, as [`vmn-exp similar -v`](experiments.md#similar)
ranks them: the run itself, its run tree and its reruns (same code, params
and inputs; forks are kept) are left out, and a sweep or the reruns of one
config show as their best run.
`GET ws/{ws}/apps/{app}/similar?text=...` is the text-only query in one app,
like `vmn-exp similar --context ... --text-only`. With `all_apps=1` either
covers every app of the workspace; `GET /api/v1/similar?text=` covers every
workspace you may view ([server.md](server.md#postgres-and-replicas)).

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'text=label smoothing, soft targets' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/similar?top=5"
```

```json
{"items": [{"workspace": "my-repo", "app": "my_app", "verstr": "0.0.3-dev.abc1234.def5678",
            "name": null, "score": 0.82, "reasons": ["shared: label smoothing"],
            "signals": {"text": 0.82}, "group_size": 3,
            "goal": {"metric": "val_loss", "goal": "min", "value": 0.31},
            "author": "alice@x.io", "timestamp": "2026-09-20T10:02:11Z", "status": "succeeded",
            "note": "smoothing 0.1", "intent": {"text": "...", "keywords": ["label smoothing"], "truncated": false}}],
 "truncated": false}
```

- `intent` is the first 2 KB of the run's intent text with its keywords, or
  `null`; `truncated` says more runs matched than `top`.
- Scored from the apps' index snapshots (never the Postgres search rows). A
  run's similar runs, in every app searched, are scored under the target app's
  (the run's) conf `experiment.similar.weights`, in git workspaces only (a
  store workspace has no conf); a text query on its text alone. Archived runs
  only with `archived=1`. `q=<query>` narrows the candidates with the
  [query language](sdk.md#the-query-language), like `vmn-exp similar --query`
  (a bad query: 400).
- `{verstr}` is a full verstr (no `latest`/`@N`). `top` is 1..100; a blank
  `text` or one over 4 KB, a bad app or verstr: 400. An unknown run or
  workspace: 404. Viewer role; ETag/304. A request that cannot answer within
  10 s (an app's index still building) gets a 503 with `Retry-After`; the build
  goes on, so the retry is quick.
- The run page shows a **similar runs** card beside lineage (loaded when
  scrolled near, with a *this app* / *all apps* choice): each run's link
  (labelled with its app when it is another), score, status, goal metric,
  author, age, `(+N runs)`, its reasons as chips and its intent, collapsed.
- The leaderboard's query bar has a **similar** toggle inside it: the box text
  then goes to the per-app text route, with every filter token (query, branch,
  status, search) as `q` (and the archived token), and a results card replaces
  the charts and table; leaving the mode restores the typed text and the table.
- The leaderboard has one filter grammar: the query bar shows every filter as a
  removable token worded as its clause (`status = "failed"`, `branch = "main"`,
  `text ~ "batch"` for free text over name/verstr/note/branch, `archived`, and each
  top-level `and` conjunct of the query). The status chips, branch picker and
  archived switch (one toolbar, a single Tab stop; the arrow keys move inside
  it) write tokens; a hand-typed `status = ...`/`status in (...)`/
  `branch = ...` clause becomes the same token (Enter commits the text,
  Backspace in an empty box drops the last token). The URL keeps `q`, `status`,
  `branch`, `search` and `archived`. Typed text that compares a word no field
  matches (`lr=0.1`) searches as text instead of failing on the server, with a
  hint offering `params.lr=0.1` (or `metrics.<k>`) when the app has that key.
- A `?` in the query box (sharing one Tab stop with the similar toggle) opens
  query help: this app's `metrics.<k>`/`params.<k>`/`tags.<k>` fields, the
  main row fields, the operators and three examples built from the app's keys
  and the loaded rows' values; picking one puts it in the box. Escape closes
  it and returns focus to the `?`.
- The run log describes `features` entries as `features: N files, M functions,
  K commits (author)` and intents as `intent: <first line> [keywords]`.

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
