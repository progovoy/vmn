# vmn — versioning

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
