<h1 align="center">vmn</h1>
<p align="center"><strong>One command. Any language. Versions that live in git — not in your way.</strong></p>

<p align="center">
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/v/vmn?logo=pypi&logoColor=white&label=PyPI" alt="PyPI version"></a>
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/dw/vmn?logo=pypi&logoColor=white" alt="PyPI downloads"></a>
  <a href="https://github.com/progovoy/vmn"><img src="https://img.shields.io/github/stars/progovoy/vmn?style=flat&logo=github" alt="GitHub stars"></a>
  <a href="https://semver.org"><img src="https://img.shields.io/badge/semver-2.0.0-blue?logo=semver&logoColor=white" alt="Semver"></a>
  <a href="https://conventionalcommits.org"><img src="https://img.shields.io/badge/Conventional%20Commits-1.0.0-%23FE5196?logo=conventionalcommits&logoColor=white" alt="Conventional Commits"></a>
  <a href="https://github.com/progovoy/vmn/blob/master/LICENSE"><img src="https://img.shields.io/github/license/progovoy/vmn" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-3776AB?logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20windows-brightgreen" alt="Platforms">
</p>

---

```sh
pip install vmn

vmn stamp -r minor my_app              # => 0.1.0
vmn stamp -r patch --pr rc my_app      # => 0.1.1-rc.1
vmn release my_app                     # => 0.1.1
vmn goto -v 0.1.0 my_app              # entire repo + deps restored to 0.1.0
```

That last line? **No other versioning tool can do that.**

---

[Why vmn?](#why-vmn) · [Only in vmn](#what-only-vmn-can-do) · [Commands](#commands) · [Auto-Embedding](#version-auto-embedding) · [Configuration](#configuration) · [CI](#ci-integration) · [Migration](#already-using-another-tool) · [Contributing](CONTRIBUTING.md)

---

### vmn is for you if:

- You version projects in **Python, Rust, Go, C++, Java** — or any language (not just JavaScript)
- You manage **microservices** and need coordinated versions across services
- You work across **multiple repos** and need reproducible cross-repo snapshots
- You're tired of **configuring plugins** for semantic-release or release-please
- You want versions stored in **pure git tags** — zero lock-in, zero databases, zero SaaS
- You need to work **offline**, in air-gapped environments, or without CI

No separate `vmn init` required — `vmn stamp` auto-initializes on first run. Works with shallow clones (`fetch-depth: 1`).

<details>
<summary><strong>Try it locally (playground)</strong></summary>

```sh
pip install vmn

mkdir remote && cd remote && git init --bare && cd ..
git clone ./remote ./local && cd local
echo a >> ./a.txt && git add ./a.txt && git commit -m "first commit" && git push origin master

vmn stamp -r patch my_app   # => 0.0.1

echo b >> ./a.txt && git add ./a.txt && git commit -m "feat: add b" && git push origin master
vmn stamp -r patch my_app   # => 0.0.2
```

</details>

---

## Why vmn?

vmn does everything semantic-release and release-please do — plus **6 things nothing else can**.

| Capability | vmn | semantic-release | release-please | changesets |
|:-----------|:---:|:----------------:|:--------------:|:----------:|
| Language-agnostic | :white_check_mark: | JS-centric | JS-centric | JS-only |
| Git-tag source of truth | :white_check_mark: | :white_check_mark: | :white_check_mark: | :x: |
| Conventional commits + changelog | :white_check_mark: | :white_check_mark: | :white_check_mark: | :x: / :white_check_mark: |
| GitHub Release creation | :white_check_mark: | :white_check_mark: | :white_check_mark: | :x: |
| Auto-embed version (npm, Cargo, pyproject, any file) | :white_check_mark: | per-plugin | :x: | JS only |
| **Multi-repo dependency tracking** | :white_check_mark: | :x: | :x: | :x: |
| **State recovery (`vmn goto`)** | :white_check_mark: | :x: | :x: | :x: |
| **Microservice / root app topology** | :white_check_mark: | :x: | :x: | monorepo only |
| **4-segment hotfix versioning** | :white_check_mark: | :x: | :x: | :x: |
| **Zero-config start (auto-init)** | :white_check_mark: | :x: | :x: | :x: |
| **Offline / local file backend** | :white_check_mark: | :x: | :x: | :x: |
| **Zero lock-in (pure git tags)** | :white_check_mark: | :x: | :x: | :x: |

> **Bold rows = only vmn.** That's the moat.

<details>
<summary>Detailed comparisons & migration guides</summary>

- [vmn vs semantic-release](docs/vmn-vs-semantic-release.md)
- [vmn vs release-please](docs/vmn-vs-release-please.md)
- [vmn vs setuptools-scm](docs/vmn-vs-setuptools-scm.md)
- [Migrating from standard-version](docs/migrating-from-standard-version.md)
- [Migrating from bump2version](docs/migrating-from-bump2version.md)

</details>

---

## What only vmn can do

### State recovery — a time machine for your repo

Your QA team reports a bug in v1.2.3. Instead of digging through `git log`, you run one command:

```sh
vmn goto -v 1.2.3 my_app
```

Your entire repository — **plus every tracked dependency** — is now at exactly the state when 1.2.3 shipped. Reproduce the bug in seconds, not hours. No other versioning tool offers this.

### Multi-repo snapshots — reproducible builds across repositories

If your product spans multiple git repos, vmn records the exact commit hash of every dependency at stamp time. `vmn goto` restores all of them in parallel:

```sh
# stamp records: my_app @ abc123, lib_core @ def456, lib_utils @ 789fed
vmn stamp -r minor my_app

# six months later — restore everything to that exact state
vmn goto -v 0.1.0 my_app    # all 3 repos checked out to their recorded commits
```

### Microservice topology — one umbrella, independent versions

Version multiple services under one root app. Each service has its own semver; the root app gets an auto-incrementing integer on every service stamp:

```sh
vmn stamp -r patch my_platform/auth      # auth => 0.0.1, root => 1
vmn stamp -r minor my_platform/billing   # billing => 0.1.0, root => 2
vmn stamp -r patch my_platform/auth      # auth => 0.0.2, root => 3

vmn show --root my_platform              # => 3 (latest root version)
```

### Zero lock-in — it's just git tags

All version state lives in annotated git tag messages. Uninstall vmn tomorrow and your tags still make perfect sense. No config files, databases, or SaaS dependencies hold your versions hostage.

### Version formats — full semver plus hotfix

Standard [Semver 2.0](https://semver.org) plus an optional 4th hotfix segment for when you need it:

`1.6.0` · `1.6.0-rc.23` · `1.6.7.4` · `1.6.0-rc.23+build01.Info`

---

## Commands

> `init-app` and `stamp` both support `--dry-run` for safe testing.

| Command | What it does | Example |
|:--------|:-------------|:--------|
| `vmn stamp` | Create a new version | `vmn stamp -r patch my_app` |
| `vmn release` | Promote prerelease to final | `vmn release my_app` |
| `vmn show` | Display version info | `vmn show my_app` |
| `vmn goto` | Checkout repo at a version | `vmn goto -v 1.2.3 my_app` |
| `vmn gen` | Generate file from template | `vmn gen -t ver.j2 -o ver.txt my_app` |
| `vmn add` | Attach build metadata | `vmn add -v 1.0.0 --bm build42 my_app` |
| `vmn config` | Edit app config (TUI) | `vmn config my_app` |
| `vmn init` | Initialize repo/app | `vmn stamp` auto-inits — rarely needed |

### vmn stamp

```sh
vmn stamp -r patch my_app                 # => 0.0.1
vmn stamp -r minor my_app                 # => 0.1.0
vmn stamp -r patch --pr rc my_app         # => 0.0.2-rc.1 (prerelease)
vmn stamp my_app                          # => 0.0.3 (with conventional_commits — no -r needed)
vmn stamp --dry-run -r patch my_app       # preview without committing
vmn stamp --pull -r patch my_app          # pull before stamping (retries on conflict)
```

Idempotent (won't re-stamp if current commit already matches). Auto-initializes repo/app on first run.

<details>
<summary><strong>Stamping without <code>-r</code>, <code>-r</code> vs <code>--orm</code>, and all flags</strong></summary>

**Without `-r`:** works **only during a prerelease sequence** — continues the existing prerelease. If the current version is a release, omitting `-r` errors out. **Exception:** with [`conventional_commits`](#stamp-automation-conventional-commits-changelog-github-releases) enabled, `-r` can always be omitted.

```sh
vmn stamp -r patch --pr rc my_app   # 0.0.2-rc.1
vmn stamp --pr rc my_app            # 0.0.2-rc.2  (continues)
vmn stamp my_app                    # 0.0.2-rc.3  (still continues)
```

**`-r` vs `--orm`:**

| Flag | Behavior |
|:----:|:---------|
| `-r patch` | **Strict** — always advances. `0.0.1` -> `0.0.2`. `0.0.2-rc.3` -> `0.0.3`. |
| `--orm patch` | **Optional** — advances only if no prerelease exists at target. `0.0.2-rc.1` exists -> `0.0.2-rc.2`. |

`--orm` is useful in CI to bump on new work but continue an existing prerelease series.

**All flags:**

| Flag | Description |
|:-----|:------------|
| `-r`, `--release-mode` | `major` / `minor` / `patch` / `hotfix` (also `micro` for hotfix) |
| `--orm`, `--optional-release-mode` | Like `-r` but only advances if no prerelease at target |
| `--pr`, `--prerelease` | Prerelease identifier (e.g. `alpha`, `rc`, `beta.1`) |
| `--dry-run` | Preview without committing or pushing |
| `--pull` | Pull remote first; retries on push conflict (3 retries, 1-5s delay) |
| `-e`, `--extra-commit-message` | Append text to commit message (e.g. `[skip ci]`) |
| `--ov`, `--override-version` | Force a specific version string |
| `--orv`, `--override-root-version` | Force root app version to a specific integer |
| `--dont-check-vmn-version` | Skip vmn binary version check |

**`vmn init-app` flags:**

| Flag | Description |
|:-----|:------------|
| `-v`, `--version` | Version to start from (default: `0.0.0`) |
| `--dry-run` | Preview without committing |
| `--orm`, `--default-release-mode` | Set `default_release_mode` in app config: `optional` (default) or `strict` |


</details>

#### Stamp automation (conventional commits, changelog, GitHub releases)

Enable `conventional_commits` and **never type `-r` again** — vmn reads your commit messages (`fix:` → patch, `feat:` → minor, `BREAKING CHANGE` / `!` → major) and picks the release mode automatically:

```sh
# with conventional_commits enabled:
git commit -m "feat: add search endpoint"
vmn stamp my_app    # => 0.2.0 (minor, auto-detected from "feat:")
```

Configure per-app in `.vmn/<app-name>/conf.yml`:

```yaml
conf:
  conventional_commits: true             # auto-detect release mode — no -r flag needed
  default_release_mode: optional         # "optional" (--orm behavior) or "strict" (-r behavior)

  changelog:                             # generate CHANGELOG.md on each stamp (requires conventional_commits)
    path: "CHANGELOG.md"

  github_release:                        # create GitHub Release after push (requires gh CLI + GITHUB_TOKEN)
    draft: false
```

### vmn release

Promote a prerelease to its final version. Three modes:

```sh
vmn release -v 0.0.1-rc.1 my_app   # explicit version — tag-only, works from anywhere
vmn release my_app                  # auto-detect from current commit (must be on version commit)
vmn release --stamp my_app          # full stamp flow — new commit + tag + push
```

Idempotent. `-v` and `--stamp` are mutually exclusive.

### vmn show

```sh
vmn show my_app                    # current version from HEAD
vmn show -v 0.0.1 my_app          # specific version info
vmn show --verbose my_app          # full YAML metadata dump
vmn show --raw my_app              # without template formatting
vmn show --root my_root_app        # root app version (integer)
vmn show --type my_app             # release / prerelease / metadata
vmn show -u my_app                 # unique ID (version+commit_hash)
vmn show -t '[{major}]' my_app    # override display template
vmn show --conf my_app             # show app configuration
vmn show --ignore-dirty my_app     # ignore dirty working tree
vmn show --from-file my_app        # read from local verinfo file (requires create_verinfo_files)
```

### vmn goto

Checkout the repo (and all tracked dependencies) to the exact state at a version:

```sh
vmn goto -v 1.2.3 my_app              # repo + deps restored to version 1.2.3
vmn goto my_app                        # latest version on current branch
vmn goto -v 1.2.3 --deps-only my_app  # only checkout dependencies
vmn goto -v 5 --root my_root_app      # checkout to root app version
vmn goto --pull -v 1.2.3 my_app       # pull remote before checking out
```

Dependencies are auto-cloned if missing (up to 10 in parallel).

### vmn gen

Generate a version file from a Jinja2 template:

```sh
vmn gen -t version.j2 -o version.txt my_app           # current HEAD version
vmn gen -t version.j2 -o version.txt -v 1.0.0 my_app  # specific version
vmn gen -t version.j2 -o version.txt -c custom.yml my_app  # with custom template values
vmn gen -t version.j2 -o version.txt --verify-version my_app  # verify version exists
```

See [Template Variables](#template-variables-for-vmn-gen) for available Jinja2 variables.

### vmn add

Attach build metadata to an existing version:

```sh
vmn add -v 0.0.1 --bm build42 my_app                    # => 0.0.1+build42
vmn add -v 0.0.1 --bm build42 --vmp meta.yml my_app     # attach metadata file
vmn add -v 0.0.1 --bm build42 --vmu https://ci/42 my_app  # attach metadata URL
```

### vmn config

```sh
vmn config                  # list all managed apps in the repo
vmn config my_app           # interactive TUI editor
vmn config my_app --vim     # open in $EDITOR
vmn config --branch my_app  # edit/create branch-specific config for current branch
vmn config --root my_app    # edit root app config (root_conf.yml)
vmn config --global         # repo-level .vmn/conf.yml
```

### vmn init / init-app

Usually not needed — `vmn stamp` auto-initializes. Use for explicit control:

```sh
vmn init-app my_app             # starts from 0.0.0
vmn init-app -v 1.6.8 my_app   # start from a specific version
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

## Release candidates

Iterate on prereleases, then promote:

```sh
vmn stamp -r major --pr alpha my_app    # 2.0.0-alpha.1
vmn stamp --pr alpha my_app             # 2.0.0-alpha.2
vmn stamp --pr mybeta my_app            # 2.0.0-mybeta.1
vmn release my_app                      # 2.0.0
```

<details>
<summary><strong>Template variables for <code>vmn gen</code></strong></summary>

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

**Example template** (`version.j2`):
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

## Version auto-embedding

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

## Configuration

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

### Per-branch configuration

vmn supports branch-specific config overrides. Place a file named `<branch>_conf.yml` next to the default `conf.yml` in `.vmn/<app-name>/`:

```
.vmn/my_app/
  conf.yml              # fallback when no branch-specific file exists
  feature-x_conf.yml    # used when on branch "feature-x"
```

When vmn loads configuration it checks for `<active_branch>_conf.yml` first; if that file exists it is used instead of `conf.yml`. The same applies to root app configs (`<branch>_root_conf.yml` vs `root_conf.yml`).

During `vmn stamp`, branch-specific config files from other branches are automatically cleaned up so they don't accumulate in the repository.


---

## CI integration

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

## Already using another tool?

Migration takes 5 minutes:

- [Migrating from semantic-release](docs/vmn-vs-semantic-release.md)
- [Migrating from release-please](docs/vmn-vs-release-please.md)
- [Migrating from setuptools-scm](docs/vmn-vs-setuptools-scm.md)
- [Migrating from standard-version](docs/migrating-from-standard-version.md)
- [Migrating from bump2version](docs/migrating-from-bump2version.md)

---

<h3 align="center">Ready to stop fighting your versioning tools?</h3>

```sh
pip install vmn
```

<p align="center">
  Star the repo if vmn saved you time. <a href="https://github.com/progovoy/vmn/issues">File an issue</a> if it didn't — we'll fix it.
</p>

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
