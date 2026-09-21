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
- [Finishing, failures, and the heartbeat](#finishing-failures-and-the-heartbeat)
- [Nesting](#nesting)
- [Reading runs back](#reading-runs-back)
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
    print(run.id)

best = get_run("my_app", ref="latest")
```

- `list_runs(app_name=None, storage=None, sort=None, last=None, status=None)` —
  `sort` picks the metric to order by (the configured [primary
  metric](experiments.md#metrics-schema-sorting--goals) when omitted), `last`
  caps the result count, `status` filters to one derived status.
- `get_run(app_name=None, ref="latest", storage=None)` — `ref` takes any
  [addressing form](experiments.md#addressing-experiments): a full verstr, a
  unique prefix, `@N`, or `latest`.

As on the write side, `app_name=None` resolves from the current repo.

---

## Library logging

The SDK emits stdlib `logging` records under the `version_stamp.exp` logger and
never configures handlers — it is a library, so what happens to the records is
your application's call. To see its debug output:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```
