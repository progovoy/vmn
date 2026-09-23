# Experiments

`vmn experiment` (alias: `vmn exp`) is local-first experiment tracking for any
versioned app. An "experiment" is a **snapshot of your working tree plus a log of
metrics and notes** — nothing more. There is no required training script, no
server, and no database. Experiments are plain files under
`.vmn/{app}/experiments/` (git-ignored, never committed or pushed), each anchored
to an exact version and commit so reproducing a result is one `vmn exp restore`
away.

Machine-learning training is the headline use case, but the mechanism is
general. Anything you can measure and want to reproduce fits: **config sweeps,
performance/benchmark runs, load tests, data-pipeline outputs, compiler flag
comparisons.** If you can print a `key=value`, vmn can track it.

- [Mental model](#mental-model)
- [Four ways to record an experiment](#four-ways-to-record-an-experiment)
- [Without a script: config sweeps & performance tests](#without-a-script-config-sweeps--performance-tests)
- [With a command: `exp run` and the metrics file](#with-a-command-exp-run-and-the-metrics-file)
- [From Python: the SDK](#from-python-the-sdk)
- [Run status: did my job die?](#run-status-did-my-job-die)
- [Outer & inner jobs (sweeps)](#outer--inner-jobs-sweeps)
- [Addressing experiments](#addressing-experiments)
- [Subcommand reference](#subcommand-reference)
- [Structured notes & params](#structured-notes--params)
- [Metrics schema (sorting & goals)](#metrics-schema-sorting--goals)
- [Storage (local & S3)](#storage-local--s3)
- [Web UI](#web-ui)

---

## Mental model

Each experiment captures:

1. **Code state** — the base version, the base commit, and a diff of any
   uncommitted working-tree changes (and local-only commits). This is what
   `restore`, `diff`, and `export` replay. Config edits count as code state, so
   an experiment records exactly which knobs you changed, committed or not.
2. **A log** — an append-only list of entries: the initial `create`, plus any
   `metrics`, `note`, `artifact`, `run`, or `structured` entries you add later.
   The log is never rewritten; `add` only appends.

Experiments are **content-addressed**. The verstr looks like:

```
1.6.0-dev.a1b2c3d.e4f5g6h
        │        │
        │        └─ hash of your working-tree diff (0000000 on a clean tree)
        └─────────── short base commit
```

Because identical code produces an identical verstr, re-running the same state
does **not** overwrite the previous run — each new run over an existing state
gets a `.r2`, `.r3`, … suffix. That is how "same config, different seed" or
"same benchmark, second measurement" stay as distinct rows.

The first `exp create` / `exp run` in a fresh repo **cold-starts** everything:
it auto-initializes vmn tracking and stamps a `0.0.0` baseline for you. No
separate `vmn init` or `vmn stamp` is required.

---

## Four ways to record an experiment

| You want to… | Use |
|---|---|
| Capture the tree and type in the numbers yourself | `exp create … --metrics k=v` |
| Add more numbers/notes/files to an existing run later | `exp add …` |
| Let vmn run a command and slurp metrics it emits | `exp run … -- <cmd>` |
| Log from inside your own Python process | [`start_run(...)`](#from-python-the-sdk) |

All four snapshot the working tree (dirty or clean). They differ only in *how*
the metrics get in, and they produce the same run on disk. You can mix them —
e.g. `exp run` a benchmark, then `exp add` a hand-measured number afterward, or
`exp show` a run your Python script opened.

Untracked (non-ignored) files are captured too, within size caps so a stray
checkpoint or dataset never balloons every run: files over 50 MB are skipped,
and at most 200 MB is collected per snapshot. Override with
`VMN_SNAPSHOT_MAX_FILE_MB` / `VMN_SNAPSHOT_MAX_TOTAL_MB`. Skipped paths are
logged and recorded in the run's metadata as `untracked_skipped`, so a restore
can tell you what it could not bring back.

---

## Without a script: config sweeps & performance tests

You do **not** need a `train.py` (or any command) to use experiments. This is
the workflow for playing with a config and recording how each variant performs.

### Record measurements by hand

Edit your config, then capture the state together with whatever your test
measured:

```sh
# edit config.yml (uncommitted is fine — it's captured either way)
vmn exp create my_app --note "batch=64, cache on" --metrics latency_ms=12.3 throughput=8100
```

`exp create` snapshots the tree and prints the new verstr. Add more numbers to it
in as many passes as you like:

```sh
vmn exp add my_app --latest --metrics p99_ms=41 --note "warm run"
```

Change the config and capture again. Repeated identical states get `.rN`
suffixes, so nothing is clobbered:

```sh
# tweak config.yml ...
vmn exp create my_app --note "batch=128" --metrics latency_ms=15.1 throughput=9400
```

### Compare the sweep

Because each snapshot captures the config diff, you can line the variants up:

```sh
vmn exp list my_app                  # table of runs + their latest metrics
vmn exp compare my_app --last 3      # metrics side-by-side across the last 3
vmn exp diff my_app -v @1 -v @2      # real config/code diff + metric delta
```

### Record which knobs you set

Use a YAML file to log the inputs alongside the measurements, so the run is
self-describing:

```yaml
# variant.yml
hypothesis: "larger batch trades latency for throughput"
params:
  batch_size: 128
  cache: true
  workers: 8
tags: [perf, batch-sweep]
```

```sh
vmn exp create my_app -f variant.yml --metrics latency_ms=15.1 throughput=9400
```

`--metrics` records outputs; `-f variant.yml` records inputs (`params`,
`hypothesis`, `tags`). They are stored separately and never overwrite each other,
and `exp diff` shows a `params:` delta line so you can see exactly which knob
moved between two runs.

---

## With a command: `exp run` and the metrics file

`exp run` snapshots the tree, runs **any** command (a shell script, `hyperfine`,
`wrk`, `pytest-benchmark`, `python train.py` — anything), and records the exit
code and duration. The command inherits your terminal, so its output streams
live.

```sh
vmn exp run my_app --note "batch=64" -- ./perf_test.sh
```

Everything after the first `--` is the command. `vmn exp run` returns the
command's own exit code, so CI can tell a failed run from a passing one — or
`128 + N` when signal N ended it, the way a shell reports it.

The command runs in the directory you invoked `vmn` from (or
`$VMN_WORKING_DIR` when set), not the repo root, so
`cd src && vmn exp run my_app -- python train.py` finds `src/train.py`.

### The metrics-file protocol

vmn sets three environment variables for the child process:

| Variable | Value |
|---|---|
| `VMN_EXPERIMENT_ID` | the verstr of this run — also how [nesting](#outer--inner-jobs-sweeps) is detected |
| `VMN_APP_NAME` | the app name |
| `VMN_METRICS_FILE` | a path your command appends metrics to |

Any line your command writes to `$VMN_METRICS_FILE` is ingested as a metrics
entry. The grammar is:

```
[step=N] key=value [key=value ...]
```

- Numeric values are parsed as floats; anything else is kept as a string.
- An optional leading `step=N` builds a **per-step series** (a curve). Without
  it, the values are recorded as scalars.
- vmn **tails the file live** during the run, so metrics appear in `exp show`
  and the web UI *while the command is still running*, not just at the end.

A performance test in plain shell:

```sh
#!/usr/bin/env bash
# perf_test.sh
start=$(date +%s.%N)
./run_benchmark --requests 100000
end=$(date +%s.%N)

echo "latency_ms=$(compute_p50)"           >> "$VMN_METRICS_FILE"
echo "p99_ms=$(compute_p99)"               >> "$VMN_METRICS_FILE"
echo "wall_sec=$(echo "$end - $start" | bc)" >> "$VMN_METRICS_FILE"
```

The same protocol from Python (with a per-step series):

```python
import os

metrics_file = os.environ["VMN_METRICS_FILE"]

def log_metric(key, value, step=None):
    with open(metrics_file, "a") as f:
        prefix = f"step={step} " if step is not None else ""
        f.write(f"{prefix}{key}={value}\n")

for i in range(10):
    log_metric("throughput", measure(), step=i)   # -> a live curve
log_metric("p99_ms", final_p99())                  # -> a final scalar
```

---

## From Python: the SDK

When the workload is already Python, you don't need `exp run` or a metrics file
at all — open the run in-process:

```python
from version_stamp.exp import start_run

with start_run("my_app", note="baseline", params={"lr": 3e-4}) as run:
    for step, loss in enumerate(train()):
        run.log_metric("loss", loss, step=step)
    run.log_metrics({"acc": 0.91})
    print(run.id)     # 1.6.0-dev.a1b2c3d.e4f5g6h
```

The result is **the same run** the CLI would have written: same verstr, same
files, same heartbeat — so `exp list`, `exp show`, `exp compare`, the web UI and
S3 sync all work on it unchanged, and nesting still produces outer/inner jobs.
Full guide, including the read-side API: [docs/sdk.md](sdk.md).

Two things only the SDK gives you: [autologging](sdk.md#autologging) — one
`autolog()` call records scikit-learn hyperparameters, scores and fitted models
with no logging in your training code — and the [query
language](sdk.md#the-query-language) for filtering runs on metrics and params.

---

## Run status: did my job die?

A long run can end in three ways: it finishes cleanly, it finishes with an
error, or the machine underneath it disappears without anybody writing that
down. `exp run` handles the third case by keeping a **heartbeat**.

While the child process is alive, `exp run` maintains a `run_state.yml` next to
the experiment's `metadata.yml` (same directory locally, same key prefix on S3):

```yaml
state: running          # "running" while alive, "finished" after the child exits
command: [python, train.py]
pid: 12345
host: somebox
started_at: 2026-09-21T12:00:00Z
heartbeat: 2026-09-21T12:03:00Z   # refreshed while the child is alive
heartbeat_interval_sec: 30
exit_code: null         # an int once finished
finished_at: null
duration_sec: null
```

The beat interval defaults to 30 seconds and is tunable:

```sh
vmn exp run my_app --heartbeat-interval 10 -- python train.py
```

An [SDK](sdk.md) run has no supervising process, so it beats from its own daemon
thread — `start_run(..., heartbeat_interval_sec=10)` — and everything below
applies to it identically.

### Derived statuses

Status is **never stored** — it is derived from `run_state.yml` plus the current
time, so a run whose machine vanished does not need anybody to update a record:

| Status | Means |
|---|---|
| `created` | the experiment exists but no command was ever started (e.g. `exp create`) |
| `running` | the heartbeat is fresh |
| `stuck` | claims to be running, but the heartbeat went stale and there is no exit code |
| `succeeded` | finished, exit code 0 |
| `failed` | finished, non-zero exit code |

`stuck` is the interesting one: the runner died, was OOM-killed, or lost its
node, and left nothing behind to say so. Several missed beats are tolerated
before vmn calls a run stuck — the staleness window is
`max(3 × heartbeat_interval_sec, 60s)`.

### Preemption and signals

A scheduler stopping the job (Slurm `scancel`, Kubernetes eviction, a spot
reclaim) sends `SIGTERM` to `vmn exp run`. vmn forwards it to the command, gives
the command `--kill-grace-sec` (default 30, or `$VMN_EXP_KILL_GRACE_SEC`) to exit
cleanly, kills it if it is still alive after that, and then **always** records
the final state — so a preempted run reads `failed`, never `stuck`, and the
command never outlives its supervisor. `SIGINT` and `SIGHUP` are handled the
same way, except that they are not re-sent when your terminal already delivered
them to the command (a Ctrl-C in the foreground reaches both). A second signal
kills the command at once.

The final `run_state.yml` says what happened:

```yaml
state: finished
exit_code: 143          # 128 + 15: the command died of SIGTERM
signal: SIGTERM         # present when a signal ended the command
received_signal: SIGTERM  # present when vmn itself was signalled
```

A command that traps `SIGTERM` and exits 0 (say, after checkpointing) keeps its
own exit code; `received_signal` still records that it was asked to stop.

Only a `SIGKILL` of `vmn` itself leaves a run claiming `running` — the stale
heartbeat then reports it `stuck`. A failing heartbeat write, a metrics line
that cannot be stored or a remote sync that errors or hangs never ends
supervision: vmn warns once and keeps watching the command.

> **Honest limitation:** a process that is *hung but alive* keeps heartbeating,
> so it still reads as `running`. To catch that, watch `last_metric_at` (exposed
> by the UI and API) — a run that is alive but has logged nothing for a long
> time is alive but not making progress.

### Seeing it

`exp list` shows a status per row; `exp show` prints a `Status:` line with the
exit code, duration, and pid/host — plus the heartbeat age when the run is
`stuck`:

```sh
vmn exp list my_app
vmn exp show my_app --latest
```

---

## Outer & inner jobs (sweeps)

`exp run` exports `VMN_EXPERIMENT_ID` to its child. Any experiment created
**while that variable is set** records it as its `parent`. So a sweep script
that itself calls `vmn exp run` per trial automatically produces one **outer**
job containing **inner** jobs — no wiring required.

```sh
#!/usr/bin/env bash
# sweep.sh — each trial becomes an inner job of the run that launched this script
for lr in 0.001 0.01 0.1; do
    vmn exp run my_app --note "lr=$lr" -- python train.py --lr "$lr"
done
```

```sh
vmn exp run my_app --note "lr sweep" -- ./sweep.sh
```

You can also parent explicitly, which is handy when the trials are launched from
somewhere that does not inherit the environment:

```sh
vmn exp run my_app --parent @3 -- python train.py --lr 0.01
vmn exp create my_app --parent latest --metrics acc=0.91
```

`--parent` takes any of the [addressing forms](#addressing-experiments): a full
verstr, a unique prefix, `@N`, or `latest`.

### kind and tree_status

Each run has a `kind`: `outer` (has children), `inner` (has a parent), or
`single` (neither). An outer job also gets a **`tree_status`** — the rollup over
itself and its whole subtree, with precedence:

```
failed > stuck > running > created > succeeded
```

One failed trial therefore makes the whole sweep read as failed, which is the
answer you usually want from a glance.

### What `exp list` looks like

Inner runs are indented under their outer run:

```
[1] 1.6.0-dev.a1b2c3d.9f8e7d6  succeeded/failed  (3s ago)  - lr sweep
  [2] 1.6.0-dev.a1b2c3d.9f8e7d6.r2  succeeded  (2s ago)  loss=0.31  - lr=0.001
  [3] 1.6.0-dev.a1b2c3d.1122334  succeeded  (2s ago)  loss=0.28  - lr=0.01
  [4] 1.6.0-dev.a1b2c3d.5566778  failed  (1s ago)  - lr=0.1
```

The sweep script itself exited 0, but one trial failed — so the outer row reads
`succeeded/failed`: **its own status, then its subtree's**. A single status token
means the two agree. `exp show` on the outer run prints `Children:` and a
`Subtree:` line when the rollup differs from its own status; on a trial it
prints `Parent:`.

---

## Addressing experiments

Every subcommand that takes a version accepts, in place of a full verstr:

| Form | Means |
|---|---|
| *(omitted)* | the latest experiment (for `add`/`show`/`restore`/`export`; `compare`/`diff` default to the latest two) |
| `--latest` | the most recent experiment, explicitly |
| `@N` | the N-th row shown by `vmn exp list` (1-indexed, oldest-first) |
| a unique prefix | e.g. `-v 1.6.0-dev.a1b` if it uniquely identifies one run |
| full verstr | exact, e.g. `-v 1.6.0-dev.a1b2c3d.e4f5g6h` |

```sh
vmn exp show my_app                 # latest
vmn exp show my_app -v @2           # the [2] row from list
vmn exp diff my_app -v @1 -v @3     # two specific runs
```

---

## Subcommand reference

### `create`

Capture the current state as an experiment without running anything. Works on a
clean or dirty tree (a clean tree zeroes the diff hash). Re-running over an
identical state starts a new `.rN` run instead of overwriting.

```sh
vmn exp create my_app --note "dropout 0.3" --metrics loss=0.45 acc=0.85
vmn exp create my_app -f params.yml --attach initial_weights.pt
vmn exp create my_app --parent @2 --metrics acc=0.91
```

An experiment created with no run has status `created`. `--parent <ref>` attaches
it as an [inner job](#outer--inner-jobs-sweeps) of another experiment.

### `run`

Create an experiment, run a command, and record its outcome (exit code,
duration) plus any metrics it emits to `$VMN_METRICS_FILE`. Publishes a
[`run_state.yml`](#run-status-did-my-job-die) with a heartbeat while the command
is alive.

Only creating the experiment takes the per-repo vmn lock; it is released before
the command starts. So a run that trains for hours leaves the repo usable — other
`vmn` commands, including ones the command itself runs, are unaffected, and
nesting `vmn exp run` inside `vmn exp run` works.

```sh
vmn exp run my_app --note "lr 0.01" -- python train.py --lr 0.01
vmn exp run my_app -- ./perf_test.sh
vmn exp run my_app --heartbeat-interval 10 -- python train.py
vmn exp run my_app --parent latest -- python train.py --lr 0.1
```

| Flag | Default | Description |
|---|---|---|
| `--heartbeat-interval <sec>` | `30` | How often the run refreshes its heartbeat |
| `--kill-grace-sec <sec>` | `30` (`$VMN_EXP_KILL_GRACE_SEC`) | How long a [signalled](#preemption-and-signals) command may take to exit before it is killed |
| `--sync-interval <sec>` | `30` | How often the log syncs to remote storage, off the supervise loop (`0` disables periodic sync) |
| `--parent <ref>` | *(inherited from `VMN_EXPERIMENT_ID`)* | Attach this run as an inner job of another experiment |

### `add`

Append metrics, a note, an artifact, or a structured entry to an experiment
(defaults to the latest). The log is append-only — nothing is overwritten.

```sh
vmn exp add my_app --metrics val_loss=0.29 val_acc=0.93
vmn exp add my_app -v @2 --attach checkpoint.pt --note "after warmup"
vmn exp add my_app -f extra_notes.yml
```

### `list`

List experiments with a [status](#run-status-did-my-job-die) per row, optionally
sorted by a metric. Inner runs are indented under their outer run.

```sh
vmn exp list my_app                        # all
vmn exp list my_app --sort loss --top 5    # best 5 by loss (goal-aware)
vmn exp list my_app --last 10              # most recent 10
```

The `[N]` in front of each row is the run's storage index — the same number
`-v @N` resolves — so it never changes with `--sort`, `--top` or `--last`:
`vmn exp list my_app --sort loss` showing `[7]` first means `vmn exp show my_app
-v @7` opens that run.

`list`, `show`, `compare`, `diff` and `export` (and `vmn snapshot
list|show|diff|export`) are read-only and take no repo lock, so they never wait
for — or hold up — a `create`/`run` in the same checkout.

Richer filtering — `metrics.loss < 0.5 and status = "succeeded"` — is available
from the SDK reader and the REST API via [the query
language](sdk.md#the-query-language), not yet as a flag here.

### `show`

Full details for one experiment: metadata, a `Status:` line (exit code,
duration, pid/host, and the heartbeat age when `stuck`), `Parent:`/`Children:`
lines, latest metrics, and the log timeline — the newest 50 entries, with a
line saying how many earlier ones were hidden. `--full-log` prints all of them.

```sh
vmn exp show my_app          # latest
vmn exp show my_app -v @1
vmn exp show my_app -v @1 --full-log
```

### `compare`

Side-by-side metric table across N experiments (no code diff — use `diff` for
that). Needs at least two. It reads only each run's metadata and log, never its
patches or untracked-file tarball, so comparing many runs stays cheap.

```sh
vmn exp compare my_app --last 3
vmn exp compare my_app -v @1 -v @4
```

### `diff`

Metric/param delta **plus a real source diff** between two experiments (defaults
to the latest two). Uses your git `diff.tool` if configured, or `--tool`.

```sh
vmn exp diff my_app                 # latest two
vmn exp diff my_app -v @1 -v @3
vmn exp diff my_app --tool delta
```

### `restore`

Check out the exact code state of an experiment and retrieve its artifacts. If
the working tree is dirty, that work is **auto-snapshotted first** (and the
recovery command is printed) — you never lose uncommitted changes.

```sh
vmn exp restore my_app --latest
vmn exp restore my_app -v @2
```

### `export`

Package an experiment (materialized code, metadata, metrics, artifacts) into a
directory or a `.tar.gz`.

```sh
vmn exp export my_app                        # latest -> <verstr>.tar.gz
vmn exp export my_app --latest -o best.tar.gz
```

### `prune`

Delete old experiments by count or age. Each deleted verstr is printed.

```sh
vmn exp prune my_app --keep 10              # keep the 10 most recent
vmn exp prune my_app --older-than 30d       # remove anything older than 30 days (Nd/Nw/Nh)
vmn exp prune my_app --keep 10 --dry-run    # print what would go, delete nothing
vmn exp prune my_app --keep 0 --local-only  # drop local copies, keep the S3 ones
```

Two guards take runs back out of the selection:

- a run whose status is `running` is never deleted (it is reported as skipped);
  `--force` deletes it anyway. A `stuck` run is deletable.
- a run with a kept descendant is kept, so no surviving inner run is left
  pointing at a parent that no longer exists.

With a remote bucket configured, prune deletes both the local and the remote
(S3) copy — which may hold your teammates' runs too. `--local-only` removes only
the local copies.

| Flag | Description |
|---|---|
| `--keep N` | Keep the N most recent experiments |
| `--older-than <dur>` | Delete experiments older than `Nd`/`Nw`/`Nh` |
| `--dry-run` | Print what would be deleted, delete nothing |
| `--force` | Also delete runs that are still `running` |
| `--local-only` | Keep the remote (S3) copies |

---

## Structured notes & params

Pass a YAML file with `-f` to attach structured metadata. On `create`/`run`, the
`params`, `hypothesis`, and `tags` keys are recorded as the experiment's inputs;
on `add`, the whole file becomes a structured log entry.

```yaml
# params.yml
hypothesis: "larger batch size improves convergence"
params:
  lr: 0.001
  batch_size: 64
  epochs: 50
tags: [baseline, transformer-v2]
```

```sh
vmn exp create my_app -f params.yml --metrics loss=0.38
```

`exp diff` prints a `params:` line showing which inputs changed between two runs,
next to the `metrics:` delta.

---

## Metrics schema (sorting & goals)

Declare each metric's goal and a primary metric in `.vmn/{app}/conf.yml` so
`list --sort` (and the web-UI leaderboard) know which direction is "better" and
what to sort by when you don't pass `--sort`:

```yaml
experiment:
  metrics:
    loss:        {goal: min, primary: true}   # lower is better; default sort key
    val_loss:    {goal: min}
    acc:         {goal: max}                   # higher is better
    latency_ms:  {goal: min}
```

- `goal: min` → best-first ascending. `goal: max` → best-first descending.
  Metrics with no declared goal default to higher-is-better.
- `primary: true` marks the metric used to sort `list` when `--sort` is omitted.
- Schema columns also fix the column order in `list`/`compare`; any extra
  metrics you logged appear after them, alphabetically.

---

## Storage (local & S3)

Experiments live under `.vmn/{app}/experiments/` by default — local, git-ignored,
never pushed. To share across a team, point any subcommand at an S3-compatible
backend:

```sh
vmn exp run my_app --backend s3 --bucket my-experiments \
    --endpoint-url http://minio:9000 --prefix team/ml -- ./perf_test.sh
```

| Flag | Default | Description |
|---|---|---|
| `--backend` | `local` | `local` or `s3` |
| `--bucket` | — | S3 bucket name |
| `--endpoint-url` | — | Custom endpoint (MinIO, LocalStack, …) |
| `--prefix` | `vmn-experiments` | Key prefix inside the bucket |

These can also be set once under `experiment.storage` in `.vmn/{app}/conf.yml`
so you don't repeat them on every command; CLI flags override the config.

### How records are stored

- **One directory (or key prefix) per run**: `metadata.yml`, the patches,
  `run_state.yml`, `artifacts/` and one append-only `log.<writer>.jsonl` per
  writer. `metadata.yml` is written last, so a half-created run is never listed.
  Every storage directory carries its own `.gitignore` (`*`), so experiments of
  nested apps (`root_app/service`) never show up in `git status` either.
- **Atomic allocation**: a new run claims its verstr atomically (a plain
  `mkdir` locally, a conditional `PUT` with `If-None-Match: *` on S3). Two
  hosts running the same commit against a shared bucket or directory get
  `…` and `….r2`, never one run with both hosts' data merged in.
- **S3 keys**: `<prefix>/<app>/<verstr>/<file>`, where `<app>` is the tag form
  (`root_app/service` → `root_app-service`). Records written by older versions
  under the `root_app_service` form are still read.
- **Incremental log sync**: a host keeps its log locally and ships only what it
  appended since the last sync, as segments `log.<writer>@<n>.jsonl` next to
  the first upload `log.<writer>.jsonl`. Readers merge them per writer.
- **Local-first caching**: immutable files fetched from S3 (metadata, patches)
  are cached locally; `run_state.yml` and logs never are, so another host's run
  shows its live status.
- **Deduplicated patches**: runs of the same code (`….r2`, `….r3`, …) hard-link
  byte-identical patch files instead of storing a copy each.
- **Artifacts** are uploaded to S3 streamed (multipart for large files) and are
  listed and downloadable from S3-backed workspaces.

---

## Web UI

`vmn ui` (from `pip install "vmn[ui]"`) serves a dashboard over the same files:
a sortable experiment leaderboard, per-run detail with **live training/perf
curves** (from `step=` series), side-by-side compare with a real code diff, and
an artifact browser. Each run gets a color-coded
[status](#run-status-did-my-job-die) pill, inner runs nest under their outer run,
and the page auto-refreshes while anything is unfinished. See
[docs/ui.md](ui.md) for the full tour and the API fields.

To get live curves, have your command log `step=`-tagged lines to
`$VMN_METRICS_FILE` — `exp run` tails the file during the run, so the curve
updates in the browser *while the command is still executing*.
