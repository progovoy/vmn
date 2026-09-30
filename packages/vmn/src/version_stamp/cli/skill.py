#!/usr/bin/env python3
"""Print a vibe-coding skill block for AI agents."""

import os

from version_stamp.core.logging import VMN_LOGGER, init_stamp_logger
from version_stamp.core.utils import (
    MalformedBlockError,
    atomic_write,
    resolve_root_path,
    upsert_marked_block,
)

VMN_TEXT = r"""# vmn — versioning

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

Experiment tracking: install vmn-exp and run `vmn-exp skill`.
"""


CLAUDE_DESCRIPTION = (
    "Use when stamping versions or restoring multi-repo state "
    "via the vmn CLI in this repo."
)

# Where each --target writes. `claude` gets a real Agent Skill directory
# (``.claude/skills/<skill name>/SKILL.md``); the others are shared
# instruction files edited in place.
TARGET_PATHS = {
    "cursor": ".cursorrules",
    "agents": "AGENTS.md",
}

BEGIN_MARKER = "<!-- BEGIN vmn skill (managed by `vmn skill --install`) -->"
END_MARKER = "<!-- END vmn skill -->"


def print_skill(body=VMN_TEXT):
    """Print a skill block (vmn's by default) to stdout."""
    print(body.strip())
    return 0


def _write_creating_parent(path, content):
    os.makedirs(os.path.dirname(path) or os.curdir, exist_ok=True)
    atomic_write(path, content)


def _install_claude(path, force, name, description, body):
    if os.path.exists(path) and not force:
        VMN_LOGGER.error(f"{path} already exists — use --force to overwrite it.")
        return 1
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"{body}\n"
    )
    _write_creating_parent(path, content)
    VMN_LOGGER.info(f"Wrote {name} Agent Skill to {path}")
    return 0


def _install_block(path, name, body, markers):
    begin, end = markers
    block = f"{begin}\n{body}\n{end}"
    existing = ""
    if os.path.exists(path):
        with open(path) as f:
            existing = f.read()

    try:
        new, verb = upsert_marked_block(existing, begin, end, block)
    except MalformedBlockError as exc:
        VMN_LOGGER.error(f"Refusing to update {path}: malformed {name} skill {exc}.")
        return 1

    _write_creating_parent(path, new)
    VMN_LOGGER.info(f"{verb} {name} skill block in {path}")
    return 0


def _target_path(root, target, name):
    if target == "claude":
        return os.path.join(root, ".claude", "skills", name, "SKILL.md")
    return os.path.join(root, TARGET_PATHS[target])


def install_skill(
    target,
    force=False,
    root=None,
    *,
    name="vmn",
    description=CLAUDE_DESCRIPTION,
    body=VMN_TEXT,
    markers=(BEGIN_MARKER, END_MARKER),
):
    """Write a skill block to an AI tool's instruction file.

    ``claude`` creates a self-contained Agent Skill at
    ``.claude/skills/<name>/SKILL.md`` (refuses to clobber unless ``force``).
    ``cursor``/``agents`` upsert the block between *markers* into the shared
    instruction file, preserving any surrounding content. vmn-exp installs
    its own skill through the same machinery with its own name and markers.
    """
    body = body.strip()
    try:
        if root is None:
            root = resolve_root_path()
        else:
            root = os.path.realpath(os.path.expanduser(root))
            if not os.path.isdir(root):
                VMN_LOGGER.error(
                    f"Cannot install {name} skill: {root} is not a directory."
                )
                return 1

        path = _target_path(root, target, name)
        if target == "claude":
            return _install_claude(path, force, name, description, body)
        return _install_block(path, name, body, markers)
    except RuntimeError:
        VMN_LOGGER.error(f"Cannot install {name} skill from an unmanaged directory.")
    except (KeyError, OSError) as exc:
        VMN_LOGGER.error(f"Failed to install {name} skill: {exc}")
    return 1


def run_skill(install, target="claude", force=False, **skill):
    """Exit code of a ``skill`` command: print the block, or install it.

    *skill* (``name``/``description``/``body``/``markers``) defaults to vmn's;
    ``vmn-exp skill`` passes its own through ``version_stamp.api``.
    """
    init_stamp_logger()
    if install:
        return install_skill(target, force, **skill)
    return print_skill(skill.get("body", VMN_TEXT))
