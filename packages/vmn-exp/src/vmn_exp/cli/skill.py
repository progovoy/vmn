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
# "Best" needs a declared goal: run.define_metric("val_loss", goal="min") (or
# conf.yml metrics.<name>.goal). Without one nothing is ranked or guessed from
# the name: the UI shows "(no goal)" and sorts ascending.

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

When pods are created as the work gets planned, their count is no denominator:
declare the real one on the outer run, `outer.set_progress(41, 60, unit="dates")`
(metrics `progress`/`progress_total`); its bar, `done/expected`, rate and ETA then
read it (`41/60 dates · 1,415 runs · ...`), the run counts unchanged.

Pods that get evicted or preempted: hand the run back instead of failing it,
so it reads waiting again and the next pod reopens it (`run_id=`, which bumps
`resume_count`):

```python
pod = start_run("<app_name>", run_id=pod_id, on_sigterm="release")  # SIGTERM -> released
# by hand, any run: run.release(reason="preempted") (flush, stop, state `released`)
# process-wide: VMN_EXP_ON_SIGTERM=release; VMN_EXP_SIGTERM_EXIT=raise (or sigterm_exit=)
# exits via SystemExit(143) so finally blocks run, instead of re-killing
```

A finished pod (done or failed) is not reopened: `start_run(run_id=)` raises
`manage.ReopenRefusedError` (`.reason` "finished") unless `reopen=True`
(env `VMN_RESUME_REOPEN=1` with `VMN_RESUME_RUN_ID`), since reopening clears
its exit code.

A pod that died without finishing can be finished from outside (a controller,
a cleanup job); `manage.FinishRefusedError` (`.reason` "live"/"finished")
while the run still beats or once it finished.
`force="live"` finishes a live run but never re-finishes one; `force=True` both.
Both errors subclass `manage.RunRefusedError` (a ValueError carrying `.reason`,
`.status`, `.exit_code`, `.verstr`), so branch on fields, not message text:

```python
from vmn_exp.sdk import manage
manage.finish_run("<app_name>", "<verstr>", 137, error="OOMKilled")
# many at once; never raises per run: {ref: verstr | FinishRefusedError | ValueError}
manage.finish_runs("<app_name>", ["<verstr>", ...], 1, force="live")
# shell: vmn-exp add <app_name> -v <verstr> --finish 137 --error OOMKilled [--force-live|--force]
```

To check many pods' states (resume, audit) on a large store, read them in one
call without the index: `vmn_exp.sdk.reader.get_run_states("<app_name>", refs)`
returns `{ref: state | None}` (`get_run_state`'s fields plus `run_state`,
`observed_at`, `verstr`). Exact verstrs read only their own run; `latest`/`@N`
resolve once per call; prefixes are not resolved (None).

Once an outer run has ended, what is left under it settles (derived, never
written, query it as `settled`): `never_started` (still `created`, but no
longer waiting or live; adds nothing to the counts), `lost`
(stuck; its own state: it never makes `tree_status` read `failed`, only a
non-zero exit does; `lost_below` counts it, `failed_below`/`failed_pct` count
it as not finished) or `outlived` (still beating; counted as running
and flagged). For runs lasting hours, slow the beat with
`VMN_EXP_HEARTBEAT_SEC=120` (stuck after 6 min) and the log sync with
`VMN_EXP_SYNC_SEC`; a heartbeat that changes nothing skips its write.
`run.define_metric("health.*", chart="bars")` (or `chart="table"`) draws a
metric as bars or a table on the run page instead of a line.

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

### Pruning

```sh
vmn-exp prune <app_name> --keep 100 --dry-run         # policy: preview first
vmn-exp prune <app_name> -v <verstr> -v <verstr>      # exactly these runs
vmn-exp prune <app_name> -v <verstr> --store s3://<bucket>/<prefix>  # no checkout needed
```

Running/stuck and `--protect-tag` runs are kept unless `--force`; a run with a
kept descendant is always kept. A `-v` prune reads only its targets (exact verstrs need
no index) and never trims the change journal; a policy prune
(`--keep`/`--older-than`/`--query`) trims it unless `--no-trim-journal` (for a
bucket whose lifecycle rule expires it). Outside a git checkout the store-only
maintenance commands (`prune`, `backfill-children`, `compact`, `similar-backfill`)
take their store from `--store`/`--experiment-dir` or
`VMN_EXPERIMENT_STORE`/`VMN_EXPERIMENT_DIR`.

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

What the UI shows for an app is shared app settings in the store (no checkout
needed; a checkout's conf.yml `experiment:` block wins over them):

```sh
vmn-exp settings <app_name> show
vmn-exp settings <app_name> set -f experiment.yml   # refused if invalid
```

```yaml
ui:
  progress: {done: dates_done, total: dates_total, unit: dates}  # your metric names
  split_by: tags.kind              # per-kind counts/durations on an outer run's page
  attention:                       # <= 8 named queries, counted on every outer run
    - {key: unstable, query: 'tags.health = "unstable"', level: error}
    - {key: slow_start, level: warn,  # settled = null: not what an ended outer run left
       query: 'status = "created" and settled = null and timestamp < ago("1h")'}
  baseline: {match: [tags.target], differ: [tags.launch_id], children_by: tags.trade_date}
  # compare with the last launch of the same target from another training
  views: [{name: Live, page: jobs, search: "view=live", default: true}]
  # each outer run row's value: one value per unit (here each date's own
  # date.best_value), aggregated; agg mean|best|median|min|max|best10|worst10,
  # by children|runs|field:<params.k|tags.k>|kind:<v>, value best|own
  job_aggregate: {agg: median, by: "field:params.trade_date", value: own, metric: date.best_value}
  failed_pct_threshold: 5          # the board's "≥ N% failed" chip
```

A save checks `ui.progress`/`ui.attention`/`ui.baseline`/`ui.views`/
`ui.job_aggregate`/`ui.failed_pct_threshold` (an attention query must
compile). The URL's `job_agg`, `job_agg_by`, `job_agg_value` and
`job_agg_metric` override `ui.job_aggregate` for one view. A resumed
training's attempts share a tag: `group=tags.launch_id` (on the Outer runs
view) pools their units under that aggregate, the latest attempt wins a
unit they share; `collapse_all=1` shows one row per training. A tree's failure
share is queryable: `failed_pct >= 5` (`100 * failed_below / runs below`,
lost runs included; also `failed_below`, `lost_below`, `live_below`,
`running_below`, `stuck_below`).
Queries (`vmn-exp list --query`, the UI's filter, `ui.attention`) can read
an ancestor's fields: `up.params.<k>`, `up(tags.kind = "study").params.<k>`.
`GET /metrics` serves Prometheus gauges per app and outer run (status counts,
attention counts, progress, ETA, index freshness) for alerting.
Full reference: `vmn_exp/cli/docs/server.md` (App settings).

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
