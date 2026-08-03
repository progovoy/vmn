# CLAUDE.md

# Claude Code instructions

When generating commit messages, pull request text, patches, or any code-related output, never include this line:

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

Omit any Claude co-author trailer unless I explicitly ask for it.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Splitting tasks
Always split big tasks into separate worktrees and do in parallel.
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

Tests require Docker. Run the full test suite:
```sh
./tests/run_pytest.sh
```

Run a specific test:
```sh
./tests/run_pytest.sh --specific_test <test_name>
```

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
- `vmn experiment [action] <name>` (alias `vmn exp`): Local-first experiment tracking (a snapshot + an append-only metrics/notes log). Actions: `create` (default), `run`, `add`, `list`, `show`, `compare`, `diff`, `restore`, `export`, `prune`. `vmn exp run <name> -- <cmd>` runs a command and ingests `key=value` lines the child writes to `$VMN_METRICS_FILE`. See docs/experiments.md.
- `vmn ui`: Serve the web dashboard + REST API (`pip install "vmn[ui]"`). `--host`, `--port` (8265), `--token`, `--data-dir`, `--repo` (repeatable), `--s3-bucket`/`--s3-prefix`/`--endpoint-url`, `--read-only`, `--no-browser`, `--no-index`. See docs/ui.md.
- `vmn skill`: Print the AI-agent skill block to stdout. `--install` writes it instead (`--target claude` → `.claude/skills/vmn/SKILL.md`, `cursor` → `.cursorrules`, `agents` → `AGENTS.md`); `--methodology` appends the opinionated TDD/worktree rules; `--force` overwrites an existing Claude SKILL.md. Cursor/agents targets only rewrite vmn's marker block and preserve surrounding text.
- `vmn config <name>`: TUI config editor. `--vim` for $EDITOR, `--global` for repo-level config. `--branch` edits the current branch's canonical branch conf (seeded from the effective conf).
- `vmn config gen <name>`: Non-interactively create a config file (no TTY needed, for CI/scripting). Default creates `conf.yml`; `--branch` (± `--root`) creates the canonical branch conf seeded from the existing effective conf. Never overwrites an existing file.
- `vmn worktrees create <name>`: Create isolated development islands (git worktrees for main repo + all deps). `--island-name`, `-fv`/`--from-version`, `-fb`/`--from-branch`, `--base-path` (default `../vmn-islands`), `--no-stamp`, `--shallow-deps`, `--editable-dep`. `create` is the default action, so `vmn worktrees <name>` works.
- `vmn worktrees list`: List active islands.
- `vmn worktrees remove <island>`: Clean up an island (removes its worktrees and local branches).
- `vmn --completion [SHELL]`: Print shell completion setup script (bash/zsh/fish/tcsh). Auto-detects shell.
- `vmn --completion-install [SHELL]`: Append completion to shell rc file. Idempotent.
- `vmn --completion-uninstall [SHELL]`: Remove completion from the shell rc file. Idempotent.

### Islands (worktrees)

- Main repo gets a new branch `island/{name}/{original-branch}`; deps are detached HEAD at the hash recorded when the source version was stamped. `--editable-dep` gives a dep its own island branch.
- `island.json` in the island root is the machine-readable manifest (paths, branches, dep hashes, `readonly`, `shallow_deps`).
- Stamping inside an island keeps the version commit on the local island branch and pushes only the tag — the island branch is never published. `--no-stamp` creates a read-only island where `vmn stamp` is refused.

## Environment Variables

- `VMN_WORKING_DIR`: Override the working directory for vmn
- `VMN_LOCK_FILE_PATH`: Custom lock file path (default `.vmn/vmn.lock`, a per-repo lock preventing concurrent vmn commands)
- `GITHUB_TOKEN` / `GH_TOKEN`: Required for GitHub Releases feature
- `VMN_GIT_PUSH_USER` / `VMN_GIT_PUSH_TOKEN`: Fallbacks for `stamp`/`release` `--git-push-user`/`--git-push-token`
- `VMN_UI_TOKEN`: Fallback for `vmn ui --token`
- Set *by* vmn for the `vmn exp run` child process: `VMN_EXPERIMENT_ID`, `VMN_APP_NAME`, `VMN_METRICS_FILE`

## Docs Layout

- `README.md`: user-facing overview. Skimmable top level with reference material inside `<details>` blocks; deep guides live in `docs/` and are linked, not inlined. Keep it that way — don't paste long reference back into it.
- `docs/agent-skill.md`: **generated** from `vmn skill --methodology`. Regenerate it (don't hand-edit) whenever `version_stamp/cli/skill.py` changes.
- `docs/experiments.md`: full `vmn exp` guide. `docs/ui.md`: `vmn ui` deployment + API.
- `docs/vmn-vs-*.md`, `docs/migrating-from-*.md`: migration guides from other tools.
