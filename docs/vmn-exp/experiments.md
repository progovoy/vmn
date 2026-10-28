# Experiments

`vmn-exp` is local-first experiment tracking for any versioned app. An
experiment is a **snapshot of your working tree plus an append-only log of
metrics and notes** — no required training script, no server, no database.
Runs are plain files under `.vmn/store/runs/<app-key>/` (git-ignored, never
committed or pushed), each anchored to an exact version and commit, so
reproducing a result is one `vmn-exp restore` away.

ML training is the headline use case, but anything you can measure fits:
config sweeps, benchmarks, load tests, pipeline outputs. If you can print a
`key=value`, vmn can track it.

New here? [client-guide.md](client-guide.md) walks through a project end to
end. This page is the CLI reference. Elsewhere: the Python SDK
([sdk.md](sdk.md)), the web UI and HTTP API ([ui.md](ui.md)), the model and
dataset registry ([models.md](models.md)), sweeps ([sweeps.md](sweeps.md)),
`vmn snapshot` ([snapshots.md](../snapshots.md)).

- [Mental model](#mental-model)
- [Recording an experiment](#recording-an-experiment)
- [With a command: `exp run` and the metrics file](#with-a-command-exp-run-and-the-metrics-file)
- [Run status: did my job die?](#run-status-did-my-job-die)
- [Outer & inner jobs (sweeps)](#outer--inner-jobs-sweeps)
- [Addressing experiments](#addressing-experiments)
- [Subcommand reference](#subcommand-reference)
- [Structured notes & params](#structured-notes--params)
- [Metrics schema (sorting & goals)](#metrics-schema-sorting--goals)
- [Storage (local, S3, GCS, Azure, plugins)](#storage-local-s3-gcs-azure-plugins)
- [Offline recording and push](#offline-recording-and-push)
- [Environment variables](#environment-variables)
- [Web UI](#web-ui)

---

## Mental model

Each experiment captures:

1. **Code state** — base version, base commit, the diff of uncommitted
   changes, local-only commits, untracked files and deps. This is what
   `restore`, `diff`, `export` and `rerun` replay. Config edits are code
   state, so a run records exactly which knobs you changed, committed or not.
2. **A log** — append-only entries: the initial `create`, then `metrics`,
   `note`, `artifact`, `run`, `structured`, `tags`, `define_metric`, `rewind`,
   `features`, `intent`, ... The log is never rewritten.
3. **Facts for finding it again** — who ran it and which files, functions and
   commits the change touched (a `features` entry written at submission), and
   optionally what it is for (an `intent`). [`similar`](#similar) ranks past
   runs on them.

Experiments are **content-addressed**:

```
1.6.0-dev.a1b2c3d.e4f5g6h
          │       └─ hash of the working-tree diff (0000000 on a clean tree)
          └───────── short base commit
```

Identical code yields an identical verstr, so a new run over an existing
state gets a `.r2`, `.r3`, … suffix instead of overwriting — "same config,
different seed" stays as distinct rows. (Offline runs, and runs with an
explicit writer id — `$VMN_WRITER_ID`, `--writer-id` or conf `writer_id` — use
a writer-id suffix instead; see [Offline recording](#offline-recording-and-push).)

The first `create`/`run` in a fresh repo **cold-starts**: it initializes vmn
and stamps a `0.0.0` baseline (the repo needs a git remote). A new app name in
a repo that already has other apps is refused as a likely typo unless you pass
`--new-app`.

Untracked (non-ignored) files are captured within size caps: files over
50 MB are skipped and at most 200 MB is collected per snapshot
(`VMN_SNAPSHOT_MAX_FILE_MB` / `VMN_SNAPSHOT_MAX_TOTAL_MB`). Skipped paths are
logged and recorded as `untracked_skipped`.

---

## Recording an experiment

| You want to… | Use |
|---|---|
| Capture the tree and type in the numbers yourself | `vmn-exp create <app> --metrics k=v …` |
| Add numbers/notes/files to an existing run later | `vmn-exp add <app> …` |
| Let vmn run a command and ingest the metrics it emits | `vmn-exp run <app> -- <cmd>` |
| Log from inside your own Python process | `start_run(...)` — see [sdk.md](sdk.md) |

All four snapshot the tree (dirty or clean) and produce the same kind of run,
so they mix freely: `exp run` a benchmark, then `exp add` a hand-measured
number to it.

A run records the git remote URL of the app and of each dep (`remote`,
`changesets.<path>.remote`) without credentials: an `https://user:token@host/…`
remote is stored as `https://host/…`, and an `ssh://` remote keeps only its
username (`ssh://git@host/…`). Records written before this that still carry a
token are redacted whenever they are read, so `show`, the UI, `export`,
`rerun` and `push` never pass it on; a record is rewritten clean the next time
its metadata changes (a note or `archive`).

### Record measurements by hand

A config sweep without any script:

```sh
# edit config.yml (uncommitted is fine)
vmn-exp create my_app --note "batch=64" --metrics latency_ms=12.3 throughput=8100
vmn-exp add my_app --latest --metrics p99_ms=41
# tweak config.yml ...
vmn-exp create my_app --note "batch=128" -f variant.yml --metrics latency_ms=15.1

vmn-exp list my_app                  # runs + metrics
vmn-exp compare my_app --last 3      # metrics side by side
vmn-exp diff my_app -v @1 -v @2      # config/code diff + params/metrics delta
```

`--metrics` records outputs; `-f variant.yml` records inputs (`params`,
`hypothesis`, `tags` — see [Structured notes & params](#structured-notes--params)).

**Python.** `start_run()` writes the same run the CLI would (same verstr,
files and heartbeat), so every command here works on it. The SDK also has
[autologging](sdk.md#autologging), step counters, rich media, resume/fork and
the read API — all documented in [sdk.md](sdk.md).

---

## With a command: `exp run` and the metrics file

`exp run` snapshots the tree, runs **any** command, and records its exit code,
duration and a `run` log entry:

```sh
vmn-exp run my_app --note "batch=64" -- ./perf_test.sh
```

- Everything after the first `--` is the command. `vmn-exp run` exits with the
  command's exit code (`128 + N` when signal N ended it) and prints the new
  verstr when it finishes.
- The command runs in the directory you invoked `vmn-exp` from (or
  `$VMN_WORKING_DIR`), not the repo root, so `cd src && vmn-exp run my_app --
  python train.py` finds `src/train.py`.
- Only creating the experiment takes the repo lock; it is released before the
  command starts, so long runs don't block other `vmn` commands and nesting
  `vmn-exp run` inside `vmn-exp run` works.
- `sys_*` system metrics (CPU/RAM, GPU with pynvml) of the command's process
  tree are sampled on every heartbeat ([list](sdk.md#starting-a-run)).
  `--no-system-metrics` > `VMN_SYSTEM_METRICS=0` > conf
  `experiment.system_metrics: false` turn it off. An SDK run inside the child
  then skips its own sampling.
- With `VMN_MODE=disabled`, `run` records nothing: it execs the command (no
  lock, snapshot or `run_state.yml`; works outside a checkout) with
  `VMN_METRICS_FILE=/dev/null`. See [Disabled mode](sdk.md#disabled-mode).

### Console output: `output.log`

`vmn-exp run` tees the command's stdout/stderr: every byte still reaches your
terminal, and a combined copy is stored as the run's `outputs/output.log`
(`show` prints an `Output:` line; the UI shows an output card).

- **Cap**: `--output-cap-mb` > `$VMN_EXP_OUTPUT_CAP_MB` > 10. Past it the first
  and last halves are kept around a `[vmn: N bytes of output omitted]` marker.
  The terminal is never capped.
- **Uploaded while it runs**, on each `--sync-interval` when changed (throttled
  to ~64 KB/s of upload), and once more unthrottled at the end — whatever
  ended the run. Only a SIGKILL of `vmn-exp run` itself loses the tail.
- **Pipes, not a TTY**: `isatty()` is false in the child, so tools may drop
  colours and progress bars. `PYTHONUNBUFFERED=1` is set unless you set it.
  Output is stored as raw bytes; capture failures never stop supervision.
- `--no-capture-output` gives the command your terminal and stores nothing.

### The metrics-file protocol

vmn sets these for the child:

| Variable | Value |
|---|---|
| `VMN_EXPERIMENT_ID` | this run's verstr — also drives [nesting](#outer--inner-jobs-sweeps) |
| `VMN_APP_NAME` | the app name |
| `VMN_METRICS_FILE` | a file your command appends metric lines to |
| `VMN_EXP_SUPERVISOR_SAMPLES` | `1` when the supervisor samples system metrics |

Each line appended to `$VMN_METRICS_FILE` is one metrics entry:

```
[step=N] key=value [key=value ...]
```

- Values are numeric only: non-numeric values are dropped with a warning (log
  strings as [params](#structured-notes--params) instead). NaN/inf are kept.
- A leading `step=N` builds a per-step series (a curve); without it the
  values are step-less scalars — the file is never auto-stepped (unlike the
  SDK's `log_metrics`, see [sdk.md](sdk.md#steps)).
- The file is **tailed live**, so metrics show in `exp show` and the UI while
  the command runs.

```sh
echo "latency_ms=$(compute_p50)" >> "$VMN_METRICS_FILE"
echo "step=$i throughput=$tput"  >> "$VMN_METRICS_FILE"
```

```python
import os
with open(os.environ["VMN_METRICS_FILE"], "a") as f:
    f.write(f"step={step} loss={loss}\n")
```

---

## Run status: did my job die?

While the command lives, `exp run` keeps a `run_state.yml` next to the run's
`metadata.yml` (same key prefix on S3) with a **heartbeat**:

```yaml
state: running          # "finished" after the child exits
command: [python, train.py]
runner: exp run         # "sdk" for a start_run() run
cwd: src                # child cwd relative to the repo root ("." at the root)
pid: 12345
host: somebox
started_at: 2026-09-21T12:00:00Z
heartbeat: 2026-09-21T12:03:00Z
heartbeat_seq: 6        # +1 per beat: a clock-free "it moved" signal
heartbeat_interval_sec: 30
exit_code: null
finished_at: null
duration_sec: null
```

`--heartbeat-interval <sec>` (default 30) sets the beat. SDK runs beat from a
daemon thread (`start_run(heartbeat_interval_sec=)`) and behave identically.

### Derived statuses

Status is **never stored** — it is derived from `run_state.yml` and the
current time:

| Status | Means |
|---|---|
| `created` | waiting: no command was ever started (e.g. `exp create`), or the SDK run was handed back unfinished (`state: released`, [`run.release()`](sdk.md#handing-a-run-back-release)) for a retry to reopen |
| `running` | the heartbeat is fresh |
| `stuck` | claims running, no exit code, and the heartbeat is stale |
| `succeeded` | finished with exit code 0 (or `end_reason: stopped`, a sweep's early stop) |
| `failed` | finished with a non-zero exit code |

`stuck` means the runner died, was OOM-killed or lost its node. The staleness
window is `max(3 × heartbeat_interval_sec, 60s)`; readers take the 60s floor
from `$VMN_EXP_MIN_STALE_SEC`. To tolerate writer clock skew, a run is `stuck`
only when **both** the heartbeat timestamp and the store's write time of
`run_state.yml` (file mtime, S3 `LastModified`) are stale; a future-dated
heartbeat is ignored. When the store time is unknown the heartbeat alone
decides. (`vmn_exp.core.status.derive_status(state, observed_at=...)`.)

A process that is hung but alive keeps heartbeating and reads `running`;
watch `last_metric_at` (UI/API) for "alive but not making progress".

Two attempts of one SDK run (speculative duplicate pods, a run resumed with
`start_run(run_id=)` while the old process still lives) share its
`run_state.yml`. Each SDK attempt records a random `attempt` id, and a
heartbeat first reads the stored state: once another attempt has written the
final state, the beat is dropped and this attempt stops heartbeating (one
warning), so the loser never flips a finished run back to `running`. A start
is always written, so resuming a finished run still reopens it. Best-effort:
there is no compare-and-swap, so a final state that lands between a beat's
read and its write is overwritten once; and the losing attempt's own final
state (when it finishes later) still replaces the winner's.

### Preemption and signals

`SIGTERM` (Slurm `scancel`, Kubernetes eviction, spot reclaim), `SIGINT` and
`SIGHUP` to `vmn-exp run` are forwarded to the command, which gets
`--kill-grace-sec` (> `$VMN_EXP_KILL_GRACE_SEC` > 30) to exit before SIGKILL.
A second signal kills it at once; a Ctrl-C the terminal already delivered to
the command is not re-sent. The final state is **always** written, so a
preempted run reads `failed`, never `stuck`:

```yaml
state: finished
exit_code: 143            # 128 + 15
signal: SIGTERM           # present when a signal ended the command
received_signal: SIGTERM  # present when vmn itself was signalled
```

A command that traps SIGTERM and exits 0 keeps its exit code. Only a SIGKILL
of `vmn-exp run` itself leaves a run claiming `running` (it then derives
`stuck`). Failing heartbeat writes, bad metric lines or hung syncs never end
supervision: vmn warns and keeps watching.

When the command fails (non-zero exit, not a sweep's `stopped`) and its
output is captured, the final state also records `error`, parsed from
`output.log`: `source: output`, the `output_tail` (last 50 lines) and, when the
output holds a Python traceback, its `type`, `message` and `traceback`. Not with
`--no-capture-output`. The SDK records `error` from the exception itself
(`source: exception`) and `signal` when SIGTERM finalized the run — or released
it (`start_run(on_sigterm="release")`: `state: released`, no exit code, reads
`created`; see [sdk.md](sdk.md#handing-a-run-back-release)). Rows and
queries carry the one-line `error_summary` (`Type: message`); a failure alert's
text ends with it too.

`exp list` shows a status per row; `exp show` prints `Status:`, exit code,
duration, `Runner: pid … on <host>`, the heartbeat age when `stuck`, and an
`Error:` block (`Type: message`, then the traceback or output tail) for a run
with an `error`; `show --json` carries the full `error`.

### Alerts

A run can notify a webhook, Slack or a shell command when it fails, goes
stuck, or calls `run.alert()` ([sdk.md](sdk.md#alerts)). Configure in
`conf.yml`:

```yaml
conf:
  experiment:
    alerts:
      on: [failed, stuck, alert]   # default: [alert]
      wait_sec: 60                 # run.alert(): drop repeats of one title within this
      timeout_sec: 5               # per-sink delivery timeout
      sinks:
        - {type: webhook, url: "https://example.com/hook"}               # JSON POST
        - {type: slack, url: "https://hooks.slack.com/services/T/B/X"}   # incoming webhook
        - {type: command, command: "./notify.sh"}                        # shell hook
```

Without a checkout: `VMN_EXP_ALERT_WEBHOOK_URL`, `VMN_EXP_ALERT_SLACK_URL` and
`VMN_EXP_ALERT_COMMAND` each add a sink (next to conf's), and
`VMN_EXP_ALERT_ON=failed,stuck` replaces the trigger list.

| Trigger | Fired by |
|---|---|
| `alert` | `run.alert(title, text, level)` in the SDK |
| `failed` | the process that saw the run end non-zero: `vmn-exp run`'s supervisor, or the SDK's finish (exception, `finish(exit_code=N)`, SIGTERM) |
| `stuck` | [`vmn-exp watch`](#watch) — a dead process cannot report itself |

Payloads: the webhook POSTs JSON with `trigger`, `title`, `text`, `level`
(`info`/`warn`/`error`), `app_name`, `run_id`, `run_name`, `status`,
`timestamp`, `host`, `pid`, `exit_code`, `signal`, `heartbeat`,
`finished_at`. Slack gets a coloured attachment. The command runs through the
shell with `VMN_ALERT_TRIGGER`, `VMN_ALERT_TITLE`, `VMN_ALERT_TEXT`,
`VMN_ALERT_LEVEL`, `VMN_ALERT_APP`, `VMN_ALERT_RUN_ID`, `VMN_ALERT_STATUS` and
`VMN_ALERT_JSON` (the whole payload); a non-zero exit is a failed delivery.
Delivery is best-effort and never affects the run or its exit code.

---

## Outer & inner jobs (sweeps)

For a managed search (grid/random/bayes, many agents, early stopping) use
[`vmn-exp sweep`](sweeps.md). This is the underlying nesting mechanism.

An experiment created **while `VMN_EXPERIMENT_ID` is set** records it as its
`parent`. `exp run` exports it to its child, so a script that calls
`vmn-exp run` (or `start_run()`) per trial yields one **outer** job with
**inner** jobs:

```sh
# sweep.sh
for lr in 0.001 0.01 0.1; do
    vmn-exp run my_app --note "lr=$lr" -- python train.py --lr "$lr"
done
```

```sh
vmn-exp run my_app --note "lr sweep" -- ./sweep.sh
vmn-exp run my_app --parent @3 -- python train.py   # explicit parent (any ref form)
```

Each run has a `kind`: `outer` (has children), `inner` (has a parent) or
`single`. An outer job's **`tree_status`** rolls up its subtree with
precedence `failed > stuck > running > created > succeeded`, so one failed
trial makes the sweep read failed. `exp list` indents inner runs and shows an
outer row as `<own status>/<subtree status>` when they differ:

```
[1] 1.6.0-dev.a1b2c3d.9f8e7d6  succeeded/failed  (3s ago)  - lr sweep
  [2] 1.6.0-dev.a1b2c3d.9f8e7d6.r2  succeeded  (2s ago)  loss=0.31  - lr=0.001
  [3] 1.6.0-dev.a1b2c3d.1122334  failed  (1s ago)  - lr=0.1
```

An outer run that never ran itself (no run state, own status `created`) is a
container: its own `created` is left out of the rollup, so 16 succeeded trials
make it read `succeeded`. A sweep outer (`vmn-exp sweep create`) also knows its
planned size — the grid size (capped by `run_cap`), else `run_cap`; an uncapped
random/bayes sweep has none. While its trials (a retried trial counts once)
number fewer than that, `created` joins the rollup: a sweep whose 16 trials all
finished out of 20 planned reads `created`, and `exp list` says so:

```
[1] 1.6.0-dev.a1b2c3d.9f8e7d6 'sw'  created (16/20 incomplete)  (3s ago)
```

Rows of such a sweep carry `sweep_planned` and `sweep_trials`; the UI shows
`16/20 · incomplete`.

**An ended outer run settles what it left behind.** Once an outer run has
ended — its own status is `succeeded`, `failed` or `stuck` (its orchestrator
died) — nothing will start its waiting children any more, so each descendant
gets a derived `settled` field (never stored; a run's own `status` stays): a
`created` one is `never_started`, a `stuck` or released one (it ran and never
finished) `lost`. The nearest started
ancestor decides: a container that never ran passes its parent's verdict on,
a still-running sub-outer keeps its own children open. Rollups then count
them apart: a never-started run adds nothing to `tree_status` and a lost one
adds `failed`, so an orchestrator whose pending trials were deleted reads its
own final status instead of `created`/`stuck` forever; the job rollups, fleet
counts and the app's status counts carry them as `never_started`/`lost` next
to the status counts (see [ui.md](ui.md#status-counts-and-rollup)). An ended
sweep short of its plan reads its own final status (its unclaimed slots never
start, the UI says `ended · 4 never started`); `created (16/20 incomplete)` is
for a sweep that has not ended. A settled run that starts after all (writes a
run state) leaves the settlement by itself. Query them with `settled =
"never_started"`, `settled = "lost"` or `settled = null`.

`exp show` prints `Parent:` on a trial, and `Children:` (plus `Subtree:` when
it differs) on the outer run.

**Forks are not children.** `create`/`run --fork-from <ref> [--fork-step N]`
(or `<ref>?_step=N`) starts a new run seeded with the source's params and
metrics up to step N (all of them without `--fork-step`). It records
`forked_from: {verstr, step}` but no `parent`, and never counts in the
source's `tree_status`. `list --query 'forked_from = "<verstr>"'` lists a
run's forks. To hide a run's own history past a step, see [`rewind`](#rewind).

---

## Addressing experiments

Every `-v`/ref argument accepts:

| Form | Means |
|---|---|
| *(omitted)* | the latest run for `add`/`show`/`restore`/`export`/`lineage`; the latest two for `compare`/`diff`; every local run for `push`; the current **working tree** (no run) for `similar` |
| `--latest` or `latest` | the most recent run |
| `@N` | the `[N]` row of `vmn-exp list` (1-indexed storage order, oldest first; stable under `--sort`/`--last`) |
| a unique prefix | e.g. `-v 1.6.0-dev.a1b` |
| full verstr | exact |

`tag`, `rewind`, `rerun` and `prune -v` require an explicit ref.
`vmn goto -v` takes a full verstr only (see [Restore vs goto](#restore-vs-goto)).

---

## Subcommand reference

`vmn-exp [action] <app> [flags]`; `create` is the default action, and a
leading `exp`/`experiment` is accepted (`vmn-exp exp list my_app`, or
`vmn exp list my_app` with vmn-exp installed). Actions: `create`, `run`,
`add`, `list`, `show`, `compare`, `diff`, `restore`, `export`, `prune`,
`tag`, `archive`, `unarchive`, `rewind`, `rerun`, `push`, `watch`,
`compact`, `importance`, `lineage`, `similar`, `similar-backfill`,
`backfill-children`, `export-metrics`, `import-mlflow`, `migrate`. Separate commands: `vmn-exp sweep`
([sweeps.md](sweeps.md)), `vmn-exp model` ([models.md](models.md)),
`vmn-exp settings` ([store settings](#store-settings-vmn-exp-settings)),
`vmn-exp ui` ([ui.md](ui.md)).

Read-only actions — `list`, `show`, `compare`, `diff`, `export`, `watch`,
`importance`, `lineage`, `similar`, `export-metrics` (and `import-mlflow`) —
take no repo lock. `list`, `show`, `compare`, `similar` and ref resolution
read through the [experiment index](#the-experiment-index-per-host-cache), a
per-host SQLite cache never inside the store, so thousands of runs cost one
names listing plus whatever changed, and resolving one run is a point read.

Flags shared by most actions:

| Flag | Description |
|---|---|
| `-v, --version <ref>` | the run (repeatable for `compare`/`diff`/`prune`/`push`/`compact`) |
| `--latest` | the most recent run |
| `--store <uri>` | experiment store URI; see [Storage](#storage-local-s3-gcs-azure-plugins) |
| `--bucket` / `--prefix` / `--endpoint-url` | shorthand for an `s3://` store |
| `--experiment-dir <dir>` | local root instead of the checkout's `.vmn/` (or `$VMN_EXPERIMENT_DIR`) |
| `--writer-id <id>` | this process's writer id; `$VMN_WRITER_ID` > `--writer-id` > conf `experiment.storage.writer_id` > `$HOSTNAME` > the host name (a `~` in it becomes `-`; see [streams](#how-records-are-stored)) |
| `--from-snapshot <path>` | git-free mode against a tree from `vmn-exp export`; see [Git-free mode](#git-free-mode) |
| `--json` | machine-readable output (`list`, `show`, `importance`, `lineage`, `similar`, `push`, `rerun --print`) |

### `create`

Capture the current state as a run without running anything (status
`created`). Prints the verstr.

```sh
vmn-exp create my_app --note "dropout 0.3" --metrics loss=0.45 acc=0.85
vmn-exp create my_app -f params.yml --name baseline-v1
vmn-exp create my_app --parent @2 --input "train=s3://bucket/train.csv#sha256:abc"
```

| Flag | Description |
|---|---|
| `--note <text>` | a note |
| `--metrics k=v …` | metrics to record |
| `-f <yaml>` | [params/hypothesis/tags](#structured-notes--params) |
| `--name <text>` | a human-readable name (shown quoted in `list`; row/query field `name`) |
| `--parent <ref>` | make it an inner job (default: `$VMN_EXPERIMENT_ID`) |
| `--fork-from <ref>` / `--fork-step N` | [fork](#outer--inner-jobs-sweeps) another run |
| `--input [name=]uri[#digest]` | record an input (repeatable); see [Inputs and lineage](#inputs-and-lineage) |
| `--no-env` | skip [environment capture](#environment-capture) |
| `--intent <text>` / `--intent-file <path\|->` | what the run is for, matched by [`similar`](#similar); see [Intent](#intent-what-a-run-is-for) |
| `--no-similar` | don't print the [similar-runs hint](#the-submission-hint) |
| `--new-app` | confirm a brand-new app name in a repo that has other apps |

After the claim, `create` prints up to 3 [similar past runs](#the-submission-hint)
on stderr; stdout still ends with the verstr.

### `run`

`create` plus a supervised command: `vmn-exp run <app> [flags] -- <cmd>`.
Takes every `create` flag except `--metrics`, plus:

| Flag | Default | Description |
|---|---|---|
| `--heartbeat-interval <sec>` | `30` | heartbeat period ([status](#run-status-did-my-job-die)) |
| `--kill-grace-sec <sec>` | `$VMN_EXP_KILL_GRACE_SEC` or `30` | time a [signalled](#preemption-and-signals) command gets before SIGKILL |
| `--sync-interval <sec>` | `30` | remote sync period for the log and `output.log` (`0` disables periodic sync) |
| `--output-cap-mb <mb>` | `$VMN_EXP_OUTPUT_CAP_MB` or `10` | [`output.log`](#console-output-outputlog) cap |
| `--no-capture-output` | capture on | don't keep `output.log`; the command inherits the terminal |
| `--no-system-metrics` | sampling on | don't record `sys_*` metrics |

`run` prints the [similar-runs hint](#the-submission-hint) once the repo lock
is released, before the command starts. `--intent-file -` reads stdin, which
the command then no longer gets.

`run` never reopens an existing run. To continue one, use the SDK's
`start_run(run_id=<ref>)` ([sdk.md](sdk.md#resuming-a-preempted-run)) or
`--fork-from`.

### Inputs and lineage

`--input [name=]uri[#digest]` (on `create`, `run`, `add`; repeatable) records
something the run consumed. `name` is an identifier before the first `=`
(a token containing `:` or `/` is never a name, so `s3://b/p?k=v` stays a
URI) and defaults to the URI's basename without extension; the last `#`
splits off an optional digest. `show` lists inputs, and queries read
`inputs.<name>.uri|digest|kind`.

A run's artifacts, images and tables are its **outputs**
(`outputs."<path>".digest|size|path`). Runs link when one's input is another's
output: an input URI `vmn://<app>/<verstr>/<path>` (`<app>` in tag form)
names its producer in any app; any other input links to same-app runs that
produced an output with the same digest. Used registry versions are inputs
named `<name>@<N>` ([models.md](models.md#using-versions)).

```sh
vmn-exp add my_app -v @1 --attach model.pkl
vmn-exp create my_app --input "model=vmn://my_app/<verstr of @1>/model.pkl"
vmn-exp lineage my_app -v @2 --depth 2
vmn-exp list my_app --query 'inputs."resnet50@3".kind = "model"'
```

`vmn-exp lineage <app> [-v <ref>] [--depth N] [--json]` (default: latest run,
depth 1) prints `Upstream:` and `Downstream:` runs with the
`input <- artifact (uri|digest)` links between them (plus the registry
version an artifact was registered as), `Datasets:` (reference datasets used)
and `Models:` (versions registered from the run). `--json` prints the
`get_lineage` object. Semantics and the payload are in
[sdk.md](sdk.md#lineage); consumers in other apps are found from the version
side (`version_lineage`, the UI's model page).

### Environment capture

`create`, `run` and `start_run()` record the Python version, platform,
installed packages, GPU and container info (image digest from
`VMN_IMAGE_DIGEST`/`IMAGE_DIGEST`/…): a ≤ 2 KB summary under `env` in
`metadata.yml` (shown as `Env:` by `show`) and the full list in `env.yml`.
When the `run` command is a Python interpreter (`python`, `python3.x`) or a
`.py` script, that interpreter's packages are probed (5 s timeout, falling
back to the current env). Best-effort; never blocks a run. Opt out:
`--no-env` > `VMN_CAPTURE_ENV=0` > conf `experiment.capture_env: false`.
Queries read `env.<key>` (summary fields) and `env.packages.<pkg>` for the
summary's key packages only (`torch`, `tensorflow`, `jax`, `numpy`,
`transformers`; other packages live in `env.yml` and never match). Versions are
strings, so compare with `=`: `env.packages.torch = "2.0.0"`.

### Intent: what a run is for

`--intent "<text>"` or `--intent-file <path|->` (on `create`, `run`, `add`)
records what a human, or their AI agent, says the run is for. It is matched by
[`similar`](#similar), lexically: vmn runs no model.

```sh
vmn-exp run my_app --intent-file intent.md -- python train.py
vmn-exp add my_app -v @4 --intent "baseline: plain cross-entropy"
vmn-exp add my_app -v @4 --intent-file - < intent.md       # stdin
```

```markdown
---
keywords: [focal loss, class imbalance, long tail]
generator: claude-opus-5-5
---
Hypothesis: focal loss (gamma=2) fixes the minority-class recall drop.
Changed: src/loss.py::focal_loss (new); src/train.py::train_step uses it.
```

- A file may start with YAML front matter between two `---` lines (or `---`
  … `...`): `keywords` (a list or a comma-separated string) and `generator`
  (the model id that wrote it; absent means a human). The rest is the text. An
  unclosed block is plain text; front matter that is not a YAML mapping, or
  keywords of another type, exits 1. `-` reads stdin.
- The text is stripped and cut at 16 KB of UTF-8 (`truncated: true`); keywords
  are stripped, deduplicated case-insensitively and capped at 50; numbers and
  dates become text. An empty text exits 1.
- The input is checked before anything is written (a cold start's baseline
  stamp included), so a bad one creates nothing. Inline text starting with `-`
  needs `--intent=-x`.
- `add` writes onto the latest run unless `-v`, like `--note`. Each call
  appends an entry; the latest wins, so a new intent replaces the old one.
  Forks and sweep trials start without one.
- It is not the note: `--note` stays the short line `list` shows, while the
  intent is the long description used for matching (set both if you like).
  On `create`/`run`, `-f`'s [`hypothesis:`](#structured-notes--params) is
  matched as text too (not `add -f`'s, which is a `structured` entry).
- Rows carry `has_intent` (a bool on every row), so the runs without one are
  `list my_app --query 'has_intent = false'`. `show --json`'s `log` holds the
  entry; `similar --json` items carry its first 2 KB.
- SDK: `start_run(intent=, intent_keywords=)` and `run.set_intent(text,
  keywords=, generator=)` ([sdk.md](sdk.md#similar-runs)).

The entry ([`similar`](#what-a-run-records-for-similar) lists the `features`
entry next to it):

```yaml
type: intent
text: "markdown"          # <= 16384 bytes of UTF-8
keywords: [..]            # <= 50, optional
generator: "model id"     # optional
source: user
truncated: true           # only when the text was cut
```

### `add`

Append to a run (default: latest). Nothing is overwritten.

```sh
vmn-exp add my_app --metrics val_loss=0.29 val_acc=0.93
vmn-exp add my_app -v @2 --attach checkpoint.pt --note "after warmup"
vmn-exp add my_app -f extra_notes.yml            # the whole file as a structured entry
vmn-exp add my_app -v @2 --define-metric val_loss --goal min
vmn-exp add my_app -v @7 --finish 1 --error "OOMKilled" --note "closed by orchestrator"
```

Flags: `--metrics`, `--note`, `--attach <file>` (an artifact), `-f <yaml>`,
`--input`, `--intent`/`--intent-file` ([Intent](#intent-what-a-run-is-for)),
`--define-metric NAME [--goal min|max] [--summary
min|max|last|first|mean] [--step-metric M] [--hidden]` (the CLI's
`run.define_metric`; see [summaries](#best-value-summaries-summary)), and
`--finish <code> [--error <text>] [--end-reason <text>] [--force]`: write the
run's final state from outside it, after the other entries, without
reopening it (refused while another attempt heartbeats it or once it
finished, unless `--force`; the CLI's
[`manage.finish_run`](sdk.md#finishing-a-run-from-outside-it)).

### `list`

```sh
vmn-exp list my_app                        # all (archived hidden)
vmn-exp list my_app --sort loss --top 5    # best 5 by loss (goal-aware)
vmn-exp list my_app --sort finished_at     # most recently finished first
vmn-exp list my_app --last 10              # the 10 most recent
vmn-exp list my_app --query 'metrics.loss < 0.5 and status = "succeeded"'
vmn-exp list my_app --json
vmn-exp list my_app --archived             # include archived runs, marked [archived]
```

Each row: `[N] <verstr> ['name'] [archived]  <status>  (<age>)  <metrics>
- <note>`, inner runs indented. `[N]` is the storage index `-v @N` resolves
and never changes with `--sort`/`--top`/`--last`/`--query`. Metric columns are
the [schema](#metrics-schema-sorting--goals)'s first, then the rest
alphabetically. Without `--sort`, the schema's `primary` metric orders rows.
`--sort` takes a metric name, or `timestamp` (creation), `started_at`,
`finished_at` (undated runs last) or `idx` (run number), all newest first.

`--query` takes [the query language](sdk.md#the-query-language) and applies
before `--last`, `--sort` and `--top`; a bad query exits 1 with the offset.
Besides `metrics.*`, `params.*` and `tags.*` it sees every row field
(`status`, `kind`, `depth`, `tree_status`, `settled`, `name`, `archived`, `rerun_of`,
`forked_from`, `imported_from`, `end_reason`, `author`, `has_intent`, …),
`inputs.*`, `outputs.*` and `env.*`. `author` is who ran it (the
[`features`](#what-a-run-records-for-similar) author's git email, else OS
user, else writer id; `null` when unknown): `list my_app --query 'author ~
"alice"'`.

`--json` prints the shown rows as a JSON array (keys sorted, non-finite
metrics as `null`, `[]` for no runs), one object per run with the keys of an
SDK [`list_runs`](sdk.md#reading-runs-back) row: `idx`, `verstr`,
`code_verstr`, `timestamp`, `note`, `create_note`, `name`, `author`,
`has_intent`, `tags`, `archived`, `params`, `metrics`, `metric_summary`,
`inputs`, `outputs`, `parent`, the status fields (`status`, `exit_code`, `started_at`,
`finished_at`, `heartbeat`, `duration_sec`, `pid`, `host`, …) and the tree
fields (`children`, `kind`, `depth`, `settled`, `tree_status`).

### `show`

Full details of one run (default: latest): branch, base, created, note,
`Deps:`, `Env:`, `Output:`, the status block, `Parent:`/`Children:`/
`Subtree:`, `Rerun of:`, `Forked from: <verstr> @ step N`, one
`Rewound to step N` line per rewind, patch sizes, `Inputs:`, `Metrics:` (each
at its [summary value](#best-value-summaries-summary), with last/min/max where
they differ), `Media:`, and the newest 50 log entries (`--full-log` for all).

```sh
vmn-exp show my_app -v @1 --full-log
vmn-exp show my_app -v @1 --json
```

`--json` prints one object: the `list --json` row keys plus `base_commit`,
`format_version`, `has_dep_patches`, `patches` (`{working_tree|local_commits:
line count}`), `log` (newest 50, or all with `--full-log`), `log_total`,
`media_counts` and `features` (the run's newest features entry at the highest
`features_version`, or `null`).
The `features` entry is a fact about the run, not an event, so neither the
text log nor `log`/`log_total` include it.

`--patch [--max-bytes N]` also prints the run's own text patches after the
show block — what to read when inspecting a [similar](#similar) run or writing
an [intent](#intent-what-a-run-is-for) for an old one:

```sh
vmn-exp show my_app -v @3 --patch
vmn-exp show my_app -v @3 --patch --json --max-bytes 50000
```

- Sections `=== working_tree ===`, `=== local_commits ===`, then each dep's
  `=== deps/<dep>/<type> ===`. The untracked tarball is never printed.
- At most `--max-bytes` (default 200000, at least 1) bytes, cut on a UTF-8
  character boundary; past it a `[patch truncated at N bytes; raise
  --max-bytes to see more]` line follows.
- A run with no text patch prints `<verstr> has no patch to show: <reason>` on
  stderr and exits 0: an MLflow import, a clean tree, a run recorded from an
  exported tree, a pruned code object, or untracked files only (it names up to
  three and points at `export`/`restore`).
- With `--json` the object gains `patch`: `{"text", "truncated"}`, or `{"text":
  null, "reason"}` with `reason` `no_code`, `code_missing` (the run's code
  object is gone from the store) or `untracked_only` (plus `untracked_files`,
  the tarball's paths, deps under `deps/<dep>/`, unless the tarball cannot be
  read). Without `--patch` there is no `patch` key.

### `compare`

Metric table across runs (default: the latest two; `--last N` for the N most
recent; `-v` repeatable). Reads only metadata and logs, never code, so
comparing many runs stays cheap. With two runs it prints the matching `diff`
command.

```sh
vmn-exp compare my_app --last 3
vmn-exp compare my_app -v @1 -v @4 -v @7
```

### `diff`

`params:`/`metrics:` delta lines, an inputs/provenance section, and a **real
source diff** between two runs (default: the latest two). Uses `--tool`, else
git's `diff.tool`, else a plain diff. For runs without code (e.g. MLflow
imports) the deltas print and the code diff is refused (exit 1).

```sh
vmn-exp diff my_app -v @1 -v @3 --tool delta
```

### `restore`

Put this checkout at a run's exact code (default: latest). A dirty tree is
**auto-saved first** as a [snapshot](../snapshots.md) noted `auto-saved before
restore`, and the `vmn goto -v <saved> <app>` that brings it back is printed.
The restore deletes untracked files, so when some exceed the snapshot size
caps (and so could not be saved) it refuses and names them; `--force`
restores anyway. It is the same restore `vmn snapshot restore` runs.

The run is looked up in the local experiments dir, then (only on a local
miss) the app's remote experiment store, then the snapshots store — so a run
another host recorded straight to S3 restores from any checkout. Runs without
code are refused.

```sh
vmn-exp restore my_app -v @2
vmn-exp restore my_app -v @2 --force
```

#### Restore vs goto

Both restore base commit, diff, local commits and untracked files, auto-save
a dirty tree, and share the lookup above.

| | `vmn-exp restore <app>` | `vmn goto -v <verstr> <app>` |
|---|---|---|
| Ref | any [addressing form](#addressing-experiments); default latest | a full dev verstr only |
| Remote store | `--store`/`--bucket`…, else env, else conf | env, else conf (no store flags) |
| Needs | `vmn-exp` | `vmn` with `vmn-exp` installed (it registers the dev-version loader) |
| Also restores | experiment runs and snapshots | also stamped versions, with deps |

Use `restore` while working with runs (`@N`, prefixes); use `goto` for the
full verstr a restore prints for your auto-saved work, or in scripts that
already speak `vmn goto`. `goto --force` matches `restore --force`.

### `export`

Package a run (default: latest) — materialized code without `.git`,
`vmn_metadata.yml`, `vmn_experiment.yml` (metadata, log and `exported_by`: the
exporter's writer, git email and OS user), `vmn_features.yml` (the run's
[features](#what-a-run-records-for-similar) and `exported_by`: all a git-free
run of the tree reads), `artifacts/` and `outputs/` —
into a directory or a `.tar.gz`/`.tgz` (default `<verstr>.tar.gz`). Prints the
output path. Runs without code are refused.

```sh
vmn-exp export my_app --latest -o best.tar.gz
vmn-exp export my_app --latest -o /mnt/code  # a plain directory
```

The exported tree records runs without git — see [Git-free
mode](#git-free-mode) and the [client guide](client-guide.md#jobs-without-git-export-the-code-once-kubernetes)
for the cluster flow.

### `prune`

Delete runs by count, age, query or exact ref. Prints `Deleted <verstr>` per
run and a summary.

```sh
vmn-exp prune my_app --keep 10              # keep the 10 most recent
vmn-exp prune my_app --older-than 30d       # Nd / Nw / Nh
vmn-exp prune my_app --keep 10 --dry-run
vmn-exp prune my_app --keep 0 --local-only  # drop local copies, keep remote ones
vmn-exp prune my_app -v @4 -v @5            # exactly these runs
vmn-exp prune my_app --keep 5 --protect-tag stage
vmn-exp prune my_app --query 'status = "failed"'          # preview only
vmn-exp prune my_app --query 'status = "failed"' --yes    # delete
```

| Flag | Description |
|---|---|
| `--keep N` | keep the N most recent |
| `--older-than <dur>` | delete runs older than `Nd`/`Nw`/`Nh` |
| `-v <ref>` | delete exactly these runs (repeatable); not with `--keep`/`--older-than`/`--query` |
| `--query <expr>` | select by [query](sdk.md#the-query-language) (same rows as `list --query`); **a dry-run preview unless `--yes`/`-y`**; `--keep`/`--older-than` then refine within the matches |
| `--yes`, `-y` | confirm a `--query` deletion |
| `--dry-run` | print what would go, delete nothing (beats `--yes`) |
| `--protect-tag <key>` | never delete a run carrying this tag key (repeatable) |
| `--force` | also delete `running`/`stuck` and tag-protected runs |
| `--local-only` | keep the remote copies |

Guards take runs back out of any selection:

- `running` or `stuck` runs are skipped (a stuck run may just be late);
  `--force` overrides.
- runs carrying a `--protect-tag` key are skipped; `--force` overrides.
- runs registered as a live model/dataset version are skipped **even with
  `--force`** — `vmn-exp model delete` the version first
  ([models.md](models.md#prune-protection)); if the registry can't be read,
  prune refuses.
- a run with a kept descendant is kept, so no inner run loses its parent.

With a remote store, prune deletes local **and** remote copies (which may be
teammates' runs); `--local-only` touches only local ones. A code object is
deleted with the last run of its code. Archived runs are pruned like others.

### `tag`

Set or remove mutable `key=value` labels on a run (finished ones too):

```sh
vmn-exp tag my_app @3 stage=prod owner=ann
vmn-exp tag my_app @3 --remove owner
vmn-exp tag my_app stage=candidate --latest
```

Exactly one run: the positional without `=`, or `-v`/`--latest`. Values may
contain `=`. Put positionals before flags. Each call appends a `tags` log
entry; readers fold per key, last write wins. Rows carry `tags`; queries read
`tags.<key>`. SDK: [sdk.md](sdk.md#changing-stored-runs-archive-unarchive-tags).

### `archive` / `unarchive`

Hide runs from listings without deleting anything:

```sh
vmn-exp archive my_app @1 @2 0.0.3-dev.abc1234.def5678
vmn-exp unarchive my_app @2
```

Sets (or clears) `archived: true` in the run's `metadata.yml` (atomically on
disk, under the ETag on S3). `list`, `list_runs` and the UI hide archived
runs unless asked (`--archived`, `include_archived=True`, `archived=1`); the
query language matches `archived = true`.

### `rewind`

Hide a run's history past a step, in place:

```sh
vmn-exp rewind my_app -v @3 --step 250
# rewound 0.0.3-dev.abc1234.def5678 to step 250 (hid 42 entries)
```

Needs `-v`/`--latest` and `--step N` (≥ 0). Nothing is deleted: a
`{"type": "rewind", "step": N}` entry is appended, and every reader (`show`,
`list`, the index, the UI, `list_runs`) ignores earlier entries with a step
past N. Step-less entries (params, notes, tags) are never hidden. A run that
derives `running` is refused. A run whose metrics are already
[compacted](#metric-storage) gets its `.vmx` rebuilt without the hidden
points. Takes the repo lock, honours the store flags,
and works git-free. The UI's `exp_rewind` job action runs it. To rewind and
continue in one go, use `start_run(run_id=<ref>, rewind_to_step=N)`
([sdk.md](sdk.md#rewinding-a-run)); to branch instead, `--fork-from`.

### `rerun`

Run a run's recorded command again, against that run's own code (dirty edits,
local commits, untracked files and deps), as a new linked run:

```sh
vmn-exp rerun my_app -v @3                                 # recorded command and cwd
vmn-exp rerun my_app -v @3 -- python train.py --lr 0.01    # another command, same code
vmn-exp rerun my_app -v @3 --dry-run                       # print the plan
vmn-exp rerun my_app -v @3 --print [--json]                # what a cluster job should run
```

- **Workspace**: the code is restored into detached worktrees in a fresh
  `$TMPDIR/vmn-rerun-<app>-*` (or `--worktree-dir DIR`, missing or empty and
  outside the repo), cloning from the recorded remote when a commit is not
  local. Anything that doesn't restore exactly is an error and nothing is
  created; the live checkout is never touched. The workspace is removed
  afterwards (also on SIGTERM) unless `--keep-worktree`, which prints its path
  and records it as `workdir` in `run_state.yml`.
- **Command**: runs in the recorded `cwd` (`--cwd PATH`, relative to the
  restored app root, overrides); `-- <cmd>` replaces the recorded command;
  absolute paths into the live repo are pointed into the workspace. Supervision
  is exactly [`run`](#run)'s, and `run`'s flags apply (`--note`, `--name`,
  `--parent`, `--input`, `-f`, `--no-env`, the supervision flags); `--fork-from`
  is refused.
- **Record**: `rerun_of: <verstr>`, sharing the original's code object under
  the same code verstr (so it keeps that code alive through `prune`). Create
  params are copied (tags and inputs are not); a sweep trial's params are
  re-exported as `VMN_SWEEP_PARAMS`. The child's `VMN_EXPERIMENT_DIR` is the
  original store, so runs it creates land there as inner runs.
  `list --query 'rerun_of = "<verstr>"'` lists reruns.
- **Warnings**: a differing environment, untracked files too large to have
  been captured, a source still `running`, a sweep trial.
- **Refused**: runs without code, runs that never ran a command (pass one
  after `--`), SDK runs without `--` (they record the script's arguments, not
  the interpreter: `vmn-exp rerun my_app -v X -- python train.py`), and
  git-free mode. Gitignored files (datasets, `.env`) are not part of the code
  — point the command at them by absolute path.

#### Reruns on a cluster

vmn doesn't schedule jobs. `--print` tells your job script what to run:

```
command:       python train.py --lr 0.1
cwd:           src
code_verstr:   0.0.3-dev.abc1234.def5678
code:          0.0.3-dev.abc1234.def5678.<diff hash>
recipe:        vmn-exp rerun my_app -v 0.0.3-dev.abc1234.def5678
export_recipe: vmn-exp export my_app -v ... -o ... && cd ... && VMN_SNAPSHOT_METADATA=... vmn-exp run my_app -- python train.py --lr 0.1
```

`--print --json` prints `rerun_of`, `app`, `command` (a list), `cwd`,
`code_verstr`, `code`, `base_commit`, `recipe`, `export_recipe`. Nodes with a
checkout reaching the same store run `recipe`; nodes without git run
`export_recipe` (a plain git-free run of the exported code, not a linked
rerun).

### `push`

Upload local runs (typically recorded offline) to the remote store under the
same names. `--adopt` first makes this checkout the owner of the streams its
runs inherited from a copied or moved checkout. See
[Offline recording and push](#offline-recording-and-push).

### `watch`

Deliver `failed`/`stuck` [alerts](#alerts) for runs that have not alerted yet:

```sh
vmn-exp watch my_app                 # one pass (cron-friendly)
vmn-exp watch my_app --interval 60   # loop every 60 s
vmn-exp watch my_app --within 6h     # ignore transitions older than 6h (default 1d; Nd/Nw/Nh)
```

Prints `<verstr> <status>` per alert delivered; exits 1 when no sink is
configured for `failed` or `stuck`. Each run alerts once per transition: a
delivered alert is recorded in the run's `alerts_sent.yml` (keyed by
`finished_at` or the last heartbeat), so a run that recovers and stalls again
alerts again, and a `failed` alert the supervisor already sent is not
repeated. An alert no sink accepted is retried on the next pass.

`--compact` also [compacts](#compact) the metrics of every `failed` or
`stuck` run on each pass (a writer that died never compacted itself); with
it, no alert sink is needed.

### `compact`

Build the compacted metric file (`metrics/<stream>@000000-<last>.vmx`, see
[Metric storage](#metric-storage)) of runs whose writer ended before doing so:

```sh
vmn-exp compact my_app -v @3 -v @4      # these runs
vmn-exp compact my_app --all-finished   # every succeeded or failed run
```

Takes run refs (`-v`, repeatable) or `--all-finished`, exactly one of the two.
Prints `<verstr> compacted (N writers)` or `<verstr> up-to-date` per run and
exits 1 when one failed. A named run that is `running` is refused (it compacts
itself at its end); `--all-finished` never picks running or stuck runs. Already
compacted writers are left alone. `vmn-exp watch --compact` does the same for
failed/stuck runs.

### `importance`

Which params drive a metric:

```sh
vmn-exp importance my_app --metric loss
vmn-exp importance my_app --metric loss --query 'status = "succeeded"' --json
```

```
param    importance                        correlation  kind         n
lr            0.912  ##################         +0.954  numeric      240
opt           0.061  #                               -  categorical  240
```

Over the runs `list --query` would show (`--archived` to include archived)
that carry the metric, each param with at least two distinct values gets:
`importance` — its share of the impurity decrease of a small, fixed-seed
random forest (50 trees, depth 6; the column sums to 1); `correlation` —
Pearson (`spearman` too in `--json`; `-`/`null` for categorical params, bools
count as 0/1); `kind` (`numeric`/`bool`/`categorical`) and `n`. A missing
numeric param counts as its median, a missing categorical value as its own
category. Past 5000 runs a deterministic sample of 5000 is scored. An unknown
metric or bad query exits 1. SDK: `reader.param_importance`.

### `similar`

Has anyone run something like this before? The past runs most like a run, by
anyone, in this app or (`--all-apps`) every app of the store — or, with no
ref, like the **current working tree**, so you can ask before creating a run:

```sh
vmn-exp similar my_app                          # like my uncommitted change; creates nothing
vmn-exp similar my_app -v @7 --top 5            # like run @7
vmn-exp similar my_app --context-file intent.md --all-apps --json
vmn-exp similar my_app --context "label smoothing, soft targets" --text-only
vmn-exp similar my_app -v @7 --query 'status = "succeeded" and author ~ "alice"'
```

```
0.0.3-dev.abc1234.def5678  0.82  alice@x.io  3w ago  succeeded  val_loss=0.31  — 2 shared functions: loss.py::focal_loss, train.py::train_step, same dataset imagenet@3, lr 3e-4 vs 1e-4  (+7 runs)
0.0.2-dev.9f8e7d6.0000000  0.41  -  5mo ago  failed  —  — same base version 0.0.2, same metrics: val_loss
```

| Flag | Description |
|---|---|
| `-v <ref>` / `--latest` | the target run. Without either: the current working tree, captured without creating a run. `similar` is the one action whose missing ref means the working tree (`show`/`restore`/`export` take the latest run), because it is mostly asked before you submit |
| `--top N` | how many results (default 10) |
| `--all-apps` | every app of the store, each under its own metrics schema |
| `--query <expr>` | keep only candidates `list --query` would show (the target is never filtered) |
| `--archived` | include archived runs |
| `--context <text>` / `--context-file <path\|->` | a text query, combined with the target's code facts; it replaces the target's own text. A file's front matter `keywords` join the query (other keys are ignored) and `-` reads stdin, so an [`intent.md`](#intent-what-a-run-is-for) doubles as the query |
| `--text-only` | match the context text alone (no code, params or inputs); needs `--context`/`--context-file`, and no working tree or run |
| `--json` | the results as a JSON array |

- **Output**: one line per result, `<verstr>  <score>  <author|->  <age>
  <status>  <goal metric>=<value>|—  — <reasons>  (+N runs)`, with `<app>/`
  before the verstr under `--all-apps`. Reasons are the top 3 contributing
  signals; a comparison reads candidate first (`lr 3e-4 vs 1e-4` = the
  candidate's lr vs the target's). No result prints `No similar runs found for
  <app>` on stderr (exit 0; `--json` prints `[]`).
- **`--json`** items: `app`, `verstr`, `name`, `score`, `reasons`, `signals`
  (each signal's similarity), `group_size`, `author`, `timestamp`, `status`,
  `goal` (`{metric, goal, value}` or `null`), `note` (the record's, else the
  create note), `intent` (`{text, keywords?, generator?, truncated?}`, the text
  cut to 2 KB, or `null`) and `features` (the run's
  [`features`](#what-a-run-records-for-similar) entry or `null`).
- **Left out**: the target run, its whole run tree (its outer run, the
  trials and the SDK runs they open, its own inner runs) and its reruns — the
  runs of its *rerun identity*: same `code_verstr`, same params (compared
  exactly) and same inputs (digest, else uri) — in the target's app only. A
  fork of the target, or the run it forked from, is a continuation and stays
  a candidate. Runs of the same code with other params or inputs (e.g. other
  hyperparameters on one clean commit) are ordinary candidates. A
  working-tree target excludes nothing.
- **Grouped**: the runs of one tree (a sweep), else the runs of one rerun
  identity (seeds or reruns of one config), fill one slot, shown by the member best
  on the group's goal metric (the [schema](#metrics-schema-sorting--goals)
  `goal` metric most of its runs carry), else the most similar one, with `(+N
  runs)`. Ties sort newest first.
- Read-only and lock-free. An app is searched in its persisted
  [experiment index](#the-experiment-index-per-host-cache) file, brought up to
  date with the store first; the few runs a search shows are read by verstr,
  so no snapshot of the app is loaded. A `--query`, a store never indexed on
  this host or no index file at all (`VMN_INDEX_CACHE_DIR=none`, an
  unwritable cache dir) read a refreshed snapshot instead; without a file the
  same search runs on an in-memory SQLite database filled from it (slower to
  start, same answers). Git-free mode needs `-v`/`--latest` or `--text-only` (a
  working tree needs a checkout). A bad `--query` exits 1. SDK:
  `reader.similar_runs`, `run.similar()` ([sdk.md](sdk.md#similar-runs)); UI:
  the run page's similar runs card and the leaderboard's similar mode
  ([ui.md](ui.md#similar-runs)).

**How runs are ranked.** Every save of the index files each run as one
document in a SQLite FTS5 table of that index file, one column per signal,
in the same transaction as the run's record (a run whose document did not
change writes nothing). A search turns the target into one FTS5 `MATCH` and
ranks the documents with FTS5's `bm25` in SQLite; Python never scores the
corpus. FTS5 is required: without it `similar` fails with `similar runs need
SQLite with FTS5 (python's sqlite3 lacks it)` (the rest of vmn-exp works on).

| Signal | FTS column holds | Default weight |
|---|---|---|
| `code` | the base commit (the base version and its `major.minor` line are kept for reasons only, never matched) | 2 |
| `files` | the changed files (untracked paths included), or a clean-tree token | 2 |
| `symbols` | the changed functions (`path::name`, from hunk headers and from definitions on added/removed lines, any language), or a clean-tree token | 3 |
| `inputs` | input digests and dataset names | 2 |
| `params` | each param key, and each scalar param's `key=value` | 1.5 |
| `entrypoint` | the script, its subcommand and its full argument list; launchers (`torchrun`, `accelerate launch`, `deepspeed`, `mpirun`, `srun`, `python -m torch.distributed.run`, …) are looked past | 1 |
| `objective` | the metric names (minus params and `sys_*`) | 1 |
| `branch` | the branch | 0.5 |
| `text` | the intent text, its keywords (each ×3), name, note, tag keys and values, commit subjects and `create`/`run -f`'s `hypothesis` | 1.5 |

- **Structured signals are words too.** Every value of the structured columns
  is filed as one opaque word (a hash of `file:src/a.py`, `sym:…`,
  `pkey:lr`, …), so identical structure matches exactly and nothing else
  does: `lr=3e-4` and `lr=1e-4` share the `lr` key, not a value.
- **Text is FTS5's.** The `text` column uses the `porter unicode61`
  tokenizer: case-insensitive words split at anything that is no letter or
  digit (`ResNet-18` is `resnet` and `18`), stemmed (`losses` matches
  `loss`, `smoothing` matches `smooth`). No stopword list; common words just
  weigh little in bm25.
- **The query is bounded by rarity.** Per column the target asks for at most
  64 of its tokens, the rarest first (document frequencies from the FTS
  vocabulary); tokens no document holds are dropped. Past the 8 rarest
  tokens overall, more are added only while their documents add up to at
  most the number of documents filed (at least 40,000), so a common token
  never costs a pass over the app. Each token is a quoted FTS5 string, so
  `"`, `*`, `:` or `NEAR` in a context text are only words.
- **Weights are bm25 column weights.** Conf `experiment.similar.weights`
  (merged over the defaults above; values that are not numbers ≥ 0 are
  ignored) sets them; a weight of 0 drops its column from the query. When the
  target has an intent, a `--context` or intent keywords, the default `text`
  weight becomes `code` + `inputs` (4 by default); an explicit `text` weight
  still wins. `--text-only` asks the `text` column alone.
- **Paged, then shaped.** SQL returns the best 500 matches (then 1000, 2000,
  … more) while fewer than `--top` groups are found; Python drops the
  left-out runs, applies `--query` and the archived filter and groups, as
  above. There is no candidate cap.
- **Scores** are bm25 relative to the best run found (that run scores 1.0;
  the target and the runs it leaves out aside), rounded to 4 digits — a
  ranking, not an absolute similarity, never stored.
- **Reasons and signals** are computed for the items shown only: per signal
  the overlap (Jaccard) of the target's and the run's filed tokens — for
  `text` the share of the target's (stemmed) words the run holds — left out
  when either side has none. Reasons are those of the 3 heaviest overlaps
  (weight × overlap); shared text names the keywords both hold, then the
  rarest shared words.

A run whose features entry names no changes ran a clean tree: two clean
trees share the clean-tree token on `files`/`symbols`. Changes stay unknown
(nothing filed) without a features entry, for MLflow imports, for an
export's author-only entry and for a backfill that found the code object
gone. Conf overrides, per app:

```yaml
conf:
  experiment:
    similar:
      weights: {symbols: 4, branch: 0}   # merged over the defaults; invalid values ignored
      hint: false                         # no submission hint
```

The CLI, the hint, the SDK and the UI's run route score every app they search
under the target app's `weights` (in the UI, git workspaces only); a text-only
query scores its text alone.

#### The submission hint

After the claim, `create` and `run` print up to 3 similar runs on stderr, once
the repo lock is released (`run` before the command starts):

```
2 similar runs: best val_loss=0.31 — 0.0.3-dev.abc1234.def5678 by alice@x.io, 3w ago (same dataset imagenet@3, 1 shared function: loss.py::focal_loss)
  0.0.3-dev.9f8e7d6.0000000 by bob@x.io, 2d ago (same base commit 9f8e7d6, same branch main)
```

It leads with the best of them on its goal metric (`closest — …` when none has
one). Cheap or nothing, and never affecting the run:

- Its candidates are this host's persisted index of the app, as `list`,
  `show`, `compare`, `similar` or an SDK reader (`list_runs`, `similar_runs`)
  last refreshed it; `vmn-exp ui` keeps its own index under its data dir,
  which the hint does not read. It never refreshes from the store, so a cold
  cache prints nothing and runs since the last refresh are not seen
  (`vmn-exp similar <app> -v <verstr>` shows them).
- It needs that index file and a local side of the storage (the
  repo-local store, or the local copy in front of a remote one; a store
  written to directly gets no hint): of the store it reads only the new run's
  own record, where the command just wrote it, never a remote listing.
- Its 300 ms budget bounds the work, not just the wait: the search's SQLite
  queries are interrupted at the deadline and nothing is printed. It reads
  the FTS table and the few runs it shows by verstr, so its cost does not
  grow with the number of runs (there is no run-count cutoff).
- Never for inner runs (`--parent`, an enclosing run's `VMN_EXPERIMENT_ID`,
  sweep trials).
- Off with `--no-similar` or conf `experiment.similar.hint: false`. The SDK
  prints no hint.

#### What a run records for similar

Every git-mode run (`create`, `run`, sweep trials, `start_run()`) gets a
`features` entry right after its `create` entry: who ran it and what the
change touched, read from the captured patches.

```yaml
type: features
features_version: 1
source: capture             # capture | rerun | export | backfill | mlflow
author: {writer: gpu-07, git_user_email: a@x.io, os_user: alice, source: git}
changed:
  files: [src/loss.py, src/train.py]       # deps under their configured path
  symbols: ["src/loss.py::focal_loss", "src/train.py::train_step"]
  untracked: [notes/idea.md]               # paths only, at capture only
commits: ["try focal loss gamma=2"]        # the local commits' subjects
truncated: true                            # only when a cap cut a list
```

- Empty values are left out. Caps: 200 files, 500 functions, 50 commits, 200
  untracked paths. MLflow entries may also carry `entrypoint`, `branch` and
  `changed_source: commit` ([migrating-from-mlflow.md](migrating-from-mlflow.md#similar-runs-for-imported-runs)).
- `author.source` says where the email came from: `git` (git config
  `user.email` in the repo, given up on after 2 s), `env`
  (`VMN_EXP_AUTHOR`), `commit` (the first local commit's `From:`), `export`
  (the exporter's, git-free), `mlflow`, or `host` (no email; writer and OS user
  only). The row field `author` shows the email, else the OS user, else the
  writer.
- The branch is not repeated here: every record's metadata has it (row field
  `branch`).
- Best-effort, like environment capture: a failure warns and the run is
  created without the entry; [`similar-backfill`](#similar-backfill) fills it
  in later.
- A rerun copies the original's facts with the rerunner as the author
  (`source: rerun`); a fork captures its own and inherits neither features nor
  intent. A [git-free](#git-free-mode) run copies the exported run's facts from
  the export's `vmn_features.yml` (`source: export`; author email: git config in
  the tree, else the export's `exported_by`, else `VMN_EXP_AUTHOR`). An older
  export without that file is read from `vmn_experiment.yml`'s log, only while
  that file is at most 1 MiB; without the facts only the author is known and the
  entry has `features_version: 0`, so `similar-backfill` completes it.
- vmn's own commits (init, stamp: authored as `vmn`; an SDK cold start leaves
  them unpushed) are not the run's: their files, subjects and author are left
  out of capture, rerun and backfill entries.
- A change's function is what git's default funcname (no `diff=` driver in
  `.gitattributes`) names for it: the nearest line above it in the old file
  that starts with a letter, `_` or `$`. That is a def or class, but also an
  `if __name__` block, a module constant or a text file's prose, and never a
  method or a nested def (a method's edits all name its class), read as git
  prints it: its first 80 bytes, up to its first byte that is not UTF-8. A
  hunk starts with its header's name (none at the top of a file, or with only
  blank, indented or comment lines above it) and each such context or removed
  line moves it for the changes below, so `git diff`'s 3 context lines name
  what `-U0` (`import-mlflow --repo`) does, e.g. the function a file starts
  with. With a driver such as `diff=python`, `-U0` names what the driver picks
  (methods, not `if __name__` blocks), which can differ.
- The fold keeps the entry with the highest `features_version`, then the
  latest. `show` leaves it out of the log; `show --json` gives it as
  `features`.

### `similar-backfill`

Give runs the `features` entry their code implies when they lack one at the
current `features_version`: runs recorded before features existed, whose
capture failed, or captured by an older vmn-exp.

```sh
vmn-exp similar-backfill my_app --dry-run
vmn-exp similar-backfill my_app --all-apps
```

```
0.0.1-dev.abc1234.def5678  backfilled (2 files, 2 symbols, 1 commit)
0.0.1-dev.abc1234.0000000  backfilled (clean tree)
0.0.2-dev.9f8e7d6.1a2b3c4  partial (code object 0.0.2-dev.9f8e7d6.1a2b3c4.<diff hash> is missing)
0.0.2-dev.9f8e7d6.5d6e7f8  skipped (running)
backfilled 2, partial 1, skipped 1, failed 0
```

- Skips runs that are up to date, `running`/`stuck`, or imported
  (`imported_from`; MLflow runs use `import-mlflow --refresh-features`).
- Reads only the text patches of the run's code object (never the untracked
  tarball), each object parsed once. A clean tree gets a complete entry with
  nothing changed. A run whose code object is gone is `partial`: its entry has
  no `changed` (or keeps its older entry's). Code the store lists but cannot
  read `failed`s the run and writes nothing, so the next backfill retries it.
- What an older entry observed at submission (author, branch, entrypoint,
  untracked paths) is carried over; only `changed`/`commits` are recomputed.
  Without one, the author is the first local commit's `From:` plus the writer
  that created the run (for a run `migrate` converted from v1, its run state's
  host).
- The entry (`source: backfill`) is appended under this host's writer id.

### `backfill-children`

Every run created with a parent (`create`/`run --parent`, nested runs under
`VMN_EXPERIMENT_ID`, sweep trials, reruns, SDK runs, imports, `push`) also
writes an empty child marker `children/<child verstr>` into its parent's
record, best-effort (a failed marker never fails the child; `prune` drops a
pruned child's marker). An outer run's children are then one listing of its
own record away, which is how `vmn-exp ui` can show an outer run before its
index has loaded the store. The markers only speed reads up: the children's
`parent` fields stay the truth, and a marker whose run is gone (or was
renamed) is skipped. `backfill-children` writes the markers a store lacks
(runs from before markers existed, or a marker that failed to write), from
one listing of the app's runs, each run's `metadata.yml` alone (never the
index; `read N/M runs` on stderr) and one marker listing per parent. A
`vmn-exp ui` serving the store does this itself unless `--read-only` (see
[ui.md](ui.md#store-upkeep)), so the command is only needed without one:

```sh
vmn-exp backfill-children my_app --dry-run
vmn-exp backfill-children my_app --store s3://bucket/prefix
```

```
wrote 1840, present 12
```

It takes the repo lock like other writing actions, also runs without a
checkout (`--from-snapshot`), and exits 1 (adding `failed F`) when a marker
could not be written; run it again to retry. Markers are not record files:
listings, index signatures and the change journal ignore `children/`.
- Prints `<verstr>  backfilled|partial|skipped|failed[ (detail)]` per run
  (`<app>:` header lines under `--all-apps`), then `backfilled N, partial P,
  skipped S, failed F` (plus ` (dry run: nothing written)` with `--dry-run`).
  Exit 1 when any run failed; a second backfill skips every run.
- Takes the repo lock like `tag`, honours the store flags, works git-free.

### `export-metrics`

```sh
vmn-exp export-metrics my_app -v <ref> [-v <ref>...] [--keys loss acc] [-o metrics.parquet] [--format parquet|csv]
```

Writes the named runs' metric series as one long table with the columns
`run, writer, key, step, ts, value` (`ts` in microseconds since the epoch; a
step-less point has an empty `step`), so DuckDB, Polars or pandas can read it.
`--keys` keeps only those metric keys. The format comes from `--format`, else
from the `-o` suffix (`.csv` gives CSV); the default is `metrics.parquet`.
Parquet needs pyarrow (`pip install "vmn-exp[parquet]"`); without it the command
exits 1 and suggests `--format csv`, which needs nothing extra. Read-only (no
repo lock).

`vmn-exp compact my_app -v <ref>... | --all-finished` builds the compacted
metric index of runs whose writer died before doing it itself (running runs are
refused); `vmn-exp watch --compact` does the same for failed/stuck runs. A
`vmn-exp ui` serving the store compacts failed/stuck runs itself unless
`--read-only` ([ui.md](ui.md#store-upkeep)).

### `import-mlflow`

Import runs from an MLflow FileStore or tracking server:

```sh
vmn-exp import-mlflow my_app --mlruns ./mlruns                        # no mlflow package needed
vmn-exp import-mlflow my_app --tracking-uri http://mlflow:5000        # needs mlflow-skinny
vmn-exp import-mlflow my_app --mlruns ./mlruns --experiment my_exp --experiment 3 --dry-run
```

| Flag | Description |
|---|---|
| `--mlruns <dir>` / `--tracking-uri <uri>` | the source (exactly one) |
| `--experiment <name\|id>` | only this MLflow experiment (repeatable) |
| `--skip-artifacts` | don't copy local artifact files |
| `--include-deleted` | include deleted/trashed runs |
| `--dry-run` | preview, write nothing |
| `--workers N` | parallel workers (default 8) |
| `--refresh-features` | give already-imported runs the [features](#what-a-run-records-for-similar) (author, entrypoint, branch) and note their MLflow tags hold but the record lacks |
| `--repo <path>` | a checkout holding the runs' source commits: record what each commit's branch changed (`changed`, `changed_source: commit`) |

Re-import is idempotent: runs are keyed by MLflow `run_id` with a
deterministic verstr `0.0.0-mlflow.<run_id[:12]>`, so present runs are
skipped and parents resolve in any order. Prints `imported N, skipped M
(already present), resumed K, failed F` (with `--refresh-features`: `imported
N, skipped M (already present), resumed K, refreshed R, failed F`); exits 1 if
any failed. Takes no repo lock and never auto-inits; write outside a repo with
`--experiment-dir`/`VMN_EXPERIMENT_DIR` or straight to a store with `--store`. Imported runs have
no code (`restore`/`export`/`rerun` refuse them) and match
`imported_from != null`. The MLflow user, note, branch and entrypoint feed
[`similar`](#similar) ([tag mapping](migrating-from-mlflow.md#similar-runs-for-imported-runs)).
Guide: [migrating-from-mlflow.md](migrating-from-mlflow.md).

---

## Structured notes & params

`-f <yaml>` attaches structured metadata. On `create`/`run` the `params`,
`hypothesis` and `tags` keys become the run's inputs; on `add` the whole file
becomes a `structured` log entry.

```yaml
# params.yml
hypothesis: "larger batch size improves convergence"
params:
  lr: 0.001
  batch_size: 64
tags: [baseline, transformer-v2]
```

`params` are kept verbatim (strings and bools included; query them as
`params.<name>`); finite numeric params also fold into `metrics`. `exp diff`
prints a `params:` delta next to the `metrics:` delta. The `hypothesis` of
`create`/`run` (not `add -f`'s, whose `structured` entry is not matched) is
matched as text by [`similar`](#similar), like an
[intent](#intent-what-a-run-is-for) (which can be long and is replaceable later).

---

## Metrics schema (sorting & goals)

Declare goals and a primary metric in `.vmn/{app}/conf.yml`:

```yaml
conf:
  experiment:
    metrics:
      loss:       {goal: min, primary: true}   # lower is better; default sort key
      acc:        {goal: max}
      "val_*":    {goal: min}                  # glob; an exact name beats it
      "grad_*":   {hidden: true}
      val_acc:    {step_metric: epoch}
```

| Key | Effect |
|---|---|
| `goal: min\|max` | best-first sort direction (a metric without a goal sorts ascending); also sets the default summary |
| `primary: true` | the sort key of `list`/`list_runs` when `--sort` is omitted |
| `summary` | which value a repeated metric folds to (below) |
| `hidden: true` | out of the UI's default leaderboard columns and chart grid (still sorts, queries, summarizes) |
| `step_metric: <name>` | chart against that metric instead of the step ([sdk.md](sdk.md#custom-x-axis-step_metric)) |

Schema columns come first in `list`/`compare`, the rest alphabetically. Runs
can declare `goal`/`hidden` themselves (`run.define_metric`, `add
--define-metric`): for names conf.yml lacks, the latest run's declaration
sets the sort direction of `list --sort`, `list_runs()` and the UI
leaderboard (conf.yml always wins) — so a store-only UI workspace without a
conf.yml still sorts best-first.

### Store settings (`vmn-exp settings`)

The same `metrics:` keys (and `ui:` ones) can live in the store, for readers
without the checkout — a store workspace in `vmn-exp ui`, `list_runs()` or
`vmn-exp list` over a shared store:

```sh
vmn-exp settings my_app set -f settings.yml --store s3://bucket/prefix
vmn-exp settings my_app [show] --store s3://bucket/prefix   # prints the file
```

The file holds the inside of conf's `experiment:` block (`metrics`, `ui`);
`set` refuses unknown keys and bad values (exit 1). It is stored at
`settings/<app-key>/app/experiment.yml` and needs no git checkout
(`--dir`/`--store`/`--bucket` or the env, like `vmn-exp model`).
Precedence: conf.yml > store settings > run declarations, per metric name.
See [server.md](server.md#app-settings) for the UI side.

### Best-value summaries (`summary`)

A metric logged many times folds to one number per run:

| `summary` | `metrics.<name>` is |
|---|---|
| `last` | the latest value |
| `min` / `max` | the smallest / largest finite value |
| `first` | the earliest value (by timestamp, across writers) |
| `mean` | the mean of the finite values |

Without `summary` it follows `goal` (`min` → `min`, `max` → `max`), else
`last`. So with `loss: {goal: min}` an overfitting run (1.0, 0.2, 0.9) ranks
on 0.2. Use `{goal: min, summary: last}` to sort best-first on the final
value.

- The summary is what everything ranks and filters on: `list --sort`,
  `--query metrics.x`, `prune`, `compare`, `diff`, the UI, `list_runs()`.
  Every metric logged more than once also carries `metric_summary`
  (`{last, min, max, first, mean}`) in `list --json`/`show --json`, SDK rows
  and the UI; `show` prints `loss: 0.2 (last 0.9, min 0.2, max 1)`.
- **Precedence**: the run's own `define_metric` > conf.yml > `last`; in each,
  an exact name beats a glob. Another run's declaration never changes this
  run's summary.
- **After the fact**: `vmn-exp add my_app -v <ref> --define-metric val_loss
  --goal min` (needs at least one of `--goal`/`--summary`/`--step-metric`/
  `--hidden`) — handy for a `vmn-exp run` whose child only wrote `key=value`
  lines.
- **Live**: conf.yml policies apply at read time, so editing them re-ranks
  existing runs. A store workspace in `vmn-exp ui` has no conf.yml; the
  app's [store settings](#store-settings-vmn-exp-settings) and the runs' own
  definitions apply there.
- NaN/inf may be a `last`/`first` but never a `min`/`max` or part of a `mean`;
  a metric with no finite value sorts last.

SDK side: [Metric goals and summaries](sdk.md#metric-goals-and-summaries).

---

## Storage (local, S3, GCS, Azure, plugins)

Runs live in the repo-local store `.vmn/store/` by default. To share across a team,
point any action at a **store URI**:

```sh
vmn-exp run my_app --store s3://my-experiments/team/ml -- ./t.sh
vmn-exp run my_app --store "s3://my-experiments/team/ml?endpoint_url=http://minio:9000" -- ./t.sh
vmn-exp run my_app --store gs://my-experiments/team/ml -- ./t.sh
vmn-exp run my_app --store az://experiments/team/ml -- ./t.sh
vmn-exp run my_app --store file:///mnt/nfs/experiments -- ./t.sh
```

| URI | Backend | Notes |
|---|---|---|
| `s3://bucket[/prefix][?endpoint_url=...]` | S3 / MinIO / LocalStack | extra `vmn-exp-sdk[s3]` (boto3); AWS credentials as usual |
| `gs://bucket[/prefix]` | Google Cloud Storage | extra `[gcs]`; Application Default Credentials |
| `az://container[/prefix][?account_url=...]` | Azure Blob Storage | extra `[azure]`; `AZURE_STORAGE_CONNECTION_STRING`, else `AZURE_STORAGE_ACCOUNT_URL` + `DefaultAzureCredential` |
| `file:///abs/dir` (or a bare path) | a local/NFS directory | used *as* the local root, no cache in front |
| `<scheme>://...` | a plugin | see [Storage backends](#storage-backends-plugins) |

A URI without a prefix uses the root `vmn`. A missing SDK fails with the
`pip install` line to run.

**Layout.** Every store (repo-local, `file://`, bucket) has one layout
under its root:

```
<root>/
  store.yml                                  layout marker
  runs/<app-key>/<verstr>/                   experiment runs
  snapshots/<app-key>/<verstr>/              vmn snapshot records
  code/<app-key>/<code_verstr>.<diff_hash>/  shared code objects
  sweeps/<app-key>~<sweep>/<slot>/           sweep trial claims
  registry/<model>/<record>/                 model/dataset registry
  reports/  comments/  journal/
  settings/<app-key>/app/                    app settings (experiment.yml)
```

`<app-key>` is the app in tag form (`root_app/service` → `root_app-service`).
The repo-local root is `<repo>/.vmn/store/` with one `.gitignore` of `*`.
The first writer creates `store.yml` (`layout: 2`); readers and writers
refuse an unknown layout, and a v1 store (records but no `store.yml`) is
refused with a hint to run [`vmn-exp migrate`](#migrate). Per-host state
(the [index cache](#the-experiment-index-per-host-cache) and the [push](#offline-recording-and-push) ledger) lives
outside the store, in the user cache/state dirs (`$VMN_EXP_CACHE_DIR`
overrides both).

**Resolution.** `--store` > `VMN_EXPERIMENT_STORE` > conf
`experiment.storage.uri`. `--bucket`/`--prefix`/`--endpoint-url` (env
`VMN_EXPERIMENT_BUCKET`/`_PREFIX`/`_ENDPOINT_URL`, conf `bucket`/`prefix`/
`endpoint_url`) are shorthand for an `s3://` URI; any store URI wins over
them. The local root is `--experiment-dir` > conf
`experiment.storage.experiment_dir` > `VMN_EXPERIMENT_DIR` > the checkout. With a remote store and a
local root, runs record locally and sync to the store; without a local root
they go straight to the store. [`VMN_EXP_OFFLINE`](#offline-recording-and-push)
drops the remote.

```yaml
# .vmn/my_app/conf.yml
conf:
  experiment:
    storage:
      uri: gs://ml-experiments/team
      writer_id: ci-runner        # optional; VMN_WRITER_ID and --writer-id win
```

### Git-free mode

A tree from [`vmn-exp export`](#export) carries `vmn_metadata.yml`, so a
container can record runs without git:

```sh
vmn-exp run my_app --from-snapshot /mnt/code --experiment-dir /mnt/runs -- python train.py
# or: VMN_SNAPSHOT_METADATA=/mnt/code/vmn_metadata.yml VMN_EXPERIMENT_DIR=/mnt/runs
```

`--from-snapshot` (or `$VMN_SNAPSHOT_METADATA`) accepts the file or its
directory. In this mode `create`, `run`, `add`, `list`, `show`, `compare`,
`prune`, `rewind`, `push`, `similar-backfill`, `backfill-children` and `similar` (with `-v`/`--latest`
or `--text-only`) work; other actions need a checkout. A run recorded this way
copies the exported run's [features](#what-a-run-records-for-similar) from
`vmn_features.yml`.
`start_run()` honours the same variables
([sdk.md](sdk.md#runs-without-a-git-checkout-containers)).

### Storage backends (plugins)

The URI scheme picks the backend. Built-ins are `file`, `s3`, `gs` and `az`;
a package adds (or overrides) a scheme under the `vmn_exp.storage`
entry-point group:

```toml
[project.entry-points."vmn_exp.storage"]
mem = "my_pkg.store:open_store"
```

`open_store(uri, area=...)` receives a `vmn_exp.storage.uri.StoreURI` (`scheme`,
`location` = bucket/container, `path` = root, `options` = the query string)
and an area (`runs`, `snapshots`, `code`, `sweeps`, `registry`, `reports`,
`comments`; see `vmn_exp.storage.areas`), and returns a
`vmn_exp.storage.base.SnapshotStorage`. `vmn_exp.storage.registry.register_store(scheme,
factory)` does the same at runtime. The contract:

- **Records**: `<root>/<area>/<scope>/<name>/` (scope = app key, model name,
  ...) holding `metadata.yml`, patch files, per-stream
  `log/<stream>[@<seq>].jsonl` (a stream is `<writer>~<owner>`, see
  [How records are stored](#how-records-are-stored)), `metrics/` (see [Metric storage](#metric-storage)),
  `run_state.yml`, `outputs/` and `artifacts/`.
  `metadata.yml` makes a record exist: write it last, delete it first.
  Implement the abstract methods (`save`, `load_record`, `list_snapshots`,
  `update_note`, `delete`, `load_file`, `save_file`, `save_artifact_file`,
  `local_record_dir`) and override the defaulted ones your store does
  better (`list_verstrs`, `exists`, `update_metadata`, `list_files`,
  `read_file_from`, the log methods, `list_artifacts`, `artifact_uri`).
  Every backend implements `list_apps()`.
- **`create_exclusive` must be atomic**: of any number of hosts racing for a
  verstr exactly one gets `True`. A store `vmn-exp push` can target also takes
  `create_exclusive(..., claim_token=)`: a claim holding the same token but no
  `metadata.yml` is the caller's own crashed attempt and is resumed (`True`);
  other claims and records stay taken. The base-class default (check, then
  save) is *not* safe on a shared store — use a conditional create (`O_EXCL`
  mkdir, S3 `If-None-Match: *`, GCS `if_generation_match=0`, Azure
  `overwrite=False`). `update_metadata` should be a compare-and-swap.
- **Segments are created, never overwritten**: a local root ships its streams
  through `create_log_segment(app, verstr, stream, seq, data)` and
  `create_metric_segment(...)`, which store segment *seq* only if it does not
  exist yet and return whether they did (the same conditional create). A
  store without `create_log_segment` gets plain `save_file` writes, safe
  only while one process ships a record copy at a time;
  `create_metric_segment` is required for metric streams.
  `put_indexed(app, verstr, stream, path, replace=, covers=)` stores a
  stream's compacted `.vmx` covering its segments up to `covers` and deletes
  just those (and narrower `.vmx`), never a later segment.
- **Listing**: `list_verstrs` returns names only (claimed-but-unfinished
  included); `list_snapshots` returns only records whose `metadata.yml`
  exists; `list_files` maps `{verstr: {file: (size, mtime[, etag])}}` and
  drives incremental index refreshes, so a rewritten file must change its
  signature.
- **`is_remote()`** `True` for a network store (fronted by the local root when
  there is one; reads parallelized); `False` makes it the local root itself.
- **`cache_identity()`** returns a hashable name for the data (e.g.
  `(scheme, endpoint, bucket, prefix)`) so process-wide caches never mix stores.

An object store with conditional create and overwrite gets all of this by
subclassing `vmn_exp.storage.s3.S3SnapshotStorage` with a
`vmn_exp.storage.object_client.ObjectClient` adapter — how the GCS and Azure
backends are built.

### How records are stored

- **One directory (or key prefix) per run**: `metadata.yml`, `run_state.yml`,
  `env.yml`, `alerts_sent.yml`, one append-only `log/<stream>.jsonl` per
  stream, its metric files under `metrics/` ([below](#metric-storage)), `outputs/` (vmn's own files: `output.log`, `media/<name>/<step>.png`,
  `tables/<name>/<step>.json`) and `artifacts/` (the user's only, so any name
  is free). `metadata.yml` is written last, so a half-created run is never
  listed. Local writes are atomic (temp + rename).
- **Atomic allocation**: a new run claims its verstr atomically, so two hosts
  running the same commit against a shared bucket or directory get `…` and
  `….r2`, never one merged run.
- **Object keys**: `<root>/runs/<app-key>/<verstr>/<file>`, `<app-key>` in tag
  form (`root_app/service` → `root_app-service`).
- **Streams**: a stream is `<writer>~<owner>`: the writer id (the host name by
  default) and an owner id the local record copy keeps in its
  `.stream-owner`, tied to the directory's `(st_dev, st_ino)`: a symlink, a
  bind mount or a rename on one filesystem keep it; another directory (a
  copy elsewhere, a backup restored at the same path, a cross-filesystem
  move, a copy deleted and fetched again) mints a new one, and so does a
  stream once compacted. A process seeing the directory under another
  `st_dev` (a container) keeps the owner when the inode and path agree, else
  gets one owner of its own. Only a stream's owner ships, compacts and pushes
  it: the streams a copy *inherited* from its original stay as they are, and
  a sync or push notes on stderr when the remote lacks part of them; adopt
  them with `vmn-exp push --adopt` ([push](#offline-recording-and-push)) once the
  original checkout is gone. Every
  process of one checkout appends to the same stream; two clones on one host
  never share one. Without a local copy (straight to a bucket) the owner is
  the process's. Displays (log `_writer`, UI writer columns,
  `export-metrics`, authors) show the writer id only.
- **Incremental log sync**: a local copy is the only source of its streams,
  so a sync ships what the remote lacks of each of them as the next segment
  `log/<stream>@<n>.jsonl`, created only if it does not exist; a taken
  segment is listed again and the ship resumes from the remote size. What
  the remote holds is kept in `<record>/.ship/`, shared by the copy's
  processes under one lock. Readers merge all streams. Log batches are
  written as whole lines in one write (one PUT), so readers never see a
  partial line.
- **Caching**: immutable files fetched from a remote (metadata, patches) are
  cached locally; `run_state.yml` and logs never are, so another host's run
  shows its live status.
- **Code stored once per code identity**: a run's patches and untracked
  tarball live in one *code object* per identity — a record
  `<code_verstr>.<diff hash>` in the store's `code` area
  (`.vmn/store/code/<app-key>/…` locally, shared with `vmn snapshot`) — and the run's
  `metadata.yml` names it as `code:`. The object's `metadata.yml`, written
  last, marks it complete. A run of already-stored code uploads nothing but
  its own record. When the object is missing or incomplete,
  `restore`/`goto`/`export` refuse ("code snapshot … is missing from the
  store"). `prune` deletes an object with the last run of its code; a
  clean-tree run has none.
- **Artifacts** stream to remote stores (multipart for large files) and are
  listable and downloadable. Names may be nested relative paths; absolute
  paths, `..`, `.`, empty components, backslashes and NUL are refused.
- **Format version**: new runs (and registry records) store `format_version`
  (currently 2) covering metadata, log lines, metric files and `run_state.yml`. `list`,
  `show`, the UI and the SDK skip records from a newer format with a warning
  to upgrade, and records without it (v1) with a warning to run
  `vmn-exp migrate`.

### The experiment index (per-host cache)

`list`, `show`, `compare`, `similar`, ref resolution, the SDK readers and the
submission hint read an app's runs through its *experiment index*: one
SQLite file per app per store on this host, never inside the store. It is a
cache: deleting it costs one rebuild from the store, never data.

- **Location**: `<cache>/index/<store-id>/<app-slug>.<hash8>.sqlite`.
  `<cache>` is `$VMN_EXP_CACHE_DIR`, else `$XDG_CACHE_HOME/vmn-exp`, else
  `~/Library/Caches/vmn-exp` (macOS) or `~/.cache/vmn-exp`;
  `$VMN_INDEX_CACHE_DIR` replaces the index root alone (`none` turns the file
  off). `<store-id>` is a hash of the store's identity (a local root's
  absolute path, a bucket's endpoint, bucket and prefix), so two stores never share a file; the
  app slug carries a hash of the app name, so apps whose slugs collide never
  do either. Without a file (off, or an unwritable dir) every command builds
  the index in memory from the store. The CLI and the SDK of one host share
  the file; `vmn-exp ui` keeps its own under its data dir
  ([server.md](server.md)).
- **Network filesystems**: SQLite's locking and WAL are unreliable on NFS,
  SMB, sshfs and the like. A default cache dir on one is warned about once and
  replaced by `$TMPDIR/vmn-exp-cache-<uid>`; a dir chosen with
  `VMN_EXP_CACHE_DIR` (or `VMN_INDEX_CACHE_DIR`) is used as given.
- **What it holds**, each written in the refresh's one transaction: every
  record's folded log and run state; its *lean row* in `exp_rows` (the row
  `list` prints, with `idx`, `status`, `parent`, `root`, `timestamp`, `name`
  and `archived` as indexed SQL columns); its side tables (features, intent,
  hypothesis, outputs, metric summaries, declared metrics) in `exp_sides`;
  and its [similar-runs](#similar) document in the FTS5 tables. A new process
  starts from the lean rows without decoding any full record.
- **Point reads**: resolving a ref (an exact verstr, `@N`, a unique prefix,
  `latest`) for `show -v`, `reader.get_run`, `restore`, `export`, a dev-version
  `goto` and every other `-v` is one indexed query on `exp_rows`, with no
  snapshot of the app. Records created since the last refresh are read and
  persisted first and records gone from the store forgotten, so refs and
  parent/child links are current; the record names are not even listed while
  the local app directory's mtime has not moved since the last such read. A
  run edited in place since keeps its persisted row until the next refresh
  (the command reads the run itself from the store). `list` lets SQL pick
  the rows it can keep (the archived filter, `--last N` without a query, and
  a query's top-level `status`/`parent`/`verstr`/`name`/`archived` clauses)
  and reads only those runs and their trees.
- **Revalidation**: a refresh lists the record *names* (one directory
  listing, or a delimiter LIST on a bucket) with a cheap per-record
  signature where the backend has one (a local record directory's mtime and
  inode, which every vmn write moves), and lists the files of only the new
  records, the running ones, the recently changed ones (5 minutes) and those
  whose signature moved. A name gone from the listing drops its run at once.
  The listing baselines persist in the file, so a new process does the same
  rather than starting over. Every 300 s (across processes) one full sweep
  lists every record's files, which catches what no signature shows: a
  finished run changed in place behind vmn's back, on a pure S3 store (S3
  has no per-record signature), or by another host on a cached remote store
  (behind this host's local copy) shows up within 300 s, at the first
  command after.
- **Rebuilds never delete a live file**: a rebuild or a corruption recovery
  writes a new generation `<name>.<n>.sqlite` beside it and atomically
  flips the pointer file `<name>.sqlite.current`; every open follows the
  pointer, and an old file is removed only once no connection holds it.
- **Schema versions**: a file written by an older vmn-exp has its tables
  replaced in one transaction (a rebuild). A file written by a *newer*
  vmn-exp is left alone: the older process works without it (in memory),
  so two versions sharing a host never wipe each other's cache.
- **Failures are never fatal**: WAL with `synchronous=NORMAL`, a 5 s busy
  timeout, writes in `BEGIN IMMEDIATE`. A file that will not open is
  retried with a backoff (up to 60 s); a failed save keeps its records
  dirty for the next refresh; each kind of trouble with a file warns once,
  naming the file and the reason.

### Metric storage

Metric values are not JSONL log lines. Each stream records them columnar
(int64 steps and microsecond timestamps, float64 values, per key):

- **While the run is live**: an append-only stream `metrics/<stream>.vms`, one
  block per flush (the SDK batches like the log). A remote store gets the
  appended blocks as segments `metrics/<stream>@<seq>.vms` on each sync. A
  long writer compacts its stream every 10M points and goes on in a new one
  (a new owner), so live readers don't decode the whole stream.
- **Compacted at the end**: when a writer finishes (`finish()`/exit of an SDK
  run within its final upload wait, `vmn-exp run` at the child's exit, the
  importers), its stream's points become one indexed file
  `metrics/<stream>@000000-<last>.vmx`, which replaces the stream's segments
  up to `<last>` (a later segment stays and reads beside it); the record copy
  then appends to a new stream. Per key it holds the points sorted on
  the key's axis in separately compressed chunks plus a level-of-detail pyramid
  of min/max buckets, and a footer indexing all of it, so a chart of any length
  reads the footer and one small slice (byte-range reads on object stores).
  Rewinds known at that time are applied; a later `rewind` rebuilds the file.
- **Writers that died** keep their stream; it reads the same, just slower.
  `vmn-exp compact` or `vmn-exp watch --compact` compacts them later. If
  compaction does not finish within the final upload wait, the run warns
  `metrics stay uncompacted (vmn-exp compact)`.

Readers (`show`, the index, the UI, the SDK readers) merge every writer's
files, and show the points as `metrics` entries in log views, so nothing
reading a run changes. They still read the `metrics` entries of older JSONL
logs.

### `migrate`

`vmn-exp migrate [--store <uri> | --dir <path>] [--dry-run] [--skip-live]`
converts a v1 store to layout 2. Without a flag it moves the checkout's v1
records (`.vmn/<app>/experiments/`, `.vmn/<app>/snapshots/`, the `vmn-code`/
`vmn-sweeps`/`vmn-registry` pseudo-apps) into `.vmn/store/`; `--dir` takes a
dir whose v1 records sit under `<dir>/.vmn`; `--store` an object store (or
`file://`). It sets `migrating: true` in `store.yml` (writers refuse
meanwhile), copies each record to its v2 path (area, tag-form key, `log/`,
`outputs/`; `metadata.yml` last) and deletes the old copy, then clears the
flag. On the way, each writer's JSONL `metrics` entries move into one
compacted `metrics/<writer>@000000-000000.vmx` (rewinds applied) and the record gets
`format_version: 2`. Record by record, so a killed migration resumes on rerun. Running or
stuck runs stop it with a list unless `--skip-live` (rerun later for those).
`--dry-run` prints the plan and changes nothing.

---

## Offline recording and push

Compute nodes often can't reach the bucket that the committed conf.yml names.
`VMN_EXP_OFFLINE=1` (`true`/`yes`/`on`) makes every storage factory —
`vmn-exp` actions, `start_run()`, `vmn snapshot` — drop the remote store and
record to the local root only (the checkout, or
`--experiment-dir`/`VMN_EXPERIMENT_DIR`). It beats flags, env and conf;
without a local root it fails rather than falling back. Code objects stay
local too.

An offline run can't see which names other hosts took, so it is named
`<code_verstr>.<writer_id>[.N]` instead of `.rN` (e.g.
`1.6.0-dev.a1b2c3d.e4f5g6h.gpu07`, then `….gpu07.2`); the writer id is
`$VMN_WRITER_ID`, else `--writer-id`, conf `writer_id`, `$HOSTNAME`, the host
name.

Upload later, from a host that reaches the store:

```sh
VMN_EXP_OFFLINE=1 vmn-exp run my_app -- python train.py      # on the node
vmn-exp push my_app                                          # every local run
vmn-exp push my_app -v @3 -v 1.6.0-dev.a1b2c3d.e4f5g6h.gpu07 # just these
vmn-exp push my_app --store s3://ml-exps/team --dry-run      # preview
```

```text
1.6.0-dev.a1b2c3d.e4f5g6h.gpu07  new
1.6.0-dev.a1b2c3d.e4f5g6h.gpu07.2  up-to-date
1.6.0-dev.a1b2c3d.e4f5g6h  new -> 1.6.0-dev.a1b2c3d.e4f5g6h.r3
pushed 2, up-to-date 1, renamed 1, skipped 0, failed 0
```

- **Target**: `--store` (or the bucket shorthand) > `VMN_EXPERIMENT_STORE` >
  conf. `VMN_EXP_OFFLINE` never hides it here. It must be a remote store;
  `file://` (rsync instead) and no remote are refused.
- **Same name, parents first**: the code object (if the remote lacks it), the
  claim, other top-level files, each writer's log from where the remote copy
  ends, each stream's missing or resized metric objects (a `.vmx` via
  `put_indexed`, which drops the remote segments it covers, else the local
  stream's blocks past the remote ones as its next segment), and missing or resized artifacts. `archived`/`note` merge three-way
  against what was last pushed; on conflict the remote wins, with a warning.
- **Resumable**: a per-host ledger per remote (user state dir,
  `$XDG_STATE_HOME/vmn-exp/push/...`, or under `$VMN_EXP_CACHE_DIR`) records
  what was sent, so an
  interrupted push is simply rerun; an unchanged run costs no remote call
  (`up-to-date`) and a changed one ships only what is new (`update`).
- **Collisions**: when the remote holds a different run under the name, the
  run is renamed on *both* sides to the next free `<code_verstr>.rN` (local
  directory, `verstr`, `renamed_from`, and its children's `parent`). Running
  or stuck runs, runs a local model version references and sweep outer runs
  are `skipped` instead.
- **Output**: `<verstr>  <status>[ -> <new name>][ (<reason>)]` per run
  (`new`, `update`, `up-to-date`, `skipped`, `failed`; `collision` in a
  dry-run), then the summary. `--json` prints a list of `{verstr, status,
  detail, warnings, renamed_from}`. Exit 1 when any run failed.
- **Copied or moved records**: a run whose record came from another checkout
  (a `cp -r` of the repo, a backup restored, a move across filesystems) holds
  that checkout's streams. Only their owner pushes them, so push leaves them
  alone and prints a one-line note on stderr when the remote lacks part of
  them (another view of the folder, e.g. a container mounting it at another
  path, counts as another checkout). `--adopt` makes this checkout their
  owner for the selected runs (catching their files up with what the remote
  holds first) and pushes them, then and on every later sync/push. It never
  deletes local points the remote does not provably hold: when a remote
  `.vmx` lacks some (another clone compacted what the original had shipped),
  that run is refused with a one-line error, left unchanged, and counted
  failed (exit 1), while the other runs are adopted. Run it only when the
  original checkout is gone or will never write again — otherwise two
  checkouts would ship one stream:

  ```sh
  vmn-exp push my_app -v 1.6.0-dev.a1b2c3d.e4f5g6h.gpu07 --adopt
  ```
- Takes the repo lock (it may rename local runs); works git-free. The UI runs
  it as the `exp_push` job action ([ui.md](ui.md#actions)).

---

## Environment variables

Read by `vmn-exp` (most also by the SDK):

| Variable | Effect |
|---|---|
| `VMN_EXPERIMENT_STORE` | store URI fallback for `--store` |
| `VMN_EXPERIMENT_BUCKET` / `_PREFIX` / `_ENDPOINT_URL` | fallbacks for the `s3://` shorthand flags |
| `VMN_EXPERIMENT_DIR` | local experiment root (`--experiment-dir`) |
| `VMN_SNAPSHOT_METADATA` | [git-free mode](#git-free-mode) (`--from-snapshot`) |
| `VMN_EXP_OFFLINE` | `1`/`true`/`yes`/`on`: [record locally only](#offline-recording-and-push) |
| `VMN_WRITER_ID` | writer id (`--writer-id`) |
| `VMN_WORKING_DIR` | the directory `run` starts the command in |
| `VMN_MODE` | `disabled`: `run` execs the command without recording |
| `VMN_CAPTURE_ENV` | `0`/`false`/`no`/`off` disables [environment capture](#environment-capture) |
| `VMN_EXP_AUTHOR` | the email a new run's [`features`](#what-a-run-records-for-similar) author gets when git config has no `user.email` (git-free: after the export's `exported_by`; git mode: before the first local commit's `From:`) |
| `VMN_SYSTEM_METRICS` | `0`/`false`/`no`/`off` disables `sys_*` sampling |
| `VMN_EXP_OUTPUT_CAP_MB` | `output.log` cap (`--output-cap-mb`) |
| `VMN_EXP_KILL_GRACE_SEC` | signal grace (`--kill-grace-sec`) |
| `VMN_EXP_MIN_STALE_SEC` | floor of the `stuck` window (default 60) |
| `VMN_EXP_ALERT_WEBHOOK_URL` / `_SLACK_URL` / `_COMMAND` / `_ON` | [alert](#alerts) sinks and triggers |
| `VMN_SNAPSHOT_MAX_FILE_MB` / `_TOTAL_MB` | untracked-file capture caps (50 / 200) |
| `VMN_EXP_CACHE_DIR` | base dir for per-host state (index cache, push ledger) instead of the XDG cache/state dirs |
| `VMN_INDEX_CACHE_DIR` | index cache root only (`none` disables) |
| `VMN_IMAGE_DIGEST` | container image digest recorded by environment capture |
| `VMN_LOCK_FILE_PATH` | repo lock path (default `.vmn/vmn.lock`) |

SDK-only variables (`VMN_RESUME_RUN_ID`, `VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC`)
are in [sdk.md](sdk.md). Set **by** vmn for a `run` child:
`VMN_EXPERIMENT_ID`, `VMN_APP_NAME`, `VMN_METRICS_FILE`,
`VMN_EXP_SUPERVISOR_SAMPLES`; sweep trials also get `VMN_SWEEP_PARAMS`,
`VMN_SWEEP_ID`, `VMN_SWEEP_TRIAL` ([sweeps.md](sweeps.md)).

---

## Web UI

`vmn-exp ui` (`pip install "vmn-exp[ui]"`) serves a dashboard over the same
files: a sortable board of runs grouped by parent run, fork, rerun, code or a field, live
curves from `step=` series, compare with a real code diff, an Importance view,
artifacts, media and lineage. Deployment, workspaces, job actions and the
HTTP API are in [ui.md](ui.md).
