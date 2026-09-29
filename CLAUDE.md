# CLAUDE.md

# Claude Code instructions

When generating commit messages, pull request text, patches, or any code-related output, never include this line:

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

Omit any Claude co-author trailer unless I explicitly ask for it.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Splitting tasks
Split big tasks into separate worktrees and do in parallel, but TDD takes precedence.
Each worktree agent must follow TDD internally: write its tests first (red), then implement (green).
If multiple worktrees touch independent features, each worktree owns its own red-green-refactor cycle.
Each worktree agent should write ~200-300 lines max per file. If writing more, split into additional worktrees.
When finished - always try /simplify on the change.

## Timeout handling
If you see API timeouts, split the current task into smaller parallel worktrees rather than retrying.

## Worktree hygiene
- Never push worktree branches to remote.
- When a worktree agent finishes, immediately remove the worktree (`git worktree remove --force`) and delete its local branch (`git branch -D`).
- Before starting new work, check for and clean up any stale worktrees from previous sessions (`git worktree list`).

## Permissions hygiene
- Do not accumulate one-off permission rules in `.claude/settings.local.json`.
- Prefer broad wildcards (e.g., `Bash(git:*)`) over specific subcommand rules.
- Keep the allow list under 30 entries.

## Code practices
- Keep functions small and single-purpose; prefer clear names over comments.
- Don't add abstractions, config flags, or error handling for cases that can't happen — match the scope of the change to what was actually asked.
- Reuse existing helpers/patterns in the codebase instead of duplicating logic.
- Keep diffs minimal and focused; don't refactor unrelated code in the same change.
- Run the relevant tests (see Running Tests) before considering a change done.

## Test-driven development (required)
All feature work and bug fixes must follow strict TDD:
1. Write the test first. It must fail for the right reason (red).
2. Write the minimum implementation code needed to make it pass (green). Do not modify the test to make it pass.
3. Refactor implementation code only, keeping tests green.

Rules:
- Never edit a test to force a passing result — if the test seems wrong, stop and ask before touching it.
- Do not write implementation code before its test exists.
- Each new behavior gets a test asserting it before any code implements it.

## Project Overview

vmn is a CLI tool and Python library for automatic semantic versioning. Versions live in git annotated tags — zero lock-in, zero databases.

Key differentiators vs semantic-release/release-please:
- Language-agnostic (not JS-centric)
- Multi-repo dependency tracking with `vmn goto` state recovery
- Microservice topology (root apps with independent service versions)
- 4-segment hotfix versioning (`major.minor.patch.hotfix`)
- Auto-init on first `vmn stamp` — no separate `vmn init` required
- Works offline, with shallow clones, in air-gapped environments

## Development Setup

The repo is a uv workspace of three packages (see docs/packaging.md):
`packages/vmn` (`version_stamp`), `packages/vmn-exp-sdk` (the job-side
`vmn_exp.sdk`/`storage`/`core`/`registry`/`integrations`/`_base`) and
`packages/vmn-exp` (`vmn_exp.cli`/`ui`/`snapshot`/`importers`/`gitmode`, the
`vmn-exp` command and `webui/`). `vmn_exp` is a PEP 420 namespace package split
across the last two — never add a `vmn_exp/__init__.py`.

```sh
python3 -m venv ./venv
source ./venv/bin/activate
pip install -U pip "setuptools>=64"
pip install -r ./tests/requirements.txt
pip install -r ./tests/test_requirements.txt
pip install -e packages/vmn -e packages/vmn-exp-sdk -e "packages/vmn-exp[ui]"
vmn --version  # Should see 0.0.0 if installed successfully
```

`uv sync` also works from the repo root. Build the wheels with
`uv build --all-packages` (or `make _build NAME=vmn|vmn_exp`).

Import rules (tests/test_packaging_split.py): `version_stamp` never imports
`vmn_exp`; the vmn-exp-sdk subpackages import neither `version_stamp` nor the
vmn-exp subpackages (except a lazy `vmn_exp.gitmode`); vmn-exp reaches
`version_stamp` only through `version_stamp.api`. vmn loads `vmn goto` of dev
versions (`register_dev_version`) from the `vmn.plugins` entry point that
vmn-exp declares.

## Running Tests

Tests require Docker. Activate the test venv first — the suite runs through the
active interpreter's `coverage`/`pytest`, and the release-notes tests need the
`git-cliff` binary that `tests/test_requirements.txt` installs into it.
```sh
source ./venv/bin/activate
./tests/run_pytest.sh
```

Run a specific test:
```sh
./tests/run_pytest.sh --specific_test <test_name>
```

UI load harness (real `vmn-exp ui` + live job processes; see tests/uiload/README.md):
```sh
python tests/uiload/run.py live --profile smoke --duration 0   # watch in a browser
VMN_UILOAD_PROFILE=smoke python -m pytest -s tests/test_uiload_profile.py
```

CI is the local Muster pipeline in `ci/pipeline.py` (`./ci/start.sh`, see
`ci/README.md`) — there is no GitHub Actions workflow.

Skip a test:
```sh
./tests/run_pytest.sh --skip_test <test_name>
```

Tests run in parallel (29 workers by default) using pytest-xdist.

### Key Concepts

- **App name**: Identifier for a versioned app (e.g., `my_app` or `root_app/service1`). Cannot contain `-` or start with `/`
- **Root app**: Parent container for microservices, format `root_app/service_name`. Root version is an auto-incrementing integer.
- **Version format**: `major.minor.patch[.hotfix][-prerelease.rcn][+buildmetadata]`
- **Tag format**: `{app_name}_{version}` where `/` in app names becomes `-`

### Data Flow

1. Version info stored in git annotated tag messages as YAML (`vmn_info` + `stamping` sections with changesets)
2. Local state tracked in `.vmn/{app_name}/last_known_app_version.yml`
3. `stamp` command: increments version → writes to backends → commits → tags → pushes

### Configuration

Per-app config in `.vmn/{app_name}/conf.yml`. Key fields:
- `template`: Version display format (e.g., `[{major}][.{minor}]`)
- `conventional_commits`: Auto-detect release mode from commit messages (`fix:` → patch, `feat:` → minor, `BREAKING CHANGE` → major). When enabled, `-r` flag is optional.
- `release_mode_policy`: `optional` (--orm behavior) or `strict` (-r behavior) — controls how detected release mode is applied
- `default_release_mode`: Fallback release mode (`patch`/`minor`/`major`/`hotfix`) when none is resolved from CLI or conventional commits
- `changelog.path`: Generate CHANGELOG.md on stamp (requires conventional_commits)
- `github_release.draft`: Create GitHub Release on stamp (requires `gh` CLI + `GITHUB_TOKEN`)
- `deps`: External repository dependencies for multi-repo tracking
- `version_backends`: Auto-embed version into package.json, Cargo.toml, pyproject.toml, or any file via regex/Jinja2
- `policies.whitelist_release_branches`: Restrict which branches can stamp/release
- Branch-specific overrides: canonical layout `.vmn/{app}/branch_conf/{branch}/conf.yml` (branch slashes become real directories; root apps use `root_conf.yml`). Legacy flat `<branch>_conf.yml` and nested `{branch}/conf.yml` files are still read (precedence canonical > flat > legacy) and are auto-migrated to the canonical layout on the next `vmn stamp`.

### Test Infrastructure

- `tests/conftest.py`: Pytest fixtures including `FSAppLayoutFixture` for creating isolated git repos
- Tests create temporary git repos with remotes to simulate real workflows

## CLI Commands

- `vmn stamp -r <mode> <name>`: Stamp a new version (mode: major/minor/patch/hotfix). Auto-inits repo/app. Idempotent.
  - `--pr <id>`: Create prerelease (e.g., `--pr rc` → `0.0.1-rc.1`)
  - `--orm`: Optional release mode — only advances if no prerelease exists at target
  - `--pull`: Pull remote first, retry on conflict
  - `--dry-run`: Preview without committing
  - Without `-r`: works during prerelease sequence, or always with `conventional_commits` enabled
  - `--git-push-user` / `--git-push-token`: push credentials for hosts where the checkout has none (fall back to `VMN_GIT_PUSH_USER` / `VMN_GIT_PUSH_TOKEN`). Both required together; injected into an ephemeral HTTPS push URL only, git remote config is left untouched.
- `vmn release <name>`: Promote prerelease to final. `-v <version>` for explicit, `--stamp` for full stamp flow. Also takes the `--git-push-*` flags.
- `vmn show <name>`: Display version info. `--verbose` for full YAML, `--raw`, `--type`, `-u` for unique ID, `--dev`, `--conf`, `--from-file`, `--ignore-dirty`, `-t <template>`.
- `vmn goto -v <version> <name>`: Checkout repo + all deps to exact state at version. `--deps-only`, `--root`, `--pull` (fetch first when the version is not local).
- `vmn gen -t <template> -o <output> <name>`: Generate file from Jinja2 template.
- `vmn add -v <version> --bm <metadata> <name>`: Attach build metadata. `--vmp` for a metadata YAML path, `--vmu` for an associated URL.
- `vmn-exp [action] <name>` (the `vmn-exp` command; a leading `exp`/`experiment` is accepted): Local-first experiment tracking (a snapshot + an append-only metrics/notes log). Actions: `create` (default), `run`, `add`, `list`, `show`, `compare`, `diff`, `restore`, `export`, `prune`, `tag`, `archive`, `unarchive`, `import-mlflow`, `watch`, `importance`, `lineage`, `rewind` (sweeps are the separate `vmn-exp sweep` command). `create`/`run --name` names a run; `list --query <expr>` filters, `list`/`show --json` print machine-readable output; archived runs are hidden unless `list --archived`. `vmn-exp run <name> -- <cmd>` runs a command and ingests `key=value` lines the child writes to `$VMN_METRICS_FILE`. See docs/experiments.md.
  - `run` publishes `run_state.yml` (state/pid/host/heartbeat/exit_code) next to `metadata.yml` and refreshes a heartbeat while the child lives; `--heartbeat-interval <sec>` (default 30).
  - `run` tees the child's stdout/stderr (pipes, not a pty; `PYTHONUNBUFFERED=1` unless set) into a size-capped `output.log` artifact (head + tail kept past the cap; `--output-cap-mb` > `VMN_EXP_OUTPUT_CAP_MB` > 10), uploaded after the log sync, throttled to ~64 KB/s of upload bandwidth, and once unthrottled at the end; `--no-capture-output` opts out. SDK: `start_run(capture_output=True)` (off by default) tees fds 1/2 the same way.
  - System metrics (`sys_*`: CPU/RAM, GPU with pynvml) are sampled on the heartbeat by default. Opt out: `--no-system-metrics` / `start_run(system_metrics=False)` > `VMN_SYSTEM_METRICS=0` > conf `experiment.system_metrics: false`. psutil is a hard dependency of vmn-exp-sdk. When `vmn-exp run` samples the child's tree it sets `VMN_EXP_SUPERVISOR_SAMPLES=1`, and `start_run()` inside the child then defaults `system_metrics` off (explicit `True` wins).
  - Alerts: `run.alert(title, text, level)` (rate-limited per title), plus `failed`/`stuck` transition alerts to sinks in conf `experiment.alerts` (`on: [failed, stuck, alert]`, `sinks: webhook|slack|command`) or `VMN_EXP_ALERT_WEBHOOK_URL`/`_SLACK_URL`/`_COMMAND`/`_ON`. `failed` fires from the run itself; `vmn-exp watch <app> [--interval] [--within]` (cron-friendly) detects `stuck` and missed `failed`, deduped via the run's `alerts_sent.yml`. Sink errors never break a run.
  - `vmn-exp run` supervision is crash-proof: the metrics tailer reads bytes (non-ASCII lines never kill it), ingestion/heartbeat/sync errors are best-effort, SIGTERM/SIGINT/SIGHUP are forwarded to the child (SIGKILL after `--kill-grace-sec`, default 30 / `VMN_EXP_KILL_GRACE_SEC`) and the final state is always written (`exit_code` = `128+N` when signal N ended the child; `signal`/`received_signal` fields). The child runs in the invocation cwd (or `$VMN_WORKING_DIR`). Remote sync runs off the heartbeat loop.
  - Read-only actions (`list`/`show`/`compare`/`diff`/`export`/`watch`/`importance`/`lineage`) never take the repo lock. `list` row numbers are the storage index `@N` resolves, whatever `--sort`/`--last`/`--top` do. `show` prints the last 50 log entries (`--full-log` for all). `prune` never deletes `running` or `stuck` runs, or a run carrying a `--protect-tag`-named tag key (`--force` overrides either), or a run with a kept descendant; `--dry-run` previews, `--local-only` keeps remote copies, `-v <ref>` (repeatable, not combined with `--keep`/`--older-than`) deletes exactly the named run(s) instead of a bulk policy. `--query <expr>` selects candidates via the query language (same rows as `list --query`); is a dry-run preview unless `--yes`/`-y` is given; `--dry-run` beats `--yes`; `--keep`/`--older-than` apply within the query scope; cannot be combined with `-v`.
  - Metric summaries: the fold keeps last, first (earliest by fold key), finite min/max and an exact finite sum/count per repeated metric (`core/metric_summary.py`; index `SCHEMA_VERSION` bumps on any fold change). `row["metrics"][k]` is the summary per policy: run `define_metric(name, summary=min|max|last|first|mean, goal=, step_metric=, hidden=)` (exact name beats glob) > conf `experiment.metrics.<name|glob>.summary|goal|step_metric|hidden` > `last`; `goal` derives the summary; `summary="none"` is rejected. Sorting, queries, prune `--keep`, compare and the UI all rank on it; `row["metric_summary"][k]` holds `{last,min,max,first,mean}` for metrics logged more than once. The *effective schema* (`core/metric_schema.py`: conf + run-declared `goal`/`hidden` for names conf lacks, latest run wins; `IndexSnapshot.declared_schema()`) drives sort direction (`list_runs`, `vmn-exp list`, UI leaderboard; glob goals count) and UI hidden columns/`/metrics-schema`, never summaries. `hidden` is display-only; run detail carries `hidden_metrics`. CLI: `vmn-exp add <app> -v <ref> --define-metric NAME [--goal] [--summary] [--step-metric] [--hidden]`. `step_metric` joins a metric's series on another metric's value at the same step (reader `get_run(x=)`, series endpoints `x=`, UI x-axis picker).
  - Record format: new runs and registry records carry `format_version` (`core/record_format.py`, currently 1; missing = 1); readers skip records from a newer format with a warning.
  - Fork/rewind: `start_run(fork_from="<ref>", fork_step=N)` (or `"<ref>?_step=N"`; CLI `--fork-from/--fork-step`) makes a new run whose log starts with the source's entries up to N (marked `inherited`) and records `forked_from` (not a child). `start_run(run_id=<ref>, rewind_to_step=N)` appends a `rewind` marker; every reader hides earlier entries with step > N. CLI `vmn-exp rewind <app> -v <ref> --step N` appends the same marker without reopening the run (repo lock like `tag`; works with `VMN_SNAPSHOT_METADATA`; ui job action `exp_rewind`); `vmn-exp run` has no resume, so continue via SDK `run_id=` or `--fork-from`. A running run can't be rewound.
  - Lineage: rows carry `outputs` (path/digest/size of every artifact and logged image/table, queryable as `outputs."<path>".digest`). The index keeps them off its lean snapshot rows (`IndexSnapshot.outputs_of(verstr)`, like `metric_summary`), so UI list/leaderboard/facets/columns payloads never carry them; row copies (`list_runs`, `get_run`, `list --json`), UI run detail, `LineageIndex(rows, outputs_of)` and queries (`filter_rows(..., extra={"outputs": snap.outputs_of})`) do. `run.use_artifact(ref, path)` records a `vmn://<app>/<verstr>/<path>` input and returns the file; inputs link to producers by that URI (any app) or by digest (same app). `reader.get_lineage`, `vmn-exp lineage <app> -v <ref> [--depth]`, `GET .../experiments/{verstr}/lineage`.
  - Rich logging: `run.log_table/log_image/log_histogram` (tables as `tables/<name>/<step>.json`, images as `media/<name>/<step>.png` with a stdlib PNG encoder fallback, histograms as log entries; image/table files upload on a background worker that finalization waits for). The image/table entry carries the stored bytes' `sha256`/`size` (hashed before upload) and is itself the output record (no separate `artifact` entry), so `run.use_artifact(ref, "media/<name>/<step>.png")` fetches it; the uploader appends the entry (with its log-time step/timestamp) only once the file is stored — `finish()` drains the queue before the final log flush — and a file that fails to store (or is still queued at the final wait's deadline) is never recorded, so no entry/output ever outlives a failed or killed upload; run detail exposes `media`/`tables`/`histograms`, `GET .../experiments/{verstr}/table/{path}` pages a table.
  - Parameter importance: `core/importance.py` (pure-Python histogram random forest + Pearson/Spearman) behind `reader.param_importance`, `vmn-exp importance <app> --metric m`, `GET .../experiments-importance?metric=`, and the leaderboard's Importance view.
  - Metric values: numeric only. numpy/torch scalars and numeric strings are coerced to float; bools/strings/vectors are dropped with a warning; NaN/inf are kept in the log and served as JSON `null`. Missing/non-finite values sort last in both directions. Numeric params fold into `metrics` only when finite (bools fold as 1.0/0.0).
  - Status is derived, never stored: `created`/`running`/`stuck`/`succeeded`/`failed`. `stuck` = claims running with no exit code, and both the heartbeat timestamp (writer clock) and the store's write time of `run_state.yml` (file mtime / S3 `LastModified`, when known) are stale past `max(3 * interval, 60s)` — a fresh store write proves liveness despite writer clock skew; unknown store time falls back to the heartbeat alone.
  - Python SDK: `from vmn_exp.sdk import start_run` — in-process alternative to `vmn-exp run` (`run.log_metric/log_metrics/log_params/log_note/log_input/log_artifact/log_artifacts/log_dict/log_text/log_figure/set_tag(s)`, `run.finish()`; log writes are batched and flushed at most ~1s apart, on heartbeat and on finish/SIGTERM/exit; `start_run(name=, tags=, run_id=<resume>, all_ranks=False, capture_env=None)` — ranks > 0 get a no-op run; the snapshot is captured outside the repo lock; an SDK cold start commits/tags locally without pushing; read side `vmn_exp.sdk.reader.get_run/list_runs/runs_dataframe/get_metric_history` — the last two need `vmn-exp-sdk[pandas]`). Writes the same files as the CLI and heartbeats from its own daemon thread (which also syncs the log to a remote every `sync_interval_sec`, default 30). `current_run()` returns the run the calling thread records into (its own context-bound run, else the process's only open run); runs are fork-aware (`Run.pid`), and `VMN_EXPERIMENT_ID` never parents a run to a sibling another thread opened. With `VMN_SNAPSHOT_METADATA` set, `start_run()` works without a git checkout (storage from `VMN_EXPERIMENT_DIR`). `vmn_exp/sdk/` ships in vmn-exp-sdk: it depends only on `vmn_exp.core`, `vmn_exp.storage`, `vmn_exp.registry`, `vmn_exp._base` — never on `version_stamp`, `vmn_exp.snapshot`, `vmn_exp.ui` or `vmn_exp.cli`; git-mode creation lives in `vmn_exp.gitmode` (vmn-exp) and is imported lazily. See docs/sdk.md.
  - Autologging: `from vmn_exp.sdk import autolog, autolog_disable`. `autolog()` wraps framework `fit()` methods to record hyperparameters, final metrics, per-epoch series where the framework exposes one, and (with `log_models=True`; default off) the model in its native format. Frameworks are patched only once imported (`vmn_exp/sdk/import_hooks.py`), so `autolog()` never imports tensorflow/torch itself. Fits record into `current_run()`; framework worker threads without their own run are ignored while a recorded fit is in progress. Search estimators add `sklearn_best_cv_score`/`sklearn_best_<param>`; `sklearn_score` is a training-set score, computed when `training_score="auto"` (<= 10k rows). Lightning under DDP skips model saving. Supported: `sklearn`, `xgboost`, `keras`/`tensorflow`, `lightning`/`pytorch_lightning`, `transformers` (injects a `VmnCallback` via `Trainer.train`; watches `transformers.trainer` lazily). Plain `torch` has no `fit` to wrap — use explicit `run.log_metric(...)` in your own loop. Add a framework with an `_Adapter` entry in `SUPPORTED_FRAMEWORKS` in `vmn_exp/sdk/autolog.py` (only `discover` is mandatory; the other hooks default to the sklearn behaviour). Records nothing unless a `start_run()` is open (never opens one implicitly — that would stamp a version from inside `fit()`). Keys are `<framework>_<name>` with an underscore so the query language's two-part paths resolve them. Failures never break `fit()`; patching is idempotent and `autolog_disable()` restores the originals.
  - Query language (`vmn_exp/core/query.py`): filters rows for `list_runs(query=...)` and the UI's `?q=`. Comparisons `= == != < <= > >=`, `~`/`contains`/`!~` (case-insensitive substring; on list fields like `command`/`children` any element matches), numbers accept scientific notation (`1e-4`), `in`/`not in`, `and`/`or`/`not`, parens. Fields are bare row keys, `metrics.<name>` (numeric fold) and `params.<name>` (verbatim, so strings/bools work). Two-valued: a comparison against a missing field is false, `= null` tests absence. Bad queries raise `QueryError` with an offset (400 over HTTP). `vmn-exp list --query` applies it on the CLI.
  - Lock scope: `vmn-exp run` holds the repo lock only for the create/auto-init phase and releases it before supervising the child, so long runs don't block other `vmn` commands and nesting works. The SDK scopes it the same way around create/cold-start.
  - Storage (`vmn_exp/storage/`): backends are chosen by store URI — `--store` > `VMN_EXPERIMENT_STORE` > conf `experiment.storage.uri` (`s3://bucket/prefix[?endpoint_url=]`, `gs://` (`[gcs]` extra), `az://` (`[azure]` extra), `file:///dir`); `--bucket/--prefix/--endpoint-url` are shorthand for an `s3://` URI (`--prefix` has no literal default; `store_uri` supplies `vmn-experiments`). Restore safety snapshots (and `vmn goto` of them) live in the experiment store's `snapshots` subdir. `vmn goto -v <dev-version>` and `vmn-exp restore` share one lookup (`cli/code_record.py`): local experiments, then the remote experiment store, then snapshots; no-code runs are refused. Every backend implements `list_apps()` (reserved app names filtered there). Schemes register in `storage/registry.py`; other packages add them via the `vmn_exp.storage` entry-point group (the contract is in docs/experiments.md). Run verstrs are claimed atomically (`create_exclusive`: `O_EXCL` mkdir / S3 `If-None-Match` / GCS `if_generation_match=0` / Azure `overwrite=False`), so hosts sharing a bucket or NFS dir never collide; allocation lists names only. Local writes are atomic (temp + rename) and never resurrect a deleted record. Each storage dir carries a `.gitignore` of `*`. Remote log sync uploads only new lines as segments `log.<writer>@<seq>.jsonl`; `run_state.yml`/logs are never cached locally from a remote. S3 app keys use the tag form (`/`→`-`, legacy `_` still read); S3 `exists` is a HEAD; artifacts stream via `upload_file` and are listable/downloadable. Snapshot identity keeps the full `diff_hash` and extends the verstr's hash on a collision instead of overwriting. A run's code (patches + untracked tarball) is stored once per code identity as a record `<code_verstr>.<diff_hash>` of the reserved `vmn-code/<app>` pseudo-app (`core/code_store.py`; its `metadata.yml`, written last, marks it complete); the run's metadata references it as `code:` and `storage.load` resolves it (backends implement `load_record`). A run of already-stored code builds no tarball and uploads nothing; a missing/incomplete object makes `restore`/`goto`/`export` refuse (`code_missing`); `prune` deletes an object with the last run of its code.
  - Nesting: an experiment created while `VMN_EXPERIMENT_ID` is set records it as its `parent`, so a sweep wrapped in `vmn-exp run` yields one outer job with inner jobs. `create`/`run --parent <ref>` sets it explicitly. `kind` is `outer`/`inner`/`single`; an outer job's `tree_status` rolls up its subtree (`failed > stuck > running > created > succeeded`).
  - Sweeps (docs/sweeps.md): `vmn-exp sweep create <app> -f sweep.yml` stores a W&B-style spec (`method: grid|random|bayes`, `metric`, `parameters`, `run_cap`, `early_terminate: {type: median}`, `command`/`program` template) on an outer run; `vmn-exp sweep agent <app> <sweep> [--count] [--retry-failed] [-- cmd]` claims trial slots with `create_exclusive` (records `t<N>`/`t<N>.a<K>` in the reserved `vmn-sweeps/...` app; never reused), runs each as an inner job with `VMN_SWEEP_PARAMS`, and median-stops laggards (recorded as `end_reason: stopped` in `run_state.yml`, which derives as succeeded; `end_reason` is a row/query field). A trial's metric is its own, else its nested SDK runs' (single one, or best by goal). `sweep status [--json]`, `GET .../experiments/{verstr}/sweep`; SDK `from vmn_exp.sdk import sweep_params`. bayes needs optuna.
  - `import-mlflow`: `vmn-exp import-mlflow (--mlruns <dir> | --tracking-uri <uri>) [--experiment <name|id>]... [--skip-artifacts] [--include-deleted] [--dry-run] [--workers 8] <app>` — import runs from an MLflow FileStore or tracking server. Exactly one source required. Re-import is idempotent (already-present runs are skipped). No repo lock taken; no auto-init. Summary line: `imported N, skipped M (already present), resumed K, failed F`; exit 1 if any failed. `--tracking-uri` requires `pip install mlflow-skinny`.
- `vmn-exp ui`: Serve the web dashboard + REST API (`pip install "vmn-exp[ui]"`). `--host`, `--port` (8265), `--token`, `--data-dir`, `--repo` (repeatable), `--store <uri>` (`s3://bucket/prefix?endpoint_url=` for MinIO), `--read-only`, `--no-browser`, `--no-index`, `--allowed-host` (repeatable). Without a token, `/api` only accepts loopback/allowed `Host` headers (DNS-rebinding guard); mutations reject foreign `Origin`s and need `Content-Type: application/json`; URL app names/verstrs are validated; the SPA fallback never serves files outside `static/`. Responses are gzipped and NaN-safe. `vmn-exp ui` keeps each watched app's index fresh from a background refresher, so requests read a lock-free snapshot (list/detail stay ~ms at 100k runs); list/detail/columns answer ETag/304; `experiments-facets`, `experiments-columns` (whole-set chart data) and `POST .../series` (batched overlay series) exist. The list endpoint pages (`offset`/`limit` <= 1000), sorts server-side (`sort`, `sort=timestamp|started_at|finished_at`, `order=asc|desc`); run detail is bounded (`log_tail`/`log_total`, per-metric `series` downsampled to `max_points`, `include_log=1` for the full log) and `/experiments/{verstr}/log?offset&limit` pages the log. With the GIL on and a watched app of >= 10k runs it logs a one-time hint to run it on free-threaded 3.14t (`uvx --python 3.14t --from "vmn-exp[ui]" vmn-exp ui`; ~10x the throughput at 100k runs). See docs/ui.md.
- `vmn-exp model <action> [model] [flags]`: Model registry — link named, versioned model identifiers to experiment runs. Actions: `register` (attach a run ref + artifact path to a new version), `alias` (point a mutable alias at a version number), `list`, `show`, `resolve` (print version metadata for a ref), `deprecate`, `delete`. All actions are git-free; storage resolved from `--dir`/`--store`/`--bucket` or env. Refs: `model`, `model@latest`, `model@N`, `model@alias`. `register --alias <name>` sets an alias on create; `alias --expect <N>` is a CAS guard. Prune refuses registered runs even with `--force`; delete the model version first. SDK: `from vmn_exp.sdk.models import register_model, set_alias, remove_alias, get_model_version, list_models, download_model`; `run.register_model(name, artifact_path=, alias=)`. See docs/models.md.
- `vmn skill`: Print the AI-agent skill block to stdout. `--install` writes it instead (`--target claude` → `.claude/skills/vmn/SKILL.md`, `cursor` → `.cursorrules`, `agents` → `AGENTS.md`); `--force` overwrites an existing Claude SKILL.md. Cursor/agents targets only rewrite vmn's marker block and preserve surrounding text.
- `vmn config <name>`: TUI config editor. `--vim` for $EDITOR, `--global` for repo-level config. `--branch` edits the current branch's canonical branch conf (seeded from the effective conf).
- `vmn config gen <name>`: Non-interactively create a config file (no TTY needed, for CI/scripting). Default creates `conf.yml`; `--branch` (± `--root`) creates the canonical branch conf seeded from the existing effective conf. Never overwrites an existing file.
- `vmn worktrees create <name>` (alias `vmn wt`): Create an island (git worktrees for main repo + all deps). `--island-name`, `-fv`/`--from-version`, `-fb`/`--from-branch`, `--base-path` (default `../vmn-islands`), `--shallow-deps`, `--carry-changes` (apply the app's and deps' uncommitted tracked edits as a patch and copy their untracked non-ignored files into the island; a checkout not at the source's commit is skipped with a warning; without the flag, `create` only warns). `create` is the default action, so `vmn wt <name>` works.
- `vmn worktrees list`: List active islands.
- `vmn worktrees remove <island>`: Clean up an island (removes its worktrees, private branches, and the `vmn-readonly` remote once no island uses it).
- `vmn worktrees freeze <name>`: In the app checkout, pin every dep that is on a real (non-`island/`) branch to that branch in the current branch's canonical branch conf. Refuses on an `island/` branch, on detached HEAD, or while a dep has commits only on its private branch. Never commits or pushes.
- `vmn worktrees pull [island]`: `git pull --rebase` in every island checkout still on its private branch (skips repos moved to a real branch; dirty repos and conflicts exit 1). Without a name, finds `island.json` above the cwd.
- `vmn --completion [SHELL]`: Print shell completion setup script (bash/zsh/fish/tcsh). Auto-detects shell.
- `vmn --completion-install [SHELL]`: Append completion to shell rc file. Idempotent.
- `vmn --completion-uninstall [SHELL]`: Remove completion from the shell rc file. Idempotent.

### Islands (worktrees)

- Layout mirrors the source: every checkout sits at its path relative to the common parent of the app and its deps, so configured dep paths like `../libs/B` resolve inside the island.
- Source branch = the branch each repo was on (or `--from-branch`); `--from-version` islands have none. Each repo with a source branch gets private branch `island/{name}/{source}` tracking `vmn-readonly/{source}` with `pushRemote=vmn-readonly`. `vmn-readonly` is a per-repo remote with origin's fetch URL, an unusable push URL, and refspecs only for islands' source branches; vmn never selects it as its remote.
- Dep start point comes from the conf pin: hash/tag → that ref (detached); branch X → the local checkout if it is on X, else `vmn-readonly/X` fetched; no pin → the local checkout.
- `stamp`/`release`/`add`/`init-app` are refused on an `island/` branch (checked before the lock). A real branch checked out inside an island stamps normally once pushed. A dep on `island/{name}/X` with no commits beyond its upstream counts as synced with a `branch: X` pin.
- `island.json` in the island root is the machine-readable manifest (paths, private `branch`, `source_branch`, `upstream`, dep hashes, `shallow_deps`).
- vmn never borrows another branch's upstream: a branch whose upstream is missing (or on another remote) needs `git push -u origin <branch>` before `vmn stamp`.
- Islands are for app + deps work next to `goto`, not the way to spawn parallel worktrees — the worktree methodology uses plain `git worktree`.

## Environment Variables

- `VMN_WORKING_DIR`: Override the working directory for vmn
- `VMN_LOCK_FILE_PATH`: Custom lock file path (default `.vmn/vmn.lock`, a per-repo lock preventing concurrent vmn commands). Purely a user-facing override — vmn never injects it into a child process's environment. `exp run` and the SDK hold this lock only for their create/auto-init phase, not for the run's lifetime.
- `GITHUB_TOKEN` / `GH_TOKEN`: Required for GitHub Releases feature
- `VMN_GIT_PUSH_USER` / `VMN_GIT_PUSH_TOKEN`: Fallbacks for `stamp`/`release` `--git-push-user`/`--git-push-token`
- `VMN_UI_TOKEN`: Fallback for `vmn-exp ui --token`
- `VMN_EXP_MIN_STALE_SEC`: Overrides the 60s floor of the stuck window (`max(3 * interval, floor)`), read wherever status is derived (CLI, `vmn-exp ui`). Non-positive/invalid values keep 60.
- `VMN_EXP_KILL_GRACE_SEC`: Fallback for `vmn-exp run --kill-grace-sec` (seconds a forwarded signal waits before SIGKILL)
- `VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC`: Seconds the SDK waits for a run's last remote uploads when it is finalized (`finish()`, SIGTERM, interpreter exit; default 60). Several runs finalized together share this one wait (each drains its media uploads before its final log flush, then all final states are written before the remaining uploads are awaited). Non-positive/invalid values keep 60.
- `VMN_SNAPSHOT_MAX_FILE_MB` / `VMN_SNAPSHOT_MAX_TOTAL_MB`: caps on untracked files captured into a snapshot/experiment tarball (defaults 50 / 200; skipped paths are recorded as `untracked_skipped`)
- `VMN_CAPTURE_ENV`: Set to `0`/`false`/`no`/`off` to disable automatic environment capture (Python version, platform, installed packages) on `vmn-exp create`, `vmn-exp run`, and `start_run()`. CLI `--no-env` and `start_run(capture_env=False)` also opt out; `start_run(capture_env=True)` overrides this variable and conf.yml but cannot override the CLI flag. Opt-out precedence: CLI flag > `VMN_CAPTURE_ENV` > conf `experiment.capture_env`.
- `VMN_EXPERIMENT_DIR` / `VMN_SNAPSHOT_METADATA`: git-free experiment mode (container images built from `vmn-exp export`) for both the CLI and `start_run()`
- `VMN_EXPERIMENT_STORE`: fallback for `--store` (a store URI; beats the bucket shorthand)
- `VMN_SYSTEM_METRICS`: `0`/`false`/`no`/`off` disables default `sys_*` sampling
- `VMN_EXP_OUTPUT_CAP_MB`: fallback for `vmn-exp run --output-cap-mb`
- `VMN_EXP_ALERT_WEBHOOK_URL` / `VMN_EXP_ALERT_SLACK_URL` / `VMN_EXP_ALERT_COMMAND` / `VMN_EXP_ALERT_ON`: add alert sinks / set triggers
- `VMN_EXPERIMENT_BUCKET` / `VMN_EXPERIMENT_PREFIX` / `VMN_EXPERIMENT_ENDPOINT_URL`: fallbacks for the experiment `--bucket`/`--prefix`/`--endpoint-url` (flags > env > conf.yml), honoured by the CLI and `start_run()`; with a bucket and no local dir, runs record straight to S3
- Set *by* vmn for the `vmn-exp run` child process: `VMN_EXPERIMENT_ID`, `VMN_APP_NAME`, `VMN_METRICS_FILE`, `VMN_EXP_SUPERVISOR_SAMPLES` (when it samples system metrics); sweep trials also get `VMN_SWEEP_PARAMS`/`VMN_SWEEP_ID`/`VMN_SWEEP_TRIAL`. `VMN_EXPERIMENT_ID` also drives auto-parenting — any experiment created while it is set becomes an inner job of that run.

## Docs Layout

- `README.md`: user-facing overview. Skimmable top level with reference material inside `<details>` blocks; deep guides live in `docs/` and are linked, not inlined. Keep it that way — don't paste long reference back into it.
- `docs/agent-skill.md`: **generated** from `vmn skill`. Regenerate it (don't hand-edit) whenever `packages/vmn/src/version_stamp/cli/skill.py` changes.
- `docs/ai-fleet-tracking.md`: for AI agents — which SDK/CLI call moves each UI fleet column (total/waiting/running/done/failed).
- `docs/client-guide.md`: task-oriented `vmn-exp` walkthrough from the client's side (install, store, submit/sweep, in-job SDK, watch, compare, restore vs goto, resume/rewind/fork decision table with worked examples, models, prune). Link to the reference docs rather than duplicating them.
- `docs/experiments.md`: full `vmn-exp` guide. `docs/sdk.md`: the `vmn_exp.sdk` Python SDK (`start_run`, reader API, integrations) — keep the SDK reference there, not in experiments.md. `docs/ui.md`: `vmn-exp ui` deployment + API. `docs/models.md`: model registry reference (CLI, SDK, UI, storage, prune protection).
- `docs/packaging.md`: the three-package split, import rules, and how releases version each package.
- `docs/vmn-vs-*.md`, `docs/migrating-from-*.md`: migration guides from other tools (includes `docs/migrating-from-mlflow.md`).
