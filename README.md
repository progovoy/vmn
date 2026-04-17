<h1 align="center">vmn</h1>

<p align="center"><strong>Version your code. Track your experiments. One tool, zero lock-in.</strong></p>
<p align="center"><em>The only CLI that does semantic versioning AND ML experiment tracking -- stored in git, not in your way.</em></p>

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

vmn stamp -r minor my_model              # => 0.1.0
vmn exp create my_model \
    --metrics loss=0.34 acc=0.91          # capture code + metrics
vmn exp compare --latest 2 my_model       # side-by-side metrics table
vmn exp restore --latest my_model         # exact code state restored
```

Stop juggling MLflow for experiments and semantic-release for versions. vmn does both -- and stores everything in git tags and local files. No servers. No cloud. No lock-in.

---

[Why vmn?](#why-vmn) · [ML Experiments](#why-vmn-for-ml-experiments) · [Only in vmn](#what-only-vmn-can-do) · [Experiment Tracking](#experiment-management) · [Snapshots](#snapshots) · [Commands](#commands) · [Configuration](#configuration) · [Roadmap](#roadmap) · [Migration](#already-using-another-tool) · [Contributing](CONTRIBUTING.md)

---

### vmn is for you if:

**Developers who ship software:**

- You version projects in Python, Rust, Go, C++, Java, or anything else -- vmn is language-agnostic.
- You run microservices and need independent versions per service under one root app.
- You manage multi-repo dependencies and want reproducible state recovery across all of them.
- You want zero config. No plugins, no YAML pipelines, no ecosystem buy-in.
- You need versioning that works offline, in CI, and in air-gapped environments.
- You like that versions live in git annotated tags -- uninstall vmn and the tags stay.

**AI/ML researchers who run experiments:**

- You want reproducible experiment snapshots without committing half-finished code.
- You track metrics from the CLI -- no MLflow server, no W&B account, no internet required.
- You compare experiments side by side and restore the exact working tree state of any run.
- You work offline, on a train, in a lab with no cloud access -- it all still works.

No separate `vmn init` required -- `vmn stamp` auto-initializes on first run. Works with shallow clones (`fetch-depth: 1`).

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

## Quick Start

### Version a project (30 seconds)

```sh
pip install vmn
cd your-project     # any git repo

vmn stamp -r patch my_app                 # => 0.0.1 (auto-initializes)
vmn stamp -r minor my_app                 # => 0.1.0
vmn stamp -r patch --pr rc my_app         # => 0.1.1-rc.1 (prerelease)
vmn release my_app                        # => 0.1.1
```

### Track an ML experiment (60 seconds)

```sh
# You're mid-experiment, code is dirty, results look promising
vmn exp create my_model --note "baseline CNN" --metrics loss=0.45 acc=0.85

# Try a different approach...
vmn exp create my_model --note "with dropout" --metrics loss=0.34 acc=0.91

# Compare results
vmn exp compare --latest 2 my_model
# metric    baseline_CNN          with_dropout
# loss      0.45                  0.34
# acc       0.85                  0.91

# Winner! Restore that exact state anytime
vmn exp restore --latest my_model
```

Both workflows store everything in git -- uninstall vmn tomorrow and your tags still make sense.

---
## Why vmn?

vmn does everything semantic-release and release-please do — plus **9 things nothing else does**.

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
| **Offline / air-gapped** | :white_check_mark: | :x: | :x: | :x: |
| **Zero lock-in (pure git tags)** | :white_check_mark: | :x: | :x: | :x: |
| **Dev snapshots (uncommitted state capture)** | :white_check_mark: | :x: | :x: | :x: |
| **ML experiment tracking** | :white_check_mark: | :x: | :x: | :x: |

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
## Why vmn for ML experiments?

Most experiment trackers require a server, a cloud account, or both. vmn tracks experiments the same way it tracks versions — in git and local files.

```sh
vmn exp create my_model \
  --metrics accuracy=0.94 loss=0.12 \
  --note "baseline ResNet run"

vmn exp list my_model --sort accuracy
vmn exp compare --latest 3 my_model
vmn exp restore --latest my_model         # checkout exact code state
```

### How vmn compares to dedicated experiment trackers

| Capability | vmn | MLflow | W&B | DVC | Neptune |
|:-----------|:---:|:------:|:---:|:---:|:-------:|
| No server required | :white_check_mark: | :x: | :x: | :white_check_mark: | :x: |
| No cloud account | :white_check_mark: | :white_check_mark: (self-hosted) | :x: | :white_check_mark: | :x: |
| Free & open source | :white_check_mark: | :white_check_mark: | Free tier | :white_check_mark: | Free tier |
| Metrics tracking | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| Experiment comparison | CLI table | Web UI | Web UI | CLI | Web UI |
| **Full code state capture** | :white_check_mark: | :x: | :x: | partial | :x: |
| **Uncommitted changes captured** | :white_check_mark: | :x: | :x: | :x: | :x: |
| **One-command state restore** | :white_check_mark: | :x: | :x: | :x: | :x: |
| **Built-in version management** | :white_check_mark: | :x: | :x: | :x: | :x: |
| Artifact tracking | :white_check_mark: (SHA256) | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| Works offline / air-gapped | :white_check_mark: | self-hosted only | :x: | partially | :x: |
| Install complexity | `pip install vmn` | server + DB | account + pip | pip + git config | account + pip |
| Storage | git + local/S3 | database | cloud | git/S3 | cloud |
| Lock-in | zero (git tags + files) | MLflow format | W&B cloud | DVC format | Neptune cloud |

> **Bold rows = only vmn.** Capture your exact working state — dirty files, local commits, everything — and restore it with one command. No other experiment tracker does this.

vmn is not trying to replace MLflow's web dashboard or W&B's visualization suite. It's for researchers who want **lightweight, git-native experiment tracking** that lives alongside their version management — without spinning up servers, creating cloud accounts, or leaving the terminal.

### When to use what

**Use vmn when:**
- You want a CLI-first workflow with no context switching
- You work offline or in air-gapped environments
- You need version management and experiment tracking in one tool
- You want zero infrastructure — no servers, no databases, no accounts
- You prefer git-native storage with no vendor lock-in

**Use MLflow / W&B when:**
- You need rich web visualizations and interactive charts
- Your team relies on shared dashboards and collaboration features
- You are already invested in their ecosystem and integrations

Eight subcommands cover the full experiment lifecycle:

| Command | What it does |
|:--------|:-------------|
| `vmn exp create` | Capture a snapshot with metrics, parameters, and notes |
| `vmn exp add` | Log additional metrics, notes, or artifacts to an experiment |
| `vmn exp list` | List experiments with filtering and sorting by any metric |
| `vmn exp show` | Display full experiment details including log history |
| `vmn exp compare` | Side-by-side metric comparison across experiments |
| `vmn exp restore` | Restore the exact code state — checkout + apply patches |
| `vmn exp export` | Export experiment as a directory or tarball |
| `vmn exp prune` | Clean up old experiments (keep N or older than duration) |

---
## What only vmn does

### State recovery -- a time machine for your repo

```sh
vmn goto -v 1.2.3 my_app
```

Your entire repository -- plus every tracked dependency -- is now at exactly the state when 1.2.3 shipped. No digging through CI logs, no guessing which commit broke prod. Reproduce bugs in seconds, not hours.

### Multi-repo snapshots -- reproducible builds across repositories

If your product spans multiple git repos, vmn records the exact commit hash of every dependency at stamp time. `vmn goto` restores all of them in parallel:

```sh
vmn stamp -r minor my_app
# records: my_app @ abc123, lib_core @ def456, lib_utils @ 789fed

# six months later
vmn goto -v 0.1.0 my_app    # all 3 repos restored to recorded commits
```

Dependencies are declared in `.vmn/my_app/conf.yml` and auto-cloned if missing -- up to 10 in parallel. One command, full reproducibility.

### Microservice topology -- one umbrella, independent versions

Version multiple services under one root app. Each service has its own semver; the root gets an auto-incrementing integer that ticks on every child stamp:

```sh
vmn stamp -r patch my_platform/auth      # auth => 0.0.1, root => 1
vmn stamp -r minor my_platform/billing   # billing => 0.1.0, root => 2
vmn stamp -r patch my_platform/auth      # auth => 0.0.2, root => 3

vmn show --root my_platform              # => 3
```

Deploy auth and billing independently while the root version gives you a single monotonic counter for "what changed last." Perfect for Kubernetes manifests and release notes that span services.

### Zero lock-in -- it is just git tags

All version state lives in annotated git tag messages as plain YAML. There are no proprietary databases, no SaaS dashboards, no JSON files you have to keep in sync. Uninstall vmn tomorrow and your tags still make perfect sense:

```sh
git tag -l 'my_app_*'          # every version, right there
git tag -n1 my_app_1.2.3       # full stamp metadata in the tag message
```

Switch to a different tool, read the tags with a shell script, or parse them in CI -- the data is yours.

### Version formats -- full semver plus hotfix

Standard Semver 2.0 plus an optional 4th hotfix segment and dev snapshots for every workflow:

```
1.6.0                              # stable release
1.6.0-rc.23                        # prerelease
1.6.7.4                            # hotfix (4th segment)
1.6.0-rc.23+build01.Info           # build metadata
1.6.0-dev.a1b2c3d.e4f5g6h          # dev snapshot
```

The hotfix segment lets you ship emergency fixes without bumping patch, keeping your release train on schedule while production stays safe.

---
## Experiment Management

`vmn experiment` (alias: `vmn exp`) adds git-native experiment tracking to any
versioned app. No servers, no databases -- experiments are stored alongside your
tags and snapshots. Every experiment ties back to an exact version and commit,
so reproducing results is a `vmn exp restore` away.

### Quick workflow

```sh
# Create an experiment pinned to a version
vmn exp create my_model --note "baseline CNN" --metrics loss=0.45 acc=0.85

# Train more, append metrics and artifacts
vmn exp add my_model --latest --metrics loss=0.31 acc=0.92 --attach weights.pt

# Compare the last 3 experiments side by side
vmn exp compare my_model --latest 3

# Restore the best run (checkout code + retrieve artifacts)
vmn exp restore my_model -v 1.2.0
```

### Subcommand reference

#### create

Start a new experiment. This is the default action when no subcommand is given.

```sh
vmn exp create my_model --note "dropout 0.3" --metrics loss=0.45 acc=0.85
vmn exp create my_model -f params.yml --attach initial_weights.pt -v 1.2.0
```

#### add

Append metrics, notes, or artifacts to an existing experiment.

```sh
vmn exp add my_model -v 1.2.0 --metrics val_loss=0.29 val_acc=0.93
vmn exp add my_model --latest --attach checkpoint_epoch10.pt --note "after LR warmup"
```

#### list

List experiments, optionally sorted by a metric.

```sh
vmn exp list my_model                          # all experiments
vmn exp list my_model --sort loss --top 5      # best 5 by loss
vmn exp list my_model --latest 10              # most recent 10
```

#### show

Display full details for a single experiment.

```sh
vmn exp show my_model -v 1.2.0
vmn exp show my_model --latest
```

#### compare

Side-by-side metric comparison across experiments.

```sh
vmn exp compare my_model -v 1.1.0 -v 1.2.0 -v 1.3.0
vmn exp compare my_model --latest 3 --tool delta   # use external diff tool
```

Set `VMN_DIFFTOOL` to default to your preferred diff viewer.

#### restore

Check out the exact code state and retrieve artifacts for an experiment.

```sh
vmn exp restore my_model -v 1.2.0
vmn exp restore my_model --latest
```

#### export

Package an experiment (metadata, metrics, artifacts) into a tarball.

```sh
vmn exp export my_model -v 1.2.0                     # writes 1.2.0.tar.gz
vmn exp export my_model --latest -o best_run.tar.gz
```

#### prune

Clean up old experiments by count or age.

```sh
vmn exp prune my_model --keep 10           # keep the 10 most recent
vmn exp prune my_model --older-than 30d    # remove experiments older than 30 days
```

### Structured notes

Pass a YAML file with `-f` to attach structured metadata to any experiment:

```yaml
# params.yml
hypothesis: "larger batch size improves convergence"
params:
  lr: 0.001
  batch_size: 64
  epochs: 50
tags: [baseline, transformer-v2]
```

```sh
vmn exp create my_model -f params.yml --metrics loss=0.38
```

### Metrics schema

Define sort order and a primary metric in `.vmn/{app_name}/conf.yml` so that
`list --sort` and `compare` know which direction is better:

```yaml
experiment:
  metrics:
    loss: {sort: desc, primary: true}
    acc:  {sort: desc}
    val_loss: {sort: desc}
```

### Storage

Experiments are stored locally by default under `.vmn/`. For team-wide sharing,
point to an S3-compatible backend:

<details>
<summary>S3 / MinIO storage flags</summary>

All subcommands accept these flags:

```sh
vmn exp create my_model --backend s3 --bucket my-experiments \
    --endpoint-url http://minio:9000 --prefix team/ml
```

| Flag | Default | Description |
|------|---------|-------------|
| `--backend` | `local` | `local` or `s3` |
| `--bucket` | -- | S3 bucket name |
| `--endpoint-url` | -- | Custom endpoint (MinIO, LocalStack, etc.) |
| `--prefix` | `vmn-experiments` | Key prefix inside the bucket |

</details>

---
## Snapshots

Snapshots capture your exact working state -- uncommitted changes, local commits, untracked files -- into a deterministic dev version you can restore later. No WIP commits, no stash juggling. The newer `vmn experiment` command builds on this primitive for structured experiment tracking.

### Dev version format

Every snapshot produces a version string derived from the content itself:

```
{base_version}-dev.{commit_hash}.{diff_hash}
```

Identical code state always produces the identical version string. If nothing changed, you get the same snapshot version back.

### Quick start

```sh
vmn snapshot create my_model --note "promising results"
# => 1.2.0-dev.a1b2c3d.e4f5g6h

vmn snapshot list my_model
# [1] 1.2.0-dev.a1b2c3d.e4f5g6h  (2h ago) - promising results
# [2] 1.2.0-dev.x9y8z7w.q1r2s3t  (1d ago)

vmn snapshot show --latest my_model
vmn snapshot note --latest --note "confirmed: best run" my_model
vmn snapshot diff -v 1.2.0-dev.a1b --to current my_model
vmn snapshot export --latest -o ./experiment_42 my_model

# Restore via goto
vmn goto -v 1.2.0-dev.a1b2c3d.e4f5g6h my_model
```

<details>
<summary>What's stored in a snapshot</summary>

```
.vmn/{app}/snapshots/{version}/
  metadata.yml           # version, branch, timestamp, note, dirty states
  working_tree.patch     # uncommitted changes (git diff HEAD)
  local_commits.patch    # local commits not yet pushed
  untracked_files.tar.gz # untracked files
  deps/{dep_name}/...    # dependency patches (same structure)
  artifacts/{filename}   # attached files
```

Everything needed to reconstruct the working tree is stored alongside the metadata. Dependencies get their own patch set so multi-repo states restore correctly with `vmn goto`.

</details>

<details>
<summary>All snapshot flags</summary>

| Flag | Description |
|------|-------------|
| `-v`, `--version` | Target a specific snapshot version (supports prefix matching) |
| `--latest` | Use the most recent snapshot |
| `--note` | Attach or update a text note |
| `--to` | Second version for `diff` (or `current` for working tree) |
| `--tool` | External diff tool (`meld`, `vimdiff`, etc.). Env: `VMN_DIFFTOOL` |
| `-o`, `--output` | Export destination path |
| `--meta` | Repeatable `key=value` metadata pairs |
| `--meta-file` | YAML file with additional metadata |
| `--filter` | Repeatable `key=value` pairs for filtering `list` output |
| `--backend` | Storage backend: `local` (default) or `s3` |
| `--bucket` | S3 bucket name |
| `--endpoint-url` | Custom S3 endpoint (MinIO, DigitalOcean Spaces, etc.) |
| `--prefix` | S3 key prefix (default: `vmn-snapshots`) |
| `--verbose` | Show extended snapshot details |

</details>

<details>
<summary>Storage backends</summary>

**Local (default)** -- snapshots live under `.vmn/{app}/snapshots/` in the repository. Nothing to configure.

**S3** -- push snapshots to any S3-compatible store:

```sh
vmn snapshot create my_model --backend s3 --bucket my-snapshots
vmn snapshot list my_model --backend s3 --bucket my-snapshots
```

Custom endpoints work for MinIO, DigitalOcean Spaces, and similar services:

```sh
vmn snapshot create my_model \
  --backend s3 \
  --bucket dev-snapshots \
  --endpoint-url http://localhost:9000 \
  --prefix team/ml
```

</details>

---
## Commands

> `init-app` and `stamp` both support `--dry-run` for safe testing.

| Command | What it does | Example |
|:--------|:-------------|:--------|
| `vmn stamp` | Create a new version | `vmn stamp -r patch my_app` |
| `vmn release` | Promote prerelease to final | `vmn release my_app` |
| `vmn show` | Display version info | `vmn show my_app` |
| `vmn goto` | Checkout repo at a version | `vmn goto -v 1.2.3 my_app` |
| `vmn snapshot` | Capture dev state (uncommitted work) | `vmn snapshot create my_app` |
| `vmn experiment` | Track ML experiments (alias: `exp`) | `vmn exp create my_model --metrics loss=0.34` |
| `vmn gen` | Generate file from template | `vmn gen -t ver.j2 -o ver.txt my_app` |
| `vmn add` | Attach build metadata | `vmn add -v 1.0.0 --bm build42 my_app` |
| `vmn config` | Edit app config (TUI) | `vmn config my_app` |
| `vmn init` | Initialize repo/app | `vmn stamp` auto-inits -- rarely needed |

### vmn stamp

```sh
vmn stamp -r patch my_app                 # => 0.0.1
vmn stamp -r minor my_app                 # => 0.1.0
vmn stamp -r patch --pr rc my_app         # => 0.0.2-rc.1 (prerelease)
vmn stamp my_app                          # => 0.0.3 (with conventional_commits -- no -r needed)
vmn stamp --dry-run -r patch my_app       # preview without committing
vmn stamp --pull -r patch my_app          # pull before stamping (retries on conflict)
```

Idempotent -- won't re-stamp if the current commit already matches. Auto-initializes repo and app on first run.

<details>
<summary>Stamping without -r, -r vs --orm, and all flags</summary>

**Without `-r`:** only works during a prerelease sequence (continues the existing prerelease). Errors on a release commit. Exception: with `conventional_commits` enabled, `-r` is always optional -- the release mode is inferred from commit messages.

**`-r` vs `--orm`:**

| Flag | Behavior |
|:----:|:---------|
| `-r patch` | **Strict** -- always advances. `0.0.1` -> `0.0.2`. `0.0.2-rc.3` -> `0.0.3`. |
| `--orm patch` | **Optional** -- advances only if no prerelease exists at the target version. |

**All stamp flags:**

| Flag | Description |
|:-----|:------------|
| `-r`, `--release-mode` | Release mode: `major`, `minor`, `patch`, `hotfix`, `micro` |
| `--orm`, `--optional-release-mode` | Optional release mode: `major`, `minor`, `patch`, `hotfix` |
| `--pr`, `--prerelease` | Create a prerelease (e.g., `--pr rc` produces `X.Y.Z-rc.N`) |
| `--pull` | Pull remote before stamping; retries on conflict |
| `--dry-run` | Preview the version without committing or tagging |
| `-e`, `--extra-commit-message` | Append extra text to the stamp commit message |
| `--ov`, `--override-version` | Force a specific version string |
| `--orv`, `--override-root-version` | Force a specific root-app version |
| `--dont-check-vmn-version` | Skip the vmn version compatibility check |

**`vmn init-app` flags:**

| Flag | Description |
|:-----|:------------|
| `-v`, `--version` | Initial version (default `0.0.0`) |
| `--dry-run` | Preview without writing |
| `--orm`, `--default-release-mode` | Set default release mode: `optional` or `strict` |
</details>

#### Stamp automation (conventional commits, changelog, GitHub releases)

Enable `conventional_commits` and never type `-r` again. Commit prefixes map directly to release modes: `fix:` -> patch, `feat:` -> minor, `BREAKING CHANGE` or `!` after type -> major.

```sh
git commit -m "feat: add search endpoint"
vmn stamp my_app    # => 0.2.0 (minor, auto-detected)
```

```yaml
conf:
  conventional_commits: true
  default_release_mode: optional
  changelog:
    path: "CHANGELOG.md"
  github_release:
    draft: false
```

`default_release_mode` is a top-level config key (not nested under `conventional_commits`).
### vmn release

```sh
vmn release -v 0.0.1-rc.1 my_app   # explicit version -- tag-only
vmn release my_app                  # auto-detect from current commit
vmn release --stamp my_app          # full stamp flow -- new commit + tag + push
```
Promotes prerelease to final. Idempotent. `-v` and `--stamp` are mutually exclusive.

### vmn show

```sh
vmn show my_app              # current version
vmn show --dev my_app        # dev version with commit+diff hash
vmn show --verbose my_app    # full YAML metadata dump
vmn show --raw my_app        # without template formatting
vmn show --type my_app       # release / prerelease / metadata
vmn show -u my_app           # unique ID (version+commit_hash)
vmn show --conf my_app       # show app configuration
vmn show --root my_root_app  # root app version (integer)
```

### vmn goto

```sh
vmn goto -v 1.2.3 my_app              # repo + deps restored to exact state
vmn goto my_app                        # latest version on current branch
vmn goto -v 1.2.3 --deps-only my_app  # only checkout dependencies
vmn goto -v 5 --root my_root_app      # checkout to root app version
vmn goto -v 1.2.0-dev.a1b2c3d.e4f5g6h my_model  # restore dev snapshot
```
Deps auto-cloned if missing. Dev restore: checkout base, replay commits, apply working tree patch.

### vmn gen

```sh
vmn gen -t version.j2 -o version.txt my_app
vmn gen -t version.j2 -o version.txt -c custom.yml my_app
```
<details><summary>Template variables</summary>

`version`, `base_version`, `name`, `release_mode`, `prerelease`, `previous_version`, `stamped_on_branch`, `release_notes`, `changesets`, `root_name`, `root_version`, `root_services`.
</details>

### vmn add

```sh
vmn add -v 0.0.1 --bm build42 my_app
```
Attaches build metadata to an existing version tag (e.g. `0.0.1+build42`). Optional `--vmp` for metadata file path.

### vmn config

```sh
vmn config                  # list all managed apps
vmn config my_app           # interactive TUI editor
vmn config my_app --vim     # open in $EDITOR
vmn config --branch my_app  # branch-specific override
vmn config --global         # repo-level .vmn/conf.yml
```

### Release candidates

Iterate on prereleases, then promote:

```sh
vmn stamp -r major --pr alpha my_app    # 2.0.0-alpha.1
vmn stamp --pr alpha my_app             # 2.0.0-alpha.2
vmn stamp --pr mybeta my_app            # 2.0.0-mybeta.1
vmn release my_app                      # 2.0.0
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
| `GITHUB_TOKEN` / `GH_TOKEN` | Required for GitHub Releases |
| `VMN_DIFFTOOL` | External diff tool for snapshot/experiment compare |

---
## Version Auto-Embedding

`vmn stamp` can automatically write the stamped version into your project files. Add a `version_backends` section to `.vmn/<app>/conf.yml`:

| Backend | File | What it updates |
|:--------|:-----|:----------------|
| `npm` | `package.json` | `version` field |
| `cargo` | `Cargo.toml` | `version` field |
| `poetry` | `pyproject.toml` | `[tool.poetry].version` |
| `pep_621` | `pyproject.toml` | `[project].version` |

```yaml
version_backends:
  npm:
    path: "relative/path/to/package.json"
```

<details><summary>Hatchling / uv dynamic versioning (hatch-vcs)</summary>

Instead of file injection, read the version directly from git tags at build time:

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[tool.hatch.version]
source = "vcs"
tag-pattern = "my_app_(?P<version>.*)"
```

No `version_backends` entry needed -- the build tool pulls the version from the tag vmn created.
</details>

<details><summary>Generic backends (regex and Jinja2)</summary>

**generic_selectors** -- regex find-and-replace in any file:

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

**generic_jinja** -- render a Jinja2 template:

```yaml
version_backends:
  generic_jinja:
    - input_file_path: f1.jinja2
      output_file_path: jinja_out.txt
      custom_keys_path: custom.yml
```

Same variables as `vmn gen`.
</details>

---
## Configuration

vmn auto-generates `.vmn/<app-name>/conf.yml` when an app is first stamped. Edit it directly or use the built-in TUI:

```sh
vmn config my_app        # interactive TUI editor
vmn config my_app --vim  # open in $EDITOR
```

Full `conf.yml` structure:

```yaml
conf:
  template: '[{major}][.{minor}][.{patch}][.{hotfix}][-{prerelease}][.{rcn}][-dev.{dev_commit}.{dev_diff_hash}][+{buildmetadata}]'
  hide_zero_hotfix: true
  extra_info: false
  create_snapshots: false
  conventional_commits: true
  default_release_mode: optional   # "optional" (--orm) or "strict" (-r required)
  changelog:
    path: "CHANGELOG.md"
  github_release:
    draft: false
  deps:
    ../:
      other_repo:
        vcs_type: git
  version_backends:
    npm:
      path: "package.json"
  policies:
    whitelist_release_branches: ["main"]
  snapshot_storage:
    backend: local
    bucket: my-bucket
    prefix: vmn-snapshots
    endpoint_url: https://...
  experiment:
    metrics:
      loss: { sort: desc, primary: true }
      acc:  { sort: desc }
```

> **Migration note:** `create_verinfo_files` has been renamed to `create_snapshots`. The old key still works but prints a deprecation warning.

**Per-branch configuration.** Place `{branch}_conf.yml` next to `conf.yml` in `.vmn/<app>/`. vmn checks for a branch-specific config first and falls back to `conf.yml`. Stale branch configs from other branches are auto-cleaned on stamp.

## CI Integration

Use the official GitHub Action for stamping in CI pipelines:

```yaml
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0          # vmn needs full history
  - uses: progovoy/vmn-action@latest
    with:
      app-name: my_app
      do-stamp: true
      stamp-mode: patch
    env:
      GITHUB_TOKEN: ${{ github.token }}
```

`fetch-depth: 0` is required -- vmn reads git tags and history to compute the next version.

---
## Roadmap

vmn is actively developed. Here's what's next — [file an issue](https://github.com/progovoy/vmn/issues) to vote or suggest.

**Experiment Tracking**

- [ ] **`vmn experiment plot`** — ASCII metric charts in the terminal.
  Visualize loss curves, accuracy trends across experiments without leaving the CLI.
  `vmn exp plot --metric loss my_model`

- [ ] **W&B / MLflow export** — Push experiments to existing tracking platforms for team visualization.
  `vmn exp export --format mlflow` bridges vmn's lightweight tracking to rich UIs when you need them.

- [ ] **Advanced filtering** — Filter experiments by tags, metric thresholds, or date ranges.
  `vmn exp list --tag baseline --filter "loss<0.5"` for targeted experiment discovery.

- [ ] **Local web dashboard** — `vmn dashboard my_model` serves a local-only web UI for visualizing
  experiment metrics, diffs, and artifacts. Think MLflow UI without the server — reads directly from `.vmn/`.

- [ ] **Team experiment sync** — Push/pull experiments via S3 for team-wide collaboration and comparison,
  building on the existing S3 backend.

**Version Management**

- [ ] **Monorepo auto-discovery** — Detect apps automatically from workspace configs
  (Cargo workspaces, pnpm-workspace.yaml, Python namespace packages).

- [ ] **PR version annotation** — GitHub Action that auto-comments the next version on pull requests
  using `vmn stamp --dry-run`.

- [ ] **Version policies** — Guardrails like `max_release_mode: minor` (prevent accidental major bumps
  on feature branches) and `require_changelog: true`.

- [ ] **Post-stamp hooks** — Run custom commands after a successful stamp
  (e.g., trigger deploys, update docs, notify Slack).

**Distribution**

- [ ] **Homebrew tap** — `brew install vmn` for macOS/Linux users who prefer Homebrew over pip.

- [ ] **npm wrapper** — `npx vmn` for Node.js teams who want vmn without Python.

- [ ] **conda-forge package** — `conda install vmn` for data science teams.

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
  Star the repo if vmn saved you time.
  <a href="https://github.com/progovoy/vmn/issues">File an issue</a> if it didn't — we'll fix it.
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
