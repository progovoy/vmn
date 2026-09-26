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

```sh
python3 -m venv ./venv
source ./venv/bin/activate
pip install -r ./tests/requirements.txt
pip install -r ./tests/test_requirements.txt
pip install -e ./
vmn --version  # Should see 0.0.0 if installed successfully
```

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
- `vmn snapshot [action] <name>`: Capture/restore uncommitted work as a deterministic dev version. Actions: `create` (default), `list`, `show`, `note`, `diff`, `export`, `restore`. Version-taking actions accept a full verstr, a unique prefix, `--latest`, or `@N`.
- `vmn experiment [action] <name>` (alias `vmn exp`): Local-first experiment tracking (a snapshot + an append-only metrics/notes log). Actions: `create` (default), `run`, `add`, `list`, `show`, `compare`, `diff`, `restore`, `export`, `prune`, `tag`, `archive`, `unarchive`. `create`/`run --name` names a run; `list --query <expr>` filters, `list`/`show --json` print machine-readable output; archived runs are hidden unless `list --archived`. `vmn exp run <name> -- <cmd>` runs a command and ingests `key=value` lines the child writes to `$VMN_METRICS_FILE`. See docs/experiments.md.
  - `run` publishes `run_state.yml` (state/pid/host/heartbeat/exit_code) next to `metadata.yml` and refreshes a heartbeat while the child lives; `--heartbeat-interval <sec>` (default 30).
  - `exp run` supervision is crash-proof: the metrics tailer reads bytes (non-ASCII lines never kill it), ingestion/heartbeat/sync errors are best-effort, SIGTERM/SIGINT/SIGHUP are forwarded to the child (SIGKILL after `--kill-grace-sec`, default 30 / `VMN_EXP_KILL_GRACE_SEC`) and the final state is always written (`exit_code` = `128+N` when signal N ended the child; `signal`/`received_signal` fields). The child runs in the invocation cwd (or `$VMN_WORKING_DIR`). Remote sync runs off the heartbeat loop.
  - Read-only actions (`list`/`show`/`compare`/`diff`/`export`, and the same `snapshot` actions) never take the repo lock. `list` row numbers are the storage index `@N` resolves, whatever `--sort`/`--last`/`--top` do. `show` prints the last 50 log entries (`--full-log` for all). `prune` never deletes `running` or `stuck` runs, or a run carrying a `--protect-tag`-named tag key (`--force` overrides either), or a run with a kept descendant; `--dry-run` previews, `--local-only` keeps remote copies, `-v <ref>` (repeatable, not combined with `--keep`/`--older-than`) deletes exactly the named run(s) instead of a bulk policy.
  - Metric values: numeric only. numpy/torch scalars and numeric strings are coerced to float; bools/strings/vectors are dropped with a warning; NaN/inf are kept in the log and served as JSON `null`. Missing/non-finite values sort last in both directions. Numeric params fold into `metrics` only when finite (bools fold as 1.0/0.0).
  - Status is derived, never stored: `created`/`running`/`stuck`/`succeeded`/`failed`. `stuck` = claims running with no exit code, and both the heartbeat timestamp (writer clock) and the store's write time of `run_state.yml` (file mtime / S3 `LastModified`, when known) are stale past `max(3 * interval, 60s)` — a fresh store write proves liveness despite writer clock skew; unknown store time falls back to the heartbeat alone.
  - Python SDK: `from version_stamp.exp import start_run` — in-process alternative to `exp run` (`run.log_metric/log_metrics/log_params/log_note/log_artifact/log_artifacts/log_dict/log_text/log_figure/set_tag(s)`, `run.finish()`; log writes are batched and flushed at most ~1s apart, on heartbeat and on finish/SIGTERM/exit; `start_run(name=, tags=, run_id=<resume>, snapshot=False, all_ranks=False)` — ranks > 0 get a no-op run; the snapshot is captured outside the repo lock; an SDK cold start commits/tags locally without pushing; read side `version_stamp.exp.reader.get_run/list_runs`). Writes the same files as the CLI and heartbeats from its own daemon thread (which also syncs the log to a remote every `sync_interval_sec`, default 30). `current_run()` returns the run the calling thread records into (its own context-bound run, else the process's only open run); runs are fork-aware (`Run.pid`), and `VMN_EXPERIMENT_ID` never parents a run to a sibling another thread opened. With `VMN_SNAPSHOT_METADATA` set, `start_run()` works without a git checkout (storage from `VMN_EXPERIMENT_DIR`). `version_stamp/exp/` must depend only on `version_stamp.core` + the snapshot helpers, never on `version_stamp.ui`, so it stays liftable into its own distribution. See docs/sdk.md.
  - Autologging: `from version_stamp.exp import autolog, autolog_disable`. `autolog()` wraps framework `fit()` methods to record hyperparameters, final metrics, per-epoch series where the framework exposes one, and (with `log_models=True`; default off) the model in its native format. Frameworks are patched only once imported (`version_stamp/exp/import_hooks.py`), so `autolog()` never imports tensorflow/torch itself. Fits record into `current_run()`; framework worker threads without their own run are ignored while a recorded fit is in progress. Search estimators add `sklearn_best_cv_score`/`sklearn_best_<param>`; `sklearn_score` is a training-set score, computed when `training_score="auto"` (<= 10k rows). Lightning under DDP skips model saving. Supported: `sklearn`, `xgboost`, `keras`/`tensorflow`, `lightning`/`pytorch_lightning`. Plain `torch` has no `fit` to wrap — use explicit `run.log_metric(...)` in your own loop. Add a framework with an `_Adapter` entry in `SUPPORTED_FRAMEWORKS` in `version_stamp/exp/autolog.py` (only `discover` is mandatory; the other hooks default to the sklearn behaviour). Records nothing unless a `start_run()` is open (never opens one implicitly — that would stamp a version from inside `fit()`). Keys are `<framework>_<name>` with an underscore so the query language's two-part paths resolve them. Failures never break `fit()`; patching is idempotent and `autolog_disable()` restores the originals.
  - Query language (`version_stamp/core/experiment_query.py`): filters rows for `list_runs(query=...)` and the UI's `?q=`. Comparisons `= == != < <= > >=`, `~`/`contains`/`!~` (case-insensitive substring; on list fields like `command`/`children` any element matches), numbers accept scientific notation (`1e-4`), `in`/`not in`, `and`/`or`/`not`, parens. Fields are bare row keys, `metrics.<name>` (numeric fold) and `params.<name>` (verbatim, so strings/bools work). Two-valued: a comparison against a missing field is false, `= null` tests absence. Bad queries raise `QueryError` with an offset (400 over HTTP). `vmn exp list --query` applies it on the CLI.
  - Lock scope: `exp run` holds the repo lock only for the create/auto-init phase and releases it before supervising the child, so long runs don't block other `vmn` commands and nesting works. The SDK scopes it the same way around create/cold-start.
  - Storage (`version_stamp/cli/snapshot_storage*.py`, re-exported from `cli/snapshot.py`): run verstrs are claimed atomically (`create_exclusive`: `O_EXCL` mkdir / S3 `If-None-Match`), so hosts sharing a bucket or NFS dir never collide; allocation lists names only. Local writes are atomic (temp + rename) and never resurrect a deleted record. Each storage dir carries a `.gitignore` of `*`. Remote log sync uploads only new lines as segments `log.<writer>@<seq>.jsonl`; `run_state.yml`/logs are never cached locally from a remote. S3 app keys use the tag form (`/`→`-`, legacy `_` still read); S3 `exists` is a HEAD; artifacts stream via `upload_file` and are listable/downloadable. Snapshot identity keeps the full `diff_hash` and extends the verstr's hash on a collision instead of overwriting.
  - Nesting: an experiment created while `VMN_EXPERIMENT_ID` is set records it as its `parent`, so a sweep wrapped in `vmn exp run` yields one outer job with inner jobs. `create`/`run --parent <ref>` sets it explicitly. `kind` is `outer`/`inner`/`single`; an outer job's `tree_status` rolls up its subtree (`failed > stuck > running > created > succeeded`).
- `vmn ui`: Serve the web dashboard + REST API (`pip install "vmn[ui]"`). `--host`, `--port` (8265), `--token`, `--data-dir`, `--repo` (repeatable), `--s3-bucket`/`--s3-prefix`/`--endpoint-url`, `--read-only`, `--no-browser`, `--no-index`, `--allowed-host` (repeatable). Without a token, `/api` only accepts loopback/allowed `Host` headers (DNS-rebinding guard); mutations reject foreign `Origin`s and need `Content-Type: application/json`; URL app names/verstrs are validated; the SPA fallback never serves files outside `static/`. Responses are gzipped and NaN-safe. `vmn ui` keeps each watched app's index fresh from a background refresher, so requests read a lock-free snapshot (list/detail stay ~ms at 100k runs); list/detail/columns answer ETag/304; `experiments-facets`, `experiments-columns` (whole-set chart data) and `POST .../series` (batched overlay series) exist. The list endpoint pages (`offset`/`limit` <= 1000), sorts server-side (`sort`, `sort=timestamp`, `order=asc|desc`); run detail is bounded (`log_tail`/`log_total`, per-metric `series` downsampled to `max_points`, `include_log=1` for the full log) and `/experiments/{verstr}/log?offset&limit` pages the log. See docs/ui.md.
- `vmn skill`: Print the AI-agent skill block to stdout. `--install` writes it instead (`--target claude` → `.claude/skills/vmn/SKILL.md`, `cursor` → `.cursorrules`, `agents` → `AGENTS.md`); `--methodology` appends the opinionated TDD/worktree rules; `--force` overwrites an existing Claude SKILL.md. Cursor/agents targets only rewrite vmn's marker block and preserve surrounding text.
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
- `VMN_UI_TOKEN`: Fallback for `vmn ui --token`
- `VMN_EXP_KILL_GRACE_SEC`: Fallback for `vmn exp run --kill-grace-sec` (seconds a forwarded signal waits before SIGKILL)
- `VMN_SNAPSHOT_MAX_FILE_MB` / `VMN_SNAPSHOT_MAX_TOTAL_MB`: caps on untracked files captured into a snapshot/experiment tarball (defaults 50 / 200; skipped paths are recorded as `untracked_skipped`)
- `VMN_EXPERIMENT_DIR` / `VMN_SNAPSHOT_METADATA`: git-free experiment mode (container images built from `vmn snapshot export`) for both the CLI and `start_run()`
- `VMN_EXPERIMENT_BUCKET` / `VMN_EXPERIMENT_PREFIX` / `VMN_EXPERIMENT_ENDPOINT_URL`: fallbacks for the experiment `--bucket`/`--prefix`/`--endpoint-url` (flags > env > conf.yml), honoured by the CLI and `start_run()`; with a bucket and no local dir, runs record straight to S3
- Set *by* vmn for the `vmn exp run` child process: `VMN_EXPERIMENT_ID`, `VMN_APP_NAME`, `VMN_METRICS_FILE`. `VMN_EXPERIMENT_ID` also drives auto-parenting — any experiment created while it is set becomes an inner job of that run.

## Docs Layout

- `README.md`: user-facing overview. Skimmable top level with reference material inside `<details>` blocks; deep guides live in `docs/` and are linked, not inlined. Keep it that way — don't paste long reference back into it.
- `docs/agent-skill.md`: **generated** from `vmn skill --methodology`. Regenerate it (don't hand-edit) whenever `version_stamp/cli/skill.py` changes.
- `docs/experiments.md`: full `vmn exp` guide. `docs/sdk.md`: the `version_stamp.exp` Python SDK (`start_run`, reader API) — keep the SDK reference there, not in experiments.md. `docs/ui.md`: `vmn ui` deployment + API.
- `docs/vmn-vs-*.md`, `docs/migrating-from-*.md`: migration guides from other tools.
