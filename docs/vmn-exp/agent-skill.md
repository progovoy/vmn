# vmn-exp — experiment tracking & model registry

## Experiment tracking

Track code changes, metrics, and artifacts without a server:

```sh
# Run an experiment (captures code state + metrics + duration automatically)
vmn-exp run <app_name> --note "description" -- <your command>

# Your script writes metrics to $VMN_METRICS_FILE as key=value lines
# vmn ingests them automatically when the run finishes.

# Manual experiment (no command to run)
vmn-exp create <app_name> --metrics loss=0.34 acc=0.91 --note "manual run"

# List experiments sorted by a metric
vmn-exp list <app_name> --sort loss --top 5

# Compare two experiments (shows metric delta + code diff)
vmn-exp diff <app_name>

# Restore the most recent experiment's code state
vmn-exp restore <app_name> --latest
# For the best run instead: find it with `vmn-exp list --sort <metric>`, then
# vmn-exp restore <app_name> -v <version>

# Re-run a run's recorded command against its exact code, in a throwaway
# workspace (the live checkout is untouched); the new run records rerun_of
vmn-exp rerun <app_name> -v <version> [-- <other command>]
# What a cluster job would run (command, cwd, code identity); vmn does not schedule
vmn-exp rerun <app_name> -v <version> --print --json
```

### Driving the UI's fleet columns (total / waiting / running / done / failed)

The `vmn-exp ui` leaderboard shows these on an outer run (a run with inner runs).
They are derived from the inner runs' states, never written directly:

- **total**: the number of inner runs (register every pod up front so it is right from the start)
- **waiting**: inner runs registered but not started (`created`)
- **running**: inner runs with a live heartbeat
- **done**: inner runs that exited 0
- **failed**: inner runs that exited non-zero, plus `stuck` ones (heartbeat went stale)

```python
from vmn_exp.sdk import start_run

outer = start_run("<app_name>", name="sweep", params={"expected_pods": 8})
# register each pod up front (total +1, waiting +1):
#   vmn-exp create <app_name> --name pod3 --parent <outer.id>
pod = start_run("<app_name>", run_id="<pod verstr>")  # waiting -> running
pod.finish()               # running -> done    (exit_code=0)
# or pod.finish(exit_code=1)  running -> failed (any non-zero)
```

`start_run("<app_name>", nested=True)` inside the outer run (or
`vmn-exp run <app_name> --parent <ref> -- <cmd>`) starts a pod straight in
`running`. Use `with start_run(...) as pod:` so a crash records `failed`.
Full guide: docs/vmn-exp/ai-fleet-tracking.md

### Saving uncommitted work

Every experiment captures the working tree (tracked edits and untracked files),
so `vmn-exp create` doubles as a work-in-progress save point:

```sh
vmn-exp create <app_name> --note "WIP: refactoring auth"
vmn-exp restore <app_name> --latest
vmn-exp export <app_name> -o wip.tar.gz   # portable tarball of the captured state
```

## Similar experiments

Before submitting a run, check whether anyone already ran something like it.
vmn ranks past runs (any author, any app of the store) on facts recorded at
submission (base commit, changed files and functions), params, inputs,
entrypoint, metric names and text. You supply the meaning:

1. Read the change (`git diff HEAD`, unpushed `git log`) and write `intent.md`:
   the hypothesis, which functions changed and why, key params, the dataset,
   the expected effect. Describe the change, not results. Never paste secrets
   or data; stay under ~2 KB. Matching is lexical, so put synonyms and the
   problem's usual names in `keywords:`:

   ```markdown
   ---
   keywords: [focal loss, class imbalance, long tail, reweighting]
   generator: <your model id>
   ---
   Hypothesis: focal loss (gamma=2) fixes the minority-class recall drop.
   Changed: src/loss.py::focal_loss (new); src/train.py::train_step uses it.
   Data: imagenet-lt@3. Expect: val_recall_min up, val_loss roughly flat.
   ```

2. Ask, then inspect the 1-3 closest (each under its item's `app`):

   ```sh
   # no -v: compares the current working tree; creates nothing
   vmn-exp similar <app_name> --context-file intent.md --all-apps --json
   vmn-exp show <app_name> -v <ref> --patch --json
   ```

   Items carry `verstr`, `app`, `score`, `reasons`, `author`, `timestamp`,
   `status`, `goal`, `note`, `intent`, `features` and `group_size` (a sweep,
   or repeats of one code, shows as its best run). `show --patch --json` adds
   `"patch": {"text", "truncated"}`, or `{"text": null, "reason"}`: `no_code`
   (MLflow imports, clean trees, runs recorded git-free from an exported tree),
   `code_missing` (code object pruned), `untracked_only` (untracked files only,
   listed in `untracked_files` when readable). So `no_code` alone does not
   prove a run changed nothing.
   Re-rank on meaning, not just the score, and tell the user who ran what,
   when, how it scored and how this run differs.

3. Submit with the intent (`run`/`create` also print up to 3 similar runs on
   stderr; `--no-similar` skips that):

   ```sh
   vmn-exp run <app_name> --intent-file intent.md -- <your command>
   ```

   SDK: `start_run("<app_name>", intent="<text>", intent_keywords=[...])`, or
   later `run.set_intent(text, keywords=[...], generator="<model id>")`.

4. Backfilling intents, only when asked (bound the cost with `--last`/`--query`):

   ```sh
   vmn-exp list <app_name> --query "has_intent = false" --last 20 --json
   vmn-exp show <app_name> -v <ref> --patch --json   # read it, write intent.md
   vmn-exp add <app_name> -v <ref> --intent-file - < intent.md   # latest intent wins
   ```

   Runs missing the automatic code facts (recorded before they existed, or
   whose capture failed): `vmn-exp similar-backfill <app_name> [--dry-run]`.

5. Questions ("did anyone try X?"): answer citing verstrs from

   ```sh
   vmn-exp similar <app_name> --context "<X plus synonyms>" --text-only --all-apps --json
   ```

## Model registry

Link trained models to the experiment runs that produced them:

```sh
# Register a model version pointing at a run
vmn-exp model register resnet50 -v <verstr> --app my_app --artifact weights.pt --alias staging

# Move an alias (e.g., promote to production)
vmn-exp model alias resnet50 production 2
vmn-exp model alias resnet50 production 3 --expect 2   # CAS guard

# Inspect and list
vmn-exp model list
vmn-exp model show resnet50
vmn-exp model resolve resnet50@production   # print version metadata
```

SDK:

```python
from vmn_exp.sdk.models import (
    register_model, set_alias, get_model_version, download_model
)
# or on a run object:
run.register_model("resnet50", artifact_path="weights.pt", alias="staging")
path = download_model("resnet50@production")
```

`vmn-exp model` is git-free. Prune refuses registered runs even with `--force`; delete the version first.
