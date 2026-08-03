# The vmn AI agent integration

`vmn ai` groups all AI-agent-related commands: a factual CLI skill block and
composable methodology rules.

```sh
# Skill — vmn CLI reference for agents
vmn ai skill --install                  # .claude/skills/vmn/SKILL.md (default)
vmn ai skill --install --target cursor  # .cursorrules
vmn ai skill --install --target agents  # AGENTS.md
vmn ai skill --install --methodology    # + all methodology rules
vmn ai skill                            # print instead of writing

# Methodology — opinionated development rules (pick what you want)
vmn ai methodology --install            # all rules
vmn ai methodology --tdd --install      # just TDD
vmn ai methodology --tdd --boyscout --install  # combine freely
vmn ai methodology                      # print instead of writing
```

Available methodology flags: `--tdd`, `--testability`, `--boyscout`,
`--worktrees`, `--communication`. No flags = all rules.

`--install` resolves the managed repository root even when run from a nested
directory. The `claude` target writes a self-contained Agent Skill and refuses
to clobber an existing one without `--force`. The `cursor` and `agents` targets
upsert a marker-delimited block, preserving whatever else is in the file.

`vmn skill` remains as a backwards-compatible alias for `vmn ai skill`.

> The text below is the output of `vmn ai skill --methodology`, reproduced for
> browsing. **It is generated** — the source of truth is
> [`version_stamp/cli/skill.py`](../version_stamp/cli/skill.py). Regenerate with
> `vmn ai skill --methodology` rather than editing this file by hand.
>
> Everything from **Development gold rules** onward is the opt-in
> methodology section; plain `vmn ai skill` stops before it.

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

## Development gold rules

> Follow these rules. If your CLAUDE.md or project instructions explicitly
> contradict a rule below, the project instruction wins.

### Testability by design
- Every non-deterministic or side-effectful dependency (network, disk, clock, randomness, environment) must be an injected interface, created at the application boundary and passed inward.
- New code must be testable with fast, in-process tests — no containers, no real I/O, no sleeps. If you can't test it without a running service, the design is wrong.
- When touching existing code that violates this, extract the I/O behind an interface in a separate preparatory commit before adding new behavior.

### TDD (strict)
1. **RED** — Write the failing test first. It must fail for the right reason (not a syntax error or import failure).
2. **GREEN** — Write the minimum implementation to make it pass. Do not modify the test.
3. **REFACTOR** — Clean up implementation only, keeping tests green.

Rules:
- No implementation code exists without a test that demanded it.
- Never weaken, delete, or rewrite a test to make it pass — if the test seems wrong, stop and ask.
- Config-only changes, documentation, and pure refactors (where existing tests still cover behavior) are exempt.

### Boy Scout rule
- When you're already modifying a function or file, improve clarity of what you touch — rename an unclear variable, simplify a conditional, extract a helper.
- Don't refactor code you're not otherwise changing. The improvement must be in the natural path of the current task, not a detour.
- If you spot a larger cleanup opportunity outside your current scope, note it to the developer rather than doing it silently.

### Parallel worktree workflow
- Use `vmn worktrees create` to spawn isolated islands for independent features or experiments.
- Never push island branches to remote — they are local-only.
- Run the full test suite in the island before merging back.
- Verify no work is lost (`git diff` and `git log` against merge target) before removing an island.
- Remove islands immediately after merging (`vmn worktrees remove <name>`). Run `vmn worktrees list` at session start and clean up stale ones.

### Communication
- If the task is ambiguous or has multiple valid interpretations, ask one clarifying question before starting — don't guess at requirements.
- If a request seems over-engineered for the problem, say so and propose the simpler alternative.
- If you're blocked or uncertain about a design choice with significant downstream impact, surface it rather than picking silently.
- Don't ask for confirmation on clear, low-risk, reversible actions — just do them.

### Minimal diffs
- Every commit does one thing. Don't mix refactoring with behavior changes.
- Don't add code that isn't exercised by the current task — no speculative helpers, unused parameters, or dead feature flags.
- Prefer deleting dead code over commenting it out. Version control is the archive.
- When a change touches many files, verify the diff contains no accidental formatting or whitespace noise.

### Error handling
- Handle errors at the level that can do something useful about them. Don't catch-and-rethrow, don't log-and-ignore.
- Fail fast and loud on programmer errors (wrong types, broken invariants). Only retry on transient external failures.
- Error messages must say what went wrong, what was expected, and (when possible) what the user should do. No naked stack traces to end users.
