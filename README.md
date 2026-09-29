<h1 align="center">vmn</h1>

<p align="center"><strong>git checkout for releases that span many repos.</strong></p>

<p align="center">
  Record a release once. Put the app and every repo it depends on back to exactly that state with one command.<br>
  No server. No database. Any language.
</p>

<p align="center">
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/v/vmn?logo=pypi&logoColor=white&label=PyPI" alt="PyPI version"></a>
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/pyversions/vmn?logo=python&logoColor=white" alt="Supported Python versions"></a>
  <a href="https://github.com/progovoy/vmn/blob/master/LICENSE.txt"><img src="https://img.shields.io/github/license/progovoy/vmn" alt="MIT license"></a>
</p>


<p align="center"><img src="demo/vmn-goto.gif" alt="vmn stamp, then vmn goto restoring the app and both dependency repos" width="820"></p>

Production broke after last Tuesday's 2.1.0 deploy. Your product is four repos.
Which commit of each one actually shipped?

Without vmn, that is an afternoon of CI logs and container tags. With vmn:

```sh
vmn goto -v 2.1.0 my_platform   # every repo back at the commit that shipped
```

Try it in any Git repository:

```sh
pipx install vmn

vmn stamp -r patch my_app       # 0.0.1
vmn goto -v 0.0.1 my_app        # restore the app and every configured dependency
```

vmn stores release metadata as readable YAML in annotated Git tags. Each tag
records the application revision, dependency revisions, previous version, and
release context. There is no vmn server and no external metadata database.

> Developed continuously since 2019, vmn is used in daily production workflows
> by teams at large companies managing multi-repository products. vmn versions
> its own releases. The repository contains more than 400 tests, including
> Docker-backed multi-repository, recovery, and compatibility scenarios.

If vmn saves you an afternoon, a ⭐ helps other teams find it.

[Quick start](#quick-start) · [Why vmn](#why-vmn) ·
[Multi-repository recovery](#multi-repository-recovery) ·
[Operations](#production-operation) · [Commands](#command-map) ·
[Documentation](#documentation)

## Why vmn

| Requirement | What vmn provides |
| --- | --- |
| Recover a recorded multi-repository source state | `vmn goto` restores the application and its configured dependencies to their recorded Git revisions. |
| Keep release data inspectable | Annotated tags contain readable YAML and use the namespaced form `<app>_<version>`. |
| Version mixed technology stacks | vmn operates on Git repositories, not a language-specific package manager or build system. |
| Release services independently | Root apps group independently versioned services under a monotonic composition version. |
| Work without a hosted control plane | A standard Git remote is enough; internal and air-gapped Git servers are supported. |
| Adopt without replacing build tooling | Version backends update npm, Cargo, Poetry, PEP 621, Jinja2, or regex-selected files. |

vmn treats a version as a handle to recorded source state, not only as a
string. The same model supports releases, working snapshots, and measured runs:

| State | Command | Captures |
| --- | --- | --- |
| Release | `vmn stamp` → `vmn goto` | Committed application and dependency revisions |
| Working | `vmn snapshot` | Release state plus local commits, tracked changes, and untracked files |
| Measured | `vmn-exp` → `vmn goto` | Working state plus the run's metrics, parameters, artifacts, and history |

> **Scope:** vmn restores recorded source revisions. It does not rebuild
> artifacts, capture toolchains or runtime infrastructure, sign tags, or deploy
> software. Keep those responsibilities in your build, signing, and deployment
> pipeline.

## Quick start

### Requirements

- Python 3.8 or newer
- Git 2.10 or newer; Git 2.17+ is recommended
- A Git repository with at least one commit and a writable remote

Install vmn as an isolated command-line tool:

```sh
pipx install vmn
# Alternative: uv tool install vmn

vmn --completion-install   # bash/zsh/fish/tcsh; auto-detects shell
```

vmn ships as three packages; install only what you need:

| Package | What you get |
|---|---|
| `vmn` | Versioning: `stamp`, `release`, `show`, `goto`, `snapshot`, … |
| `vmn-exp` | Experiment tracking on top of vmn: the `vmn-exp` CLI, model registry, and the dashboard (`vmn-exp[ui]`) |
| `vmn-exp-sdk` | Just the metrics writer for training jobs: `start_run()`, no git needed |

`pip install "vmn-exp[ui]"` brings all three. Coming from vmn 0.10 or earlier,
`vmn exp`/`model`/`ui` are now `vmn-exp …`; see
[docs/packaging.md](https://github.com/progovoy/vmn/blob/master/docs/packaging.md#installing).

Inside any Git repository:

```sh
vmn stamp -r patch my_app       # 0.0.1; initializes on first use
vmn show my_app                 # 0.0.1

# After committing the next change:
vmn stamp -r minor my_app       # 0.1.0

# After committing another change:
vmn stamp -r patch --pr rc my_app  # 0.1.1-rc.1
vmn release my_app              # 0.1.1
```

A successful stamp creates a version commit, creates annotated tags, and
pushes the branch and tags. Use `--dry-run` to inspect the operation first.
Repeated stamping of an already-versioned state is idempotent.

Inspect the source of truth directly:

```sh
git tag --list 'my_app_*'
git cat-file -p my_app_0.1.0
vmn show --verbose my_app
```

No separate `vmn init` is required. Explicit `init` and `init-app` commands
remain available for migrations and non-default starting versions.

## Multi-repository recovery

Your product spans 4 repos. Production broke after the 2.1.0 deploy last
Tuesday. You need the exact source state — not just one repo, all of them — to
reproduce and fix the bug. One command:

```sh
vmn goto -v 2.1.0 my_platform
```

Every configured dependency is restored to its recorded revision, cloning any
that are missing locally. No container archaeology, no CI log diving.

### Setup

Declare sibling dependency repositories in `.vmn/my_app/conf.yml`:

```yaml
conf:
  deps:
    ../:
      lib_core:
        vcs_type: git
      service_api:
        vcs_type: git
```

Stamping records the exact revision and remote for every dependency:

```sh
vmn stamp -r minor my_app

# Later, from any other revision:
vmn goto -v 1.4.0 my_app
```

`goto` restores all recorded repositories and can clone a missing dependency.
Use `--pull` when the requested refs are not available locally, or
`--deps-only` to leave the application repository unchanged.

To work on the application and its dependencies side by side without moving
your main checkout, `vmn wt` (alias of `vmn worktrees`) builds an island: git
worktrees for the application and every dependency, laid out like the originals,
next to an `island.json` manifest. Each checkout starts on a private
`island/<name>/<branch>` branch that follows its source branch but cannot be
pushed, and stamping is refused on it.

```sh
vmn wt create my_app --island-name feat   # from the current commits
vmn wt create my_app --island-name feat --carry-changes   # ...plus uncommitted work
vmn wt pull                               # rebase onto the source branches
vmn wt freeze my_app                      # pin deps to the branches they are on
vmn wt remove feat
```

To share the work, check out a real branch in each repo you changed
(`git checkout -b feature/x`, then `git push -u origin feature/x`) and run
`vmn wt freeze` in the application. It records those dependency branches in
the current branch's conf, so a colleague who checks out `feature/x` and runs
`vmn wt create` gets the same dependency state. `-fv 2.1.0` builds an island at
a recorded version instead.

Do not embed credentials in Git remote URLs: dependency remotes are part of
release metadata. Use SSH, a Git credential helper, or vmn's per-command push
credentials instead.

## Release models

vmn supports SemVer-based release and prerelease workflows plus explicit vmn
extensions:

```text
1.6.0                         release
1.6.0-rc.23                   prerelease
1.6.7.4                       optional fourth hotfix segment
1.6.0-rc.23+build01           build metadata
1.6.0-dev.a1b2c3d.e4f5g6h     recorded working state (a snapshot or experiment run)
```

Enable Conventional Commits, changelog generation, GitHub Releases, branch
policy, and version embedding in the app configuration:

```yaml
conf:
  conventional_commits: true
  default_release_mode: optional
  changelog:
    path: CHANGELOG.md
  github_release:
    draft: true
  policies:
    whitelist_release_branches: [main]
  version_backends:
    pep621:
      path: pyproject.toml
```

With `conventional_commits` enabled, `fix:` selects patch, `feat:` selects
minor, and a `type!:` header selects major. GitHub Release creation requires
the `gh` CLI and `GITHUB_TOKEN` or `GH_TOKEN`; it is best-effort and warns
rather than failing an otherwise successful stamp.

For independently deployed services, use a root app:

```sh
vmn stamp -r patch platform/auth       # auth 0.0.1; platform 1
vmn stamp -r minor platform/billing    # billing 0.1.0; platform 2
vmn show --root platform               # 2
```

### Branch-specific configuration

Integration branches can override dep pinning without touching the main config:

```sh
vmn config gen my_app --branch                  # create branch conf for current branch
vmn config gen my_app --branch --sync-dep-branches  # auto-pin deps to their checked-out branches
vmn config my_app --branch                      # edit interactively
```

Branch confs are resolved automatically at stamp time. The canonical layout is
`.vmn/<app>/branch_conf/<branch>/conf.yml` (branch slashes become directories).

## Production operation

vmn is designed for release automation where failure must be visible and
recoverable:

- `--dry-run` previews a stamp without committing or tagging.
- Dirty, detached, outgoing, and dependency states are checked before release.
- A per-repository lock prevents concurrent local vmn operations.
- Release-branch allowlists restrict stable stamps to configured branches.
- `--pull` fetches remote state and retries version conflicts.
- vmn rolls back newly created local release state when publication fails.
- Release metadata remains readable with standard Git and YAML tooling.
- No internet access is required when an internal or local Git remote is used.

For GitHub Actions, use the official [vmn-action](https://github.com/marketplace/actions/automated-versioning):

```yaml
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0

  - id: vmn
    uses: progovoy/vmn-action@latest
    with:
      app-name: my_app
      do-stamp: true
      stamp-mode: patch
    env:
      GITHUB_TOKEN: ${{ github.token }}

  - run: echo "Stamped ${{ steps.vmn.outputs.verstr }}"
```

For other CI systems, fetch complete history and tags, serialize stamps for the
same app, and provide write access to the remote:

```sh
pip install vmn
vmn stamp --pull -r patch my_app
```

Start an established migration with `--dry-run`; then add branch policy before
enabling automatic stamps.

## Working-state snapshots

Between releases, capture and restore your exact working state — uncommitted
changes, local commits, and untracked files, across every dependency — as a
named version, without committing:

```sh
vmn snapshot create my_app --note "parser refactor"   # prints 1.2.0-dev.a1b2c3d.e4f5g6h
vmn snapshot restore my_app --latest                  # your current work is auto-saved first
```

<details>
<summary><strong>Snapshot actions</strong></summary>

`vmn snapshot [create|list|show|note|delete|restore|export|diff] <app>`
(`create` is the default). Refs are a full verstr, a unique prefix, `@N` or
`--latest`.

```sh
vmn snapshot list my_app --last 5
vmn snapshot diff my_app -v @2                   # vs your working tree; --to <ref|version>
vmn snapshot export my_app -v @2                 # -> ./<verstr>.tar.gz, or -o <dir>
vmn snapshot restore my_app -v @2                # refuses to drop oversized untracked files without --force
vmn goto -v 1.2.0-dev.a1b2c3d.e4f5g6h my_app     # also works (with vmn-exp installed)
```

Snapshots are thin records in `.vmn/<app>/snapshots/` that share code objects
with experiment runs. With `vmn-exp` installed, `--store <uri>` (or
`VMN_EXPERIMENT_STORE`, or conf `experiment.storage.uri`) keeps them in a
team store; `--local` overrides it.

</details>

See [docs/snapshots.md](https://github.com/progovoy/vmn/blob/master/docs/snapshots.md).

## Experiments: recorded working state

Between releases, `vmn-exp` records your exact working state — uncommitted
changes, local commits, and untracked files — as a dev version, with the
run's metrics alongside:

```sh
vmn-exp create my_app --note "parser refactor"
vmn goto -v <dev-version> my_app      # or: vmn-exp restore my_app --latest
```

This extends the same state-recovery model as `goto` to uncommitted work; see [docs/experiments.md](https://github.com/progovoy/vmn/blob/master/docs/experiments.md).
New to it? The [client guide](https://github.com/progovoy/vmn/blob/master/docs/client-guide.md) walks one project through submit, log, watch, compare, reproduce, resume/rewind/fork and models.
Hyperparameter sweeps run server-less across many agents with `vmn-exp sweep`; see [docs/sweeps.md](https://github.com/progovoy/vmn/blob/master/docs/sweeps.md).
Nodes with no route to the store record with `VMN_EXP_OFFLINE=1` and upload
later with `vmn-exp push my_app`; see [offline recording and push](https://github.com/progovoy/vmn/blob/master/docs/experiments.md#offline-recording-and-push).
Python workloads can log in-process instead of shelling out — `from
vmn_exp.sdk import start_run`, plus `autolog()` for scikit-learn
hyperparameters and scores, and a query language for filtering runs on metrics
and params; see
[docs/sdk.md](https://github.com/progovoy/vmn/blob/master/docs/sdk.md).
Five runnable scripts — a minimal run, a training loop, a nested sweep, queries
and autologging — live in
[examples/](https://github.com/progovoy/vmn/blob/master/examples/README.md).

Install `vmn-exp[ui]` for a local web dashboard with stamp-tree views and
run comparison.

## AI agent integration

`vmn skill` gives AI coding agents the context they need to use vmn correctly:

```sh
vmn skill                               # print the skill block
vmn skill --install                     # .claude/skills/vmn/SKILL.md
vmn skill --install --target cursor     # .cursorrules
vmn skill --install --target agents     # AGENTS.md
```

Re-running `--install` updates vmn's section and leaves the rest of your
instructions untouched.

Agents that run sweeps and want the `vmn-exp ui` leaderboard's fleet columns
(total / waiting / running / done / failed) to track them: see
[docs/ai-fleet-tracking.md](docs/ai-fleet-tracking.md) for which call moves each column.

Optional, opinionated development rules for agents (TDD, testability,
worktrees, minimal diffs, ...) live in
[docs/agent-methodology.md](docs/agent-methodology.md) — paste the sections
you want into your `CLAUDE.md` or `AGENTS.md`.

## Command map

| Command | Purpose |
| --- | --- |
| `vmn stamp` | Compute, create, and publish a version |
| `vmn release` | Promote a prerelease to a final release |
| `vmn show` | Read version, status, or effective configuration |
| `vmn goto` | Restore recorded application and dependency revisions |
| `vmn snapshot` | Capture, inspect, compare, export, or restore working state |
| `vmn-exp` | Record, compare, export, or restore experiment runs (working state plus metrics) |
| `vmn worktrees` (`wt`) | Islands: worktrees of the app and its deps on private branches (create, pull, freeze, remove) |
| `vmn skill` | Output or install the AI agent skill block |
| `vmn add` | Attach build metadata to an existing version |
| `vmn gen` | Render a file from a Jinja2 template |
| `vmn config` | List or edit global, app, root-app, and branch configuration |
| `vmn-exp ui` | Run the optional web dashboard |

Run `vmn --help` or `vmn <command> --help` for the authoritative flag reference.

## Documentation

- [AI agent skill reference](https://github.com/progovoy/vmn/blob/master/docs/agent-skill.md)
- [Driving the UI fleet columns (for AI agents)](https://github.com/progovoy/vmn/blob/master/docs/ai-fleet-tracking.md)
- [Working-state snapshots](https://github.com/progovoy/vmn/blob/master/docs/snapshots.md)
- [Experiment tracking: client guide](https://github.com/progovoy/vmn/blob/master/docs/client-guide.md)
- [Experiment tracking](https://github.com/progovoy/vmn/blob/master/docs/experiments.md)
- [Python SDK](https://github.com/progovoy/vmn/blob/master/docs/sdk.md)
- [Model registry](https://github.com/progovoy/vmn/blob/master/docs/models.md)
- [Web UI](https://github.com/progovoy/vmn/blob/master/docs/ui.md)
- [vmn vs MLflow](https://github.com/progovoy/vmn/blob/master/docs/vmn-vs-mlflow.md)
- [vmn vs semantic-release](https://github.com/progovoy/vmn/blob/master/docs/vmn-vs-semantic-release.md)
- [vmn vs release-please](https://github.com/progovoy/vmn/blob/master/docs/vmn-vs-release-please.md)
- [vmn vs setuptools-scm](https://github.com/progovoy/vmn/blob/master/docs/vmn-vs-setuptools-scm.md)
- [Migrating from standard-version](https://github.com/progovoy/vmn/blob/master/docs/migrating-from-standard-version.md)
- [Migrating from bump2version](https://github.com/progovoy/vmn/blob/master/docs/migrating-from-bump2version.md)
- [Migrating from MLflow](https://github.com/progovoy/vmn/blob/master/docs/migrating-from-mlflow.md)

## Project

vmn is open source under the [MIT License](https://github.com/progovoy/vmn/blob/master/LICENSE.txt).
Issues, questions, and pull requests are welcome; see the
[contributing guide](https://github.com/progovoy/vmn/blob/master/CONTRIBUTING.md) and the
[issue tracker](https://github.com/progovoy/vmn/issues).
