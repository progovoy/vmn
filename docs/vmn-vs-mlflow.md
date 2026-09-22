# vmn vs MLflow

> [vmn](https://github.com/progovoy/vmn)'s experiment tracking (`vmn exp`, the
> `version_stamp.exp` Python SDK, and the `vmn ui` dashboard) overlaps with
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
files, locally or in S3. `vmn ui` is a reader you start when you want to look at
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
| Autologging | sklearn, xgboost, keras/tensorflow, lightning | Broader (incl. spark, statsmodels, prophet, LLM libs) |
| System metrics (CPU/mem/GPU) | Yes, on the heartbeat | Yes |
| Nested runs | Yes, with a `tree_status` rollup over the subtree | Yes (no rollup) |
| Run status | **Derived** — `created`/`running`/`stuck`/`succeeded`/`failed` | Stored; a dead run can stay `RUNNING` forever |
| Query language | `metrics.loss < 0.5 and params.model = "xgb"` | `search_runs` filter strings |
| Exact source reproduction | **Snapshot of the working tree, dirty included** | Git commit + dirty *flag* |
| Source diff between two runs | `vmn exp diff` / the Compare page | Not possible — the diff was never stored |
| Multi-repo / dependency versions | Built-in (`deps` in conf.yml, `vmn goto`) | Not available |
| Backing store | Files: local filesystem or S3 | DB-backed tracking server (a local file store exists, but not for teams) |
| Server required | No — `vmn ui` is optional and read-mostly | Yes, for any real deployment |
| Remote logging over HTTP | **No** — clients write to a filesystem or S3 | Yes, the tracking server's REST API |
| Multi-user / permissions | **One bearer token, all-or-nothing** | Users, experiment permissions, auth plugins |
| Model registry (versions, stages, aliases) | **Absent** | Yes — a core feature |
| Model serving / packaging | **Absent** | `mlflow models serve`, pyfunc flavors, SageMaker/Docker targets |
| Artifact rendering in the UI | **Download only** | Inline images, plots, tables, HTML |
| `evaluate()`, LLM/prompt tracing, Projects | **Absent** | Yes |
| Plugin ecosystem | None | Extensive |
| Scale | SQLite index over snapshot metadata | DB-backed; handles far larger run counts |

---

## Where vmn is genuinely ahead

### Reproducibility is structural, not a best-effort annotation

MLflow records the git commit a run started from, plus a flag saying the tree was
dirty. That is enough to find the neighbourhood of a result and not enough to
reproduce it — and a dirty tree is the state most experiments actually run in.

vmn records the diff. A run's id is computed from HEAD *and* the patch set
(`_compute_verstr(base_version, commit_hash, patches)`), so it is content
addressed: the same tree always yields the same base version string. That makes
two things possible that MLflow cannot offer:

```sh
vmn exp restore my_app -v 1.6.0-dev.a1b2c3d.e4f5g6h   # the tree, exactly
vmn exp diff my_app -v <run_a> -v <run_b>             # why they differ
```

`vmn goto` extends the same guarantee across every tracked dependency
repository, which has no MLflow equivalent at all.

### A dead run does not read as a live one

Status in vmn is derived, never stored. `vmn exp run` and the SDK publish a
heartbeat into `run_state.yml`; a run that claims to be running but has not beaten
in `max(3 × interval, 60s)` and has no exit code is reported as **`stuck`**. Kill
the node, pull the power, `kill -9` the trainer — the dashboard says stuck.

MLflow writes a terminal status on clean exit, so a run that dies without one sits
at `RUNNING` indefinitely. Nested jobs make it worse: vmn rolls a subtree up into
the outer job's `tree_status` (`failed > stuck > running > created > succeeded`),
so one row tells you a sweep has a problem.

### No infrastructure to stand up or keep alive

`pip install "vmn[exp]"` adds no third-party dependency and needs no server, no
database, and no daemon. Runs are files; point `vmn ui` at them when you want to
look, or don't. Airgapped, laptop-only, and shared-S3 setups are all the same
code path. MLflow's local file store covers a single user on one machine; anything
shared means running a server plus a database.

### Tracking is continuous with release versioning

The same tool that stamps `1.6.0` for the release records
`1.6.0-dev.a1b2c3d.e4f5g6h` for the experiment. One version namespace across
research and shipping, with no separate ids to reconcile.

---

## Where MLflow is still the right tool

### The model registry

This is the big one, and it is simply absent from vmn. MLflow gives model
versions, stage transitions (staging → production), aliases, and an approval
trail. If your workflow ends in *promoting a model*, that machinery is the reason
teams stay on MLflow, and nothing in vmn replaces it. `autolog(log_models=True)`
saves a model in its native format; vmn will not load, version, or promote it.

### Serving and packaging

No `mlflow models serve`, no pyfunc flavors, no SageMaker or Docker deployment
targets. vmn stops at recording what happened.

### Logging from somewhere else

vmn clients write to a filesystem or to S3. A worker with neither a shared mount
nor S3 credentials has nowhere to log. MLflow's tracking server accepts runs over
HTTP from anywhere, which is the easier story for heterogeneous or
externally-managed compute.

### More than one kind of user

`vmn ui --token` is a single shared bearer token: everyone who has it can do
everything (unless the whole server is `--read-only`). There are no users and no
per-experiment permissions. MLflow has both.

### Seeing artifacts without downloading them

`vmn ui` lists artifacts as download links. A run that plots a confusion matrix
makes you download the PNG to look at it; MLflow renders images, plots, tables,
and HTML inline.

### Scale, and breadth of integrations

vmn's SQLite index keeps dashboard reads cheap, but listing still walks snapshot
metadata, and we have not tested at the run counts a DB-backed MLflow serves.
MLflow also autologs more frameworks and has a real plugin ecosystem.

---

## Choosing

| If you… | Use |
| --- | --- |
| Need to reproduce a result exactly, uncommitted changes included | vmn |
| Run experiments across several git repositories | vmn |
| Want to know when a run died, not just when it finished | vmn |
| Don't want to operate a tracking server or a database | vmn |
| Already use vmn for release versioning | vmn |
| Ship models through staging to production | MLflow |
| Need to serve or package a model | MLflow |
| Log from compute without shared storage or S3 credentials | MLflow |
| Need per-user permissions | MLflow |
| Depend on an autologged framework vmn doesn't cover | MLflow |

The two are not mutually exclusive. vmn's log is plain files with a documented
shape, so a run can be recorded by vmn for reproducibility and mirrored to MLflow
for registry and serving.

## Coming from MLflow

MLflow's core loop maps over closely:

```python
# MLflow                                  # vmn
with mlflow.start_run():                  with start_run("my_app") as run:
    mlflow.log_params({"lr": 3e-4})           run.log_params({"lr": 3e-4})
    mlflow.log_metric("loss", x, step=i)      run.log_metric("loss", x, step=i)
    mlflow.log_artifact("model.pt")           run.log_artifact("model.pt")
mlflow.sklearn.autolog()                  autolog()   # all frameworks at once
mlflow.search_runs(filter_string=...)     list_runs("my_app", query=...)
```

Differences worth knowing before you port a script:

- **A run needs a git repo with a remote and a usable git identity** — creating
  one snapshots the tree, which means a commit-shaped write. Set `user.name` and
  `user.email` (or `GIT_AUTHOR_*`) in containers.
- **`autolog()` records nothing unless a run is open.** It never opens one
  implicitly: that would stamp a version from inside `fit()`.
- **Metric keys from autolog are prefixed** `<framework>_<name>`, so the query
  language's two-part paths resolve them.
- **`run.id` is a verstr**, not a uuid — and it is the same string `vmn exp
  restore` and `vmn goto` take.

## Further reading

- [vmn experiment tracking guide](experiments.md)
- [vmn Python SDK](sdk.md) · [runnable examples](../examples/README.md)
- [vmn ui](ui.md)
- [MLflow documentation](https://mlflow.org/docs/latest/index.html)
