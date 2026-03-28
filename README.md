<h1 align="center">🏷️ vmn</h1>
<p align="center"><strong>Automatic semantic versioning, powered by git tags</strong></p>

<p align="center">
  <a href="https://github.com/progovoy/vmn"><img src="https://img.shields.io/badge/vmn-automatic%20versioning-blue" alt="vmn"></a>
  <a href="https://www.repostatus.org/#active"><img src="https://www.repostatus.org/badges/latest/active.svg" alt="Active"></a>
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/v/vmn?logo=pypi&logoColor=white&label=PyPI" alt="PyPI version"></a>
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/dw/vmn?logo=pypi&logoColor=white" alt="PyPI downloads"></a>
  <a href="https://github.com/progovoy/vmn"><img src="https://img.shields.io/github/stars/progovoy/vmn?style=flat&logo=github" alt="GitHub stars"></a>
  <a href="https://github.com/progovoy/vmn/blob/master/LICENSE"><img src="https://img.shields.io/github/license/progovoy/vmn" alt="License"></a>
</p>
<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/python-3.8+-3776AB?logo=python&logoColor=white" alt="Python 3.8+"></a>
  <a href="#"><img src="https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20windows-brightgreen" alt="Platforms"></a>
  <a href="https://semver.org"><img src="https://img.shields.io/badge/semver-2.0.0-blue?logo=semver&logoColor=white" alt="Semver"></a>
  <a href="https://conventionalcommits.org"><img src="https://img.shields.io/badge/Conventional%20Commits-1.0.0-%23FE5196?logo=conventionalcommits&logoColor=white" alt="Conventional Commits"></a>
</p>

<p align="center">
  Language-agnostic versioning for any project.<br>
  Monorepos, multi-repo dependencies, microservices, release candidates, conventional commits — all built in.
</p>

<p align="center">
  <img width="500" src="https://i.imgur.com/g3wYIk8.png" alt="vmn workflow: Work → git push → vmn stamp">
</p>

---

🚀 [Quick Start](#-quick-start) · ⚖️ [Why vmn?](#%EF%B8%8F-why-vmn) · 📖 [Commands](#-commands) · 🔌 [Auto-Embedding](#-version-auto-embedding) · ⚙️ [Configuration](#%EF%B8%8F-configuration) · 🔄 [CI](#-ci-integration) · 🤝 [Contributing](CONTRIBUTING.md)

---

## 🚀 Quick Start

```sh
pip install vmn                 # or: pipx install vmn / uvx vmn

# That's it — vmn auto-initializes on first stamp (no init needed)
vmn stamp -r patch my_app
# => 0.0.1
```

No separate `vmn init` or `vmn init-app` required — when you run `vmn stamp` on a fresh repo, vmn automatically initializes the repository and app for you.

> **Shallow clones**: vmn works with shallow repositories (e.g. `git clone --depth 1` or CI's `fetch-depth: 1`). It automatically detects shallow clones and fetches the missing history it needs. For best performance, prefer a full clone (`fetch-depth: 0` in CI).

## ⚖️ Why vmn?

> 💡 **tl;dr** — vmn does what semantic-release/release-please do, but works with *any* language and adds multi-repo tracking, state recovery, and microservice topologies that no competitor offers.

| Capability | <img src="https://img.shields.io/badge/vmn-blue?style=flat-square" alt="vmn"> | <img src="https://img.shields.io/badge/semantic--release-494949?style=flat-square&logo=semanticrelease&logoColor=white" alt="semantic-release"> | <img src="https://img.shields.io/badge/release--please-4285F4?style=flat-square&logo=google&logoColor=white" alt="release-please"> | <img src="https://img.shields.io/badge/changesets-purple?style=flat-square" alt="changesets"> |
|:-----------|:---:|:----------------:|:--------------:|:----------:|
| Language-agnostic | :white_check_mark: | JS-centric | JS-centric | JS-only |
| Git-tag source of truth | :white_check_mark: | :white_check_mark: | :white_check_mark: | :x: |
| Multi-repo dependency tracking | :white_check_mark: | :x: | :x: | :x: |
| State recovery (`vmn goto`) | :white_check_mark: | :x: | :x: | :x: |
| Microservice / root app topology | :white_check_mark: | :x: | :x: | monorepo only |
| 4-segment hotfix versioning | :white_check_mark: | :x: | :x: | :x: |
| Auto-embed version (npm, Cargo, pyproject, any file) | :white_check_mark: | per-plugin | :x: | JS only |
| Conventional commits | :white_check_mark: | :white_check_mark: | :white_check_mark: | :x: |
| Changelog generation | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| GitHub Release creation | :white_check_mark: | :white_check_mark: | :white_check_mark: | :x: |
| Zero-config start (auto-init) | :white_check_mark: | :x: | :x: | :x: |
| Offline / local file backend | :white_check_mark: | :x: | :x: | :x: |
| Zero lock-in (pure git tags) | :white_check_mark: | :x: | :x: | :x: |

<details>
<summary>Detailed comparisons & migration guides</summary>

- [vmn vs semantic-release](docs/vmn-vs-semantic-release.md)
- [vmn vs release-please](docs/vmn-vs-release-please.md)
- [vmn vs setuptools-scm](docs/vmn-vs-setuptools-scm.md)
- [Migrating from standard-version](docs/migrating-from-standard-version.md)
- [Migrating from bump2version](docs/migrating-from-bump2version.md)

</details>

## ✨ Features

| | Feature | Description |
|:-:|:--------|:------------|
| 🔢 | **Version formats** | `1.6.0` / `1.6.0-rc.23` / `1.6.7.4` / `1.6.0-rc.23+build01.Info` — [Semver](https://semver.org) + hotfix extension |
| 🪄 | **[Zero-config start](#-quick-start)** | Auto-initializes repo and app on first `vmn stamp` — no init step needed |
| 📝 | **[Conventional commits](#conventional-commits)** | Auto-detect release mode from `fix:`, `feat:`, `BREAKING CHANGE` commits |
| 📋 | **[Changelog generation](#changelog-generation)** | Built-in CHANGELOG.md from conventional commits on each stamp |
| 🚀 | **[GitHub Releases](#github-release-creation)** | Optionally create GitHub Releases after stamp (via `gh` CLI) |
| 📦 | **[Version auto-embedding](#-version-auto-embedding)** | Write version into `package.json`, `Cargo.toml`, `pyproject.toml`, or any file |
| ⏪ | **[State recovery](#vmn-goto)** | `vmn goto` restores the exact repo state for any stamped version |
| 🧩 | **[Microservices](#root-apps-or-microservices)** | Root apps with independent service versions |
| 🔗 | **[Multi-repo deps](#configuration)** | Track and lock versions across repositories |
| ⚡ | **[uv / hatchling](#hatchling--uv)** | Dynamic versioning from git tags via `hatch-vcs` |
| 🔧 | **[Interactive config](#vmn-config)** | TUI editor for app configuration (`vmn config`) |

<details>
<summary><strong>Try it locally (playground)</strong></summary>

```sh
pip install vmn

# Create a playground repo
mkdir remote && cd remote && git init --bare && cd ..
git clone ./remote ./local && cd local
echo a >> ./a.txt && git add ./a.txt && git commit -m "first commit" && git push origin master

# Stamp your first version
vmn stamp -r patch my_app   # => 0.0.1

# Make a change and stamp again
echo b >> ./a.txt && git add ./a.txt && git commit -m "feat: add b" && git push origin master
vmn stamp -r patch my_app   # => 0.0.2
```

</details>

---

## 📖 Commands

> `init-app` and `stamp` both support `--dry-run` for safe testing.

### vmn init / init-app

Usually not needed — `vmn stamp` auto-initializes on first run. Use these only for explicit control:

```sh
vmn init                            # initialize vmn in a repository (creates .vmn/, commits, pushes)
vmn init-app <app-name>             # initialize an app (starts from 0.0.0)
vmn init-app -v 1.6.8 <app-name>   # initialize from a specific version
vmn init-app --dry-run <app-name>   # preview without making changes
vmn init-app --orm strict <app-name> # set default_release_mode to strict (default: optional)
```

### vmn stamp

```sh
vmn stamp -r patch <app-name>                 # => 0.0.1
vmn stamp -r minor <app-name>                 # => 0.1.0
vmn stamp -r patch --pr rc <app-name>         # => 0.0.2-rc.1 (prerelease)
vmn stamp --dry-run -r patch <app-name>       # preview without committing
vmn stamp -r patch -e '[skip ci]' <app-name>  # append text to commit message
vmn stamp --pull -r patch <app-name>          # pull before stamping (retries on push conflict)
```

<details>
<summary><strong>All stamp flags</strong></summary>

| Flag | Description |
|:-----|:------------|
| `-r`, `--release-mode` | Release mode: `major` / `minor` / `patch` / `hotfix` (also accepts `micro` as alias for `hotfix`) |
| `--orm`, `--optional-release-mode` | Like `-r` but only advances if no prerelease exists at target version ([details below](#-r-vs---orm)) |
| `--pr`, `--prerelease` | Prerelease identifier (e.g. `alpha`, `rc`, `beta.1`). Trailing `.` is auto-stripped |
| `--dry-run` | Preview the version that would be stamped without committing or pushing |
| `--pull` | Pull remote changes before stamping. Enables retry on push conflicts (up to 3 retries with 1-5s delay) |
| `-e`, `--extra-commit-message` | Append text to the stamp commit message (e.g. `[skip ci]`) |
| `--ov`, `--override-version` | Force a specific version string (bypasses release mode logic) |
| `--orv`, `--override-root-version` | Force root app version to a specific integer |
| `--dont-check-vmn-version` | Skip check that the vmn binary is at least as new as the version in metadata |

**Behaviors:**
- **Idempotent** — if the current commit already has a matching version, vmn returns 0 without re-stamping
- **Detached HEAD** — vmn refuses to stamp in detached HEAD state
- **Auto-init** — automatically runs `vmn init` + `vmn init-app` on first stamp if repo/app not yet tracked

</details>

<details>
<summary><strong>Stamping without <code>-r</code> and <code>-r</code> vs <code>--orm</code></strong></summary>

#### Stamping without `-r`

Running `vmn stamp <app-name>` without `-r` (and without `--orm`) works only when the current version is a **prerelease**. In that case `vmn` continues the existing prerelease sequence without changing the base version:

```sh
vmn stamp -r patch --pr rc <app-name>
# 0.0.2-rc.1

vmn stamp --pr rc <app-name>
# 0.0.2-rc.2  (no -r needed, continues the prerelease)

vmn stamp <app-name>
# 0.0.2-rc.3  (even without --pr, stays on the same prerelease)
```

If the current version is a **released** version (e.g., `0.0.1`), running `vmn stamp` without `-r` or `--orm` will error:

```
[ERROR] When not in release candidate mode, a release mode must be specified
       - use -r/--release-mode with one of major/minor/patch/hotfix
```

The same error occurs when conventional commits are configured but no recognized conventional commit types (`fix`, `feat`, etc.) are found in the commit range since the last stamp.

#### `-r` vs `--orm`

Both flags specify the release mode (major/minor/patch/hotfix), but they differ in how they handle existing prereleases:

| Flag | Behavior |
|:----:|:---------|
| `-r patch` | **Strict** — always advances the base version. From `0.0.1` → `0.0.2`. From `0.0.2-rc.3` → `0.0.3`. |
| `--orm patch` | **Optional** — advances the base version only if the target version has no existing prereleases. From `0.0.1` → `0.0.2`. From `0.0.1` when `0.0.2-rc.1` already exists → `0.0.2-rc.2` (continues the prerelease instead of bumping). |

</details>

### Conventional commits

To have `vmn stamp` deduce the release mode automatically from commit messages, configure your app's `conf.yml`:

```yaml
conf:
  default_release_mode: optional
  conventional_commits: true
```

`vmn` scans commits since the last stamp and picks the highest release mode based on conventional commit types: `fix` → patch, `feat` → minor, `BREAKING CHANGE` or `!` → major.

`default_release_mode` controls which stamping behavior is used for the auto-detected mode:

| Value | Equivalent flag | Behavior |
|:-----:|:---------------:|:---------|
| `optional` (default) | `--orm` | Only advances the base version if no prerelease already exists for the target version. If a prerelease exists, continues from it. |
| `strict` | `-r` | Always advances the base version unconditionally. |

Now you can run `vmn stamp <app-name>` and `vmn` will deduce the proper release mode automatically.

### Changelog generation

`vmn stamp` can automatically generate a [Keep a Changelog](https://keepachangelog.com)-formatted CHANGELOG.md from conventional commits:

```yaml
# .vmn/<app-name>/conf.yml
conf:
  conventional_commits: true
  changelog:
    enabled: true
    path: "CHANGELOG.md"   # optional, defaults to CHANGELOG.md
```

On each stamp, vmn collects commits since the last version, groups them by type (Features, Bug Fixes, Breaking Changes, etc.), and prepends a new `## [version] - date` entry to the changelog. The changelog file is automatically included in the stamp commit.

### GitHub Release creation

`vmn stamp` can automatically create a GitHub Release after pushing tags:

```yaml
# .vmn/<app-name>/conf.yml
conf:
  github_release:
    enabled: true
    draft: false           # optional, create as draft release
```

**Requirements:** the [`gh` CLI](https://cli.github.com/) must be installed and either `GITHUB_TOKEN` or `GH_TOKEN` must be set. If a CHANGELOG.md exists, the release body is extracted from it; otherwise vmn falls back to listing commits. Prereleases are automatically marked as such. Failures are best-effort — they log a warning but don't fail the stamp.

### vmn release

Promote a prerelease to its final version. Three modes:

```sh
vmn stamp -r patch --pr rc <app-name>   # => 0.0.1-rc.1

# 1. Explicit version — tag-only, no new commit, works from anywhere
vmn release -v 0.0.1-rc.1 <app-name>   # => 0.0.1

# 2. Auto-detect — omit -v when on the prerelease commit (tag-only)
vmn release <app-name>                  # => 0.0.1

# 3. Full stamp flow — new commit + tag + push (runs version backends, changelog, etc.)
vmn release --stamp <app-name>          # => 0.0.1
```

Modes 1 and 2 create a lightweight tag pointing to the original prerelease commit — no new commit is created. Mode 2 auto-detects the version from the current commit (you must be on a version commit).

`--stamp` (`-s`) runs the full stamp pipeline (new commit, tag, push, version backends, changelog) but requires being on a branch tip (not detached HEAD) at the exact prerelease commit, with clean dependencies. `-v` and `-s`/`--stamp` are mutually exclusive.

**Notes:**
- Cannot release a version that contains build metadata (e.g. `1.0.0+build42`)
- `whitelist_release_branches` policy is enforced — release is rejected if the version was stamped on a non-whitelisted branch
- Idempotent — if the release version already exists, returns 0 without creating a duplicate tag

### vmn show

```sh
vmn show <app-name>                    # current version (formatted)
vmn show --raw <app-name>              # raw version without template formatting
vmn show --verbose <app-name>          # full YAML metadata dump
vmn show -v 0.0.1 <app-name>          # show info for a specific version
vmn show --root my_root_app            # show root app version (integer)
vmn show --conf <app-name>             # include configuration (deps, template, backends)
vmn show --from-file <app-name>        # read from file instead of git (faster, no repo validation)
vmn show --type <app-name>             # show version type: release / prerelease / metadata
vmn show -u <app-name>                 # show unique ID (version+commit_hash)
vmn show --ignore-dirty <app-name>     # suppress dirty repo warnings in output
vmn show -t '[{major}]' <app-name>    # override display template for this invocation
```

### vmn gen

Generate a version file from a Jinja2 template:

```sh
vmn gen -t version.j2 -o version.txt <app-name>               # basic generation
vmn gen -t version.j2 -o version.txt -v 1.0.0 <app-name>     # generate for a specific version
vmn gen -t notes.j2 -o notes.txt -c custom.yml <app-name>     # merge custom YAML values into template
vmn gen -t notes.j2 -o notes.txt --verify-version <app-name>  # fail if repo is dirty or not at version
```

`--verify-version` ensures the repository is clean and checked out at the exact target version before generating. Output is idempotent — the file is not rewritten if content is identical.

See [Template Variables](#-template-variables-for-vmn-gen) for available Jinja2 variables.

### vmn goto

Checkout the repository (and its dependencies) to the exact state at a stamped version:

```sh
vmn goto -v 0.0.1 <app-name>              # checkout app + deps to version 0.0.1
vmn goto -v 0.0.1 --deps-only <app-name>  # only checkout dependencies, leave main app as-is
vmn goto -v 5 --root my_root_app          # checkout to root app version
vmn goto --pull -v 0.0.1 <app-name>       # pull from remote before checkout
```

Dependencies are cloned automatically if missing (up to 10 in parallel) and checked out to the exact hash recorded at stamp time.

### vmn add

Attach build metadata to an existing stamped version:

```sh
vmn add -v 0.0.1 --bm build42 <app-name>                          # => 0.0.1+build42
vmn add --bm build42 <app-name>                                    # auto-detect version from current commit
vmn add -v 0.0.1 --bm build42 --vmp metadata.yml <app-name>       # attach a YAML file as metadata
vmn add -v 0.0.1 --bm build42 --vmu https://ci/build/42 <app-name> # attach a URL as metadata
```

Idempotent — if the same metadata already exists, returns 0. Cannot add metadata to a version that already has different metadata attached.

### vmn config

Interactive TUI for viewing and editing app configuration without manually editing YAML:

```sh
vmn config <app-name>           # interactive TUI editor
vmn config <app-name> --vim     # open in $EDITOR (default: vim) instead of TUI
vmn config                      # list all managed apps
vmn config --global             # edit repo-level .vmn/conf.yml
vmn config <app-name> --root    # edit root app config (requires app name with /)
```

The TUI supports editing most config fields (template, version_backends, deps, policies, conventional_commits, etc.) with validation and auto-detection. `changelog` and `github_release` are not yet editable in the TUI — use `--vim` to edit those. Requires a terminal (TTY); falls back to `--vim` if not available.

### 🐍 Python Library Usage

```python
from contextlib import redirect_stdout, redirect_stderr
import io
import version_stamp.vmn as vmn

out = io.StringIO()
err = io.StringIO()
with redirect_stdout(out), redirect_stderr(err):
    ret, vmn_ctx = vmn.vmn_run(["show", "vmn"])
out_s = out.getvalue()
err_s = err.getvalue()
```

Explore the `vmn_ctx` object for available fields. Attributes starting with `_` are private and may change.

### 🌐 Environment Variables

| Variable | Description |
|:---------|:------------|
| `VMN_WORKING_DIR` | Override the working directory for vmn |
| `VMN_LOCK_FILE_PATH` | Custom lock file path (default: per-repo lock to prevent concurrent vmn commands) |
| `GITHUB_TOKEN` / `GH_TOKEN` | Required for [GitHub Release creation](#github-release-creation) via `gh` CLI |

---

## 🔬 Advanced Topics

### 🏗️ Release Candidates

`vmn` supports Semver prerelease versions, letting you iterate on release candidates before promoting to a final release:

```sh
vmn init-app -v 1.6.8 <app-name>

vmn stamp -r major --pr alpha <app-name>    # 2.0.0-alpha.1
vmn stamp --pr alpha <app-name>             # 2.0.0-alpha.2
vmn stamp --pr mybeta <app-name>            # 2.0.0-mybeta.1

vmn release -v 2.0.0-mybeta.1 <app-name>   # 2.0.0 (tag only)
# or: vmn release --stamp <app-name>      # 2.0.0 (full stamp flow)
```

### 🧩 Root Apps (Microservices)

Manage versions for multiple services under one umbrella:

```sh
vmn init-app my_root_app/service1
vmn init-app my_root_app/service2
vmn init-app my_root_app/service3

vmn stamp -r patch my_root_app/service1
vmn stamp -r patch my_root_app/service2
vmn stamp -r patch my_root_app/service3
```

<details>
<summary>Example <code>vmn show --verbose</code> output</summary>

```yaml
vmn_info:
  description_message_version: '1'
  vmn_version: <vmn version>
stamping:
  msg: 'my_root_app/service3: update to version 0.0.1'
  app:
    name: my_root_app/service3
    _version: 0.0.1
    release_mode: patch
    prerelease: release
    previous_version: 0.0.0
    stamped_on_branch: master
    changesets:
      .:
        hash: 8bbeb8a4d3ba8499423665ba94687b551309ea64
        remote: <remote url>
        vcs_type: git
    info: {}
  root_app:
    name: my_root_app
    version: 5
    latest_service: my_root_app/service3
    services:
      my_root_app/service1: 0.0.1
      my_root_app/service2: 0.0.1
      my_root_app/service3: 0.0.1
    external_services: {}
```

</details>

```sh
vmn show my_root_app/service3      # => 0.0.1
vmn show --root my_root_app        # => 5
```

### 📄 Template Variables for `vmn gen`

<details>
<summary>Available template variables</summary>

```json
{
  "version": "0.0.1",
  "base_version": "0.0.1",
  "name": "test_app2/s1",
  "release_mode": "patch",
  "prerelease": "release",
  "previous_version": "0.0.0",
  "stamped_on_branch": "main",
  "release_notes": "",
  "changesets": {".": {"hash": "d637...", "remote": "...", "vcs_type": "git"}},
  "root_name": "test_app2",
  "root_version": 1,
  "root_services": {"test_app2/s1": "0.0.1"}
}
```

</details>

<details>
<summary>Template example</summary>

**Template** (`version.j2`):
```text
VERSION: {{version}}
NAME: {{name}}
BRANCH: {{stamped_on_branch}}
{% for k,v in changesets.items() %}
REPO: {{k}} | HASH: {{v.hash}} | REMOTE: {{v.remote}}
{% endfor %}
```

**Output**:
```text
VERSION: 0.0.1
NAME: test_app2/s1
BRANCH: master
REPO: . | HASH: ef4c6f43... | REMOTE: ../test_repo_remote
```

</details>

---

## 🔌 Version Auto-Embedding

`vmn stamp` can automatically write the version string into your project files:

| Backend | File | Description |
|:-------:|:----:|:------------|
| <img src="https://img.shields.io/badge/npm-CB3837?style=flat-square&logo=npm&logoColor=white" alt="npm"> | `package.json` | Updates `version` field |
| <img src="https://img.shields.io/badge/Cargo-000000?style=flat-square&logo=rust&logoColor=white" alt="Cargo"> | `Cargo.toml` | Updates `version` field |
| <img src="https://img.shields.io/badge/Poetry-60A5FA?style=flat-square&logo=poetry&logoColor=white" alt="Poetry"> | `pyproject.toml` | Updates `[tool.poetry].version` |
| <img src="https://img.shields.io/badge/PEP_621-3776AB?style=flat-square&logo=python&logoColor=white" alt="PEP 621"> | `pyproject.toml` | Updates `[project].version` |

### 🥚 Hatchling / <img src="https://img.shields.io/badge/uv-DE5FE9?style=flat-square&logo=uv&logoColor=white" alt="uv">

Projects using [hatchling](https://hatch.pypa.io/) (the default build backend for [uv](https://github.com/astral-sh/uv)) can use vmn's git tags as the version source with zero file injection. This is done by configuring hatchling's [hatch-vcs](https://github.com/ofek/hatch-vcs) plugin to read vmn tags directly.

This approach also supports **multiple apps per repository** — each app's tag pattern is distinct, so hatchling resolves the correct version for each package.

#### Setup

1. Install the plugin:

```sh
uv add --dev hatch-vcs
# or: pip install hatch-vcs
```

2. Configure `pyproject.toml` to use dynamic versioning from vmn tags:

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "my-package"
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"
tag-pattern = "my_app_(?P<version>.*)"
```

Replace `my_app` with your vmn app name. For root app services like `my_root_app/service1`, use the tag form where `/` becomes `-`:

```toml
[tool.hatch.version]
source = "vcs"
tag-pattern = "my_root_app-service1_(?P<version>.*)"
```

3. Stamp and build:

```sh
vmn stamp -r patch my_app
uv build
```

`hatch-vcs` will read the version from vmn's git tag — no version file to maintain.

#### Static version alternative

If you prefer a static version in `pyproject.toml` instead of dynamic resolution, use the `pep621` version backend:

```yaml
# .vmn/my_app/conf.yml
conf:
  version_backends:
    pep621:
      path: "pyproject.toml"
```

This writes the version directly into `[project].version` on each `vmn stamp`.

### 🔧 Generic Version Backends

For any file format not covered by built-in backends, use `generic_selectors` (regex-based) or `generic_jinja` (Jinja2 template-based):

<details>
<summary><strong>generic_selectors</strong> — regex find-and-replace</summary>

```yaml
version_backends:
  generic_selectors:
    - paths_section:
        - input_file_path: in.txt
          output_file_path: in.txt
          custom_keys_path: custom.yml    # optional
      selectors_section:
        - regex_selector: '(version: )(\d+\.\d+\.\d+)'
          regex_sub: \1{{version}}
        - regex_selector: '(Custom: )([0-9]+)'
          regex_sub: \1{{k1}}
```

- `regex_selector` matches the target text; `regex_sub` defines the replacement
- Use `{{version}}` to inject the stamped version
- Use `{{VMN_VERSION_REGEX}}` as a built-in pattern for matching any vmn-compliant version string ([playground](https://regex101.com/r/JoEvaN/1))

</details>

<details>
<summary><strong>generic_jinja</strong> — Jinja2 template rendering</summary>

```yaml
version_backends:
  generic_jinja:
    - input_file_path: f1.jinja2
      output_file_path: jinja_out.txt
      custom_keys_path: custom.yml    # optional
```

Same template variables as `vmn gen` are available.

</details>

---

## ⚙️ Configuration

`vmn` auto-generates a `conf.yml` file per app (`.vmn/<app-name>/conf.yml`). Edit it to customize behavior:

```yaml
conf:
  template: '[{major}][.{minor}]'
  hide_zero_hotfix: true
  conventional_commits: true
  default_release_mode: optional
  changelog:
    enabled: true
    path: "CHANGELOG.md"
  github_release:
    enabled: true
    draft: false
  deps:
    ../:
      <repo dir name>:
        vcs_type: git
  version_backends:
    npm:
      path: "relative_path/to/package.json"
  policies:
    whitelist_release_branches: ["main"]
```

| Field | Description |
|:------|:------------|
| `template` | Display format for versions. `[{major}][.{minor}]` shows `0.0` instead of `0.0.1`. Use `vmn show --raw` for the full version |
| `hide_zero_hotfix` | Hide the 4th version segment when it's `0` (default: `true`) |
| `conventional_commits` | Enable automatic release mode detection from commit messages |
| `default_release_mode` | `optional` (default) or `strict` — controls how auto-detected mode behaves ([details](#conventional-commits)) |
| `changelog` | `{enabled: true, path: "CHANGELOG.md"}` — generate changelog on stamp ([details](#changelog-generation)) |
| `github_release` | `{enabled: true, draft: false}` — create GitHub Release on stamp ([details](#github-release-creation)) |
| `version_backends` | Auto-embed versions into project files on `vmn stamp` ([details](#-version-auto-embedding)) |
| `deps` | External repo dependencies — vmn tracks them during `stamp` and checks them out during `goto` |
| `policies` | Branch restrictions — `whitelist_release_branches` prevents stamping/releasing from unauthorized branches |
| `extra_info` | Include host/environment metadata in stamp info |
| `create_verinfo_files` | Create version info files (enables `vmn show --from-file`) |


---

## 🔄 CI Integration

Use the official <img src="https://img.shields.io/badge/GitHub%20Action-2088FF?style=flat-square&logo=githubactions&logoColor=white" alt="GitHub Action"> &mdash; [progovoy/vmn-action](https://github.com/progovoy/vmn-action):

```yaml
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0   # recommended for performance; vmn handles shallow clones but will auto-unshallow
  - uses: progovoy/vmn-action@latest
    with:
      app-name: my_app
      do-stamp: true
      stamp-mode: patch
    env:
      GITHUB_TOKEN: ${{ github.token }}
```

---

<p align="center">
  <a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/Contributing-guide-blue?style=for-the-badge" alt="Contributing"></a>
  &nbsp;
  <a href="https://github.com/progovoy/vmn/issues"><img src="https://img.shields.io/badge/Report-Issue-red?style=for-the-badge&logo=github" alt="Report an issue"></a>
  &nbsp;
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/badge/Install-PyPI-3776AB?style=for-the-badge&logo=pypi&logoColor=white" alt="PyPI"></a>
</p>

<p align="center">
  <a href="https://github.com/progovoy/vmn/graphs/contributors"><img src="https://contrib.rocks/image?repo=progovoy/vmn" /></a>
</p>

<h3 align="center">Works with your stack</h3>
<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Node.js-339933?style=for-the-badge&logo=nodedotjs&logoColor=white" alt="Node.js">
  <img src="https://img.shields.io/badge/Rust-000000?style=for-the-badge&logo=rust&logoColor=white" alt="Rust">
  <img src="https://img.shields.io/badge/Go-00ADD8?style=for-the-badge&logo=go&logoColor=white" alt="Go">
  <img src="https://img.shields.io/badge/Java-ED8B00?style=for-the-badge&logo=openjdk&logoColor=white" alt="Java">
  <img src="https://img.shields.io/badge/C++-00599C?style=for-the-badge&logo=cplusplus&logoColor=white" alt="C++">
  <img src="https://img.shields.io/badge/Any_Language-gray?style=for-the-badge" alt="Any language">
</p>

<p align="center">
  <sub>Add the badge to your project:</sub><br>
  <code>[![vmn: automatic versioning](https://img.shields.io/badge/vmn-automatic%20versioning-blue)](https://github.com/progovoy/vmn)</code>
</p>
