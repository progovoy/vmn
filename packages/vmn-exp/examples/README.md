# Runnable examples

Five small scripts for the `vmn_exp.sdk` experiment-tracking SDK. Each one
is standalone, takes no arguments, needs no network, and finishes in seconds.
They all record to the vmn app **`vmn_examples`**, so they never collide with a
real app in your repo.

| Script | Shows |
|---|---|
| `01_minimal.py` | the ten-line version: open a run, log metrics with steps, print `run.id` |
| `02_training_loop.py` | params, a per-step metric curve, a note, an artifact, and `system_metrics=True` |
| `03_sweep.py` | one outer run over three `nested=True` inner runs, and the `tree_status` rollup |
| `04_query.py` | `list_runs(query=...)` — a metric threshold, a string param, a status set |
| `05_autolog_sklearn.py` | `autolog()` recording a real sklearn `fit()` with no logging calls |

## One-time setup

vmn tracks versions in git, so run the scripts from inside **a git repo with
at least one commit and a git identity** (`user.name`/`user.email`). No remote
is needed: the SDK never pushes. A throwaway repo works:

```sh
git init /tmp/vmn-demo && cd /tmp/vmn-demo
git commit --allow-empty -m "initial commit"
pip install vmn-exp            # brings vmn and vmn-exp-sdk
python /path/to/vmn/packages/vmn-exp/examples/01_minimal.py
```

The first script you run cold-starts vmn tracking: it initializes `.vmn/` and
commits and tags a local `0.0.0` baseline for `vmn_examples` before recording.
No `vmn init` needed.

## Afterwards

```sh
vmn-exp list vmn_examples            # every run, with the sweep as a tree
vmn-exp show vmn_examples --latest   # one run: params, metrics, curves, artifacts
vmn-exp compare vmn_examples         # runs side by side
vmn-exp ui                           # the dashboard (vmn-exp[ui]), at http://127.0.0.1:8265
```

Re-running any script is safe: it appends new runs and never rewrites old ones.

Full reference: [`docs/vmn-exp/sdk.md`](../../../docs/vmn-exp/sdk.md) for the SDK,
[`docs/vmn-exp/experiments.md`](../../../docs/vmn-exp/experiments.md) for the CLI.
