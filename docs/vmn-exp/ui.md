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
| `--keep-warm` / `--no-keep-warm` | store workspaces on, checkouts off | Keep refreshing every index once loaded, with nobody watching (see [the index](#the-index)) |
| `--no-browser` | off | Don't open a browser (one opens only for a loopback `--host`) |
| `--diag-every` | off | Write a [diagnostic dump](#diagnostic-dumps) every N seconds (keeps the last 20) |

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
  within the last minute (or kept warm, below) gets a thread that refreshes it about once a second,
  with every record re-listed at least once an hour (at most 500 a refresh; on a store
  also 50 a second, so past 180k runs a round takes longer); requests read the latest snapshot, so
  the dashboard lags the files by about a second. Only an app's first request
  waits for the initial load. A failed refresh (say, the bucket is
  unreachable) is logged and the last snapshot keeps being served.
- **Keep-warm**: the server loads every app at startup, and a store
  workspace's apps then keep refreshing while the server runs, watched or
  not, so a cold load runs to the end, store upkeep keeps going and
  `/metrics` scrapes see current numbers with no browser open. That costs
  little: a store's refreshes follow its change journal, so an idle one lists
  only the hinted and live records. A checkout's apps stop refreshing a minute
  after their last request. `--keep-warm` keeps checkouts warm too,
  `--no-keep-warm` lets store apps idle as well (or `server.keep_warm` in
  [server.yml](server.md#serveryml)); the diag dump's `indexes` entries carry
  `keep_warm`.
- **Per-snapshot work**: status, the run tree, filtering and sorting are
  computed once per index generation and paging is a slice. Live runs'
  status is re-derived per 2-second bucket, so `stuck` shows within seconds.
  After each refresh (and at startup) the server builds the app's facets and
  each view's first page ahead of the browser, under the app's conf.yml /
  store settings, so the first request after a refresh is a cache hit.
  The app list is cached per workspace for 5 seconds.

Embedding `create_app()` directly (tests, scripts) leaves the background
refresher off unless you pass `background_refresh=True`; each request then
refreshes first and sees every earlier write.

### Store upkeep

Serving a store workspace without `--read-only`, `vmn-exp ui` tidies the store
itself, off the request path (one background thread, after index refreshes,
a pass per app at most every 60 seconds, on the replica that leads the index):

- **Child markers.** Inner runs created before markers existed (or whose
  marker failed to write) get one, so an outer run's page lists its runs with
  one listing instead of waiting for the index. This is what
  `vmn-exp backfill-children` does by hand.
- **Compaction.** A failed or stuck run whose writer died before compacting
  keeps one metrics segment per 30 s sync, hundreds for a long run; the server
  compacts each one once (newest first, 30 seconds of work per pass), so its
  charts and Compare cost two reads. This is what `vmn-exp watch --compact`
  does by hand.

A run whose compaction fails is logged and retried only after a restart. The
server needs write access to the store's `runs/` area for both; with
`--read-only` it does neither, and the two commands remain.

### Large stores: run the UI on free-threaded Python

With the GIL, every request and the refresher share one core. A free-threaded
Python (3.14t) uses all of them. The UI needs none of your jobs' packages, so it can run on
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

`orjson` has no free-threaded wheel yet, so the `ui` extra leaves it out and
3.14t encodes JSON with the standard library (included above). On a regular
CPython, `pip install "vmn-exp[ui,orjson]"` renders large pages faster. With the GIL on and a watched app of
10,000 to 199,999 runs, `vmn-exp ui` prints this hint once.

**Past ~200k runs, use a GIL build** (3.12, 3.14). A 486k-run server on S3 grew
from 28 GiB to 250 GiB on 3.14t with a constant row count, and stalled for about
two minutes at a time. On 3.14t with that many runs, `vmn-exp ui` warns once.
Two things cause this, and both grow with the heap:

- **The allocator keeps every thread's peak.** A free-threaded build always
  allocates with mimalloc, which gives each thread its own heap. Memory that a
  live worker thread allocated and another thread freed can only be reused by
  that worker. The ui keeps ~100 long-lived threads (request pools, S3 readers,
  refreshers), so its RSS tends toward the sum of each thread's peak. Measured
  on 3.14.10, macOS arm64: rebuilding 300k rows that another thread had freed
  took RSS from 940 MB to 1849 MB on 3.14t. On the GIL build (pymalloc) RSS
  stayed at 810 MB. With 16 to 40 concurrent requests copying rows, RSS settled
  at 3 to 5 times the live table on 3.14t, against 1.5 to 2 times on the GIL
  build. The same retention shows with `PYTHON_GIL=1` on 3.14t and with
  `PYTHONMALLOC=mimalloc` on a GIL build. `MIMALLOC_PURGE_DELAY=0`,
  `MIMALLOC_ARENA_PURGE_MULT=1` and `MIMALLOC_ABANDONED_RECLAIM_ON_FREE=1`
  changed nothing, and 3.14t refuses `PYTHONMALLOC=malloc`. Memory held by a
  thread that exits is reclaimed. These numbers come from macOS; Linux was not
  measured.
- **Every collection stops the whole process.** The free-threaded collector is
  not generational. A collection runs when objects grew by 25% of the unfrozen
  survivors and RSS grew by 10% since the last collection (CPython 3.14
  `gc_should_collect`). Each one stops every thread and scans the whole heap,
  whatever generation `gc.callbacks` reports. Measured: 0.47 to 0.66 s for 8M
  tracked objects (4 GB), against 1.5 s on the GIL build. The GIL build,
  though, runs a full collection only rarely; its frequent young collections
  take under 1 ms. Freed memory the allocator still holds makes a scan up to
  8 times slower for the same live objects. A swapped heap made a scan take
  16 to 32 s on both builds. Objects frozen with `gc.freeze()` (the ui freezes
  everything after it builds a board from scratch) are skipped but still
  walked: 50 ms per 8M objects on 3.14t, about 18 ms per GB of heap. Freezing
  did not make collections more frequent. Under steady churn (as many frees as
  allocations), 3.14t did not collect at all.

As RSS grows 10%, a collection runs and takes longer than the last one, so
stalls and growth arrive together. The dump's `gc` section and
`vmn-exp ui diag --summarize` show it: count, total and worst pause, recent
pauses, frozen objects, the allocator and its block count next to RSS, and
whether the event loop's worst lag overlaps a GC pause.

## Diagnostic dumps

Every line the server logs starts with a UTC timestamp, its level and its
logger (`2026-10-28T13:47:25.830Z [WARNING] vmn_exp.core.index: Index of
my_app: could not read 1.0.0-dev.a…`), uvicorn's and a thread's uncaught
exception included; WARNING and up go to stderr. A warning about one run
names its app and verstr.

When the UI is slow or stuck, take a dump: one JSON file of what the server is
doing, to carry off an air-gapped host (no py-spy needed).

- `GET /api/v1/diag` (admin; without a token, loopback only like the rest of
  `/api`) returns it. The route runs on the event loop with its own auth
  threads, so it answers while every pool thread is busy.
- `kill -USR1 <pid>` writes `<data-dir>/diag/diag-<UTC %Y%m%dT%H%M%SZ>-<pid>.json`
  and prints its path on stderr; it works while the event loop is starved.
- `kill -USR2 <pid>` appends every thread's Python stack to
  `<data-dir>/diag/stacks-<pid>.log`, written from C by `faulthandler`: it
  answers when the SIGUSR1 handler cannot run (a pegged interpreter, a C call
  holding the GIL), like py-spy's `dump` without ptrace or sudo.
  `vmn-exp ui diag --pid` falls back to it when no JSON dump comes within `--wait`.
- `--diag-every <sec>` writes the same file every N seconds, keeping the last 20.

`{"format": 1, "taken_at", "pid", "sections": {...}}`; a section that fails
shows `{"error": ...}` instead of breaking the dump:

| Section | Contents |
|---|---|
| `threads` | every thread's name/ident/daemon and Python stack; identical stacks collapse into one group with a count |
| `requests` | in-flight requests (method, route template, query parameter names — never values —, age, queue wait, thread, bytes sent so far, the S3 calls it made per operation `{n, ms, err}`), the last 200 completed in over 1 s (same fields), per-route count/p50/p95/max since start |
| `pools` | anyio's default thread limiter and the slow-read limiter: borrowed/total/waiting |
| `indexes` | per watched app: rows, records, `loading` progress, generation, seconds since publish/refresh, last refresh duration, refresher thread alive, journaled, full listing due |
| `process` | Python/implementation/free-threaded, vmn and vmn-exp versions, uptime, CPU, RSS, threads, open fds, gc counts/stats, the server's options |
| `env` | names of the set `VMN_*`/`AWS_*` variables, never their values |
| `s3` | per S3 operation: count, errors by code, retries, in flight, bytes read, latency p50/p95/max; `by_kind`: the same per operation × object kind (`metadata.yml`, `run_state.yml`, `log segment`, `metric stream`, `metric index (.vmx)`, `child marker`, `children listing`, `run listing`, `journal`, `comments`, …), so a flood of `NoSuchKey` names what is missing; `recent_failures` (last 50 failed calls with their keys) and `recent_other_failures` (the same without `NoSuchKey`); `by_thread`: calls outside any request per thread name (pools are named: `vmn-index-load`, `vmn-series-read`, `vmn-listing`, …); clients and their pool sizes; the 10 oldest calls in flight |
| `locks` | the server's key locks (report index, index refresh per app, refresher, store upkeep, leaderboard base per app) held or waited on now — holder thread, held for, each waiter and its wait — and per lock acquires, contended, max wait, max held |
| `background` | per background activity (index refresh per app, journal tick, report index refresh, store upkeep, board warm, startup warmup): runs, running now (thread, for how long), last/max duration, last ok, last error |
| `logs` | the last 200 warnings/errors (logger, message, exception type/message, thread), counts per logger and level, the last 50 vmn-exp info lines |
| `gc` | the cyclic collector: enabled, `gil_enabled`, threshold, `freeze_count`; collections, total/max pause (when, which generation), collected/uncollectable, the same per generation, the last 32 pauses (`at`, `ms`, generation, collected, uncollectable), timed by a `gc.callbacks` hook from start to stop; `allocator`: `mimalloc` (every free-threaded build) or `PYTHONMALLOC`'s (default `pymalloc`), `sys.getallocatedblocks()`, the set `PYTHONMALLOC`/`MIMALLOC_*` values |
| `latency` | event-loop lag (a 0.25 s sleep's overshoot) and thread-scheduling lag (a 0.05 s sleep's; the GIL shows here) over the last 5 minutes: p50/p95/max, when the worst was |

Redaction: store URIs and DSNs lose their userinfo and every query value but
`endpoint_url`'s host, the token shows as `set`, and the configured token and
any secret-looking env value (`*SECRET*`, `*TOKEN*`, `*PASSWORD*`, `*KEY*`)
are scrubbed from every string of the dump. Other modules add sections with
`vmn_exp.ui.diag.register_section(name, fn)`.

### vmn-exp ui diag

`vmn-exp ui diag` takes a diagnostic dump of a running `vmn-exp ui` (no
py-spy or network access needed) and prints a short summary: the most common
thread stacks, the slowest in-flight requests, pool saturation, index loading
and S3 latency (p50/p95/max, errors, retries) per operation, and the
collector's pauses (whether the worst event-loop lag was one), the
allocator's block count and RSS per block.

```sh
vmn-exp ui diag --pid 12345                        # SIGUSR1; waits for <data-dir>/diag/diag-<ts>-12345.json
vmn-exp ui diag --pid 12345 --data-dir /srv/vmn-ui --wait 60 -o dump.json
vmn-exp ui diag --url http://host:8265 --token T   # GET /api/v1/diag (admin), writes vmn-exp-diag-<ts>.json
vmn-exp ui diag --summarize dump.json              # summarize a dump carried out of the site
```

`--pid` works when the server is too starved to answer HTTP: the process
writes the dump on SIGUSR1 into its data dir (resolved like `vmn-exp ui`'s
`--data-dir`: flag, `--config`'s `data_dir`, else `~/.vmn-ui`), and
`diag` waits up to `--wait` seconds (default 30) for the new file, then
copies it to `-o` if given. `--url` sends `--token` (or `VMN_UI_TOKEN`) as a
bearer token. The summary skips any section that is missing or failed.

## Run status in the dashboard

Every run row has a status pill (`created`, `running` (pulsing), `stuck`,
`succeeded`, `failed`). Every run is a row, outer and inner alike; an outer
run's pill shows its subtree's rolled-up status. While any run on the page is
running, the leaderboard and the run page poll on their own and show
`● live · updated Ns ago` with a Pause button (Resume restarts it); with
nothing running they show a Refresh button instead. On the leaderboard this
sits in the table's caption, under the board, with the "best in column" legend
and the sort; below 640px, where the caption follows every card, the page head
also shows `live · updated Ns ago` (or `paused`) as plain text after the run
count. Above the board, an attention strip (`⚠ 2 stuck · 3 failed in 24h
· 4 unstable · 4 running`, from `experiments-status`) appears while a run is
stuck, one failed in the last 24 hours, one still runs under an outer run
that ended (`2 outlived their outer run`, built in) or one of the app's attention queries
(conf/[settings](server.md#app-settings) `experiment.ui.attention`, e.g.
`tags.health = "unstable"` or `status = "created" and timestamp <
ago("1h")`) matches a run; each part links to the board filtered to exactly
those runs (`status=stuck`; the failures also get a `finished_at >= "<24h
ago>"` token, newest first; a configured part its query, coloured by its
`warn`/`error` level), replacing the other filters. The same strip sits on
the Outer runs view (its parts open All runs) and on an outer run's page,
counting that run's subtree (its parts open the Runs tab). A filter lists exactly the
runs that match, so the rows behind a link are as many as it counts. App tiles count runs the same way
(archived runs left out). See [Run status](experiments.md#run-status-did-my-job-die) for
how statuses are derived.

## Outer runs and the outer run's page

An **outer run** (`kind = "outer"`, as `vmn-exp list <app> --query 'kind =
"outer"'` selects them) is a run other runs point at with `parent`: a sweep,
a k-fold grid, an eval fan-out, a fleet of pods. It is the unit of the
experiments screen: one outer run can have thousands of runs. (The code and
the URL still say *job*: `view=jobs`, `kind=jobs`, the `job` row field and the
`job:*` sorts keep their names.)

**The experiments page** opens on **Outer runs** (`view=jobs`). Its switch next
to the app name has `Outer runs (N)`, `Single runs (N)` and `All runs`. The
last view is remembered per app, and `view=`/`kind=` in the URL win.
- **Outer runs** has one row per top-level outer run. Each row shows:
  - its tree status, and a run bar with `1,412/2,000 · 3 failed · 2 stuck · 41/min · ETA 14m`. A finished outer run reads `finished 3d ago`, one that ended short reads `ended · 180 never started`, and one with running runs but no completion in 10 min reads `stalled`. Once the outer run itself has ended (succeeded, failed or stuck), its never-started runs are settled: they leave the waiting count (the bar's empty track is then what never ran), and its stuck runs read `N lost`, drawn as failures (see [settled runs](experiments.md#nesting)).
  - An outer run whose own row carries finite metrics `progress` and `progress_total` (`run.set_progress(done, total, unit)`; the unit is the `progress_unit` param) declares its progress: the bar fills that share, the line leads with it and the runs follow (`41/60 dates · 1,415 runs · 3 failed · 20 dates/h · ETA 14m`), and the rate and ETA are the declared progress since the outer run started. Use it when the inner-run count grows as work gets planned. Metrics under other names count once `experiment.ui.progress: {done: <metric>, total: <metric>, unit: <label>}` (conf.yml or the [store settings](server.md#app-settings)) names them; a settings change shows at once.
  - the best run on the main metric, linked (`—` when no goal is declared), and a sparkline of the metric's spread.
  - runs, failed %, rate, ETA, branch and start.

  - its non-zero attention counts as chips (`2 unstable`), the runs of its tree each attention query matches.

  Every column sorts (`job:progress`, `job:failed_pct`, `job:throughput`, `job:best`, `job:total`, `job:started`); the status column sorts by `job:attention` (needs attention first: error-level matches, stuck runs included, then warn-level ones); the name column is headed `outer run · progress`.
- **Single runs** lists the top-level runs without children.
- **All runs** is the flat board with Group by ([below](#grouped-board)).

An **`outer · N runs` badge** marks an outer run wherever it shows: beside its
tree status in All runs' name cell, on the phone's cards, in its page header,
on its Compare chip and in ⌘K. N is the subtree's run count the row already
carries; the badge links to the outer run's page.

Search and the query bar match every run of the app, whichever view is open:
- In Outer runs, the list narrows to the outer runs that match or have
  matching runs. A line reads `2 outer runs · 413 runs match · show all 413
  runs`, and each outer run carries a `412 matching runs` chip that opens its
  Runs tab filtered.
- ⌘K finds any run by `@N`, name or verstr prefix.

**The selection** belongs to the app, not to one board, so runs from several
outer runs can be picked and compared:
- It is kept per workspace and app in sessionStorage. It follows you across
  Outer runs, All runs, outer run pages and inner run pages, and is capped at
  500 runs. A `sel=` in a shared link replaces it on load and then leaves the
  URL. Compare keeps its own `compare-runs?sel=`.
- One tray at the bottom of every page of the app (boards, outer and inner run
  pages, compare-runs, the stamp tree, actions) shows it while anything is
  picked: `7 runs selected · from 3 outer runs ▾ · Compare (7) · Archive · ✕`.
  An outer run ticked in Outer runs counts as one run, the outer run itself,
  never its subtree. The board on screen adds its own actions (select all
  matching, Unarchive on an archived view); on the Compare page, Compare
  replaces the current comparison.
- "Select all N matching" on an outer run's Runs tab adds that query (the
  outer run, its filter and status) to the selection instead of replacing it,
  so picks from other outer runs stay: `4,012 runs selected · from 3 outer
  runs`. Selecting the same query again replaces its entry. Its loaded runs
  are part of it, not counted twice; unticking one of them turns the query
  back into those loaded runs minus that one.
- `from 3 outer runs ▾` expands the picks grouped by outer run. Each pick
  links to its run page and has its own remove button; a selected query is one
  removable entry, e.g. `all 4,000 matching in hist-0012 (status = failed)`.
- Archive counts every selected query on the server first (`dry_run`), then
  runs one archive by query per query plus one for the other picks. Compare
  can't take thousands of runs: with queries selected it compares the picks
  plus the first 10 loaded runs of each query, in the board's order, and its
  tooltip says so.
- A pick that a selected query also matches but the board never loaded is
  counted once: the tray asks the list endpoint (`scope`, `q = (<query>) and
  verstr in (…)`) and leaves such picks out of the by-verstr bodies; until it
  answers the count reads `≤N`. Tag (next to Archive) takes `key=value` tags
  to set and keys to remove, counts the runs it changes, then runs one
  `exp_tag` by query per query plus one (`verstr in (…)`) for the other picks.
- A status region announces each count change. `x`, `shift+x` and the
  checkboxes pick runs. Esc clears the picks only on a board's page.

Group by groups the rows of the view it is in: outer runs in Outer runs, runs
across outer runs in All runs, and runs inside one outer run on its Runs tab.
A group of more than 50 runs has no fold; its header button adds the group's
clause as a filter.

**The outer run's page** is what a run with children opens on (`?tab=`).
- **The header** has the name, `@N`, the tree status, the `outer · N runs`
  badge, the actions and the live indicator, then the full-width run bar and
  its counts.
- **The tabs** (each a URL value of `tab=`):
  - `overview` (the default): KPI tiles (done of expected, in a declared progress's unit with a `runs done` tile beside it, failed, running, waiting, stuck, median and p90 duration, best), with a split field (`?split=tags.kind` on the page, else `experiment.ui.split_by` from conf.yml or the store settings) a table under them of runs, done, failed, running, waiting and p50/p90 duration per value (each cell opens the Runs tab filtered by that value and status), status over time with completions per minute, the main metric's distribution with p10/p50/p90, the top 10 runs, the top failure clusters, a [pivot heatmap](#pivot-heatmap) of two fields picked from its facets (tags, params, their ancestors' `up.*`, status, branch; cell = runs, the share matching a query, or an aggregate of a metric; each cell opens the Runs tab filtered to its runs), and, for a sweep, the params that matter.
  - `runs`: the board scoped to the outer run's subtree, with a facet sidebar (status and per-param value counts or histograms; a click filters) and "Select all N matching", which adds the query to the app's selection. Archiving it archives every matching run, with a count confirm first.
  - `charts`: a param-vs-metric scatter of every run, parallel coordinates (a brush filters the Runs tab), top-K curves, and a box plot per param value.
  - `failures`: failed and stuck runs clustered by a failure signature, which masks the numbers, paths and ids in `end_reason`, `signal`, `exit_code` and `error_summary`. Each cluster shows its count, share, first and last seen, top hosts, and the params overrepresented in it (at most 20 distinct values, at least 5 runs and 10% of the cluster, a lift of at least 1.5). It also has "Show these runs" and copy-rerun.
  - `code` and `log`.

  Every number comes from a per-outer-run rollup the index keeps up to date.

Without a declared goal, an outer run tracks the app's most common metrics,
never a param folded into metrics. It shows their spread but crowns no best
(`ranked: false`).

**An inner run's page** carries an outer run context bar: `Outer run <name> ›
run 1,903 of 2,000 · rank 1 of 1,409 on val_loss · ‹ prev  next ›`. It also
shows the run's value marked on the outer run's distribution. Prev and next
follow the Runs tab's order (`from=`/`at=` in the URL), and `[` / `]` step
between runs.

**Compare** takes outer runs too. An outer run that logs metrics itself (its
aggregates) compares like any run. One that logs none gets a note on Curves
and Table, `kfold-cv is an outer run of 5 runs and logs no metrics itself`,
with `Compare its best run` (swaps it for its best run on the primary goal,
from `experiments/{v}/summary`'s `top`, else its first run) and `Add its 5
runs` (at most 20, and the note says so when capped).

Live pages update from the server's change stream (SSE, `.../events`) and
poll only as a fallback.

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

A run with children opens the [outer run's page](#outer-runs-and-the-outer-runs-page) instead;
its runs are the Runs tab, not a card.

## App settings page

`/ws/{ws}/app/{app}/settings` (sidebar Settings, ⌘K `settings`) edits the app's
[store settings](server.md#app-settings): the YAML as saved, with who saved
it and when. Save sends it to the server, which refuses invalid settings
with the reason (shown under the text, the edit kept); a stored file that
does not parse is flagged as ignored. Viewers, read-only servers and stores
without edit access see it read-only, with the reason.

## Leaderboard columns

By default the leaderboard shows `#`, status, experiment, the metrics whose
`goal` the schema declares (pinned after the experiment column; every metric
when none declares one), up to six params whose values vary across the loaded
runs (as many as fit the window), and `when`. An outer run's experiment cell
adds `tree <status>` when its subtree differs and an incomplete sweep's
`16/20 · incomplete`. Note, tags, the run's
`started`/`ended` dates, its `queue` time, `duration` and `ratio` (its
[`duration_ratio`](#experiment-status-fields), `3.1× siblings`; `show=c:queue`,
`c:duration`, `c:ratio`, plan 28 N4) and the rest come from the Columns picker.
Clicking a date or duration header sorts the board by it server-side. The choices
live in the URL (`show=`/`hide=`, e.g. `show=m:train_loss`, `hide=p:seed`;
`hide=` always hides, except that it still shows a schema-hidden metric, as
before; `pin=`; `pin=-` pins nothing), and dragged
widths/order in the browser. A fade on the table's right edge shows there are
more columns to scroll to.

## Grouped board

The **Group by** menu next to Columns has `none`, then two sections. **Links**:
`parent run`, `forked from`, `rerun of`, `same code` (`code_verstr`). **Fields**:
`branch`, `status`, each `tags.<key>`, and each `params.<key>` with at most 20
distinct values (from the [facets](#facets)). Its **Aggregate** section picks
what a group header shows per metric: `mean`, `best`, `median`, `min` or
`max`. The choice lives in the URL as `?group=` (`parent`, `forked_from`,
`rerun_of`, `code_verstr`, `branch`, `status`, `tags.<k>`, `params.<k>`,
an ancestor's field such as `up.params.trade_date` or
`up(tags.kind = "study").params.group` (URL only, not in the menu), `none`)
and `?agg=`, so saved views keep it. Without `?group=` the board is
grouped by parent run when some run has a parent, else not grouped. Without
`?agg=` it shows the aggregate the server applied — conf.yml's
`experiment.ui.group_aggregate` (branch conf respected), else the app's
[store settings](server.md#app-settings), else the mean. Grouped, the board stays live while
any run in any group is running, loaded or not. Ungrouped, every run is one
row, sorted and paged as a flat list.

A group's run counts belong to its head (for a link, the target run — the
outer job), so they sit on its header row, not in columns: a small bar in the
status colours (finished runs fill from the left, the empty track is the
waiting runs; a group of one run has none), then the counts in words
(`16 runs · 2 running · 1 failed`). The menu's **Sort groups** row orders
the groups by the aggregate (the default) or by how many of their runs are
in a state: `runs`, `running`, `failed`, `waiting` or `succeeded`, most
first (`sort=c:total`, …; the rows within a group keep their order; a count
sort is dropped with `group=none`).

With a grouping the board lists groups: each
starts with a header row (the fold, the group's label — for a link the
target run's `@N` name and status pill, for `same code` the code verstr with
its base version and branch, for a field `branch = main` — and its status
count in words, `16 runs · 2 running · 1 failed`, or `16 runs · all
succeeded`; `5 of 16 runs · 5 succeeded` while a filter leaves part of the
group, from K1's `rows_unfiltered`), then up to 10 of its rows and a
`+N more` row that loads the rest (a refresh keeps each group as deep as it
was loaded). Each metric column of a header shows the
group's aggregate (`?agg=`, default conf `experiment.ui.group_aggregate`,
else mean; the cell title says `mean of 16`, and `(no goal)` where `best`
falls back to the mean), plus `own 0.91` when the target run logged the
metric itself; the metric headers carry a small aggregate tag. `?collapse=`
lists the closed groups. Sorting orders the groups (by the aggregate) and the rows within
them; 50 groups load per page. A filter keeps the groups with a matching run
and counts only those runs; a link group's header stays even when its target
run does not match. Grouped by parent run, an outer run heads its inner runs'
group, and its own row sits in the group of its parent. Grouped by a link
(parent run, forked from, rerun of), the runs with no link that head no
group are not a group: they are plain rows after the groups (plain cards on
a phone), with no header, no group colour in Charts, and a plain `+N more`
row.

A group header's checkbox selects the group's loaded rows, shut or open (it
is indeterminate while only some are selected); the header's target run is
not one of them, so Compare (N) and Archive count rows. The Charts tab's
bar, scatter and parallel charts colour every charted run by its group (the
board's groups in order, the no-value group grey, a legend above the chart;
parallel's `color by` offers `group` first), reading each run's group from
`experiments-columns`' `group:<field>`.

With rows selected, grouped or not, the Charts tab plots only the selected
runs, under a `Showing N selected · Show all` note. Show all plots every
filtered run again and keeps the selection (a `Show N selected` link goes
back); changing the selection plots it again. Without a selection the charts
plot every filtered run.

Below 640px, where the board is one card per run, each group's header is a
section label above its cards that sticks to the top while you scroll them:
the group's checkbox (as on the desktop header), the fold, the group's name
(a link group's target run, linked), its status count (wrapped, never cut
short), and the group's aggregate on the card metric (`0.2327 val_loss mean`).
Its `+N more` is a button under the last card.

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

The plan-20 `overlay?runs=` and `compare?v=&to=` pages are gone (plan 22
G8), with no redirect: everything vmn links to is `compare-runs?tab=…`.

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
- **Boards**: `j`/`k` (or ↑↓ in the table) move the active row, `x` toggles
  its selection, `shift+x` selects a range, Enter/`o` opens it, `/` focuses
  the filter, Esc leaves the row, `?` lists the keys. `density=compact|comfortable`
  (the toggle under the table, remembered per browser) sets the row height.
- **Run pages**: `[` / `]` go to the previous / next run of the outer run.
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
| `GET` | `ws/{ws}/apps/{app}/experiments-pivot?rows=&cols=` | [Pivot heatmap](#pivot-heatmap) |
| `GET` | `ws/{ws}/apps/{app}/experiments-status` | [Status counts and rollup](#status-counts-and-rollup) |
| `GET` | `ws/{ws}/apps-status` | [Every app's status counts](#status-counts-and-rollup), one request |
| `GET` | `ws/{ws}/apps/{app}/experiments-diff?v=&to=` | [Code diff of two runs](#diffs-and-artifacts) |
| `POST` | `ws/{ws}/apps/{app}/series` | [Series of many runs](#series-for-many-runs) |
| `GET` | `.../experiments/{verstr}/metric-keys?prefix=&offset=&limit=` | [A run's metric names, paged](#zoom-and-many-keys) |
| `GET` | `ws/{ws}/apps/{app}/metrics-schema` | The [effective metrics schema](#paging-sorting-and-order) |
| `GET` / `PUT` | `ws/{ws}/apps/{app}/settings` | The app's [store settings](server.md#app-settings) (`PUT {"text"}`: editor) |
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

### Outer runs, scope and search

- **Rows** carry `root` (the top-level ancestor's verstr, null at the top) and
  `failure_sig`. Both are query fields, as is `under("<verstr>")` (in that
  run's subtree).
- **`experiments?top=1|jobs|singles`** lists top-level runs only (all, those
  with children, those without). An outer run's row carries `job`: `{total, counts,
  done, expected, progress, failed_pct, throughput_per_min, eta_sec,
  declared_progress, metric, best, best_verstr, best_idx, spread}`. It takes
  the `job:*` sorts. `declared_progress` is `{done, total, unit,
  rate_per_min}` when the outer run declares one (else null); `progress`
  and `eta_sec` are then its, while `done`/`expected`/`counts`/
  `throughput_per_min` stay run counts. The outer run's `summary` carries
  the same.
  - With `match_subtree=1` and a `q`, an outer run matches when it or any run of its
    subtree does. Each row then gets `matched`, and the page gets
    `jobs_matched`/`runs_matched`.
  - `experiments-facets` returns `jobs`/`singles` counts.
- **`scope=<verstr>`** keeps that run's subtree, without the run itself. It
  works on `experiments` (flat and grouped), `experiments-columns`,
  `experiments-facets` (which also takes `q`/`status`), `experiments-importance`
  and `experiments-pivot`. An unknown run is a 404.
- **Grouped answers** give every group a `clause`, the filter text that
  selects exactly it. With `top=`, groups add `job_counts`, `runs`, `failed`
  and `job_aggregates` (over the outer runs' best values).
- **`experiments/{v}/summary`** is the outer run's rollup: counts, `expected`,
  `ended` (its own status succeeded/failed/stuck), `never_started` and `lost`
  (its settled runs, never in `counts`; `done` takes the lost ones, an ended
  run's ETA only its running and waiting ones), progress, throughput, ETA, `metric`, `ranked`, per-metric
  `{n,min,max,mean,best,best_verstr,p10,p50,p90,hist}`, duration p50/p90,
  failure signatures, `top` (10 best) and a `timeline` (epoch-second buckets
  of `started`/`succeeded`/`failed`, plus `released` where runs were handed
  back, sparse; the chart draws releases per minute beside completions).
  - `?split=tags.<k>|params.<k>` (default: `experiment.ui.split_by` from conf.yml, else the store
    settings; another field is a 400)
    adds `split` (the field, else `null`) and `by`: per value
    `{key, label, clause, total, counts, done, never_started, lost,
    failed_pct, duration: {n, p50, p90}}`, most runs first, at most 12, then
    one `{key: null, label: "other", other: true, ...}` for the rest. `key`
    is the group key (`∅` = no value, label `(none)`), `clause` the query
    selecting the value's runs (`other`: `<field> not in (...)`). The index
    keeps one tally per (parent, value) for at most 12 values a parent (the
    first in key order; the rest under the parent's `other`), moved by the
    same deltas as the rollup. A value some parent may hold under its `other`
    is never listed: its runs count under `other`, so a listed value's
    numbers are always its whole subtree's.
- **`experiments/{v}/failures?limit=`** returns the clusters. Both outer run
  endpoints 404 for a run without children, and answer 304 on an early ETag.
- **`search?text=&limit=`** is ⌘K's run search over every run. It ranks exact
  `@N`, then verstr prefix, then name prefix, then a substring in any indexed
  field.
- **`events?scope=<verstr>|top`** is a Server-Sent Events stream of
  `change` events (`{generation, changed: {rows, jobs}}`), coalesced to one a
  second, with a heartbeat every 25 s. It is 404 without a background
  refresher and 503 past 256 streams.
- **`POST actions/exp_archive|exp_unarchive|exp_tag`** also take
  `{scope, q, status, archived}` instead of `verstrs`. `dry_run: true`
  returns `{count, sample}`. Otherwise the action runs as a job in batches of
  500, with `progress: {done, total}`.

### Experiment status fields

Every row of `.../experiments` and the run detail carry:

| Field | Meaning |
|---|---|
| `status` | `created` / `running` / `stuck` / `succeeded` / `failed` (derived, never stored) |
| `exit_code` | the command's exit code once finished, else `null` |
| `started_at` / `finished_at` | ISO-8601 timestamps |
| `heartbeat` | last heartbeat refresh |
| `stale_sec` | seconds since the last proof of life (the fresher of the heartbeat and the store's write time of `run_state.yml`) |
| `duration_sec` | wall-clock run time once finished (elapsed while running) |
| `queue_sec` | seconds from creation (`timestamp`) to `started_at`, never below 0; `null` until the run starts |
| `duration_ratio` | board rows only: `duration_sec` over the median duration of its siblings, the finished (succeeded or failed), unarchived runs with the same parent and the same value of `experiment.ui.split_by` (none: the parent alone; the median at P3's rank as its sketches report it, within 1 %). A running run uses its elapsed time. `null` with fewer than 3 finished siblings (the run counted), without a parent, and for a waiting, stuck or end-less run. The board's `ratio` column reads `3.1× siblings`; `q=duration_ratio > 3` finds the outliers |
| `pid` / `host` / `command` | what ran, where |
| `last_metric_at` | when a metric was last logged, to spot a run that is alive but not progressing |
| `parent` / `children` | verstrs linking outer and inner jobs |
| `kind` | `outer`, `inner` or `single` |
| `depth` | nesting depth, for indenting the list |
| `settled` | `never_started` (created), `lost` (stuck, or released) or `outlived` (running, counted as running) for a run under an outer run that ended, else `null`: derived, the run's own `status` stays |
| `tree_status` | rollup over the run and its subtree (`failed > stuck > running > created > succeeded`); a container outer's own `created` and a `never_started` run are left out, a `lost` run adds `failed`, an incomplete sweep that has not ended adds `created` |
| `sweep_planned` / `sweep_trials` | a sweep outer's planned trials (grid size, else `run_cap`) and the trial slots its inner runs fill; absent for other runs and uncapped random/bayes sweeps. While `sweep_trials < sweep_planned` the UI reads `16/20 · incomplete`, and the detail's `status.fleet.expected` is the planned size |
| `signal` / `end_reason` | the signal that ended (or released) the run (`SIGTERM`); `stopped` for an early-stopped sweep trial, `released` for a run handed back unfinished (`run.release()`, status `created`) |
| `released_at` / `resume_count` | the run's last release (kept once it is reopened) and how many times it was reopened (`start_run(run_id=)`), else `null` |
| `error_summary` | `Type: message` of a failed run's recorded `error`, else `null` |

The run detail also groups them under a top-level `status` object, which also
carries `error`: the run's full `error` mapping (`type`, `message`,
`traceback`, `source`, `output_tail`) or `null` — never on list rows. An
outer run's `status.fleet` is `{expected, counts}` (no `children`: its runs
are the outer run page's Runs tab). The list
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
 "never_started": 0, "lost": 0, "failed_recent": 1, "rollup": "stuck"}
```

Counts the non-archived runs by derived status (all five keys always present).
A run an ended outer run settled counts as `never_started` or `lost` instead,
never in `counts` (`total` holds every run), so a lost run raises no `stuck`;
an `outlived` one (still running) stays in `counts.running`.
`failed_recent` counts failures that finished within the last 24 hours. `rollup` is
`stuck` if any run is stuck, else `failed` if `failed_recent > 0`, else
`running` if any runs, else `null`. A known app with no runs answers zeros; an
unknown app is a 404 `{"detail", "code": "app_not_found"}`, checked against the
checkout (`.vmn/<app>/conf.yml`) and the store (any run or snapshot record),
not the cached app list. ETag/304, accurate to the hour for `failed_recent`.

With attention queries configured (`experiment.ui.attention`, at most 8, see
[server.md](server.md#app-settings)), the summary carries a count for each,
after the built-in stuck and failed-in-24h parts the strip shows first:

```json
"attention": [{"key": "unstable", "label": "unstable", "level": "error", "count": 4,
               "q": "tags.health = \"unstable\""}]
```

A count is the length of the board's own cached order for `q` (non-archived
runs), so a time-free query moves with the index deltas and an `ago()` one is
rebuilt at most once a minute (about 0.2 s at 100k runs). A query that does
not compile counts `null` and carries `error`. `?scope=<verstr>` answers the
whole summary over that run's subtree, without the run (an outer run's page;
counts and recent failures from its rollup; 404 for no such run). On the
Outer runs view (`experiments?top=...`) each row's `job` carries `attention:
{key: n}` (the runs of its tree, itself included, each query matches) and
`attention_rank`, which `sort=job:attention` orders by.

One part is built in, configured queries or not, and comes before them:
`{"key": "outlived", "label": "outlived their outer run", "level": "warn",
"q": "settled = \"outlived\""}`, the runs still running under an outer run
that ended. It is counted from the live rows (never a board order) and, in
the summary and in a row's `job.attention` alike, present only while it
counts any, so an app with none and no queries has no `attention`. A list `q` with
`ago()` is pinned to the minute, so its ETag moves with the clock.

With background refresh (`vmn-exp ui`), the summary also carries how fresh
the app's index is, read without I/O, so a dashboard or a load balancer sees
an index that serves old data or stopped keeping up:

```json
"freshness": {"as_of": "2026-10-22T19:44:00.120000+00:00", "refreshing": true,
              "refresh_running_sec": 125, "phase": "full_listing", "progress": 0.45,
              "refresh_failing": false, "last_error": null, "stale_after_sec": 300}
```

- `as_of`: the wall time the last completed refresh started (`null` before
  one). It persists in the index file (at most once a minute), so a restarted
  server serving its persisted rows says they date from its last refresh.
- `refreshing` / `refresh_running_sec`: a refresh is running, for how long
  (`null` when none).
- `phase`: what that refresh does — `full_listing` (every record's files),
  `journal` (a store's journaled sweep: hinted and live records), `listing`
  (a checkout's names-only listing), `loading_new` (reading the new or changed
  records it found), else `idle`. `progress` (0..1, else `null`): how far an
  S3 full listing's walk is among the index's known keys, or the share of new
  records read. A store app's full listing runs behind serving (see
  [server.md](server.md#how-the-cache-stays-fresh)): between its refreshes
  `phase` stays `full_listing` with the share of records listed as
  `progress`, and `journal` while the app catches up on the change journal
  (a replay after a restart, an overflow, re-reads queued).
- `refresh_failing`: the refresh is failing (`last_error` is its streak's
  last error), its thread is gone, or it has run past 10 minutes (stuck).
- `stale_after_sec`: the age past which the dashboard warns — conf
  `experiment.ui.stale_after_min` of a checkout's app, else the app's
  [store settings](server.md#app-settings) (default 5).
- `unreadable` (absent when none): `{"count": 12, "store_errors": 12,
  "last_error": "ClientError('An error occurred (SlowDown) ...')"}` — the
  records the index set aside unread, retried 60 s later doubling to 10 min:
  `store_errors` of them failed on the store (a throttled, refused or reset
  read), the rest on their own content; `last_error` is the latest failure's
  short repr. The refresh succeeds around them, so this is the only sign of a
  throttled store; a new record stays out and a known one keeps what the
  index had.

Its times count by the minute in the ETag, and what a refresh does only while
the data is stale or the refresh failing (a fresh index's once-a-second
refreshes leave the ETag alone). The dashboard shows a banner under
the topbar, and the boards' count line a short form, when the data is older
than `stale_after_sec` or a refresh runs on data older than that ("Showing
data as of Oct 22 19:44 UTC (4d old). Syncing with the store — listing runs,
~45%. New runs will appear when it finishes."), or when the refresh is failing
("Data is 4d old and the background refresh has not completed for 25m
(last error: …)"); none once a refresh published fresh data. Unless the
refresh is failing, runs set aside unread add a warning to it, or make one
on fresh data ("12 runs could not be read (the store is throttling:
SlowDown); retrying."). It polls the
status every 2 s while a refresh runs on stale data. The refresher heals
itself: an error in any refresh step is logged (a WARNING with the traceback
when a failure streak starts, every 10 minutes while it lasts, and when it
recovers) and never ends its thread; a refresh or journal thread that ended
anyway is restarted by the next request (an ERROR); a refresh running past
10 minutes is warned about once. S3 calls time out (10 s connect, 30 s per
read) and retry in botocore's adaptive mode (a throttling store's `SlowDown`
slows the client down); a refresh or journal tick that failed is retried
`interval_sec` later doubling up to 60 s, and a record the store failed to
read is set aside and read again after 60 s doubling to 10 min.

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
- `sort` also takes any other row field (`duration_sec`, `queue_sec`,
  `duration_ratio`, `stale_sec`, `status`, ...), `tags.<k>` or `params.<k>`
  (plan 28 FS): numbers (bools as 0/1) before strings, ascending unless
  `order=desc`, runs without a value last either way. These orders are cached
  and moved across index generations like the metric orders; a running run's
  `duration_sec`/`duration_ratio` place it again per time bucket. The board's
  `queue`/`duration`/`ratio` columns sort this way.
- `archived=1` includes archived runs, which `.../experiments`,
  `-columns`, `-importance` and `-facets` otherwise leave out (and out of
  `total`).
- Each response carries an `ETag` (index generation, parameters and, while runs
  are live, the status bucket); send it back as `If-None-Match` and an
  unchanged poll is an empty `304`.

The goal comes from the app's effective metrics schema,
`GET .../metrics-schema`: conf.yml's `experiment.metrics` over the app's
[store settings](server.md#app-settings), plus the `goal`/`hidden` runs
declare for names neither has (see
[Metrics schema](experiments.md#metrics-schema-sorting--goals)); a store
workspace has no conf.yml, only the settings and the runs' declarations. It also decides which metrics the
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
code state), a row field: `branch`, `status`, `root` (the top-level outer run), `tags.<key>`,
`params.<key>`,
or an ancestor's field, as the [query language](sdk.md#the-query-language) reads
it: `up.params.<key>`, `up.tags.<key>`, `up.name`,
`up(tags.kind = "study").params.<key>` (the clause is `<field> = <value>`,
`<field> = null` for the `(none)` group). A change to an ancestor's params,
tags or name regroups the runs below it.

```
{"groups": [{"key", "label",
             "target": {verstr, idx, name, status, tree_status, metrics} | null,
             "loose": false,
             "counts": {total, running, waiting, done, failed, stuck},
             "aggregates": {"<metric>": {mean, best, median, min, max, n}},
             "rows": [...], "rows_total": 5, "rows_unfiltered": 16}],
 "total_groups": 3, "total_rows": 48, "running": 2, "aggregate": "mean"}
```

- `target` is the header run of a `parent`/`forked_from`/`rerun_of` group. A
  target missing from the index (pruned, another app) groups under its verstr
  with `target: null` and the label `<verstr> (not found)`. Runs without a
  value form one group, always last, labelled `(none)`. Its `key` is `∅` (U+2205), which no value's key equals: a value
  whose text starts with `∅` is keyed with it doubled (`∅x` -> `∅∅x`), so a
  param literally set to `(none)` is a group of its own. Every group carries
  `loose`, true only for that group of a link grouping (`parent`,
  `forked_from`, `rerun_of`): the runs with no link minus those heading a
  group of the grouping (after the filters), so each run shows once; its
  counts, aggregates, `rows_total` and `rows_unfiltered` cover those runs,
  and it is absent when there are none. `total_rows` and `running` count
  every passing run. The board shows a loose group's rows without a header.
- Filters (`q`, `status`, `archived`) select rows; a group shows when one of
  its rows passes, and its counts and aggregates cover the passing rows.
  `rows_total` counts its passing rows, `rows_unfiltered` its rows with the
  same `archived` setting but without `q`/`status` (equal when no filter is
  set; the board's `5 of 16`). Only `q` and `status` are dropped: the web
  client sends its branch and search filters inside `q`, so they are dropped
  too. A link group keeps its `target` even when the
  target fails the filter. A `rerun_of` group's aggregates include the
  original's own value.
- `running` counts the running rows of every group after the filters, not
  only the page's, so a client can poll while any run is live.
- `aggregates` cover each metric's finite values, by each run's summary
  policy; `best` follows the metric's goal and is null without one.
- `sort`/`order` order rows within a group as on the flat list. Groups order
  by `agg=mean|best|median|min|max` of the sort metric (`best` without a goal
  is the mean; groups without a value after the others), and by their first
  row for a date or no metric sort. `sort=c:total|c:waiting|c:running|c:done|c:failed`
  orders groups by that count instead (`waiting` = created, `done` =
  succeeded, `failed` = failed + stuck; the board's Sort groups row),
  most first unless `order=asc`; ties keep the default group order, rows
  within a group keep their default order (no sort), and the no-value group
  stays last. Without `group=`, a `c:*` sort is an unknown metric like any
  other (no row carries it). `agg` defaults to
  `experiment.ui.group_aggregate` of the conf.yml the app reads on the
  checkout's branch (its branch conf when there is one, as `vmn` resolves
  it; a detached HEAD, as in CI, counts as the branch `vmn stamp` resolves
  it to: the CI env's branch, else the branch last checked out, else the one
  branch at or containing it; no branch reads the app's conf.yml), else the
  app's store settings, else `mean`; `aggregate` names what it
  resolved to, and every aggregate is in the payload either way.
- `offset`/`limit` page groups (default and at most 50); `rows_per_group`
  (default 10, 1..100) caps each group's `rows`, lowered so a page holds at
  most 5000 rows. Values out of range are clamped, not refused.
  `group_key=<key>&offset=&limit=` answers that one group with its rows paged
  like the flat list (404 for an unknown key).
- An unknown field or aggregate, or `last`, is a 400. Groupings are kept
  per index generation and moved along with it, so a grouped page costs
  about what a flat one does.

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

- `keys`: comma list of `metrics.<k>`, `params.<k>`, `up.<field>` (an
  ancestor's value, as in a query: `up.params.trade_date`), `timestamp`, `status`,
  `branch`, `name` (the run's name, else its note) and `group:<field>` (the
  run's group key on the board grouped by `<field>`, as the list's `group=`
  takes it, `∅` for no value); anything else is a 400.
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

### Pivot heatmap

`GET .../experiments-pivot?rows=<field>&cols=<field>` crosses the matching
runs by two [group fields](#paging-sorting-and-order) (`tags.<k>`,
`params.<k>`, `up.*`, `branch`, `status`, `failure_sig`, a link, or `root`):
one cell per pair of values (plan 28 N2; the outer run's Overview card and
the reports' [`pivot` panel](reports.md#panels-vmn-panel-blocks)).

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'match=tags.health = "unstable"' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments-pivot?rows=tags.trade_date&cols=tags.group&cell=share&scope=0.4.0-dev.abc"
```

```json
{"rows": [{"key": "2024-06", "label": "2024-06", "n": 240, "clause": "tags.trade_date = \"2024-06\""}],
 "cols": [{"key": "BCA", "label": "BCA", "n": 60, "clause": "tags.group = \"BCA\""}],
 "cells": [[{"n": 24, "value": 0.125, "hits": 3,
             "clause": "tags.trade_date = \"2024-06\" and tags.group = \"BCA\""}]],
 "total": 240, "rows_total": 1, "cols_total": 1, "cell": "share",
 "match": "tags.health = \"unstable\"", "metric": null, "agg": null}
```

- `cell=count` (the default): `value` is the cell's runs. `cell=share&match=<query>`:
  the share of them matching the query (`hits` of `n`). `cell=agg&metric=<m>&agg=`
  `mean|best|median|min|max` (default the app's group aggregate): the aggregate of
  the metric's finite values, `null` when none carries it.
- Takes `scope`, `q`, `status`, `archived`. A bad field, cell or query is a 400.
- Each axis keeps its 200 (rows) / 50 (cols) most common values, ordered by
  value (numbers before text, `(none)` last); `rows_total`/`cols_total` count
  them all. An empty cell is `null`. Headers and cells carry the `clause`
  selecting their runs (`null` when the language can't say the value).
- Kept per index generation; within a `scope` with nothing live under it (a
  settled launch) the pivot is kept until a run of its subtree (or an
  ancestor an `up` field reads) changes, so a finished launch's heatmap is
  built once per process and keeps its ETag (a 304) across generations
  (`ui/pivot_cache.py`). Otherwise ETag/304 like the list.

### Facets

`GET .../experiments-facets[?archived=1]` answers the filter and Group by
vocabulary, each list sorted (`metric_keys` includes numeric params; `total`
counts all runs), with an ETag. `param_values` is each param's number of
distinct values, capped at 21 (the board's Group by menu offers a param only
with at most 20); `parented` counts the runs with a parent (the board groups
by parent run by default when it is non-zero):

```json
{"branches": ["feat/x", "main"], "metric_keys": ["acc", "loss"], "param_keys": ["lr", "opt"],
 "tag_keys": ["team"], "param_values": {"lr": 21, "opt": 3}, "parented": 40, "total": 5000}
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
- Ranked by FTS5 bm25 like the CLI ([how](experiments.md#similar)), never
  from the Postgres search rows (they carry no features or intent). An app
  whose index persists in a SQLite file (a git workspace's
  `<data_dir>/index/`, a store workspace's SQLite cache) is searched in that
  file, which every index save files; any other (a store cached in Postgres,
  `--no-index`) gets a host-local FTS5 database of its own under
  `<data_dir>/index/similar/` (in memory with `--no-index`), kept in step
  with the app's index on every refresh. A
  run's similar runs, in every app searched, are scored under the target app's
  (the run's) conf `experiment.similar.weights`, in git workspaces only (a
  store workspace has no conf); a text query on its text alone. Archived runs
  only with `archived=1`. `q=<query>` narrows the candidates with the
  [query language](sdk.md#the-query-language), like `vmn-exp similar --query`
  (a bad query: 400).
- `{verstr}` is a full verstr (no `latest`/`@N`). `top` is 1..100; a blank
  `text` or one over 4 KB, a bad app or verstr: 400. An unknown run or
  workspace: 404. Viewer role; ETag/304. A request that cannot answer within
  10 s (an app's index or its host-local FTS5 database still being filled)
  gets a 503 with `Retry-After`; the filling goes on, so the retry is quick.
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

JSON is rendered with `orjson` when installed (the `orjson` extra; else the
standard library; NaN/inf become `null` either way) and
gzipped when the client accepts it. The web bundle (`/assets/*`, `index.html`
and client routes) is served `Cache-Control: no-cache` with ETags, so an
upgrade never serves a stale chunk and a reload revalidates to a bodiless 304.
