# Experiments

`vmn-exp` is local-first experiment tracking for any
versioned app. An "experiment" is a **snapshot of your working tree plus a log of
metrics and notes** — nothing more. There is no required training script, no
server, and no database. Experiments are plain files under
`.vmn/{app}/experiments/` (git-ignored, never committed or pushed), each anchored
to an exact version and commit so reproducing a result is one `vmn-exp restore`
away.

New here? [client-guide.md](client-guide.md) walks through a project end to end
(install, store, submit, log, watch, compare, reproduce, resume/rewind/fork,
models, prune). This page is the reference.

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
- [Storage (local, S3, GCS, Azure, plugins)](#storage-local-s3-gcs-azure-plugins)
- [Offline recording and push](#offline-recording-and-push)
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
vmn-exp create my_app --note "batch=64, cache on" --metrics latency_ms=12.3 throughput=8100
```

`exp create` snapshots the tree and prints the new verstr. Add more numbers to it
in as many passes as you like:

```sh
vmn-exp add my_app --latest --metrics p99_ms=41 --note "warm run"
```

Change the config and capture again. Repeated identical states get `.rN`
suffixes, so nothing is clobbered:

```sh
# tweak config.yml ...
vmn-exp create my_app --note "batch=128" --metrics latency_ms=15.1 throughput=9400
```

### Compare the sweep

Because each snapshot captures the config diff, you can line the variants up:

```sh
vmn-exp list my_app                  # table of runs + their latest metrics
vmn-exp compare my_app --last 3      # metrics side-by-side across the last 3
vmn-exp diff my_app -v @1 -v @2      # real config/code diff + metric delta
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
vmn-exp create my_app -f variant.yml --metrics latency_ms=15.1 throughput=9400
```

`--metrics` records outputs; `-f variant.yml` records inputs (`params`,
`hypothesis`, `tags`). They are stored separately and never overwrite each other,
and `exp diff` shows a `params:` delta line so you can see exactly which knob
moved between two runs.

---

## With a command: `exp run` and the metrics file

`exp run` snapshots the tree, runs **any** command (a shell script, `hyperfine`,
`wrk`, `pytest-benchmark`, `python train.py` — anything), and records the exit
code and duration. The command's output streams live to your terminal
(stdout to stdout, stderr to stderr) and is also kept as the run's
[`output.log`](#console-output-outputlog) artifact.

```sh
vmn-exp run my_app --note "batch=64" -- ./perf_test.sh
```

Everything after the first `--` is the command. `vmn-exp run` returns the
command's own exit code, so CI can tell a failed run from a passing one — or
`128 + N` when signal N ended it, the way a shell reports it.

The command runs in the directory you invoked `vmn-exp` from (or
`$VMN_WORKING_DIR` when set), not the repo root, so
`cd src && vmn-exp run my_app -- python train.py` finds `src/train.py`.

### Console output: `output.log`

`vmn-exp run` tees the command's stdout and stderr: every byte still reaches
your terminal as it is written, and a combined copy is stored as the run's
`output.log` artifact (next to any other artifact, locally or on S3), with an
`artifact` log entry. `vmn-exp show` prints an `Output:` line for it and the
web UI's run page shows it in an **output** card.

- **Size cap**: `--output-cap-mb` (default 10, or `$VMN_EXP_OUTPUT_CAP_MB`).
  Past the cap the first and last halves are kept around a
  `[vmn: N bytes of output omitted]` marker — the start has the config the job
  printed, the end has the traceback it died with. The terminal is never capped.
- **Uploaded while it runs**: every `--sync-interval` seconds (only when it
  changed; an upload of N bytes also holds the next one off for N / 64 KB
  seconds, so a chatty command spends at most ~64 KB/s re-uploading it) and
  once more, unthrottled, at the end — whatever ended it, a forwarded SIGTERM
  included — so a preempted or hung job still has its latest output stored.
  Only a SIGKILL of `vmn-exp run` itself loses what came after the last upload.
- **Bytes, not text**: output is stored verbatim; non-UTF-8 bytes and control
  codes never break capture. A failing capture never stops supervision.
- **Pipes, not a TTY**: the command writes to pipes, so `isatty()` is false —
  tools may drop colours and progress bars switch to their non-interactive
  mode. `PYTHONUNBUFFERED=1` is set (unless you set it) so a Python command
  still streams line by line. A pty was not used: it merges the two streams,
  rewrites line endings, is POSIX-only and paints redraws into the log.
  `--no-capture-output` gives the command your terminal back and stores
  nothing.

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

- Numeric values are parsed as floats; anything else is dropped (with a
  warning) — metrics are numeric-only. Log non-numeric data (e.g.
  `model=resnet`) as a [param](#structured-notes--params) instead, which keeps
  strings and bools verbatim.
- An optional leading `step=N` builds a **per-step series** (a curve). Without
  it, the values are recorded as scalars — the metrics file is never
  auto-stepped (unlike the SDK's `log_metrics`, see
  [sdk.md](sdk.md#steps)).
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
from vmn_exp.sdk import start_run

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
`autolog()` call records scikit-learn, xgboost, Keras and Lightning
hyperparameters and scores (and, with `log_models=True`, the fitted models) with
no logging in your training code — and the [query
language](sdk.md#the-query-language) for filtering runs on metrics and params.
`exp run` records the `sys_*` metrics [listed in the SDK
guide](sdk.md#starting-a-run) for the child's process tree on every heartbeat,
by default. `--no-system-metrics`, `VMN_SYSTEM_METRICS=0` or conf
`experiment.system_metrics: false` turn it off (in that precedence).

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
runner: exp run         # "exp run", or "sdk" for a start_run() run
cwd: src                # the child's cwd relative to the repo root ("." at the root)
pid: 12345
host: somebox
started_at: 2026-09-21T12:00:00Z
heartbeat: 2026-09-21T12:03:00Z   # refreshed while the child is alive
heartbeat_seq: 6        # +1 on every beat
heartbeat_interval_sec: 30
exit_code: null         # an int once finished
finished_at: null
duration_sec: null
```

The beat interval defaults to 30 seconds and is tunable:

```sh
vmn-exp run my_app --heartbeat-interval 10 -- python train.py
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
| `running` | the heartbeat is fresh (by the writer's timestamp or the store's write time) |
| `stuck` | claims to be running, but the heartbeat went stale on both clocks and there is no exit code |
| `succeeded` | finished, exit code 0 |
| `failed` | finished, non-zero exit code |

`stuck` is the interesting one: the runner died, was OOM-killed, or lost its
node, and left nothing behind to say so. Several missed beats are tolerated
before vmn calls a run stuck — the staleness window is
`max(3 × heartbeat_interval_sec, 60s)`. The 60s floor is read by the *reader*
(`vmn-exp list`, `vmn-exp ui`) from `$VMN_EXP_MIN_STALE_SEC`; lower it for
demos and load tests that want hung runs to show up as `stuck` within seconds.

The writer's `heartbeat` timestamp comes from the writer's clock, which may be
off from the reader's. So every reader — `vmn-exp list`/`show`, `prune`'s live
guard, the ui and the SDK reader — also weighs the *store's* write time of
`run_state.yml` (the file mtime locally, `LastModified` on S3): a run is `stuck`
only when **both** the heartbeat timestamp **and** that write time are older than
the staleness window. A fresh store write proves the run alive even when its
writer's clock is behind; a heartbeat dated in the future (a writer clock ahead)
is ignored, so such a run still turns `stuck` once the store sees no writes.
When the store time is unknown (a backend listing that carries no mtime), the
timestamp rule above applies alone. In code: `derive_status(state,
observed_at=...)` in `vmn_exp.core.status`, with `observed_at`
from `run_state_observed_at(storage, app, verstr)` or an index snapshot's
`run_state_observed_at`; `stale_sec` is the age of the fresher of the two. `heartbeat_seq` increases by one on
every beat, for readers that poll and want a clock-free "it moved" signal.

### Preemption and signals

A scheduler stopping the job (Slurm `scancel`, Kubernetes eviction, a spot
reclaim) sends `SIGTERM` to `vmn-exp run`. vmn forwards it to the command, gives
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

Only a `SIGKILL` of `vmn-exp run` itself leaves a run claiming `running` — the stale
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
vmn-exp list my_app
vmn-exp show my_app --latest
```

### Alerts

A run can notify you — a webhook, Slack, or any shell command — when it
fails, goes stuck, or calls `run.alert()` from the SDK (see
[docs/sdk.md](sdk.md#alerts)). Configure sinks and opt into triggers in the
app's `conf.yml`:

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

A pod without a checkout uses env vars instead: `VMN_EXP_ALERT_WEBHOOK_URL`,
`VMN_EXP_ALERT_SLACK_URL` and `VMN_EXP_ALERT_COMMAND` each add a sink (next to
any from conf.yml), and `VMN_EXP_ALERT_ON=failed,stuck` replaces the trigger list.

| Trigger | Fired by |
|---------|----------|
| `alert` | `run.alert(title, text, level)` in the SDK |
| `failed` | the process that saw the run end non-zero: `vmn-exp run`'s supervisor (child exit, signal) or the SDK's finish (exception, `finish(exit_code=N)`, SIGTERM) |
| `stuck` | `vmn-exp watch <app>` — a dead process cannot report itself |

`stuck` needs an outside observer. Run the watcher from cron, or leave it
looping:

```sh
vmn-exp watch my_app                 # one pass: alert new failed/stuck runs, exit
vmn-exp watch my_app --interval 60   # keep checking every minute
vmn-exp watch my_app --within 6h     # ignore transitions older than 6h (default 1d)
```

It prints `<verstr> <status>` per alert it delivered, never takes the repo
lock, and exits 1 when no sink is configured for `failed` or `stuck`. Each run alerts once per transition: a delivered alert is recorded in the
run's `alerts_sent.yml` (through the storage, so local and S3 alike), keyed by
the run's `finished_at` (failed) or last heartbeat (stuck) — a run that
recovers and stalls again alerts again, and a `failed` alert the supervisor
already sent is not repeated by the watcher. An alert no sink accepted is not
recorded, so the next pass retries it.

Payloads: the webhook POSTs the alert as JSON — `trigger`, `title`, `text`,
`level` (`info`/`warn`/`error`), `app_name`, `run_id`, `run_name`, `status`,
`timestamp`, `host`, `pid`, `exit_code`, `signal`, `heartbeat`, `finished_at`.
Slack gets a message with a colored attachment. The command runs through the
shell with `VMN_ALERT_TRIGGER`, `VMN_ALERT_TITLE`, `VMN_ALERT_TEXT`,
`VMN_ALERT_LEVEL`, `VMN_ALERT_APP`, `VMN_ALERT_RUN_ID`, `VMN_ALERT_STATUS` and
`VMN_ALERT_JSON` (the whole payload) in its environment; a non-zero exit counts
as a failed delivery. Delivery is best-effort: an unreachable endpoint is
logged, never raised into the run, and never changes its exit code.

---

## Outer & inner jobs (sweeps)

For a managed search — grid/random/bayes over a spec, many agents, early
stopping — use [`vmn-exp sweep`](sweeps.md). This section is the underlying
nesting mechanism.

`exp run` exports `VMN_EXPERIMENT_ID` to its child. Any experiment created
**while that variable is set** records it as its `parent`. So a sweep script
that itself calls `vmn-exp run` per trial automatically produces one **outer**
job containing **inner** jobs — no wiring required.

```sh
#!/usr/bin/env bash
# sweep.sh — each trial becomes an inner job of the run that launched this script
for lr in 0.001 0.01 0.1; do
    vmn-exp run my_app --note "lr=$lr" -- python train.py --lr "$lr"
done
```

```sh
vmn-exp run my_app --note "lr sweep" -- ./sweep.sh
```

You can also parent explicitly, which is handy when the trials are launched from
somewhere that does not inherit the environment:

```sh
vmn-exp run my_app --parent @3 -- python train.py --lr 0.01
vmn-exp create my_app --parent latest --metrics acc=0.91
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

### Forks are not children

`vmn-exp create/run --fork-from <ref> [--fork-step N]` (or the SDK's
`start_run(fork_from=..., fork_step=N)`) starts a new run seeded with another
run's metrics and params up to step N — all of them without `--fork-step`;
`<ref>?_step=N` also works. The fork records `forked_from: {verstr, step}` but
no `parent`: it is `single` unless nested some other way, and it never counts
in its source's `tree_status`. Rows carry `forked_from`/`forked_from_step`, so
`vmn-exp list my_app --query 'forked_from = "<verstr>"'` lists a run's forks.
Rewinding a run hides its own history past a step instead — see
[`rewind`](#rewind).

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
| `@N` | the N-th row shown by `vmn-exp list` (1-indexed, oldest-first) |
| a unique prefix | e.g. `-v 1.6.0-dev.a1b` if it uniquely identifies one run |
| full verstr | exact, e.g. `-v 1.6.0-dev.a1b2c3d.e4f5g6h` |

```sh
vmn-exp show my_app                 # latest
vmn-exp show my_app -v @2           # the [2] row from list
vmn-exp diff my_app -v @1 -v @3     # two specific runs
```

---

## Subcommand reference

### `create`

Capture the current state as an experiment without running anything. Works on a
clean or dirty tree (a clean tree zeroes the diff hash). Re-running over an
identical state starts a new `.rN` run instead of overwriting.

```sh
vmn-exp create my_app --note "dropout 0.3" --metrics loss=0.45 acc=0.85
vmn-exp create my_app -f params.yml --attach initial_weights.pt
vmn-exp create my_app --parent @2 --metrics acc=0.91
vmn-exp create my_app --name baseline-v1
vmn-exp create my_app --input s3://bucket/train.csv --input s3://bucket/eval.csv
vmn-exp create my_app --input "train=s3://bucket/train.csv#sha256:abc123"
```

An experiment created with no run has status `created`. `--parent <ref>` attaches
it as an [inner job](#outer--inner-jobs-sweeps) of another experiment.
`--name <text>` (also on `run`) gives the run a human-readable name, stored as
`name` in `metadata.yml`: `vmn-exp list` shows it quoted after the verstr, rows
carry it as `name`, and queries match it (`name ~ "baseline"`).

### `run`

Create an experiment, run a command, and record its outcome (exit code,
duration) plus any metrics it emits to `$VMN_METRICS_FILE`. Publishes a
[`run_state.yml`](#run-status-did-my-job-die) with a heartbeat while the command
is alive.

Only creating the experiment takes the per-repo vmn lock; it is released before
the command starts. So a run that trains for hours leaves the repo usable — other
`vmn` commands, including ones the command itself runs, are unaffected, and
nesting `vmn-exp run` inside `vmn-exp run` works.

```sh
vmn-exp run my_app --note "lr 0.01" -- python train.py --lr 0.01
vmn-exp run my_app -- ./perf_test.sh
vmn-exp run my_app --heartbeat-interval 10 -- python train.py
vmn-exp run my_app --parent latest -- python train.py --lr 0.1
```

| Flag | Default | Description |
|---|---|---|
| `--heartbeat-interval <sec>` | `30` | How often the run refreshes its heartbeat |
| `--kill-grace-sec <sec>` | `30` (`$VMN_EXP_KILL_GRACE_SEC`) | How long a [signalled](#preemption-and-signals) command may take to exit before it is killed |
| `--sync-interval <sec>` | `30` | How often the log (and `output.log`) syncs to remote storage, off the supervise loop (`0` disables periodic sync) |
| `--output-cap-mb <mb>` | `10` (`$VMN_EXP_OUTPUT_CAP_MB`) | Size cap of the [`output.log`](#console-output-outputlog) artifact; past it the first and last halves are kept |
| `--no-capture-output` | *(capture enabled)* | Don't keep the command's output as `output.log`; the command inherits the terminal |
| `--parent <ref>` | *(inherited from `VMN_EXPERIMENT_ID`)* | Attach this run as an inner job of another experiment |
| `--fork-from <ref>` / `--fork-step <N>` | *(none)* | Start this run with `<ref>`'s metrics and params up to step N (all of them without `--fork-step`). Also accepted by `create`. See [Forks are not children](#forks-are-not-children) |
| `--no-env` | *(capture enabled)* | Skip environment capture for this run |
| `--input [name=]uri[#digest]` | *(repeatable)* | Record a dataset or artifact input. Optional `name=` prefix (identifier before the first `=` and before `://`); optional `#digest` suffix (last `#` splits it). Also accepted by `create` and `add`. |

With `VMN_MODE=disabled` in the environment, `run` records nothing: it replaces
itself with the command (no lock, auto-init, snapshot or `run_state.yml`; works
outside a git checkout), sets `VMN_METRICS_FILE` to `/dev/null`, and exits with
the command's own exit code. See [Disabled mode](sdk.md#disabled-mode).

### Input tracking

`--input [name=]uri[#digest]` records a dataset, model checkpoint, or any other artifact the run consumed. It is repeatable; each call appends an independent log entry:

```sh
vmn-exp create my_app --input s3://bucket/train.csv
vmn-exp run my_app --input "train=s3://bucket/train.csv#sha256:abc" -- python train.py
vmn-exp add my_app -v @3 --input s3://bucket/labels.json
```

* **`name`**: a label for the input, so queries can use `inputs.train.uri`. Defaults to the URI basename without extension (`train.csv` → `train`).
* **`digest`**: optional checksum for reproducibility, e.g. `sha256:abc123`.
* **URIs with `=` inside** (like `s3://bucket/path?key=value`) are not mistaken for `name=uri` — only a token before the first `=` AND before `://` counts as a name.

In the Python SDK, use `run.log_input(uri, name=None, digest=None, kind=None)`:

```python
from vmn_exp.sdk import start_run

with start_run("my_app") as run:
    run.log_input("s3://bucket/train.csv", name="train", digest="sha256:abc")
```

Inputs are visible in `vmn-exp show` and queryable as three-part paths:
`inputs.<name>.uri`, `inputs.<name>.digest`, `inputs.<name>.kind`.

### Lineage

A run's artifacts — and the images and tables the SDK's `run.log_image` /
`run.log_table` store (`media/<name>/<step>.png`, `tables/<name>/<step>.json`)
— are its **outputs**: `list --json`/`show --json` rows and the SDK's
`get_run`/`list_runs` carry `outputs.<path>.path|digest|size` (`digest` is
`sha256:<hex>` of the stored bytes), queryable like inputs — quote a path with
a dot or slash: `outputs."model.pkl".digest = "sha256:..."`,
`list --query 'outputs."media/samples/0.png".size > 0'`. The experiment index
keeps outputs beside its rows, not on them, so the `vmn-exp ui` list and
leaderboard pages never ship them (per-step images would bloat every row);
`?q=` queries, the run detail (`outputs`) and lineage still read them. A
logged image/table is recorded only once its file is stored (it uploads in
the background); one that fails to store is never recorded — see
[sdk.md](sdk.md#tables-images-and-histograms).
Runs link when one's input is another's output:

* an input URI `vmn://<app>/<verstr>/<artifact path>` (`<app>` in tag form,
  `/` → `-`) names the producing run directly — `run.use_artifact(ref, path)`
  in the SDK records one, or pass it to `--input`;
* any other input links to the runs of the same app that produced an artifact
  with the same digest.

```sh
vmn-exp add my_app -v @1 --attach model.pkl
vmn-exp create my_app --input "model=vmn://my_app/<verstr of @1>/model.pkl"
vmn-exp lineage my_app -v @2 --depth 2
vmn-exp lineage my_app -v @1 --json
```

`vmn-exp lineage <app> -v <ref> [--depth N] [--json]` prints the upstream runs
(what this run consumed), the downstream runs of the same app (what consumed
its outputs), each with the input/artifact pairs that link them — a pair whose
artifact is a registered version's gets that version too
(`clf@2 <- model.pkl (uri)  model clf v2`) — the reference datasets it used
(`Datasets:`, its `vmn-registry://` inputs), and the model versions registered
from the run. `--depth` (default 1) follows links further;
`--json` prints the same object as `get_lineage` in the SDK
([Lineage](sdk.md#lineage)). It is read-only, never takes the repo lock, and is
answered from the experiment index.

A used registry version is an ordinary input named `<name>@<N>` (see
[models.md](models.md#using-versions)), so the query language finds the runs
that used one:

```sh
vmn-exp list my_app --query 'inputs."resnet50@3".kind = "model"'
vmn-exp list my_app --query 'inputs."imagenet@1".uri ~ "vmn-registry://"'
```

For every app at once — including consumers in other apps, which downstream
links never reach — ask the version itself: the model page's lineage card in
`vmn-exp ui`, or `version_lineage` ([sdk.md](sdk.md#lineage)).

### Environment capture

Both `create` and `run` automatically record a snapshot of the runtime environment into the experiment: Python version, platform, and installed packages (the full `pip freeze` output). The summary (≤ 2 KB) is embedded in `metadata.yml` under `"env"`, and the full package list is written to `env.yml` next to it. These writes are best-effort — a failure never prevents the run from being created.

When the command passed to `vmn-exp run` is a Python interpreter (`python`, `python3`, `python3.x`) or a `.py` script, vmn probes that interpreter's own package list instead of the current one (5-second timeout; falls back to the current env on failure).

**Opt-out:**

| Method | Example |
|---|---|
| CLI flag | `vmn-exp create my_app --no-env` |
| Environment variable | `VMN_CAPTURE_ENV=0 vmn-exp run my_app -- train.py` |
| Per-app config | `experiment.capture_env: false` in `.vmn/my_app/conf.yml` |

The precedence is CLI flag > `VMN_CAPTURE_ENV` > conf.yml (default: capture enabled).

### `add`

Append metrics, a note, an artifact, or a structured entry to an experiment
(defaults to the latest). The log is append-only — nothing is overwritten.

```sh
vmn-exp add my_app --metrics val_loss=0.29 val_acc=0.93
vmn-exp add my_app -v @2 --attach checkpoint.pt --note "after warmup"
vmn-exp add my_app -f extra_notes.yml
vmn-exp add my_app --input train=s3://bucket/train.csv#sha256:abc123
```

### `watch`

`vmn-exp watch <app> [--interval SEC] [--within 1d]` delivers `failed`/`stuck`
alerts for runs that have not alerted them yet — see [Alerts](#alerts).

### `list`

List experiments with a [status](#run-status-did-my-job-die) per row, optionally
sorted by a metric. Inner runs are indented under their outer run.

```sh
vmn-exp list my_app                        # all
vmn-exp list my_app --sort loss --top 5    # best 5 by loss (goal-aware)
vmn-exp list my_app --last 10              # most recent 10
vmn-exp list my_app --query 'metrics.loss < 0.5 and status = "succeeded"'
vmn-exp list my_app --json                 # machine-readable
vmn-exp list my_app --archived             # include archived runs
```

[Archived](#archive--unarchive) runs are left out unless `--archived` is given;
then they are marked `[archived]`.

The `[N]` in front of each row is the run's storage index — the same number
`-v @N` resolves — so it never changes with `--sort`, `--top`, `--last` or `--query`:
`vmn-exp list my_app --sort loss` showing `[7]` first means `vmn-exp show my_app
-v @7` opens that run.

`list`, `show`, `compare`, `diff` and `export` are read-only and take no repo lock, so they never wait
for — or hold up — a `create`/`run` in the same checkout.

`--query '<expr>'` keeps the runs matching [the query
language](sdk.md#the-query-language) — the same one the SDK reader and the
REST API use. It sees every row field, including `status`, `kind`, `depth` and
`tree_status`, and applies before `--last`, `--sort` and `--top`. A bad query
exits 1 with the offending offset. Provenance fields are also queryable:
`inputs.<name>.uri`, `inputs.<name>.digest`, `inputs.<name>.kind` (3-part paths
for each logged input), `outputs.<path>.digest|size|path` (each artifact, image or table the run
logged; quote a dotted path: `outputs."model.pkl".digest`), `env.<key>` and `env.packages.<pkg>` (environment
summary), `imported_from` (set on runs imported from external tools) and
`forked_from`/`forked_from_step` (a fork's source verstr and step) and
`rerun_of` (the run a [`rerun`](#rerun) reran).

`--json` prints the rows shown (after `--query`/`--last`/`--sort`/`--top`) as a
JSON array instead of the table — one object per run with the keys of an SDK
[`list_runs`](sdk.md#reading-runs-back) row: `idx`, `verstr`, `code_verstr`,
`timestamp`, `note`, `create_note`, `branch`, `base_version`,
`params`, `metrics`, `parent`, `last_metric_at`, `name`, `tags`, `archived`,
the status fields (`status`,
`exit_code`, `started_at`, `finished_at`, `heartbeat`, `duration_sec`, `pid`,
`host`, ...) and the tree fields (`children`, `kind`, `depth`, `tree_status`).
Keys are sorted and non-finite metrics are `null`, so the output is strict JSON.
An app with no runs prints `[]`.

`list`, `show` and `compare` read through the experiment index
(`.index.sqlite` beside the records), so a workspace with thousands of runs
costs one listing plus whatever changed — never a re-read of every record. So
does resolving `@N`, `latest` and prefixes.

### `importance`

Which params drive a metric — the CLI face of the dashboard's Importance panel.

```sh
vmn-exp importance my_app --metric loss
vmn-exp importance my_app --metric loss --query 'status = "succeeded"' --json
```

```
param    importance                        correlation  kind         n
lr            0.912  ##################         +0.954  numeric      240
opt           0.061  #                               -  categorical  240
dropout       0.027  #                          -0.081  numeric      236
```

For the runs `list --query` would show (archived ones only with `--archived`)
that carry the metric, every param with at least two distinct values gets:

- `importance` — its share of the impurity decrease of a small random forest
  fitted to predict the metric from the params (50 trees, depth 6, fixed seed,
  so the same runs always give the same answer). The column sums to 1.
- `correlation` — Pearson correlation with the metric (`spearman`, the rank
  correlation, is in `--json`). Categorical params have no order, so theirs is
  `-`/`null`; bools count as 0/1.
- `kind` (`numeric`, `bool`, `categorical`) and `n`, the runs carrying both the
  param and the metric. A run missing a numeric param counts as its median;
  a missing categorical value is a category of its own.

Past 5000 runs a deterministic sample of 5000 is scored. An unknown metric or a
bad `--query` exits 1. Read-only: no repo lock. From Python:
[`reader.param_importance`](sdk.md#reading-runs-back).

### `show`

Full details for one experiment: metadata, a `Status:` line (exit code,
duration, pid/host, and the heartbeat age when `stuck`), `Parent:`/`Children:`
lines, `Rerun of: <verstr>` for a [rerun](#rerun), `Forked from: <verstr> @ step N` for a fork and a `Rewound to step N`
line per rewind, metrics (each at its [summary value](#best-value-summaries-summary),
with last/min/max where they differ), and the log timeline — the newest 50 entries, with a
line saying how many earlier ones were hidden. `--full-log` prints all of them.

```sh
vmn-exp show my_app          # latest
vmn-exp show my_app -v @1
vmn-exp show my_app -v @1 --full-log
vmn-exp show my_app -v @1 --json
```

`--json` prints one object: the `list --json` row keys plus `base_commit`,
`has_dep_patches`, `patches` (`{working_tree|local_commits: line count}`),
`log` (the newest 50 entries, all of them with `--full-log`) and `log_total`.

### `compare`

Side-by-side metric table across N experiments (no code diff — use `diff` for
that). Needs at least two. It reads only each run's metadata and log, never its
patches or untracked-file tarball, so comparing many runs stays cheap.

```sh
vmn-exp compare my_app --last 3
vmn-exp compare my_app -v @1 -v @4
```

### `diff`

Metric/param delta **plus a real source diff** between two experiments (defaults
to the latest two). Uses your git `diff.tool` if configured, or `--tool`.

```sh
vmn-exp diff my_app                 # latest two
vmn-exp diff my_app -v @1 -v @3
vmn-exp diff my_app --tool delta
```

### `restore`

Check out the exact code state of an experiment. If the working tree is
dirty, that work is **auto-saved first** as a [snapshot](snapshots.md) noted
`auto-saved before restore` (and the `vmn goto -v <saved> my_app` that brings
it back is printed) — you never lose uncommitted changes. This is the same
restore `vmn snapshot restore` runs: the reset deletes untracked files, so when
some are over the snapshot size caps (`VMN_SNAPSHOT_MAX_FILE_MB` /
`VMN_SNAPSHOT_MAX_TOTAL_MB`) and could not be saved, the restore refuses and
names them; `--force` restores anyway and loses them.
`vmn goto -v <dev-version> my_app` restores a run's code the same way,
`--force` included (it takes a full verstr, not a prefix or `@N`; see
[Restore vs goto](#restore-vs-goto)).

Both look the run up the same way: the local experiments dir, then the app's
remote experiment store (`--store`, else `VMN_EXPERIMENT_STORE`/`VMN_EXPERIMENT_BUCKET`,
else conf `experiment.storage`) only on a local miss, then the snapshots store —
so a run another host recorded straight to S3 restores from any checkout. A run
with no code snapshot (e.g. an MLflow import) is refused with an error, and a
run that is nowhere is reported with the list of places searched.

```sh
vmn-exp restore my_app --latest
vmn-exp restore my_app -v @2
vmn-exp restore my_app -v @2 --force   # even if big untracked files would be lost
```

#### Restore vs goto

Both put this checkout at a run's exact code (base commit, working-tree diff,
local commits, untracked files), auto-save a dirty tree first, and use the same
lookup. They differ in what they accept:

| | `vmn-exp restore <app>` | `vmn goto -v <verstr> <app>` |
|---|---|---|
| Ref | any [addressing form](#addressing-experiments): a full verstr, a unique prefix, `@N`, `latest`/`--latest`; defaults to the latest run | a full dev verstr only (e.g. `1.6.0-dev.a1b2c3d.e4f5g6h`) |
| Remote store | `--store`/`--bucket`/`--prefix`/`--endpoint-url`, else `VMN_EXPERIMENT_STORE`/`VMN_EXPERIMENT_BUCKET`, else conf | `VMN_EXPERIMENT_STORE`/`VMN_EXPERIMENT_BUCKET`, else conf (no store flags) |
| Needs | `vmn-exp` | `vmn` with `vmn-exp` installed (vmn-exp registers the dev-version loader `goto` uses) |
| Also restores | experiment runs only | a stamped (non-dev) version with all its deps, as usual |

Use `restore` while working with runs, where `@N` and prefixes are convenient.
Use `goto` for the full verstr that a restore prints for your auto-saved work,
or when a script already speaks `vmn goto`.

### `export`

Package an experiment (materialized code, metadata, metrics, artifacts) into a
directory or a `.tar.gz`.

```sh
vmn-exp export my_app                        # latest -> <verstr>.tar.gz
vmn-exp export my_app --latest -o best.tar.gz
vmn-exp export my_app --latest -o /mnt/code  # a plain directory
```

The exported tree carries a `vmn_metadata.yml`, so a container built from it
records runs without git: `vmn-exp create my_app --from-snapshot /mnt/code
--experiment-dir /mnt/runs` (or `VMN_SNAPSHOT_METADATA` for [`start_run()`](sdk.md)). See the
[tracking guide](experiment-tracking-guide.md) for the cluster flow.

### `prune`

Delete old experiments by count, age, query, or exact ref. Each deleted verstr
is printed.

```sh
vmn-exp prune my_app --keep 10              # keep the 10 most recent
vmn-exp prune my_app --older-than 30d       # remove anything older than 30 days (Nd/Nw/Nh)
vmn-exp prune my_app --keep 10 --dry-run    # print what would go, delete nothing
vmn-exp prune my_app --keep 0 --local-only  # drop local copies, keep the S3 ones
vmn-exp prune my_app -v @4                  # delete exactly that one run
vmn-exp prune my_app --keep 5 --protect-tag stage  # never prune a run tagged stage=...

# Query-based selection (uses the same query language as vmn-exp list --query):
vmn-exp prune my_app --query 'status = "failed"'          # preview (dry-run by default)
vmn-exp prune my_app --query 'status = "failed"' --yes    # actually delete
vmn-exp prune my_app --query 'tags.env = "test"' --keep 1 --yes  # keep newest match
```

`--query <expr>` selects candidates via the same query language as
`vmn-exp list --query` — it sees full rows including `status`, `metrics`, and
`tags`.  Because a typo in a `<`/`>` comparison could delete far more than
intended, **`--query` is a dry-run preview by default**; pass `--yes`/`-y` to
confirm deletion.  `--dry-run` always wins over `--yes`.  An empty or invalid
query is an error.  `--keep N`/`--older-than` apply *within* the query scope
(further refining the matched set).  `-v` cannot be combined with `--query`.

`-v <ref>` (repeatable — a verstr, a unique prefix, or `@N`) deletes exactly the
named run(s) instead of applying `--keep`/`--older-than`; it cannot be combined
with either.

Guards take runs back out of the selection, whether it came from `--keep`/
`--older-than`, `--query`, or `-v`:

- a run whose status is `running` or `stuck` is never deleted (it is reported
  as skipped — a stuck run may just have a late heartbeat); `--force` deletes
  it anyway.
- a run carrying a tag key named by `--protect-tag` (repeatable) is never
  deleted, so a run tagged e.g. `stage=prod` survives `--keep`/`-v` alike;
  `--force` deletes it anyway.
- a run with a kept descendant is kept, so no surviving inner run is left
  pointing at a parent that no longer exists.

With a remote bucket configured, prune deletes both the local and the remote
(S3) copy — which may hold your teammates' runs too. `--local-only` removes only
the local copies.

| Flag | Description |
|---|---|
| `--query <expr>` | Select candidates by query; dry-run unless `--yes`/`-y` |
| `--yes`/`-y` | Confirm deletion when `--query` is given |
| `-v <ref>` | Delete exactly this run (repeatable); not combined with `--keep`/`--older-than` |
| `--keep N` | Keep the N most recent experiments (applies within `--query` scope too) |
| `--older-than <dur>` | Delete experiments older than `Nd`/`Nw`/`Nh` (applies within `--query` scope too) |
| `--protect-tag <key>` | Never delete a run carrying this tag key (repeatable) |
| `--dry-run` | Print what would be deleted, delete nothing (beats `--yes`) |
| `--force` | Also delete runs that are still `running`, or tag-protected |
| `--local-only` | Keep the remote (S3) copies |

Archived runs are pruned like any other finished run.

### `tag`

Set or remove tags on a run — mutable `key=value` labels, also on a finished
run. The first positional without `=` (or `-v`/`--latest`) is the run; every
`key=value` sets a tag (the value may contain `=`), and `--remove <key>`
(repeatable) drops one.

```sh
vmn-exp tag my_app @3 stage=prod owner=ann
vmn-exp tag my_app @3 --remove owner
vmn-exp tag my_app stage=candidate --latest
```

Each call appends a `tags` entry to the log; readers fold them per key, last
write wins. Rows carry the result as `tags` and the query language reads
`tags.<key>` (`vmn-exp list my_app --query 'tags.stage = "prod"'`). Positionals
go before the flags: argparse binds them before the first option.

### `archive` / `unarchive`

Hide runs from listings without deleting anything:

```sh
vmn-exp archive my_app @1 @2 0.0.3-dev.abc1234.def5678
vmn-exp unarchive my_app @2
```

Archiving writes `archived: true` into the run's `metadata.yml` (atomically on
disk, under the ETag on S3); unarchiving removes it. `vmn-exp list` and the SDK's
`list_runs` hide archived runs by default (`--archived` / `include_archived=True`
shows them), as does the web UI unless asked with `archived=1`; the query language
matches `archived = true`. From Python: `vmn_exp.sdk.manage.archive_run` /
`unarchive_run` (see [sdk.md](sdk.md#changing-stored-runs-archive-unarchive-tags)).

### `rewind`

Hide a run's history past a step, in place, without reopening the run:

```sh
vmn-exp rewind my_app -v @3 --step 250
# rewound 0.0.3-dev.abc1234.def5678 to step 250 (hid 42 entries)
```

`-v` takes any ref (verstr, unique prefix, `@N`, `latest`), or use `--latest`;
`--step` is an integer >= 0. Nothing is deleted: the run's log gets a
`{"type": "rewind", "step": 250}` entry, and every reader (`show`, `list`, the
index, the UI's series, `list_runs`) ignores each entry with a step past 250
written before it. Entries without a step (params, notes, tags) are never
hidden, and `show` prints a `Rewound to step N` line per rewind. A run that
derives as `running` is refused — its writer would keep logging the steps being
hidden. It writes like `tag`/`add`: it takes the repo lock, honours
`--store`/`--bucket`/`--dir`, and works without a checkout too (with
`VMN_SNAPSHOT_METADATA`). The web UI's `exp_rewind` job action (body
`{"verstr", "step"}`) runs this command.

`vmn-exp run` does not reopen runs. To redo a run from a checkpoint, rewind it
here and continue it from the SDK with `start_run(run_id=<ref>)` — or do both in
one call, `start_run(run_id=<ref>, rewind_to_step=N)` (see
[sdk.md](sdk.md#rewinding-a-run)) — or fork it into a new run with
`vmn-exp run my_app --fork-from <ref> --fork-step N -- <cmd>`.

### `rerun`

Run a run's recorded command again, against that run's own code — dirty
edits, local commits, untracked files and deps included — as a new run:

```sh
vmn-exp rerun my_app -v @3                        # the recorded command, recorded cwd
vmn-exp rerun my_app -v @3 -- python train.py --lr 0.01   # another command, same code
vmn-exp rerun my_app -v @3 --dry-run              # print the plan, create nothing
vmn-exp rerun my_app -v @3 --print [--json]       # print what a job would run
```

The run is required (`-v <ref>` or `--latest`). Its code is restored into a
throwaway workspace — a fresh `vmn-rerun-<app>-*` directory in `$TMPDIR`, or
`--worktree-dir DIR` (missing or empty, outside the repo) — as detached
worktrees at the recorded commits (a clone from the recorded remote when a
commit is not local), with the recorded deps at their relative paths and the
captured patches applied. Anything that doesn't restore exactly — a patch that
doesn't apply, a dep that can't be checked out, a missing code object — is an
error, and nothing is created. The live checkout is never touched. The
workspace is removed when the command ends (also on SIGTERM);
`--keep-worktree` keeps it, prints its path and records it as `workdir` in
`run_state.yml`.

The command runs in the recorded `cwd` inside the workspace (`--cwd PATH`,
relative to the restored app root, overrides it; a run recorded before `cwd`
existed runs from the app root). `-- <cmd>` replaces the recorded command.
Absolute paths into the live repo in the command are pointed into the
workspace. Supervision is exactly [`run`](#run)'s: heartbeat, `output.log`,
signal forwarding, the child's exit code as the exit code, the new verstr
printed, and the repo lock released once the record is claimed. The run flags
`--note`, `--name`, `--parent`, `--no-env`, `--input`, `-f`,
`--heartbeat-interval`, `--kill-grace-sec`, `--no-system-metrics`,
`--sync-interval`, `--no-capture-output` and `--output-cap-mb` apply;
`--fork-from` is refused.

The new run records `rerun_of: <verstr>` and copies the original's code
identity instead of snapshotting the workspace, so it shares the original's
code object and is named `<code_verstr>.rN` under the same code — which keeps
that code alive when [`prune`](#prune) deletes the original.
`vmn-exp list my_app --query 'rerun_of = "<verstr>"'` lists a run's reruns.
The original's create params are copied (tags and inputs are not); a sweep
trial's params are re-exported as `VMN_SWEEP_PARAMS`, but the rerun is not a
trial. The child's `VMN_EXPERIMENT_DIR` points at the original store, so runs
the command creates (an SDK `start_run()`, a nested `vmn-exp run`) land there as
inner runs of the rerun.

It warns when the rerun can't match the original: an environment that differs
from the one captured with the run (python, platform, packages), untracked files
that were too large to capture, a source run still `running`, a sweep trial.

Refused, with nothing created: runs without code (imports, a missing code
object), runs that never ran a command (`create`-only — pass one after `--`),
and SDK runs without `--`: an SDK run records its script's arguments, not the
interpreter, so rerun it as `vmn-exp rerun my_app -v X -- python train.py`. Its
metrics then land on the inner run the script opens. `rerun` needs a checkout;
it is refused in `--from-snapshot` / `VMN_SNAPSHOT_METADATA` mode.

Gitignored files (datasets, `.env`, checkpoints) are not part of a run's code
and are not in the workspace — point the command at them with absolute paths.

#### Reruns on a cluster

vmn does not schedule jobs — your Kubernetes job, Condor submit file or Slurm
script does. `--print` tells it what to run, without executing or creating
anything:

```sh
vmn-exp rerun my_app -v @3 --print
# command:       python train.py --lr 0.1
# cwd:           src
# code_verstr:   0.0.3-dev.abc1234.def5678
# code:          0.0.3-dev.abc1234.def5678.<diff hash>
# recipe:        vmn-exp rerun my_app -v 0.0.3-dev.abc1234.def5678
# export_recipe: vmn-exp export my_app -v ... -o ... && cd ... && VMN_SNAPSHOT_METADATA=... vmn-exp run my_app -- python train.py --lr 0.1
```

`--print --json` prints the same as one JSON object (`rerun_of`, `app`,
`command` as a list, `cwd`, `code_verstr`, `code`, `base_commit`, `recipe`,
`export_recipe`) for a submit script to read.

- **Nodes with the repo**: the job runs the recipe,
  `vmn-exp rerun my_app -v <verstr>`, in a checkout that reaches the same
  store (a shared `--store`/`VMN_EXPERIMENT_STORE`, or the same directory).
- **Nodes without git**: export the run's tree once —
  `vmn-exp export my_app -v <verstr> -o dir` — ship `dir` (an image, a shared
  volume), and have the job run the printed command in `dir/<cwd>` with
  `VMN_SNAPSHOT_METADATA=dir/vmn_metadata.yml` (or `vmn-exp run my_app
  --from-snapshot dir -- <command>`), as `export_recipe` spells out. That run
  is a normal git-free run of the exported code, not a linked rerun.

### `push`

Upload local runs (typically recorded under `VMN_EXP_OFFLINE`) to the remote
store under the same names, renaming on a collision. Resumable; `-v`
(repeatable) picks runs, `--dry-run` previews, `--json` prints the outcomes.
See [Offline recording and push](#offline-recording-and-push).

```sh
vmn-exp push my_app
vmn-exp push my_app -v @3 --dry-run
```

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
vmn-exp create my_app -f params.yml --metrics loss=0.38
```

`exp diff` prints a `params:` line showing which inputs changed between two runs,
next to the `metrics:` delta.

---

## Metrics schema (sorting & goals)

Declare each metric's goal and a primary metric in `.vmn/{app}/conf.yml` so
`list --sort` (and the web-UI leaderboard) know which direction is "better" and
what to sort by when you don't pass `--sort`:

```yaml
conf:
  experiment:
    metrics:
      loss:        {goal: min, primary: true}   # lower is better; default sort key
      val_loss:    {goal: min}
      acc:         {goal: max}                   # higher is better
      latency_ms:  {goal: min}
```

- `goal: min` → best-first ascending. `goal: max` → best-first descending.
  A metric with no declared goal in the schema sorts as a plain ascending
  value sort — declare a `goal` to get goal-aware (best-first) ordering.
- A glob key (`"val_*": {goal: min}`) sets the goal of every metric it
  matches; an exact name beats it.
- Runs can declare goals too (`run.define_metric(name, goal=)` or
  `vmn-exp add --define-metric`): for names conf.yml does not declare, the
  latest run's `goal` sets the sort direction of `list --sort`, `list_runs()`
  and the UI leaderboard. conf.yml always wins.
- `hidden: true` keeps a metric (or glob, `"grad_*": {hidden: true}`) out of
  the UI's default leaderboard columns and chart grid; it still sorts,
  queries and summarizes. Runs may declare it with `define_metric(hidden=True)`.
- `primary: true` marks the metric used to sort `list` when `--sort` is omitted.
- `step_metric: epoch` charts the metric (a name or a glob such as `val_*`)
  against `epoch` logged at the same step instead of the step itself — see
  [sdk.md](sdk.md#custom-x-axis-step_metric).
- Schema columns also fix the column order in `list`/`compare`; any extra
  metrics you logged appear after them, alphabetically.

### Best-value summaries (`summary`)

A run that logs a metric many times (a loss per epoch) folds it into one
number per run. Which one is the metric's **summary policy**:

| `summary` | The run's `metrics.<name>` is |
|---|---|
| `last` | the latest value logged |
| `min` | the smallest finite value logged |
| `max` | the largest finite value logged |
| `first` | the earliest value logged (by timestamp, across writers) |
| `mean` | the mean of the finite values logged (`last` when there is none) |

Without an explicit `summary` the policy follows `goal` (`goal: min` → `min`,
`goal: max` → `max`); a metric with neither is `last`. So with
`loss: {goal: min}` an overfitting run — loss 1.0, 0.2, then back up to 0.9 —
ranks on 0.2, its best epoch, not on 0.9:

```yaml
conf:
  experiment:
    metrics:
      loss:     {goal: min}                  # ranks on the minimum
      val_loss: {goal: min, summary: last}   # sorts ascending, ranks on the final value
      lr:       {summary: last}
```

The summary value is what everything ranks and filters on: `list --sort`,
`--query metrics.loss < 0.3`, `prune --query`, `compare`, `diff`, the UI
leaderboard, and `list_runs()` rows. Every metric logged more than once also
carries its full `metric_summary` (`{"last", "min", "max", "first", "mean"}`) in `list --json`,
`show --json`, `list_runs()`/`get_run()` rows and the UI run detail; `show`
prints them where they differ:

```
  Metrics:
    loss: 0.2 (last 0.9, min 0.2, max 1)
```

- **Precedence**: a run's own definition — [`run.define_metric()`](sdk.md#metric-goals-and-summaries),
  recorded in its log — beats conf.yml, which beats the `last` default. In
  each, an exact metric name beats a glob key (`"val_*": {goal: min}`).
  Another run's declaration never changes a run's summary — it only counts
  for sort direction and hidden columns.
- **After the fact**: `vmn-exp add my_app -v <ref> --define-metric val_loss
  --goal min [--summary min|max|last|first|mean] [--step-metric epoch]
  [--hidden]` appends the same `define_metric` entry `run.define_metric()`
  does — handy for a `vmn-exp run` whose child only wrote `key=value` lines.
  It needs at least one of the four options.
- **Live**: conf.yml's policies apply when a run is read, so editing them
  re-ranks existing runs too (the index re-derives rows from its folded state,
  no log is re-read). An S3 workspace in `vmn-exp ui` has no conf.yml, so only
  the runs' own definitions apply there (their goals still set the sort
  direction).
- **NaN/inf** stay in the log and may be a metric's `last` or `first`, but
  never its `min`/`max` or part of its `mean`. A `min`/`max` metric with no finite value at all keeps its last
  (non-finite) value and sorts last.
- Numeric params folded into `metrics` are single values: `min`/`max` of a
  param is the param itself.

---

## Storage (local, S3, GCS, Azure, plugins)

Experiments live under `.vmn/{app}/experiments/` by default — local, git-ignored,
never pushed. To share across a team, point any subcommand at a **store URI**:

```sh
vmn-exp run my_app --store s3://my-experiments/team/ml -- ./perf_test.sh
vmn-exp run my_app --store "s3://my-experiments/team/ml?endpoint_url=http://minio:9000" -- ./t.sh
vmn-exp run my_app --store gs://my-experiments/team/ml -- ./t.sh     # pip install 'vmn-exp-sdk[gcs]'
vmn-exp run my_app --store az://experiments/team/ml -- ./t.sh        # pip install 'vmn-exp-sdk[azure]'
vmn-exp run my_app --store file:///mnt/nfs/experiments -- ./t.sh
```

| URI | Backend | Notes |
|---|---|---|
| `s3://bucket[/prefix][?endpoint_url=...]` | S3 / MinIO / LocalStack | extra `[s3]` (boto3); AWS credentials as usual |
| `gs://bucket[/prefix]` | Google Cloud Storage | extra `[gcs]` (google-cloud-storage); Application Default Credentials |
| `az://container[/prefix][?account_url=...]` | Azure Blob Storage | extra `[azure]`; `AZURE_STORAGE_CONNECTION_STRING`, else `AZURE_STORAGE_ACCOUNT_URL` + `DefaultAzureCredential` |
| `file:///abs/dir` (or a bare path) | a local/NFS directory | used *as* the local root, no cache in front |
| `<scheme>://...` | a plugin | see [Storage backends](#storage-backends-plugins) |

The prefix defaults to `vmn-experiments`.
The store resolves as `--store` > `VMN_EXPERIMENT_STORE` > `experiment.storage.uri`
in `.vmn/{app}/conf.yml`. `--bucket`/`--prefix`/`--endpoint-url` (and
`VMN_EXPERIMENT_BUCKET`/`_PREFIX`/`_ENDPOINT_URL`, conf `bucket`/`prefix`/
`endpoint_url`) remain as shorthand for an `s3://` URI; any store URI wins over
the shorthand. With a remote store, runs record locally and sync to it when
there is a local root (a checkout or `--experiment-dir`/`VMN_EXPERIMENT_DIR`),
or go straight to the store when there is none. A missing SDK fails with the
`pip install 'vmn-exp-sdk[<extra>]'` line to run.

```yaml
# .vmn/my_app/conf.yml
conf:
  experiment:
    storage:
      uri: gs://ml-experiments/team
```

### Storage backends (plugins)

A backend is chosen by the URI scheme. Built-ins are `file`, `s3`, `gs` and
`az`; a package adds (or overrides) a scheme under the `vmn_exp.storage`
entry-point group:

```toml
[project.entry-points."vmn_exp.storage"]
mem = "my_pkg.store:open_store"
```

`open_store(uri, subdir)` receives a `vmn_exp.storage.uri.StoreURI`
(`scheme`, `location` = bucket/container, `path` = prefix, `options` = the query
string) and `subdir` (`"experiments"` or `"snapshots"`), and returns a
`vmn_exp.storage.base.SnapshotStorage`. `vmn_exp.storage.registry.register_store(scheme,
factory)` does the same at runtime. The contract:

- **Records**: a record is `<base>/<app>/<verstr>/` holding `metadata.yml`, the
  patch files, per-writer `log.<writer>[@<seq>].jsonl`, `run_state.yml` and
  `artifacts/`. `metadata.yml` makes it exist: write it last, delete it first.
  Implement the abstract methods (`save`, `load_record`, `list_snapshots`,
  `update_note`, `delete`, `load_file`, `save_file`, `save_artifact_file`,
  `list_artifact_files`) and override the defaulted ones your store can do
  better (`list_verstrs`, `exists`, `update_metadata`, `list_files`,
  `read_file_from`, the log methods, `list_artifacts`, `artifact_uri`).
- **`create_exclusive` must be atomic**: of any number of hosts racing for one
  verstr exactly one gets `True`; everyone else gets `False` and allocates the
  next name. A store `vmn-exp push` can target also takes
  `create_exclusive(..., claim_token=)`: the token is stored with the claim,
  and a claim holding the same token but no `metadata.yml` is the caller's own
  crashed attempt and is resumed (`True`); empty or foreign claims and
  existing records stay taken. The base-class default (check, then save) is *not* safe on a shared
  store — use the store's conditional create (`O_EXCL` mkdir, S3
  `If-None-Match: *`, GCS `if_generation_match=0`, Azure `overwrite=False`).
  `update_metadata` should likewise be a compare-and-swap on the object version.
- **Listing semantics**: `list_verstrs` returns names only (claimed-but-unfinished
  names included — they are taken); `list_snapshots` returns only records whose
  `metadata.yml` exists; `list_files` maps `{verstr: {file: (size, mtime[, etag])}}`
  and is what incremental index refreshes compare, so a rewritten file must
  change its signature.
- **`is_remote()`** returns `True` for a network store: it is then fronted by
  the local root when there is one, and its reads are parallelized. A store
  returning `False` is used as the local root itself (as `file://` is).
- **`cache_identity()`** returns a hashable name for the data (e.g.
  `(scheme, endpoint, bucket, prefix)`) so process-wide caches never mix stores.

An object store with a conditional create and a conditional overwrite gets all
of this for free by subclassing `vmn_exp.storage.s3.S3SnapshotStorage` with an
`vmn_exp.storage.object_client.ObjectClient` adapter for its SDK — that is how
the GCS and Azure backends are built.

### How records are stored

- **One directory (or key prefix) per run**: `metadata.yml`,
  `run_state.yml`, `artifacts/` and one append-only `log.<writer>.jsonl` per
  writer. `metadata.yml` is written last, so a half-created run is never listed.
  Every storage directory carries its own `.gitignore` (`*`), so experiments of
  nested apps (`root_app/service`) never show up in `git status` either.
- **Atomic allocation**: a new run claims its verstr atomically (a plain
  `mkdir` locally, a conditional `PUT` with `If-None-Match: *` on S3, and the
  GCS/Azure equivalents). Two
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
- **Code stored once per code identity**: a run's patches and untracked tarball
  live in one *code object* per code identity, not in the run's own directory.
  Code objects are records of the reserved `vmn-code/<app>` pseudo-app in the
  same store (`.vmn/vmn-code/<app>/experiments/<code_verstr>.<diff hash>/`
  locally, `<prefix>/vmn-code-<app>/…` on S3; a root app's `/` becomes `~`),
  and the run's `metadata.yml` names its object as `code:`. Their
  `metadata.yml` is written after the payload and marks them complete. A new
  run of code whose object is already complete builds no tarball and uploads
  nothing but its own record; an incomplete object is rewritten. `load` (and so
  `restore`, `vmn goto`, `export`, `diff`) reads the patches from the object;
  when it is missing or incomplete, `restore`/`goto`/`export` refuse with
  "code snapshot … is missing from the store" and leave the tree untouched.
  `prune` deletes a code object together with the last run of its code. A
  clean-tree run has no code object.
- **Artifacts** are uploaded to S3 streamed (multipart for large files) and are
  listed and downloadable from S3-backed workspaces. Names may be nested
  relative paths (`artifacts/model/sub/c.txt` is listed as `model/sub/c.txt`);
  absolute paths, `..`, `.`, empty components, backslashes and NUL are refused.
- **Batched appends**: `append_log_entries` writes a batch of entries as one
  write of whole lines (one PUT on S3); the SDK flushes its buffered log that
  way, so readers never see a partial line.
- **Format version**: every new run (and model registry record) stores
  `format_version` in its `metadata.yml`. It versions the whole record —
  metadata, log lines and `run_state.yml` — so log lines carry none of their
  own. A record without it reads as version 1. `list`, `show`, the ui and the
  SDK reader skip a record whose version is newer than the installed vmn-exp
  supports, with a warning to upgrade, rather than mis-read it. `show --json`
  prints the field.

## Offline recording and push

Compute nodes often have no route to the bucket, while the committed conf.yml
names one. `VMN_EXP_OFFLINE=1` (also `true`/`yes`/`on`) makes every storage
factory — `vmn-exp create`/`run`/..., `start_run()`, and `vmn snapshot` — drop
the remote store and record to the local root only (the checkout's
`.vmn/<app>/experiments/`, or `--experiment-dir`/`VMN_EXPERIMENT_DIR`). It
beats `--store`, `VMN_EXPERIMENT_STORE` and conf; without a local root it fails
rather than silently falling back. Code objects stay local too.

An offline run can't see which names other hosts took, so it is named
`<code_verstr>.<writer_id>[.N]` rather than `.rN` — the writer id is
`VMN_WRITER_ID`, else `HOSTNAME`, else the host name (e.g. `1.6.0-dev.a1b2c3d.e4f5g6h.gpu07`, then `….gpu07.2`).

Later, from a host that can reach the store, upload them with `vmn-exp push`:

```sh
VMN_EXP_OFFLINE=1 vmn-exp run my_app -- python train.py      # on the node
vmn-exp push my_app                                          # later: every local run
vmn-exp push my_app -v @3 -v 1.6.0-dev.a1b2c3d.e4f5g6h.gpu07 # just these (repeatable)
vmn-exp push my_app --store s3://ml-exps/team --dry-run      # preview, write nothing remote
```

```text
1.6.0-dev.a1b2c3d.e4f5g6h.gpu07  new
1.6.0-dev.a1b2c3d.e4f5g6h.gpu07.2  up-to-date
1.6.0-dev.a1b2c3d.e4f5g6h  new -> 1.6.0-dev.a1b2c3d.e4f5g6h.r3
pushed 2, up-to-date 1, renamed 1, skipped 0, failed 0
```

- **Target**: `--store` (or `--bucket`/`--prefix`/`--endpoint-url`) >
  `VMN_EXPERIMENT_STORE` > conf `experiment.storage.uri`. `VMN_EXP_OFFLINE`
  never hides it here, so push works from the same shell. It must be a remote
  store (`s3://`, `gs://`, `az://`); a `file://` target is refused (rsync the
  experiments dir instead), and so is having no remote configured.
- **Same name**: each run is pushed under its local verstr, parents before
  children: the code object (only when the remote lacks it), the record, the
  other top-level files, each writer's log from where the remote copy ends,
  and missing or resized artifacts. `archived`/`note` merge three-way against
  what was last pushed; on a conflict the remote wins, with a warning.
- **Resumable**: a failed or interrupted push is simply run again. A ledger per
  remote under `.vmn/<app>/experiments/.push/<remote id>/` records what was
  sent, so an unchanged run costs no remote call (`up-to-date`) and a changed
  one ships only what is new (`update`).
- **Collisions**: when the remote holds a different run under the same name,
  the run is renamed on *both* sides to the next free `<code_verstr>.rN` (its
  local directory, `verstr`, a `renamed_from` field, and its children's
  `parent`) and then pushed. A running or stuck run, a run a local model
  version references, and a sweep's outer run are never renamed: they are
  `skipped`, with the reason.
- **Output**: one line per run — `<verstr>  <status>` with status `new`,
  `update`, `up-to-date`, `skipped` or `failed` (`collision` in a `--dry-run`),
  `-> <new name>` after a rename, and the reason in parentheses — then
  `pushed N, up-to-date M, renamed R, skipped S, failed F`. `--json` prints the
  outcomes as a list of `{verstr, status, detail, warnings, renamed_from}`. The
  exit code is 1 when any run failed.
- Push takes the repo lock (it may rename local runs) and works git-free
  (`VMN_SNAPSHOT_METADATA` + `VMN_EXPERIMENT_DIR`) as well as in a checkout.
  The web UI runs it as the `exp_push` job action ([ui.md](ui.md#actions)).

---

## Web UI

`vmn-exp ui` (from `pip install "vmn-exp[ui]"`) serves a dashboard over the same files:
a sortable experiment leaderboard, per-run detail with **live training/perf
curves** (from `step=` series), side-by-side compare with a real code diff, and
an artifact browser. The leaderboard's **Importance** chart ranks the params
driving a metric (see [`importance`](#importance)). Each run gets a color-coded
[status](#run-status-did-my-job-die) pill, inner runs nest under their outer run,
and the page auto-refreshes while anything is unfinished. See
[docs/ui.md](ui.md) for the full tour and the API fields.

To get live curves, have your command log `step=`-tagged lines to
`$VMN_METRICS_FILE` — `exp run` tails the file during the run, so the curve
updates in the browser *while the command is still executing*.

---

## Importing from MLflow

`vmn-exp import-mlflow` reads runs from an existing MLflow store and writes
them into vmn-exp storage.  The imported runs appear in `vmn-exp list`,
the web UI, and are queryable with `--query 'imported_from != null'`.

```sh
# From a local mlruns/ directory (no mlflow package needed)
vmn-exp import-mlflow --mlruns ./mlruns my_app

# From a tracking server (requires pip install mlflow-skinny)
vmn-exp import-mlflow --tracking-uri http://mlflow.internal:5000 my_app

# Limit to specific experiments (repeatable, by name or numeric ID)
vmn-exp import-mlflow --mlruns ./mlruns --experiment my_exp --experiment 3 my_app

# Preview without writing (dry-run)
vmn-exp import-mlflow --mlruns ./mlruns --dry-run my_app

# Skip copying local artifact files
vmn-exp import-mlflow --mlruns ./mlruns --skip-artifacts my_app

# Include deleted/trashed runs
vmn-exp import-mlflow --mlruns ./mlruns --include-deleted my_app

# Tune parallelism (default: 8 workers)
vmn-exp import-mlflow --mlruns ./mlruns --workers 16 my_app
```

**Re-import is safe**: running the command a second time skips already-imported
runs (`skipped N (already present)`).  Runs are identified by their MLflow
`run_id`, and their vmn verstr is deterministic (`0.0.0-mlflow.<run_id[:12]>`),
so parents are resolved correctly regardless of import order.

**Summary line** printed on completion:
```
imported 42, skipped 0 (already present), resumed 0, failed 0
```
Exit code is 1 if any run failed.

**No git repo needed**: the command does not take the repo lock and does not
auto-init the vmn app.  Use `--experiment-dir` or `VMN_EXPERIMENT_DIR` to
point at an experiment directory outside a repo, or `--store <uri>` /
`VMN_EXPERIMENT_STORE` (or the `--bucket` shorthand) to write directly to a store.

See [docs/migrating-from-mlflow.md](migrating-from-mlflow.md) for a migration
guide including artifact layout, query equivalences, and known differences.
