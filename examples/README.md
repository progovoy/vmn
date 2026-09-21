# Runnable examples

Five small scripts for the `version_stamp.exp` experiment-tracking SDK. Each one
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

vmn tracks versions in git, so it needs **a git repo with a remote**. Any
existing repo of yours works — just run the scripts from inside it. For a
throwaway repo, a local bare clone is a perfectly good remote:

```sh
git init --bare /tmp/vmn-demo-remote.git
git clone /tmp/vmn-demo-remote.git /tmp/vmn-demo
cd /tmp/vmn-demo
git commit --allow-empty -m "initial commit"
git push -u origin HEAD
```

Then install vmn (`pip install vmn`) and run the examples from that directory:

```sh
python /path/to/vmn/examples/01_minimal.py
```

The first script you run cold-starts vmn tracking: it initializes `.vmn/` and
stamps a `0.0.0` baseline for `vmn_examples` before recording. No `vmn init`
needed, and nothing to undo — deleting `.vmn/` removes it all.

## Afterwards

```sh
vmn exp list vmn_examples            # every run, with the sweep as a tree
vmn exp show vmn_examples --latest   # one run: params, metrics, curves, artifacts
vmn exp compare vmn_examples         # runs side by side
vmn ui                               # the dashboard, at http://127.0.0.1:8265
```

Re-running any script is safe: it appends new runs and never rewrites old ones.

Full reference: [`docs/sdk.md`](../docs/sdk.md) for the SDK,
[`docs/experiments.md`](../docs/experiments.md) for the CLI.
