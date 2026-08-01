<h1 align="center">vmn</h1>

<p align="center"><strong>Restorable release state across Git repositories.</strong></p>

<p align="center">
  Language-agnostic version management for products that span repositories.<br>
  Record a release once. Restore its source state later with one command.
</p>

<p align="center">
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/v/vmn?logo=pypi&logoColor=white&label=PyPI" alt="PyPI version"></a>
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/pyversions/vmn?logo=python&logoColor=white" alt="Supported Python versions"></a>
  <a href="https://github.com/progovoy/vmn/blob/master/LICENSE.txt"><img src="https://img.shields.io/github/license/progovoy/vmn" alt="MIT license"></a>
</p>

```sh
pipx install vmn

vmn stamp -r patch my_app       # 0.0.1

# Restore the application and every configured dependency repository.
vmn goto -v 0.0.1 my_app
```

vmn stores release metadata as readable YAML in annotated Git tags. Each tag
records the application revision, dependency revisions, previous version, and
release context. There is no vmn server and no external metadata database.

> Developed continuously since 2019, vmn is used in daily production workflows
> by teams at large companies managing multi-repository products. vmn versions
> its own releases. The repository contains more than 400 tests, including
> Docker-backed multi-repository, recovery, and compatibility scenarios.

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
| Measured | `vmn exp` | Working state plus metrics, parameters, artifacts, and run history |

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
```

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
1.6.0-dev.a1b2c3d.e4f5g6h     working-state snapshot
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

For CI, fetch complete history and tags, serialize stamps for the same app, and
provide write access to the remote. A minimal GitHub Actions job looks like:

```yaml
permissions:
  contents: write

steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0
  - uses: actions/setup-python@v5
    with:
      python-version: '3.12'
  - run: pip install 'vmn==0.9.3'
  - run: vmn stamp --pull -r patch my_app
```

Start an established migration with `--dry-run`; then add branch policy before
enabling automatic stamps.

## Working-state snapshots

Between releases, capture and restore your exact working state — uncommitted
changes, local commits, and untracked files — as a named version:

```sh
vmn snapshot create my_app --note "parser refactor"
vmn snapshot restore my_app --latest
```

Snapshots extend the same state-recovery model as `goto` to uncommitted work.
Local-first experiment tracking (`vmn exp`) builds on snapshots to capture
metrics alongside code state; see [docs/experiments.md](https://github.com/progovoy/vmn/blob/master/docs/experiments.md).

Install `vmn[ui]` for a local web dashboard with stamp-tree views and snapshot
comparison.

## Command map

| Command | Purpose |
| --- | --- |
| `vmn stamp` | Compute, create, and publish a version |
| `vmn release` | Promote a prerelease to a final release |
| `vmn show` | Read version, status, or effective configuration |
| `vmn goto` | Restore recorded application and dependency revisions |
| `vmn snapshot` | Capture, inspect, compare, export, or restore working state |
| `vmn exp` | Track experiments built on working-state snapshots |
| `vmn add` | Attach build metadata to an existing version |
| `vmn gen` | Render a file from a Jinja2 template |
| `vmn config` | List or edit global, app, root-app, and branch configuration |
| `vmn ui` | Run the optional web dashboard |

Run `vmn --help` or `vmn <command> --help` for the authoritative flag reference.

## Documentation

- [Experiment tracking](https://github.com/progovoy/vmn/blob/master/docs/experiments.md)
- [Web UI](https://github.com/progovoy/vmn/blob/master/docs/ui.md)
- [vmn vs semantic-release](https://github.com/progovoy/vmn/blob/master/docs/vmn-vs-semantic-release.md)
- [vmn vs release-please](https://github.com/progovoy/vmn/blob/master/docs/vmn-vs-release-please.md)
- [vmn vs setuptools-scm](https://github.com/progovoy/vmn/blob/master/docs/vmn-vs-setuptools-scm.md)
- [Migrating from standard-version](https://github.com/progovoy/vmn/blob/master/docs/migrating-from-standard-version.md)
- [Migrating from bump2version](https://github.com/progovoy/vmn/blob/master/docs/migrating-from-bump2version.md)

## Project

vmn is open source under the [MIT License](https://github.com/progovoy/vmn/blob/master/LICENSE.txt).
Issues, questions, and pull requests are welcome; see the
[contributing guide](https://github.com/progovoy/vmn/blob/master/CONTRIBUTING.md) and the
[issue tracker](https://github.com/progovoy/vmn/issues).
