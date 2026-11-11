# vmn-exp

Local-first experiment tracking built on [vmn](../../README.md): every run is
a snapshot of your code plus an append-only log of metrics and notes, stored
as plain files locally or in an object store (S3, GCS, Azure).

**Storage is the source of truth; training never depends on a server.** No
server or database is required to record or read runs, and the optional team
server ([server.md](server.md)) keeps only a rebuildable cache.

## Quickstart

Work inside a git repo with at least one commit and a git identity
(`user.name`/`user.email`); a throwaway one is fine:

```sh
pip install "vmn-exp[ui]"        # [ui] is the dashboard; add [s3] for buckets
git init demo && cd demo && git commit --allow-empty -m init
```

Save this as `train.py`:

```python
from vmn_exp.sdk import start_run

with start_run("my_app") as run:
    for step in range(5):
        run.log_metric("loss", 1.0 / (step + 1), step=step)
    print(run.id)
```

```sh
python train.py
vmn-exp list my_app --sort loss
vmn-exp ui                       # http://127.0.0.1:8265
```

The first run cold-starts tracking: it commits vmn's init files (`.vmn/`) and
tags the baseline `my_app_0.0.0` in your local repo; nothing is pushed.

- A script you cannot edit: `vmn-exp run my_app -- python train.py`. When
  it is the app's first run and the repo has a remote, it also pushes the
  baseline commit and tag to that remote.
- No git checkout (a container, a notebook): see
  [Runs without a git checkout](sdk.md#runs-without-a-git-checkout-containers).
- Jobs that only record metrics need just `pip install vmn-exp-sdk`
  (see [packaging](../packaging.md)).

## Guides

- [Runnable examples](../../packages/vmn-exp/examples/README.md) — five small SDK scripts.
- [Architecture](architecture.md) — diagrams: how vmn, the SDK, the CLI, the
  dashboard and the store fit together, and how clients use them.
- [Client guide](client-guide.md) — start here: a project end to end (store,
  submit, SDK in the job, watch, compare, reproduce, resume/rewind/fork, models,
  cleanup).
- [Notebooks](notebooks.md) — one run across cells, re-run cells, kernel
  restarts, and what the snapshot captures.
- [Migrating from MLflow](migrating-from-mlflow.md) and
  [vmn-exp vs MLflow](vmn-vs-mlflow.md).
- [Driving the UI fleet counts](ai-fleet-tracking.md) — for AI agents
  orchestrating pods.
- [AI agent skill](agent-skill.md) — what `vmn-exp skill` prints; install it
  with `vmn-exp skill --install [--target claude|cursor|agents]`.

## Reference

| Doc | Covers |
|---|---|
| [experiments.md](experiments.md) | the `vmn-exp` CLI, run status and alerts, nesting, similar runs and intents, storage, offline recording and `push` |
| [sdk.md](sdk.md) | the `vmn_exp.sdk` Python SDK: `start_run`, logging, autolog, readers, query language, integrations |
| [ui.md](ui.md) | `vmn-exp ui`: deployment and the HTTP API |
| [models.md](models.md) | the model and dataset registry |
| [sweeps.md](sweeps.md) | `vmn-exp sweep`: grid/random/bayes search |
| [server.md](server.md) | `vmn-exp ui` as a team server: `server.yml`, cache, change journal, resync/rebuild, OIDC, API tokens, roles |
| [byo-bucket.md](byo-bucket.md) | bring-your-own-bucket: store areas, the server's read-only and read + edits permission sets, journal lifecycle rule |
| [reports.md](reports.md) | reports (`vmn-panel` blocks, revisions, publish, HTML export) and comments |
| [upgrading.md](upgrading.md) | the patch-only release rules, behaviour changes (removals included) and format changes per release |

Saving and restoring uncommitted work without a run is core vmn:
[`vmn snapshot`](../snapshots.md).
