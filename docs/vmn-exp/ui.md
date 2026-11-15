# vmn-exp ui

`vmn-exp ui` serves a web dashboard and REST API over your vmn repos and
experiment stores. Reads go straight to git tags and `.vmn/` files (or the
store) and never take the repo lock; mutations run as real `vmn` / `vmn-exp`
subprocesses.

- [Install](#install)
- [Localhost](#localhost)
- [Flags](#flags)
- [Workspaces](#workspaces)
- [Remote deployment](#remote-deployment)
- [Signing in](#signing-in)
- [Actions](#actions)
- [The index](#the-index)
- [Diagnostic dumps](#diagnostic-dumps)
- [Run status in the dashboard](#run-status-in-the-dashboard)
- [Outer runs and the outer run's page](#outer-runs-and-the-outer-runs-page)
- [The run page](#the-run-page)
- [App settings page](#app-settings-page)
- [Saved and team views](#saved-and-team-views)
- [Leaderboard columns](#leaderboard-columns)
- [Grouped board](#grouped-board)
- [Compare](#compare)
- [Keyboard](#keyboard)
- [API](#api)

## Install

The dashboard is the `ui` extra, `pip install "vmn-exp[ui]"` (see
[client-guide.md](client-guide.md#1-install)). Without the extra, `vmn-exp ui`
prints an install hint and exits. An
`s3://`, `gs://` or `az://` store (`--store` or a `server.yml` workspace) also
needs its storage extra (`s3`, `gcs` or `azure`, e.g.
`pip install "vmn-exp[ui,s3]"`); without it the server refuses to start.

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
| `--metrics-ended-hours` | `24` | Keep an ended outer run's gauges on [`/metrics`](server.md#prometheus-metrics) this many hours |
| `--no-browser` | off | Don't open a browser (one opens only for a loopback `--host`) |
| `--diag-every` | off | Write a [diagnostic dump](#diagnostic-dumps) every N seconds (keeps the last 20) |

`vmn-exp ui` serves by default. Its maintenance verbs are subcommands, each
with its own flags (`vmn-exp ui <verb> --help` lists them):
`cache resync|rebuild [--workspace]` ([server.md](server.md#self-healing-and-resync)),
`onboarding` ([byo-bucket.md](byo-bucket.md)), `backup <path>`
([server.md](server.md#standalone-vs-configured)) and [`diag`](#vmn-exp-ui-diag). The source flags
`--config`, `--db`, `--token`, `--data-dir`, `--repo` and `--store` go before
or after the verb; the serve flags above go before it and only matter to
`cache` (its `--host`/`--port` find a running server). A flag of another mode,
such as `vmn-exp ui --pid 3` or `vmn-exp ui onboarding --port 1`, is a usage
error (exit 2).

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
  `auth.oidc` is configured (see [server.md](server.md#authentication)) or
  `--read-only` is given, which still serves reads to anyone who can reach
  the port.
- **TLS and users**: put a reverse proxy (nginx, Caddy) in front; vmn does not
  terminate TLS or manage accounts.
- **Host allowlist** (no token only): `/api`, `/metrics` and `/auth` answer
  only a `Host` of `localhost`, `127.0.0.1`, `[::1]`, a non-wildcard `--host`,
  or an `--allowed-host`; anything else is 403. This stops DNS-rebinding pages
  reaching a token-less server on your machine. The web page and its bundle
  hold no data and stay open, so health probes by pod IP still get 200.
- **Cross-site writes**: a POST/PUT/PATCH/DELETE to `/api`, `/metrics` or
  `/auth` whose `Origin` (or `Referer`) names another site than `Host` is 403
  unless that site is an `--allowed-host`, and mutating `/api` requests must
  send `Content-Type: application/json` (415 otherwise). curl and scripts that send
  neither header are unaffected.
- **Paths**: URL app names, verstrs and artifact paths are validated (400 on
  `..` and the like); the SPA fallback serves only files inside `static/`.
- **Symlinks in a record**: in a `file://` store or a git workspace, a run
  file that is a symlink whose target is outside the run's record dir is
  never served. It is left out of the record's listing, so it is neither
  indexed nor parsed, and it is left out of the artifact list. Reading it
  answers as a missing file: an artifact download, a table or the
  `output_tail` 404s or is empty, and a linked-out `metadata.yml` hides the
  run. A symlink that stays inside the record dir still works. Job-side SDK
  reads do not check this, so a job can still read back a checkpoint it
  linked in from another volume. The UI does not show that file; to see it
  there, copy it into the record.

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
   `failed`, with the exit code and the captured log. With authentication on,
   only a viewer of the job's workspace in its org sees it; anyone else gets
   the same `404` as for an unknown id.

| Action | Body | Runs |
|---|---|---|
| `stamp` | `{"release_mode", "prerelease"?, "dry_run"?}` | `vmn stamp --release-mode=<mode> [--pr=<prerelease>] [--dry-run] <app>` |
| `release` | `{"verstr"?}` | `vmn release [--version=<verstr>] <app>` |
| `goto` | `{"verstr"?}` | `vmn goto [--version=<verstr>] <app>` |
| `restore` | `{"verstr"}` | `vmn-exp experiment restore <app> --version=<verstr>` |
| `prune` | `{"keep"}` or `{"older_than"}` | `vmn-exp experiment prune <app> --keep=<n>` / `--older-than=<d>` |
| `exp_create` | `{"note"?, "metrics"?: {k: v}}` | `vmn-exp experiment create <app> [--note=<text>] [--metrics=<k>=<v> ...]` |
| `exp_add` | `{"verstr", "note"?, "metrics"?}` (one of the two) | `vmn-exp experiment add <app> --version=<verstr> ...` |
| `note` | `{"verstr", "note"}` | `vmn-exp experiment add <app> --version=<verstr> --note=<text>` |
| `exp_tag` | `{"verstr", "set"?: {k: v}, "remove"?: [k]}` (at most 100) | `vmn-exp experiment tag <app> <verstr> [k=v ...] [--remove=<k> ...]` |
| `exp_archive` / `exp_unarchive` | `{"verstrs": [...]}` (at most 500) | `vmn-exp experiment archive` / `unarchive <app> <verstr> ...` |
| `exp_rewind` | `{"verstr", "step"}` | [`vmn-exp experiment rewind`](experiments.md#rewind) `<app> --version=<verstr> --step=<n>` |
| `exp_push` | `{"verstrs"?: [...]}` (empty: every local run) | [`vmn-exp experiment push`](experiments.md#offline-recording-and-push) `<app> [--version=<verstr> ...]` |

The job's `command` is that argv: the app and other positionals come first
and every option is one `--flag=value` token, so no body value can be read as
a flag, whatever it starts with. Fields are checked before anything runs, and
a bad one answers `400`:

- `verstr`, `verstrs`: run versions (one path component, not starting with `-`).
- `release_mode`: `major`, `minor`, `patch` or `hotfix`; `prerelease`: a printable string.
- `keep`: an integer `>= 1` (the CLI still takes `--keep 0`); `older_than`: `<N>d`, `<N>w` or `<N>h`.
- `note`: a string of at most 16 KiB; it may start with `-`.
- `metrics`: an object; names as on the CLI (not starting with `-`, no `=` or
  whitespace), values numbers or strings.
- tag keys and values: printable, not starting with `-`, at most 64 / 256 characters.

Each job runs in the workspace as a subprocess, so it takes the per-repo lock
like terminal use, and at most one runs per workspace. A job has stdin closed
and fails after 30 minutes; the server keeps the last 200 jobs and the last
1 MB of each log. A restore or goto over a dirty tree auto-saves the work
first, and the job log names the `vmn goto` that brings it back.

A store workspace's edits ([server.md](server.md#edits-on-store-workspaces))
run in the server process, also as jobs: the request answers `202` at once,
whatever the store does. A store call (a bulk action: each batch of 500) that
does not return within the same 30 minutes fails its job with exit code `-1`
and `Job timed out after 1800s: the store did not answer`. That call is not
cancelled, so the workspace takes no new action until it returns: meanwhile
a submit answers `409` `The previous action is still waiting for the store`.

On a bucket store an edit is written to the server's buffer before it is
uploaded. An edit whose upload fails is pending, not lost: its job fails with
the error and `The edit is kept on the server and is pending until it ships`,
and the next action on that workspace uploads it first. If that upload fails
again, the new action does not run and its job says `An earlier edit is still
pending`; a server that exits ships what is still pending.

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
  [`/metrics`](server.md#prometheus-metrics) scrapes see current numbers with no browser open. That costs
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

Embedding `create_app(manager, io=real_io())` directly (tests, scripts;
`real_io` is in `vmn_exp.core.real_io`) leaves the background refresher off
unless you pass `background_refresh=True`; each request then refreshes first
and sees every earlier write. `io` is required: the server reads its clock
from it. `build_app(manager, deps)` serves with a job runner, refresher and
other collaborators you build (`vmn_exp.ui.app_deps.ServerDeps`).

### Store upkeep

Serving a store workspace without `--read-only`, `vmn-exp ui` tidies the store
itself, off the request path (one background thread, after index refreshes,
a pass per app at most every 60 seconds, on the replica that leads the index):

- **Child markers.** Inner runs created before markers existed (or whose
  marker failed to write) get one, so an outer run's page lists its runs with
  one listing instead of waiting for the index. This is what
  `vmn-exp backfill-children` does by hand. A pass that leaves every child
  marked also flags the app as having all its markers (after one listing of
  its run names, to catch runs the index has not seen yet; an attempt that
  does not flag waits two passes, then twice as long each time, up to an
  hour), so the first `vmn-exp prune -v` skips its one-time scan. The flag
  is learned from the index refresher's listing of the app (the flag object's
  size tells complete from dropped, its ETag is the version token), so a
  flagged app costs a pass no read, even right after a restart; `prune -v`
  still reads the flag itself before trusting it.
- **Compaction.** A failed or stuck run whose writer died before compacting
  keeps one metrics segment per 30 s sync, hundreds for a long run; the server
  compacts each one once (newest first, 30 seconds of work per pass), so its
  charts and Compare cost two reads. This is what `vmn-exp watch --compact`
  does by hand.

A run whose compaction fails is logged and retried only after a restart. The
server needs write access to the store's `runs/` area for both; with
`--read-only` it does neither, and the two commands remain.

### Large stores: run the UI on free-threaded Python

Run the UI on free-threaded Python 3.15t, whatever the store's size. With the
GIL, every request and the refresher share one core; a free-threaded Python
uses all of them, and on large stores it also holds less memory. The UI needs
none of your jobs' packages, so it can run on its own interpreter:

```sh
uvx --python 3.15t --from "vmn-exp[ui]" vmn-exp ui --repo .
uv tool install --python 3.15t "vmn-exp[ui]"     # or install it once
```

On a 737k-run S3 store, a cold index took the UI to 112 GB RSS on 3.14 (GIL)
and 74 GB on 3.14t. On 3.15.2t, loading from the built index, it held 18 GB
RSS (19 GB peak) after 40 minutes; warm board pages answered in about 10 ms
and an outer run's summary in 0.1 to 0.2 s.

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
10,000 runs or more, `vmn-exp ui` prints this hint once.

Two costs of a free-threaded build still grow with the heap. On a 486k-run
store, `vmn-exp ui` 0.1.21 on 3.14t grew from 28 GiB to 250 GiB with a constant
row count and stalled for about two minutes at a time, partly from leaks fixed
since; what is left is the runtime's own:

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
  From 200k runs a free-threaded ui therefore turns automatic collection off
  and a `vmn-gc` thread collects on its own clock instead: first after 5
  minutes, then the wait doubles up to an hour while collections find little
  garbage (under 100k objects), and halves when one finds more. Serving the
  board, HTTP polls and S3 reads make almost no cyclic garbage (0 to 30
  objects each). This makes pauses rarer, not shorter: each one still scans
  everything alive. Measured on 3.14.10t, 16 request threads, the heap growing
  from 4M to 17M tracked objects as the 705k-run ui's did (intervals scaled
  down 20 times): 4 collections and 3.4 s paused, against 6 and 5.3 s
  automatic, each 0.1 to 2 s either way. A heap that stops growing is not
  collected automatically at all, so there the clock adds one an hour.

As RSS grows 10%, a collection runs and takes longer than the last one, so
stalls and growth arrive together. The dump's `gc` section and
`vmn-exp ui diag --summarize` show it: count, total and worst pause, recent
pauses, frozen objects, the allocator and its block count next to RSS, and
whether the event loop's worst lag overlaps a GC pause; with collection
scheduled, also how many it ran, its total and last pause, the garbage it
found and the wait until the next one (`gc.policy`).

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
| `s3` | per S3 operation: count, errors by code, retries, in flight, bytes read, latency p50/p95/max; `by_kind`: the same per operation × object kind (`metadata.yml`, `run_state.yml`, `log segment`, `metric stream`, `metric index (.vmx)`, `child marker`, `children listing`, `run listing`, `journal`, `comments`, …), so a flood of `NoSuchKey` names what is missing; `recent_failures` (last 50 failed calls with their keys) and `recent_other_failures` (the same without `NoSuchKey`); `by_thread`: calls outside any request per thread name (pools are named: `vmn-index-load`, `vmn-series-read`, `vmn-listing`, …); clients and their pool sizes; the 10 oldest calls in flight; `prefix_caps`: the per-prefix cap (`limit`) and the 20 most waited-on `(bucket, prefix)`s with `in_flight`/`peak_in_flight`/`waiting`/`waits`/`wait_ms_total`/`wait_ms_max` |
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
and the sort. A metric column without a declared goal reads `(no goal)` in its
header (no arrow, no best, sorts low first); one whose runs declare different
goals reads `(goals differ)` and is treated the same. A value its run's own summary
picked, unlike the schema's (row `metric_policy`), carries a small muted tag
(`min`), and the header reads `loss · mixed` while a loaded row does.
One line under the caption
counts those columns (a second line counts the conflicting ones) and points to conf.yml or the app's settings page to
declare `goal: min|max`; below 640px, where the caption follows every card, the page head
also shows `live · updated Ns ago` (or `paused`) as plain text after the run
count. Above the board, an attention strip (`⚠ 2 stuck · 3 failed in 24h
· 4 unstable · 4 running`, from `experiments-status`) appears while a run is
stuck, one failed in the last 24 hours, one still runs under an outer run
that ended (`2 outlived their outer run`, built in) or one of the app's attention queries
(conf/[settings](server.md#app-settings) `experiment.ui.attention`, e.g.
`tags.health = "unstable"` or `status = "created" and settled = null and
timestamp < ago("1h")`) matches a run; each part links to the board filtered to exactly
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
counts are the app's; under a filter (`q`, status, a search or a preset) the
shown side counts what its board matches and the other side shows no number.
The last view is remembered per app, and `view=`/`kind=` in the URL win.
An app with single runs and no outer runs reads `Runs | All runs` and opens
`Runs` on the Single runs board: its goal metrics are columns, as in All runs.
An app whose runs are not counted yet (or that has none) lists every
top-level run under `Runs` in the outer-run table.
- **Outer runs** has one row per top-level outer run. Each row shows:
  - its tree status, and a run bar with `1,412/2,000 · 3 failed · 2 stuck · 41/min · ETA 14m`. A finished outer run reads `finished 3d ago`, one that ended short reads `ended · 180 never started`, and one with running runs but no completion in 10 min reads `stalled`. Once the outer run itself has ended (succeeded, failed or stuck), its never-started runs are settled: they leave the waiting count (the bar's empty track is then what never ran), and its stuck runs read `N lost`, apart from `N failed` (only those make the tree status `failed`; the bar draws both in its failed share, what did not finish), and the status reads `succeeded · 1 lost` (see [settled runs](experiments.md#outer--inner-jobs-sweeps)). A lost run's own pill reads `stuck · lost`, on the board, in the tree and on its page.
  - An outer run whose own row carries finite metrics `progress` and `progress_total` (`run.set_progress(done, total, unit)`; the unit is the `progress_unit` param) declares its progress: the bar fills that share, the line leads with it and the runs follow (`41/60 dates · 1,415 runs · 3 failed · 20 dates/h · ETA 14m`), and the rate and ETA are the declared progress since the outer run started. Use it when the inner-run count grows as work gets planned. Metrics under other names count once `experiment.ui.progress: {done: <metric>, total: <metric>, unit: <label>}` (conf.yml or the [store settings](server.md#app-settings)) names them; a settings change shows at once.
  - a sparkline of the main metric's spread.
  - its **aggregate** (`rolled`) in the **value** column: the header names it (`median · dates`), the cell reads `0.65` (`≈ 0.65` for an approximate quantile), linked to the unit holding it, its title the source and coverage (`median of 14/16 dates' own date.best_value · 1 duplicate date left out`), `— (no goal)` without a goal. The header's `▾` picks the aggregate, the units (children, runs, a param or tag field), each unit's value (`best`/`own`) and the metric, into the URL's `job_agg*` (`app default` drops them). A single run's cell is its own main metric. One value per unit, aggregated. Walk-forward needs the nested number (the best trial of each date, then the median across dates), not a median over every trial, which measures the search space. The board picks it once for every row (never mixed across rows): `job_agg` (`mean`, `best`, `median`, `min`, `max`, `best10`, `worst10`; the tails follow the metric's goal, so higher-is-better reads `best10 (p90)` / `worst10 (p10)` and lower-is-better flips them), `job_agg_by` (the units: `children`, the default, one per direct child; `field:<params.k|tags.k>`, the nearest run carrying the field on each branch, e.g. `field:params.trade_date`, two units with the same value a counted conflict left out: `median of 15/16 dates · 1 duplicate`, and a carrier nested under another one left out and named: `median of 11 dates · 3 nested under another date, not counted`; `job_agg_nested=1` (`experiment.ui.job_aggregate.nested: true`, the menu's **Nested** `at any depth`) counts carriers at any depth instead, the same value twice still a conflict (plan 36 §2); `kind:<tags.kind>`, a `tags.kind` match at any depth; `runs`, every run below from the merged sketch, labelled `≈`), `job_agg_value` (each unit's `best`, its subtree's best run, the default, or its `own` metric, with no fallback: a unit without it is missing, `median of 12/16 dates`) and `job_agg_metric` (default the main metric; e.g. date runs logging `date.best_value`). A metric without a declared goal has no value (`— (no goal)`). `job_agg=best` (the default) is the subtree's best for every `by`. Every unit with a value counts, finished or not; `n`/`of` is the coverage. The app's default is `experiment.ui.job_aggregate: {agg, by, value, metric, nested}` (conf.yml or the [store settings](server.md#app-settings)), e.g. fgm's `{agg: median, by: "field:params.trade_date", value: own, metric: date.best_value}`; the URL overrides it, and a team view per kind of outer run carries its own. Only top-level rows have one: a [tree](#the-tree) row keeps its own values.
  - runs, failed %, rate, ETA, branch and start.

  - its non-zero attention counts as chips (`2 unstable`), the runs of its tree each attention query matches.
  - an expander (`▸`) before its name that opens its [tree](#the-tree) in place, under the row (on a phone, under its card): its rows flow inline at full height, scrolling with the board (one scrollbar), and only the rows on screen are drawn.
  - its [baseline chip](ui-api.md#baseline-compare) (`▼ best_value from 2024-12 (5 of 41 trade_date values worse than the baseline's p10)`), opening its Overview; the page's outer runs' chips come in one `experiments-baselines` request.

  The status chips match an outer run by its tree, not its own status (a
  launch run ends once it has submitted its runs): **running** keeps it when
  it or any run below it runs (`status = "running" or running_below > 0`),
  **stuck** likewise (`stuck_below`), and **failed**, **succeeded** and
  **created** match its `tree_status` (so a tree with a failed run reads
  failed, and may still read running; a lost run never makes it failed).
  A **lost** chip beside **failed** keeps the trees with lost runs below
  them (`lost_below > 0`, URL `lost=1`). Once **failed** is on, a
  **≥ N% failed** chip beside it keeps only the trees whose failure share
  is at least N instead (`failed_pct >= N`, URL `failed_pct=N`): one failed
  run in 3,000 no longer reads like 40%. N is the app's
  `experiment.ui.failed_pct_threshold` (default 5, `0 < N <= 100`). It is a
  filter, not a status. They travel in `top_q`, beside a preset's query, and
  the command line under the board shows them.

  Every column sorts by what its cell shows (`job:progress`, `job:failed_pct`, `job:rate`, `job:throughput`, `job:value`, `job:total`, `job:started`): **value** is the row's aggregate (`rolled.value`, best-first by its metric's goal, ascending without one), **rate** is a declared progress per minute since the outer run started (`declared_progress.rate_per_min`, `—` without one), **runs/min** the runs finished per minute over the last 10 minutes (`throughput_per_min`, always), and **when** the subtree's first start, else the outer run's own, else its creation labelled `created` (`when_at`, `when_source`). `progress`/`eta_sec` (and an ended row's ETA cell: `ended · 19 dates not done` or `ended · 180 never started`) come from the declared progress when there is one, else from the runs; `progress_source` (`declared`/`runs`) says which; the status column sorts by `job:attention` (needs attention first: error-level matches, stuck runs included, then warn-level ones); the name column is headed `outer run · progress`.
- **Live** and **Review** (`view=live|review`, a second switch `Live · Review`
  beside the first, shown when the app has outer runs) are presets of Outer
  runs, with everything above (attention strip, bars, tree expanders,
  baseline chips, live updates):
  - **Live** ("what is on the cluster now") lists the outer runs in flight
    (their own status or their tree status running, waiting or stuck, or
    any run below them still running, waiting or stuck: `live_below > 0`,
    so a tree with a failed run and others still running stays) or
    finished within the last 6 hours, needs attention first (`job:attention`).
    The runs an ended outer run never started (`settled = "never_started"`,
    [settled runs](experiments.md#outer--inner-jobs-sweeps)) are not waiting: a launch that
    ended with only those below it leaves Live, while a running launch's
    `created` runs keep it there.
  - **Review** ("is this launch good to ship?") lists the ended ones, newest
    first, each with its baseline chip.

  The preset is sent as `top_q` ([API](ui-api.md#outer-runs-scope-and-search)), so the
  filter bar and a search still apply as in Outer runs; a sort picked in the
  header beats the preset's. An outer run whose tree ended short of its plan
  (`16/20 · incomplete`) reads `created`, so it stays in Live. The last view,
  presets included, is remembered per app.
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
In grouped Outer runs (e.g. `group=tags.launch_id`, the attempts of one resumed training), a group's header shows in the value column (beside the label on a phone) the rows' [aggregate](#outer-runs-and-the-outer-runs-page) over the units of all its outer runs pooled (`job_aggregates`): the same `job_agg`, `by`, `value` and `metric` as the rows, never the page's `agg`. A unit found in several attempts (a date rerun by a later launch) counts once, from the latest attempt (the outer run's start, else its creation), and the title names how many came from earlier ones: `median 0.65` titled `median of 16 dates' own date.best_value · 3 from earlier attempts`. A duplicate inside one attempt stays a conflict, left out as on a row (an earlier attempt's copy never fills it in). With `by=runs` the header pools every run of every attempt (the merged sketches); latest-wins does not apply to runs, so nothing is from an earlier attempt. A tail shows its percentile (`best10 (p90)`), `*` marks runs overriding the summary policy, `— (no goal)` without a goal and `—` when no unit has a value.
**One row per group** (the toolbar's toggle, `collapse_all=1` in the URL, so saved and team views keep it; changing the grouping drops it) shows each group as its header row alone: the label, the pooled value with its coverage (`median 0.65 14/16`) and the run counts summed over its outer runs and their lost runs (`1,412 runs · 3 running · 2 failed · 1 lost`), on a phone one card per group; the board's count names the groups beside the outer runs (`14 groups · 44 outer runs`). The per-group fold (`collapse=<key>`) is separate. A column's `job:*` sort (e.g. `sort=job:started`) orders each group's outer runs by it and the groups by their first outer run under it: by **when**, newest first, a group comes by its latest attempt's start; with `order=asc` by its earliest. Groups without the value (no outer run with it) come after, then `(none)`.

**The outer run's page** is what a run with children opens on (`?tab=`).
- **The header** has the name, `@N`, the tree status, the `outer · N runs`
  badge, the [baseline chip](ui-api.md#baseline-compare) (linked to the baseline run),
  the actions and the live indicator, then the full-width run bar and its
  counts.
- **The tabs** (each a URL value of `tab=`):
  - `overview` (the default): KPI tiles (done of expected, in a declared progress's unit with a `runs done` tile beside it, failed, running, waiting, stuck, median and p90 duration, best, and beside it the [aggregate](#outer-runs-and-the-outer-runs-page) by the app's default, `median date.best_value · dates` over `of 14/16 dates' own`), with a split field (`?split=tags.kind` on the page, else `experiment.ui.split_by` from conf.yml or the store settings) a table under them of runs, done, failed, running, waiting and p50/p90 duration per value (each cell opens the Runs tab filtered by that value and status), status over time with completions per minute, the main metric's distribution with p10/p50/p90, the top 10 runs, the top failure clusters, a [pivot heatmap](ui-api.md#pivot-heatmap) of two fields picked from its facets (tags, params, their ancestors' `up.*`, status, branch; cell = runs, the share matching a query, or an aggregate of a metric; each cell opens the Runs tab filtered to its runs), the [baseline](ui-api.md#baseline-compare) card (the run it is compared with, the chip, the rollup deltas and the children paired by key, the worse ones marked), and, for a sweep, the params that matter.
  - `runs`: a `Flat | Tree` switch (`layout=flat|tree`; the app's last choice is remembered, flat until one is made), then either the board scoped to the outer run's subtree, with a facet sidebar (status and per-param value counts or histograms; a click filters) and "Select all N matching", which adds the query to the app's selection (archiving it archives every matching run, with a count confirm first), or [the tree](#the-tree).
  - `charts`: a param-vs-metric scatter of every run, parallel coordinates (a brush filters the Runs tab), top-K curves, and a box plot per param value.
  - `failures`: failed and stuck runs clustered by a failure signature, which masks the numbers, paths and ids in `end_reason`, `signal`, `exit_code` and `error_summary`. Each cluster shows its count, share, first and last seen, top hosts, and the params overrepresented in it (at most 20 distinct values, at least 5 runs and 10% of the cluster, a lift of at least 1.5). It also has "Show these runs" and copy-rerun.
  - `code` and `log`.

  Every number comes from a per-outer-run rollup the index keeps up to date.
  Archived runs count nowhere above them: an archived run with children takes
  its whole subtree out of every outer run above it (its own page still
  counts its subtree), in counts, progress and attention alike.

Without a declared goal, an outer run tracks the app's most common metrics,
never a param folded into metrics. A metric without a goal (a `primary: true`
one too) shows its spread but crowns no best and gets no better/worse
verdict: its rollup entry has `goal: null` and `best: null`, and `ranked`
says whether the main metric has a goal (`ranked: false` without one).

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

### The tree

The tree lays an outer run's runs out by parent, as deep as they nest (a
launch, its dates, their studies, their trials). Each row is a run and the
rollup of its subtree:
- the name, indented by depth, behind its expander, and its `tags.kind`;
- for a run with children its run bar and line (declared progress first), for
  a run without its status;
- the worst attention part over its subtree (error level first, then the most
  runs), e.g. `2 unstable`; a run without children shows the ones it matches;
- the best value on the main metric (linked to that run), its duration and
  `3.1× siblings` ([`duration_ratio`](ui-api.md#experiment-status-fields));
- the columns `experiment.ui.tree_columns` names for its `tags.kind` value
  (conf.yml or the [store settings](server.md#app-settings)), e.g.
  `tree_columns: {study: [m:best_value, p:group], refit: [t:health, c:ratio]}`:
  show keys `m:<metric>`, `p:<param>`, `t:<tag>`, `c:duration|queue|ratio`,
  `c:total` (`runs`) and `c:failed_pct` (`failed`), those two read from the
  node's own subtree rollup (`—` on a run without children), or another row
  field, shown as `label value` chips. A walk-forward's date rows, say:
  `tree_columns: {date: [m:date.best_value, c:total, c:failed_pct]}`.

Children load when a node opens, 100 at a time with a `+N more` row. A node
the server marks `open` (attention in its subtree, or running or stuck runs
below) starts open; healthy ones stay folded, so a 10k-run launch opens as a
handful of rows. Opening or folding a node yourself sticks while the page is
open. Pages showing running runs refresh every 15 s. The tree is a WAI-ARIA
tree grid (`aria-level`, `aria-expanded`, `aria-posinset`/`aria-setsize`):
Up/Down move between rows, Right opens a node (or steps into it), Left folds
it (or steps to its parent), Enter toggles it, Home/End jump. It is
virtualized like the board.

In the Runs tab the tree keeps the tab's filter bar and URL filters
(`status`, `q`, `search`, `branch`, `archived`, `sort`/`order`), so switching
layouts keeps them. A filter matches subtrees: each level keeps the runs that
pass it or have a passing run below, and a node with a passing run below
starts open, so a filter such as `status=failed` leads from the outer run
down to the failed runs.

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

## Saved and team views

A board's **Views ▾** menu saves its URL (filters, sort, columns, grouping;
not the selection) under a name in the browser (localStorage, per app; an
outer run's Runs tab keeps its own). Above them it lists the app's **team
views** (plan 28 P4): conf.yml/[settings](server.md#app-settings)
`experiment.ui.views`, each `{name, page, search, default}` for one page —
`jobs` (the Outer runs view, Single runs too), `runs` (All runs) or `job` (an
outer run's Runs tab) — read-only there. Applying one keeps the page's own
`view=`/`kind=`/`tab=` when its search leaves them out. A page's `default:
true` view is applied when you land on it with no view params in the URL
(only `view`/`kind`/`tab`/`sel`): on every link to the bare page (the
sidebar, a crumb), and on any other landing (a reload, Back, a typed URL)
once per page per browser tab (per outer run for `job`). What you do on the
page sticks: cleared filters or a bare URL left in place stay bare until
the next link; the URL then shows the view's params. An editor gets **Save for team** (optionally as the page's
default, which takes it from the page's other views): the web reads the
settings, adds or replaces the view by page and name, and writes the file
back through the settings `PUT` — rewritten from its parsed form, so YAML
comments do not survive it. A view in conf.yml's `ui.views` hides the
settings' whole list in that checkout.

## Leaderboard columns

By default the leaderboard shows `#`, status, experiment, the metrics whose
`goal` the schema declares (pinned after the experiment column; every metric
when none declares one), up to six params whose values vary across the loaded
runs (as many as fit the window), and `when`. An outer run's experiment cell
adds `tree <status>` when its subtree differs and an incomplete sweep's
`16/20 · incomplete`. Note, tags, the run's
`started`/`ended` dates, its `queue` time, `duration` and `ratio` (its
[`duration_ratio`](ui-api.md#experiment-status-fields), `3.1× siblings`; `show=c:queue`,
`c:duration`, `c:ratio`, plan 28 N4), a column per tag key (the picker's
**tags** section, from the [facets](ui-api.md#facets)' `tag_keys`: `show=t:health`,
`—` for a run without the tag; plan 28 P4) and the rest come from the Columns picker.
Clicking a date, duration or tag header sorts the board by it server-side
(a tag by `sort=tags.<key>`, a to z first). The choices
live in the URL (`show=`/`hide=`, e.g. `show=m:train_loss`, `hide=p:seed`;
`hide=` always hides, except that it still shows a schema-hidden metric, as
before; `pin=`; `pin=-` pins nothing), and dragged
widths/order in the browser. A fade on the table's right edge shows there are
more columns to scroll to.

## Grouped board

The **Group by** menu next to Columns has `none`, then two sections. **Links**:
`parent run`, `forked from`, `rerun of`, `same code` (`code_verstr`). **Fields**:
`branch`, `status`, each `tags.<key>`, and each `params.<key>` with at most 20
distinct values (from the [facets](ui-api.md#facets)). Its **Aggregate** section picks
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
group's aggregate (`?agg=`: `mean`, `best`, `median`, `min`, `max`, `best10`,
`worst10` — the tails the p90/p10 a goal points at —, default conf
`experiment.ui.group_aggregate`, else mean; the cell title says `mean of 16`, and `(no goal)` where `best`
has no goal and so no value), plus `own 0.91` when the target run logged the
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
declared goal (none is guessed from a name). The curves tab has one labelled
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

The HTTP API reference (routes, query parameters, response fields) is in
[ui-api.md](ui-api.md). OpenAPI docs are served at `/api/docs`.
