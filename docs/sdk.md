# Python SDK

`version_stamp.exp` is the in-process Python API for [experiment
tracking](experiments.md). It records the same runs the CLI does — same
snapshot, same verstr, same files — without a wrapper command or a metrics file.

```python
from version_stamp.exp import start_run

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

- [CLI or SDK?](#cli-or-sdk)
- [Starting a run](#starting-a-run)
- [Logging](#logging)
- [Autologging](#autologging)
- [Finishing, failures, and the heartbeat](#finishing-failures-and-the-heartbeat)
- [Nesting](#nesting)
- [Reading runs back](#reading-runs-back)
- [The query language](#the-query-language)
- [Library logging](#library-logging)

---

## CLI or SDK?

| Situation | Use |
|---|---|
| Wrapping a script you don't want to modify | `vmn exp run my_app -- python train.py` |
| A non-Python workload (a shell benchmark, `wrk`, a compiler flag sweep) | `vmn exp run` + `$VMN_METRICS_FILE` |
| You're already inside Python and want per-step metrics without a metrics file | `start_run(...)` |
| Metrics you measured by hand | `vmn exp create … --metrics k=v` |

**An SDK run is indistinguishable from a CLI run on disk.** Same verstr scheme,
same `metadata.yml`, same per-writer JSONL log, same `run_state.yml`. So
`vmn exp list`, `vmn exp show`, `vmn exp compare`, the web dashboard, and S3 sync
all work on SDK runs with no extra steps, and mixing the CLI and the SDK in one
project is fine — `vmn exp add` a hand-measured number to a run your training
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
)
```

| Argument | Means |
|---|---|
| `app_name` | the app to track under. `None` resolves it from the current repo, exactly as the CLI does |
| `note` | free-text note recorded on the run |
| `params` | the run's inputs, like `-f params.yml`'s `params:` key |
| `parent` | parent run, in any [addressing form](experiments.md#addressing-experiments) — a full verstr, a unique prefix, `@N`, or `latest` |
| `nested` | parent to the innermost open in-process run (see [Nesting](#nesting)) |
| `heartbeat_interval_sec` | beat cadence; defaults to the same 30s the CLI uses |
| `storage` | a storage backend, for S3-backed stores; defaults to the app's configured one |

Creating the run snapshots the working tree (dirty or clean) and assigns the
verstr, available as `run.id`. As with the CLI, the first run in a fresh repo
cold-starts vmn tracking and stamps a `0.0.0` baseline.

That create/cold-start phase is the only part that touches the repository, so it
is the only part that takes the per-repo vmn lock (`.vmn/vmn.lock`). The lock is
released before your training code runs — a run that trains for hours does not
block other `vmn` commands, and a subprocess you launch can use vmn freely.

---

## Logging

Every call appends to the run's log; nothing is ever rewritten.

| Call | Records |
|---|---|
| `run.log_metric(key, value, step=None)` | one metric. With `step`, it joins a **per-step series** — the curve `exp show` and the UI plot |
| `run.log_metrics({...})` | several metrics at once; also takes `step=` |
| `run.log_params({...})` | more inputs, merged into the run's params |
| `run.log_note(text)` | a note entry |
| `run.log_artifact(path)` | a file produced by the run |

Metrics land in the store as they are logged, so `vmn exp show` and the web UI
see the curve **while training is still running**.

---

## Autologging

`autolog()` patches a framework's training entry point so that every `fit()`
records the estimator's hyperparameters, its training score and (optionally) the
fitted model — with no logging calls in your training code:

```python
from version_stamp.exp import autolog, autolog_disable, start_run

autolog()                                          # every supported framework that is importable
autolog(frameworks=["sklearn"], log_models=True)   # or name them, and pick whether to pickle models
autolog_disable()                                  # restore the originals
```

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
autolog()

with start_run("my_app", note="rbf baseline") as run:
    SVC(kernel="rbf", C=2.0).fit(X, y)
    # params.sklearn_estimator = "SVC", params.sklearn_kernel = "rbf",
    # params.sklearn_C = 2.0, metrics.sklearn_score = 0.97, plus an SVC.pkl artifact
```

| Recorded | As |
|---|---|
| the estimator class name | `params.sklearn_estimator` |
| every key of `estimator.get_params()` | `params.sklearn_<name>` — scalars verbatim, anything else as its `repr()` |
| `estimator.score(X, y)` after the fit, when it returns a number | `metrics.sklearn_score` |
| the pickled fitted estimator, when `log_models=True` (the default) | an artifact named `sklearn_<Class>.pkl` |

What each framework can actually give up differs, so what lands differs too:

| | Keras | Lightning |
|---|---|---|
| params | `keras_estimator`, `keras_optimizer`, `keras_learning_rate`, `keras_loss_fn`, `keras_parameter_count` — read back off the compiled model | `lightning_estimator`, `lightning_max_epochs`, `lightning_precision`, plus every `LightningModule.hparams` key (so call `save_hyperparameters()`) |
| metrics | one point per epoch from the returned `History`, `metrics.keras_loss` and one per compiled metric | the final `trainer.callback_metrics`, e.g. `metrics.lightning_train_loss` |
| step series | yes — `History` carries every epoch, so no callback of vmn's is attached to your model | no; log inside `training_step` and Lightning's own loggers keep the curve |
| `log_models=True` | `keras_<Class>.keras`, the native archive | `lightning_<Class>.ckpt` via `trainer.save_checkpoint`, restorable with `load_from_checkpoint` |

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
- **Autologging never breaks training.** Every recording step is guarded; a
  failure inside it becomes a debug log line. Your `fit()` call, its return value
  and any exception it raises pass through untouched.
- **Patching is idempotent and reversible.** Each wrapper remembers the function
  it replaced, so a second `autolog()` recognizes its own work and leaves it
  alone, and `autolog_disable()` puts the exact originals back.

Adding a framework is one `_adapter(...)` entry in `SUPPORTED_FRAMEWORKS`, in
`version_stamp/exp/autolog.py`. An adapter answers the five questions the shared
recording path asks, and everything but the first defaults to the scikit-learn
answer:

| Field | Answers |
|---|---|
| `discover(module)` | which `(owner, attr)` pairs to wrap |
| `subject(call)` | which object is being trained — `call.instance` by default, the first argument for Lightning |
| `params(call)` | its hyperparameters, unprefixed — `subject.get_params()` by default |
| `metrics(call)` | its final metrics — `subject.score(X, y)` by default |
| `series(call)` | `{name: [per-step values]}`, logged one `log_metrics` per step — empty by default |
| `save(call, subject, base)` | write the model to `base + ext` and return the path — a pickle by default |

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

**The run heartbeats itself.** `vmn exp run` refreshes the heartbeat from the
process supervising the child; an SDK run has no supervisor — it *is* the
workload — so it carries its own daemon thread. That is what makes
[`stuck`](experiments.md#run-status-did-my-job-die) work for SDK runs: a job
that is OOM-killed or loses its node goes stale and is reported `stuck`, instead
of sitting at `running` forever with nobody left to write down that it died.

---

## Nesting

`nested=True` parents the new run to the innermost in-process run still open:

```python
with start_run("my_app", note="lr sweep") as sweep:
    for lr in (1e-4, 3e-4, 1e-3):
        with start_run("my_app", nested=True, params={"lr": lr}) as trial:
            trial.log_metric("loss", train(lr))
```

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

---

## Reading runs back

```python
from version_stamp.exp.reader import get_run, list_runs

for run in list_runs("my_app", last=10, status="succeeded"):
    print(run["verstr"], run["metrics"])

for run in list_runs("my_app", query='metrics.loss < 0.5 and params.optimizer = "adam"'):
    print(run["verstr"])

best = get_run("my_app", ref="latest")
```

- `list_runs(app_name=None, storage=None, sort=None, last=None, status=None,
  query=None)` — `sort` picks the metric to order by (the configured [primary
  metric](experiments.md#metrics-schema-sorting--goals) when omitted), `last`
  caps the result count, `status` filters to one derived status, and `query` is
  [the query language](#the-query-language). A bad query raises `QueryError`.
- `get_run(app_name=None, ref="latest", storage=None)` — `ref` takes any
  [addressing form](experiments.md#addressing-experiments): a full verstr, a
  unique prefix, `@N`, or `latest`.

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
| `~` / `contains` / `!~` | case-insensitive substring; the right-hand side must be a string |
| `in (…)` / `not in (…)` | membership in a literal list |
| `and` `or` `not`, `(…)` | the usual, `not` binding tightest |

Literals are numbers, quoted strings (either quote), `true`, `false`, `null`.
Numbers are plain integers or decimals — write `0.001`, not `1e-3`. Keywords and operators are case-insensitive (`AND`, `Contains`); **field names
are case-sensitive**, so `STATUS = "failed"` is an error, not an empty result.

**Fields**

- Bare row keys — `status`, `verstr`, `note`, `branch`, `exit_code`,
  `duration_sec`, `idx`, `timestamp`, `parent`, `kind`, `depth`, `tree_status`,
  `pid`, `host`, `command`, and the rest of what a row
  [carries](ui.md#experiment-status-fields). An unknown name is a query error,
  so a typo tells you instead of returning nothing.
- `metrics.<name>` — a numeric metric.
- `params.<name>` — a param, as it was recorded.

`metrics` and `params` read different dicts, and the difference matters:
**`metrics` holds numeric values only** (params that parse as numbers are folded
in, since sorting, leaderboards and charts need numbers), while **`params` holds
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
recursive-descent parser in `version_stamp/core/experiment_query.py`.

There is no `vmn exp list --query` flag yet; the query language is available from
the SDK and the REST API.

---

## Library logging

The SDK emits stdlib `logging` records under the `version_stamp.exp` logger and
never configures handlers — it is a library, so what happens to the records is
your application's call. To see its debug output:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```
