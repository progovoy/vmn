# Python SDK

`vmn_exp.sdk` is the in-process Python API for [experiment
tracking](experiments.md). It records the same runs the CLI does — same
snapshot, same verstr, same files — without a wrapper command or a metrics file.

```python
from vmn_exp.sdk import start_run

with start_run("my_app", note="baseline", params={"lr": 3e-4}) as run:
    run.log_params({"batch": 32})
    for step, loss in enumerate(train()):
        run.log_metric("loss", loss, step=step)
    run.log_metrics({"acc": 0.91, "f1": 0.88})
    run.log_note("converged early")
    run.log_artifact("model.pt")
    print(run.id)     # the verstr, e.g. 1.6.0-dev.a1b2c3d.e4f5g6h
```

No extra install: the SDK ships in the base wheel and adds no third-party
dependencies. It imports `version_stamp.core` and the snapshot helpers and
nothing else — in particular never `version_stamp.ui` — so the experiment
feature stays liftable into its own distribution later.

A run needs a git repo with a remote and a usable git identity: creating one
commits a snapshot, so `user.name` and `user.email` must be set. In a container
that means setting them in the image or via `GIT_AUTHOR_*`/`GIT_COMMITTER_*` —
otherwise the first `start_run` fails on git's "please tell me who you are".

**Runnable versions of what follows live in
[`examples/`](../examples/README.md)** — five standalone scripts (a minimal run,
a training loop, a nested sweep, the query language, autologging) that need no
arguments and no network: `python examples/01_minimal.py` from inside a git repo
with a remote. They record to the app `vmn_examples`, so they never touch a real
one.

- [CLI or SDK?](#cli-or-sdk)
- [Starting a run](#starting-a-run)
- [Logging](#logging)
- [Autologging](#autologging)
- [Finishing, failures, and the heartbeat](#finishing-failures-and-the-heartbeat)
- [Nesting](#nesting)
- [Reading runs back](#reading-runs-back)
- [The query language](#the-query-language)
- [Model registry](#model-registry)
- [Integrations](#integrations)
- [Library logging](#library-logging)

---

## CLI or SDK?

| Situation | Use |
|---|---|
| Wrapping a script you don't want to modify | `vmn-exp run my_app -- python train.py` |
| A non-Python workload (a shell benchmark, `wrk`, a compiler flag sweep) | `vmn-exp run` + `$VMN_METRICS_FILE` |
| You're already inside Python and want per-step metrics without a metrics file | `start_run(...)` |
| Metrics you measured by hand | `vmn-exp create … --metrics k=v` |

**An SDK run is indistinguishable from a CLI run on disk.** Same verstr scheme,
same `metadata.yml`, same per-writer JSONL log, same `run_state.yml`. So
`vmn-exp list`, `vmn-exp show`, `vmn-exp compare`, the web dashboard, and S3 sync
all work on SDK runs with no extra steps, and mixing the CLI and the SDK in one
project is fine — `vmn-exp add` a hand-measured number to a run your training
script opened.

---

## Starting a run

```python
start_run(
    app_name=None,
    note=None,
    params=None,
    parent=None,
    nested=False,
    heartbeat_interval_sec=None,
    storage=None,
    system_metrics=None,
    sync_interval_sec=30,
    snapshot=True,
    run_id=None,
    all_ranks=False,
    name=None,
    tags=None,
    capture_env=None,
    capture_output=False,
)
```

| Argument | Means |
|---|---|
| `app_name` | the app to track under. `None` resolves it from the current repo, exactly as the CLI does |
| `note` | free-text note recorded on the run |
| `params` | the run's inputs, like `-f params.yml`'s `params:` key |
| `parent` | parent run, in any [addressing form](experiments.md#addressing-experiments) — a full verstr, a unique prefix, `@N`, or `latest` |
| `nested` | parent to the calling context's open run (see [Nesting](#nesting)) |
| `heartbeat_interval_sec` | beat cadence; defaults to the same 30s the CLI uses. Also the sampling interval for `system_metrics` — the two are the same clock |
| `storage` | a storage backend, for S3-backed stores; defaults to the app's configured one |
| `system_metrics` | `None` (default) records this process's CPU/memory (and GPU, with `pynvml` installed) as `sys_*` metrics on every beat; `False` turns sampling off; `True` samples even when `experiment.system_metrics: false` is set in conf.yml but still respects `VMN_SYSTEM_METRICS=0`. `psutil` ships with the SDK; GPU metrics need `pip install pynvml`. A missing sampler dependency is silent (debug log only). Non-zero ranks record nothing, system metrics included |
| `sync_interval_sec` | push the log to the remote store (when `storage` has one, e.g. S3) at most this often, off the heartbeat thread (a hung upload never delays a beat) — so a run that is OOM-killed or preempted still leaves its metrics remotely. `None`/`0` syncs only on `finish()`. A failed sync is logged and retried on a later beat; it never stops the heartbeat |
| `snapshot` | `False` records only the code identity — base commit and diff hash, the same `code_verstr` a full snapshot gets — with no patches and no untracked tarball (`metadata.yml` says `snapshot: false`). For many lightweight runs; such a run cannot be restored |
| `run_id` | reopen an existing run of the app instead of creating one, in any [addressing form](experiments.md#addressing-experiments). Falls back to `$VMN_RESUME_RUN_ID`. See [Resuming a preempted run](#resuming-a-preempted-run) |
| `all_ranks` | record on every rank of a distributed job; by default only rank 0 does (see [Distributed training](#distributed-training-ddp-torchrun-slurm)) |
| `name` | a human-readable run name, stored as `name` in `metadata.yml`, shown by `vmn-exp list`, available as `run.name` and queryable (`name ~ "sweep"`) |
| `tags` | `{key: value}` tags set as the run opens (see [Tags](#tags)) |
| `capture_env` | `None` (default) captures the runtime environment (Python version, platform, installed packages); `False` skips capture entirely; `True` captures even when `experiment.capture_env: false` is set in conf.yml but still respects `VMN_CAPTURE_ENV=0`. Resuming (`run_id=...`) always keeps the original captured env. |
| `capture_output` | `True` tees this process's stdout/stderr into the run's `output.log` artifact — the same artifact [`vmn-exp run`](experiments.md#console-output-outputlog) keeps. Captured at the file-descriptor level (fds 1 and 2), so `print`, logging handlers, C extensions and subprocesses are all kept, and everything still reaches the original streams. Capped like the CLI (`$VMN_EXP_OUTPUT_CAP_MB`, default 10; first and last halves kept), uploaded off-thread every `sync_interval_sec` and at `finish()` (SIGTERM and interpreter exit included); the fds are restored at finish. Off by default: redirecting a host process's descriptors means it writes to pipes rather than its TTY, which an interactive debugger or a notebook kernel may not expect. Under `vmn-exp run` the CLI already keeps the output, so leave it off there |

The system metrics are on by default — here and on `vmn-exp run`, which
measures the child's process tree instead. Opt out, strongest first:
`system_metrics=False` / `vmn-exp run --no-system-metrics`, then
`VMN_SYSTEM_METRICS=0` (or `false`/`no`/`off`), then conf.yml:

```yaml
conf:
  experiment:
    system_metrics: false
```

Samples are taken on the heartbeat thread, once per beat (30 s by default), so
a run shorter than one beat records none.

| Metric | Meaning |
|---|---|
| `sys_cpu_percent` | CPU of the process tree, summed (so >100 on several cores). Samples are at least 0.1 s apart — psutil reads a near-zero interval as 0% — and a worker born since the last sample is counted from its own CPU time |
| `sys_rss_mb` | memory of the tree: the root's RSS plus each child's *unique* memory (USS), so forked workers sharing the parent's pages are not counted N times |
| `sys_gpu_mem_mb` | GPU memory held by the tree's own processes (NVML per-process accounting); omitted when NVML lists none of them — e.g. inside a container, where NVML reports host pids |
| `sys_gpu_node_mem_mb` | used memory on the visible GPUs, all processes included |
| `sys_gpu_node_util_percent` | mean utilization over the visible GPUs, all processes included |

"Visible" follows `CUDA_VISIBLE_DEVICES` (indices or UUIDs), not every device
on the node. Each NVML query is guarded on its own, so one a device does not
support (utilization under MIG, say) drops that value only. Several runs open
in one process all sample that same process.

Creating the run snapshots the working tree (dirty or clean) and assigns the
verstr, available as `run.id`. As with the CLI, the first run in a fresh repo
cold-starts vmn tracking and stamps a `0.0.0` baseline. Several workers may
cold-start one fresh checkout at the same moment: they serialize on the repo
lock, and each builds its view of the repo only once it holds the lock, so the
ones that wait see the initialization the first one did.

**An SDK cold start is local-only.** Unlike `vmn-exp`/`vmn stamp`, it never
pushes: the init commit and the `<app>_0.0.0` tag stay in your checkout, so a
training script neither publishes refs as a side effect nor fails in a checkout
that has no remote. Push them when you want to share them
(`git push --follow-tags`).

The repo lock (`.vmn/vmn.lock`) is held only where it is needed: by the cold
start, when there is something to initialize, and for the verstr claim. The
snapshot itself — `git diff`, format-patch, hashing and tarring untracked files —
is captured *before* the lock is taken, so the trials of a sweep started at once
capture in parallel instead of queueing behind each other. Within one process
the untracked tarball is memoized by the tree's identity (repo, `HEAD`, diff
hash — which covers the untracked files' contents), so trials 2..N of an
unchanged tree reuse trial 1's. The lock is released before your training code
runs — a run that trains for hours does not block other `vmn` commands, and a
subprocess you launch can use vmn freely.

### Runs without a git checkout (containers)

A training image built from [`vmn-exp export`](experiments.md#export) has no `.git`.
Set `VMN_SNAPSHOT_METADATA` to the exported `vmn_metadata.yml` (or its directory)
and `VMN_EXPERIMENT_DIR` to where runs should be recorded, and `start_run()`
records against that exported code — the same git-free mode the CLI's `--from-snapshot`
uses:

```python
# VMN_SNAPSHOT_METADATA=/app/vmn_metadata.yml  VMN_EXPERIMENT_DIR=/mnt/runs
with start_run() as run:            # app name comes from the metadata
    run.log_metric("loss", 0.25)
```

`app_name` may still be passed (or set via `VMN_APP_NAME`); otherwise the app the
snapshot names is used.

To record to a shared store from a pod, set `VMN_EXPERIMENT_STORE` to a store URI —
`s3://bucket/prefix`, `gs://bucket/prefix` (`[gcs]` extra), `az://container/prefix`
(`[azure]` extra), `file:///mnt/nfs/exps` or a plugin scheme (see
[Storage](experiments.md#storage-local-s3-gcs-azure-plugins)).
`VMN_EXPERIMENT_BUCKET` (plus `VMN_EXPERIMENT_PREFIX`, default `vmn-experiments`, and
`VMN_EXPERIMENT_ENDPOINT_URL` for MinIO and the like) is shorthand for an `s3://`
URI; `VMN_EXPERIMENT_STORE` wins over it. With `VMN_EXPERIMENT_DIR` too, entries are
appended to that local scratch dir and the new lines are synced to the store every
`sync_interval_sec`; with the store alone the run writes straight to it. The job
creates its own record — no prefix needs to exist beforehand — and
`vmn-exp ui --store <uri>` reads it. `storage=` still overrides all of this. With
neither a dir nor a store, `start_run()` raises a `ValueError` naming
`VMN_EXPERIMENT_DIR` and `VMN_EXPERIMENT_STORE`.

---

## Logging

Every call appends to the run's log; nothing is ever rewritten.

| Call | Records |
|---|---|
| `run.log_metric(key, value, step=None)` | one metric. With `step`, it joins a **per-step series** — the curve `exp show` and the UI plot |
| `run.log_metrics({...})` | several metrics at once; also takes `step=` |
| `run.log_params({...})` | more inputs, merged into the run's params |
| `run.log_input(uri, name=None, digest=None, kind=None)` | record a dataset or artifact the run consumed. `name` defaults to the URI basename. `digest` (e.g. `"sha256:..."`) and `kind` (e.g. `"dataset"`) are optional. Multiple calls are independent entries; folded last-write-wins by name in `vmn-exp list`. |
| `run.log_note(text)` | a note entry |
| `run.log_artifact(path, name=None)` | a file produced by the run, stored as `name` (a relative `a/b/c.txt` path) or under its basename |
| `run.log_dict(obj, name)` | `obj` as JSON (`.json`) or YAML (`.yaml`/`.yml`), by `name`'s extension |
| `run.log_text(text, name)` | a text file |
| `run.log_figure(fig, name, **savefig_kwargs)` | a matplotlib-style figure through its `savefig` (the format follows `name`); nothing imports matplotlib |
| `run.log_artifacts(local_dir, prefix=None)` | every file under `local_dir`, named by its path below it (`prefix/sub/file`) |
| `run.set_tag(key, value)` / `run.set_tags({...})` / `run.remove_tag(key)` | mutable [tags](#tags) |
| `run.define_metric(name, step_metric=None, **fields)` | declare how metric `name` (exact, or an `fnmatch` glob like `val_*`) is charted — see [Custom x axis](#custom-x-axis-step_metric) |

Artifact names may be nested relative paths; absolute paths, `..`, `.`, empty
components, backslashes and NUL are refused with a `ValueError` (`log_artifacts`
checks every name before uploading any). Each helper stores a real file, so the
log entry (`path` = the name, `size`, `sha256`) and the backends are exactly those
of `log_artifact`, and `vmn-exp ui` downloads nested ones at
`.../artifacts/<a/b/c.txt>`.

**Writes are batched.** Log calls queue in memory and reach the store as one
write of whole lines per flush: at most every ~1 s (a daemon thread), whenever
1000 entries are pending, on every heartbeat (before the remote sync), and on
`finish()`, SIGTERM and interpreter exit — before the final run state is
published, so a reader that sees a run finished sees everything it logged.
A reader never sees half a line. This is what lets a loop log ~50k points a
second (vs ~2-5k when every call opened and appended to the file); the price is
that another process sees a metric up to ~1 s after it was logged. A forked
child writing through an inherited `Run`, or a write after `finish()`, goes
straight to the store. Storage backends take the batch through
`append_log_entries(app, verstr, writer, entries)` (one `O_APPEND` write and
one record-signature bump locally, one PUT on S3; the base class loops over
`append_log_entry`).

Metrics land in the store within about a second of being logged, so `vmn-exp
show` and the web UI see the curve **while training is still running**.

Metric values are stored as floats, whatever you pass:

- numpy scalars, 0-d arrays and 0-d torch tensors are unwrapped (no need for
  `.item()`), and numeric strings such as `"0.5"` are parsed;
- `nan` and `inf` are kept — a diverged loss is a real result — and sort last
  on a leaderboard;
- booleans, vectors and other non-numeric values are dropped with a warning,
  and an entry left with nothing numeric is not written.

Params keep their values verbatim, with numpy/torch scalars unwrapped to plain
Python numbers so `params.max_depth = 3` matches.

### Custom x axis (`step_metric`)

Chart a metric against another metric instead of the step, like W&B's
`define_metric`:

```python
run.define_metric("val_*", step_metric="epoch")
for step, batch in enumerate(loader):
    ...
    if end_of_epoch:
        run.log_metrics({"val_loss": vl, "val_acc": va, "epoch": epoch}, step=step)
```

- The declaration is a log entry,
  `{"type": "define_metric", "name": "val_*", "step_metric": "epoch"}`; extra
  keyword fields ride along in the same entry. Entries fold per name, last
  write wins per field, so a resumed run can redeclare.
- The same can be declared without the SDK (for `vmn-exp run` metrics files and
  `vmn-exp add`) in the app's conf.yml metrics schema, next to `goal:`:
  `experiment.metrics.<name or glob>.step_metric: epoch`. A run's own
  declarations win over the schema, and an exact name over a glob. A metric is
  never its own x.
- **Join rule**: a point is plotted at the x metric's value logged at the *same
  step* (in the same `log_metrics` call or another call with that step);
  step-less points join only within the same call. A point with no (finite) x
  value is dropped from the joined series — the plain series is unchanged.
- Read back: `get_run(...)["step_metrics"]` maps each declaring metric to its
  x metric, and `get_run(..., x="epoch")["series"]` holds every other metric
  joined on `epoch`, each point a `{"step", "ts", "value", "x"}`.
  `vmn_exp.core.log.metric_series(log, x="epoch")` does the same on a raw log.
- The UI picks the declared x metric by default and lets you choose any
  metric; see [ui.md](ui.md#custom-x-axis).

### Tags

Tags are mutable `str -> str` labels (values are stored as strings). Each
`set_tag`/`set_tags`/`remove_tag` appends a `tags` log entry
(`{"type": "tags", "set": {...}, "remove": [...]}`); readers fold them per key,
last write wins, and a removal is a write like any other, so a removed tag can
be set again. They work on a finished run too — tag the winner after the sweep:

```python
run.set_tags({"stage": "candidate", "owner": "ann"})
run.finish()
run.set_tag("verdict", "keep")      # still recorded
```

Rows carry them as `tags` (`{key: value}`), and the query language reads
`tags.<key>` (`tags.stage = "prod"`). A `tags:` mapping (or list of labels) in a
`-f` notes file seeds them at creation.

### Alerts

`run.alert()` is `wandb.alert()`: flag something from inside the loop and get
told about it.

```python
if math.isnan(loss):
    run.alert("loss is NaN", text=f"step {step}, lr {lr}", level="error")
```

- `level` is `"info"` (default), `"warn"` or `"error"`; anything else raises
  `ValueError`.
- It appends an `alert` log entry (`{"type": "alert", "title", "text",
  "level"}`), rendered by `vmn-exp show` and listed in the dashboard's run log.
- Repeats of one title within `wait_sec` seconds (default: conf
  `experiment.alerts.wait_sec`, 60) are dropped — neither logged nor sent — so a
  check inside a loop cannot spam a channel. `wait_sec=0` sends every call. The
  return value says whether this one went through.
- It is sent to the configured sinks when the `alert` trigger is on (the
  default); delivery runs off-thread, never raises, and `finish()` waits up to
  5s for it.
- With the `failed` trigger opted in, the run also alerts when it finishes
  failed (an exception, `finish(exit_code=N)` with N != 0, SIGTERM).

Sinks (webhook, Slack, shell command), triggers and the env-var fallbacks are
configured as described in [docs/experiments.md](experiments.md#alerts). A
`NoOpRun` (non-zero rank) ignores `alert()`.

### Changing stored runs: archive, unarchive, tags

```python
from vmn_exp.sdk import manage

manage.archive_run("my_app", "@3")          # hidden from list_runs by default
manage.unarchive_run("my_app", "@3")
manage.set_tags("my_app", "latest", {"verdict": "keep"}, remove=["todo"])
```

`archive_run(app_name=None, ref="latest", *, storage=None)`,
`unarchive_run(...)` and `set_tags(app_name=None, ref="latest", tags=None, *,
remove=None, storage=None)` take any [addressing form](experiments.md#addressing-experiments),
return the verstr they changed and raise `ValueError` for a ref that names no
run. Archiving writes `archived: true` into `metadata.yml` (atomically on disk,
under the ETag on S3); unarchiving
removes it. Nothing is deleted, and nothing but listings treats an archived run
differently — `vmn-exp prune` counts and deletes it like any finished run.

---

## Autologging

`autolog()` patches a framework's training entry point so that every `fit()`
records the estimator's hyperparameters, its training score and (optionally) the
fitted model — with no logging calls in your training code:

```python
from vmn_exp.sdk import autolog, autolog_disable, start_run

autolog()                                          # every supported framework
autolog(frameworks=["sklearn"], log_models=True)   # or name them, and opt in to saving models
autolog(training_score=False)                      # calling again reconfigures
autolog_disable()                                  # restore the originals
```

| Option | Default | Meaning |
|---|---|---|
| `frameworks` | all supported | which frameworks to patch |
| `log_models` | `False` | also save each trained model as an artifact — opt-in, because it writes, hashes and copies a file per fit on the training thread |
| `training_score` | `"auto"` | record `<framework>_score`, the estimator's `score()` on its *training* data: `True`, `False`, or `"auto"` = only for inputs of at most 10,000 rows (the re-predict can cost as much as the fit) |

`autolog()` never imports a framework itself. One the script has already
imported is patched on the spot; any other is patched the moment the script
first imports it — so a scikit-learn-only script does not pay for loading
TensorFlow or torch just because they are installed.

Supported framework names, each covered by integration tests that train a real
model from the real library:

| Name | Wraps | Notes |
|---|---|---|
| `sklearn` | every estimator's `fit` | includes the meta-estimator and inherited-`fit` cases |
| `xgboost` | `XGBClassifier.fit`, `XGBRegressor.fit` | the scikit-learn wrappers only |
| `keras` | `keras.Model.fit` | Keras 3, any backend |
| `tensorflow` | the same method | `tensorflow.keras.Model` *is* `keras.Model` |
| `lightning` | `lightning.pytorch.Trainer.fit` | |
| `pytorch_lightning` | `pytorch_lightning.Trainer.fit` | a separate mirror package, so a separate patch |
| `transformers` | `Trainer.train` (via injected `VmnCallback`) | patches `transformers.trainer` lazily — `import transformers` alone never triggers it; records `params.*` on `on_train_begin` and `metrics.train/<name>` / `metrics.eval/<name>` per step on `on_log` |

Naming an unsupported — or simply uninstalled — framework is a silent no-op, so
`autolog()` is safe to call at import time in code that may run without any ML
library present.

For xgboost it is the scikit-learn wrappers that are autologged; the native
`xgboost.train` / `Booster` API is a different shape, with no estimator to ask
for hyperparameters, and is left alone. `tensorflow` and `keras` name the same
underlying function, so requesting both patches it once, not twice. Lightning's
two import names are genuinely two classes and each gets its own patch, but both
record under the `lightning_` prefix — a query must not have to care which
import the training script reached for.

**Plain `torch` is deliberately not a framework**, and no `torch` entry exists.
Raw PyTorch has no training entry point to wrap: you write the loop, so there is
no `fit()`. The candidate hooks are worse than nothing — `Module.__call__` fires
on every forward pass, `Optimizer.step` on every batch, and neither can tell an
epoch from a step or knows which loss you care about. Raw-torch users log
explicitly in their own loop, which costs two lines:

```python
with start_run("my_app", params={"lr": lr, "batch_size": 32}) as run:
    for epoch in range(epochs):
        loss = train_one_epoch(model, loader, optimizer)
        run.log_metric("train_loss", loss, step=epoch)
```

Lightning is the supported way to get the same thing autologged, because
`Trainer.fit` is the entry point raw torch lacks.

**Autologging only records inside a run you opened.** With no run open, the
patched `fit()` is a pass-through plus one debug line. It will never open a run
for you: creating a run snapshots the repository and stamps a dev version, which
is not something `fit()` gets to do behind your back. So the usage is always
`autolog()` first, then a run:

```python
autolog(log_models=True)

with start_run("my_app", note="rbf baseline") as run:
    SVC(kernel="rbf", C=2.0).fit(X, y)
    # params.sklearn_estimator = "SVC", params.sklearn_kernel = "rbf",
    # params.sklearn_C = 2.0, metrics.sklearn_score = 0.97, plus an SVC.pkl artifact
```

| Recorded | As |
|---|---|
| the estimator class name | `params.sklearn_estimator` (a meta-estimator's own `estimator` param is kept as `params.sklearn_param_estimator`) |
| every key of `estimator.get_params()` | `params.sklearn_<name>` — scalars verbatim (numpy scalars as the Python number they hold), anything else as its `repr()` with memory addresses stripped |
| `estimator.score(X, y)` on the **training** data, per `training_score` | `metrics.sklearn_score` — a training-set score flatters overfit models; prefer the CV score below |
| a search estimator's `best_score_` (`GridSearchCV`, `RandomizedSearchCV`, ...) | `metrics.sklearn_best_cv_score` |
| a search estimator's `best_params_` | `params.sklearn_best_<name>` |
| the pickled fitted estimator, when `log_models=True` | an artifact named `sklearn_<Class>.pkl`; the n-th model of the same class in one run is `sklearn_<Class>_<n>.pkl` |

What each framework can actually give up differs, so what lands differs too:

| | Keras | Lightning |
|---|---|---|
| params | `keras_estimator`, `keras_optimizer`, `keras_learning_rate`, `keras_loss_fn`, `keras_parameter_count` — read back off the compiled model | `lightning_estimator`, `lightning_max_epochs`, `lightning_precision`, plus every `LightningModule.hparams` key (so call `save_hyperparameters()`) |
| metrics | one point per epoch, `metrics.keras_loss` and one per compiled metric | the final `trainer.callback_metrics`, e.g. `metrics.lightning_train_loss` |
| step series | yes — a callback vmn appends to your `callbacks` records each epoch as it ends, with the epoch's real time and its true number (`fit(initial_epoch=3)` continues at step 3), so a run that crashes at epoch 4 keeps epochs 0–3 | no; log inside `training_step` and Lightning's own loggers keep the curve |
| `log_models=True` | `keras_<Class>.keras`, the native archive | `lightning_<Class>.ckpt` via `trainer.save_checkpoint`, restorable with `load_from_checkpoint`. **Skipped under multi-process training** (`trainer.world_size > 1`) with a warning: `save_checkpoint` ends in a barrier every rank must reach, and only the rank with an open run would call it |

Neither is pickled: a Keras model and a Lightning module full of tensors both
have a first-class save format, and pickle is not it.

Because the store folds a metric to its latest value, the last point of the Keras
epoch series *is* `metrics.keras_loss` — the curve and the headline number are
the same log, not two.

Autologged names are prefixed with the framework name and an **underscore**, not
a dot: `sklearn_kernel`, never `sklearn.kernel`. The prefix keeps autologged
values out of the way of your own, and the underscore keeps each name a single
segment, because [the query language](#the-query-language) resolves only
two-part dotted paths — `params.sklearn.kernel` would be a parse error, while
`params.sklearn_kernel` filters normally.

Three guarantees worth relying on:

- **One record per training call.** A `Pipeline` fits each step and a forest fits
  each tree, and those inner `fit()` calls are patched too — but only the
  outermost one records. So fitting a pipeline gives you
  `params.sklearn_estimator = "Pipeline"` and one model artifact, not the last
  sub-estimator's name and one pickle per step.
- **Each fit records into its own run.** A `fit()` records into the run opened
  by the same thread; a thread with no run of its own uses the process's only
  open run. So a thread-pool sweep (Optuna `n_jobs>1`) records each trial into
  its own run. A framework's worker threads (joblib's threading backend,
  `IsolationForest(n_jobs=4)`) run while the outer fit is recording and never
  record themselves, and forked worker processes never write into the parent's
  run. One consequence: while a fit is recording, a fit in *another* thread that
  opened no run of its own is not recorded — open a run in that thread.
- **Autologging never breaks training.** Every recording step is guarded; a
  failure inside it becomes a debug log line. Your `fit()` call, its return value
  and any exception it raises pass through untouched.
- **Patching is idempotent and reversible.** Each wrapper remembers the function
  it replaced, so a second `autolog()` recognizes its own work instead of
  wrapping twice (it only applies the new options), and `autolog_disable()` puts
  the exact originals back and drops any pending import hooks.

Adding a framework is one `_adapter(...)` entry in `SUPPORTED_FRAMEWORKS`, in
`vmn_exp/sdk/autolog.py`. An adapter answers the five questions the shared
recording path asks, and everything but the first defaults to the scikit-learn
answer:

| Field | Answers |
|---|---|
| `discover(module)` | which `(owner, attr)` pairs to wrap |
| `subject(call)` | which object is being trained — `call.instance` by default, the first argument for Lightning |
| `params(call)` | its hyperparameters, unprefixed — `subject.get_params()` by default |
| `metrics(call)` | its final metrics — `subject.score(X, y)` by default |
| `series(call)` | `{name: [per-step values]}`, logged one `log_metrics` per step — empty by default |
| `save(call, subject, base)` | write the model to `base + ext` and return the path (or `None` to skip) — a pickle by default |
| `instrument(call, run)` | the call to make instead, e.g. with a callback added — the call unchanged by default |
| `fitted_params(call)` | params that only exist after training — a search's `best_params_` as `best_<name>` by default |

`call` is the intercepted training call: `(instance, args, kwargs, result)`, with
`result` still `None` while params are captured before training starts. The
recording path is shared; nothing else needs a branch per framework.

---

## Finishing, failures, and the heartbeat

The context manager calls `run.finish(exit_code=0)` on the way out. You can call
it yourself when the run doesn't fit a `with` block, and it is idempotent:

```python
run = start_run("my_app")
try:
    ...
finally:
    run.finish()
```

An exception raised inside the `with` block finalizes the run as **failed** and
then **re-raises** — the SDK never swallows your error, and a crashed training
job reads as `failed` rather than as a run that just stopped logging.

**The run heartbeats itself.** `vmn-exp run` refreshes the heartbeat from the
process supervising the child; an SDK run has no supervisor — it *is* the
workload — so it carries its own daemon thread. That is what makes
[`stuck`](experiments.md#run-status-did-my-job-die) work for SDK runs: a job
that is OOM-killed or loses its node goes stale and is reported `stuck`, instead
of sitting at `running` forever with nobody left to write down that it died.

Each beat also bumps `heartbeat_seq` in `run_state.yml`. The remote copy of the
run state and the log sync are uploaded off the heartbeat thread, and only the
newest pending state is uploaded (in order, so the final state is never
overwritten by an older beat): a hung S3 PUT cannot delay the local heartbeat.

**SIGTERM finalizes the run.** A preempted job (spot reclaim, `scancel`, a
Kubernetes eviction) is sent `SIGTERM`, and `atexit` never runs for a process a
signal kills. The SDK therefore handles `SIGTERM`: it finishes every open run
with exit code `143` (`128 + 15`, so it reads `failed`, never `stuck`) and
`received_signal: SIGTERM`, syncs the log (giving up after a minute —
`VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC` changes that — so a hung store cannot keep
the process alive), and then hands the signal on — the handler
that was in place before is called, otherwise the default action is
re-delivered, so the process still dies of `SIGTERM`. With no run open it
finalizes nothing. Python lets only the main thread install a handler, so the
SDK installs it when `vmn_exp.sdk` is imported on the main thread; runs opened
later from worker threads (a thread-pool sweep) are covered. If you install
your own `SIGTERM` handler after that import, or first import the SDK from a
worker thread, call `install_signal_handlers()` from the main thread afterwards
to chain it. It is never installed over `SIG_IGN`. With several runs open,
every run's final state is written locally first and their uploads then share
that one wait, so a hung store cannot leave the later runs `stuck`; the same
holds at interpreter exit.

**A flaky store never becomes your error.** `finish()` does not raise for a
storage failure (a remote that returns 503 at the end of a ten-hour run is logged
as a warning, not thrown at the workload), and it always closes the run — the
run leaves the open-run registry and the environment is handed back regardless.
An exception from your own code inside the `with` block is re-raised unchanged;
a storage error while recording it is logged, never substituted for it.

### Resuming a preempted run

A requeued job should continue the run it was rather than start a new one:

```python
run = start_run("my_app", run_id=saved_run_id)
# or set VMN_RESUME_RUN_ID=<verstr> in the requeued job's environment
```

The run is reopened — same verstr, `state: running` again with this process's
pid/host, heartbeating — and new entries are appended to its log (this process
writes its own log segment; readers merge them). `started_at` is kept, so
`duration_sec` spans every attempt; `resume_count` and `resumed_at` record the
restarts. A `note`/`params` passed on resume is appended as a note/params entry.
A reference that matches no experiment of the app raises `ValueError`.
`$VMN_RESUME_RUN_ID` is consumed (removed from the environment) when used, so
neither the next run this process opens nor a vmn subprocess resumes it again;
an explicit `run_id` wins over it.

### Distributed training (DDP, torchrun, Slurm)

Every rank of a distributed job runs the same script. On a non-zero rank —
`RANK > 0`, or (without `RANK`) `LOCAL_RANK > 0` with `WORLD_SIZE > 1`, or
`SLURM_PROCID > 0` — `start_run()` returns a `NoOpRun`: the same interface
(`log_metric`, `log_params`, `finish`, `with` ...), recording nothing, with no
heartbeat thread and no git or storage access. It is never registered as open,
so `current_run()` is `None` there and autologging records nothing. Rank 0
records as usual and exports `VMN_EXPERIMENT_ID`. Pass `all_ranks=True` to
record on every rank.

---

## Nesting

`nested=True` parents the new run to the calling context's run — the innermost
run opened by this thread that is still open (else the process's only open run):

```python
with start_run("my_app", note="lr sweep") as sweep:
    for lr in (1e-4, 3e-4, 1e-3):
        with start_run("my_app", nested=True, params={"lr": lr}) as trial:
            trial.log_metric("loss", train(lr))
```

In one process it is belt-and-braces: an open run exports `VMN_EXPERIMENT_ID`
into its own environment, so the inner `start_run` would have found the parent
anyway. Pass it when you want the parenting to be explicit in the code, or when
the enclosing run may have been started elsewhere.

Otherwise `VMN_EXPERIMENT_ID` is honored exactly as the CLI honors it, and the
SDK **exports** it while a run is open — so any subprocess you launch auto-links
as an inner run:

```python
with start_run("my_app", note="lr sweep"):
    for lr in (1e-4, 3e-4, 1e-3):
        subprocess.run(["vmn", "exp", "run", "my_app", "--", "python", "train.py", "--lr", str(lr)])
```

Either way you get the same outer/inner structure — including `kind` and the
`tree_status` rollup — that a [CLI sweep](experiments.md#outer--inner-jobs-sweeps)
produces.

### Sweep trials: `sweep_params()`

Inside a trial that [`vmn-exp sweep agent`](sweeps.md) launched,
`from vmn_exp.sdk import sweep_params` returns the trial's params (a fresh dict
from `$VMN_SWEEP_PARAMS`; `{}` outside a sweep). Report the sweep's metric
through `$VMN_METRICS_FILE`: a `start_run()` in the trial opens a nested run,
whose metrics the sweep does not read.

### Threads, forks and `current_run()`

`from vmn_exp.sdk.run import current_run` returns the run the calling code
should record into, or `None`:

1. the run the calling context (thread) opened, if it is still open;
2. else the process's only open run;
3. else `None` — several runs are open and none belongs to this context.

That is what keeps concurrent runs in one process apart:

- **Thread-pool sweeps** (Optuna `n_jobs>1`, a `ThreadPoolExecutor`): trials that
  each call `start_run()` in their own thread are independent siblings. The
  exported `VMN_EXPERIMENT_ID` names whichever run opened last, but a run another
  thread of this process has open is never taken as a parent — only the value the
  process was *launched* with (an enclosing `vmn-exp run`) is. Once every run has
  finished, in whatever order, the environment is exactly what it was before the
  first one opened. To nest a trial under an outer run opened by another thread,
  pass `parent=outer.id`.
- **Forks** (`multiprocessing` with `fork`, DataLoader workers): a child inherits
  the parent's `Run` objects but not the runs. `current_run()` is `None` there, and
  the child's interpreter exit never finalizes the parent's still-running run.
  Every `Run` records its owning process as `run.pid`. A child that calls
  `start_run()` itself becomes an inner run of the parent via the inherited
  `VMN_EXPERIMENT_ID`, exactly like a subprocess.

---

## Reading runs back

```python
from vmn_exp.sdk.reader import get_run, list_runs

for run in list_runs("my_app", last=10, status="succeeded"):
    print(run["verstr"], run["metrics"])

for run in list_runs("my_app", query='metrics.loss < 0.5 and params.optimizer = "adam"'):
    print(run["verstr"])

best = get_run("my_app", ref="latest")
```

- `list_runs(app_name=None, *, storage=None, sort=None, last=None, status=None,
  query=None, use_index=True, include_archived=False)` — archived runs are
  left out unless `include_archived=True`; `sort` picks the metric to order by (the configured [primary
  metric](experiments.md#metrics-schema-sorting--goals) when omitted), `last`
  caps the result count, `status` filters to one derived status, and `query` is
  [the query language](#the-query-language). A bad query raises `QueryError`.
  Everything after `app_name` is keyword-only, so a query passed positionally
  cannot be mistaken for `storage`.
- `get_run(app_name=None, ref="latest", *, storage=None, x=None)` — `ref` takes any
  [addressing form](experiments.md#addressing-experiments): a full verstr, a
  unique prefix, `@N`, or `latest`. `x="epoch"` joins `series` on that metric
  (see [Custom x axis](#custom-x-axis-step_metric)); the row's `step_metrics`
  lists the declared x metrics.

A `list_runs` row carries the latest value of each metric, the run's `name`
(or `None`), its current `tags` and `archived` (a bool). `get_run` adds the record's
`format_version` (1 for runs written before it existed); runs written in a
newer format than the installed SDK reads are left out of both, with a
warning (see [How records are stored](experiments.md#how-records-are-stored)). To read a metric's
whole history, ask for the run itself — `get_run(...)["series"]` maps each metric
name to its points in log order, each a `{"step": ..., "ts": ..., "value": ...}`.

### As pandas DataFrames

```python
from vmn_exp.sdk.reader import get_metric_history, runs_dataframe

df = runs_dataframe("my_app", query="metrics.loss < 0.5", status="succeeded")
df.sort_values("metrics.loss").head()

loss = get_metric_history("loss", "my_app", ref="@3")   # columns: step, timestamp, value
```

Needs pandas: `pip install "vmn-exp-sdk[pandas]"` (without it both raise an
`ImportError` naming that extra).

- `runs_dataframe(app_name=None, **list_runs_kwargs)` — the `list_runs` rows as
  one flat DataFrame, like `mlflow.search_runs()`. It takes every `list_runs`
  keyword (`storage`, `query`, `status`, `sort`, `last`, `include_archived`, ...),
  so filtering stays in the query language rather than a second API. Columns:
  `run_id` (the verstr), `idx`, `name`, `status`, `kind`, `parent`,
  `tree_status`, `timestamp`/`started_at`/`finished_at` (UTC datetimes),
  `duration_sec`, `exit_code`, `host`, `branch`, `code_verstr`, `note`,
  `archived`, then `metrics.<k>`, `params.<k>`, `tags.<k>` and `inputs.<name>`
  (the input's URI), each group sorted. A run missing a value reads `NaN`/`None`.
  `metrics.<k>` is the same fold the query language's `metrics.<k>` sees, so
  numeric params appear there too.
- `get_metric_history(metric, app_name=None, ref="latest", *, storage=None)` —
  every logged value of one metric in one run, in log order (`step` is `None`
  where none was logged); empty when the run never logged it. The metric comes
  first because it is the only argument without a default.

A separate function rather than `list_runs(output="pandas")`: one return type
per function keeps `list_runs` free of a pandas code path and type-checkable.

`vmn-exp list`, the ui and `list_runs()` read through an incremental index
(`list_runs(..., use_index=False)` reads storage directly and writes no index
file): the folded
rows persist in `.vmn/<app>/experiments/.index.sqlite`, next to the records
(the directory's own `.gitignore` keeps it out of `git status`). A call lists
the record files once and re-reads only what changed since the last one — the
new lines of a grown log, a rewritten `run_state.yml` — so listing thousands of
runs stays cheap while they train. It is a disposable cache: delete it any time,
and if it cannot be opened (read-only disk, corrupt file) the rows are read
directly. Status is still derived on every call.

`get_run` always goes through the index to resolve `@N`/`latest`/prefixes and
to find the run's place in the tree; it then reads just that run — its
metadata, log and artifacts, and the run states of its own subtree.

As on the write side, `app_name=None` resolves from the current repo.

---

## The query language

One small expression language filters experiment rows, shared by the SDK reader
and the [REST API](ui.md#filtering-with-a-query) so they select identically:

```
metrics.loss < 0.5 and status = "succeeded"
status in ("running", "stuck")
note ~ "baseline"
params.optimizer = "adam" and not params.frozen = true
metrics.acc >= 0.9 and (kind = "inner" or depth = 0)
```

**Operators**

| Form | Means |
|---|---|
| `=` `==` `!=` | equality. Types must match: a number never equals a string, `true` never equals `1` |
| `<` `<=` `>` `>=` | ordering, for two numbers or two strings. Mixed types simply don't match |
| `~` / `contains` / `!~` | case-insensitive substring; the right-hand side must be a string. Against a list field (`command`, `children`) it matches any element — `command ~ "train.py"` — and against `user_meta` any value |
| `in (…)` / `not in (…)` | membership in a literal list |
| `and` `or` `not`, `(…)` | the usual, `not` binding tightest |

Literals are numbers, quoted strings (either quote), `true`, `false`, `null`.
Numbers are integers, decimals or scientific notation (`1e-4`, `2.5E+3`), so
`params.lr = 1e-4` works as written. Keywords and operators are case-insensitive (`AND`, `Contains`); **field names
are case-sensitive**, so `STATUS = "failed"` is an error, not an empty result.
`not` and parentheses nest at most 100 levels deep (deeper is a `QueryError`);
`and`/`or` chains can be any length.

**Fields**

- Bare row keys — `status`, `verstr`, `note`, `branch`, `exit_code`,
  `duration_sec`, `idx`, `timestamp`, `parent`, `kind`, `depth`, `tree_status`,
  `pid`, `host`, `command`, and the rest of what a row
  [carries](ui.md#experiment-status-fields). An unknown name is a query error,
  so a typo tells you instead of returning nothing.
- `metrics.<name>` — a numeric metric.
- `params.<name>` — a param, as it was recorded.
- `tags.<key>` — a tag, always a string (`tags.stage = "prod"`); a removed or
  never-set tag is missing. Keys the query can name are letters, digits and `_`.
- `name` (`name ~ "sweep"`, `name = null` for unnamed runs) and `archived`
  (`archived = true` — only meaningful with `include_archived=True`, since the
  default listing drops archived rows first).

`metrics` and `params` read different dicts, and the difference matters:
**`metrics` holds numeric values only** (params that parse as finite, non-boolean
numbers are folded in, since sorting, leaderboards and charts need numbers — so
`missing=nan` or `verbose=True` never become metrics), while **`params` holds
every param verbatim**. So `params.model = "xgb"` and `params.cache = true` work
and `metrics.model` does not, while a numeric param resolves under both
`params.lr` and `metrics.lr`.

**Missing fields** are two-valued, not SQL's `UNKNOWN`: a comparison against an
absent or `None` field is simply false, so a query and its `not` always partition
the rows exactly. `= null` is how you ask for absence — and `!= x` is therefore
true for a run that has no `x` at all.

An invalid query raises `QueryError` with the offending character offset
(`unknown field 'statuz' at offset 0`). Over HTTP the same message comes back as
a 400. Nothing is ever `eval`'d: the implementation is a hand-written lexer plus
recursive-descent parser in `vmn_exp/core/query.py`.

On the command line the same expressions go to `vmn-exp list <app> --query
'<expr>'` (see [experiments.md](experiments.md#list)).

---

## Model registry

The model registry links named, versioned model identifiers to the experiment
runs and artifact paths that produced them. The registry lives in the same
storage root as experiment runs (under the reserved pseudo-app `vmn-registry`),
so no extra infrastructure is needed.

```python
from vmn_exp.sdk import start_run, register_model, get_model_version, download_model

# Register during (or after) a run
with start_run("my_app") as run:
    run.log_artifact("weights.pt")
    run.register_model("resnet50", artifact_path="weights.pt", alias="staging")

# Or register after the run is closed
meta = register_model("resnet50", run=run, artifact_path="weights.pt")
print(meta["n"])          # version number, e.g. 1
print(meta["run_ref"])    # {"app": "my_app", "verstr": "1.6.0-dev.a1b2c3d..."}
```

### Resolving a model version

Refs have four forms:

| Ref | Resolves to |
|-----|-------------|
| `model` | Latest non-deleted version |
| `model@latest` | Same |
| `model@3` | Version number 3 |
| `model@alias` | Version the alias currently points to |

```python
from vmn_exp.sdk import get_model_version, set_alias, remove_alias

meta = get_model_version("resnet50@staging")
meta = get_model_version("resnet50@2")
meta = get_model_version("resnet50")     # latest

set_alias("resnet50", "production", 2)           # move alias
set_alias("resnet50", "production", 3, expect=2) # only if currently at v2
remove_alias("resnet50", "staging")
```

### Downloading artifacts

```python
from vmn_exp.sdk import download_model

path = download_model("resnet50@production")         # returns local path
path = download_model("resnet50@production", dst="/tmp/models")  # copy to dir
```

Local storage returns the on-disk path directly. S3 storage downloads the
artifact to a temporary cache directory.

### Listing models

```python
from vmn_exp.sdk import list_models

print(list_models())   # e.g. ["bert-base", "resnet50"]
```

### Storage resolution

All model registry functions accept an optional keyword argument `storage=` for
passing an explicit storage object. When omitted, storage is resolved the same
way as experiment runs:

1. `VMN_SNAPSHOT_METADATA` set → container/snapshot mode
2. `VMN_EXPERIMENT_DIR` set → that directory
3. Otherwise → the current git checkout's `.vmn` root

The local root found this way fronts the remote store, if any:
`VMN_EXPERIMENT_STORE` (a URI; `resolve_experiment_storage(store=...)` in code),
else the `VMN_EXPERIMENT_BUCKET`/`_PREFIX`/`_ENDPOINT_URL` shorthand for `s3://`.
With no local root the store is used directly; a `file://` store *is* the root.
The URI scheme picks the backend from the registry in `vmn_exp.storage.registry`
(built-ins `file`, `s3`, `gs`, `az`; plugins via the `vmn_exp.storage`
entry-point group). A backend whose SDK is missing raises `ImportError` naming
the extra to install, e.g. `pip install 'vmn-exp-sdk[gcs]'`.

---

## Integrations

Higher-level wrappers for specific ML frameworks and experiment-management
libraries.  Each integration lives in `vmn_exp.integrations.*` and is separate
from autologging: autolog patches the framework's training entrypoint
automatically; integrations are explicit helpers you call when you need more
control.  They need the library they wrap (`transformers`, `optuna`,
`ray[tune]`), which you install yourself; vmn never pulls in a framework.

### Hugging Face Transformers — `VmnCallback`

`VmnCallback` records Trainer params and per-step train/eval metrics.  It is
injected automatically when `autolog()` is active; you can also attach it
manually without calling `autolog()`:

```python
from vmn_exp.integrations.hf import VmnCallback
# VmnCallback is assembled lazily — transformers is NOT imported by this line

from transformers import Trainer, TrainingArguments
from vmn_exp.sdk import start_run

with start_run("my_app") as run:
    trainer = Trainer(
        model=model,
        args=TrainingArguments(...),
        callbacks=[VmnCallback()],
    )
    trainer.train()
    # params.learning_rate, metrics.train/loss, metrics.eval/f1, … are recorded
```

`VmnCallback` only records on rank 0 (world_process_zero).  Checkpoint artifacts
are saved when `log_models=True` is passed to `autolog()`; the manual callback
does not save checkpoints by default.

For `autolog("transformers")` behaviour see the [Autologging](#autologging)
section above.

### Optuna — `start_study_run` + `StudyTracker`

`start_study_run` opens an outer run for an Optuna study and returns a
`StudyTracker`.  Each trial maps to an inner run with the study's run as its
parent, so the tree view in `vmn-exp ui` shows one row per sweep with all trials
nested under it.

```python
import optuna
from vmn_exp.integrations.optuna_study import start_study_run
from vmn_exp.sdk import autolog

autolog()   # autolog records into whatever run is active on each thread

def objective(trial):
    lr = trial.suggest_float("lr", 1e-4, 1e-1, log=True)
    # ... train ...
    return val_loss

study = optuna.create_study(direction="minimize")
tracker = start_study_run(study, app_name="my_app", name="lr_sweep")

study.optimize(tracker.wrap(objective), n_trials=20, n_jobs=4)
tracker.finish()   # records best trial metrics on the outer run
```

`tracker.wrap(objective)` returns a new callable that opens an inner run before
calling `objective` and closes it afterwards.  With `n_jobs > 1` (thread-pool
parallelism), each trial thread gets its own inner run; `autolog()` records into
the thread's current run automatically.

Pruned trials (`optuna.TrialPruned`) are recorded as `succeeded` with
`tag state=pruned` and the exception is re-raised so Optuna marks the trial
`PRUNED`.

### Ray Tune — `TuneRecorder` + `VmnTuneCallback`

The Ray integration is driver-side only (D20 decision): it records trial outcomes
from the driver process that calls `tune.run`.  Worker-side autolog is deferred.

```python
from vmn_exp.integrations.ray_tune import TuneRecorder, make_callback
import ray.tune as tune
from vmn_exp.sdk import start_run

recorder = TuneRecorder(app_name="my_app", experiment_name="lr_sweep")

analysis = tune.run(
    trainable,
    config={"lr": tune.grid_search([1e-3, 3e-4, 1e-4])},
    callbacks=[make_callback(recorder)],
)
recorder.finish()
```

`TuneRecorder` creates one outer run on the first `on_trial_start` event and one
inner run per trial.  Ray's bookkeeping keys (`config`, `timestamp`, `pid`, …)
are stripped; the rest of each result dict is logged as metrics.  The outer run's
`tree_status` rolls up to `failed` if any trial failed.

See also: [docs/models.md](models.md) for registering the model after a sweep.

---

## Library logging

The SDK emits stdlib `logging` records under the `vmn_exp.sdk` logger and
never configures handlers — it is a library, so what happens to the records is
your application's call. To see its debug output:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```

---

## Slim install

For recording-only environments (container images, CI workers, air-gapped
training jobs), install just the metrics writer:

```sh
pip install vmn-exp-sdk           # + [s3]/[gcs]/[azure] to record to a bucket; pynvml for GPU sys_* metrics
```

`vmn-exp-sdk` is `vmn_exp.sdk` plus the storage, registry and record helpers it
needs. It depends only on `PyYAML`, `filelock` and `psutil`: no vmn, no GitPython, no git
binary. Creating a run from a git checkout (cold start, snapshot capture), the
`vmn-exp` CLI and the dashboard live in `vmn-exp`, which depends on this
package; in a slim install, `start_run()` in a checkout fails with a pointer to
`pip install vmn-exp`. See [packaging.md](packaging.md) for how the three
packages split.

### Git-free recording

With `VMN_SNAPSHOT_METADATA` pointing to the `vmn_metadata.yml` that
`vmn-exp export` writes (baked into your image) and `VMN_EXPERIMENT_DIR`
pointing to a writable directory, `start_run()` works with no git checkout and
no GitPython installed:

```python
import os

os.environ["VMN_SNAPSHOT_METADATA"] = "/opt/model/vmn_metadata.yml"
os.environ["VMN_EXPERIMENT_DIR"]    = "/mnt/experiments"

from vmn_exp.sdk import start_run

with start_run(app_name="my_model") as run:
    run.log_metric("accuracy", 0.91)
```

Reads work the same way:

```python
from vmn_exp.sdk.reader import list_runs

runs = list_runs("my_model")
print(runs[0]["verstr"], runs[0]["metrics"])
```
