# vmn vs MLflow

> [vmn](https://github.com/progovoy/vmn)'s experiment tracking (`vmn-exp`, the
> `vmn_exp.sdk` Python SDK, and the `vmn-exp ui` dashboard) overlaps with
> [MLflow](https://mlflow.org/). This page is an honest comparison — including
> what MLflow does that vmn does not.

## Overview

**MLflow** is a four-part ML platform: Tracking (runs, params, metrics,
artifacts), Models (a packaging format with flavors), Model Registry (versions,
stages, approvals), and Projects. Its centre of gravity is the path from a
trained model to a served one. Production deployments run a tracking server
backed by a database, with artifacts in blob storage.

**vmn** approaches tracking from the versioning side. An experiment is a
*snapshot* plus an append-only log: vmn captures the exact working tree the run
executed against — committed or not — assigns it a deterministic version string,
and records metrics against that. There is no server and no database; storage is
files, locally or in S3. `vmn-exp ui` is a reader you start when you want to look at
them.

That difference in origin explains most of what follows. vmn is stronger on
*reproducing* a run and on *knowing whether it is still alive*. MLflow is
stronger on everything downstream of a finished run.

---

## Feature comparison

| Feature | vmn | MLflow |
| --- | --- | --- |
| Params / metrics / notes / artifacts | Yes | Yes |
| Per-step metric series + charts | Yes | Yes |
| Autologging | sklearn, xgboost, keras/tensorflow, lightning, **transformers** (`VmnCallback` via autolog or manually from `vmn_exp.integrations.hf`) | Broader (incl. spark, statsmodels, prophet, LLM libs) |
| Optuna / Ray Tune integration | `start_study_run` + `StudyTracker`; `TuneRecorder` + `VmnTuneCallback` (driver-side) — see `vmn_exp.integrations.*` | Optuna/Ray callbacks available |
| System metrics (CPU/mem/GPU) | Yes, on by default, sampled on the heartbeat (GPU with `pynvml`) | Yes |
| Nested runs | Yes, with a `tree_status` rollup over the subtree | Yes (no rollup) |
| Run status | **Derived** — `created`/`running`/`stuck`/`succeeded`/`failed` | Stored; a dead run can stay `RUNNING` forever |
| Query language | `metrics.loss < 0.5 and params.model = "xgb"`, `inputs.uri ~ s3://`, `env.packages.torch = "2.0.0"` | `search_runs` filter strings |
| Environment capture | **Auto** — Python version, platform, packages captured at run create (`env.yml` + summary) | With logged models (requirements/conda files) |
| Dataset / input tracking | `run.log_input(uri, digest, kind)` / `--input uri` on CLI | `mlflow.log_input(mlflow.data.from_*(...))` |
| Exact source reproduction | **Snapshot of the working tree, dirty included** | Git commit + dirty *flag* |
| Source diff between two runs | `vmn-exp diff` / the Compare page | Not possible — the diff was never stored |
| Import from MLflow | **`vmn-exp import-mlflow`** — FileStore (no deps) or tracking server (`mlflow-skinny`) | — |
| Multi-repo / dependency versions | Built-in (`deps` in conf.yml, `vmn goto`) | Not available |
| Backing store | Files: local filesystem, S3, GCS or Azure Blob | DB-backed tracking server (a local file store exists, but not for teams) |
| Server required | No — `vmn-exp ui` is optional and read-mostly | Yes, for any real deployment |
| Remote logging over HTTP | **No** — clients write to the store directly; nodes without access record offline and `vmn-exp push` later | Yes, the tracking server's REST API |
| Multi-user / permissions | **One bearer token, all-or-nothing** | Users, experiment permissions, auth plugins |
| Model registry (versions, aliases, deprecation) | **Yes** — `vmn-exp model register\|alias\|list\|show\|…`; SDK `register_model`/`set_alias`/`download_model`; UI Models page — see [docs/models.md](models.md) | Yes — a core feature; also has stages approval workflow |
| Model serving / packaging | **Absent** | `mlflow models serve`, pyfunc flavors, SageMaker/Docker targets |
| Artifact rendering in the UI | Logged images, tables and histograms inline; other artifacts download | Inline images, plots, tables, HTML |
| `evaluate()`, LLM/prompt tracing, Projects | **Absent** | Yes |
| Plugin ecosystem | None | Extensive |
| Scale | Cached SQLite index; the UI stays fast at ~100k runs per app | DB-backed; scales with the database |

---

## Where vmn is genuinely ahead

### Reproducibility is structural, not a best-effort annotation

MLflow records the git commit a run started from, plus a flag saying the tree was
dirty. That is enough to find the neighbourhood of a result and not enough to
reproduce it — and a dirty tree is the state most experiments actually run in.

vmn records the diff. A run's version string is computed from HEAD *and* the
patch set, so it is content addressed: the same tree always yields the same
code version. That makes two things possible that MLflow cannot offer:

```sh
vmn-exp restore my_app -v 1.6.0-dev.a1b2c3d.e4f5g6h   # the tree, exactly
vmn-exp diff my_app -v <run_a> -v <run_b>             # why they differ
```

`vmn goto` extends the same guarantee across every tracked dependency
repository, which has no MLflow equivalent at all.

### A dead run does not read as a live one

Status in vmn is derived, never stored. `vmn-exp run` and the SDK publish a
heartbeat into `run_state.yml`; a run that claims to be running, has no exit
code, and whose heartbeat (and the store's write time of that file) is older
than `max(3 × interval, 60s)` is reported as **`stuck`**. Kill
the node, pull the power, `kill -9` the trainer — the dashboard says stuck.

MLflow writes a terminal status on clean exit, so a run that dies without one sits
at `RUNNING` indefinitely. Nested jobs make it worse: vmn rolls a subtree up into
the outer job's `tree_status` (`failed > stuck > running > created > succeeded`),
so one row tells you a sweep has a problem.

### No infrastructure to stand up or keep alive

`pip install vmn-exp-sdk` adds only PyYAML, filelock and psutil and needs no
server, no database, and no daemon. Runs are files; point `vmn-exp ui` at them when you want to
look, or don't. Airgapped, laptop-only, and shared-S3 setups are all the same
code path. MLflow's local file store covers a single user on one machine; anything
shared means running a server plus a database.

### Tracking is continuous with release versioning

The same tool that stamps `1.6.0` for the release records
`1.6.0-dev.a1b2c3d.e4f5g6h` for the experiment. One version namespace across
research and shipping, with no separate ids to reconcile.

---

## Where MLflow is still the right tool

### The model registry approval workflow

vmn has a [model registry](models.md) with versions, aliases, and `active` /
`deprecated` / `deleted` statuses, but it does not have MLflow's stage-transition
approval trail or governance integrations.  If your workflow requires formal sign-
off before a model goes to production, or a plugin that posts Slack notifications
on stage changes, MLflow's registry is more mature.

`autolog(log_models=True)` saves a model artifact; `run.register_model(...)` links
it to a named model version.  What vmn cannot do is serve that model or package it
in a pyfunc flavor.

### Serving and packaging

No `mlflow models serve`, no pyfunc flavors, no SageMaker or Docker deployment
targets. vmn stops at recording what happened.

### Logging from somewhere else

vmn clients write straight to a filesystem or object store. A worker with no
access to either can only record locally (`VMN_EXP_OFFLINE=1`) and upload later
with `vmn-exp push`. MLflow's tracking server accepts runs over HTTP from
anywhere, which is the easier story for heterogeneous or externally-managed
compute.

### More than one kind of user

`vmn-exp ui --token` is a single shared bearer token: everyone who has it can do
everything (unless the whole server is `--read-only`). There are no users and no
per-experiment permissions. MLflow has both.

### Rendering arbitrary artifacts

`vmn-exp ui` renders what was logged with `run.log_image`, `log_table` and
`log_histogram`; any other artifact (an HTML report, a saved plot file) is a
download link. MLflow renders images, plots, tables and HTML artifacts inline.

### Scale, and breadth of integrations

vmn's cached index keeps dashboard reads in milliseconds at ~100k runs per app,
but it is not a database, and we have not tested at the run counts a DB-backed
MLflow serves. MLflow also autologs more frameworks and has a real plugin
ecosystem.

---

## Choosing

| If you… | Use |
| --- | --- |
| Need to reproduce a result exactly, uncommitted changes included | vmn |
| Run experiments across several git repositories | vmn |
| Want to know when a run died, not just when it finished | vmn |
| Don't want to operate a tracking server or a database | vmn |
| Already use vmn for release versioning | vmn |
| Want to import an existing MLflow history | vmn (`vmn-exp import-mlflow`) |
| Need a model registry without a tracking server | vmn (`vmn-exp model`) |
| Need formal stage-transition approval workflow for models | MLflow |
| Need to serve or package a model | MLflow |
| Log live from compute with no store access at all | MLflow |
| Need per-user permissions | MLflow |
| Depend on an autologged framework vmn doesn't cover | MLflow |

The two are not mutually exclusive. vmn's log is plain files with a documented
shape, so a run can be recorded by vmn for reproducibility and mirrored to MLflow
for registry and serving.

## Coming from MLflow

`vmn-exp import-mlflow` brings an existing MLflow history across, and the SDK's
`start_run` / `log_*` calls map almost one-to-one onto `mlflow.*`. The
[migration guide](migrating-from-mlflow.md) has the API and registry mapping
and the differences to know before porting a script.

## Further reading

- [Client guide](client-guide.md) · [vmn-exp tracking guide](experiments.md)
- [vmn Python SDK](sdk.md) · [runnable examples](../../examples/README.md)
- [vmn-exp model registry](models.md)
- [Migrating from MLflow](migrating-from-mlflow.md)
- [vmn-exp ui](ui.md)
- [MLflow documentation](https://mlflow.org/docs/latest/index.html)
