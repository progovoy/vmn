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
pip install -r ./packages/vmn-exp/tests/test_requirements.txt  # core + vmn-exp test deps
pip install -e packages/vmn -e packages/vmn-exp-sdk -e "packages/vmn-exp[ui]"
make _build_ui  # the web UI bundle (vmn_exp/ui/static, export_bundle) is git-ignored build output; needs npm
vmn --version  # e.g. 0.10.2-rc.11+dev: a source checkout adds +dev
```

`uv sync` also works from the repo root. Build the wheels with
`uv build --all-packages` (or `make _build NAME=vmn|vmn_exp`, which builds the
web UI first; a bare `uv build` ships whatever bundle is on disk).

Import rules (packages/vmn-exp/tests/test_packaging_split.py): `version_stamp` never imports
`vmn_exp`; the vmn-exp-sdk subpackages import neither `version_stamp` nor the
vmn-exp subpackages (except a lazy `vmn_exp.gitmode`); vmn-exp reaches
`version_stamp` only through `version_stamp.api`. vmn loads `vmn goto` of dev
versions (`register_dev_version`) from the `vmn.plugins` entry point that
vmn-exp declares.

## Running Tests

Two suites (vmn-exp will become a separate product):
- **core** — `tests/`: vmn alone. `tests/conftest.py` puts only `packages/vmn/src`
  on `sys.path` and makes `vmn_exp` unimportable (`tests/no_vmn_exp.py`), so it
  passes without vmn-exp installed; deps in `tests/test_requirements.txt`.
- **exp** — `packages/vmn-exp/tests/`: vmn-exp. Its conftest adds all three
  `src/` roots plus `tests/`, reusing the core fixtures (`tests/vmn_fixtures.py`)
  and helpers (`exp_helpers.py` = `tests/helpers.py` + `_experiment`/`_exp`/
  `_storage`/`cli_module`); deps in `packages/vmn-exp/tests/test_requirements.txt`
  (includes the core file). A test that needs `vmn_exp` or a vmn-exp command
  belongs here; one asserting vmn works *without* vmn-exp belongs in core.

Tests require Docker. Activate the test venv first — the suites run through the
active interpreter's `coverage`/`pytest`, and the release-notes tests need the
`git-cliff` binary that `tests/test_requirements.txt` installs into it.
```sh
source ./venv/bin/activate
./tests/run_pytest.sh                        # core suite (= --suite core)
./packages/vmn-exp/tests/run_pytest.sh       # exp suite (= tests/run_pytest.sh --suite exp)
```

Run a specific test:
```sh
./tests/run_pytest.sh --specific_test <test_name>
./packages/vmn-exp/tests/run_pytest.sh --specific_test <test_name>
```

UI load harness (real `vmn-exp ui` + live job processes; see packages/vmn-exp/tests/uiload/README.md):
```sh
python packages/vmn-exp/tests/uiload/run.py live --profile smoke --duration 0   # watch in a browser
VMN_UILOAD_PROFILE=smoke python -m pytest -s packages/vmn-exp/tests/test_uiload_profile.py
```

CI is the local Muster pipeline in `ci/pipeline.py` (`./ci/start.sh`, see
`ci/README.md`) — there is no GitHub Actions workflow.

Skip a test:
```sh
./tests/run_pytest.sh --skip_test <test_name>
```

Tests run in parallel (29 workers by default) using pytest-xdist. Timing benchmarks carry
`@pytest.mark.serial`: `run_pytest.sh` (and the CI `tests_exp` stage) run them alone in a
second, one-process pass, since under 29 busy workers they measure contention.

### Key Concepts

- **App name**: Identifier for a versioned app (e.g., `my_app` or `root_app/service1`). Cannot contain `-` or start with `/`
- **Root app**: Parent container for microservices, format `root_app/service_name`. Root version is an auto-incrementing integer.
- **Version format**: `major.minor.patch[.hotfix][-prerelease.rcn][+buildmetadata]`
- **Tag format**: `{app_name}_{version}` where `/` in app names becomes `-`

### Data Flow

1. Version info stored in git annotated tag messages as YAML (`vmn_info` + `stamping` sections with changesets). Changeset `remote`s carry no credentials (`core/utils.py:redact_changesets`: `https://user:token@host/x` → `https://host/x`, ssh keeps its user); `vmn goto` cloning a dep from such a URL borrows the checkout's own remote's credentials on the same scheme+host (`borrow_credentials`).
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

- `tests/vmn_fixtures.py`: Pytest fixtures including `FSAppLayoutFixture` for creating isolated git repos, registered by both suites' `conftest.py`
- Tests create temporary git repos with remotes to simulate real workflows

## CLI Commands (core vmn)

Full flag reference: README.md `<details>` blocks and `vmn <cmd> --help`.

- `vmn stamp -r <mode> <name>`: stamp a version (major/minor/patch/hotfix). Auto-inits, idempotent. `--pr <id>` prerelease, `--orm` optional release mode, `--pull`, `--dry-run`, `--git-push-user/--git-push-token` (env `VMN_GIT_PUSH_*`; ephemeral HTTPS push URL only). Without `-r`: only mid-prerelease or with `conventional_commits`.
- `vmn release <name>`: promote prerelease to final (`-v`, `--stamp`). Pushes only its tag.
- `vmn show <name>`: version info (`--verbose`, `--raw`, `--base`, `--type`, `-u`, `--dev`, `--conf`, `--from-file`, `--ignore-dirty`, `-t`).
- `vmn goto -v <version> <name>`: checkout repo + deps at a version; without `-v` returns to a branch tip via `ensure_on_branch()` (`backends/branch_checkout.py`, resolver in `backends/branch_resolver.py`). Building a backend never switches branches; commands that commit declare `commits` in their `CommandSpec` (`cli/constants.py`, `cli/plugin_api.py`). `tests/test_git_process_budget.py` caps git processes for detached stamp/goto. Dev-version goto restores through `version_stamp.snapshot.restore.restore_record`.
- `vmn gen -t <template> -o <output> <name>`, `vmn add -v <version> --bm <metadata> <name>`.
- `vmn snapshot [create|list|show|note|delete|restore|export|diff] <name>`: save/restore uncommitted work as a dev verstr (`cli/snapshot_cmd.py`, `version_stamp/snapshot/`). See docs/snapshots.md.
- `vmn config <name>` (TUI; `--vim`, `--global`, `--branch`), `vmn config gen <name>` (non-interactive, never overwrites).
- `vmn worktrees create|list|remove|freeze|pull` (alias `vmn wt`): islands — see below.
- `vmn skill [--install --target claude|cursor|agents]`, `vmn --completion[-install|-uninstall]`.

### Islands (worktrees)

- Layout mirrors the source relative to the common parent of app + deps; manifest in `island.json`.
- Each repo gets private branch `island/{name}/{source}` tracking the `vmn-readonly` remote (unusable push URL). `stamp`/`release`/`add`/`init-app` are refused on `island/` branches.
- vmn never borrows another branch's upstream: `git push -u origin <branch>` before `vmn stamp`.
- Islands are for app + deps work next to `goto`; parallel agent worktrees use plain `git worktree`.

## vmn-exp

`vmn-exp` (experiment tracking, SDK, model registry, sweeps, web UI/server) is documented in `docs/vmn-exp/` — read the relevant doc before changing a feature, and `docs/plans/<NN>-*.md` for the design behind a plan item. Architecture overview: `docs/vmn-exp/architecture.md`.

| Topic | Doc |
|---|---|
| CLI reference, status/alerts, nesting, storage + plugin contract, offline/push, streams, env vars | `experiments.md` |
| Python SDK (`start_run`, logging, autolog, readers, query language) | `sdk.md` |
| `vmn-exp ui` + HTTP API, boards, outer runs, pivots, baselines | `ui.md` |
| Central server, settings, journal, auth | `server.md`, `byo-bucket.md` |
| Model/dataset registry, sweeps, reports | `models.md`, `sweeps.md`, `reports.md` |

Invariants worth knowing without opening a doc:
- Packages: `vmn_exp/sdk` depends only on `vmn_exp.core|storage|registry|_base`, never `version_stamp`/`snapshot`/`ui`/`cli`; git-mode creation (`vmn_exp.gitmode`) is imported lazily.
- Status is derived, never stored (`created`/`running`/`stuck`/`succeeded`/`failed`); `stuck` = stale heartbeat *and* stale store write time past `max(3 * interval, 60s)`.
- Read-only actions never take the repo lock; `vmn-exp run` and the SDK hold it only for create/auto-init.
- Run verstrs are claimed atomically (`create_exclusive`); local writes are temp + rename; only a stream's owner appends/ships/compacts it.
- Store layout v2 (`store.yml`, `layout: 2`); v1 stores are refused with a migrate hint. Per-host state (index cache, push ledger) lives outside the store (`storage/host_dirs.py`).
- Every vmn SQLite file goes through `core/sqlite_conn.py`.
- The UI reads lock-free index snapshots kept fresh by a background refresher; never add per-request store listing.

## Environment Variables

Core: `VMN_WORKING_DIR`, `VMN_LOCK_FILE_PATH` (user override only; vmn never injects it into a child), `GITHUB_TOKEN`/`GH_TOKEN`, `VMN_GIT_PUSH_USER`/`VMN_GIT_PUSH_TOKEN`, `VMN_SNAPSHOT_MAX_FILE_MB`/`VMN_SNAPSHOT_MAX_TOTAL_MB`.
vmn-exp (`VMN_EXP_*`, `VMN_EXPERIMENT_*`, `VMN_MODE`, `VMN_CAPTURE_ENV`, `VMN_SYSTEM_METRICS`, `VMN_UI_TOKEN`, …): see docs/vmn-exp/experiments.md. `VMN_EXPERIMENT_ID` set in the environment auto-parents any new run.

## Docs Layout

Core vmn and vmn-exp are documented separately (vmn-exp will become a separate product): core docs never carry experiment material beyond one link to `docs/vmn-exp/README.md`.

- `README.md`: core vmn only. Skimmable top level with reference material (commands, flags, conf.yml keys, backends, env vars) inside `<details>` blocks; deep guides live in `docs/` and are linked, not inlined. Keep it that way — don't paste long reference back into it.
- `docs/agent-skill.md`: **generated** from `vmn skill`. Regenerate it (don't hand-edit) whenever `packages/vmn/src/version_stamp/cli/skill.py` changes.
- `docs/vmn-exp/agent-skill.md`: **generated** from `vmn-exp skill`. Regenerate it (don't hand-edit) whenever `packages/vmn-exp/src/vmn_exp/cli/skill.py` changes.
- `docs/snapshots.md`: the `vmn snapshot` guide (core vmn; vmn-exp stores in one closing section). `docs/packaging.md`: the three-package split, import rules, and how releases version each package. `docs/agent-methodology.md`: optional dev rules for AI agents.
- `docs/vmn-vs-*.md`, `docs/migrating-from-*.md`: comparison/migration guides for core vmn; they link to README anchors instead of repeating setup.
- `docs/vmn-exp/`: all vmn-exp docs, indexed by `docs/vmn-exp/README.md`. One canonical home per topic; other docs summarize and link:
  - `client-guide.md`: task walkthrough (store choice, submit/sweep, Kubernetes git-free recipe, in-job SDK, watch, compare, restore/goto/rerun/export, resume/rewind/fork, models, prune).
  - `experiments.md`: `vmn-exp` CLI reference, status/alerts, nesting, storage + plugin contract, offline + `push`, env vars.
  - `sdk.md`: the `vmn_exp.sdk` Python SDK (`start_run`, logging, autolog, readers, query language, integrations).
  - `ui.md`: `vmn-exp ui` deployment + HTTP API. `models.md`: model/dataset registry. `sweeps.md`: sweeps.
  - `server.md`: `vmn-exp ui` as a central server (`server.yml`, SQLite cache, change journal, resync/rebuild, OIDC/API tokens/roles). `byo-bucket.md`: store areas, the server's permission sets, journal lifecycle rule. `reports.md`: reports, panels, publish/export, comments.
  - `ai-fleet-tracking.md`: for AI agents — which SDK/CLI call moves each UI fleet count (the parent group header). `vmn-vs-mlflow.md`, `migrating-from-mlflow.md`.
