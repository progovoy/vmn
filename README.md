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
Which commit of each one actually shipped? Without vmn, that is an afternoon of
CI logs and container tags. With vmn:

```sh
vmn goto -v 2.1.0 my_platform   # every repo back at the commit that shipped
```

vmn stores release metadata as readable YAML in annotated Git tags: the
application revision, every dependency's revision and remote, the previous
version, and release context. There is no vmn server and no external metadata
database.

> Developed continuously since 2019, vmn is used in daily production workflows
> by teams at large companies managing multi-repository products. vmn versions
> its own releases. The repository contains more than 400 tests, including
> Docker-backed multi-repository, recovery, and compatibility scenarios.

If vmn saves you an afternoon, a ⭐ helps other teams find it.

[Quick start](#quick-start) · [Why vmn](#why-vmn) ·
[Multi-repository recovery](#multi-repository-recovery) ·
[Release models](#release-models) · [Configuration](#configuration) ·
[Operations](#production-operation) · [Commands](#command-reference) ·
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

A version is a handle to recorded source state, not only a string:

| State | Command | Captures |
| --- | --- | --- |
| Release | `vmn stamp` → `vmn goto` | Committed application and dependency revisions |
| Working | `vmn snapshot` | Release state plus local commits, tracked changes, and untracked files |

> **Scope:** vmn restores recorded source revisions. It does not rebuild
> artifacts, capture toolchains or runtime infrastructure, sign tags, or deploy
> software. Keep those responsibilities in your build, signing, and deployment
> pipeline.

## Quick start

Requirements: Python 3.8+, Git 2.10+ (2.17+ recommended), and a Git repository
with at least one commit and a writable remote.

```sh
pipx install vmn            # or: uv tool install vmn
vmn --completion-install    # optional: bash/zsh/fish/tcsh, auto-detected
```

Inside any Git repository:

```sh
vmn stamp -r patch my_app          # 0.0.1; initializes the repo and app on first use
vmn show my_app                    # 0.0.1

# After committing the next change:
vmn stamp -r minor my_app          # 0.1.0

# After committing another change:
vmn stamp -r patch --pr rc my_app  # 0.1.1-rc.1
vmn release my_app                 # 0.1.1
```

A stamp creates a version commit and annotated tags, then pushes the branch and
tags. `--dry-run` previews it. Stamping an already-versioned state is
idempotent. No separate `vmn init` is needed; `init` and `init-app -v <version>`
remain for migrations and non-default starting versions.

Inspect the source of truth directly:

```sh
git tag --list 'my_app_*'
git cat-file -p my_app_0.1.0
vmn show --verbose my_app
```

## Multi-repository recovery

Declare dependency repositories in `.vmn/my_app/conf.yml`, keyed by their
directory relative to the app repository:

```yaml
conf:
  deps:
    ../:
      lib_core:
        vcs_type: git
      service_api:
        vcs_type: git
        branch: main       # optional pin, checked before every stamp
```

Every stamp records each dependency's exact revision and remote. Later, from
any revision:

```sh
vmn goto -v 1.4.0 my_app
```

`goto` checks out every recorded repository and clones any that are missing.
`--pull` fetches first when the version is not available locally;
`--deps-only` leaves the application repository unchanged; without `-v` it
returns to the tip of the current branch.

<details>
<summary><strong>Dependency keys</strong></summary>

| Key | Meaning |
| --- | --- |
| `vcs_type` | `git` |
| `remote` | Clone URL; auto-detected from the existing checkout when omitted |
| `branch` | Stamping requires the dep to be on this branch |
| `tag` | Stamping requires the dep to be at this tag |
| `hash` | Stamping requires the dep to be at this commit |

A dependency with uncommitted changes blocks `stamp`. Do not embed credentials
in remote URLs: dependency remotes are part of release metadata. Use SSH, a Git
credential helper, or vmn's per-command push credentials.

</details>

### Islands: app and deps side by side

`vmn wt` (alias of `vmn worktrees`) builds an *island*: git worktrees for the
application and every dependency, laid out like the originals, plus an
`island.json` manifest. Each checkout starts on a private
`island/<name>/<branch>` branch that follows its source branch but cannot be
pushed; stamping is refused on it.

```sh
vmn wt create my_app --island-name feat                   # from the current commits
vmn wt create my_app --island-name feat --carry-changes   # ...plus uncommitted work
vmn wt pull                                               # rebase onto the source branches
vmn wt freeze my_app                                      # pin deps to the branches they are on
vmn wt remove feat
```

To share the work, check out a real branch in each repo you changed
(`git checkout -b feature/x && git push -u origin feature/x`) and run
`vmn wt freeze` in the application. It pins those dependency branches in the
current branch's conf, so a colleague who checks out `feature/x` and runs
`vmn wt create` gets the same dependency state. `-fv 2.1.0` builds an island at
a recorded version instead.

## Release models

```text
1.6.0                         release
1.6.0-rc.23                   prerelease
1.6.7.4                       optional fourth hotfix segment
1.6.0-rc.23+build01           build metadata (vmn add)
1.6.0-dev.a1b2c3d.e4f5g6h     recorded working state (a snapshot)
```

**How the release mode is chosen**, first match wins:

1. `-r <mode>` (strict: always bumps) or `--orm <mode>` (optional: only
   advances if no prerelease exists at the target) on the command line.
2. Conventional Commits since the last version — **on by default**: `fix:` →
   patch, `feat:` → minor, `type!:` or a `BREAKING CHANGE` footer → major.
3. `default_release_mode` from conf.yml.

Modes from 2 and 3 are applied as `--orm` or `-r` per `release_mode_policy`
(`optional` by default, or `strict`). During a prerelease sequence, `vmn stamp
--pr rc my_app` needs no mode at all.

For independently deployed services, use a root app:

```sh
vmn stamp -r patch platform/auth       # auth 0.0.1; platform 1
vmn stamp -r minor platform/billing    # billing 0.1.0; platform 2
vmn show --root platform               # 2
```

## Configuration

Per-app configuration lives in `.vmn/<app>/conf.yml` under a top-level `conf:`
key; root apps have `.vmn/<root>/root_conf.yml`. Edit it with the TUI
(`vmn config my_app`, `--vim` for `$EDITOR`) or create it non-interactively
with `vmn config gen my_app`.

```yaml
conf:
  release_mode_policy: optional
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

<details>
<summary><strong>All conf.yml keys</strong></summary>

| Key | Default | Meaning |
| --- | --- | --- |
| `template` | `[{major}][.{minor}][.{patch}][.{hotfix}][-{prerelease}][.{rcn}][-dev.{dev_commit}.{dev_diff_hash}][+{buildmetadata}]` | Display format; `[...]` sections drop out when their field is empty |
| `hide_zero_hotfix` | `true` | Show `1.2.3` rather than `1.2.3.0` |
| `conventional_commits` | `true` | Detect the release mode from commit messages |
| `release_mode_policy` | `optional` | Apply a detected/default mode as `--orm` (`optional`) or `-r` (`strict`) |
| `default_release_mode` | unset | `major`/`minor`/`patch`/`hotfix` fallback when nothing else resolves a mode |
| `changelog` | unset | `{path: CHANGELOG.md}`: insert a Conventional-Commits entry below the file's title on each stamp |
| `github_release` | unset | `{draft: true\|false}`: create a GitHub Release on stamp (body from the changelog entry, else the commits); needs `gh` and `GITHUB_TOKEN`/`GH_TOKEN`; best-effort, warns instead of failing |
| `policies.whitelist_release_branches` | unset | Branches allowed to stamp non-prerelease versions and to `vmn release` |
| `deps` | the app repo only | Dependency repositories (see [Dependency keys](#multi-repository-recovery)) |
| `version_backends` | none | Files to write the version into (below) |
| `create_snapshots` | `false` | Also write a version file per stamp, readable with `vmn show --from-file` |
| `extra_info` | `false` | Record host/environment information in the stamp metadata |
| `experiment` | none | vmn-exp settings (storage URI, metrics, alerts); ignored by core vmn |

Root apps: `root_conf.yml` accepts `external_services`, recorded in each root
version. Deprecated keys (`create_verinfo_files`, `default_release_mode:
optional|strict`) are migrated automatically.

</details>

<details>
<summary><strong>Version backends</strong></summary>

| Backend | Writes |
| --- | --- |
| `npm: {path: package.json}` | `version` |
| `cargo: {path: Cargo.toml}` | `package.version` |
| `poetry: {path: pyproject.toml}` | `tool.poetry.version` |
| `pep621: {path: pyproject.toml}` | `project.version` |
| `generic_jinja` | Renders Jinja2 templates to output files |
| `generic_selectors` | Regex search-and-replace inside existing files |

```yaml
conf:
  version_backends:
    generic_jinja:
      - input_file_path: version.py.j2
        output_file_path: mypkg/_version.py
        custom_keys_path: custom.yml       # optional extra template values
    generic_selectors:
      - paths_section:
          - input_file_path: chart/Chart.yaml
            output_file_path: chart/Chart.yaml
        selectors_section:
          - regex_selector: '(version: ){{VMN_VERSION_REGEX}}'
            regex_sub: '\1{{version}}'
```

In `regex_selector`, `{{VMN_VERSION_REGEX}}` expands to a pattern matching any
vmn version; it has capture groups of its own, so in `regex_sub` refer only to
groups placed before it. Templates see the stamp metadata (`version`, `base_version`,
`changesets`, `root_*` for root apps, ...), plus `release_notes` (generated by
the bundled `git-cliff`, only when the template uses it). `vmn gen -t <tmpl>
-o <out> my_app` renders the same data on demand.

</details>

### Branch-specific configuration

Integration branches can override configuration, typically dep pins, without
touching the main conf:

```sh
vmn config gen my_app --branch                      # seeded from the effective conf
vmn config gen my_app --branch --sync-dep-branches  # pin deps to their checked-out branches
vmn config my_app --branch                          # edit interactively
```

The canonical layout is `.vmn/<app>/branch_conf/<branch>/conf.yml` (slashes in
the branch name become directories; root apps use `root_conf.yml`). Legacy
`<branch>_conf.yml` files are still read and are migrated on the next stamp.

## Production operation

- `--dry-run` previews a stamp without committing or tagging.
- Dirty, detached, outgoing, and dependency states are checked before release.
- A per-repository lock prevents concurrent local vmn operations.
- Release-branch allowlists restrict stable stamps to configured branches.
- `--pull` fetches remote state and retries version conflicts.
- vmn rolls back newly created local release state when publication fails.
- `--git-push-user`/`--git-push-token` (or `VMN_GIT_PUSH_USER`/`_TOKEN`)
  authenticate the push through an ephemeral HTTPS URL; the remote config is
  never modified.
- No internet access is required when an internal or local Git remote is used.

For GitHub Actions, use [vmn-action](https://github.com/marketplace/actions/automated-versioning):

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

Elsewhere, fetch complete history and tags, serialize stamps for the same app,
and give the job write access to the remote:

```sh
pip install vmn
vmn stamp --pull -r patch my_app
```

Start an established migration with `--dry-run`, then add branch policy before
enabling automatic stamps.

## Working-state snapshots

Between releases, save and restore your exact working state — uncommitted
changes, local commits, and untracked files, across every dependency — as a
named version, without committing:

```sh
vmn snapshot create my_app --note "parser refactor"   # prints 1.2.0-dev.a1b2c3d.e4f5g6h
vmn snapshot list my_app --last 5
vmn snapshot diff my_app -v @2                        # vs your working tree; --to <ref|version>
vmn snapshot restore my_app --latest                  # your current work is auto-saved first
```

Actions are `create` (default), `list`, `show`, `note`, `delete`, `restore`,
`export` and `diff`. The app must be stamped once first. With vmn-exp
installed, `--store <uri>` keeps snapshots in a shared experiment store and
`vmn goto -v <snapshot>` restores them. See
[docs/snapshots.md](https://github.com/progovoy/vmn/blob/master/docs/snapshots.md).

## Experiment tracking (vmn-exp)

`vmn-exp` is a separate, optional product built on vmn: it records training and
evaluation runs as working-state versions with their metrics, params and
artifacts, plus a model registry, sweeps and a web dashboard.

```sh
pip install vmn-exp         # "vmn-exp[ui]" adds the dashboard
```

See the [vmn-exp documentation](https://github.com/progovoy/vmn/blob/master/docs/vmn-exp/README.md).
Coming from vmn 0.10 or earlier: `vmn exp`/`model`/`ui` are now `vmn-exp …`
([packaging](https://github.com/progovoy/vmn/blob/master/docs/packaging.md#installing)).

## AI agent integration

`vmn skill` gives AI coding agents the context they need to use vmn correctly:

```sh
vmn skill                               # print the skill block
vmn skill --install                     # .claude/skills/vmn/SKILL.md (--force overwrites)
vmn skill --install --target cursor     # .cursorrules
vmn skill --install --target agents     # AGENTS.md
```

Re-running `--install` for cursor/agents updates only vmn's section. Optional,
opinionated development rules for agents (TDD, worktrees, minimal diffs, ...)
live in [docs/agent-methodology.md](https://github.com/progovoy/vmn/blob/master/docs/agent-methodology.md).

## Command reference

| Command | Purpose |
| --- | --- |
| `vmn stamp` | Compute, create, and publish a version |
| `vmn release` | Promote a prerelease to a final release |
| `vmn show` | Read version, status, or effective configuration |
| `vmn goto` | Restore recorded application and dependency revisions |
| `vmn snapshot` | Capture, inspect, compare, export, or restore working state |
| `vmn worktrees` (`wt`) | Islands: worktrees of the app and its deps (create, list, pull, freeze, remove) |
| `vmn add` | Attach build metadata to an existing version |
| `vmn gen` | Render a file from a Jinja2 template |
| `vmn config` | List apps, or edit global, app, root-app, and branch configuration |
| `vmn skill` | Output or install the AI agent skill block |
| `vmn init` / `vmn init-app` | Explicit initialization (optional; `stamp` auto-inits) |

<details>
<summary><strong>Flags</strong></summary>

**`vmn stamp <app>`**

| Flag | Meaning |
| --- | --- |
| `-r, --release-mode` | `major`/`minor`/`patch`/`hotfix`; always bumps |
| `--orm, --optional-release-mode` | Bump only if no prerelease already exists at the target |
| `--pr, --prerelease <id>` | Prerelease, e.g. `rc` → `0.0.1-rc.1` |
| `--ov, --override-version <v>` | Bump from `<v>` instead of the current version (`--ov 1.0.0 -r patch` → `1.0.1`) |
| `--orv, --override-root-version <n>` | Bump the root app from `<n>` |
| `--pull` | Pull first; retry on a version conflict |
| `--dry-run` | Preview without committing, tagging or pushing |
| `-e, --extra-commit-message <s>` | Append to the version commit message (e.g. `[ci skip]`) |
| `--dont-check-vmn-version` | Skip the check that this vmn is not older than the one that stamped last |
| `--git-push-user`, `--git-push-token` | Push credentials (both required) |

**`vmn release <app>`**: tags the prerelease's commit as the final version
and pushes the tag. `-v <version>` names the prerelease (default: the one at
HEAD); `-s, --stamp` instead runs the full stamp flow (new commit, backends
updated). Takes `--git-push-user`/`--git-push-token`.

**`vmn show <app>`**

| Flag | Meaning |
| --- | --- |
| `-v <version>` | Show a specific version instead of the current one |
| `--verbose` | Full stamp metadata as YAML |
| `--raw` | Version without the template applied |
| `-t, --template <t>` | Format with a different template |
| `--root` | Root app version |
| `--type` | Release type (`release` or the prerelease id) |
| `-u, --unique` | Version plus the commit hash |
| `--dev` | Working-state version of a dirty tree |
| `--conf` | Effective configuration |
| `--from-file` | Read from `.vmn/` files instead of git (with `create_snapshots`) |
| `--ignore-dirty` | Do not report dirty states |

**`vmn goto <app>`**: `-v <version>` (default: tip of the current branch),
`--root` (`-v` is a root version), `--deps-only`, `--pull`, `--force` (dev
versions: restore even if oversized untracked files would be lost).

**`vmn add <app>`**: `--bm, --buildmetadata <s>` (required), `-v <version>`
(default: the version at HEAD), `--vmp, --version-metadata-path <yml>`,
`--vmu, --version-metadata-url <url>`.

**`vmn gen <app>`**: `-t, --template <j2>` and `-o, --output <file>`
(required), `-v <version>`, `-c, --custom-values <yml>`, `--verify-version`
(refuse on a dirty tree or when HEAD is not at the version).

**`vmn config [gen] [app]`**: no app lists managed apps; `--vim` (`$EDITOR`),
`--root` (`root_conf.yml`), `--global` (`.vmn/conf.yml`), `--branch`,
`--sync-dep-branches` (with `gen --branch`). `gen` never overwrites.

**`vmn worktrees [create|list|pull|freeze|remove] [name]`**: `create` (the
default) takes `--island-name`, `-fv, --from-version`, `-fb, --from-branch`,
`--base-path` (default `../vmn-islands`), `--shallow-deps`, `--carry-changes`.

**`vmn init-app <app>`**: `-v <version>` (start from, default `0.0.0`),
`--dry-run`, `--orm optional|strict` (sets `release_mode_policy`).

**`vmn snapshot`**: see [docs/snapshots.md](https://github.com/progovoy/vmn/blob/master/docs/snapshots.md#actions).

**Global**: `--version`, `--debug`, `--completion [SHELL]`,
`--completion-install [SHELL]`, `--completion-uninstall [SHELL]`.

</details>

<details>
<summary><strong>Environment variables</strong></summary>

| Variable | Effect |
| --- | --- |
| `VMN_WORKING_DIR` | Run as if started in this directory |
| `VMN_LOCK_FILE_PATH` | Lock file path (default `.vmn/vmn.lock`) |
| `VMN_GIT_PUSH_USER` / `VMN_GIT_PUSH_TOKEN` | Fallbacks for `--git-push-user` / `--git-push-token` |
| `GITHUB_TOKEN` / `GH_TOKEN` | Needed for `github_release` |
| `VMN_SNAPSHOT_MAX_FILE_MB` / `VMN_SNAPSHOT_MAX_TOTAL_MB` | Caps on untracked files captured into a snapshot (default 50 / 200) |
| `EDITOR` | Editor for `vmn config --vim` (default `vim`) |

</details>

## Documentation

- [Working-state snapshots](https://github.com/progovoy/vmn/blob/master/docs/snapshots.md)
- [AI agent skill reference](https://github.com/progovoy/vmn/blob/master/docs/agent-skill.md)
- [Packaging and installation](https://github.com/progovoy/vmn/blob/master/docs/packaging.md)
- [vmn vs semantic-release](https://github.com/progovoy/vmn/blob/master/docs/vmn-vs-semantic-release.md)
- [vmn vs release-please](https://github.com/progovoy/vmn/blob/master/docs/vmn-vs-release-please.md)
- [vmn vs setuptools-scm](https://github.com/progovoy/vmn/blob/master/docs/vmn-vs-setuptools-scm.md)
- [Migrating from standard-version](https://github.com/progovoy/vmn/blob/master/docs/migrating-from-standard-version.md)
- [Migrating from bump2version](https://github.com/progovoy/vmn/blob/master/docs/migrating-from-bump2version.md)
- [vmn-exp (experiment tracking)](https://github.com/progovoy/vmn/blob/master/docs/vmn-exp/README.md)

## Project

vmn is open source under the [MIT License](https://github.com/progovoy/vmn/blob/master/LICENSE.txt).
Issues, questions, and pull requests are welcome; see the
[contributing guide](https://github.com/progovoy/vmn/blob/master/CONTRIBUTING.md) and the
[issue tracker](https://github.com/progovoy/vmn/issues).
