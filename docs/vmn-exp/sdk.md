# Python SDK

`vmn_exp.sdk` is the in-process Python API for [experiment
tracking](experiments.md). It records the same runs the CLI does (same
snapshot, same verstr, same files) without a wrapper command or a metrics file.

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

The SDK ships in `vmn-exp-sdk` (depends only on PyYAML, filelock and psutil).
Recording from a git checkout also needs `vmn-exp`, which provides snapshot
capture; git-free jobs need only the SDK (see [Slim install](#slim-install)).
For a task-by-task walkthrough see [client-guide.md](client-guide.md).
Runnable scripts (minimal run, training loop, nested sweep, queries,
autologging) live in [`examples/`](../../examples/README.md); they record to the
app `vmn_examples`.

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
- [Environment variables](#environment-variables)
- [Library logging](#library-logging)
- [Slim install](#slim-install)

Public names in `vmn_exp.sdk`: `start_run`, `Run`, `NoOpRun`, `current_run`,
`install_signal_handlers`, `autolog`, `autolog_disable`, `sweep_params`, and the
registry functions `register_model`, `set_alias`, `remove_alias`,
`get_model_version`, `list_models`, `download_model`, `register_dataset`,
`get_dataset_version`, `use_model`, `use_dataset`. Readers live in
`vmn_exp.sdk.reader`, run management in `vmn_exp.sdk.manage`, integrations in
`vmn_exp.integrations.*`.

---

## CLI or SDK?

| Situation | Use |
|---|---|
| Wrapping a script you don't want to modify | `vmn-exp run my_app -- python train.py` |
| A non-Python workload | `vmn-exp run` + `$VMN_METRICS_FILE` |
| Per-step metrics from inside Python | `start_run(...)` |
| Metrics you measured by hand | `vmn-exp create … --metrics k=v` |

**An SDK run is indistinguishable from a CLI run on disk**: same verstr scheme,
`metadata.yml`, per-writer JSONL log and `run_state.yml`. `vmn-exp
list/show/compare`, the dashboard and remote sync work on SDK runs unchanged,
and mixing the two is fine (`vmn-exp add` a number to a run your script opened).

One difference: an SDK run records `sys.argv` as its command, with `runner:
sdk`. So [`vmn-exp rerun`](experiments.md#rerun) needs the command spelled out
(`vmn-exp rerun my_app -v <ref> -- python train.py`), and the script's
`start_run()` then opens an inner run of the rerun record.

---

## Starting a run

```python
start_run(
    app_name=None, note=None, params=None, parent=None, nested=False,
    heartbeat_interval_sec=None, storage=None, system_metrics=None,
    sync_interval_sec=30, run_id=None, all_ranks=False, name=None, tags=None,
    capture_env=None, fork_from=None, fork_step=None, rewind_to_step=None,
    capture_output=False, mode=None,
)
```

| Argument | Means |
|---|---|
| `app_name` | app to track under. `None`: `$VMN_APP_NAME` (which `vmn-exp run` exports to its child), else the checkout's only stamped app (else `ValueError`) |
| `note` | free-text note |
| `params` | the run's inputs (like `-f params.yml`'s `params:`) |
| `parent` | parent run, in any [addressing form](experiments.md#addressing-experiments) (verstr, unique prefix, `@N`, `latest`); an unknown one raises `ValueError` |
| `nested` | parent to the calling context's open run (see [Nesting](#nesting)) |
| `heartbeat_interval_sec` | beat cadence, default 30 s; also the `sys_*` sampling interval |
| `storage` | a storage backend; default the app's configured one. Build one with `vmn_exp.core.storage_resolve.resolve_experiment_storage(store="s3://…")` (also takes `dir=`, `bucket=`, `prefix=`, `endpoint_url=`) |
| `system_metrics` | `None`: sample `sys_*` unless opted out (below); `False`: off; `True`: on despite conf.yml, still off under `VMN_SYSTEM_METRICS=0` |
| `sync_interval_sec` | push new log lines to the remote store at most this often, off the heartbeat thread, so a killed job still leaves its metrics remotely. `None`/`0`: only at `finish()`. Failed syncs are retried on a later beat |
| `run_id` | reopen an existing run instead of creating one; falls back to `$VMN_RESUME_RUN_ID`. See [Resuming](#resuming-a-preempted-run) |
| `rewind_to_step` | with `run_id` (required): hide the run's history past this step. See [Rewinding](#rewinding-a-run) |
| `fork_from` / `fork_step` | a NEW run seeded with another run's history up to `fork_step` (`"<ref>?_step=N"` works too). See [Forking](#forking-a-run) |
| `all_ranks` | record on every rank; default only rank 0 (see [Distributed training](#distributed-training-ddp-torchrun-slurm)) |
| `name` | human-readable name: `run.name`, shown by `vmn-exp list`, queryable (`name ~ "sweep"`) |
| `tags` | `{key: value}` [tags](#tags) set as the run opens |
| `capture_env` | `None`: capture Python version, platform and installed packages unless opted out (`VMN_CAPTURE_ENV=0` > conf `experiment.capture_env: false`); `False`: skip; `True`: capture despite conf.yml, not despite the env var. A resumed run keeps its original env |
| `capture_output` | tee fds 1/2 (so `print`, logging, C extensions and subprocesses) into the run's [`output.log`](experiments.md#console-output-outputlog) artifact, capped by `$VMN_EXP_OUTPUT_CAP_MB` (default 10; head and tail kept), uploaded every `sync_interval_sec` and at finish. Off by default: the process then writes to pipes, not its TTY, which debuggers and notebooks may not expect. Leave it off under `vmn-exp run`, which captures already |
| `mode` | `None`: follow `$VMN_MODE`; `"disabled"`: record nothing ([Disabled mode](#disabled-mode)); `"enabled"`: record even under `VMN_MODE=disabled`. Anything else raises `ValueError` |

Calling `start_run()` again on a thread whose run is still open (a re-run
notebook cell that never called `finish()`) raises `RuntimeError`; pass
`nested=True` to nest on purpose, or finish the old run first.

Creating the run snapshots the working tree (dirty or clean) and assigns
`run.id`. The first run in a repo vmn does not track yet cold-starts it: it
commits vmn's init files and tags `<app>_0.0.0` **locally, never pushing**
(`git push --follow-tags` when you want to share them). That annotated tag
needs a git identity (`user.name`/`user.email`, or `GIT_AUTHOR_*`/
`GIT_COMMITTER_*` in a container). A remote is optional; its URL is recorded
when there is one.

The repo lock (`.vmn/vmn.lock`) is held only for the cold start and the verstr
claim. The snapshot (diff, format-patch, untracked tarball) is captured before
the lock, so sweep trials started together capture in parallel, and the code is
stored once per code identity, so trials of an unchanged tree upload only their
own records ([How records are stored](experiments.md#how-records-are-stored)).
The lock is released before your training code runs.

With `VMN_EXP_OFFLINE=1` the run records to the local root only, for a later
[`vmn-exp push`](experiments.md#offline-recording-and-push).

### System metrics

On by default here and on `vmn-exp run` (which measures the child's process
tree instead). Opt out, strongest first: `system_metrics=False` /
`--no-system-metrics`, `VMN_SYSTEM_METRICS=0` (or `false`/`no`/`off`), conf
`experiment.system_metrics: false`. Inside a `vmn-exp run` that already samples
its child (`VMN_EXP_SUPERVISOR_SAMPLES` is set), `start_run()` defaults to off;
`system_metrics=True` samples anyway.

Samples are taken once per heartbeat (a run shorter than one beat records
none), carry no step, and are skipped on non-zero ranks. GPU metrics need
`pip install pynvml`; a missing sampler dependency only logs at debug.

| Metric | Meaning |
|---|---|
| `sys_cpu_percent` | CPU of the process tree, summed (>100 on several cores) |
| `sys_rss_mb` | the root's RSS plus each child's unique memory (USS), so forked workers sharing pages are not counted N times |
| `sys_gpu_mem_mb` | GPU memory held by the tree's own processes; omitted when NVML lists none of them (e.g. in a container, where NVML reports host pids) |
| `sys_gpu_node_mem_mb` | used memory on the visible GPUs, all processes |
| `sys_gpu_node_util_percent` | mean utilization over the visible GPUs, all processes |

"Visible" follows `CUDA_VISIBLE_DEVICES` (indices or UUIDs). An NVML query a
device does not support (utilization under MIG) drops that value only.

### Runs without a git checkout (containers)

An image built from [`vmn-exp export`](experiments.md#export) has no `.git`.
Set `VMN_SNAPSHOT_METADATA` to the exported `vmn_metadata.yml` (or its
directory) and `start_run()` records against that code, like the CLI's
`--from-snapshot`. The app defaults to the one the metadata names.

```python
# VMN_SNAPSHOT_METADATA=/app/vmn_metadata.yml  VMN_EXPERIMENT_DIR=/mnt/runs
with start_run() as run:
    run.log_metric("loss", 0.25)
```

Where it records:

- `VMN_EXPERIMENT_DIR` — a local (or NFS) root. Concurrent workers sharing it
  serialize the verstr claim on a lock inside it.
- `VMN_EXPERIMENT_STORE` — a [store URI](experiments.md#storage-local-s3-gcs-azure-plugins)
  (`s3://`, `gs://`, `az://`, `file://`, plugins).
  `VMN_EXPERIMENT_BUCKET`/`_PREFIX`/`_ENDPOINT_URL` are shorthand for `s3://`;
  the store wins over them.
- Both: entries go to the local dir and new lines sync to the store every
  `sync_interval_sec`. Store alone: the run writes straight to it.
- Neither (and no `storage=`): `ValueError`.

Readers do not read these variables; pass them a storage, e.g.
`list_runs("my_model", storage=resolve_experiment_storage())` (see
[Reading runs back](#reading-runs-back)).

---

## Logging

Every call appends to the run's log; nothing is rewritten.

| Call | Records |
|---|---|
| `log_metric(key, value, step=None, commit=True)` | one metric at `step` (default `run.step`; see [Steps](#steps)) |
| `log_metrics({...}, step=None, commit=True)` | several metrics sharing one step |
| `log_params({...})` | more inputs, merged into the run's params |
| `log_input(uri, name=None, digest=None, kind=None)` | a dataset/artifact the run consumed; `name` defaults to the URI basename without extension; folded last-write-wins by name |
| `use_artifact(ref, path, name=None, app_name=None)` | consume artifact `path` of another run and return a local path to it (downloaded when remote). Records an input `vmn://<app>/<verstr>/<path>` with the artifact's digest and `kind="artifact"` ([Lineage](#lineage)). `ValueError` if that run logged no such artifact |
| `log_note(text)` | a note |
| `log_artifact(path, name=None)` | a file, stored as `name` (a relative `a/b/c.txt` path) or its basename |
| `log_artifacts(local_dir, prefix=None)` | every file under `local_dir`, named by its relative path (under `prefix`) |
| `log_dict(obj, name)` | JSON or YAML by `name`'s extension (`.json`/`.yaml`/`.yml`, else `ValueError`) |
| `log_text(text, name)` | a text file |
| `log_figure(fig, name, **savefig_kwargs)` | anything with `savefig` (format from `name`); matplotlib is not imported |
| `log_table` / `log_image` / `log_histogram` | see [Tables, images and histograms](#tables-images-and-histograms) |
| `set_tag(key, value)` / `set_tags({...})` / `remove_tag(key)` | mutable [tags](#tags) |
| `define_metric(name, step_metric=None, summary=None, goal=None, hidden=None)` | how a metric (or `fnmatch` glob) is charted, ranked and shown: [x axis](#custom-x-axis-step_metric), [goals and summaries](#metric-goals-and-summaries) |
| `alert(title, text="", level="info", wait_sec=None)` | an [alert](#alerts) |
| `register_model(...)`, `use_model(ref)`, `use_dataset(ref)` | [registry](#model-registry) shortcuts bound to this run |

`Run` attributes: `id` (verstr), `app_name`, `name`, `step`, `start_step` (the
step a fork/rewind continues from, else `None`), `pid` (the owning process),
`disabled`.

Artifact names may be nested relative paths; absolute paths, `..`, `.`, empty
components, backslashes and NUL raise `ValueError` (`log_artifacts` checks every
name before uploading any). Each entry records `path`, `size` and `sha256`.

**Writes are batched.** Log calls queue in memory and are written as whole
lines at most ~1 s apart, at 1000 pending entries, on every heartbeat and at
`finish()`/SIGTERM/exit (before the final state, so a reader that sees a run
finished sees everything it logged). A reader never sees half a line, and live
readers (`vmn-exp show`, the UI) see a metric within about a second. A forked
child writing through an inherited `Run`, or a write after `finish()`, goes
straight to the store.

Metric values are stored as floats:

- numpy scalars, 0-d arrays and 0-d torch tensors are unwrapped (no `.item()`
  needed); numeric strings like `"0.5"` are parsed;
- `nan`/`inf` are kept (a diverged loss is a result) and sort last;
- booleans, vectors and other non-numeric values are dropped with a warning;
  an entry left empty is not written.

Params are kept verbatim, with numpy/torch scalars unwrapped so
`params.max_depth = 3` matches.

### Tables, images and histograms

Keyed by `name` and `step` (default: one past the name's last step logged by
this process, so pass `step=` when resuming; explicit steps must be
non-negative ints). The run page's **Media** section shows them.

```python
run.log_table("preds", [{"y": 1, "p": 0.9}, {"y": 0, "p": 0.2}], step=epoch)
run.log_table("preds", [[1, 0.9], [0, 0.2]], columns=["y", "p"], step=epoch)
run.log_table("preds", df, step=epoch)              # a pandas DataFrame
run.log_image("samples", batch[0], step=epoch, caption="first batch")
run.log_histogram("fc1.weight", model.fc1.weight, step=epoch)
```

| Call | Accepts | Stored as |
|---|---|---|
| `log_table(name, data, columns=None, step=None)` | list of dicts (columns in first-seen order), list of lists / 2-D array plus `columns=`, or a DataFrame | `tables/<name>/<step>.json`: `{"columns": [{"name", "type"}], "data": [[column values]], "rows", "truncated"}` |
| `log_image(name, image, step=None, caption=None)` | file path, PIL image, numpy `HxW`/`HxWxC` (C = 1-4; `uint8`, or floats in 0..1), matplotlib figure | `media/<name>/<step>.png` |
| `log_histogram(name, values, step=None, bins=64)` | anything numpy can flatten, or a precomputed `{"bins": edges, "counts": counts}` (`len(bins) == len(counts) + 1`) | a `histogram` log entry only |

- Tables keep at most 10,000 rows (truncated with a warning, `total_rows`
  recorded); cells are made JSON-safe (NaN/inf → `null`, objects → `str`).
- Images need no Pillow: arrays go through a stdlib PNG encoder. Without
  Pillow, a non-PNG file is stored as is under its own extension.
- Histograms bin only finite values (numpy if installed, else pure Python, same
  edges); with none, nothing is logged.
- Images and tables are **outputs** of the run: their entry carries the stored
  bytes' `sha256`/`size`, so they appear in `outputs`, link in
  [lineage](#lineage), and `use_artifact(ref, "media/samples/3.png")` fetches
  one. Files upload on a background worker, and the entry is logged only once
  the file is stored (keeping the call's step and timestamp). A file that fails
  to store, or is still queued when the final upload wait
  (`VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC`) runs out, is never recorded.

`get_run()` adds `media`, `tables` and `histograms` (name → steps, latest entry
per step wins) and `histograms_total`; `histograms` keeps at most 100 evenly
spaced steps per name, first and last included.

### Custom x axis (`step_metric`)

Chart a metric against another metric instead of the step (W&B's
`define_metric`):

```python
run.define_metric("val_*", step_metric="epoch")
run.log_metrics({"val_loss": vl, "val_acc": va, "epoch": epoch}, step=step)
```

- A point is plotted at the x metric's value logged at the **same step**;
  step-less points join only within one call. Points without a finite x are
  dropped from the joined series.
- Declare it without the SDK in conf.yml: `experiment.metrics.<name or
  glob>.step_metric: epoch`. The run's declaration wins, an exact name beats a
  glob, and a metric is never its own x.
- `get_run(...)["step_metrics"]` maps each declaring metric to its x;
  `get_run(..., x="epoch")["series"]` joins every other metric on `epoch`
  (points `{"step", "ts", "value", "x"}`). The UI picks the declared x by
  default ([ui.md](ui.md#custom-x-axis)).

### Metric goals and summaries

A metric logged every epoch folds to one number per run, by default the last.
`define_metric()` picks another:

```python
run.define_metric("val_loss", goal="min")        # rank on the best (lowest) epoch
run.define_metric("lr", summary="last")
run.define_metric("grad_*", hidden=True)         # out of the UI's default columns
```

- `summary`: `"min"`, `"max"`, `"last"`, `"first"` (earliest) or `"mean"` (of
  finite values). Without it, `goal="min"`/`"max"` implies it. Anything else
  (including `"none"`) raises `ValueError`.
- `hidden` (a bool) is display-only: the metric still sorts, queries and
  summarizes.
- The declaration is a `define_metric` log entry, so it travels with the run
  and needs no conf.yml; later declarations override per field.
  `vmn-exp add <app> -v <ref> --define-metric NAME [--goal] [--summary]
  [--step-metric] [--hidden]` appends the same entry.
- Precedence: run declaration (exact name, then glob) > the app's [conf.yml
  schema](experiments.md#best-value-summaries-summary) > `last`.
- `row["metrics"][name]` is that value everywhere (`list_runs(sort=, query=)`,
  `vmn-exp list --sort`, `prune --query`, the leaderboard);
  `row["metric_summary"][name]` holds `{"last", "min", "max", "first",
  "mean"}` for metrics logged more than once (non-finite values never count;
  `mean` is `None` without a finite value).
- A run's `goal` and `hidden` also count across runs for names conf.yml does
  not declare (the latest run wins): they set sort direction and the UI's
  hidden columns, never which value another run ranks on.

### Tags

Mutable `str -> str` labels. Each call appends a `tags` entry; readers fold them
per key, last write wins, and a removed tag can be set again. They work on a
finished run too:

```python
run.set_tags({"stage": "candidate", "owner": "ann"})
run.finish()
run.set_tag("verdict", "keep")      # still recorded
```

Rows carry `tags` (`{key: value}`); query them as `tags.stage = "prod"`.

### Alerts

`run.alert()` is `wandb.alert()`:

```python
if math.isnan(loss):
    run.alert("loss is NaN", text=f"step {step}, lr {lr}", level="error")
```

- `level`: `"info"` (default), `"warn"` or `"error"`, else `ValueError`.
- Appends an `alert` log entry (shown by `vmn-exp show` and the run log) and
  sends it to the configured sinks when the `alert` trigger is on (the
  default). Delivery is off-thread and never raises; `finish()` waits up to 5 s.
- Repeats of one title within `wait_sec` (default conf
  `experiment.alerts.wait_sec`, 60) are dropped, neither logged nor sent;
  `wait_sec=0` sends every call. Returns whether this one went through.
- With the `failed` trigger on, the run also alerts when it finishes failed.

Sinks, triggers and env-var fallbacks: [experiments.md](experiments.md#alerts).

### Changing stored runs: archive, unarchive, tags

```python
from vmn_exp.sdk import manage

manage.archive_run("my_app", "@3")          # hidden from list_runs by default
manage.unarchive_run("my_app", "@3")
manage.set_tags("my_app", "latest", {"verdict": "keep"}, remove=["todo"])
```

`archive_run(app_name=None, ref="latest", *, storage=None)`, `unarchive_run(...)`
and `set_tags(app_name=None, ref="latest", tags=None, *, remove=None,
storage=None)` take any addressing form, return the verstr they changed and
raise `ValueError` for an unknown ref. Archiving sets `archived: true` in
`metadata.yml`; nothing is deleted, and only listings treat archived runs
differently (`vmn-exp prune` counts them like any finished run).

---

## Autologging

`autolog()` patches a framework's training entry point so every `fit()` records
hyperparameters, a score and (optionally) the fitted model, with no logging
calls in your training code.

```python
from vmn_exp.sdk import autolog, autolog_disable, start_run

autolog()                                          # every supported framework
autolog(frameworks=["sklearn"], log_models=True)   # name them; opt in to saving models
autolog(training_score=False)                      # calling again reconfigures
autolog_disable()                                  # restore the originals

with start_run("my_app", note="rbf baseline") as run:
    SVC(kernel="rbf", C=2.0).fit(X, y)
    # params.sklearn_estimator = "SVC", params.sklearn_kernel = "rbf",
    # params.sklearn_C = 2.0, metrics.sklearn_score = 0.97
```

| Option | Default | Meaning |
|---|---|---|
| `frameworks` | all supported | which to patch; unknown or uninstalled names are a silent no-op |
| `log_models` | `False` | also save each trained model as an artifact (a file per fit, written on the training thread) |
| `training_score` | `"auto"` | record `<framework>_score`, `score()` on the **training** data: `True`, `False`, or `"auto"` = only for inputs of at most 10,000 rows |

- `autolog()` never imports a framework: one already imported is patched now,
  any other when first imported. Under `VMN_MODE=disabled` it patches nothing.
- **It records only inside a run you opened**, into `current_run()`. It never
  opens a run itself (that would snapshot and stamp from inside `fit()`).
- Names are `<framework>_<name>` with an underscore, so the query language's
  two-part paths resolve them (`params.sklearn_kernel`).

| Name | Wraps | Notes |
|---|---|---|
| `sklearn` | every estimator's `fit` | incl. meta-estimators and inherited `fit` |
| `xgboost` | `XGBClassifier.fit`, `XGBRegressor.fit` | the scikit-learn wrappers; native `xgboost.train` is left alone |
| `keras`, `tensorflow` | `keras.Model.fit` | Keras 3, any backend; the two names patch the same method once |
| `lightning`, `pytorch_lightning` | `Trainer.fit` of each package | both record under the `lightning_` prefix |
| `transformers` | `Trainer.train` | injects a [`VmnCallback`](#hugging-face-transformers--vmncallback); patched when `transformers.trainer` is imported |

What each records:

| | scikit-learn / xgboost | Keras | Lightning |
|---|---|---|---|
| params | `sklearn_estimator` (class name), `sklearn_<k>` for every `get_params()` key (non-scalars as `repr`, addresses stripped; a meta-estimator's own `estimator` param as `sklearn_param_estimator`), search estimators' `sklearn_best_<param>` | `keras_estimator`, `keras_optimizer`, `keras_learning_rate`, `keras_loss_fn`, `keras_parameter_count` | `lightning_estimator`, `lightning_max_epochs`, `lightning_precision`, plus every `LightningModule.hparams` key (call `save_hyperparameters()`) |
| metrics | `sklearn_score` (training set; prefer the CV score), `sklearn_best_cv_score` for search estimators | per epoch: `keras_loss` and each compiled metric, stepped by the real epoch (`initial_epoch` respected) | the final `trainer.callback_metrics`, e.g. `lightning_train_loss`; no per-epoch series |
| `log_models=True` | pickle `sklearn_<Class>.pkl` (`_<n>` for the n-th of a class) | `keras_<Class>.keras` | `lightning_<Class>.ckpt` via `trainer.save_checkpoint`; skipped with a warning when `trainer.world_size > 1` |

Guarantees:

- **One record per training call**: inner `fit()`s (pipeline steps, forest
  trees) don't record, so a `Pipeline` gives `sklearn_estimator = "Pipeline"`
  and one model.
- **Each fit records into its own run**: the run opened by the calling thread,
  else the process's only open run, so a thread-pool sweep records each trial
  separately. A framework's worker threads never record while the outer fit
  is recording; a fit in another thread with no run of its own is not recorded
  meanwhile. Forked workers never write into the parent's run.
- **Autologging never breaks training**: recording failures become debug log
  lines; `fit()`'s return value and exceptions pass through.
- **Idempotent and reversible**: a second `autolog()` only applies new options;
  `autolog_disable()` restores the originals and drops pending import hooks.

**Plain `torch` has no `fit()` to wrap**: log in your own loop
(`run.log_metric("train_loss", loss, step=epoch)`), and use
[`watch`](#pytorch--watch) for gradient/parameter histograms. Lightning is the
autologged route.

Adding a framework is one `_adapter(...)` entry in `SUPPORTED_FRAMEWORKS`
(`vmn_exp/sdk/autolog.py`). Only `discover(module)` (the `(owner, attr)` pairs
to wrap) is required, or `method_owners` when the entry point is not `fit`;
`watch` names the module(s) whose import triggers patching. The rest default to
the scikit-learn behaviour: `subject(call)` (the trained object), `params(call)`,
`metrics(call)`, `series(call)` (`{name: [per-step values]}`), `save(call,
subject, base)`, `instrument(call, run)` (e.g. add a callback) and
`fitted_params(call)`. `call` is `(instance, args, kwargs, result)`.

---

## Finishing, failures, and the heartbeat

The context manager calls `run.finish(exit_code=0)` on the way out; call it
yourself when a `with` block doesn't fit. It is idempotent.

- An exception inside the `with` block appends an `error` entry, finalizes the
  run as **failed** (exit code 1) and is re-raised. `sys.exit(N)` inside it
  records `N` (0 for no argument).
- A run still open at interpreter exit is finalized too: succeeded after a
  clean exit, failed after an uncaught exception.
- `finish()` never raises for a storage failure (a 503 at the end of a
  ten-hour run is logged as a warning) and always closes the run.
- The run **heartbeats itself** from a daemon thread (bumping `heartbeat_seq`
  in `run_state.yml`), so an OOM-killed or lost job goes
  [`stuck`](experiments.md#run-status-did-my-job-die) instead of `running`
  forever. Remote state and log uploads run off that thread; a hung PUT never
  delays a beat.
- **SIGTERM finalizes every open run** with exit code 143 and
  `received_signal: SIGTERM` (so it reads `failed`, never `stuck`), waits for
  the final uploads up to `VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC` (default 60; one
  shared wait for all runs), then calls the previous handler or re-delivers the
  signal. The handler is installed when `vmn_exp.sdk` is imported on the main
  thread (never over `SIG_IGN`). If you install your own SIGTERM handler later,
  or first import the SDK from a worker thread, call
  `install_signal_handlers()` from the main thread to chain it.

### Steps

Every metrics entry has a step. `run.step` is the step the next call without
`step=` records; each such call advances it by one (W&B's `_step`):

```python
run.log_metrics({"loss": 0.9, "acc": 0.1})   # step 0, shared by both values
run.log_metric("loss", 0.8)                  # step 1
run.log_metric("loss", 0.5, step=10)         # step 10; run.step is now 11
run.log_metric("loss", 0.6, step=3)          # kept at step 3; run.step stays 11
run.log_metric("lr", 1e-3, commit=False)     # step 11, not advanced ...
run.log_metric("loss", 0.4)                  # ... so this one is step 11 too
```

- An explicit step only ever raises `run.step`; lower steps are kept.
  `commit=False` records without advancing. A call whose values are all dropped
  consumes no step. The counter is thread-safe.
- A new run starts at 0, a fork or rewind at `run.start_step`, a resumed run one
  past its highest visible metrics step.
- `sys_*` metrics are step-less; media keep per-name steps; the `vmn-exp run`
  metrics file still needs an explicit `step=N` prefix.
- `NoOpRun` counts `run.step` the same way, so `range(run.step, ...)` works on
  every rank.

### Resuming a preempted run

```python
run = start_run("my_app", run_id=saved_run_id)
# or set VMN_RESUME_RUN_ID=<verstr> in the requeued job's environment
```

The run is reopened (same verstr, `running` again with this pid/host) and this
process appends its own log segment. `started_at` is kept, so `duration_sec`
spans every attempt; `resume_count` and `resumed_at` record the restarts. A
`note`/`params` passed on resume is appended. An unknown ref raises
`ValueError`. `$VMN_RESUME_RUN_ID` is removed from the environment when used, so
neither later runs nor subprocesses resume it again; an explicit `run_id` wins.

### Forking a run

Branch a new run off another at a step (W&B's `fork_from`):

```python
with start_run("my_app", fork_from=source_id, fork_step=200) as run:
    for step in range(run.start_step, 400):   # start_step == 201
        run.log_metric("loss", train_one_epoch(), step=step)
# fork_from=f"{source_id}?_step=200" is the same thing
```

The fork gets its own verstr and a snapshot of the **current** tree, and
records `forked_from: {verstr, step}`. Its log opens with the source's metrics
up to and including the step and the params logged before it, marked
`"inherited": true`, so the fork's own entries (and `params=`) fold over them.
Without `fork_step` the whole history is copied. The source must be a run of
the same app (else `ValueError`, before anything is created); `run_id` and
`fork_from` cannot be combined.

A fork is **not a child** (nest it with `parent=` if you want that). Rows carry
`forked_from` and `forked_from_step`, so `query='forked_from = "<verstr>"'`
finds every fork; `vmn-exp show` prints `Forked from: <verstr> @ step N`.

### Rewinding a run

Resume a run but discard what it logged after a step:

```python
with start_run("my_app", run_id=run_id, rewind_to_step=250) as run:
    for step in range(run.start_step, 500):   # start_step == 251
        ...
```

Nothing is deleted: the run appends `{"type": "rewind", "step": 250}` and every
reader ignores entries with a step past 250 written before the marker. Entries
without a step (params, notes, tags) are never rewound; a later rewind cuts
again. A run live elsewhere is refused with `RuntimeError`. To rewind without
reopening, use [`vmn-exp rewind`](experiments.md#rewind).

### Distributed training (DDP, torchrun, Slurm)

On a non-zero rank (`RANK > 0`; without `RANK`, `LOCAL_RANK > 0` with
`WORLD_SIZE > 1`; else `SLURM_PROCID > 0`) `start_run()` returns a `NoOpRun`:
the same interface, recording nothing, with no heartbeat, git or storage
access. It is never registered as open, so `current_run()` is `None` and
autologging records nothing there. `use_artifact`/`use_model`/`use_dataset`
still return what rank 0 gets. Rank 0 records and exports
`VMN_EXPERIMENT_ID`. `all_ranks=True` records on every rank.

### Disabled mode

`VMN_MODE=disabled` (or `start_run(mode="disabled")`) makes the SDK a no-op for
CI, unit tests or debugging: `start_run()` returns a `NoOpRun` with
`run.disabled = True` and `run.id = None` before touching git or the store;
`$VMN_RESUME_RUN_ID` is left alone, `current_run()` stays `None`,
`VMN_EXPERIMENT_ID` is not exported, and `autolog()` patches nothing. An
explicit `mode="enabled"` beats the variable. `vmn-exp run my_app -- cmd` under
`VMN_MODE=disabled` just runs `cmd` (with `VMN_METRICS_FILE=/dev/null`).

---

## Nesting

`nested=True` parents the new run to the calling context's open run (else the
process's only open run):

```python
with start_run("my_app", note="lr sweep") as sweep:
    for lr in (1e-4, 3e-4, 1e-3):
        with start_run("my_app", nested=True, params={"lr": lr}) as trial:
            trial.log_metric("loss", train(lr))
```

Parent precedence: explicit `parent=` > `nested=True` > `$VMN_EXPERIMENT_ID` (a
stale one is warned about and ignored). An open run exports
`VMN_EXPERIMENT_ID`, so a subprocess you launch auto-links as an inner run:

```python
with start_run("my_app", note="lr sweep"):
    for lr in (1e-4, 3e-4, 1e-3):
        subprocess.run(["vmn-exp", "run", "my_app", "--", "python", "train.py", "--lr", str(lr)])
```

Either way you get the [outer/inner structure](experiments.md#outer--inner-jobs-sweeps)
(`kind`, `tree_status`) a CLI sweep produces.

### Sweep trials: `sweep_params()`

Inside a trial launched by [`vmn-exp sweep agent`](sweeps.md), `sweep_params()`
returns the trial's params (a fresh dict from `$VMN_SWEEP_PARAMS`; `{}` outside
a sweep). A `start_run()` in the trial nests under it, and the sweep reads the
target metric from it ([sweeps.md](sweeps.md#inside-a-trial)).

### Threads, forks and `current_run()`

`from vmn_exp.sdk import current_run` returns the run the calling code should
record into: the run this thread/context opened, else the process's only open
run, else `None`.

- **Thread-pool sweeps**: trials that each call `start_run()` in their own
  thread are independent siblings. A run another thread has open is never taken
  as a parent via `VMN_EXPERIMENT_ID` (only the value the process was launched
  with is); pass `parent=outer.id` to nest across threads. Once every run has
  finished, the environment is restored.
- **Forks** (`multiprocessing` fork, DataLoader workers): the child inherits the
  `Run` objects but not the runs: `current_run()` is `None` there and the
  child's exit never finalizes the parent's run. A child calling `start_run()`
  becomes an inner run via the inherited `VMN_EXPERIMENT_ID`.

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

All readers resolve `app_name=None` like `start_run()` (among apps with
experiments). Without `storage=` they read the local experiments of the
checkout found from the cwd (or `$VMN_WORKING_DIR`). For a git-free dir or a
remote store, pass one:
`storage=vmn_exp.core.storage_resolve.resolve_experiment_storage()` honours
`VMN_EXPERIMENT_DIR`/`VMN_EXPERIMENT_STORE`/the bucket shorthand, or takes
`dir=`/`store=` explicitly. Outside a checkout pass `app_name` too: only with
both given is no checkout looked up (and then no conf.yml metrics schema is
applied).

| Function | Returns |
|---|---|
| `list_runs(app_name=None, *, storage=None, sort=None, last=None, status=None, query=None, use_index=True, include_archived=False)` | rows, oldest first. `status`: a status or list/comma-separated statuses; `query`: [the query language](#the-query-language) (`QueryError` on a bad one); `last` keeps the last N (before sorting); `sort` orders by a metric (default the configured [primary metric](experiments.md#metrics-schema-sorting--goals)); archived runs only with `include_archived=True` |
| `get_run(app_name=None, ref="latest", *, storage=None, x=None)` | one row plus `log`, `series` (metric → `[{"step", "ts", "value"}]` in log order), `step_metrics`, `artifacts`, `format_version` and the media indexes. `x=` joins series on a metric ([x axis](#custom-x-axis-step_metric)). `ValueError` for an unknown ref |
| `get_lineage(app_name=None, ref="latest", *, depth=1, storage=None, limit=100)` | see [Lineage](#lineage) |
| `param_importance(app_name=None, metric=None, *, storage=None, query=None, status=None, include_archived=False)` | `[{"param", "importance", "correlation", "spearman", "kind", "n"}]`, most important first, over the runs `list_runs` would return. `importance` is a random-forest share (sums to 1); correlations are `None` for categorical params ([details](experiments.md#importance)). `ValueError` when no run carries `metric` |
| `runs_dataframe(app_name=None, **list_runs_kwargs)` | pandas, below |
| `get_metric_history(metric, app_name=None, ref="latest", *, storage=None)` | pandas, below |

A row carries each metric's [summary](#metric-goals-and-summaries) (the last
value unless declared otherwise), `params`, `tags`, `inputs`, `outputs`, `name`,
`archived`, the status fields and the tree fields (`parent`, `children`,
`kind`, `depth`, `tree_status`). Records written in a newer format than the
installed SDK reads are skipped with a warning.

`list_runs` reads through the incremental index `vmn-exp list` and the UI use:
for a local store `.index.sqlite` in the experiments directory, for S3 a
per-host cache under `$VMN_INDEX_CACHE_DIR` (default `$XDG_CACHE_HOME/vmn` or
`~/.cache/vmn`; `none` disables). Each call re-reads only what changed. It is a
disposable cache; `use_index=False` reads storage directly and writes no index.
`get_run` uses the index to resolve refs, then reads just that run.

### As pandas DataFrames

Needs `pip install "vmn-exp-sdk[pandas]"` (otherwise `ImportError` naming the
extra).

```python
from vmn_exp.sdk.reader import get_metric_history, runs_dataframe

df = runs_dataframe("my_app", query="metrics.loss < 0.5", status="succeeded")
df.sort_values("metrics.loss").head()

loss = get_metric_history("loss", "my_app", ref="@3")   # columns: step, timestamp, value
```

- `runs_dataframe` is `list_runs` as one flat DataFrame (like
  `mlflow.search_runs()`), taking every `list_runs` keyword. Columns: `run_id`
  (the verstr), `idx`, `name`, `status`, `kind`, `parent`, `tree_status`,
  `timestamp`/`started_at`/`finished_at` (UTC datetimes), `duration_sec`,
  `exit_code`, `host`, `branch`, `code_verstr`, `note`, `archived`, then sorted
  `metrics.<k>`, `params.<k>`, `tags.<k>` and `inputs.<name>` (the URI).
  `metrics.<k>` is the fold the query language sees, numeric params included.
- `get_metric_history` is every logged value of one metric in one run, in log
  order (`step` is `None` where none was logged); empty if never logged.

### Lineage

```python
from vmn_exp.sdk.reader import get_lineage

with start_run("my_app", name="train") as train:
    train.log_input("s3://bucket/data.parquet", digest="sha256:9f2c...")
    train.log_artifact("model.pkl")

with start_run("my_app", name="eval") as evaluate:
    path = evaluate.use_artifact(train.id, "model.pkl")   # vmn://my_app/<train>/model.pkl

get_lineage("my_app", evaluate.id, depth=2)
# {"app", "verstr", "upstream": [...], "downstream": [...],
#  "datasets": [...], "models": [...], "truncated": False}
```

Runs link through what they consumed and produced:

- Every row carries `outputs`: `{path: {"path", "digest": "sha256:<hex>",
  "size"}}` from its artifact, image and table entries (latest write wins).
- **upstream**: runs whose artifacts this run consumed. A `vmn://<app>/<verstr>/<path>`
  input (what `use_artifact` records; `<app>` in tag form, `/` → `-`) names its
  producer in any app; any other input matches runs of the same app with an
  output of the same digest (compared without `sha256:`, case-insensitively).
- **downstream**: runs of the same app that consumed this run's outputs, by the
  same rules.
- **datasets**: the reference datasets used (`vmn-registry://<name>@<N>`
  inputs): `{"model", "version", "kind", "input", "digest", "found"}`.
- **models**: live registry versions registered from the run: `{"model",
  "kind", "version", "aliases", "status", "artifact_path"}`.

Each node is `{"app", "verstr", "name", "timestamp", "status", "depth",
"found", "links"}`; `depth` counts hops, `found` is False for a `vmn://` URI
naming a missing run, and `links` are `{"input", "artifact", "digest", "via":
"uri"|"digest"}` (plus `model`/`version`/`kind` when the artifact backs a live
registry version). Each direction keeps at most `limit` nodes (`truncated`
says one was cut). It is answered from the index rows; no run log is read.
`ValueError` for an unknown ref.

The other direction, which run made a registry version and which runs used it
(across apps), is `vmn_exp.registry.lineage.version_lineage(storage, name, n)`;
see [models.md](models.md#lineage).

---

## The query language

One expression language filters rows for `list_runs(query=)`, `vmn-exp list
--query` ([experiments.md](experiments.md#list)), `prune --query` and the
[REST API / UI](ui.md#filtering-with-a-query):

```
metrics.loss < 0.5 and status = "succeeded"
status in ("running", "stuck")
note ~ "baseline"
params.optimizer = "adam" and not params.frozen = true
metrics.acc >= 0.9 and (kind = "inner" or depth = 0)
metrics."train/loss" < 0.3
```

**Operators**

| Form | Means |
|---|---|
| `=` `==` `!=` | equality; types must match (a number never equals a string, `true` never equals `1`) |
| `<` `<=` `>` `>=` | ordering of two numbers or two strings; mixed types don't match |
| `~` / `contains` / `!~` | case-insensitive substring (string right-hand side); on a list field (`command`, `children`) any element matches, on a dict field (`tags`) any value |
| `in (…)` / `not in (…)` | membership in a literal list |
| `and` `or` `not`, `(…)` | the usual, `not` binding tightest |

Literals: numbers (including `1e-4`, `2.5E+3`), quoted strings (either quote),
`true`, `false`, `null`. Keywords are case-insensitive; **field names are
case-sensitive**, and an unknown field is a `QueryError`, not an empty result.
`not`/parentheses nest at most 100 deep.

**Fields**

- Row keys: `idx`, `verstr`, `code_verstr`, `timestamp`, `note`, `branch`,
  `base_version`, `parent`, `name`, `archived`, `tags`, `last_metric_at`,
  `status`, `exit_code`, `started_at`, `finished_at`, `heartbeat`,
  `duration_sec`, `pid`, `host`, `command`, `stale_sec`,
  `heartbeat_interval_sec`, `children`, `kind`, `depth`, `tree_status`,
  `imported_from`, `forked_from`, `forked_from_step`, `rerun_of` (see
  [ui.md](ui.md#experiment-status-fields)). `archived = true` only matters with
  `include_archived=True`.
- `metrics.<name>`, `params.<name>`, `tags.<key>` (always strings; a removed tag
  is missing), `env.<key>` (the captured environment summary: `python`,
  `platform`, `packages_count`, …).
- `inputs.<name>.uri|digest|kind` and `outputs.<path>.path|digest|size`
  ([lineage](#lineage)).
- Quote a key containing `/`, `.` or `-`: `metrics."train/loss"`,
  `params.'val-acc'`, `outputs."model.pkl".digest`, `inputs."resnet50@3".kind`.

`metrics` and `params` read different dicts. **`metrics` is numeric only**:
params that parse as finite numbers are folded in (bools as 1.0/0.0; `nan`
values never). **`params` holds every param verbatim**, so `params.model =
"xgb"` and `params.cache = true` work and `metrics.model` does not.

**Missing fields** are two-valued, not SQL's `UNKNOWN`: a comparison against an
absent or `None` field is false, so a query and its `not` partition the rows.
`= null` tests absence, and `!= x` is true for a run without `x`.

An invalid query raises `QueryError` (a `ValueError`) with the character offset
(`unknown field 'statuz' at offset 0`); over HTTP it is a 400. Nothing is
`eval`'d.

---

## Model registry

Named, versioned models and datasets linked to the runs that produced them,
stored under the reserved pseudo-app `vmn-registry` in the same store as runs.
The full reference (refs, aliases, datasets, use recording, storage, prune
protection) is [models.md](models.md#sdk).

```python
from vmn_exp.sdk import download_model, get_model_version, set_alias, start_run

with start_run("my_app") as run:
    run.log_artifact("weights.pt")
    run.register_model("resnet50", artifact_path="weights.pt", alias="staging")

meta = get_model_version("resnet50@staging")      # model, model@latest, model@N, model@alias
set_alias("resnet50", "production", 2, expect=1)  # CAS guard
with start_run("serving") as run:
    path = download_model("resnet50@production")  # also records the use inside a run
    run.use_dataset("imagenet")
```

| Function | Signature |
|---|---|
| `register_model` | `(name, run=None, app_name=None, artifact_path=None, alias=None, description=None, *, storage=None)` |
| `set_alias` / `remove_alias` | `(model, alias, version, expect=None, *, storage=None)` / `(model, alias, *, storage=None)` |
| `get_model_version` / `get_dataset_version` | `(ref, *, storage=None)`; never records a use |
| `list_models` | `(*, storage=None)`; models and datasets |
| `download_model` | `(ref, dst=None, *, storage=None, record=True)` |
| `register_dataset` | `(name, uri=None, *, run=None, app_name=None, artifact_path=None, digest=None, description=None, alias=None, dedupe=True, storage=None)`; exactly one of `uri` / `artifact_path` |
| `use_model` / `use_dataset` | `(ref, *, run=None, storage=None)`; also `run.use_model(ref)` / `run.use_dataset(ref)` |

---

## Integrations

Explicit helpers in `vmn_exp.integrations.*`, separate from autologging. Each
needs the library it wraps (installed by you) and imports it lazily.

### Hugging Face Transformers — `VmnCallback`

`autolog()` injects it into every `Trainer.train`; attach it by hand without
autologging:

```python
from vmn_exp.integrations.hf import VmnCallback   # transformers is imported on first use

with start_run("my_app") as run:
    Trainer(model=model, args=TrainingArguments(...), callbacks=[VmnCallback()]).train()
```

- `on_train_begin` logs the `TrainingArguments` as params (keys containing
  `token`, `logging_dir` and `_`-prefixed ones dropped) plus model config keys
  that differ from the config's defaults, as `model.<key>`.
- `on_log` logs numeric values at `state.global_step` as `train/<name>`,
  `eval/<name>` and `test/<name>` (`epoch` → `train/epoch`; `total_flos` and
  runtime/throughput keys dropped). Query them quoted: `metrics."eval/f1"`.
- Records only on the world-process-zero rank, and only inside an open run.
- Checkpoints are not stored by default. With `VmnCallback(log_checkpoints=True)`,
  each `on_save` uploads the checkpoint just saved
  (`<output_dir>/checkpoint-<global_step>`) as artifacts under `checkpoint-<N>/`;
  earlier checkpoints are not re-uploaded.

### Optuna — `start_study_run` + `StudyTracker`

```python
import optuna
from vmn_exp.integrations.optuna_study import start_study_run

study = optuna.create_study(direction="minimize")
tracker = start_study_run(study, app_name="my_app", name="lr_sweep")
study.optimize(tracker.wrap(objective), n_trials=20, n_jobs=4)
tracker.finish()
```

- `start_study_run(study, app_name=None, **start_run_kwargs)` opens the outer
  run (`name` defaults to the study name) with params `sampler`, `pruner` and
  `direction`/`directions`.
- `tracker.wrap(objective)` opens one inner run per trial (thread-safe under
  `n_jobs > 1`; `autolog()` inside the objective records into it), tagged
  `trial_number`. It logs `trial.params`, the return value as `objective`
  (`objective_<i>` for multi-objective) and each `trial.report(value, step)` as
  the `intermediate` series.
- A pruned trial finishes succeeded with tag `state=pruned` and `TrialPruned`
  is re-raised; any other exception finishes it failed and is re-raised.
- `tracker.finish()` logs `best_value` and `best_<param>` on the outer run
  (multi-objective: `best_n_pareto_trials`) and closes it.

### Ray Tune — `TuneRecorder` + `VmnTuneCallback`

Driver-side only: it records trial outcomes from the process running Tune; no
worker-side logging.

```python
from vmn_exp.integrations.ray_tune import TuneRecorder, make_callback

recorder = TuneRecorder(app_name="my_app", experiment_name="lr_sweep")
tune.run(trainable, config={"lr": tune.grid_search([1e-3, 3e-4])},
         callbacks=[make_callback(recorder)])
recorder.finish()
```

- `TuneRecorder(app_name=None, experiment_name=None, **start_run_kwargs)`
  (kwargs go to every `start_run()`) opens the outer run on the first trial
  and one inner run per trial, named by trial id, with the flattened config
  (`a.b` keys) as params.
- Each result is logged at `training_iteration` as the step, minus Ray's
  bookkeeping keys (`config`, `timestamp`, `pid`, `time_*`, …).
- Completed trials finish succeeded, errored ones failed (so the outer
  `tree_status` rolls up to `failed`). `finish()` is idempotent and also runs
  on Tune's experiment end; used as a context manager, an exception closes
  everything as failed.

### PyTorch — `watch`

`wandb.watch(model)` for a plain torch loop: gradient and/or parameter
histograms of every parameter (unrelated to the `vmn-exp watch` command).

```python
from vmn_exp.integrations.torch_watch import watch, unwatch

with start_run("my_app") as run:
    watcher = watch(model, log="gradients", freq=1000, bins=64)
    for batch in loader:
        loss = model(batch).mean(); loss.backward(); optimizer.step()
    unwatch(model)  # or watcher.remove(): logs what is pending, drops the hooks
```

- `watch(model, log="gradients", freq=1000, bins=64, run=None, prefix="")`:
  `log` is `"gradients"`, `"parameters"` or `"all"`; `run` defaults to
  `current_run()` at each forward call. Watching a model again replaces its
  watcher.
- Keys `gradients/<param>` and `parameters/<param>` are ordinary `histogram`
  entries (Media section, `get_run(...)["histograms"]`).
- The step is the **training-mode forward count**: every `freq`-th forward with
  `model.training` set logs the parameters (before that step's update) and
  captures the gradients, logged at the next forward or `watcher.flush()`. It
  is not your metrics' step.
- Histograms are computed on the device (`torch.histc`); only logged steps pay
  a host copy. Gradients are never modified, and a failing hook never breaks
  `backward()`. Nothing is recorded without an open run or on non-zero ranks.
- Caveats: with AMP `GradScaler` the hooks see scaled gradients; FSDP-sharded
  or `torch.compile`d models may give partial histograms.
- Size: a 64-bin entry is ~1.9 KB. ResNet-50 (~161 tensors) is ~310 KB per
  logged step per mode: ~31 MB over 100k steps at `freq=1000` for gradients.
  Lower `bins` or raise `freq` for big models.

---

## Environment variables

Read (or set) by the SDK. CLI-only variables are in [experiments.md](experiments.md).

| Variable | Effect |
|---|---|
| `VMN_APP_NAME` | default app name for writers and readers |
| `VMN_WORKING_DIR` | where writers and readers look for the checkout (default the cwd) |
| `VMN_MODE` | `disabled`: no-op runs, `autolog()` patches nothing |
| `VMN_RESUME_RUN_ID` | run to reopen (consumed when used) |
| `VMN_EXPERIMENT_ID` | parent of new runs; exported while a run is open |
| `VMN_SNAPSHOT_METADATA` | git-free mode against an exported snapshot |
| `VMN_EXPERIMENT_DIR` | local experiment root |
| `VMN_EXPERIMENT_STORE` | remote store URI |
| `VMN_EXPERIMENT_BUCKET` / `_PREFIX` / `_ENDPOINT_URL` | `s3://` shorthand (prefix default `vmn-experiments`) |
| `VMN_EXP_OFFLINE` | record locally only; upload later with `vmn-exp push` |
| `VMN_WRITER_ID` | this writer's id (log segment names, offline verstrs); default `HOSTNAME`, then the host name |
| `VMN_SYSTEM_METRICS` | `0`/`false`/`no`/`off` disables `sys_*` sampling |
| `VMN_EXP_SUPERVISOR_SAMPLES` | set by `vmn-exp run` when it samples the child; `system_metrics` then defaults off |
| `VMN_CAPTURE_ENV` | `0`/`false`/`no`/`off` disables environment capture |
| `VMN_EXP_OUTPUT_CAP_MB` | `capture_output` size cap (default 10) |
| `VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC` | wait for final uploads at finish/SIGTERM/exit (default 60) |
| `VMN_EXP_ALERT_WEBHOOK_URL` / `_SLACK_URL` / `_COMMAND` / `_ON` | alert sinks and triggers ([experiments.md](experiments.md#alerts)) |
| `VMN_SWEEP_PARAMS` | sweep trial params, read by `sweep_params()` |
| `VMN_INDEX_CACHE_DIR` | where S3 index caches live; `none` disables |
| `VMN_EXP_MIN_STALE_SEC` | floor of the `stuck` window when readers derive status (default 60) |

---

## Library logging

The SDK logs through stdlib `logging` under `vmn_exp.sdk` and never configures
handlers. To see its debug output: `logging.basicConfig(level=logging.DEBUG)`.

---

## Slim install

For recording-only environments (containers, CI workers, air-gapped jobs):

```sh
pip install vmn-exp-sdk    # + [s3]/[gcs]/[azure] for a bucket, [pandas] for DataFrames; pynvml for GPU metrics
```

`vmn-exp-sdk` is `vmn_exp.sdk` plus the storage, registry and record helpers it
needs: no vmn, no GitPython, no git binary. Creating a run from a git checkout
needs `vmn-exp`; in a slim install `start_run()` in a checkout raises a
`RuntimeError` pointing at `pip install vmn-exp` or the git-free variables
([Runs without a git checkout](#runs-without-a-git-checkout-containers)). A
missing store extra raises `ImportError` naming it. See
[packaging.md](../packaging.md) for the package split.
