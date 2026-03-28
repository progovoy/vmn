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

[Quick Start](#-quick-start) · [Why vmn?](#%EF%B8%8F-why-vmn) · [What makes vmn unique](#-what-makes-vmn-unique) · [Commands](#-commands) · [Auto-Embedding](#-version-auto-embedding) · [Configuration](#%EF%B8%8F-configuration) · [CI](#-ci-integration) · [Contributing](CONTRIBUTING.md)

---

## 🚀 Quick Start

```sh
pip install vmn                 # or: pipx install vmn / uvx vmn

# That's it — vmn auto-initializes on first stamp (no init needed)
vmn stamp -r patch my_app
# => 0.0.1
```

No separate `vmn init` or `vmn init-app` required — `vmn stamp` auto-initializes the repository and app on first run.

> **Shallow clones**: vmn works with shallow repositories (e.g. `git clone --depth 1` or CI's `fetch-depth: 1`). It automatically fetches the missing history it needs. For best performance, prefer a full clone (`fetch-depth: 0` in CI).

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

## ⚖️ Why vmn?

vmn does what semantic-release / release-please do, but works with **any language** and adds capabilities no competitor offers.

| Capability | vmn | semantic-release | release-please | changesets |
|:-----------|:---:|:----------------:|:--------------:|:----------:|
| Language-agnostic | :white_check_mark: | JS-centric | JS-centric | JS-only |
| Git-tag source of truth | :white_check_mark: | :white_check_mark: | :white_check_mark: | :x: |
| Multi-repo dependency tracking | :white_check_mark: | :x: | :x: | :x: |
| State recovery (`vmn goto`) | :white_check_mark: | :x: | :x: | :x: |
| Microservice / root app topology | :white_check_mark: | :x: | :x: | monorepo only |
| 4-segment hotfix versioning | :white_check_mark: | :x: | :x: | :x: |
| Auto-embed version (npm, Cargo, pyproject, any file) | :white_check_mark: | per-plugin | :x: | JS only |
| Conventional commits + changelog | :white_check_mark: | :white_check_mark: | :white_check_mark: | :x: / :white_check_mark: |
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

## 🌟 What makes vmn unique

**State recovery** — `vmn goto -v 1.2.3 my_app` checks out the entire repository (and all tracked dependencies) to the exact state when that version was stamped. No other versioning tool can do this.

**Multi-repo dependency tracking** — vmn records the commit hash of every dependency repo at stamp time. `vmn goto` then restores all of them in parallel, giving you a reproducible snapshot across repositories.

**Microservice topology** — version multiple services under one umbrella (`my_root_app/service1`, `my_root_app/service2`). Each service has its own semver; the root app gets an auto-incrementing integer version on every service stamp. See [Root Apps](#root-apps-microservices).

**Zero lock-in** — all version state lives in git tags and their messages. Remove vmn and your tags still make sense. No config files, databases, or SaaS dependencies required.

**Offline mode** — a local file backend lets you version without a git remote.

**Version formats** — full [Semver 2.0](https://semver.org) plus an optional 4th hotfix segment: `1.6.0` / `1.6.0-rc.23` / `1.6.7.4` / `1.6.0-rc.23+build01.Info`

---

## 📖 Commands

> `init-app` and `stamp` both support `--dry-run` for safe testing.

### vmn stamp

```sh
vmn stamp -r patch <app-name>                 # => 0.0.1
vmn stamp -r minor <app-name>                 # => 0.1.0
vmn stamp -r patch --pr rc <app-name>         # => 0.0.2-rc.1 (prerelease)
vmn stamp --dry-run -r patch <app-name>       # preview without committing
vmn stamp -r patch -e '[skip ci]' <app-name>  # append text to commit message
vmn stamp --pull -r patch <app-name>          # pull before stamping (retries on push conflict)
```

**Behaviors:** idempotent (won't re-stamp if current commit already matches), refuses detached HEAD, auto-initializes repo/app on first run.

#### Stamping without `-r`

Running `vmn stamp <app-name>` without `-r` works **only during a prerelease sequence**. It continues the existing prerelease without changing the base version:

```sh
vmn stamp -r patch --pr rc <app-name>   # 0.0.2-rc.1
vmn stamp --pr rc <app-name>            # 0.0.2-rc.2  (continues prerelease)
vmn stamp <app-name>                    # 0.0.2-rc.3  (still continues)
```

If the current version is a **release** (e.g. `0.0.1`), omitting `-r` errors out — vmn needs to know which segment to bump.
**Exception:** with [`conventional_commits`](#stamp-automation-conventional-commits-changelog-github-releases) enabled, `-r` can always be omitted — the release mode is auto-detected from commit messages.

#### `-r` vs `--orm`

This is an important distinction:

| Flag | Behavior |
|:----:|:---------|
| `-r patch` | **Strict** — always advances the base version. `0.0.1` → `0.0.2`. `0.0.2-rc.3` → `0.0.3`. |
| `--orm patch` | **Optional** — advances only if no prerelease exists at the target. `0.0.1` → `0.0.2`. But if `0.0.2-rc.1` already exists → `0.0.2-rc.2` (continues it instead of bumping). |

`--orm` is useful in CI where you want to bump on new work but continue an existing prerelease series if one is in flight.

<details>
<summary><strong>All stamp flags</strong></summary>

| Flag | Description |
|:-----|:------------|
| `-r`, `--release-mode` | `major` / `minor` / `patch` / `hotfix` (also accepts `micro` as alias for `hotfix`) |
| `--orm`, `--optional-release-mode` | Like `-r` but only advances if no prerelease exists at target version |
| `--pr`, `--prerelease` | Prerelease identifier (e.g. `alpha`, `rc`, `beta.1`). Trailing `.` is auto-stripped |
| `--dry-run` | Preview the version without committing or pushing |
| `--pull` | Pull remote before stamping; retries on push conflict (up to 3 retries, 1-5s delay) |
| `-e`, `--extra-commit-message` | Append text to the stamp commit message (e.g. `[skip ci]`) |
| `--ov`, `--override-version` | Force a specific version string (bypasses release mode logic) |
| `--orv`, `--override-root-version` | Force root app version to a specific integer |
| `--dont-check-vmn-version` | Skip check that the vmn binary is at least as new as the version in metadata |

</details>

#### Stamp automation (conventional commits, changelog, GitHub releases)

All of these are configured per-app in `.vmn/<app-name>/conf.yml`:

**Conventional commits** — auto-detect release mode from commit messages (`fix:` → patch, `feat:` → minor, `BREAKING CHANGE` / `!` → major). With this enabled, `vmn stamp <app-name>` works without `-r`:

```yaml
conf:
  conventional_commits: true
  default_release_mode: optional   # "optional" uses --orm behavior; "strict" uses -r behavior
```

**Changelog** — generate a [Keep a Changelog](https://keepachangelog.com)-formatted `CHANGELOG.md` on each stamp. Requires `conventional_commits: true`. Commits are grouped by type (Features, Bug Fixes, Breaking Changes, etc.):

```yaml
conf:
  conventional_commits: true
  changelog:
    path: "CHANGELOG.md"   # optional, defaults to CHANGELOG.md
```

**GitHub Releases** — create a GitHub Release after pushing tags. Requires the [`gh` CLI](https://cli.github.com/) and `GITHUB_TOKEN` / `GH_TOKEN`. Uses changelog content if available, otherwise lists commits. Prereleases auto-marked. Failures are best-effort (warning, not failure):

```yaml
conf:
  github_release:
    draft: false   # optional, create as draft
```

### vmn release

Promote a prerelease to its final version.

`-v` is optional. Without it, vmn auto-detects the version from the current commit — but **you must be on a version commit**, otherwise it errors. `-v` and `--stamp` are mutually exclusive.

```sh
vmn stamp -r patch --pr rc <app-name>   # => 0.0.1-rc.1

# 1. Explicit version — tag-only, no new commit, works from anywhere
vmn release -v 0.0.1-rc.1 <app-name>   # => 0.0.1

# 2. Auto-detect — omit -v, must be on the prerelease commit (tag-only)
vmn release <app-name>                  # => 0.0.1

# 3. Full stamp flow — new commit + tag + push (runs version backends, changelog, etc.)
vmn release --stamp <app-name>          # => 0.0.1
```

Modes 1 & 2 create a lightweight tag on the original prerelease commit (no new commit). `--stamp` runs the full pipeline (commit + tag + push) but requires branch tip at the prerelease commit.

Idempotent. Cannot release versions with build metadata. `whitelist_release_branches` policy is enforced.

### vmn show

`-v` is optional. Without it, vmn shows the version reachable from the current HEAD:

```sh
vmn show <app-name>                    # current version from HEAD (formatted)
vmn show -v 0.0.1 <app-name>          # show info for a specific version
vmn show --raw <app-name>              # raw version without template formatting
vmn show --verbose <app-name>          # full YAML metadata dump
vmn show --root my_root_app            # show root app version (integer)
vmn show --conf <app-name>             # include configuration
vmn show --from-file <app-name>        # read from file instead of git (faster)
vmn show --type <app-name>             # version type: release / prerelease / metadata
vmn show -u <app-name>                 # unique ID (version+commit_hash)
vmn show -t '[{major}]' <app-name>    # override display template
```

### vmn goto

Checkout the repository (and its dependencies) to the exact state at a stamped version.

`-v` is optional. Without it, vmn uses the first reachable version from the current branch:

```sh
vmn goto <app-name>                        # checkout to latest version on current branch
vmn goto -v 0.0.1 <app-name>              # checkout app + deps to version 0.0.1
vmn goto -v 0.0.1 --deps-only <app-name>  # only checkout dependencies
vmn goto -v 5 --root my_root_app          # checkout to root app version
vmn goto --pull -v 0.0.1 <app-name>       # pull from remote before checkout
```

Dependencies are cloned automatically if missing (up to 10 in parallel) and checked out to the exact hash recorded at stamp time.

### vmn gen

Generate a version file from a Jinja2 template.

`-v` is optional. Without it, vmn uses the version at the current HEAD:

```sh
vmn gen -t version.j2 -o version.txt <app-name>               # uses current HEAD version
vmn gen -t version.j2 -o version.txt -v 1.0.0 <app-name>     # generate for a specific version
vmn gen -t notes.j2 -o notes.txt -c custom.yml <app-name>     # merge custom YAML values
vmn gen -t notes.j2 -o notes.txt --verify-version <app-name>  # fail if repo is dirty
```

Output is idempotent. See [Template Variables](#template-variables-for-vmn-gen) for available Jinja2 variables.

### vmn add

Attach build metadata to an existing stamped version.

`-v` is optional. Without it, vmn auto-detects from the current commit — but **you must be on a version commit**, otherwise it errors:

```sh
vmn add --bm build42 <app-name>                                    # auto-detect from current commit
vmn add -v 0.0.1 --bm build42 <app-name>                          # => 0.0.1+build42
vmn add -v 0.0.1 --bm build42 --vmp metadata.yml <app-name>       # attach YAML metadata
vmn add -v 0.0.1 --bm build42 --vmu https://ci/build/42 <app-name> # attach URL metadata
```

Idempotent. Cannot add metadata to a version that already has different metadata.

### vmn config

Interactive TUI for editing app configuration:

```sh
vmn config <app-name>           # TUI editor
vmn config <app-name> --vim     # open in $EDITOR instead
vmn config                      # list all managed apps
vmn config --global             # edit repo-level .vmn/conf.yml
vmn config <app-name> --root    # edit root app config
```

The TUI supports most config fields with validation. `changelog` and `github_release` are not yet TUI-editable — use `--vim`. Falls back to `--vim` if no TTY.

### vmn init / init-app

Usually not needed — `vmn stamp` auto-initializes. Use for explicit control.

`-v` defaults to `0.0.0` for `init-app`:

```sh
vmn init                            # initialize vmn in a repository
vmn init-app <app-name>             # initialize an app (starts from 0.0.0)
vmn init-app -v 1.6.8 <app-name>   # start from a specific version
vmn init-app --dry-run <app-name>   # preview without making changes
vmn init-app --orm strict <app-name> # set default_release_mode to strict
```

### Python library

```python
from contextlib import redirect_stdout, redirect_stderr
import io, version_stamp.vmn as vmn

out, err = io.StringIO(), io.StringIO()
with redirect_stdout(out), redirect_stderr(err):
    ret, vmn_ctx = vmn.vmn_run(["show", "vmn"])
```

### Environment variables

| Variable | Description |
|:---------|:------------|
| `VMN_WORKING_DIR` | Override working directory |
| `VMN_LOCK_FILE_PATH` | Custom lock file path (default: per-repo) |
| `GITHUB_TOKEN` / `GH_TOKEN` | Required for [GitHub Releases](#stamp-automation-conventional-commits-changelog-github-releases) |

---

## 🏗️ Release Candidates

Iterate on prereleases before promoting to a final release:

```sh
vmn init-app -v 1.6.8 <app-name>

vmn stamp -r major --pr alpha <app-name>    # 2.0.0-alpha.1
vmn stamp --pr alpha <app-name>             # 2.0.0-alpha.2
vmn stamp --pr mybeta <app-name>            # 2.0.0-mybeta.1

vmn release -v 2.0.0-mybeta.1 <app-name>   # 2.0.0 (tag only)
# or: vmn release --stamp <app-name>      # 2.0.0 (full stamp flow)
```

## 🧩 Root Apps (Microservices)

Version multiple services under one umbrella. Each service has its own semver; the root app gets an auto-incrementing integer version on every service stamp:

```sh
vmn init-app my_root_app/service1
vmn init-app my_root_app/service2

vmn stamp -r patch my_root_app/service1   # service1 => 0.0.1, root => 1
vmn stamp -r patch my_root_app/service2   # service2 => 0.0.1, root => 2

vmn show my_root_app/service1             # => 0.0.1
vmn show --root my_root_app               # => 2
```

<details>
<summary>Example <code>vmn show --verbose</code> output</summary>

```yaml
stamping:
  app:
    name: my_root_app/service2
    _version: 0.0.1
    release_mode: patch
    stamped_on_branch: master
    changesets:
      .:
        hash: 8bbeb8a...
        remote: <remote url>
        vcs_type: git
  root_app:
    name: my_root_app
    version: 2
    latest_service: my_root_app/service2
    services:
      my_root_app/service1: 0.0.1
      my_root_app/service2: 0.0.1
```

</details>

## Template Variables for `vmn gen`

<details>
<summary>Available variables and example</summary>

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

**Template** (`version.j2`):
```text
VERSION: {{version}}
NAME: {{name}}
BRANCH: {{stamped_on_branch}}
{% for k,v in changesets.items() %}
REPO: {{k}} | HASH: {{v.hash}} | REMOTE: {{v.remote}}
{% endfor %}
```

</details>

---

## 🔌 Version Auto-Embedding

`vmn stamp` can automatically write the version into your project files:

| Backend | File | What it updates |
|:--------|:-----|:----------------|
| npm | `package.json` | `version` field |
| Cargo | `Cargo.toml` | `version` field |
| Poetry | `pyproject.toml` | `[tool.poetry].version` |
| PEP 621 | `pyproject.toml` | `[project].version` |

<details>
<summary><strong>Hatchling / uv — dynamic versioning from git tags</strong></summary>

Use [hatch-vcs](https://github.com/ofek/hatch-vcs) to read vmn's tags directly (zero file injection). Works with multiple apps per repo.

```sh
uv add --dev hatch-vcs   # or: pip install hatch-vcs
```

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "my-package"
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"
tag-pattern = "my_app_(?P<version>.*)"    # replace my_app with your app name
# For root apps: "my_root_app-service1_(?P<version>.*)"  (/ becomes -)
```

Or use the `pep621` backend to write a static version into `[project].version` on each stamp instead.

</details>

<details>
<summary><strong>Generic backends — regex or Jinja2 for any file format</strong></summary>

**generic_selectors** — regex find-and-replace:

```yaml
version_backends:
  generic_selectors:
    - paths_section:
        - input_file_path: in.txt
          output_file_path: in.txt
      selectors_section:
        - regex_selector: '(version: )(\d+\.\d+\.\d+)'
          regex_sub: \1{{version}}
```

Use `{{VMN_VERSION_REGEX}}` to match any vmn version string ([playground](https://regex101.com/r/JoEvaN/1)).

**generic_jinja** — Jinja2 template rendering:

```yaml
version_backends:
  generic_jinja:
    - input_file_path: f1.jinja2
      output_file_path: jinja_out.txt
      custom_keys_path: custom.yml    # optional
```

Same variables as `vmn gen`.

</details>

---

## ⚙️ Configuration

vmn auto-generates `.vmn/<app-name>/conf.yml` per app. Full example with inline docs:

```yaml
conf:
  template: '[{major}][.{minor}]'       # display format ({major}, {minor}, {patch}, {hotfix}, {prerelease}, {rcn}, {buildmetadata})
  hide_zero_hotfix: true                 # hide 4th segment when 0 (default: true)
  conventional_commits: true             # auto-detect release mode from commits
  default_release_mode: optional         # "optional" (--orm) or "strict" (-r) for auto-detected mode
  changelog:
    path: "CHANGELOG.md"                 # generate changelog on stamp (presence enables it)
  github_release:
    draft: false                         # create GitHub Release on stamp (presence enables it)
  deps:                                  # multi-repo dependencies — tracked on stamp, restored on goto
    ../:
      <repo dir name>:
        vcs_type: git
  version_backends:                      # auto-embed version into project files
    npm:
      path: "relative_path/to/package.json"
  policies:
    whitelist_release_branches: ["main"] # restrict which branches can stamp/release
  extra_info: false                      # include host/environment metadata in stamp
  create_verinfo_files: false            # enable vmn show --from-file
```

Use `vmn config <app-name>` for a TUI editor, or edit YAML directly.

---

## 🔄 CI Integration

Use the official GitHub Action — [progovoy/vmn-action](https://github.com/progovoy/vmn-action):

```yaml
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0   # recommended; vmn handles shallow clones but full is faster
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

<p align="center">
  <sub>Add the badge to your project:</sub><br>
  <code>[![vmn: automatic versioning](https://img.shields.io/badge/vmn-automatic%20versioning-blue)](https://github.com/progovoy/vmn)</code>
</p>
