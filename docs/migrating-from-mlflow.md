# Migrating from MLflow to vmn

This guide covers three use cases:

1. **[Importing existing MLflow runs](#importing-existing-mlflow-runs)** — bring
   your history into vmn without rerunning anything.
2. **[Porting Python scripts](#porting-python-scripts)** — swap out `mlflow.*`
   calls for the vmn SDK.
3. **[Registry mapping](#registry-mapping)** — translate MLflow model registry
   concepts to `vmn-exp model`.

For a side-by-side feature comparison see [vmn vs MLflow](vmn-vs-mlflow.md).

---

## Importing existing MLflow runs

`vmn-exp import-mlflow` reads an MLflow FileStore or a live tracking server and
writes the runs into your vmn-exp storage.  No git checkout is required;
the command never takes the repo lock.

### From a local `mlruns/` directory

```sh
# Import all experiments in mlruns/ into the vmn app "my_app"
vmn-exp import-mlflow --mlruns ./mlruns my_app

# Import only one experiment (by name or numeric id)
vmn-exp import-mlflow --mlruns ./mlruns --experiment "Baseline" my_app

# Preview without writing anything
vmn-exp import-mlflow --mlruns ./mlruns --dry-run my_app

# Skip artifact files (metadata and metrics only)
vmn-exp import-mlflow --mlruns ./mlruns --skip-artifacts my_app

# Include runs MLflow marked DELETED
vmn-exp import-mlflow --mlruns ./mlruns --include-deleted my_app
```

### From a tracking server

```sh
pip install mlflow-skinny   # or vmn-exp[mlflow]

vmn-exp import-mlflow --tracking-uri http://mlflow.internal:5000 my_app
vmn-exp import-mlflow --tracking-uri http://mlflow.internal:5000 \
    --experiment "Production" --workers 16 my_app
```

`--tracking-uri` uses the MLflow client API (requires `mlflow-skinny`).
`--mlruns` reads the file store directly with no MLflow dependency.

### What maps to what

| MLflow concept | vmn concept |
|---|---|
| Experiment | App name (`<app>`) |
| Run | Experiment run |
| Run ID (UUID) | Used to compute a deterministic verstr `0.0.0-mlflow.<id[:12]>` |
| Params | `params.*` entries in the run log |
| Metrics (final value) | `metrics.*` entries in the run log |
| Metric history (value, step, timestamp) | Per-step series in the run log |
| Tags | `tags.*` entries |
| Artifacts | Copied into the run's artifact directory (unless `--skip-artifacts`) |
| Dataset inputs | `inputs.*` entries |
| Parent run ID | `parent` field on the inner run |
| Run status | `run_state.yml` — RUNNING → `stuck`, FAILED → `failed`, FINISHED → `succeeded`, KILLED → `failed` |
| `end_time` absent | State is `stuck` |

### Run identity and idempotent re-import

Imported runs get a deterministic verstr derived solely from the MLflow run ID:

```
0.0.0-mlflow.<first 12 chars of run_id>
```

Re-running the same import command is safe: runs whose verstr already exists in
storage are skipped.  Partial imports (interrupted mid-run) are detected and
resumed — the run log is appended to, not duplicated.

### No code snapshot

Imported runs have no code snapshot and no git ref.  `vmn-exp restore` and `vmn
exp diff` will refuse with a message explaining that the run has no associated
code.  `vmn-exp show` displays `imported_from: mlflow/<run_id>` to make this
clear.

### Registry

MLflow's model registry is not automatically imported.  After importing runs,
you can register model versions manually using the verstr from
`vmn-exp show my_app --query "imported_from ~ mlflow"`:

```sh
vmn-exp model register my_model \
    -v 0.0.0-mlflow.abc123def456 --app my_app \
    --artifact model/model.pkl \
    --alias production
```

---

## Porting Python scripts

The vmn SDK API mirrors MLflow closely enough that most scripts need only
mechanical substitutions.

### Core API mapping

| MLflow | vmn |
|---|---|
| `import mlflow` | `from vmn_exp.sdk import start_run` |
| `mlflow.start_run()` | `start_run("my_app")` |
| `mlflow.log_param(k, v)` | `run.log_params({k: v})` |
| `mlflow.log_params(d)` | `run.log_params(d)` |
| `mlflow.log_metric(k, v, step=i)` | `run.log_metric(k, v, step=i)` |
| `mlflow.log_metrics(d)` | `run.log_metrics(d)` |
| `mlflow.set_tag(k, v)` | `run.set_tag(k, v)` |
| `mlflow.set_tags(d)` | `run.set_tags(d)` |
| `mlflow.log_artifact(path)` | `run.log_artifact(path)` |
| `mlflow.log_artifacts(dir)` | `run.log_artifacts(dir)` |
| `mlflow.log_text(text, fname)` | `run.log_text(text, fname)` |
| `mlflow.log_figure(fig, fname)` | `run.log_figure(fig, fname)` |
| `mlflow.active_run().info.run_id` | `run.id` (a verstr, not a UUID) |
| `mlflow.search_runs(filter_string=...)` | `list_runs("my_app", query=...)` |
| `mlflow.get_run(run_id)` | `get_run("my_app", verstr)` |

### Example: minimal script conversion

```python
# MLflow
import mlflow

with mlflow.start_run():
    mlflow.log_params({"lr": 3e-4, "batch": 32})
    for step, loss in enumerate(train()):
        mlflow.log_metric("loss", loss, step=step)
    mlflow.log_artifact("model.pt")
```

```python
# vmn
from vmn_exp.sdk import start_run

with start_run("my_app") as run:
    run.log_params({"lr": 3e-4, "batch": 32})
    for step, loss in enumerate(train()):
        run.log_metric("loss", loss, step=step)
    run.log_artifact("model.pt")
```

### Differences to be aware of

**A run needs a git repo.**  Creating a run snapshots the working tree, which
means a git-level write.  Set `user.name` and `user.email` in containers or via
`GIT_AUTHOR_*` / `GIT_COMMITTER_*` environment variables.  There is no
equivalent of `mlflow.set_tracking_uri("http://...")` — clients write to files.

**`run.id` is a verstr, not a UUID.**  It is the same string `vmn-exp restore`
and `vmn goto` take.  It encodes HEAD + the uncommitted patch set.

**`autolog()` requires an open run.**  It never opens one implicitly; that would
stamp a version from inside `fit()`.  Start a run first:

```python
from vmn_exp.sdk import autolog, start_run

autolog()   # call once, before any fit
with start_run("my_app") as run:
    model.fit(X, y)   # autologged into `run`
```

**Metric keys from autolog are prefixed** `<framework>_<name>` (e.g.,
`sklearn_r2_score`), so the query language's two-part `metrics.<name>` paths
resolve them.

**No tracking server, no HTTP remote.**  All clients write to a shared filesystem
path or to an S3 bucket.  If your workers need credentials for S3, set
`VMN_EXPERIMENT_BUCKET` (and optionally `VMN_EXPERIMENT_PREFIX`,
`VMN_EXPERIMENT_ENDPOINT_URL`).

### Autologging

```python
# MLflow
mlflow.sklearn.autolog()

# vmn — all supported frameworks at once
from vmn_exp.sdk import autolog
autolog()

# or name them explicitly:
autolog(frameworks=["sklearn", "xgboost"])
autolog(log_models=True)   # also save the fitted model as an artifact
```

Supported frameworks: `sklearn`, `xgboost`, `keras`/`tensorflow`,
`lightning`/`pytorch_lightning`, `transformers`.

For Hugging Face Transformers specifically, autolog injects a `VmnCallback` into
every `Trainer.train()` call.  You can also attach it manually:

```python
from vmn_exp.integrations.hf import VmnCallback   # lazy — transformers not imported yet

trainer = Trainer(..., callbacks=[VmnCallback()])
```

---

## Registry mapping

| MLflow registry concept | vmn equivalent |
|---|---|
| Registered model | `vmn-exp model register <name> ...` |
| Model version | Version number (immutable, atomically assigned) |
| Stage (Staging / Production / Archived) | Alias (any string: `staging`, `production`, …) |
| Version status (READY / FAILED_REGISTRATION) | Version status (`active` / `deprecated` / `deleted`) |
| `client.transition_model_version_stage(...)` | `vmn-exp model alias <model> <alias> <n>` or `set_alias(...)` |
| `client.search_registered_models()` | `vmn-exp model list` / `list_models()` |
| `client.get_model_version(name, n)` | `vmn-exp model resolve name@n` / `get_model_version("name@n")` |
| `mlflow.pyfunc.load_model("models:/name/Production")` | `download_model("name@production")` returns a local path |

See [docs/models.md](models.md) for the full vmn-exp model registry reference.

---

## Further reading

- [vmn-exp tracking guide](experiments.md)
- [vmn Python SDK](sdk.md)
- [vmn-exp model registry](models.md)
- [vmn vs MLflow](vmn-vs-mlflow.md)
- [vmn-exp ui](ui.md)
