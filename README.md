<h1 align="center">🏷️ vmn</h1>
<p align="center"><strong>Automatic semantic versioning, powered by git tags</strong></p>

<p align="center">
  <a href="https://github.com/progovoy/vmn"><img src="https://img.shields.io/badge/vmn-automatic%20versioning-blue" alt="vmn"></a>
  <a href="https://www.repostatus.org/#active"><img src="https://www.repostatus.org/badges/latest/active.svg" alt="Active"></a>
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/dw/vmn" alt="PyPI downloads"></a>
  <a href="#"><img src="https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20windows-brightgreen" alt="Platforms"></a>
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

🚀 [Quick Start](#-quick-start) · ⚖️ [Why vmn?](#%EF%B8%8F-why-vmn) · 🔄 [CI Integration](#-ci-integration) · 📖 [Commands](#-commands) · ⚙️ [Configuration](#%EF%B8%8F-configuration) · 🤝 [Contributing](CONTRIBUTING.md)

---

## 🚀 Quick Start

```sh
# Install
pipx install vmn    # or: pip install vmn / uvx vmn

# Version your app (auto-initializes on first run)
vmn stamp -r patch my_app
# => 0.0.1
```

## ⚖️ Why vmn?

> 💡 **tl;dr** — vmn does what semantic-release/release-please do, but works with *any* language and adds multi-repo tracking, state recovery, and microservice topologies that no competitor offers.

| Capability | vmn | semantic-release | release-please | changesets |
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

## 🔄 CI Integration

Use the official [GitHub Action](https://github.com/progovoy/vmn-action):

```yaml
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0
  - uses: progovoy/vmn-action@latest
    with:
      app-name: my_app
      do-stamp: true
      stamp-mode: patch
    env:
      GITHUB_TOKEN: ${{ github.token }}
```

## ✨ Features

- 🔢 **Version formats** — `1.6.0` / `1.6.0-rc.23` / `1.6.7.4` / `1.6.0-rc.23+build01.Info` ([Semver](https://semver.org) compliant + hotfix extension)
- ⏪ **[State recovery](#vmn-goto)** — `vmn goto` restores the exact repo state for any stamped version
- 🧩 **[Microservice topologies](#root-apps-or-microservices)** — root apps with independent service versions
- 🔗 **[Multi-repo dependencies](#configuration)** — track and lock versions across repositories
- 📦 **[Version auto-embedding](#version-auto-embedding)** — npm, Cargo, pyproject.toml, or any file via regex/jinja2
- 📝 **[Conventional commits](#conventional-commits)** — automatic release mode detection and release notes
- 📋 **[Changelog generation](#configuration)** — built-in CHANGELOG.md output on stamp
- 🚀 **[GitHub Release creation](#configuration)** — optionally create GitHub Releases on stamp
- ⚡ **[uv / hatchling](#hatchling--uv)** — dynamic versioning from git tags via `hatch-vcs`

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

### Install

```sh
pipx install vmn       # recommended
pip install vmn        # alternative
uvx vmn stamp ...      # run without installing
```

### vmn init

```sh
cd to/your/repository
vmn init               # once per repository
```

### vmn init-app

```sh
vmn init-app <app-name>             # starts from 0.0.0
vmn init-app -v 1.6.8 <app-name>   # start from specific version
```

### vmn stamp

```sh
# will stamp 0.0.1
vmn stamp -r patch <app-name>

# will stamp 1.7.0
vmn stamp -r minor <app-name2>
```

### Stamping without `-r`

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

### `-r` vs `--orm`

Both flags specify the release mode (major/minor/patch/hotfix), but they differ in how they handle existing prereleases:

| Flag | Behavior |
|:----:|:---------|
| `-r patch` | **Strict** — always advances the base version. From `0.0.1` → `0.0.2`. From `0.0.2-rc.3` → `0.0.3`. |
| `--orm patch` | **Optional** — advances the base version only if the target version has no existing prereleases. From `0.0.1` → `0.0.2`. From `0.0.1` when `0.0.2-rc.1` already exists → `0.0.2-rc.2` (continues the prerelease instead of bumping). |

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

### vmn release

```sh
# Stamp a prerelease
vmn stamp -r patch --pr rc <app-name>
# outputs: 0.0.1-rc.1

# Release it (promote to final version)
vmn release -v 0.0.1-rc.1 <app-name>
# outputs: 0.0.1

# Or release directly from the prerelease commit
vmn release --stamp <app-name>
```

### vmn show

```sh
# Show current version
vmn show <app-name>
# outputs: 0.0.1

# Show verbose version info (YAML)
vmn show --verbose <app-name>

# Show a specific version's info
vmn show -v 0.0.1 <app-name>
```

### vmn gen

```sh
# Generate a version file from a jinja2 template
vmn gen -t version.j2 -o version.txt <app-name>
```

### vmn goto

```sh
# Checkout the repository state at a specific version
vmn goto -v 0.0.1 <app-name>
```

### vmn add

```sh
# Add build metadata to an existing version
vmn add -v 0.0.1 -b build42 <app-name>
# results in: 0.0.1+build42
```


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

---

## 🔬 Advanced Topics

### 🏗️ Release Candidates

`vmn` supports Semver prerelease versions, letting you iterate on release candidates before promoting to a final release:

```sh
vmn init-app -v 1.6.8 <app-name>

vmn stamp -r major --pr alpha <app-name>    # 2.0.0-alpha.1
vmn stamp --pr alpha <app-name>             # 2.0.0-alpha.2
vmn stamp --pr mybeta <app-name>            # 2.0.0-mybeta.1

vmn release -v 2.0.0-mybeta.1 <app-name>   # 2.0.0 (final)
# or: vmn release --stamp <app-name>
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

### 📄 vmn gen — Template Engine

Generate version files from Jinja2 templates:

```sh
vmn gen -t version.j2 -o version.txt <app-name>
```

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

### 🏗️ vmn add — Build Metadata

Attach build metadata to an existing stamped version:

```sh
vmn add -v 1.0.1 -b build42 <app-name>   # => 1.0.1+build42
```

---

## 🔌 Version Auto-Embedding

`vmn stamp` can automatically write the version string into your project files:

| Backend | File | Description |
|:-------:|:----:|:------------|
| **npm** | `package.json` | Updates `version` field |
| **Cargo** | `Cargo.toml` | Updates `version` field |
| **Poetry** | `pyproject.toml` | Updates `[tool.poetry].version` |
| **PEP 621** | `pyproject.toml` | Updates `[project].version` |

### Hatchling / uv

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

For any file format not covered by built-in backends, use `generic_selectors` (regex-based) or `generic_jinja` (template-based):

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
|:-----:|:------------|
| `template` | Display format for versions. `[{major}][.{minor}]` shows `0.0` instead of `0.0.1`. Use `vmn show --raw` for the full version. |
| `deps` | External repo dependencies — vmn tracks them during `stamp` and checks them out during `goto` |
| `hide_zero_hotfix` | Hide the 4th version segment when it's `0` (default: `true`) |
| `version_backends` | Auto-embed versions into project files on `vmn stamp` |
| `extra_info` | Include host/environment metadata in stamp info |
| `create_verinfo_files` | Create version info files (enables `vmn show --from-file`) |
| `policies` | Branch restrictions — `whitelist_release_branches` prevents stamping/releasing from unauthorized branches |


---

<p align="center">

**[Contributing](CONTRIBUTING.md)** | **[Report an issue](https://github.com/progovoy/vmn/issues)**

</p>

<p align="center">
  <a href="https://github.com/progovoy/vmn/graphs/contributors"><img src="https://contrib.rocks/image?repo=progovoy/vmn" /></a>
</p>

<p align="center">
  Add the badge to your project: <code>[![vmn: automatic versioning](https://img.shields.io/badge/vmn-automatic%20versioning-blue)](https://github.com/progovoy/vmn)</code>
</p>
