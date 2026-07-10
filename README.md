<h1 align="center">vmn</h1>

<p align="center"><strong>Automatic semantic versioning powered by git tags. Zero lock-in.</strong></p>
<p align="center"><em>Language-agnostic CLI for versioning, multi-repo state recovery, and experiment tracking -- all stored in git.</em></p>

<p align="center">
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/v/vmn?logo=pypi&logoColor=white&label=PyPI" alt="PyPI version"></a>
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/dw/vmn?logo=pypi&logoColor=white" alt="PyPI downloads"></a>
  <a href="https://github.com/progovoy/vmn"><img src="https://img.shields.io/github/stars/progovoy/vmn?style=flat&logo=github" alt="GitHub stars"></a>
  <a href="https://semver.org"><img src="https://img.shields.io/badge/semver-2.0.0-blue?logo=semver&logoColor=white" alt="Semver"></a>
  <a href="https://conventionalcommits.org"><img src="https://img.shields.io/badge/Conventional%20Commits-1.0.0-%23FE5196?logo=conventionalcommits&logoColor=white" alt="Conventional Commits"></a>
  <a href="https://github.com/progovoy/vmn/blob/master/LICENSE"><img src="https://img.shields.io/github/license/progovoy/vmn" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Rust-000000?logo=rust&logoColor=white" alt="Rust">
  <img src="https://img.shields.io/badge/Go-00ADD8?logo=go&logoColor=white" alt="Go">
  <img src="https://img.shields.io/badge/C++-00599C?logo=cplusplus&logoColor=white" alt="C++">
  <img src="https://img.shields.io/badge/Java-ED8B00?logo=openjdk&logoColor=white" alt="Java">
  <img src="https://img.shields.io/badge/JS/TS-F7DF1E?logo=javascript&logoColor=black" alt="JavaScript">
</p>

---

```sh
pip install vmn

vmn stamp -r patch my_app                 # => 0.0.1  (auto-initializes repo + app)
vmn stamp -r minor my_app                 # => 0.1.0
vmn stamp -r patch --pr rc my_app         # => 0.1.1-rc.1  (prerelease)
vmn release my_app                        # => 0.1.1
vmn goto -v 0.1.0 my_app                  # repo restored to exact 0.1.0 state
```

Versions live in git annotated tags. Uninstall vmn and the tags still make sense. No databases, no SaaS, no ecosystem buy-in.

---

[Requirements](#-requirements) · [Quick Start](#-quick-start) · [Why vmn?](#-why-vmn) · [Only in vmn](#-what-only-vmn-does) · [Experiments](#-experiment-management) · [Snapshots](#-snapshots) · [Commands](#-commands) · [Auto-Embedding](#-version-auto-embedding) · [Configuration](#️-configuration) · [CI](#-ci-integration) · [Troubleshooting](#-troubleshooting) · [Migration](#-already-using-another-tool)

---

### vmn is for you if:

| | |
|:--|:--|
| **Any language** — Python, Rust, Go, C++, Java, JS, or anything with a git repo | **Microservices** — independent versions per service, one root counter |
| **Multi-repo** — reproducible state recovery across repositories | **Zero config** — no plugins, no pipelines, no ecosystem buy-in |
| **Offline / air-gapped** — works without network access | **Zero lock-in** — versions live in plain git tags |
| **ML experiments** — reproducible snapshots with metrics, no tracking server | |

No separate `vmn init` required -- `vmn stamp` auto-initializes on first run. Works in CI (handles shallow clones automatically).

### How it works

<p align="center"><code>git commit</code> → <code>vmn stamp</code> → <strong>git tag</strong> → <code>git push</code></p>

vmn stores all version state in **git annotated tag messages** as plain YAML. When you `vmn stamp`, it computes the next version, writes it into a tag (e.g., `my_app_1.2.0`), and optionally pushes. When you `vmn show`, it reads that tag. There is no database, no config service, no proprietary format -- just git tags you can inspect with `git tag -n1`.

**Try it locally (30 seconds):**

```sh
pip install vmn

mkdir remote && cd remote && git init --bare && cd ..
git clone ./remote ./local && cd local
echo a >> ./a.txt && git add ./a.txt && git commit -m "first commit" && git push origin master

vmn stamp -r patch my_app   # => 0.0.1

echo b >> ./a.txt && git add ./a.txt && git commit -m "feat: add b" && git push origin master
vmn stamp -r patch my_app   # => 0.0.2

git tag -n1 my_app_0.0.2    # version metadata right there in the tag
```

---

## 📋 Requirements

- **Python** 3.8+
- **Git** 2.10+ (for push options support; 2.17+ recommended)
- **Platforms:** Linux, macOS, Windows (including WSL). No platform-specific configuration needed -- vmn uses GitPython for cross-platform git operations.

## 🚀 Quick Start

### Version a project

```sh
pip install vmn
cd your-project                           # any git repo

vmn stamp -r patch my_app                 # => 0.0.1 (auto-initializes)
vmn stamp -r minor my_app                 # => 0.1.0
vmn show my_app                           # => 0.1.0
vmn stamp -r patch --pr rc my_app         # => 0.1.1-rc.1 (prerelease)
vmn release my_app                        # => 0.1.1
```

### Track an ML experiment (60 seconds)

```sh
# One command: capture code state, run training, record metrics + duration + exit code.
# Your script appends "key=value" lines to $VMN_METRICS_FILE and vmn ingests them.
vmn exp run my_model --note "baseline CNN" -- python train.py
# => 0.1.0-dev.a1b2c3d.e4f5g6h

# Edit the model, run again — a fresh experiment, even on the same commit
vmn exp run my_model --note "with dropout" -- python train.py
# => 0.1.0-dev.f7a2b1c.d3e4f5g

# Leaderboard, best loss first
vmn exp list my_model --sort loss

# See exactly what changed AND what happened — metric delta + real code diff
vmn exp diff my_model
# Comparing 0.1.0-dev.a1b2c3d.e4f5g6h -> 0.1.0-dev.f7a2b1c.d3e4f5g
#
# metrics: loss 0.45 -> 0.34   acc 0.85 -> 0.91
#
# diff --git a/.../model.py b/.../model.py
# -    return lr * 0.5  # baseline
# +    return lr * 0.3  # with dropout

# Winner! Restore that exact state (any dirty work is auto-saved first)
vmn exp restore my_model --latest
```

Both workflows store everything in git -- no servers, no lock-in.

---
## ⚡ Why vmn?

vmn does everything semantic-release and release-please do -- plus **9 things nothing else does**.

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
| **Offline / air-gapped** | :white_check_mark: | :x: | :x: | :x: \* |
| **Zero lock-in (pure git tags)** | :white_check_mark: | :x: | :x: | :x: |
| **Dev snapshots (uncommitted state capture)** | :white_check_mark: | :x: | :x: | :x: |
| **ML experiment tracking** | :white_check_mark: | :x: | :x: | :x: |

> **Bold rows = only vmn.**
>
> \* changesets works offline for authoring, but requires GitHub/npm for publishing.

<details>
<summary>Detailed comparisons & migration guides</summary>

See [Already using another tool?](#already-using-another-tool) for step-by-step migration paths from semantic-release, release-please, setuptools-scm, standard-version, and bump2version.

</details>

---
## 🧪 Why vmn for ML experiments?

Most experiment trackers require a server, a cloud account, or both. vmn tracks experiments the same way it tracks versions -- in git and local files.

```sh
vmn exp run my_model --note "baseline ResNet run" -- python train.py
# => 0.2.0-dev.c3d4e5f.a1b2c3d

vmn exp list my_model --sort loss --top 3
# [1] 0.2.0-dev.c3d4e5f.a1b2c3d  (5m ago)  loss=0.12  accuracy=0.94 - baseline ResNet run
# [2] 0.1.0-dev.f7a2b1c.d3e4f5g  (2d ago)  loss=0.34  accuracy=0.91 - with dropout
# [3] 0.1.0-dev.a1b2c3d.e4f5g6h  (3d ago)  loss=0.45  accuracy=0.85 - baseline CNN

vmn exp restore my_model --latest         # checkout exact code state (dirty work auto-saved)
```

### How vmn compares to dedicated experiment trackers

| Capability | vmn | MLflow | W&B | DVC | Neptune |
|:-----------|:---:|:------:|:---:|:---:|:-------:|
| No server required | :white_check_mark: | :x: \* | :x: | :white_check_mark: | :x: |
| No cloud account | :white_check_mark: | :white_check_mark: (self-hosted) | :x: | :white_check_mark: | :x: |
| Free & open source | :white_check_mark: | :white_check_mark: | Free tier | :white_check_mark: | Free tier |
| Metrics tracking | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| Experiment comparison | CLI table | Web UI | Web UI | CLI | Web UI |
| **Full code state capture** | :white_check_mark: | :x: | :x: | partial \*\* | :x: |
| **Uncommitted changes captured** | :white_check_mark: | :x: | :x: | :x: | :x: |
| **One-command state restore** | :white_check_mark: | :x: | :x: | :x: | :x: |
| **Built-in version management** | :white_check_mark: | :x: | :x: | :x: | :x: |
| Artifact tracking | :white_check_mark: (SHA256) | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| Works offline / air-gapped | :white_check_mark: | self-hosted only | :x: | partially | :x: |
| Install complexity | `pip install vmn` | server + DB | account + pip | pip + git config | account + pip |
| Storage | git + local/S3 | database | cloud | git/S3 | cloud |
| Lock-in | zero (git tags + files) | MLflow format | W&B cloud | DVC format | Neptune cloud |

> **Bold rows = only vmn.** Capture your exact working state -- dirty files, local commits, everything -- and restore it with one command.
>
> \* MLflow Tracking can log to local files without a server, but the comparison UI requires `mlflow server`.
> \*\* DVC tracks data/model files via git, but does not capture uncommitted code changes or local-only commits.

vmn is not trying to replace MLflow's web dashboard or W&B's visualization suite. It's for researchers who want **lightweight, git-native experiment tracking** that lives alongside their version management -- without spinning up servers, creating cloud accounts, or leaving the terminal.

### When to use what

**Use vmn when:**
- You want a CLI-first workflow with no context switching
- You work offline or in air-gapped environments
- You need version management and experiment tracking in one tool
- You want zero infrastructure -- no servers, no databases, no accounts
- You prefer git-native storage with no vendor lock-in

**Use MLflow / W&B when:**
- You need rich web visualizations and interactive charts
- Your team relies on shared dashboards and collaboration features
- You are already invested in their ecosystem and integrations

Subcommands cover the full experiment lifecycle:

| Command | What it does |
|:--------|:-------------|
| `vmn exp run` | Capture code state, run a command, record metrics + exit code + duration |
| `vmn exp create` | Capture a snapshot with metrics, parameters, and notes (no command) |
| `vmn exp add` | Log additional metrics, notes, or artifacts to an experiment |
| `vmn exp list` | List experiments with filtering and sorting by any metric |
| `vmn exp show` | Display full experiment details including log history |
| `vmn exp diff` | Metric delta + real source diff between two experiments |
| `vmn exp compare` | Side-by-side metric table across N experiments |
| `vmn exp restore` | Restore the exact code state -- dirty work is auto-saved first |
| `vmn exp export` | Export experiment as a directory or tarball |
| `vmn exp prune` | Clean up old experiments (keep N or older than duration) |

Most actions default to the latest experiment when you omit `-v`. You can address
experiments by full version string, a unique prefix, `--latest`, or `@N` (the N-th
row shown by `vmn exp list`).

---
## 🔑 What only vmn does

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
## 🧬 Experiment Management

`vmn experiment` (alias: `vmn exp`) adds git-native experiment tracking to any
versioned app. No servers, no databases -- experiments are stored alongside your
tags and snapshots. Every experiment ties back to an exact version and commit,
so reproducing results is a `vmn exp restore` away.

### Quick workflow

```sh
# Run a training command; vmn captures code state + records metrics/exit/duration
vmn exp run my_model --note "baseline CNN" -- python train.py

# ...or capture the current dirty state without running anything
vmn exp create my_model --note "baseline CNN" --metrics loss=0.45 acc=0.85

# Append metrics or artifacts to the latest experiment
vmn exp add my_model --metrics loss=0.31 acc=0.92 --attach weights.pt

# Metric delta + real code diff between the last two experiments
vmn exp diff my_model

# Restore the best run (dirty work auto-saved first)
vmn exp restore my_model --latest
```

### Subcommand reference

Every version-taking action defaults to the latest experiment when `-v` is omitted,
and accepts a full version, a unique prefix, `--latest`, or `@N`.

#### run

Create an experiment, run a command, and record its outcome. The child inherits your
terminal (output streams live) and these env vars: `VMN_EXPERIMENT_ID`, `VMN_APP_NAME`,
`VMN_METRICS_FILE`. Any `key=value` lines the process appends to `VMN_METRICS_FILE`
become a metrics entry. `vmn exp run` returns the command's own exit code.

```sh
vmn exp run my_model --note "dropout 0.3" -- python train.py --lr 0.01
# inside train.py:  open(os.environ["VMN_METRICS_FILE"], "a").write("loss=0.31\n")
```

Works on a clean or dirty tree, and cold-starts a fresh repo (auto-init + baseline stamp).

#### create

Capture the current state as an experiment without running a command. Re-running over
the identical code state starts a new run (`.r2`, `.r3`, …) instead of overwriting —
so "same code, different seed" never clobbers a previous run. On a clean tree the diff
hash is zeroed (`...-dev.<commit>.0000000`).

```sh
vmn exp create my_model --note "dropout 0.3" --metrics loss=0.45 acc=0.85
vmn exp create my_model -f params.yml --attach initial_weights.pt
```

`--metrics` records measurements; `-f params.yml` records inputs (`params:`,
`hypothesis:`, `tags:`) — they no longer overwrite each other.

#### add

Append metrics, notes, or artifacts to an experiment (default: the latest).

```sh
vmn exp add my_model --metrics val_loss=0.29 val_acc=0.93
vmn exp add my_model -v @2 --attach checkpoint_epoch10.pt --note "after LR warmup"
```

#### list

List experiments, optionally sorted by a metric.

```sh
vmn exp list my_model                          # all experiments
vmn exp list my_model --sort loss --top 5      # best 5 by loss
vmn exp list my_model --last 10                # most recent 10
```

#### show

Display full details for a single experiment.

```sh
vmn exp show my_model               # latest
vmn exp show my_model -v @1         # the [1] row from list
```

#### diff

Metric/param delta plus a real source diff between two experiments (default: the latest two).

```sh
vmn exp diff my_model                       # latest two
vmn exp diff my_model -v @1 -v @3           # specific runs by index
vmn exp diff my_model --tool delta          # external diff tool
```

#### compare

Side-by-side metric table across N experiments (no code diff — use `exp diff` for that).

```sh
vmn exp compare my_model -v 1.1.0-dev.aaa.bbb -v 1.2.0-dev.ccc.ddd
vmn exp compare my_model --last 3
```

#### restore

Check out the exact code state and retrieve artifacts. If the working tree is dirty,
that work is auto-snapshotted first (and the recovery command is printed) — you never
lose uncommitted changes.

```sh
vmn exp restore my_model --latest
vmn exp restore my_model -v @2
```

#### export

Package an experiment (metadata, metrics, artifacts) into a tarball.

```sh
vmn exp export my_model                              # latest -> <verstr>.tar.gz
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

Declare each metric's goal and a primary metric in `.vmn/{app_name}/conf.yml` so
`list --sort` and the leaderboard know which direction is better. `goal: min` means
lower is better (best-first ascending); `goal: max` means higher is better:

```yaml
experiment:
  metrics:
    loss:     {goal: min, primary: true}
    val_loss: {goal: min}
    acc:      {goal: max}
```

(The legacy `sort: asc|desc` form is still accepted but deprecated in favor of `goal`.)

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
## 📸 Snapshots

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

vmn snapshot show my_model                     # latest by default
vmn snapshot note my_model --note "confirmed: best run"
vmn snapshot diff my_model -v 1.2.0-dev.a1b    # second side defaults to the working tree
vmn snapshot export my_model -o ./experiment_42

# Restore a snapshot (dirty work is auto-saved first); vmn goto also works
vmn snapshot restore my_model -v 1.2.0-dev.a1b2c3d.e4f5g6h
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

Actions: `create` (default), `list`, `show`, `note`, `diff`, `export`, `restore`.
Version-taking actions default to the latest snapshot and accept a full version, a
unique prefix, `--latest`, or `@N`.

| Flag | Description |
|------|-------------|
| `-v`, `--version` | Target a specific snapshot version (prefix / `@N` / `--latest` all work) |
| `--latest` | Use the most recent snapshot |
| `--last N` | Show only the N most recent snapshots (for `list`) |
| `--note` | Attach or update a text note |
| `--to` | Second version for `diff` (defaults to `current`, the working tree) |
| `--tool` | External diff tool (`meld`, `vimdiff`, etc.). Falls back to `git config diff.tool` |
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
## 🔧 Commands

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
vmn stamp -r patch --pr rc my_app         # => 0.1.1-rc.1 (prerelease)
vmn stamp my_app                          # => 0.1.2 (with conventional_commits -- no -r needed)
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

<details>
<summary><strong>vmn release</strong></summary>

```sh
vmn release -v 0.0.1-rc.1 my_app   # explicit version -- tag-only
vmn release my_app                  # auto-detect from current commit
vmn release --stamp my_app          # full stamp flow -- new commit + tag + push
```
Promotes prerelease to final. Idempotent. `-v` and `--stamp` are mutually exclusive.

</details>

<details>
<summary><strong>vmn show</strong></summary>

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

</details>

<details>
<summary><strong>vmn goto</strong></summary>

```sh
vmn goto -v 1.2.3 my_app              # repo + deps restored to exact state
vmn goto my_app                        # latest version on current branch
vmn goto -v 1.2.3 --deps-only my_app  # only checkout dependencies
vmn goto -v 5 --root my_root_app      # checkout to root app version
vmn goto -v 1.2.0-dev.a1b2c3d.e4f5g6h my_model  # restore dev snapshot
```
Deps auto-cloned if missing. Dev restore: checkout base, replay commits, apply working tree patch.

</details>

<details>
<summary><strong>vmn gen</strong></summary>

```sh
vmn gen -t version.j2 -o version.txt my_app
vmn gen -t version.j2 -o version.txt -c custom.yml my_app
```

Template variables: `version`, `base_version`, `name`, `release_mode`, `prerelease`, `previous_version`, `stamped_on_branch`, `release_notes`, `changesets`, `root_name`, `root_version`, `root_services`.

</details>

<details>
<summary><strong>vmn add</strong></summary>

```sh
vmn add -v 0.0.1 --bm build42 my_app
```
Attaches build metadata to an existing version tag (e.g. `0.0.1+build42`). Optional `--vmp` for metadata file path.

</details>

<details>
<summary><strong>vmn config</strong></summary>

```sh
vmn config                  # list all managed apps
vmn config my_app           # interactive TUI editor
vmn config my_app --vim     # open in $EDITOR
vmn config --branch my_app  # branch-specific override
vmn config --global         # repo-level .vmn/conf.yml
```

</details>

<details>
<summary><strong>Release candidates</strong></summary>

Iterate on prereleases, then promote:

```sh
vmn stamp -r major --pr alpha my_app    # 2.0.0-alpha.1
vmn stamp --pr alpha my_app             # 2.0.0-alpha.2
vmn stamp --pr mybeta my_app            # 2.0.0-mybeta.1
vmn release my_app                      # 2.0.0
```

</details>

<details>
<summary><strong>Python library</strong></summary>

vmn can be called programmatically. `vmn_run` accepts a command-line argument list and returns `(exit_code, context)`:

```python
from version_stamp.cli.entry import vmn_run

ret, ctx = vmn_run(["show", "my_app"])
```

> **Note:** `vmn_run` prints to stdout/stderr. To capture output programmatically, wrap calls with `contextlib.redirect_stdout`/`redirect_stderr`.

</details>

<details>
<summary><strong>Environment variables</strong></summary>

| Variable | Description |
|:---------|:------------|
| `VMN_WORKING_DIR` | Override working directory |
| `VMN_LOCK_FILE_PATH` | Custom lock file path (default: per-repo) |
| `GITHUB_TOKEN` / `GH_TOKEN` | Required for GitHub Releases |

</details>

---
## 📦 Version Auto-Embedding

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
## ⚙️ Configuration

vmn auto-generates `.vmn/<app-name>/conf.yml` when an app is first stamped. Edit it directly or use `vmn config` (see [Commands](#commands)). Full `conf.yml` structure:

```yaml
conf:
  template: '[{major}][.{minor}][.{patch}][.{hotfix}][-{prerelease}][.{rcn}][-dev.{dev_commit}.{dev_diff_hash}][+{buildmetadata}]'
  hide_zero_hotfix: true
  extra_info: false
  create_snapshots: false
  conventional_commits: true
  default_release_mode: optional   # "optional" (--orm) or "strict" (-r required). Top-level key, not nested under conventional_commits.
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
      loss: { goal: min, primary: true }
      acc:  { goal: max }
```

> **Migration note:** `create_verinfo_files` has been renamed to `create_snapshots`. The old key still works but prints a deprecation warning.

**Per-branch configuration.** Place `{branch}_conf.yml` next to `conf.yml` in `.vmn/<app>/`. vmn checks for a branch-specific config first and falls back to `conf.yml`. Stale branch configs from other branches are auto-cleaned on stamp.

## 🔄 CI Integration

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
## 🗺️ Roadmap

vmn is actively developed. [File an issue](https://github.com/progovoy/vmn/issues) to vote or suggest.

- [ ] **`vmn exp plot`** -- ASCII metric charts in the terminal (`vmn exp plot --metric loss my_model`)
- [ ] **Monorepo auto-discovery** -- detect apps from Cargo workspaces, pnpm-workspace.yaml, Python namespace packages
- [ ] **PR version annotation** -- GitHub Action that auto-comments the next version using `vmn stamp --dry-run`
- [ ] **Post-stamp hooks** -- run custom commands after a successful stamp (deploy, notify, update docs)
- [ ] **Homebrew tap** -- `brew install vmn`

See the [full roadmap and backlog](https://github.com/progovoy/vmn/issues) for more.

---
## 🔍 Troubleshooting

<details>
<summary><strong>vmn can't find tags / shows wrong version</strong></summary>

Most CI systems default to shallow clones. vmn needs full history and tags:

```yaml
# GitHub Actions
- uses: actions/checkout@v4
  with:
    fetch-depth: 0    # full history
```

Or manually: `git fetch --tags --unshallow`
</details>

<details>
<summary><strong>"Another vmn process is running" / lock file error</strong></summary>

vmn uses a per-repo lock file to prevent concurrent stamps. If a previous run crashed:

```sh
rm .vmn/.vmn.lock           # default location
# or if VMN_LOCK_FILE_PATH is set:
rm "$VMN_LOCK_FILE_PATH"
```
</details>

<details>
<summary><strong>Tag name collision with existing tags</strong></summary>

vmn tags follow the format `{app_name}_{version}`. If your repo already has tags matching this pattern, either rename the app or clean up conflicting tags before the first stamp.
</details>

<details>
<summary><strong>"Dirty" state warnings on stamp</strong></summary>

vmn checks for uncommitted changes and unpushed commits. To stamp despite dirty state, commit or stash your changes first. `vmn show --verbose` shows the exact dirty flags (`pending`, `outgoing`, `detached`).
</details>

---

## 🔀 Already using another tool?

Step-by-step guides for common migration paths:

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
  <a href="https://github.com/progovoy/vmn/issues">File an issue</a> if it didn't -- we'll fix it.
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
