# Driving the UI's fleet counts (for AI agents)

`vmn-exp ui` opens an app on its **Outer runs** view: one row per **outer
run** (a run that has inner runs, `kind = "outer"`), carrying the fleet's
counts on its run bar, e.g. `16/20 · 1 failed · 2 stuck · 3/min · ETA 2m`. The
outer run's page shows the same counts in its header and Overview tiles. The
counts cover the outer run's whole subtree (nested outer runs included).
This page tells an agent which call moves each count.
`vmn-exp skill` prints a short version of it.

There is no API that sets these counts. Each is counted from the inner runs'
states on every refresh, so you change a count by moving an inner run through
its lifecycle. The one exception is the bar's lead number: an outer run can
[declare its own progress](#declaring-the-outer-runs-own-progress).

## What each count covers

| Count | Counts inner runs that are… | Status behind it |
|---|---|---|
| total | all of them | — |
| waiting | registered, not started | `created` |
| running | started, heartbeat fresh | `running` |
| done | finished with exit code 0 | `succeeded` |
| failed | finished non-zero | `failed` |
| stuck | silent too long, no exit code | `stuck` |

Under a filter, a group's counts cover only its inner runs that match.

Status is derived from `run_state.yml`; a run is `stuck` once its heartbeat is
older than `max(3 × heartbeat interval, 60s)` with no exit code (see
[experiments.md](experiments.md#run-status-did-my-job-die)).

**total** on the group header is the number of inner runs. The run detail's
`fleet` block also reads the outer run's `expected_pods` param: `expected` is
the larger of `expected_pods` and the inner-run count, `counts.waiting` is the
declared pods not registered yet, and registered-but-not-started pods are under
`counts.created`. To get the same numbers in both places from the start, set
`expected_pods` **and** register every pod up front.

## The lifecycle, call by call

```python
from vmn_exp.sdk import create_run, start_run

# 1. The outer run: the group header the counts appear on.
outer = start_run("my_app", name="lr-sweep", params={"expected_pods": 3})

# 2. Register each pod before it starts: total +1, waiting +1.
#    Inside the outer run no parent= is needed; returns the pod's verstr.
pod_ids = [create_run("my_app", name=f"pod{i}") for i in range(3)]
```

From a shell, step 2 is `vmn-exp create my_app --name pod0 --parent <outer verstr>`.
`create_run(app_name, name=, params=, tags=, note=, parent=)` opens nothing (no
heartbeat, no thread); its parent is `parent=`, else the calling context's open
run, else `$VMN_EXPERIMENT_ID`. For hundreds of pods, `create_runs(app_name,
[{"name": ..., "params": ..., "tags": ...}, ...])` registers them in one batch
([sdk.md](sdk.md#many-at-once-create_runs)).

```python
# 3. On the worker: reopen the registered pod.   waiting -1, running +1
pod = start_run("my_app", run_id="<pod verstr>")
pod.log_metric("loss", 0.42)

# 4a. Success.                                    running -1, done +1
pod.finish()                  # exit_code=0

# 4b. Failure.                                    running -1, failed +1
pod.finish(exit_code=1)       # any non-zero code
```

`run_id=` also falls back to `$VMN_RESUME_RUN_ID`, so a scheduler can hand each
worker its pod through the environment instead of an argument.

Prefer the context manager on workers. An exception inside the block records
`failed` (exit code 1), and `sys.exit(n)` records `n`:

```python
with start_run("my_app", run_id=pod_id) as pod:
    train(pod)
```

If a worker dies without calling `finish()` (OOM kill, lost node), its heartbeat
stops. After the stale window the pod counts as **stuck**. Nothing
has to report it.

## Starting pods straight in `running`

You can skip step 2 when you don't need the waiting count. Each of these creates
the inner run already running, so total and running both go up by one:

```python
with start_run("my_app", nested=True) as pod:   # inside the outer run's context
    ...
pod = start_run("my_app", parent=outer_id)      # from any process
```

```sh
vmn-exp run my_app --parent <outer verstr> -- python train.py
```

Any experiment created while `VMN_EXPERIMENT_ID` is set is parented to that run
automatically. That includes every `start_run()` and `vmn-exp` call inside
`vmn-exp run my_app -- ./sweep.sh`.

## Declaring the outer run's own progress

When inner runs are created as work gets planned (a walk-forward that plans
each date's studies when it reaches the date), the run count is no
denominator: `1,412/2,000` says nothing about how many dates are left. Declare
the real one on the outer run:

```python
outer.set_progress(41, 60, unit="dates")   # metrics progress / progress_total, param progress_unit
```

The bar then fills 41/60, the line reads `41/60 dates · 1,415 runs · 3 failed ·
20 dates/h · ETA 14m`, and the rate and ETA are the declared progress since the
outer run started. The Overview's done tile reads `41 of 60 dates`, with a
`runs done` tile beside it. Logging the metrics `progress` and `progress_total`
yourself (`log_metrics`, or a numeric `progress_total` param) does the same; both
must be finite and the total positive. A nested outer run (a study) can declare
its own the same way. The waiting/running/done/failed/stuck counts are unchanged.

## Reading the numbers back

The UI's numbers come from the same rows the SDK reads:

```python
from vmn_exp.sdk.reader import list_runs

row = next(r for r in list_runs("my_app") if r["verstr"] == outer_id)
row["children"]       # inner-run verstrs (len = total)
row["child_counts"]   # e.g. {"created": 1, "running": 1, "succeeded": 1}
row["tree_status"]    # rollup: failed > stuck > running > created > succeeded
```

Once the outer run has ended (succeeded, failed, or stuck because the
orchestrator died), the pods it registered but never started are settled
`never_started` and its stuck pods `lost` (a row's `settled` field; their own
`status` and `child_counts` stay): `tree_status` leaves the never-started ones
out and counts a lost one as `failed`, and the waiting/stuck counts drop them.
A pod still heart-beating then is `outlived`: it counts as running, and the
UI's attention strip flags it (`settled = "outlived"`).
No terminal state needs writing for pods the orchestrator deleted.

Over HTTP, `GET /api/v1/workspaces/{ws}/apps/{app}/experiments` returns the same
`children`/`child_counts`. The detail endpoint `.../experiments/{verstr}` adds
`fleet`: `expected`, `counts` (per status, plus `waiting`) and, once the outer
run ended, `never_started` (its never-started pods and slots) and `lost`. See
[ui.md](ui.md#api).

## Checklist for an agent

- Create the outer run first, and keep its verstr (`outer.id`).
- Register every pod (`create_run()`, `create_runs()` for many, or `vmn-exp create --parent`) before dispatching, if the waiting count matters.
- Start each pod with `start_run(run_id=...)` (or `VMN_RESUME_RUN_ID`) on the worker.
- End it with `finish()` / `finish(exit_code=n)`, or use `with` so a crash is recorded.
- Never write `run_state.yml` by hand. The heartbeat and exit code are what the counts read.
