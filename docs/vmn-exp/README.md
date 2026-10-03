# vmn-exp

Local-first experiment tracking built on [vmn](../../README.md): every run is
a snapshot of your code plus an append-only log of metrics and notes, stored
as plain files locally or in an object store (S3, GCS, Azure). No server, no
database.

```sh
pip install vmn-exp              # "vmn-exp[ui]" adds the dashboard, [s3] for buckets
vmn-exp run my_app -- python train.py
vmn-exp list my_app --sort loss
vmn-exp ui
```

Jobs that only record metrics need just `pip install vmn-exp-sdk`
(see [packaging](../packaging.md)).

## Guides

- [Client guide](client-guide.md) — start here: a project end to end (store,
  submit, SDK in the job, watch, compare, reproduce, resume/rewind/fork, models,
  cleanup).
- [Runnable examples](../../packages/vmn-exp/examples/README.md) — five small SDK scripts.
- [Migrating from MLflow](migrating-from-mlflow.md) and
  [vmn-exp vs MLflow](vmn-vs-mlflow.md).
- [Driving the UI fleet columns](ai-fleet-tracking.md) — for AI agents
  orchestrating pods.
- [AI agent skill](agent-skill.md) — what `vmn-exp skill` prints; install it
  with `vmn-exp skill --install [--target claude|cursor|agents]`.

## Reference

| Doc | Covers |
|---|---|
| [experiments.md](experiments.md) | the `vmn-exp` CLI, run status and alerts, nesting, storage, offline recording and `push` |
| [sdk.md](sdk.md) | the `vmn_exp.sdk` Python SDK: `start_run`, logging, autolog, readers, query language, integrations |
| [ui.md](ui.md) | `vmn-exp ui`: deployment and the HTTP API |
| [models.md](models.md) | the model and dataset registry |
| [sweeps.md](sweeps.md) | `vmn-exp sweep`: grid/random/bayes search |
| [server.md](server.md) | `vmn-exp ui` as a team server: `server.yml`, cache, change journal, resync/rebuild, OIDC, API tokens, roles |
| [byo-bucket.md](byo-bucket.md) | bring-your-own-bucket: store areas, the server's read-only and read + edits permission sets, journal lifecycle rule |
| [reports.md](reports.md) | reports (`vmn-panel` blocks, revisions, publish, HTML export) and comments |

Saving and restoring uncommitted work without a run is core vmn:
[`vmn snapshot`](../snapshots.md).
