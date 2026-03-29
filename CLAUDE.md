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
- `default_release_mode`: `optional` (--orm behavior) or `strict` (-r behavior) when using conventional_commits
- `changelog.path`: Generate CHANGELOG.md on stamp (requires conventional_commits)
- `github_release.draft`: Create GitHub Release on stamp (requires `gh` CLI + `GITHUB_TOKEN`)
- `deps`: External repository dependencies for multi-repo tracking
- `version_backends`: Auto-embed version into package.json, Cargo.toml, pyproject.toml, or any file via regex/Jinja2
- `policies.whitelist_release_branches`: Restrict which branches can stamp/release
- Branch-specific overrides: `<branch>_conf.yml` next to `conf.yml`

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
- `vmn release <name>`: Promote prerelease to final. `-v <version>` for explicit, `--stamp` for full stamp flow.
- `vmn show <name>`: Display version info. `--verbose` for full YAML, `--raw`, `--type`, `-u` for unique ID.
- `vmn goto -v <version> <name>`: Checkout repo + all deps to exact state at version. `--deps-only`, `--root`.
- `vmn gen -t <template> -o <output> <name>`: Generate file from Jinja2 template.
- `vmn add -v <version> --bm <metadata> <name>`: Attach build metadata.
- `vmn config <name>`: TUI config editor. `--vim` for $EDITOR, `--global` for repo-level config.

## Environment Variables

- `VMN_WORKING_DIR`: Override the working directory for vmn
- `VMN_LOCK_FILE_PATH`: Custom lock file path (default is per-repo lock to prevent concurrent vmn commands)
- `GITHUB_TOKEN` / `GH_TOKEN`: Required for GitHub Releases feature
