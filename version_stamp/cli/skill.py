#!/usr/bin/env python3
"""Print a vibe-coding skill block for AI agents."""

import os
import stat
import tempfile

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.utils import resolve_root_path

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

## Experiment tracking

Track code changes, metrics, and artifacts without a server:

```sh
# Run an experiment (captures code state + metrics + duration automatically)
vmn exp run <app_name> --note "description" -- <your command>

# Your script writes metrics to $VMN_METRICS_FILE as key=value lines
# vmn ingests them automatically when the run finishes.

# Manual experiment (no command to run)
vmn exp create <app_name> --metrics loss=0.34 acc=0.91 --note "manual run"

# List experiments sorted by a metric
vmn exp list <app_name> --sort loss --top 5

# Compare two experiments (shows metric delta + code diff)
vmn exp diff <app_name>

# Restore the most recent experiment's code state
vmn exp restore <app_name> --latest
# For the best run instead: find it with `exp list --sort <metric>`, then
# vmn exp restore <app_name> -v <version>
```

## Snapshots (uncommitted work)

Save and restore work-in-progress without committing:

```sh
vmn snapshot create <app_name> --note "WIP: refactoring auth"
vmn snapshot list <app_name>
vmn snapshot restore <app_name> --latest
vmn snapshot diff <app_name>  # compare snapshot to current state
```

## Parallel work with islands

For working on multiple features simultaneously (especially useful when multiple AI agents run in parallel):

```sh
# Create an isolated worktree island
vmn worktrees create <app_name> --island-name <feature-name>

# Read island.json in the created directory to understand the layout:
# - main_repo.path: where to make changes
# - deps: read-only dependency checkouts at pinned hashes

# List active islands
vmn worktrees list

# Clean up when done
vmn worktrees remove <feature-name>
```

Use `--no-stamp` for islands where you don't want version creation (CI, testing, review).

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
"""


METHODOLOGY_TEXT = r"""## Development gold rules

### Testability by design
- All I/O objects must be created as interfaces/abstractions in the outermost layer (e.g., `main.py`), then injected into the classes that use them.
- **I/O means anything non-deterministic or side-effectful**: DB connections, HTTP clients, file handles, queues, external services, `time.sleep`, `time.time`, `datetime.now`, random number generators, environment variables, stdin/stdout. If it touches the outside world or the clock — it's an interface.
- This makes the entire codebase testable with unit tests only — no integration tests, no mocks of concrete classes, no test containers needed for fast feedback. Tests stay fast (milliseconds) because no real I/O ever runs.
- If code is not in this shape, do small incremental refactors until all I/O is injected from the boundary. Extract the interface, push the concrete implementation to the entry point.

### TDD (strict)
1. **RED** — Write the test first. It must fail for the right reason.
2. **Implement** — Write the minimum code to make it pass.
3. **GREEN** — Tests pass. Do not modify the test to force green.
- Never write implementation before its test exists.
- Never change test logic without explicit approval from the developer.

### Boy Scout rule
- If you see any refactor opportunity or simplification — even if not part of the current task — do it.
- Leave the code cleaner than you found it, every time.

### Parallel worktree workflow
- Always use `vmn worktrees create` to spawn clean isolated worktrees for feature work.
- Local worktrees are fine — no need to push worktree branches to remote.
- Run all unit tests before merging a worktree back to master or any branch.
- Run `/simplify` at the end to review each feature for reuse, simplification, and efficiency.

### Worktree hygiene
- **Before removing**: verify all work is ported to the target branch. Check `git diff` and `git log` between the worktree branch and the merge target — nothing should be lost.
- **After merging**: immediately remove the worktree (`vmn worktrees remove <name>`). Don't let stale worktrees accumulate.
- **On session start**: run `vmn worktrees list` and clean up any stale islands left from previous sessions that are no longer relevant.
- **Never leave orphaned branches**: removing a worktree should also delete its local branch. If it doesn't, clean it manually (`git branch -D island/<name>/*`).

### Communication
- Always interview the developer before starting a task to make sure requirements are clear.
- Push back if something seems wrong, over-engineered, or under-specified.
"""


CLAUDE_DESCRIPTION = (
    "Use when stamping versions, tracking experiments, taking snapshots, or "
    "working with worktree islands via the vmn CLI in this repo."
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


def _skill_body(methodology=False):
    text = VMN_TEXT.strip()
    if methodology:
        text = f"{text}\n\n{METHODOLOGY_TEXT.strip()}"
    return text


def print_skill(methodology=False):
    """Print the vibe-coding skill block to stdout.

    Prints the vmn usage block. When ``methodology`` is set, also appends the
    opinionated development gold rules (TDD, worktree workflow, communication).
    """
    print(_skill_body(methodology))
    return 0


def _atomic_write(path, content):
    """Replace ``path`` only after its complete new content is on disk."""
    parent = os.path.dirname(path) or os.curdir
    os.makedirs(parent, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(
        dir=parent,
        prefix=f".{os.path.basename(path)}.",
    )
    try:
        with os.fdopen(fd, "w") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        if os.path.exists(path):
            mode = stat.S_IMODE(os.stat(path).st_mode)
            os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def _install_claude(path, methodology, force):
    if os.path.exists(path) and not force:
        VMN_LOGGER.error(
            f"{path} already exists — use --force to overwrite it."
        )
        return 1
    content = (
        "---\n"
        "name: vmn\n"
        f"description: {CLAUDE_DESCRIPTION}\n"
        "---\n\n"
        f"{_skill_body(methodology)}\n"
    )
    _atomic_write(path, content)
    VMN_LOGGER.info(f"Wrote vmn Agent Skill to {path}")
    return 0


def _install_block(path, methodology):
    block = f"{BEGIN_MARKER}\n{_skill_body(methodology)}\n{END_MARKER}"
    existing = ""
    if os.path.exists(path):
        with open(path) as f:
            existing = f.read()

    begin_count = existing.count(BEGIN_MARKER)
    end_count = existing.count(END_MARKER)
    if (begin_count, end_count) not in ((0, 0), (1, 1)):
        VMN_LOGGER.error(
            f"Refusing to update {path}: malformed vmn skill markers."
        )
        return 1

    if begin_count:
        start = existing.index(BEGIN_MARKER)
        end_start = existing.index(END_MARKER)
        if end_start < start:
            VMN_LOGGER.error(
                f"Refusing to update {path}: malformed vmn skill marker order."
            )
            return 1
        end = end_start + len(END_MARKER)
        new = existing[:start] + block + existing[end:]
        verb = "Updated"
    elif existing.strip():
        new = f"{existing.rstrip()}\n\n{block}"
        verb = "Appended"
    else:
        new = block
        verb = "Wrote"

    new = new.rstrip("\n") + "\n"
    _atomic_write(path, new)
    VMN_LOGGER.info(f"{verb} vmn skill block in {path}")
    return 0


def install_skill(target, methodology=False, force=False, root=None):
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
            return _install_claude(path, methodology, force)
        return _install_block(path, methodology)
    except RuntimeError:
        VMN_LOGGER.error(
            "Cannot install vmn skill from an unmanaged directory."
        )
    except (KeyError, OSError) as exc:
        VMN_LOGGER.error(f"Failed to install vmn skill: {exc}")
    return 1
