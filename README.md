<h1 align="center" style="border-bottom: none;">🥇🏷️Automatic version management solution</h1>
<h3 align="center">Automatic version management and state recovery solution for any application agnostic to language or architecture</h3>

<p align="center">

[![Project Status: Active – The project has reached a stable, usable state and is being actively developed.](https://www.repostatus.org/badges/latest/active.svg)](https://www.repostatus.org/#active)
[![codecov](https://codecov.io/gh/progovoy/vmn/branch/master/graph/badge.svg)](https://codecov.io/gh/progovoy/vmn)
<a href="#badge">
<img alt="vmn" src="https://img.shields.io/github/pipenv/locked/python-version/progovoy/vmn">
</a>
<a href="#badge">
<img alt="vmn: pypi downloads" src="https://img.shields.io/pypi/dw/vmn">
</a>
<a href="#badge">
<img alt="vmn: supported platforms" src="https://img.shields.io/badge/vmn-linux%20%7C%20macos%20%7C%20windows%20-brightgreen">
</a>
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-%23FE5196?logo=conventionalcommits&logoColor=white)](https://conventionalcommits.org)


`vmn` is compliant with `Semver` (https://semver.org) semantics

</p>

### Badge

Let people know that your repository is managed by **vmn** by including this badge in your readme.

[![vmn: automatic versioning](https://img.shields.io/badge/vmn-automatic%20versioning-blue)](https://github.com/progovoy/vmn)

```md
[![vmn: automatic versioning](https://img.shields.io/badge/vmn-automatic%20versioning-blue)](https://github.com/progovoy/vmn)
```

<p align="center">
  <br>
  <img width="800" src="https://i.imgur.com/g3wYIk8.png">
  <br>
</p>

- [What is VMN?](#what-is-vmn)
- [Play around with VMN](#play-around-with-vmn)
  - [Create a playground](#option-1-create-a-playground)
  - [Use VMN Action with GitHub Action](#option-2-use-vmn-action-with-github-action)
- [Contribute](#contribute)
  - [Create a dev environment](#create-a-dev-environment)
  - [Run tests](#run-tests)
- [Key features](#key-features)
- [Usage by Lean Examples](#usage-by-lean-examples)
  - [Pre-requisites](#pre-requisites)
  - [1. vmn init](#1-vmn-init)
  - [2. vmn init-app](#2-vmn-init-app)
  - [3. vmn stamp](#3-vmn-stamp)
  - [4. vmn release](#4-vmn-release)
  - [5. vmn show](#5-vmn-show)
  - [6. vmn gen](#6-vmn-gen)
  - [7. vmn goto](#7-vmn-goto)
  - [8. vmn add](#8-vmn-add)
  - [Other usages](#other-usages)
- [Detailed Documentation](#detailed-documentation)
  - [vmn init](#vmn-init)
  - [vmn init-app](#vmn-init-app)
  - [vmn stamp](#vmn-stamp)
  - [vmn release](#vmn-release)
  - [vmn show](#vmn-show)
  - [vmn goto](#vmn-goto)
  - [vmn gen](#vmn-gen)
  - [vmn add](#vmn-add)
- [Version auto-embedding](#version-auto-embedding)
  - [Hatchling / uv](#hatchling--uv)
- [Generic version backends](#generic-version-backends)
- [Configuration](#configuration)
- [Thank yous and Contributors](#thank-yous-and-contributors)

# What is `vmn`?

`vmn` is a CLI tool and Python library for automatic semantic versioning of any project, regardless of language or architecture. It uses **git tags** as the source of truth for version state — no version files to maintain manually.

Key capabilities:
- Stamp `major.minor.patch` versions with optional `hotfix`, `prerelease`, and `buildmetadata` segments
- Auto-embed versions into `package.json`, `Cargo.toml`, `pyproject.toml`, or any file via regex/jinja2 backends — works with **uv** and **hatchling** out of the box
- Manage multi-repo dependencies and microservice topologies
- Recover the exact repository state for any previously stamped version
- Detect release mode automatically from conventional commits

# Play around with `vmn`

## Option 1: Create a playground

```sh
# Install vmn
pip install vmn

# Create fake remote
mkdir remote
cd remote
git init --bare

# Clone from fake remote
cd ..
git clone ./remote ./local
cd local

# Mimic user commit
echo a >> ./a.txt ; git add ./a.txt ; git commit -m "wip" ; git push origin master

# Initialize vmn for first time
vmn init
# Initialize app for first time
vmn init-app my_cool_app

# First stamp
vmn stamp -r patch my_cool_app

# Mimic user commit
echo a >> ./a.txt ; git add ./a.txt ; git commit -m "wip" ; git push origin master

# Second stamp
vmn stamp -r patch my_cool_app
```

## Option 2: Use VMN Action with GitHub Action

Check [VMN Official GitHub Action Repo](https://github.com/progovoy/vmn-action)

Example workflow snippet:

```yaml
steps:
  - uses: actions/checkout@v3
  - uses: progovoy/vmn-action@v1
    with:
      app-name: my_cool_app
      do-stamp: true
      stamp_release: true
```

# Contribute

## Create a dev environment

```sh
# After cloning vmn repo:
cd ./vmn
# For Ubuntu:
#   sudo apt install python3-venv
python3 -m venv ./venv
source ./venv/bin/activate

pip install -r  ./tests/requirements.txt 
pip install -r  ./tests/test_requirements.txt 
pip install -e  ./
vmn --version # Should see 0.0.0 if installed successfully
```

## Run tests

``` sh
# install Docker 
#   For Ubuntu - sudo apt install docker.io
# Then run:
./tests/run_pytest.sh
# If it runs successfully, you are good to go
```

# Key features

- [x] Stamping of versions of type: **`major`. `minor`.`patch`** , e.g., `1.6.0` [`Semver` compliant]
- [x] Stamping of versions of type: `major`. `minor`.`patch`**-`prerelease`** , e.g., `1.6.0-rc23` [`Semver` compliant]
- [x] Stamping of versions of type: `major`. `minor`.`patch`.**`hotfix`** , e.g., `1.6.7.4` [`Semver` extension]
- [x] Bringing back the repository / repositories state to the state they were when the project was stamped (
  see [`goto`](https://github.com/progovoy/vmn#goto) section)
- [x] Stamping of micro-services-like project topologies (
  see [`Root apps`](#root-apps-or-microservices) section)
- [x] Stamping of a project depending on multiple git repositories (
  see [`Configuration: deps`](#configuration) section)
- [x] Version auto-embedding into supported backends during the `vmn stamp` phase (
  see [`Version auto-embedding`](#version-auto-embedding) section)
- [x]  Addition of `buildmetadata` for an existing version, e.g., `1.6.0-rc23+build01.Info` [`Semver` compliant]
- [x]  Support for `conventional commits` for automatic release mode detection (`optional` or `strict`)
- [x]  Support for `conventional commits` for automatic release notes generation
- [x]  Support for `uv` and `hatchling` via `hatch-vcs` integration (dynamic versioning from vmn tags)
- [ ] `WIP` Support "root apps" that are located in different repositories

# Usage by Lean Examples

Note: `init-app` and `stamp` both support `--dry-run` flag for testing purposes.

## Pre-requisites

```sh
pip3 install vmn

# Another option (and a better one) is to use pipX (https://github.com/pypa/pipx):
pipx install vmn
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

In case you desire to use conventional commits for the stamp command to recognize the `release_mode` automatically, provide the following in app's `conf.yml` file:

```yaml
conventional_commits:
  default_release_mode: optional
```

`default_release_mode` may be `optional`(for --orm) or `strict`(for -r).

Now you will be able to run:
`vmn stamp <app-name>` and `vmn` will deduce the proper `release_mode` based on your conventional commits.

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


# Thank yous and Contributors

To [Pavel Rogovoy](https://github.com/progovoy) for being the main contributor for this project.

To semver.org: we used semver.org as a blueprint for the structure of this specification.

Thanks goes to these wonderful people ✨

<a href="https://github.com/progovoy/vmn/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=progovoy/vmn" />
</a>

If you like and use this project, please consider starring it ✨

Thanks!
