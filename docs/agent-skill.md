# The vmn agent skill

`vmn skill` prints a block of vmn usage instructions written for AI coding
agents, so an agent working in your repo knows how to stamp, snapshot, and use
islands correctly instead of guessing.

```sh
vmn skill --install                     # .claude/skills/vmn/SKILL.md (default)
vmn skill --install --target cursor     # .cursorrules
vmn skill --install --target agents     # AGENTS.md
vmn skill --install --methodology       # + the gold rules section below
vmn skill --install --force             # overwrite an existing Claude SKILL.md
vmn skill                               # print instead of writing
```

`--install` resolves the managed repository root even when run from a nested
directory. The `claude` target writes a self-contained Agent Skill and refuses
to clobber an existing one without `--force`. The `cursor` and `agents` targets
upsert a marker-delimited block, preserving whatever else is in the file.

> The text below is the output of `vmn skill --methodology`, reproduced for
> browsing. **It is generated** — the source of truth is
> [`version_stamp/cli/skill.py`](../version_stamp/cli/skill.py). Regenerate with
> `vmn skill --methodology` rather than editing this file by hand.
>
> Everything from **Development gold rules** onward is the opt-in
> `--methodology` section; plain `vmn skill` stops before it.

---

# vmn — versioning & experiment tracking

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

## Development gold rules

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
