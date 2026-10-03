# Sweeps: server-less hyperparameter search

`vmn-exp sweep` is a sweep controller in the style of W&B Sweeps
(`wandb sweep config.yaml` + `wandb agent <id>`), without the server. The
sweep lives in experiment storage and agents coordinate through atomic claims
in that same storage. Start N agents on Slurm, k8s or a few shells: as long as
they share the experiments directory (NFS) or store (`--store`, `--bucket`),
no two of them run the same trial.

```sh
vmn-exp sweep create my_app -f sweep.yml --name lr_search   # prints the sweep's verstr
vmn-exp sweep agent  my_app <sweep-ref>                     # run trials until none are left
vmn-exp sweep status my_app <sweep-ref> [--json]            # counts + best trial
```

`<sweep-ref>` is the sweep run's verstr, a unique prefix or `@N`. A sweep is an
outer run carrying the spec; each trial is an inner job of it.

## The spec

```yaml
method: random            # grid | random | bayes
metric:
  name: loss              # the metric each trial reports
  goal: minimize          # minimize (default) | maximize (min | max also accepted)
parameters:
  lr:      {distribution: log_uniform, min: 1e-5, max: 1e-1}
  dropout: {distribution: uniform, min: 0.0, max: 0.5}
  layers:  {distribution: int_uniform, min: 2, max: 6}
  init:    {distribution: normal, mu: 0.0, sigma: 0.02}
  act:     {values: [relu, gelu]}          # categorical
  epochs:  {value: 20}                     # a constant
run_cap: 50               # at most 50 trials (grid: at most the grid size)
seed: 0                   # default 0; random/bayes draws are seeded by (seed, trial index)
early_terminate:          # optional
  type: median
  min_iter: 3             # default 3: never stop before step 3
  min_trials: 1           # default 1: peers needed at the same step to compare
  check_interval_sec: 10  # default 10: how often the agent checks
program: train.py
command: ["${env}", "${interpreter}", "${program}", "${args}"]
```

| Parameter form | Meaning |
|---|---|
| `value: x` | a constant |
| `values: [...]` (or `distribution: categorical`) | one of the values |
| `distribution: uniform`, `min`, `max` | a float in `[min, max]` |
| `distribution: log_uniform`, `min`, `max` | a float, uniform in log space; **`min`/`max` are the actual values** (like W&B's `log_uniform_values`), `min > 0` |
| `distribution: int_uniform`, `min`, `max` | an integer in `[min, max]` |
| `distribution: normal`, `mu`, `sigma` | a Gaussian draw (defaults 0 and 1; random only) |
| `min` + `max` without `distribution` | `int_uniform` when both are integers, else `uniform` |

Methods:

* **grid** walks the Cartesian product of `value`/`values`/`int_uniform`
  parameters (continuous ones are rejected). Parameters are ordered by name,
  the first varying slowest; trial N is always the same grid point.
* **random** draws every parameter from a generator seeded by `(seed, N)`, so
  trial N has the same params on every host and every re-run. Unbounded
  without `run_cap`; stop agents with `--count`.
* **bayes** asks Optuna's TPE sampler (`pip install optuna`) for the next
  point, given every succeeded trial's params and metric. The study is rebuilt
  in memory from storage for each suggestion, so there is no shared Optuna DB.
  `normal` is not supported; without Optuna the agent exits with an error.

`create` validates and normalizes the spec and stores it in the sweep run's
metadata (`sweep:`), where agents read it.

## The trial command

`command` is a list of argv entries:

| Placeholder | Expands to |
|---|---|
| `${<param>}` (anywhere in an entry) | that param's value, e.g. `"--lr=${lr}"` |
| `${args}` (whole entry) | `--name=value` per param, sorted by name |
| `${args_no_hyphens}` | `name=value` per param |
| `${args_json}` | one entry: every param as a JSON object |
| `${interpreter}` | the agent's Python (`sys.executable`) |
| `${program}` | the spec's `program` |
| `${env}` | nothing (W&B puts `/usr/bin/env` there) |

A spec with `program` and no `command` runs W&B's default,
`${env} ${interpreter} ${program} ${args}`. `vmn-exp sweep agent ... -- cmd ...`
overrides the spec's command, with the same substitution; with none of the
three, the agent errors. Unknown placeholders are an error. Strings are
inserted as-is, other values as JSON (`0.01`, `32`, `true`).

## Inside a trial

Each trial is supervised exactly like [`vmn-exp run`](experiments.md#run)
(heartbeat, `output.log`, signal forwarding, alerts). Besides
`VMN_EXPERIMENT_ID` / `VMN_APP_NAME` / `VMN_METRICS_FILE` the child gets
`VMN_SWEEP_PARAMS` (the params as JSON), `VMN_SWEEP_ID` (the sweep's verstr)
and `VMN_SWEEP_TRIAL` (the trial index).

Report the target metric with a step, so early stopping can compare. With the
SDK ([`sweep_params()`](sdk.md#sweep-trials-sweep_params)):

```python
from vmn_exp.sdk import start_run, sweep_params

params = sweep_params()              # {} outside a sweep
with start_run() as run:             # nests under the trial run
    for step in range(1, params["epochs"] + 1):
        run.log_metric("loss", train_one_epoch(params["lr"]), step=step)
```

or with the [metrics-file protocol](experiments.md#the-metrics-file-protocol):
`step=<step> loss=<loss>` lines to `$VMN_METRICS_FILE`.

A trial's metric is the trial run's own when it has one, else its
descendants': the only descendant that logged it, or the best of several by
goal. `status`, the best trial, the median rule and bayes suggestions all read
it this way.

The trial run records its params (so `params.lr > 1e-3` queries work), the tags
`sweep=<sweep verstr>`, `sweep_trial=N`, `sweep_attempt=K`, and is named
`<sweep name>-t<N>` (`.a<K>` for retries; the sweep name defaults to `sweep`).

## Claims: how agents coordinate

Trial slots are records `t<N>` under the store's `sweeps/` area, scope
`<app-key>~<sweep verstr>` (`<app-key>` is the app in tag form, `/` → `-`;
the area sits beside `runs/`, so it never shows in app listings). An agent lists them, takes
`max(N) + 1` (stopping at the trial limit), draws that trial's params, and
creates the record with `create_exclusive`: an `O_EXCL` mkdir locally or on
NFS, a conditional `If-None-Match: *` PUT on S3, the equivalent on GCS/Azure.
Exactly one agent wins; a loser re-lists and tries the next index. The claim
records the params, the agent (`<writer id>:<pid>`) and, once created, the
trial's run verstr. Claims are never deleted, so an index is never handed out
twice, even when its agent died mid-claim.

Trial runs are created under the repo lock (they snapshot the checkout, like
`vmn-exp run`); supervision runs without it.

## Failures, retries and dead agents

* A failed trial ends `failed` and the agent moves on; the sweep keeps going.
* Failed trials, and trials whose agent died (`stuck` once the heartbeat is
  stale), are **not** retried by default. `sweep agent --retry-failed` first
  re-runs each (same params, a new run tagged `sweep_attempt=K`), claiming the
  retry slot `t<N>.a<K>` atomically so two agents never retry it twice.
  `status` judges a trial by its latest attempt.
* A claim whose run was never created (the agent died in between) counts as
  `unstarted` in `status` and is not retried.
* A signal to the agent (Slurm preemption, `kill`) is forwarded to the running
  trial; the agent then exits instead of claiming more.

## Early termination (median rule)

With `early_terminate: {type: median}` the agent checks its running trial every
`check_interval_sec`: at the trial's latest step `s >= min_iter`, if its best
value up to `s` is strictly worse than the median of the other trials' best
values up to `s` (over at least `min_trials` trials that reached `s`), the
agent stops it: SIGTERM through the supervisor, SIGKILL after
`--kill-grace-sec`. The check runs on a background thread, so slow storage
never delays the heartbeat. Steps are the metric lines' `step=` values (else
the line's position).

A stopped trial keeps the child's real `exit_code` and gets
`end_reason: stopped` in its `run_state.yml`; its status derives as
**succeeded**, and `end_reason` is a row field
(`vmn-exp list --query 'end_reason = "stopped"'`). `hyperband` is not
supported.

## Status

```text
$ vmn-exp sweep status my_app @4
sweep 0.1.0-dev.1a2b3c4.5d6e7f8.r4 (random, loss min): 12 trial(s) of 50
  failed 1  running 3  succeeded 8  stopped_early 2  unstarted 0
  best: trial 7 0.1.0-dev.1a2b3c4.5d6e7f8.r11 loss=0.183  (act=gelu, lr=0.0021)
```

`--json` prints `sweep`, `method`, `metric`, `run_cap`, `trials`, `claimed`,
`unstarted`, `counts` (by status, latest attempt per trial), `stopped_early`
and `best` (`verstr`, `name`, `trial`, `value`, `params`).

In the UI, the sweep run's page has a **sweep** section: the spec, the trial
table (status, params, metric linked to the run it came from, best trial
highlighted) and a link to the leaderboard filtered to
`parent = "<sweep verstr>"`, whose parallel coordinates plot compares the
trials. It reads `GET .../experiments/{verstr}/sweep` (ETag/304; 404 for a run
that is not a sweep), which answers `{sweep, spec, summary, trials}`:
`summary` is `status --json`'s, and each trial has `verstr`, `name`, `trial`,
`attempt`, `status`, `params`, `value`, `metric_source` and `stopped_early`.

## Flags

| Flag | Action | Description |
|---|---|---|
| `-f`, `--file` | create | The spec (YAML) |
| `--name` | create | The sweep's name (prefix of trial names) |
| `--note` | create | A note on the sweep run |
| `--count N` | agent | Run at most N trials, then exit |
| `--retry-failed` | agent | Re-run failed/stuck trials before claiming new ones |
| `--json` | status | Machine-readable output |
| `--store`, `--bucket`, `--prefix`, `--endpoint-url` | all | The shared store ([Storage](experiments.md#storage-local-s3-gcs-azure-plugins)) |
| `--experiment-dir` | all | Experiments directory instead of `.vmn/` (or `VMN_EXPERIMENT_DIR`) |
| `--writer-id` | all | This process's writer id (default `VMN_WRITER_ID` or the hostname) |
| `--heartbeat-interval`, `--sync-interval` | agent | Seconds between heartbeats / remote syncs (default 30) |
| `--kill-grace-sec` | agent | Seconds a stopped trial gets before SIGKILL |
| `--no-capture-output`, `--output-cap-mb` | agent | Trial `output.log` capture |
| `--no-system-metrics`, `--no-env` | agent | Skip `sys_*` metrics / environment capture on trials |
