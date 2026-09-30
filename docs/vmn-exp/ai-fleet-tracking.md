# Driving the UI's fleet columns (for AI agents)

`vmn-exp ui` shows five management columns on every **outer run** (a run that has
inner runs): **total**, **waiting**, **running**, **done**, **failed**. This page
tells an agent which call moves each one. `vmn-exp skill` prints a short version of it.

There is no API that sets these numbers. Each is counted from the inner runs'
states on every refresh, so you change a column by moving an inner run through
its lifecycle.

## What each column counts

| Column | Counts inner runs that are… | Status behind it |
|---|---|---|
| total | all of them | — |
| waiting | registered, not started | `created` |
| running | started, heartbeat fresh | `running` |
| done | finished with exit code 0 | `succeeded` |
| failed | finished non-zero, or silent too long | `failed` + `stuck` |

Status is derived from `run_state.yml`; a run is `stuck` once its heartbeat is
older than `max(3 × heartbeat interval, 60s)` with no exit code (see
[experiments.md](experiments.md#run-status-did-my-job-die)).

**total** on the leaderboard is the number of inner runs. The run detail's
`fleet` block also reads the outer run's `expected_pods` param: `expected` is
the larger of `expected_pods` and the inner-run count, `counts.waiting` is the
declared pods not registered yet, and registered-but-not-started pods are under
`counts.created`. To get the same numbers in both places from the start, set
`expected_pods` **and** register every pod up front.

## The lifecycle, call by call

```python
from vmn_exp.sdk import start_run

# 1. The outer run: the row the columns appear on.
outer = start_run("my_app", name="lr-sweep", params={"expected_pods": 3})
```

```sh
# 2. Register each pod before it starts: total +1, waiting +1.
vmn-exp create my_app --name pod0 --parent <outer verstr>
```

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
stops. After the stale window the pod counts under **failed** as `stuck`. Nothing
has to report it.

## Starting pods straight in `running`

You can skip step 2 when you don't need the waiting column. Each of these creates
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

## Reading the numbers back

The UI's numbers come from the same rows the SDK reads:

```python
from vmn_exp.sdk.reader import list_runs

row = next(r for r in list_runs("my_app") if r["verstr"] == outer_id)
row["children"]       # inner-run verstrs (len = total)
row["child_counts"]   # e.g. {"created": 1, "running": 1, "succeeded": 1}
row["tree_status"]    # rollup: failed > stuck > running > created > succeeded
```

Over HTTP, `GET /api/v1/workspaces/{ws}/apps/{app}/experiments` returns the same
`children`/`child_counts`. The detail endpoint `.../experiments/{verstr}` adds
`fleet`: `expected`, `counts` (per status, plus `waiting`) and `children` (per
pod: `status` and `progress`/`progress_total`, read from the pod's metrics or
params). See [ui.md](ui.md#api).

## Checklist for an agent

- Create the outer run first, and keep its verstr (`outer.id`).
- Register every pod with `--parent` before dispatching, if the waiting column matters.
- Start each pod with `start_run(run_id=...)` (or `VMN_RESUME_RUN_ID`) on the worker.
- End it with `finish()` / `finish(exit_code=n)`, or use `with` so a crash is recorded.
- Never write `run_state.yml` by hand. The heartbeat and exit code are what the columns read.
