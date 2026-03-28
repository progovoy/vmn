# vmn — Automatic Semantic Versioning

[![vmn: automatic versioning](https://img.shields.io/badge/vmn-automatic%20versioning-blue)](https://github.com/progovoy/vmn)
[![Project Status: Active](https://www.repostatus.org/badges/latest/active.svg)](https://www.repostatus.org/#active)
[![PyPI downloads](https://img.shields.io/pypi/dw/vmn)](https://pypi.org/project/vmn/)
[![Platforms](https://img.shields.io/badge/vmn-linux%20%7C%20macos%20%7C%20windows%20-brightgreen)](#)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-%23FE5196?logo=conventionalcommits&logoColor=white)](https://conventionalcommits.org)

Language-agnostic, git-tag-based semantic versioning for any project. Supports monorepos, multi-repo dependencies, microservice topologies, release candidates, and conventional commits.

## Quick Start

```sh
# Install
pipx install vmn    # or: pip install vmn / uvx vmn

# Version your app (auto-initializes on first run)
vmn stamp -r patch my_app
# => 0.0.1
```

## Why vmn?

| Capability | vmn | semantic-release | release-please | changesets |
|:-----------|:---:|:----------------:|:--------------:|:----------:|
| Language-agnostic | Y | JS-centric | JS-centric | JS-only |
| Git-tag source of truth | Y | Y | Y | N |
| Multi-repo dependency tracking | Y | N | N | N |
| State recovery (`vmn goto`) | Y | N | N | N |
| Microservice / root app topology | Y | N | N | monorepo only |
| 4-segment hotfix versioning | Y | N | N | N |
| Version auto-embedding (npm, Cargo, pyproject, any file) | Y | per-plugin | N | JS only |
| Conventional commits | Y | Y | Y | N |
| Changelog generation | Y | Y | Y | Y |
| GitHub Release creation | Y | Y | Y | N |
| Offline / local file backend | Y | N | N | N |
| Zero lock-in (pure git tags) | Y | N | N | N |

See also: [vmn vs semantic-release](docs/vmn-vs-semantic-release.md) | [vmn vs release-please](docs/vmn-vs-release-please.md) | [vmn vs setuptools-scm](docs/vmn-vs-setuptools-scm.md)

Migrating? [from standard-version](docs/migrating-from-standard-version.md) | [from bump2version](docs/migrating-from-bump2version.md)

## CI Integration

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

# Try It Out

```sh
pip install vmn

# Create a playground repo
mkdir remote && cd remote && git init --bare && cd ..
git clone ./remote ./local && cd local
echo a >> ./a.txt && git add ./a.txt && git commit -m "first commit" && git push origin master

# Stamp your first version
vmn stamp -r patch my_app
# => 0.0.1

# Make a change and stamp again
echo b >> ./a.txt && git add ./a.txt && git commit -m "feat: add b" && git push origin master
vmn stamp -r patch my_app
# => 0.0.2
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and running tests.

## Features

- `major.minor.patch` versioning, e.g., `1.6.0` (Semver compliant)
- Prerelease versions, e.g., `1.6.0-rc.23` (Semver compliant)
- Hotfix versions (4th segment), e.g., `1.6.7.4` (Semver extension)
- Build metadata, e.g., `1.6.0-rc.23+build01.Info` (Semver compliant)
- [State recovery](#vmn-goto) — `vmn goto` restores exact repo state for any stamped version
- [Microservice topologies](#root-apps-or-microservices) — root apps with independent service versions
- [Multi-repo dependencies](#configuration) — track versions across repositories
- [Version auto-embedding](#version-auto-embedding) — npm, Cargo, pyproject.toml, or any file
- [Conventional commits](#conventional-commits) — automatic release mode detection and release notes
- [Changelog generation](#configuration) — built-in CHANGELOG.md output
- [GitHub Release creation](#configuration) — create releases on stamp
- [uv / hatchling](#hatchling--uv) — dynamic versioning from git tags via `hatch-vcs`

# Usage

`init-app` and `stamp` both support `--dry-run` flag for testing purposes.

## Install

```sh
pipx install vmn       # recommended
# or
pip install vmn
# or
uvx vmn stamp ...      # run without installing
```

## 1. `vmn init`

```sh
cd to/your/repository
## Needed only once per repository.
vmn init
```

## 2. `vmn init-app`

```sh
## Needed only once per app-name
# will start from 0.0.0
vmn init-app <app-name>

# example for starting from version 1.6.8
vmn init-app -v 1.6.8 <app-name2>
```

## 3. `vmn stamp`

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
  conventional_commits:
    enabled: true
```

`vmn` scans commits since the last stamp and picks the highest release mode based on conventional commit types: `fix` → patch, `feat` → minor, `BREAKING CHANGE` or `!` → major.

`default_release_mode` controls which stamping behavior is used for the auto-detected mode:

| Value | Equivalent flag | Behavior |
|:-----:|:---------------:|:---------|
| `optional` (default) | `--orm` | Only advances the base version if no prerelease already exists for the target version. If a prerelease exists, continues from it. |
| `strict` | `-r` | Always advances the base version unconditionally. |

Now you can run `vmn stamp <app-name>` and `vmn` will deduce the proper release mode automatically.

## 4. `vmn release`

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

## 5. `vmn show`

```sh
# Show current version
vmn show <app-name>
# outputs: 0.0.1

# Show verbose version info (YAML)
vmn show --verbose <app-name>

# Show a specific version's info
vmn show -v 0.0.1 <app-name>
```

## 6. `vmn gen`

```sh
# Generate a version file from a jinja2 template
vmn gen -t version.j2 -o version.txt <app-name>
```

## 7. `vmn goto`

```sh
# Checkout the repository state at a specific version
vmn goto -v 0.0.1 <app-name>
```

## 8. `vmn add`

```sh
# Add build metadata to an existing version
vmn add -v 0.0.1 -b build42 <app-name>
# results in: 0.0.1+build42
```


## Other usages

### You can also use vmn as a python lib by importing it

``` python
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

explore `vmn_ctx` object to see what you can get from it. Vars starting with `_` are private and may change with time

## Supported env vars

`VMN_WORKING_DIR` - Set it and `vmn` will run from this directory

`VMN_LOCK_FILE_PATH` - Set this to make `vmn` use this lockfile
  when it runs. The default is to use a lock file per repo to avoid running multiple `vmn` commands simultaneously.

# Detailed Documentation

## vmn init

Initialize `vmn` tracking in a git repository. Run once per repository.

```sh
vmn init
```

This creates a `.vmn/` directory and an initial tracking tag in the repository.

## vmn init-app

Initialize a new application for version tracking. Run once per app.

```sh
vmn init-app <app-name>

# Start from a specific version
vmn init-app -v 1.0.0 <app-name>

# Dry run (no changes)
vmn init-app --dry-run <app-name>
```

## vmn stamp

### release candidates

`vmn` supports `Semver`'s `prerelease` notion of version stamping, enabling you to release non-mature versions and only
then release the final version.

```sh
# will start from 1.6.8
vmn init-app -v 1.6.8 <app-name>

# will stamp 2.0.0-alpha1
vmn stamp -r major --pr alpha <app-name>

# will stamp 2.0.0-alpha2
vmn stamp --pr alpha <app-name>

# will stamp 2.0.0-mybeta1
vmn stamp --pr mybeta <app-name>

# Run release when you ready - will stamp 2.0.0 (from the same commit)
vmn release -v 2.0.0-mybeta1 <app-name>

# Or release directly from the prerelease commit using --stamp
vmn release --stamp <app-name>
```

### "root apps" or microservices

`vmn` supports stamping of something called a "root app" which can be useful for managing version of multiple services
that are logically located under the same solution.

### Example

```sh
vmn init-app my_root_app/service1
vmn stamp -r patch my_root_app/service1
```

```sh
vmn init-app my_root_app/service2
vmn stamp -r patch my_root_app/service2
```

```sh
vmn init-app my_root_app/service3
vmn stamp -r patch my_root_app/service3
```

Next we'll be able to use `vmn show` to display everything we need:

`vmn show --verbose my_root_app/service3`

```yml
vmn_info:
  description_message_version: '1'
  vmn_version: <the version of vmn itself that has stamped the application>
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

`vmn show my_root_app/service3` will output `0.0.1`

`vmn show --root my_root_app` will output `5`

## vmn release

Promote a prerelease stamped with `vmn stamp` to a final release.
Use `-v`/`--version` to specify the prerelease version or
`--stamp` to release the most recently stamped prerelease.

```sh
# Run release when you ready - will stamp 2.0.0 (from the same commit)
vmn release -v 2.0.0-mybeta1 <app-name>

# Or release directly from the prerelease commit using --stamp
vmn release --stamp <app-name>
```

## vmn show

Use `vmn show` for displaying version information of previous `vmn stamp` commands

```sh
vmn show <app-name>
vmn show --verbose <app-name>
vmn show -v 1.0.1 <app-name>
```

## vmn goto

Similar to `git checkout` but also supports checking out all configured dependencies. This way you can easily go back to
the **exact** state of you entire code for a specific version even when multiple git repositories are involved.

```sh
vmn goto -v 1.0.1 <app-name>
```

## vmn gen

Generates version output file based on jinja2 template

`vmn gen -t path/to/jinja_template.j2 -o path/to/output.txt app_name`

### Available jinja2 keywords

```json
{
 "_version": "0.0.1",
 "base_version": "0.0.1",
 "changesets": {".": {"hash": "d6377170ae767cd025f6c623b838c7a99efbe7f8",
                      "remote": "../test_repo_remote",
                      "state": ["modified"],
                      "vcs_type": "git"}},
 "info": {},
 "name": "test_app2/s1",
 "prerelease": "release",
 "prerelease_count": {},
 "previous_version": "0.0.0",
 "release_mode": "patch",
 "stamped_on_branch": "main",
 "version": "0.0.1",
 "root_latest_service": "test_app2/s1",
 "root_name": "test_app2",
 "root_services": 
 {
   "test_app2/s1": "0.0.1"
 }, 
 "root_version": 1,
  "release_notes": ""
}
```

#### `vmn gen` jinja template example

``` text
"VERSION: {{version}} \n" \
"NAME: {{name}} \n" \
"BRANCH: {{stamped_on_branch}} \n" \
"RELEASE_MODE: {{release_mode}} \n" \
"{% for k,v in changesets.items() %} \n" \
"    <h2>REPO: {{k}}\n" \
"    <h2>HASH: {{v.hash}}</h2> \n" \
"    <h2>REMOTE: {{v.remote}}</h2> \n" \
"    <h2>VCS_TYPE: {{v.vcs_type}}</h2> \n" \
"{% endfor %}\n"
```

#### `vmn gen` output example

``` text
VERSION: 0.0.1
NAME: test_app2/s1
BRANCH: master
RELEASE_MODE: patch

    <h2>REPO: .
    <h2>HASH: ef4c6f4355d0190e4f516230f65a79ec24fc7396</h2>
    <h2>REMOTE: ../test_repo_remote</h2>
    <h2>VCS_TYPE: git</h2>
```

## vmn add

Use `vmn add` to attach build metadata to an existing stamped version. This is useful for recording CI build numbers, commit hashes, or other identifiers.

```sh
vmn add -v 1.0.1 -b build42 <app-name>
# results in: 1.0.1+build42
```

## Version auto-embedding

`vmn` supports auto-embedding the version string during the `vmn stamp` phase for supported backends:

| Backend | File | Description |
|:-------:|:----:|:------------|
| npm | `package.json` | Embeds version string into `package.json` during `vmn stamp` |
| Cargo | `Cargo.toml` | Embeds version string into `Cargo.toml` during `vmn stamp` |
| Poetry | `pyproject.toml` | Embeds version string into Poetry's `[tool.poetry]` section during `vmn stamp` |
| PEP 621 | `pyproject.toml` | Embeds version string into PEP 621 `[project]` section during `vmn stamp` |

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

## Generic version backends
There are two generic version backends types: `generic_jinja` and `generic_selectors`.

### generic_selectors

vmn has a comprehensive regex for matching any vmn compliant version string. You may use it if you'd like.

`(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:\.(?P<hotfix>0|[1-9]\d*))?(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*)\.(?P<rcn>(?:0|[1-9]\d*)))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?`

You can play with it here:

https://regex101.com/r/JoEvaN/1


``` yaml
version_backends:
    generic_selectors:
    - paths_section:
      - input_file_path: in.txt
        output_file_path: in.txt
        custom_keys_path: custom.yml
      selectors_section:
      - regex_selector: '(version: )(\d+\.\d+\.\d+)'
        regex_sub: \1{{version}}
      - regex_selector: '(Custom: )([0-9]+)'
        regex_sub: \1{{k1}}
```

`input_file_path` is the file you want to read and `output_file_path` is the file you want to write to.

`custom_keys_path` is a path to a `yaml` file containing any custom `jinja2` keywords you would like to use. This field is optional.

A `regex_selector` is a regex that will match the desired part in the `input_file_path` file and `regex_sub` is a regex that states what the matched part should be replaced with.
In this particular example, putting `{{version}}` tells vmn to inject the correct version while stamping. `vmn` will create an intermediate `jinja2` template and render it to `output_file_path` file.

#### Supported regex vars
```json 
{
   "VMN_VERSION_REGEX":"(?P<major>0|[1-9]\\d*)\\.(?P<minor>0|[1-9]\\d*)\\.(?P<patch>0|[1-9]\\d*)(?:\\.(?P<hotfix>0|[1-9]\\d*))?(?:-(?P<prerelease>(?:0|[1-9]\\d*|\\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\\.(?:0|[1-9]\\d*|\\d*[a-zA-Z-][0-9a-zA-Z-]*))*)\\.(?P<rcn>(?:0|[1-9]\\d*)))?(?:\\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\\.[0-9a-zA-Z-]+)*))?",
   "VMN_ROOT_VERSION_REGEX":"^(?P<version>0|[1-9]\\d*)$"
}
```
  
##### Usage
``` yaml
version_backends:
    generic_selectors:
    - paths_section:
      - input_file_path: in.txt
        output_file_path: in.txt
        custom_keys_path: custom.yml
      selectors_section:
      - regex_selector: '(version: )({{VMN_VERSION_REGEX}})'
        regex_sub: \1{{version}}
      - regex_selector: '(Custom: )([0-9]+)'
        regex_sub: \1{{k1}}
```

### generic_jinja

```yaml
version_backends:
  generic_jinja:
  - input_file_path: f1.jinja2
    output_file_path: jinja_out.txt
    custom_keys_path: custom.yml
```

The parameters here are the same but are talking about `jinja2` files.

## Configuration

`vmn` auto generates a `conf.yml` file that can be modified later by the user.

An example of a possible `conf.yml` file:

```yaml
# Autogenerated by vmn. You can edit this configuration file
conf:
  template: '[{major}][.{minor}]'
  deps:
    ../:
      <repo dir name>:
        vcs_type: git
        # branch: branch_name
        # tag: tag_name
        # hash: specific_hash
  extra_info: false
  create_verinfo_files: false
  hide_zero_hotfix: true
  version_backends: 
    npm:
      path: "relative_path/to/package.json"
```

|         Field          | Description                                                  | Example                                                      |
| :--------------------: | ------------------------------------------------------------ | ------------------------------------------------------------ |
|       `template`       | The template configuration string can be customized and will be applied on the "raw" vmn version.<br>`vmn` will display the version based on the `template`. | `vmn show my_root_app/service3` will output `0.0` <br>however running:<br>`vmn show --raw my_root_app/service3` will output `0.0.1` |
|         `deps`         | In `deps` you can specify other repositories as your dependencies and `vmn` will consider them when stamping and performing `goto`. | See example `conf.yml` file above                            |
|      `extra_info`      | Setting this to `true` will make `vmn` output useful data about the host on which `vmn` has stamped the version.<br>**`Note`** This feature is not very popular and may be remove / altered in the future. | See example `conf.yml` file above                            |
| `create_verinfo_files` | Tells `vmn` to create file for each stamped version. `vmn show --from-file` will work with these files instead of working with `git tags`. | See example `conf.yml` file above                            |
|   `hide_zero_hotfix`   | Tells `vmn` to hide the fourth version octa when it is equal to zero. This way you will never see the fourth octa unless you will specifically stamp with `vmn stamp -r hotfix`. `True` by default. | See example `conf.yml` file above                            |
|   `version_backends`   | Tells `vmn` to auto-embed the version string into one of the supported backends' files during the `vmn stamp` command. For instance, `vmn` will auto-embed the version string into `package.json` file if configured for `npm` projects. | See example `conf.yml` file above                            |
### policies

`vmn` can enforce policies during stamping and releasing. A common policy is to restrict these operations to specific branches.

```yaml
policies:
  whitelist_release_branches: ["main"]
```

Attempting to stamp or release from branches that are not listed will trigger an error.


# Badge

Let people know your project uses vmn:

```md
[![vmn: automatic versioning](https://img.shields.io/badge/vmn-automatic%20versioning-blue)](https://github.com/progovoy/vmn)
```

# Contributors

<a href="https://github.com/progovoy/vmn/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=progovoy/vmn" />
</a>

`vmn` is [Semver](https://semver.org) compliant. We used semver.org as a blueprint for the structure of this specification.
