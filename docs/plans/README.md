# MLflow / W&B adoption plans

Status of the 9 candidate features on `master` (after the `feature-parity` merge and
the code-store change, `0096782`).

| # | Feature | Status on master | Plan |
|---|---|---|---|
| 1 | `vmn-exp rerun` (MLflow Projects / W&B Launch) | missing | [01-exp-rerun.md](01-exp-rerun.md) |
| 2 | Console output capture (W&B `output.log`) | **done** (`cli/output_tee.py`, SDK `capture_output=True`) | — |
| 3 | Alerts on status transitions (`wandb.alert`, MLflow webhooks) | **done** (`run.alert()`, `vmn-exp watch`, `core/alerts/`) | — |
| 4 | `define_metric` + summaries | mostly done; missing `first`/`mean`, `hidden`, cross-run declared goals | [04-metric-defs-autostep-disabled.md](04-metric-defs-autostep-disabled.md) |
| 4b | Auto-incrementing step (W&B `_step`) | missing | same file |
| 5 | DataFrame reader (`search_runs`, `run.history()`) | **done** (`sdk/frames.py`) | — |
| 6 | Lineage | run-level done; missing datasets + model/dataset use edges | [06-datasets-usage.md](06-datasets-usage.md) |
| 7 | Disabled mode (`WANDB_MODE=disabled`) | missing | [04-metric-defs-autostep-disabled.md](04-metric-defs-autostep-disabled.md) |
| 8 | Step media / histograms | done; missing `watch(model)` for plain torch | [08-torch-watch.md](08-torch-watch.md) |
| 9 | Offline record + `vmn-exp push` (`wandb sync`) | missing | [09-offline-push.md](09-offline-push.md) |
| 10 | `vmn snapshot` back as a vmn command (experiments reuse it) | removed in d4954f8; being reintroduced | [10-vmn-snapshot.md](10-vmn-snapshot.md) |
| 11 | Central server: on-prem + BYO-bucket SaaS, DB cache, change journal, SSO/roles | design | [11-central-server.md](11-central-server.md) |
| 12 | Columnar metric storage: binary streams + indexed files with LOD, range reads, zoom | design | [12-columnar-metrics.md](12-columnar-metrics.md) |
| 13 | Reports (markdown + live panels, publish/export) and comments | design | [13-reports-comments.md](13-reports-comments.md) |
| 14 | Store layout v2: top-level areas, one layout for all backends, `store.yml`, `vmn-exp migrate` (fixes runs/snapshots key collision) | proposal — do before 11–13 | [14-store-layout.md](14-store-layout.md) |

Paths in the plans are repo paths under `packages/` (re-verified against `0096782`).

Architecture rule (revised 2026-10-02, see [11-central-server.md §2](11-central-server.md#2-invariants)):
**storage is the source of truth; everything else is rebuildable from it, and training never
depends on the server being up.** A server (and a database as cache) is allowed; clients write
straight to storage with their own storage access (the server never issues credentials). It replaces the earlier
"no server in the data path" rule.
