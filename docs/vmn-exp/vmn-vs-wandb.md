# vmn vs Weights & Biases

> [vmn](https://github.com/progovoy/vmn)'s experiment tracking (`vmn-exp`, the
> `vmn_exp.sdk` Python SDK, and the `vmn-exp ui` dashboard) overlaps with
> [Weights & Biases](https://wandb.ai/) (W&B). This page is an honest
> comparison, including what W&B does that vmn does not. It compares features,
> not performance.

## Overview

**W&B** is a hosted ML platform: runs, metrics and media logged over HTTP to
the W&B service (a multi-tenant cloud, a dedicated cloud, or W&B Server run on
your own infrastructure), with Artifacts, a Registry, Sweeps, Reports, and
Weave for tracing LLM applications. Its centre of gravity is a shared
workspace where a team watches and compares runs.

**vmn** approaches tracking from the versioning side. An experiment is a
*snapshot* plus an append-only log: vmn captures the exact working tree the run
executed against, committed or not, assigns it a deterministic version string,
and records metrics against that. Runs are plain files, locally or in an object
store (S3, GCS, Azure), written by the job itself. No server or database is
required to record or read them; `vmn-exp ui` is a reader you start when you
want to look, and the optional team server ([server.md](server.md)) keeps only
a rebuildable cache.

That difference explains most of what follows. vmn is stronger on
*reproducing* a run and on running with nothing to operate. W&B is stronger on rich media, hosted collaboration
and anything that needs a service in the middle.

---

## Feature comparison

| Feature | vmn | W&B |
| --- | --- | --- |
| Params / metrics / notes / artifacts | Yes | Yes |
| Per-step metric series + charts | Yes | Yes |
| Custom x axis, metric goals and summaries | `define_metric(step_metric=, goal=, summary=, hidden=)` | `define_metric` |
| Media | Tables, images, histograms | Images, tables, histograms, audio, video, HTML, 3D objects, molecules |
| Alerts | `run.alert()` to configured sinks ([experiments.md](experiments.md#alerts)) | `run.alert()` to Slack or email |
| Sweeps | `vmn-exp sweep`: grid, random, bayes; median-rule and ASHA early stopping; agents coordinate through the store, no sweep server | Grid, random, bayes; Hyperband early termination; a sweep controller in the W&B service |
| Gradient / parameter histograms | `watch(model)` from `vmn_exp.integrations.torch_watch` | `wandb.watch(model)` |
| Forking, rewinding, resuming | `fork_from`, rewind, resume | `fork_from`, rewind (`resume_from`, in preview), resume |
| Run status | **Derived**: `created`/`running`/`stuck`/`succeeded`/`failed`; a run whose heartbeat stopped reads `stuck` | Kept by the service; a run whose heartbeats stop is marked crashed |
| Exact source reproduction | **Snapshot of the working tree, dirty included**; `vmn-exp restore`, `vmn-exp diff` | Git commit, plus a diff patch and code files when code saving is on |
| Multi-repo / dependency versions | Built-in (`deps` in conf.yml, `vmn goto`) | Not available |
| Backing store | Files: local filesystem, S3, GCS or Azure Blob, written by the job | The W&B service (its database and object storage) |
| Server required | No: `vmn-exp ui` is optional and read-mostly | Yes: the hosted service or a self-managed W&B Server |
| Remote logging over HTTP | **No**: clients write to the store directly; nodes without access record offline and `vmn-exp push` later | Yes, the default |
| Offline recording | `VMN_EXP_OFFLINE=1`, then `vmn-exp push` | `WANDB_MODE=offline`, then `wandb sync` |
| Multi-user / permissions | Standalone: one bearer token. Configured server: OIDC sign-in, API tokens, per-workspace `viewer`/`editor`/`admin` roles ([server.md](server.md#roles)) | Teams with roles; per-project visibility (open, public, team, restricted) |
| Model and dataset registry | **Yes**: `vmn-exp model`, SDK `register_model`/`use_model`/`use_dataset` ([models.md](models.md)) | Artifacts and the Registry |
| Reports | `vmn-panel` blocks, revisions, publish, HTML export ([reports.md](reports.md)) | Reports |
| LLM / agent tracing | **Absent** | Weave |
| Import from W&B | **No importer yet** | n/a |

---

## Where vmn is genuinely ahead

### Reproducibility is structural

W&B records the commit a run started from and can save a diff patch and code
files alongside it; restoring that state is a manual job. vmn's run version is
computed from HEAD *and* the patch set, so the same tree always yields the same
code version, and the tree comes back with one command:

```sh
vmn-exp restore my_app -v 1.6.0-dev.a1b2c3d.e4f5g6h   # the tree, exactly
vmn-exp diff my_app -v <run_a> -v <run_b>             # why they differ
```

`vmn goto` extends that across every tracked dependency repository. The run
page's **Changes** card shows the files, param edits and metric deltas against
a baseline you pick, and a failed run links to what changed *since last good*.

### Liveness without a service

W&B marks a run crashed when the service stops hearing its heartbeats. vmn gets
the same answer with no service: status is derived from the run's heartbeat and
the store's write time, never stored, so any reader of the store, the CLI
included, says **`stuck`** once the heartbeat is past its stuck window. Nested
jobs roll up into the outer job's `tree_status`, so one row tells you a sweep
has a problem ([experiments.md](experiments.md#run-status-did-my-job-die)).

### Nothing to operate, nothing to call home

`pip install vmn-exp-sdk` adds only PyYAML, filelock and psutil. Runs are files
in a directory or a bucket you already have; airgapped, laptop-only and
shared-bucket setups are the same code path, and no run data leaves your
storage. A W&B setup needs the hosted service, or a W&B Server you run,
upgrade and back up.

### Sweeps without a sweep server

`vmn-exp sweep agent` processes on Slurm, Kubernetes or a few shells coordinate
through atomic claims in the store, so any machine that can reach the store can
run trials and a dead agent's trial is retried ([sweeps.md](sweeps.md)).

### Tracking is continuous with release versioning

The same tool that stamps `1.6.0` for the release records
`1.6.0-dev.a1b2c3d.e4f5g6h` for the experiment: one version namespace across
research and shipping.

---

## Where W&B is the right tool

Each gap is labelled with what vmn intends to do about it: **planned**, **not
planned**, or **not offered by design**.

### A hosted service

W&B runs the service for you; nothing to deploy, and sharing a run is sending a
link. vmn-exp is software you run against your own storage. **Not planned.**

### Logging over HTTP from anywhere

A W&B client needs only network access to the service. A vmn client writes to
a filesystem or object store; a worker with access to neither records locally
(`VMN_EXP_OFFLINE=1`) and uploads later with `vmn-exp push`
([experiments.md](experiments.md#offline-recording-and-push)). **Not offered by
design**: training never depends on a server.

### Rich media

W&B logs and renders audio, video, HTML, 3D objects and molecules. vmn renders
tables, images and histograms ([sdk.md](sdk.md#tables-images-and-histograms));
anything else is an artifact you download. HTML and audio: **not planned**.
Video: **not planned**.

### Hyperband

W&B early-terminates sweep trials with Hyperband. vmn has the median rule
([sweeps.md](sweeps.md#median-rule)) and ASHA, asynchronous successive
halving in one bracket (`early_terminate: {type: asha}`,
[sweeps.md](sweeps.md#asha)). Full Hyperband with several brackets:
**not planned**.

### LLM and agent traces

W&B Weave traces and evaluates LLM applications. **Not offered by design**: a
different product.

### Per-project permissions

W&B projects can be restricted to invited team members. vmn's roles are per
workspace ([server.md](server.md#roles)); today the answer is one workspace per
project. Per-project permissions: **not planned**.

### Smaller gaps in vmn

- LightGBM and CatBoost autolog: **planned** (today: scikit-learn, XGBoost,
  Keras, Lightning, Transformers; [sdk.md](sdk.md#autologging)).
- Autologging a plain PyTorch loop: **not offered by design**; use `watch()`
  plus `log_metric` ([sdk.md](sdk.md#pytorch--watch)).

---

## API mapping

| W&B | vmn-exp |
| --- | --- |
| `wandb.init(project=..., config={...})` | `start_run("my_app", params={...})` ([sdk.md](sdk.md#starting-a-run)) |
| `wandb.config.update({...})` | `run.log_params({...})` |
| `wandb.log({"loss": l}, step=s)` | `run.log_metrics({"loss": l}, step=s)` |
| `wandb.Table` / `wandb.Image` / `wandb.Histogram` | `run.log_table` / `run.log_image` / `run.log_histogram` |
| `run.log_artifact(...)` / `run.use_artifact(...)` | `run.log_artifact(path)` / `run.use_artifact(ref, path)` |
| `run.alert(title, text, level, wait_duration)` | `run.alert(title, text, level, wait_sec)` ([sdk.md](sdk.md#alerts)) |
| `run.define_metric(name, step_metric=..., summary=..., goal=...)` | `run.define_metric(name, step_metric=..., summary=..., goal=...)` ([sdk.md](sdk.md#custom-x-axis-step_metric)) |
| `wandb.watch(model, log="gradients")` | `watch(model, log="gradients")` from `vmn_exp.integrations.torch_watch` |
| `wandb.init(fork_from=...)` | `start_run(..., fork_from=...)` ([sdk.md](sdk.md#forking-a-run)) |
| `wandb sweep config.yaml` / `wandb agent <id>` | `vmn-exp sweep create my_app -f sweep.yml` / `vmn-exp sweep agent my_app <ref>` |
| `wandb.config` inside a sweep trial | `sweep_params()` ([sdk.md](sdk.md#sweep-trials-sweep_params)) |
| `WANDB_MODE=offline` + `wandb sync` | `VMN_EXP_OFFLINE=1` + `vmn-exp push` |
| `WANDB_MODE=disabled` | `VMN_MODE=disabled` ([sdk.md](sdk.md#disabled-mode)) |

There is no W&B importer yet: an existing W&B history stays in W&B.

---

## Choosing

| If you… | Use |
| --- | --- |
| Need to reproduce a result exactly, uncommitted changes included | vmn |
| Run experiments across several git repositories | vmn |
| Can't or won't send run data to a service, or want nothing to operate | vmn |
| Already use vmn for release versioning | vmn |
| Want a hosted service someone else runs | W&B |
| Log from compute with no access to any shared storage | W&B |
| Log audio, video, HTML or 3D media | W&B |
| Trace LLM applications | W&B |
| Need per-project permissions | W&B |

## Further reading

- [Client guide](client-guide.md) · [vmn-exp tracking guide](experiments.md)
- [vmn Python SDK](sdk.md) · [Sweeps](sweeps.md) · [Notebooks](notebooks.md)
- [vmn-exp vs MLflow](vmn-vs-mlflow.md)
- [W&B documentation](https://docs.wandb.ai/)

## Sources

The W&B column was checked against the W&B documentation (Python SDK 0.31.0)
on 2026-11-11. The docs now live under docs.coreweave.com; docs.wandb.ai
redirects there.

- [Deployment options](https://docs.coreweave.com/guides/hosting/): multi-tenant cloud, dedicated cloud, self-managed W&B Server.
- [Log media and objects](https://docs.coreweave.com/guides/track/log/media/): the media types.
- [Send an alert](https://docs.coreweave.com/guides/runs/alert/): `run.alert()`, Slack and email.
- [Environment variables](https://docs.coreweave.com/guides/track/environment-variables/): `WANDB_MODE`.
- [wandb sync](https://docs.coreweave.com/ref/cli/wandb-sync/): uploading offline runs.
- [Project access control](https://docs.coreweave.com/guides/hosting/iam/access-management/restricted-projects/): open, public, team and restricted projects.
- [Sweep configuration](https://docs.wandb.ai/guides/sweeps/sweep-config-keys): methods and Hyperband `early_terminate`.
- [Weave](https://docs.coreweave.com/weave/): tracing and evaluating LLM applications.
- [Why is my run showing as crashed](https://docs.wandb.ai/support/models/articles/why-is-my-run-showing-as-crashed.md): heartbeats and the crashed state.
- [Rewind a run](https://docs.wandb.ai/guides/runs/rewind): `resume_from`, private preview; `fork_from`.
