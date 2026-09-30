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
writes the runs into your vmn-exp storage.  No git checkout is required, the
command never takes the repo lock, and every imported run lands in the one
`<app>` you name (run one import per `--experiment` to split experiments into
separate apps).

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
| Experiment | The `<app>` you import into; the name is kept in `imported_from.experiment_name` |
| Run | Experiment run |
| Run ID (UUID) | Used to compute a deterministic verstr `0.0.0-mlflow.<id[:12]>` |
| Params | `params.*` entries in the run log |
| Metrics (final value) | `metrics.*` entries in the run log |
| Metric history (value, step, timestamp) | Per-step series in the run log |
| Tags | `tags.*` entries |
| Artifacts | Copied into the run's artifact directory (unless `--skip-artifacts`) |
| Dataset inputs | `inputs.*` entries |
| Parent run ID | `parent` field on the inner run |
| Run status | `run_state.yml` — FINISHED → `succeeded`; FAILED, KILLED → `failed`; RUNNING, SCHEDULED → `stuck` |

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
code, naming the source (`imported from mlflow run <run_id>; no code snapshot`,
plus the MLflow source commit when it was recorded).

### Registry

MLflow's model registry is not automatically imported.  After importing runs,
register model versions manually; an imported run's verstr is
`0.0.0-mlflow.<first 12 chars of the MLflow run id>` (`vmn-exp list my_app`
shows them):

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

**A run needs a git repo and a git identity.**  Creating a run snapshots the
working tree; the first run in a fresh repo commits and tags a local baseline
(never pushed, so no remote is required).  Set `user.name` and `user.email` in
containers or via `GIT_AUTHOR_*` / `GIT_COMMITTER_*`.  Jobs without a checkout
run git-free from a `vmn-exp export` bundle (`VMN_SNAPSHOT_METADATA`).

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

**No tracking server, no HTTP remote.**  There is no equivalent of
`mlflow.set_tracking_uri("http://...")`: clients write straight to a store —
a shared directory or `s3://`, `gs://`, `az://` — chosen by
`VMN_EXPERIMENT_STORE` (or `--store`, or conf `experiment.storage.uri`).
Workers with no store access record with `VMN_EXP_OFFLINE=1` and upload later
with `vmn-exp push`.

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

- [Client guide](client-guide.md) · [vmn-exp tracking guide](experiments.md)
- [vmn Python SDK](sdk.md)
- [vmn-exp model registry](models.md)
- [vmn vs MLflow](vmn-vs-mlflow.md)
- [vmn-exp ui](ui.md)
