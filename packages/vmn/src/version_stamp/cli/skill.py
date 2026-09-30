#!/usr/bin/env python3
"""Print a vibe-coding skill block for AI agents."""

import os

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.utils import (
    MalformedBlockError,
    atomic_write,
    resolve_root_path,
    upsert_marked_block,
)

VMN_TEXT = r"""# vmn — versioning & experiment tracking

## Versioning workflow

This project uses `vmn` for semantic versioning via git tags.

### Stamping a new version
```sh
vmn stamp -r <mode> <app_name>   # mode: major | minor | patch | hotfix
vmn stamp -r patch --pr rc <app_name>  # prerelease
vmn release <app_name>                  # promote prerelease to final
```

- `vmn stamp` auto-initializes the repo and app on first run — no separate init step.
- Use `--dry-run` to preview without committing.
- Use `--pull` in CI or shared repos to auto-retry on tag conflicts.
- Use `--orm` (optional release mode) to stamp only if no prerelease already exists at the target version — safe for CI pipelines that re-run on the same commit.
- If `conventional_commits` is enabled in config, `-r` is optional — vmn infers the mode from commit messages (`fix:` → patch, `feat:` → minor, `BREAKING CHANGE` → major).

### Checking the current version
```sh
vmn show <app_name>              # current version string
vmn show <app_name> --verbose    # full YAML metadata
vmn show <app_name> --conf       # show effective config
```

### Restoring state
```sh
vmn goto -v <version> <app_name>  # checkout repo + all deps to exact state
```

### Build metadata
```sh
vmn add -v <version> --bm <key>=<value> <app_name>  # attach metadata to a version
vmn add -v <version> --bm <key>=<value> --vmp <path> --vmu <url> <app_name>
```

Build metadata (the `+...` suffix) is append-only and does not change the version. Use it to record build hashes, artifact URLs, or CI run IDs after a stamp.

### File generation from templates
```sh
vmn gen -t <template.j2> -o <output_file> <app_name>
```

Renders a Jinja2 template with the current version context. Useful for generating version headers, build manifests, or embedding version info into non-standard file formats.

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
Full guide: docs/ai-fleet-tracking.md

### Saving uncommitted work

Every experiment captures the working tree (tracked edits and untracked files),
so `vmn-exp create` doubles as a work-in-progress save point:

```sh
vmn-exp create <app_name> --note "WIP: refactoring auth"
vmn-exp restore <app_name> --latest
vmn-exp export <app_name> -o wip.tar.gz   # portable tarball of the captured state
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

## Worktree islands (app + dependencies side by side)

```sh
vmn wt create <app_name> --island-name <name>   # worktrees of the app and every dep
vmn wt create <app_name> --island-name <name> --carry-changes   # also copy uncommitted work
vmn wt pull                                     # rebase private branches onto their sources
vmn wt freeze <app_name>                        # pin deps to the real branches they are on
vmn wt list
vmn wt remove <name>
```

- Read `island.json` in the island directory: `main_repo.path` and each dep's `path`, private `branch`, and `source_branch`.
- Island checkouts start on private `island/<name>/<source>` branches. They cannot be pushed and `vmn stamp` refuses to run on them.
- Branches you create inside an island are normal branches: publish one with `git push -u origin <branch>`.
- To share: check out real branches in the repos you changed, push them, run `vmn wt freeze <app_name>` in the app, then commit and push the conf file it wrote.
- `--from-version <version>` builds an island at a released state instead.

## Key rules

1. **Never edit .vmn/ files directly** — vmn manages them.
2. **Commit before stamping** — `vmn stamp` requires a clean working tree.
3. **App names cannot contain `-`** — use `_` or `/` (for root apps).
4. **Root app format**: `root_app/service_name` — the root version auto-increments.
5. **Tags are the source of truth** — versions survive vmn uninstall.

## Configuration

Edit config interactively: `vmn config <app_name>`
Or non-interactively: `vmn config gen <app_name>`

Key config options:
- `conventional_commits: true` — auto-detect release mode from commits
- `version_backends` — auto-embed version into package.json, Cargo.toml, pyproject.toml
- `changelog.path` — auto-generate CHANGELOG.md on stamp
- `deps` — track external repo dependencies for multi-repo state recovery

### Branch-specific config

Integration branches can override the default config to pin deps to different branches:

```sh
vmn config gen <app_name> --branch   # create branch conf for current branch
vmn config <app_name> --branch       # edit branch conf interactively
```

The canonical path mirrors the branch name (slashes become directories):
- Branch `build_checker/chore/test_rdkafka` → `.vmn/<app>/branch_conf/build_checker/chore/test_rdkafka/conf.yml`

A branch conf should be identical to master's `conf.yml` except for added `branch:` lines on deps:
```yaml
deps:
  Infra:
    remote: ssh://git@gitlab.example.com/infra/Infra.git
    vcs_type: git
    branch: rdkafka/use_external_lz4_by_default
```

vmn resolves branch confs automatically at stamp time — no extra flags needed.
"""


CLAUDE_DESCRIPTION = (
    "Use when stamping versions, tracking experiments, or "
    "restoring multi-repo state via the vmn CLI in this repo."
)

# Where each --target writes. `claude` gets a real Agent Skill directory;
# the others are shared instruction files edited in place.
TARGET_PATHS = {
    "claude": os.path.join(".claude", "skills", "vmn", "SKILL.md"),
    "cursor": ".cursorrules",
    "agents": "AGENTS.md",
}

BEGIN_MARKER = "<!-- BEGIN vmn skill (managed by `vmn skill --install`) -->"
END_MARKER = "<!-- END vmn skill -->"


def _skill_body():
    return VMN_TEXT.strip()


def print_skill():
    """Print the vmn skill block to stdout."""
    print(_skill_body())
    return 0


def _write_creating_parent(path, content):
    os.makedirs(os.path.dirname(path) or os.curdir, exist_ok=True)
    atomic_write(path, content)


def _install_claude(path, force):
    if os.path.exists(path) and not force:
        VMN_LOGGER.error(f"{path} already exists — use --force to overwrite it.")
        return 1
    content = (
        "---\n"
        "name: vmn\n"
        f"description: {CLAUDE_DESCRIPTION}\n"
        "---\n\n"
        f"{_skill_body()}\n"
    )
    _write_creating_parent(path, content)
    VMN_LOGGER.info(f"Wrote vmn Agent Skill to {path}")
    return 0


def _install_block(path):
    block = f"{BEGIN_MARKER}\n{_skill_body()}\n{END_MARKER}"
    existing = ""
    if os.path.exists(path):
        with open(path) as f:
            existing = f.read()

    try:
        new, verb = upsert_marked_block(existing, BEGIN_MARKER, END_MARKER, block)
    except MalformedBlockError as exc:
        VMN_LOGGER.error(f"Refusing to update {path}: malformed vmn skill {exc}.")
        return 1

    _write_creating_parent(path, new)
    VMN_LOGGER.info(f"{verb} vmn skill block in {path}")
    return 0


def install_skill(target, force=False, root=None):
    """Write the skill block to an AI tool's instruction file.

    ``claude`` creates a self-contained Agent Skill at
    ``.claude/skills/vmn/SKILL.md`` (refuses to clobber unless ``force``).
    ``cursor``/``agents`` upsert a marker-delimited block into the shared
    instruction file, preserving any surrounding content.
    """
    try:
        if root is None:
            root = resolve_root_path()
        else:
            root = os.path.realpath(os.path.expanduser(root))
            if not os.path.isdir(root):
                VMN_LOGGER.error(
                    f"Cannot install vmn skill: {root} is not a directory."
                )
                return 1

        path = os.path.join(root, TARGET_PATHS[target])
        if target == "claude":
            return _install_claude(path, force)
        return _install_block(path)
    except RuntimeError:
        VMN_LOGGER.error("Cannot install vmn skill from an unmanaged directory.")
    except (KeyError, OSError) as exc:
        VMN_LOGGER.error(f"Failed to install vmn skill: {exc}")
    return 1
