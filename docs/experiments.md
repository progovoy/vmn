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
- [Three ways to record an experiment](#three-ways-to-record-an-experiment)
- [Without a script: config sweeps & performance tests](#without-a-script-config-sweeps--performance-tests)
- [With a command: `exp run` and the metrics file](#with-a-command-exp-run-and-the-metrics-file)
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

## Three ways to record an experiment

| You want to… | Use |
|---|---|
| Capture the tree and type in the numbers yourself | `exp create … --metrics k=v` |
| Add more numbers/notes/files to an existing run later | `exp add …` |
| Let vmn run a command and slurp metrics it emits | `exp run … -- <cmd>` |

All three snapshot the working tree (dirty or clean). They differ only in *how*
the metrics get in. You can mix them — e.g. `exp run` a benchmark, then `exp add`
a hand-measured number afterward.

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
command's own exit code, so CI can tell a failed run from a passing one.

### The metrics-file protocol

vmn sets three environment variables for the child process:

| Variable | Value |
|---|---|
| `VMN_EXPERIMENT_ID` | the verstr of this run |
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
```

### `run`

Create an experiment, run a command, and record its outcome (exit code,
duration) plus any metrics it emits to `$VMN_METRICS_FILE`.

```sh
vmn exp run my_app --note "lr 0.01" -- python train.py --lr 0.01
vmn exp run my_app -- ./perf_test.sh
```

### `add`

Append metrics, a note, an artifact, or a structured entry to an experiment
(defaults to the latest). The log is append-only — nothing is overwritten.

```sh
vmn exp add my_app --metrics val_loss=0.29 val_acc=0.93
vmn exp add my_app -v @2 --attach checkpoint.pt --note "after warmup"
vmn exp add my_app -f extra_notes.yml
```

### `list`

List experiments, optionally sorted by a metric.

```sh
vmn exp list my_app                        # all
vmn exp list my_app --sort loss --top 5    # best 5 by loss (goal-aware)
vmn exp list my_app --last 10              # most recent 10
```

### `show`

Full details for one experiment: metadata, latest metrics, and the whole log
timeline.

```sh
vmn exp show my_app          # latest
vmn exp show my_app -v @1
```

### `compare`

Side-by-side metric table across N experiments (no code diff — use `diff` for
that). Needs at least two.

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

Delete old experiments by count or age.

```sh
vmn exp prune my_app --keep 10          # keep the 10 most recent
vmn exp prune my_app --older-than 30d   # remove anything older than 30 days (Nd/Nw/Nh)
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

---

## Web UI

`vmn ui` (from `pip install "vmn[ui]"`) serves a dashboard over the same files:
a sortable experiment leaderboard, per-run detail with **live training/perf
curves** (from `step=` series), side-by-side compare with a real code diff, and
an artifact browser. See [docs/ui.md](ui.md) for the full tour.

To get live curves, have your command log `step=`-tagged lines to
`$VMN_METRICS_FILE` — `exp run` tails the file during the run, so the curve
updates in the browser *while the command is still executing*.
