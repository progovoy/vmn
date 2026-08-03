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

Always create islands from the current HEAD — don't switch branches or specify a different base before running `vmn worktrees create`.

Island branches are named `island/<island-name>/<original-branch>`. When stamping inside an island, vmn resolves a branch conf matching this full branch name — create one with `vmn config gen <app> --branch` if you need to pin deps to different branches in the island.

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


METHODOLOGY_HEADER = r"""## Development gold rules

> Follow these rules. If your CLAUDE.md or project instructions explicitly
> contradict a rule below, the project instruction wins.
"""

METHODOLOGY_SECTIONS = {
    "testability": r"""### Testability by design
- Every non-deterministic or side-effectful dependency (network, disk, clock, randomness, environment) must be an injected interface, created at the application boundary and passed inward.
- New code must be testable with fast, in-process tests — no containers, no real I/O, no sleeps. If you can't test it without a running service, the design is wrong.
- When touching existing code that violates this, extract the I/O behind an interface in a separate preparatory commit before adding new behavior.
""",
    "tdd": r"""### TDD (strict)
1. **RED** — Write the failing test first. It must fail for the right reason (not a syntax error or import failure).
2. **GREEN** — Write the minimum implementation to make it pass. Do not modify the test.
3. **REFACTOR** — Clean up implementation only, keeping tests green.

Rules:
- No implementation code exists without a test that demanded it.
- Never weaken, delete, or rewrite a test to make it pass — if the test seems wrong, stop and ask.
- Config-only changes, documentation, and pure refactors (where existing tests still cover behavior) are exempt.
""",
    "boyscout": r"""### Boy Scout rule
- When you're already modifying a function or file, improve clarity of what you touch — rename an unclear variable, simplify a conditional, extract a helper.
- Don't refactor code you're not otherwise changing. The improvement must be in the natural path of the current task, not a detour.
- If you spot a larger cleanup opportunity outside your current scope, spawn a subagent in a separate worktree to handle it — don't block or pollute the current task's diff.
""",
    "worktrees": r"""### Parallel worktree workflow
- Use `vmn worktrees create` to spawn isolated islands for independent features or experiments.
- Never push island branches to remote — they are local-only.
- Run the full test suite in the island before merging back.
- Run `/simplify` on the finished change before merging (Claude Code) — it catches reuse opportunities and unnecessary complexity while the context is fresh.
- A task is not done until it is merged and pushed. Before merging, ask the developer which branch to merge into.
- Verify no work is lost (`git diff` and `git log` against merge target) before removing an island.
- Remove islands immediately after merging (`vmn worktrees remove <name>`). Run `vmn worktrees list` at session start and clean up stale ones.
""",
    "communication": r"""### Communication
- If the task is ambiguous or has multiple valid interpretations, ask one clarifying question before starting — don't guess at requirements.
- If a request seems over-engineered for the problem, say so and propose the simpler alternative.
- If you're blocked or uncertain about a design choice with significant downstream impact, surface it rather than picking silently.
- Don't ask for confirmation on clear, low-risk, reversible actions — just do them.
""",
    "minimal_diffs": r"""### Minimal diffs
- Every commit does one thing. Don't mix refactoring with behavior changes.
- Don't add code that isn't exercised by the current task — no speculative helpers, unused parameters, or dead feature flags.
- Prefer deleting dead code over commenting it out. Version control is the archive.
- When a change touches many files, verify the diff contains no accidental formatting or whitespace noise.
""",
    "errors": r"""### Error handling
- Handle errors at the level that can do something useful about them. Don't catch-and-rethrow, don't log-and-ignore.
- Fail fast and loud on programmer errors (wrong types, broken invariants). Only retry on transient external failures.
- Error messages must say what went wrong, what was expected, and (when possible) what the user should do. No naked stack traces to end users.
""",
}

ALL_METHODOLOGY_KEYS = list(METHODOLOGY_SECTIONS.keys())


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


def _methodology_body(sections=None):
    """Build methodology text from selected section keys."""
    if sections is None:
        sections = ALL_METHODOLOGY_KEYS
    parts = [METHODOLOGY_SECTIONS[k].strip() for k in sections if k in METHODOLOGY_SECTIONS]
    if not parts:
        return ""
    return METHODOLOGY_HEADER.strip() + "\n\n" + "\n\n".join(parts)


def _skill_body(methodology=False, methodology_sections=None):
    text = VMN_TEXT.strip()
    if methodology:
        meth = _methodology_body(methodology_sections)
        if meth:
            text = f"{text}\n\n{meth}"
    return text


def print_skill(methodology=False, methodology_sections=None):
    """Print the vibe-coding skill block to stdout."""
    print(_skill_body(methodology, methodology_sections))
    return 0


def print_methodology(sections=None):
    """Print only the methodology rules to stdout."""
    body = _methodology_body(sections)
    if body:
        print(body)
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


def _content_body(methodology, methodology_sections, methodology_only):
    if methodology_only:
        return _methodology_body(methodology_sections)
    return _skill_body(methodology, methodology_sections)


def _install_claude(path, methodology, force, methodology_sections=None,
                    methodology_only=False):
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
        f"{_content_body(methodology, methodology_sections, methodology_only)}\n"
    )
    _atomic_write(path, content)
    VMN_LOGGER.info(f"Wrote vmn Agent Skill to {path}")
    return 0


def _install_block(path, methodology, methodology_sections=None,
                   methodology_only=False):
    body = _content_body(methodology, methodology_sections, methodology_only)
    block = f"{BEGIN_MARKER}\n{body}\n{END_MARKER}"
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


def install_skill(target, methodology=False, force=False, root=None,
                  methodology_sections=None, methodology_only=False):
    """Write the skill block to an AI tool's instruction file.

    ``claude`` creates a self-contained Agent Skill at
    ``.claude/skills/vmn/SKILL.md`` (refuses to clobber unless ``force``).
    ``cursor``/``agents`` upsert a marker-delimited block into the shared
    instruction file, preserving any surrounding content.

    When ``methodology_only`` is set, only the methodology rules are written
    (no vmn CLI reference). Used by ``vmn ai methodology --install``.
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
            return _install_claude(path, methodology, force,
                                   methodology_sections, methodology_only)
        return _install_block(path, methodology,
                              methodology_sections, methodology_only)
    except RuntimeError:
        VMN_LOGGER.error(
            "Cannot install vmn skill from an unmanaged directory."
        )
    except (KeyError, OSError) as exc:
        VMN_LOGGER.error(f"Failed to install vmn skill: {exc}")
    return 1
