# Using vmn-exp from the client

This guide covers one project from start to finish, the way you use it: install once,
configure a store once, submit jobs, log from inside them, watch them, compare them,
reproduce the good one, recover from the bad ones, and ship a model. Each step is a
short snippet with a link to the reference ([experiments.md](experiments.md),
[sdk.md](sdk.md), [sweeps.md](sweeps.md), [ui.md](ui.md), [models.md](models.md)).

- [The five ideas you need](#the-five-ideas-you-need)
- [1. Install](#1-install)
- [2. Configure a store once](#2-configure-a-store-once)
- [3. Submit: an outer run with inner jobs](#3-submit-an-outer-run-with-inner-jobs)
- [4. Inside the job: the SDK](#4-inside-the-job-the-sdk)
- [5. Watch](#5-watch)
- [6. Compare and find what matters](#6-compare-and-find-what-matters)
- [7. Reproduce: restore, goto, export](#7-reproduce-restore-goto-export)
- [8. Resume, rewind, fork](#8-resume-rewind-fork)
- [9. Models](#9-models)
- [10. Clean up](#10-clean-up)

---

## The five ideas you need

1. **A run is code state plus a log.** Every run snapshots the working tree
   (base commit, uncommitted diff, untracked files) and gets a verstr such as
   `1.6.0-dev.a1b2c3d.e4f5g6h`. Metrics, params, notes, artifacts and tags are
   appended to its log. Nothing in the log is ever rewritten.
2. **Code is stored once per code identity.** Twenty trials of an unchanged
   tree share one stored code object, so every run keeps its snapshot and the
   extra runs cost almost nothing. There is no switch to turn snapshots off.
3. **Status is derived, never stored.** `created`, `running`, `stuck`,
   `succeeded`, `failed` come from the run's heartbeat and exit code. A job
   whose node vanished shows up as `stuck`; nobody has to mark it.
4. **Nesting is automatic.** A run created while `VMN_EXPERIMENT_ID` is set
   (which `vmn-exp run` and an open `start_run()` export) becomes an inner job
   of that run. A sweep is one outer run with its trials under it.
5. **A ref names a run**: a full verstr, a unique prefix, `@N` (the `[N]`
   `vmn-exp list` prints) or `latest`. Most commands take `-v <ref>`.

---

## 1. Install

```sh
pip install "vmn-exp[ui]"          # the vmn-exp CLI, the dashboard, and vmn itself
pip install "vmn-exp[ui,s3]"       # + S3; also [gcs], [azure], [mlflow]
```

A job image that only records runs needs just the SDK:

```sh
pip install vmn-exp-sdk            # + [s3] / [gcs] / [azure] for a bucket, [pandas] for DataFrames
pip install pynvml                 # optional: GPU sys_* metrics
```

`vmn-exp` is the experiment command. `vmn` stays the versioning command; with
vmn-exp installed, `vmn goto` can also restore a run's code (see
[Reproduce](#7-reproduce-restore-goto-export)). Details:
[packaging.md](packaging.md#installing).

No `init` step is needed. The first run in a repo sets up vmn tracking and
stamps a `0.0.0` baseline. Runs need a git identity (`user.name`,
`user.email`) because that first run commits.

---

## 2. Configure a store once

Runs go to `.vmn/<app>/experiments/` by default: local and git-ignored. To
share runs with your team and your cluster, point the app at a store in its
conf.yml and commit it:

```yaml
# .vmn/my_app/conf.yml
conf:
  experiment:
    storage:
      uri: s3://team-experiments/ml     # or gs://..., az://..., file:///mnt/nfs/exps
    metrics:
      val_loss: {goal: min, primary: true}   # sort key; ranks on the best epoch
      acc:      {goal: max}
    alerts:
      on: [failed, stuck, alert]
      sinks:
        - {type: slack, url: "https://hooks.slack.com/services/T/B/X"}
```

Machines without a checkout (pods, containers) use environment variables:

```sh
export VMN_EXPERIMENT_STORE=s3://team-experiments/ml
export VMN_EXP_ALERT_SLACK_URL=https://hooks.slack.com/services/T/B/X
```

The store resolves as `--store` > `VMN_EXPERIMENT_STORE` > conf
`experiment.storage.uri`. For MinIO, add the endpoint to the URI:
`s3://bucket/prefix?endpoint_url=http://minio:9000`. Backends and plugin
schemes: [Storage](experiments.md#storage-local-s3-gcs-azure-plugins).

---

## 3. Submit: an outer run with inner jobs

### On one machine: wrap the submit script

Wrap the script that launches your trials in `vmn-exp run`. Each
`vmn-exp run` (or `start_run()`) the script starts becomes an inner job:

```sh
#!/usr/bin/env bash
# submit.sh
for lr in 1e-4 3e-4 1e-3; do
    vmn-exp run my_app --name "lr=$lr" -- python train.py --lr "$lr"
done
```

```sh
vmn-exp run my_app --name lr-sweep -- ./submit.sh
```

`vmn-exp run` streams the command's output to your terminal and keeps a copy
as the run's `output.log`. It records CPU, memory and GPU as `sys_*` metrics,
heartbeats, forwards SIGTERM/SIGINT, and exits with the command's exit code.
The outer run's `tree_status` is `failed` if any trial failed. Opt-outs:
`--no-capture-output`, `--no-system-metrics`, `--no-env`.

### On a cluster: a managed sweep

For grid, random or bayes search across many machines, store the spec once and
start as many agents as you want. They share work through atomic claims in the
store, so no two agents run the same trial:

```yaml
# sweep.yml
method: random
metric: {name: val_loss, goal: minimize}
parameters:
  lr:    {distribution: log_uniform, min: 1e-5, max: 1e-2}
  batch: {values: [32, 64, 128]}
run_cap: 40
early_terminate: {type: median, min_iter: 3}
program: train.py
```

```sh
vmn-exp sweep create my_app -f sweep.yml --name lr_search     # prints the sweep ref
sbatch --array=1-8 --wrap "vmn-exp sweep agent my_app <sweep-ref>"
vmn-exp sweep status my_app <sweep-ref>
```

Agents create trial runs from a checkout, so run them where the repo is
checked out. `--count N` caps the trials an agent runs, and `--retry-failed`
re-runs failed or stuck trials. Inside a trial, `sweep_params()` returns the
trial's params. See [sweeps.md](sweeps.md).

### Jobs without git: export the code once

Pods that have no checkout record against an exported snapshot:

```sh
OUTER=$(vmn-exp create my_app --name k8s-sweep | tail -n1)   # the outer run
vmn-exp export my_app -v "$OUTER" -o ./code                  # bake ./code into the image
```

In each pod, set `VMN_SNAPSHOT_METADATA=/workspace/code/vmn_metadata.yml`,
`VMN_EXPERIMENT_STORE`, and `VMN_EXPERIMENT_ID=$OUTER` (so the job nests under
the outer run), then call `start_run()`. For the full cluster walkthrough, see
[experiment-tracking-guide.md](experiment-tracking-guide.md).

---

## 4. Inside the job: the SDK

```python
from vmn_exp.sdk import start_run

with start_run("my_app", name="resnet-lr3e-4", params={"lr": 3e-4, "batch": 64},
               tags={"team": "vision"}) as run:
    run.define_metric("val_*", step_metric="epoch", goal="min")  # chart vs epoch, rank on best
    run.log_input("s3://data/train.parquet", name="train", digest="sha256:9f2c...")

    for step, batch in enumerate(loader):
        loss = train_step(batch)
        run.log_metric("loss", loss, step=step)                  # a live curve
        if loss != loss:                                         # NaN
            run.alert("loss is NaN", text=f"step {step}", level="error")
        if step % 500 == 0:
            val_loss, epoch = evaluate(), step // len(loader)
            run.log_metrics({"val_loss": val_loss, "epoch": epoch}, step=step)
            run.log_image("samples", sample_grid(), step=step)   # numpy/PIL/path/figure
            run.log_table("preds", preds_as_dicts(), step=step)  # list of dicts or DataFrame
            run.log_histogram("fc.weight", model.fc.weight, step=step)
            torch.save(model.state_dict(), "ckpt.pt")
            run.log_artifact("ckpt.pt", name=f"checkpoints/step{step}.pt")

    run.log_artifact("model.pt")
    print(run.id)
```

What you get without asking:

- **Batched, crash-safe writes.** Log calls are flushed at least once a second,
  on every heartbeat, and on finish, SIGTERM or interpreter exit. An exception
  in the `with` block marks the run `failed` and is re-raised. A preempted job
  (SIGTERM) reads `failed` with exit code 143, never `stuck`.
- **System metrics** (`sys_cpu_percent`, `sys_rss_mb`, GPU with `pynvml`) on
  every heartbeat. Opt out with `system_metrics=False`,
  `VMN_SYSTEM_METRICS=0`, or conf `experiment.system_metrics: false`. Under
  `vmn-exp run` the supervisor already samples the job, so `start_run()`
  inside it samples nothing by default.
- **Environment capture** (Python, platform, packages). Opt out with
  `capture_env=False`, `VMN_CAPTURE_ENV=0`, or `--no-env`.
- **Distributed jobs**: only rank 0 records. Other ranks get a no-op run with
  the same methods.

Worth opting into:

- `start_run(..., capture_output=True)` keeps this process's stdout/stderr as
  `output.log`, capped by `VMN_EXP_OUTPUT_CAP_MB` (default 10). It is off by
  default, and unnecessary under `vmn-exp run`, which already keeps it.
- `from vmn_exp.sdk import autolog; autolog()` records sklearn, xgboost, Keras,
  Lightning and transformers fits into the open run. See
  [Autologging](sdk.md#autologging).

**Consuming another run's output** links the two runs (lineage):

```python
with start_run("my_app", name="eval") as ev:
    path = ev.use_artifact("@7", "model.pt")   # downloads if remote; records a vmn:// input
    ev.log_metric("test_acc", evaluate_file(path))
```

```sh
vmn-exp lineage my_app -v @8 --depth 2       # what @8 consumed, and who consumed its outputs
```

A script you don't want to change can still report metrics under
`vmn-exp run`. It appends `[step=N] key=value` lines to `$VMN_METRICS_FILE`:
[the metrics-file protocol](experiments.md#the-metrics-file-protocol).

---

## 5. Watch

```sh
vmn-exp list my_app                         # one row per run, status, inner runs indented
vmn-exp list my_app --query 'status in ("running", "stuck")'
vmn-exp show my_app -v @12                  # status, metrics (best/last/min/max), recent log
vmn-exp ui                                  # dashboard on http://127.0.0.1:8265
vmn-exp ui --store s3://team-experiments/ml # a store with no checkout
```

`show` and the dashboard update while the job trains. Logged metrics reach
the local record within about a second, and a remote store gets the new log
lines every `sync_interval_sec` (`--sync-interval` on the CLI; default 30 s)
and again at the end. None of these commands takes the repo lock.

A dead process cannot report itself, so `stuck` alerts come from a watcher.
Run one from cron or leave it looping:

```sh
vmn-exp watch my_app --interval 60          # alert new failed/stuck runs every minute
```

`failed` alerts come from the job itself. `run.alert()` goes to the same sinks.
Each run alerts once per transition. See [Alerts](experiments.md#alerts).

---

## 6. Compare and find what matters

```sh
vmn-exp list my_app --sort val_loss --top 5          # best first (goal-aware)
vmn-exp compare my_app -v @3 -v @9 -v @12            # metrics side by side
vmn-exp diff my_app -v @3 -v @9                      # params delta + the real code diff
vmn-exp importance my_app --metric val_loss          # which params drive val_loss
vmn-exp list my_app --query 'params.batch = 64 and metrics.val_loss < 0.3' --json
```

A metric logged every epoch ranks on its **summary**: the best value for a
`goal: min|max` metric, the last value otherwise. Set it with
`run.define_metric()` or in conf.yml; see
[Best-value summaries](experiments.md#best-value-summaries-summary).

From Python or a notebook:

```python
from vmn_exp.sdk.reader import get_metric_history, param_importance, runs_dataframe

df = runs_dataframe("my_app", query='status = "succeeded"')    # needs vmn-exp-sdk[pandas]
df.sort_values("metrics.val_loss").head()
curve = get_metric_history("val_loss", "my_app", ref="@9")      # step, timestamp, value
param_importance("my_app", "val_loss")[:3]
```

Tag the winner, and archive the noise without deleting it:

```sh
vmn-exp tag my_app @9 stage=candidate
vmn-exp archive my_app @1 @2 @4
```

---

## 7. Reproduce: restore, goto, export

| You want | Command |
|---|---|
| This checkout at a run's exact code (commit + uncommitted diff + untracked files) | `vmn-exp restore my_app -v @9` (or `--latest`) |
| The same, with vmn's versioning command, by full verstr | `vmn goto -v 1.6.0-dev.a1b2c3d.e4f5g6h my_app` |
| The code as a directory or tarball, for an image or a colleague | `vmn-exp export my_app -v @9 -o best.tar.gz` |

`restore` and `goto` find the run the same way. They check local experiments
first, then the app's remote store, then the snapshot store, so they can
restore a run that another host recorded straight to S3. If your tree is
dirty, the work is saved as a dev version before it is replaced, and the
`vmn goto -v <saved> my_app` command that brings it back is printed. The two
commands differ in the ref they accept and in how they find the store; see
[Restore vs goto](experiments.md#restore-vs-goto).

---

## 8. Resume, rewind, fork

These three operations do different things. Choosing the wrong one either
mixes histories or loses the original.

| | **Resume** | **Rewind** | **Fork** |
|---|---|---|---|
| What you get | the **same** run, continued | the **same** run, with its history past step N hidden | a **new** run that starts with the source's history up to step N |
| verstr | unchanged | unchanged | new; records `forked_from: {verstr, step}` |
| Code snapshot | the original one | the original one | the current working tree |
| The original history | kept, new entries appended | kept on disk; readers skip entries with `step > N` logged before the rewind marker | the source run is untouched |
| SDK | `start_run(run_id=<ref>)` or `VMN_RESUME_RUN_ID=<ref>` | `start_run(run_id=<ref>, rewind_to_step=N)` | `start_run(fork_from=<ref>, fork_step=N)` (or `"<ref>?_step=N"`) |
| CLI | none (`vmn-exp run` never reopens a run) | `vmn-exp rewind my_app -v <ref> --step N` | `vmn-exp run/create --fork-from <ref> --fork-step N` |
| Next step to log | yours to track | `run.start_step` = N + 1 | `run.start_step` = N + 1 |
| Use it when | a job was preempted or crashed and you continue from where it stopped | the run went wrong after step N and you want to redo that part in place | you want to try a variation from step N and keep the original |

What each one does:

- **Resume** reopens the run: `state: running` again with this process's
  pid/host, a fresh heartbeat, and new log entries appended in this process's
  own log segment. `started_at` is kept, and `resume_count`/`resumed_at`
  record the attempts. `VMN_RESUME_RUN_ID` is removed from the environment
  once used, so child processes don't resume the same run again. Resume does
  not check whether another process is still writing the run, so resume only a
  run whose job is gone.
- **Rewind** deletes nothing. It appends `{"type": "rewind", "step": N}` to
  the log, and every reader (`show`, `list`, the index, the dashboard,
  `list_runs`) skips each entry with a step greater than N that was written
  before that marker. Entries written after the marker count normally, so the
  run continues from N + 1. Entries without a step (params, notes, tags) are
  never hidden. `vmn-exp show` prints a `Rewound to step N` line for each
  rewind. **A live run can't be rewound**: if the run derives as `running`,
  the rewind is refused, because its writer would keep logging the steps being
  hidden. The dashboard's `exp_rewind` action runs the CLI command.
- **Fork** creates a new run with a new snapshot of the tree as it is now. Its
  log opens with the source's metrics and params up to step N, copied with
  `"inherited": true`, and `params=` you pass override the inherited ones. A
  fork is not a child: `parent` and `tree_status` don't change. To list a
  run's forks: `vmn-exp list my_app --query 'forked_from = "<verstr>"'`.

vmn keeps metrics, not model weights. To continue training, log checkpoints as
artifacts (`run.log_artifact(..., name="checkpoints/step800.pt")`) and fetch
them back with `use_artifact`, or keep them wherever you already keep them.

### Example: a preempted job resumes itself

The job saves its run id next to its checkpoints. When the scheduler requeues
it, the job reopens the same run and rewinds to its last checkpoint, which
drops the steps it logged after that checkpoint:

```python
from pathlib import Path
from vmn_exp.sdk import start_run

ckpt_dir = Path("/scratch/job-42")
id_file = ckpt_dir / "vmn_run_id"
prior = id_file.read_text() if id_file.exists() else None
ckpt_step = latest_checkpoint_step(ckpt_dir)          # your code; None on a fresh start

with start_run("my_app", run_id=prior,
               rewind_to_step=ckpt_step if prior else None) as run:
    id_file.write_text(run.id)
    start = run.start_step or 0                       # ckpt_step + 1 after a rewind
    for step in range(start, 10_000):
        run.log_metric("loss", train_step(), step=step)
        if step % 200 == 0:
            save_checkpoint(ckpt_dir, step)
```

The preempted attempt was finalized on SIGTERM (`failed`, exit 143), so the
resumed attempt can rewind it at once. If the old process died without
finalizing (a SIGKILL), it reads `running` until its heartbeat goes stale
(`max(3 x heartbeat interval, 60s)`). Until then the rewind is refused with a
`RuntimeError`, so requeue with a delay.

Without the rewind (`start_run(run_id=prior)`), the entries logged between the
checkpoint and the preemption stay in the history, next to the ones the resumed
attempt logs again for the same steps.

### Example: a divergent loss, rewound to step 800

`vmn-exp show my_app -v @7` shows the loss blowing up after step 800. Hide
everything past 800 without reopening the run:

```sh
vmn-exp rewind my_app -v @7 --step 800
# rewound 1.6.0-dev.a1b2c3d.e4f5g6h to step 800 (hid 412 entries)
```

The run's curves, summaries and leaderboard rank now end at step 800. To
continue it with a lower learning rate, reopen it from Python. The rewind and
the reopen can be a single call:

```python
with start_run("my_app", run_id="@7", rewind_to_step=800,
               params={"lr": 1e-4}) as run:      # params on resume are appended
    load_checkpoint("ckpt/step800.pt")           # your checkpoint from step 800
    for step in range(run.start_step, 5000):     # 801, 802, ...
        run.log_metric("loss", train_step(), step=step)
```

### Example: branch from step 500 with a new learning rate

Keep run `@7` as it is, and try `lr=1e-4` from its step 500 as a separate run:

```python
src = "1.6.0-dev.a1b2c3d.e4f5g6h"
with start_run("my_app", fork_from=src, fork_step=500,
               params={"lr": 1e-4}, name="lr1e-4-from-500") as run:
    load_checkpoint(run.use_artifact(src, "checkpoints/step500.pt"))
    for step in range(run.start_step, 5000):     # 501, 502, ...
        run.log_metric("loss", train_step(), step=step)
```

The fork's charts show steps 0-500 inherited from the source followed by its
own points, and the dashboard marks the fork step. The same from the CLI, with
the script loading its own checkpoint and logging `step=` lines from 501
(`--lr` and `--resume-step` are `train.py`'s flags, not vmn's):

```sh
vmn-exp run my_app --fork-from @7 --fork-step 500 -- python train.py --lr 1e-4 --resume-step 500
```

References: [Resuming](sdk.md#resuming-a-preempted-run),
[Forking](sdk.md#forking-a-run), [Rewinding](sdk.md#rewinding-a-run),
[`vmn-exp rewind`](experiments.md#rewind).

---

## 9. Models

Give the winning run's artifact a name and a moving alias. Your serving code
then refers to that name instead of a verstr:

```sh
vmn-exp model register churn_model -v @9 --app my_app --artifact model.pt --alias staging
vmn-exp model alias churn_model production 3 --expect 2    # move only if production is at v2
vmn-exp model show churn_model
```

```python
from vmn_exp.sdk import download_model, get_model_version

path = download_model("churn_model@production")
meta = get_model_version("churn_model@production")   # run_ref -> the run that produced it
```

Or register from inside the run with
`run.register_model("churn_model", artifact_path="model.pt", alias="staging")`.
Model names use letters, digits, `_` and `.`, with no hyphens. See
[models.md](models.md).

---

## 10. Clean up

```sh
vmn-exp prune my_app --keep 50 --dry-run                     # preview
vmn-exp prune my_app --older-than 30d --protect-tag stage
vmn-exp prune my_app --query 'status = "failed"' --yes       # --query previews unless --yes
vmn-exp prune my_app -v @4                                   # exactly one run
```

Prune never deletes a `running` or `stuck` run, a run tagged with a
`--protect-tag` key (`--force` overrides both), a run with a surviving inner
run, or a run registered as a model version (not even with `--force`; run
`vmn-exp model delete` first). With a remote store, prune deletes the remote
copy too; `--local-only` keeps it. A run's stored code is deleted with the
last run that uses it. Prefer `archive` for runs you only want out of sight.
