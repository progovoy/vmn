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
   ... The log is never rewritten.

Experiments are **content-addressed**:

```
1.6.0-dev.a1b2c3d.e4f5g6h
          │       └─ hash of the working-tree diff (0000000 on a clean tree)
          └───────── short base commit
```

Identical code yields an identical verstr, so a new run over an existing
state gets a `.r2`, `.r3`, … suffix instead of overwriting — "same config,
different seed" stays as distinct rows. (Offline runs use a writer-id suffix
instead; see [Offline recording](#offline-recording-and-push).)

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
| `created` | no command was ever started (e.g. `exp create`) |
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

`exp list` shows a status per row; `exp show` prints `Status:`, exit code,
duration, `Runner: pid … on <host>`, and the heartbeat age when `stuck`.

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
| *(omitted)* | the latest run for `add`/`show`/`restore`/`export`/`lineage`; the latest two for `compare`/`diff`; every local run for `push` |
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
`importance`, `lineage`, `import-mlflow`, `migrate`. Separate commands: `vmn-exp sweep`
([sweeps.md](sweeps.md)), `vmn-exp model` ([models.md](models.md)),
`vmn-exp ui` ([ui.md](ui.md)).

Read-only actions — `list`, `show`, `compare`, `diff`, `export`, `watch`,
`importance`, `lineage` (and `import-mlflow`) — take no repo lock. `list`,
`show`, `compare` and ref resolution read through the experiment index
(a per-host SQLite cache under `$VMN_EXP_CACHE_DIR`, else
`$XDG_CACHE_HOME/vmn-exp` / `~/Library/Caches/vmn-exp` / `~/.cache/vmn-exp`,
never inside the store), so
thousands of runs cost one listing plus whatever changed.

Flags shared by most actions:

| Flag | Description |
|---|---|
| `-v, --version <ref>` | the run (repeatable for `compare`/`diff`/`prune`/`push`) |
| `--latest` | the most recent run |
| `--store <uri>` | experiment store URI; see [Storage](#storage-local-s3-gcs-azure-plugins) |
| `--bucket` / `--prefix` / `--endpoint-url` | shorthand for an `s3://` store |
| `--experiment-dir <dir>` | local root instead of the checkout's `.vmn/` (or `$VMN_EXPERIMENT_DIR`) |
| `--writer-id <id>` | this process's writer id; `$VMN_WRITER_ID` > `--writer-id` > conf `experiment.storage.writer_id` > `$HOSTNAME` > the host name |
| `--from-snapshot <path>` | git-free mode against a tree from `vmn-exp export`; see [Git-free mode](#git-free-mode) |
| `--json` | machine-readable output (`list`, `show`, `importance`, `lineage`, `push`, `rerun --print`) |

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
| `--new-app` | confirm a brand-new app name in a repo that has other apps |

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

### `add`

Append to a run (default: latest). Nothing is overwritten.

```sh
vmn-exp add my_app --metrics val_loss=0.29 val_acc=0.93
vmn-exp add my_app -v @2 --attach checkpoint.pt --note "after warmup"
vmn-exp add my_app -f extra_notes.yml            # the whole file as a structured entry
vmn-exp add my_app -v @2 --define-metric val_loss --goal min
```

Flags: `--metrics`, `--note`, `--attach <file>` (an artifact), `-f <yaml>`,
`--input`, and `--define-metric NAME [--goal min|max] [--summary
min|max|last|first|mean] [--step-metric M] [--hidden]` (the CLI's
`run.define_metric`; see [summaries](#best-value-summaries-summary)).

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
(`status`, `kind`, `depth`, `tree_status`, `name`, `archived`, `rerun_of`,
`forked_from`, `imported_from`, `end_reason`, …), `inputs.*`, `outputs.*` and
`env.*`.

`--json` prints the shown rows as a JSON array (keys sorted, non-finite
metrics as `null`, `[]` for no runs), one object per run with the keys of an
SDK [`list_runs`](sdk.md#reading-runs-back) row: `idx`, `verstr`,
`code_verstr`, `timestamp`, `note`, `create_note`, `name`, `tags`,
`archived`, `params`, `metrics`, `metric_summary`, `inputs`, `outputs`,
`parent`, the status fields (`status`, `exit_code`, `started_at`,
`finished_at`, `heartbeat`, `duration_sec`, `pid`, `host`, …) and the tree
fields (`children`, `kind`, `depth`, `tree_status`).

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
line count}`), `log` (newest 50, or all with `--full-log`), `log_total` and
`media_counts`.

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
`vmn_metadata.yml`, `vmn_experiment.yml` (metadata + log), `artifacts/` and `outputs/` —
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
derives `running` is refused. Takes the repo lock, honours the store flags,
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
same names. See [Offline recording and push](#offline-recording-and-push).

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

### `import-mlflow`

Import runs from an MLflow FileStore or tracking server:

```sh
vmn-exp import-mlflow --mlruns ./mlruns my_app                        # no mlflow package needed
vmn-exp import-mlflow --tracking-uri http://mlflow:5000 my_app        # needs mlflow-skinny
vmn-exp import-mlflow --mlruns ./mlruns --experiment my_exp --experiment 3 --dry-run my_app
```

| Flag | Description |
|---|---|
| `--mlruns <dir>` / `--tracking-uri <uri>` | the source (exactly one) |
| `--experiment <name\|id>` | only this MLflow experiment (repeatable) |
| `--skip-artifacts` | don't copy local artifact files |
| `--include-deleted` | include deleted/trashed runs |
| `--dry-run` | preview, write nothing |
| `--workers N` | parallel workers (default 8) |

Re-import is idempotent: runs are keyed by MLflow `run_id` with a
deterministic verstr `0.0.0-mlflow.<run_id[:12]>`, so present runs are
skipped and parents resolve in any order. Prints `imported N, skipped M
(already present), resumed K, failed F`; exits 1 if any failed. Takes no
repo lock and never auto-inits; write outside a repo with `--experiment-dir`/
`VMN_EXPERIMENT_DIR` or straight to a store with `--store`. Imported runs have
no code (`restore`/`export`/`rerun` refuse them) and match
`imported_from != null`. Guide: [migrating-from-mlflow.md](migrating-from-mlflow.md).

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
prints a `params:` delta next to the `metrics:` delta.

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
  existing runs. An S3 workspace in `vmn-exp ui` has no conf.yml; only the
  runs' own definitions apply there.
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
```

`<app-key>` is the app in tag form (`root_app/service` → `root_app-service`).
The repo-local root is `<repo>/.vmn/store/` with one `.gitignore` of `*`.
The first writer creates `store.yml` (`layout: 2`); readers and writers
refuse an unknown layout, and a v1 store (records but no `store.yml`) is
refused with a hint to run [`vmn-exp migrate`](#migrate). Per-host state
(the index cache and the [push](#offline-recording-and-push) ledger) lives
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
`prune`, `rewind` and `push` work; other actions need a checkout.
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
  ...) holding `metadata.yml`, patch files, per-writer
  `log/<writer>[@<seq>].jsonl`, `run_state.yml`, `outputs/` and `artifacts/`.
  `metadata.yml` makes a record exist: write it last, delete it first.
  Implement the abstract methods (`save`, `load_record`, `list_snapshots`,
  `update_note`, `delete`, `load_file`, `save_file`, `save_artifact_file`,
  `list_artifact_files`) and override the defaulted ones your store does
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
  `env.yml`, `alerts_sent.yml`, one append-only `log/<writer>.jsonl` per
  writer, `outputs/` (vmn's own files: `output.log`, `media/<name>/<step>.png`,
  `tables/<name>/<step>.json`) and `artifacts/` (the user's only, so any name
  is free). `metadata.yml` is written last, so a half-created run is never
  listed. Local writes are atomic (temp + rename).
- **Atomic allocation**: a new run claims its verstr atomically, so two hosts
  running the same commit against a shared bucket or directory get `…` and
  `….r2`, never one merged run.
- **Object keys**: `<root>/runs/<app-key>/<verstr>/<file>`, `<app-key>` in tag
  form (`root_app/service` → `root_app-service`).
- **Incremental log sync**: a host ships only what it appended since the last
  sync, as segments `log/<writer>@<n>.jsonl`; readers merge per writer. Log
  batches are written as whole lines in one write (one PUT), so readers never
  see a partial line.
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
  (currently 1) covering metadata, log lines and `run_state.yml`. `list`,
  `show`, the UI and the SDK skip records from a newer format with a warning
  to upgrade, and records without it (v1) with a warning to run
  `vmn-exp migrate`.

### `migrate`

`vmn-exp migrate [--store <uri> | --dir <path>] [--dry-run] [--skip-live]`
converts a v1 store to layout 2. Without a flag it moves the checkout's v1
records (`.vmn/<app>/experiments/`, `.vmn/<app>/snapshots/`, the `vmn-code`/
`vmn-sweeps`/`vmn-registry` pseudo-apps) into `.vmn/store/`; `--dir` takes a
dir whose v1 records sit under `<dir>/.vmn`; `--store` an object store (or
`file://`). It sets `migrating: true` in `store.yml` (writers refuse
meanwhile), copies each record to its v2 path (area, tag-form key, `log/`,
`outputs/`; `metadata.yml` last) and deletes the old copy, then clears the
flag. Record by record, so a killed migration resumes on rerun. Running or
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
  ends, and missing or resized artifacts. `archived`/`note` merge three-way
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
files: a sortable leaderboard with status pills and nested inner runs, live
curves from `step=` series, compare with a real code diff, an Importance view,
artifacts, media and lineage. Deployment, workspaces, job actions and the
HTTP API are in [ui.md](ui.md).
