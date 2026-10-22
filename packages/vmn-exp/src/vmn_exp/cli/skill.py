"""``vmn-exp skill``: the AI-agent skill block for experiment tracking.

Installed through vmn's skill machinery (``version_stamp.api.run_skill``)
under its own name and markers, so it sits next to ``vmn skill``'s block.
"""
import argparse

from version_stamp.api import run_skill as _run_vmn_skill

VMN_EXP_TEXT = r"""# vmn-exp — experiment tracking & model registry

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

### Driving the UI's fleet counts (total / waiting / running / done / failed / stuck)

`vmn-exp ui` opens an app on its Outer runs view: one row per outer run
(`kind = "outer"`), whose run bar carries the counts over its whole subtree
(`16/20 · 1 failed · 2 stuck · 3/min · ETA 2m`); the outer run's page repeats them.
They are derived from the inner runs' states, never written directly:

- **total**: the number of inner runs (register every pod up front so it is right from the start)
- **waiting**: inner runs registered but not started (`created`)
- **running**: inner runs with a live heartbeat
- **done**: inner runs that exited 0 (the header leaves it implicit)
- **failed**: inner runs that exited non-zero
- **stuck**: inner runs whose heartbeat went stale with no exit code

```python
from vmn_exp.sdk import create_run, start_run

outer = start_run("<app_name>", name="sweep", params={"expected_pods": 8})
# register each pod up front (total +1, waiting +1); nests under the open outer run
pod_ids = [create_run("<app_name>", name=f"pod{i}") for i in range(8)]
# (shell: vmn-exp create <app_name> --name pod3 --parent <outer.id>)
pod = start_run("<app_name>", run_id=pod_ids[3])  # on the worker: waiting -> running
pod.finish()               # running -> done    (exit_code=0)
# or pod.finish(exit_code=1)  running -> failed (any non-zero)
```

`start_run("<app_name>", nested=True)` inside the outer run (or
`vmn-exp run <app_name> --parent <ref> -- <cmd>`) starts a pod straight in
`running`. Use `with start_run(...) as pod:` so a crash records `failed`.

Optuna trials in separate pods (shared Optuna storage): attach each pod to the
one outer run instead of opening one per pod, and finish it once:

```python
from vmn_exp.integrations.optuna_study import start_study_run
tracker = start_study_run(study, outer=os.environ["VMN_EXPERIMENT_ID"])
study.optimize(tracker.wrap(objective), n_trials=5)   # one inner run per trial
start_study_run(study, outer="<outer verstr>").finish()  # once: logs best_* on the outer run
```

Without an Optuna storage, `vmn-exp sweep` (`method: bayes`) coordinates pods
through the store alone (`vmn_exp/cli/docs/sweeps.md`).
Full guide: `vmn_exp/cli/docs/ai-fleet-tracking.md` (the guides ship with vmn-exp;
find them with `python -c "import vmn_exp.cli, os; print(os.path.dirname(vmn_exp.cli.__file__))"`).

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
   or the reruns of one config, shows as its best run). `show --patch --json` adds
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

   Any `--query` (`list`, `prune`, `similar`) filters on the same text:
   `similar("focal loss")` keeps the runs whose intent, keywords, name, note,
   tags, commit subjects or hypothesis hold every word (stemmed: `losses`
   finds `loss`); `intent ~ "focal"` and `keywords ~ "long tail"` match the
   latest intent's text and keywords as substrings:

   ```sh
   vmn-exp list <app_name> --query 'similar("focal loss") and status = "succeeded"' --json
   ```

## Serving and debugging the UI

```sh
vmn-exp ui --store s3://<bucket>/<prefix> --host 0.0.0.0 --token <t> --no-browser
vmn-exp ui --repo <checkout>        # a checkout's local store instead
```

The server indexes the store in the background (a big store's first load
shows `indexing N / M runs`; pages answer from the first 500, newest first)
and, unless `--read-only`, keeps the store tidy itself: it writes the child
markers older inner runs lack and compacts the metrics of failed/stuck runs.
Only with `--read-only` (or no server) run those by hand:
`vmn-exp backfill-children <app_name>` and `vmn-exp watch --compact <app_name>`.

When it is slow or stuck, take a dump (one JSON file, no py-spy or sudo; the
`diag` command works from any directory, no checkout needed) and send back the
file plus the summary:

```sh
vmn-exp ui diag --url http://<host>:8265 --token <t> -o dump.json   # while it answers
vmn-exp ui diag --pid <server pid> -o dump.json    # SIGUSR1; stacks if no JSON comes
kill -USR2 <server pid>     # every thread's stack -> <data-dir>/diag/stacks-<pid>.log
vmn-exp ui diag --summarize dump.json             # what is slow, who waits on what
```

Start the server with `--diag-every 30` to keep a dump every 30 s (the last
20, in `<data-dir>/diag/`), so the moment it went wrong is on disk. The dump
holds in-flight and slow requests (with the S3 calls each made), thread
stacks, held locks and their waiters, background work, pools, index load
state, S3 calls by object kind and caller, recent errors and event-loop/GIL
lag; the token and secret-looking env values are scrubbed.
Full reference: `vmn_exp/cli/docs/ui.md` (Diagnostic dumps, Store upkeep).

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

"""

DESCRIPTION = (
    "Use when tracking experiments, checking which past runs are similar before "
    "submitting one, driving the vmn-exp UI fleet counts, serving or debugging "
    "a slow vmn-exp ui server, "
    "or registering models via the vmn-exp CLI and SDK in this repo."
)

BEGIN_MARKER = "<!-- BEGIN vmn-exp skill (managed by `vmn-exp skill --install`) -->"
END_MARKER = "<!-- END vmn-exp skill -->"


def _parser():
    parser = argparse.ArgumentParser(
        prog="vmn-exp skill",
        description="Print vmn-exp usage instructions (skill block) for AI agents",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Write to a file instead of printing to stdout",
    )
    parser.add_argument(
        "--target",
        choices=["claude", "cursor", "agents"],
        default="claude",
        help="Install target: claude → .claude/skills/vmn-exp/SKILL.md, "
        "cursor → .cursorrules, agents → AGENTS.md (default: claude)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing Claude SKILL.md (claude target only)",
    )
    return parser


def run_skill(argv):
    """Exit code of ``vmn-exp skill`` with *argv* (the args after ``skill``)."""
    args = _parser().parse_args(argv)
    return _run_vmn_skill(
        args.install,
        args.target,
        args.force,
        name="vmn-exp",
        description=DESCRIPTION,
        body=VMN_EXP_TEXT,
        markers=(BEGIN_MARKER, END_MARKER),
    )
