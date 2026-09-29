# Sweeps: server-less hyperparameter search

`vmn-exp sweep` is a sweep controller in the style of W&B Sweeps
(`wandb sweep config.yaml` + `wandb agent <id>`), without the server. The
sweep lives in experiment storage; agents coordinate through atomic claims in
that same storage. Start N agents on Slurm, k8s or a few shells: as long as
they share the experiments directory (NFS) or bucket (`--store`, `--bucket`),
no two of them ever run the same trial.

```sh
vmn-exp sweep create my_app -f sweep.yml --name lr_search   # prints the sweep ref
vmn-exp sweep agent  my_app <sweep-ref>                     # run trials until none are left
vmn-exp sweep status my_app <sweep-ref> [--json]            # counts + best trial
```

## The spec

```yaml
method: random            # grid | random | bayes
metric:
  name: loss              # the metric each trial reports
  goal: minimize          # minimize | maximize (min | max also accepted)
parameters:
  lr:      {distribution: log_uniform, min: 1e-5, max: 1e-1}
  dropout: {distribution: uniform, min: 0.0, max: 0.5}
  layers:  {distribution: int_uniform, min: 2, max: 6}
  init:    {distribution: normal, mu: 0.0, sigma: 0.02}
  act:     {values: [relu, gelu]}          # categorical
  epochs:  {value: 20}                     # a constant
run_cap: 50               # at most 50 trials (grid: at most the grid size)
seed: 0                   # random/bayes draws are seeded by (seed, trial index)
early_terminate:          # optional
  type: median
  min_iter: 3             # never stop before step 3
  min_trials: 1           # need this many peers at the same step to compare
  check_interval_sec: 10  # how often the agent checks
program: train.py
command: ["${env}", "${interpreter}", "${program}", "${args}"]
```

Parameters:

| form | meaning |
|---|---|
| `value: x` | a constant |
| `values: [...]` (or `distribution: categorical`) | one of the values |
| `distribution: uniform`, `min`, `max` | a float in `[min, max]` |
| `distribution: log_uniform`, `min`, `max` | a float, uniform in log space; **`min`/`max` are the actual values** (like W&B's `log_uniform_values`), `min > 0` |
| `distribution: int_uniform`, `min`, `max` | an integer in `[min, max]` |
| `distribution: normal`, `mu`, `sigma` | a Gaussian draw (random only) |
| `min` + `max` without `distribution` | `int_uniform` when both are integers, else `uniform` |

Methods:

* **grid** walks the Cartesian product of `value`/`values`/`int_uniform`
  parameters (continuous ones are rejected). Parameters are ordered by name;
  the first varies slowest. Trial N is always the same grid point.
* **random** draws every parameter from a generator seeded by `(seed, N)`, so
  trial N has the same params on every host and every re-run of the sweep.
  Unbounded without `run_cap` — stop agents with `--count`.
* **bayes** asks Optuna's TPE sampler (`pip install optuna`) for the next point,
  given every succeeded trial's params and metric; the study is rebuilt in
  memory from storage for each suggestion, so there is no shared Optuna DB.
  `normal` is not supported. Without Optuna the agent exits with a clear error.

The spec is validated and normalized at `create`, and the normalized spec is
stored in the sweep run's metadata (`sweep:`); agents read it from there.

## The trial command

`command` is a list of argv entries. Placeholders:

| placeholder | expands to |
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
overrides the spec's command, with the same substitution. Unknown placeholders
are an error. Strings are inserted as-is; other values as JSON (`0.01`, `32`,
`true`).

## Inside a trial

Each trial is an **inner job** of the sweep run, supervised exactly like
`vmn-exp run` (heartbeat, `output.log`, signal forwarding, alerts). The child
gets, besides `VMN_EXPERIMENT_ID` / `VMN_APP_NAME` / `VMN_METRICS_FILE`:

* `VMN_SWEEP_PARAMS` — the trial's params as JSON;
* `VMN_SWEEP_ID` — the sweep's verstr; `VMN_SWEEP_TRIAL` — the trial index.

Report the target metric either way, with a step for early stopping to compare
at. With the SDK:

```python
from vmn_exp.sdk import start_run, sweep_params

params = sweep_params()              # {} outside a sweep
with start_run() as run:             # nests under the trial run
    for step in range(1, params["epochs"] + 1):
        run.log_metric("loss", train_one_epoch(params["lr"]), step=step)
```

or with the [metrics-file protocol](experiments.md#the-metrics-file-protocol):
`f.write(f"step={step} loss={loss}\n")` to `$VMN_METRICS_FILE`.

A trial's metric is the trial run's own when it has one, else its
descendants': the only descendant that logged it, or the best of several by
goal. `status`, the best trial, the median rule (that run's series by step) and
bayes suggestions all read it the same way.

The trial run records its params (so `params.lr > 1e-3` queries work), the tags
`sweep=<ref>`, `sweep_trial=N`, `sweep_attempt=K`, and is named
`<sweep name>-t<N>`.

## Claims: how agents coordinate

Trial slots are records `t<N>` of the sweep's own pseudo-app
`vmn-sweeps/<app>~<sweep verstr>` (`/` in the app becomes `~`; the whole
`vmn-sweeps` tree is reserved and hidden from app listings), so a listing only
ever reads one sweep's slots. An agent lists them, takes `max(N) + 1` (stopping at the trial limit), draws that trial's
params, and creates the record with `create_exclusive` — an `O_EXCL` mkdir
locally/on NFS, a conditional `If-None-Match: *` PUT on S3 (and the equivalent
on GCS/Azure). Exactly one agent wins; a loser re-lists and tries the next
index. The claim records the params, the agent (`<writer id>:<pid>`) and, once
created, the trial's run verstr. Claims are never deleted, so an index is never
handed out twice, even when its agent died mid-claim.

Trial runs are created under the repo lock (they snapshot the checkout, like
`vmn-exp run`); supervision runs without it.

## Failures, retries and dead agents

* A trial whose command fails ends `failed`; the agent moves on to the next
  trial. The sweep keeps going.
* Failed trials, and trials whose agent died (their run reads `stuck` once the
  heartbeat is stale), are **not** retried by default.
  `vmn-exp sweep agent --retry-failed` first re-runs each such trial — same
  params, a new run tagged `sweep_attempt=K` — claiming the retry slot
  `t<N>.a<K>` atomically, so two retrying agents never re-run it twice.
  `status` judges a trial by its latest attempt.
* A claim whose run was never created (the agent died between the two) counts
  as `unstarted` in `status`; it is not retried.
* A signal to the agent (Slurm preemption, `kill`) is forwarded to the running
  trial as with `vmn-exp run`; the agent then exits instead of claiming more.

## Early termination (median rule)

With `early_terminate: {type: median}`, the agent checks its running trial
every `check_interval_sec`: at the trial's latest step `s >= min_iter`, if its
best value up to `s` is strictly worse than the median of the other trials'
best values up to `s` (counting trials that reached `s`, at least
`min_trials` of them), the agent stops it — SIGTERM through the supervisor,
SIGKILL after `--kill-grace-sec`. The check runs on a background thread, so
slow storage never delays the trial's heartbeat. Steps are the `step=` values
of the metrics lines (else the line's position). An early-stopped trial keeps
the child's real `exit_code` and gets `stopped_early: true` in its
`run_state.yml` — status derivation reads that as **succeeded** — plus the tag
`stopped_early=true` for queries and `status`. `hyperband` is not supported.

## Status

```text
$ vmn-exp sweep status my_app @4
sweep 0.1.0-dev.1a2b3c4.5d6e7f8.r4 (random, loss min): 12 trial(s) of 50
  failed 1  running 3  succeeded 8  stopped_early 2  unstarted 0
  best: trial 7 0.1.0-dev.1a2b3c4.5d6e7f8.r11 loss=0.183  (act=gelu, lr=0.0021)
```

`--json` prints the same as an object: `counts` (by status, latest attempt per
trial), `trials`, `claimed`, `unstarted`, `stopped_early`, `run_cap`, `metric`
and `best` (`verstr`, `name`, `trial`, `value`, `params`).

In the UI, the sweep run's page has a **sweep** section: the spec, the trial
table (status, params, metric; the best trial highlighted) and a link to the
leaderboard filtered to `parent = "<sweep verstr>"`, where the parallel
coordinates plot compares the trials.

## Agent flags

`sweep agent` takes `--count N`, `--retry-failed`, the storage flags (`--store`,
`--bucket`, `--prefix`, `--endpoint-url`, `--experiment-dir`, `--writer-id`) and
the `vmn-exp run` supervision flags (`--heartbeat-interval`, `--sync-interval`,
`--kill-grace-sec`, `--no-capture-output`, `--output-cap-mb`,
`--no-system-metrics`, `--no-env`).
