# Notebooks

How the [SDK](sdk.md) behaves in a Jupyter notebook: one run across cells,
what re-running a cell does, what the snapshot captures, and how to close a
run a restarted kernel left open. The cells below run as written, in order
(`packages/vmn-exp/tests/test_docs_notebook_cells.py` runs them).

- [One run across cells](#one-run-across-cells)
- [Re-running the start cell](#re-running-the-start-cell)
- [Leave `capture_output` off](#leave-capture_output-off)
- [The notebook is part of the snapshot](#the-notebook-is-part-of-the-snapshot)
- [After a kernel restart](#after-a-kernel-restart)
- [Reading runs back into a DataFrame](#reading-runs-back-into-a-dataframe)
- [The kernel's directory must be in a git checkout](#the-kernels-directory-must-be-in-a-git-checkout)
- [Without a git checkout](#without-a-git-checkout)

## One run across cells

Open the run in one cell, log in later ones, finish it in the last:

```python
# Cell 1
from vmn_exp.sdk import start_run
run = start_run("my_app", params={"lr": 3e-4})
```

```python
# Cell 2
for step in range(3):
    run.log_metric("loss", 1.0 / (step + 1), step=step)
```

```python
# Cell 3
run.finish()
```

`run.finish()` records the run as `succeeded`; `run.finish(1, error="...")`
records it as `failed`. To keep a whole run in one cell, use `with` instead:
the run finishes when the cell does, and an exception in it marks the run
`failed`.

```python
with start_run("my_app", params={"lr": 1e-3}) as run:
    run.log_metric("loss", 0.5, step=0)
```

## Re-running the start cell

Running Cell 1 again while its run is still open raises:

```text
RuntimeError: Run '0.0.1-dev.a1b2c3d.r1' is already active on this thread. Call its .finish() before starting another, or pass nested=True to open a nested run under it.
```

Two ways out: run `run.finish()` (Cell 3) and then Cell 1 again, or open the
new run as a child of the open one on purpose:

```python
child = start_run("my_app", nested=True)
```

## Leave `capture_output` off

`capture_output=True` redirects the process's file descriptors 1 and 2 into
the run's `output.log`, so the kernel no longer writes to them as the
notebook expects. It is off by default; keep it off in a notebook and use
`run.log_note(...)` for text you want on the run.

## The notebook is part of the snapshot

Every run snapshots the working tree of the checkout, and the `.ipynb` file is
in it like any other file: modified or untracked files are captured, within
the size caps (files over 50 MB are skipped, at most 200 MB per snapshot; see
[experiments.md](experiments.md#mental-model)). What is captured is
the notebook as last saved to disk, not the cells in the kernel's memory.
Identical code gives an identical verstr, so a notebook saved with new
outputs is different code and gives a new verstr.

## After a kernel restart

If the kernel dies or is restarted before `run.finish()`, the run may be left
open: it reads `running` until its heartbeat goes stale, then `stuck`. Close
it from the new kernel without reopening it, as
[Finishing a run from outside it](sdk.md#finishing-a-run-from-outside-it)
describes:

```python
from vmn_exp.sdk import manage
manage.finish_run("my_app", "<run id>", 1, end_reason="kernel restarted")
```

`finish_run` refuses a run whose heartbeat is still fresh; once the old
kernel's last beat is stale (a few minutes at most), it succeeds.
`vmn-exp list my_app --query 'status = "stuck"'` shows its id.

## Reading runs back into a DataFrame

```python
# Cell 4
from vmn_exp.sdk.reader import runs_dataframe
df = runs_dataframe("my_app")
df[["run_id", "status", "metrics.loss"]]
```

Needs `pip install "vmn-exp-sdk[pandas]"`. Every reader and its columns are in
[Reading runs back](sdk.md#reading-runs-back).

## The kernel's directory must be in a git checkout

A run records the code it ran from, so the kernel's working directory (or
`VMN_WORKING_DIR`) must be inside a git checkout, unless you ask for a run
without code ([below](#without-a-git-checkout)). Front ends differ in which
directory they start the kernel in; check with `import os; os.getcwd()`.
Outside a checkout `start_run()` raises:

```text
RuntimeError: '/home/me/scratch' is not inside a git checkout, and a run records the code it ran from one. Either make it a checkout (`git init && git commit --allow-empty -m init`), record against an exported tree by setting VMN_SNAPSHOT_METADATA, or record no code with start_run(code=False) / VMN_EXP_CODE=none (see sdk.md, 'Runs without a git checkout').
```

The first run in a checkout vmn does not track yet initializes vmn there and
tags a `0.0.0` baseline locally (see [Starting a run](sdk.md#starting-a-run)).

## Without a git checkout

A kernel with no checkout to start in (a hosted notebook, a scratch
directory) can log metrics if you ask for a run without code. Name the app
and the store; vmn-exp-sdk alone is enough:

```python
import os
os.environ["VMN_EXPERIMENT_DIR"] = "/content/runs"  # or VMN_EXPERIMENT_STORE
run = start_run("my_app", code=False)  # or set VMN_EXP_CODE=none
```

The run is named `0.0.0-nocode`, then `0.0.0-nocode.r2`, and so on. It
records no code, so it cannot be rerun, restored, exported or diffed, and
`vmn-exp show` prints `Code: none`. Everything else in this guide applies.
See [Runs without code](sdk.md#runs-without-code-codefalse).
