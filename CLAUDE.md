# CLAUDE.md

# Claude Code instructions

When generating commit messages, pull request text, patches, or any code-related output, never include this line:

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

Omit any Claude co-author trailer unless I explicitly ask for it.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

vmn is a CLI tool and Python library for automatic semantic versioning of software projects. It uses git tags to track versions and supports multi-repository dependencies, microservices architectures (root apps), and conventional commits for automatic release mode detection.

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

## Code Architecture

### Core Modules (`version_stamp/`)

**vmn.py** (~3600 lines) - Main entry point and business logic:
- Entry: `main()` → `vmn_run()` → `_vmn_run()` → `handle_<command>()`
- `VMNContainer`: Creates VCS backend and holds args/params
- `IVersionsStamper`: Base class for version operations
  - Loads config from `.vmn/{app_name}/conf.yml`
  - Version backend writers (`_write_version_to_npm`, `_write_version_to_cargo`, etc.)
  - `gen_advanced_version()`, `advance_version()` - version incrementing logic
- `VersionControlStamper(IVersionsStamper)`: Adds stamping/publishing
  - `find_matching_version()` - check if current state matches existing version
  - `stamp_app_version()` - create new version
  - `publish_stamp()` - commit, tag, and push
- Command handlers: `handle_init`, `handle_init_app`, `handle_stamp`, `handle_release`, `handle_show`, `handle_goto`, `handle_gen`, `handle_add`
- Argument parsing: `parse_user_commands()` with `add_arg_*` functions

**stamp_utils.py** (~1900 lines) - VCS abstraction and utilities:
- `VMNBackend`: Base class with static version string methods
  - `serialize_vmn_tag_name()`, `serialize_vmn_version()`, `deserialize_vmn_version()`
  - `get_utemplate_formatted_version()` - apply display template
- `GitBackend(VMNBackend)`: Git operations
  - `tag()`, `push()`, `commit()`, `checkout()`
  - `get_latest_stamp_tags()` - find version tags
  - `parse_tag_message()` - extract version info from tag
  - `perform_cached_fetch()` - fetch with 30-min cache
- `LocalFileBackend(VMNBackend)`: File-based backend for offline use
- Version regex patterns: `VMN_VERSION_REGEX`, `VMN_TAG_REGEX`, `VMN_ROOT_TAG_REGEX`
- `parse_conventional_commit_message()` - extract type/scope from commits

**version.py** - vmn's own version string

### Key Concepts

- **App name**: Identifier for a versioned application (e.g., `my_app` or `root_app/service1`). Cannot contain `-` or start with `/`
- **Root app**: Parent container for microservices, uses format `root_app/service_name`
- **Version format**: `major.minor.patch[.hotfix][-prerelease.rcn][+buildmetadata]`
- **Tag format**: `{app_name}_{version}` where `/` in app names becomes `-`

### Data Flow

1. Version info stored in git tag messages as YAML with structure:
   ```yaml
   vmn_info:
     vmn_version: "x.x.x"
   stamping:
     app:
       name: app_name
       _version: "1.0.0"
       changesets:
         ".": {hash: "abc123", remote: "...", vcs_type: "git"}
     root_app: {...}  # if microservice
   ```
2. Local state tracked in `.vmn/{app_name}/last_known_app_version.yml`
3. `stamp` command: increments version → writes to backends → commits → tags → pushes

### Configuration

Per-app configuration stored in `.vmn/{app_name}/conf.yml`:
- `template`: Version display format
- `deps`: External repository dependencies
- `version_backends`: Auto-embed version into package.json, Cargo.toml, etc.
- `policies`: Branch restrictions for stamping/releasing
- `conventional_commits`: Enable automatic release mode detection

### Test Infrastructure

- `tests/conftest.py`: Pytest fixtures including `FSAppLayoutFixture` for creating isolated git repositories
- Tests create temporary git repos with remotes to simulate real workflows

## Environment Variables

- `VMN_WORKING_DIR`: Override the working directory for vmn
- `VMN_LOCK_FILE_PATH`: Custom lock file path (default is per-repo lock to prevent concurrent vmn commands)

## CLI Commands

- `vmn init`: Initialize vmn tracking in a repository (once per repo)
- `vmn init-app <name>`: Initialize a new app for versioning (once per app)
- `vmn stamp -r <mode> <name>`: Stamp a new version (mode: major/minor/patch/hotfix)
- `vmn release -v <version> <name>`: Promote a prerelease to final release
- `vmn show <name>`: Display version information
- `vmn goto -v <version> <name>`: Checkout repository state at a specific version
- `vmn gen -t <template> -o <output> <name>`: Generate version file from Jinja2 template
- `vmn add <name>`: Add build metadata to existing version

Use `--dry-run` flag with `init-app` and `stamp` for testing.
