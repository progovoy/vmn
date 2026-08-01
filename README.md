<h1 align="center">vmn</h1>

<p align="center"><strong>A version number that can rebuild your repo.</strong></p>

<p align="center">
  <em>Language-agnostic semantic versioning where a version is a <b>restorable state</b>, not just a label.<br>
  Built for the age of coding agents. Versions live in git tags — no database, no server, no lock-in.</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/v/vmn?logo=pypi&logoColor=white&label=PyPI" alt="PyPI version"></a>
  <a href="https://pypi.org/project/vmn/"><img src="https://img.shields.io/pypi/dw/vmn?logo=pypi&logoColor=white" alt="PyPI downloads"></a>
  <a href="https://github.com/progovoy/vmn"><img src="https://img.shields.io/github/stars/progovoy/vmn?style=flat&logo=github" alt="GitHub stars"></a>
  <a href="https://semver.org"><img src="https://img.shields.io/badge/semver-2.0.0-blue?logo=semver&logoColor=white" alt="Semver"></a>
  <a href="https://conventionalcommits.org"><img src="https://img.shields.io/badge/Conventional%20Commits-1.0.0-%23FE5196?logo=conventionalcommits&logoColor=white" alt="Conventional Commits"></a>
  <a href="https://github.com/progovoy/vmn/blob/master/LICENSE.txt"><img src="https://img.shields.io/github/license/progovoy/vmn" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Rust-000000?logo=rust&logoColor=white" alt="Rust">
  <img src="https://img.shields.io/badge/Go-00ADD8?logo=go&logoColor=white" alt="Go">
  <img src="https://img.shields.io/badge/C++-00599C?logo=cplusplus&logoColor=white" alt="C++">
  <img src="https://img.shields.io/badge/Java-ED8B00?logo=openjdk&logoColor=white" alt="Java">
  <img src="https://img.shields.io/badge/JS/TS-F7DF1E?logo=javascript&logoColor=black" alt="JS/TS">
</p>

---

```sh
pip install vmn

vmn stamp -r patch my_app        # => 0.0.1   (auto-initializes, no setup)

# ...six months and 400 commits later, prod is broken on 0.0.1

vmn goto -v 0.0.1 my_app         # your repo AND every dependency repo,
                                 # exactly as they were when 0.0.1 shipped
```

Every other versioning tool hands you a **string**. vmn hands you a **state you can return to** — and it does it for every repo your product spans, not just the one you're standing in.

That turns out to be exactly what you need when the code is being written by agents that move faster than you can review. Give each one [its own island](#-built-for-ai-assisted-development), capture what it did, and roll back the ones that went sideways.

Uninstall vmn tomorrow and your tags still make sense: it's all plain YAML in git annotated tag messages.

---

**[Install](#-install)** · **[The idea](#-the-idea)** · **[AI agents](#-built-for-ai-assisted-development)** · **[Why vmn](#-why-vmn)** · **[Commands](#-commands)** · **[Config](#️-configuration)** · **[Experiments](#-experiments)** · **[Web UI](#️-web-ui)** · **[Islands](#️-islands-parallel-worktrees)** · **[CI](#-ci)** · **[Help](#-troubleshooting)** · **[Migrate](#-coming-from-another-tool)**

---

## 📦 Install

```sh
pip install vmn          # or: pipx install vmn / uvx vmn
pip install "vmn[ui]"    # + the web dashboard
```

**Requirements:** Python 3.8+, Git 2.10+ (2.17+ recommended). Linux, macOS, Windows/WSL. Nothing platform-specific to configure.

<details>
<summary><strong>Try it in 30 seconds (copy-paste, no existing repo needed)</strong></summary>

```sh
mkdir remote && cd remote && git init --bare && cd ..
git clone ./remote ./local && cd local
echo a >> ./a.txt && git add ./a.txt && git commit -m "first commit" && git push origin master

vmn stamp -r patch my_app   # => 0.0.1

echo b >> ./a.txt && git add ./a.txt && git commit -m "feat: add b" && git push origin master
vmn stamp -r patch my_app   # => 0.0.2

git tag -n1 my_app_0.0.2    # the version metadata is right there in the tag
```

No `vmn init` needed — the first `vmn stamp` initializes the repo and the app. Works in CI, in shallow clones, and fully offline.

</details>

<details>
<summary><strong>Shell completion (bash / zsh / fish / tcsh)</strong></summary>

```sh
vmn --completion-install      # auto-detects your shell, idempotent
vmn --completion              # or just print the script, change nothing
vmn --completion-uninstall    # remove it again
```

All three take an optional explicit shell if auto-detection guesses wrong. After installing, restart your shell. Then `vmn <TAB>` lists commands, `vmn stamp <TAB>` suggests **your actual app names**, and `vmn stamp -r <TAB>` offers the release modes.

</details>

---

## 💡 The idea

Most tools treat a version as a **name for a moment**. vmn treats it as a **handle on a state** — and once you have that, the same primitive answers four different problems.

| Granularity | Command | What gets captured |
|:--|:--|:--|
| **Released** state | `vmn stamp` → `vmn goto` | committed code + the exact commit of every dependency repo |
| **Working** state | `vmn snapshot` | ↑ plus uncommitted changes, unpushed commits, untracked files |
| **Measured** state | `vmn exp` | ↑ plus metrics, params, artifacts, and a run log |
| **Parallel** state | `vmn worktrees` | ↑ materialized *beside* your work instead of on top of it |

Each row is the row above it plus one thing. They aren't four features bolted together — `vmn exp` is literally built on the snapshot primitive, and snapshots reuse the same version grammar as stamps. That's why `vmn goto -v 1.2.0-dev.a1b2c3d.e4f5g6h` works: a snapshot **is** a version.

<details>
<summary><strong>What that buys you, concretely</strong></summary>

**State recovery across repos.** If your product spans five git repos, `vmn stamp` records every dependency's commit hash into the tag. `vmn goto` restores all of them, in parallel, cloning any that are missing. Reproducing a six-month-old bug becomes one command instead of an afternoon of CI archaeology.

**Uncommitted work becomes addressable.** `git stash` is unnamed, local, and single-repo. A WIP commit pollutes history. A snapshot turns your exact messy state — dirty files, local commits, untracked junk, across every dep — into a version string you can name, diff, share, and restore.

**Experiment tracking with no server.** An experiment is a snapshot plus an append-only metrics log. That's the whole design. No tracking server, no database, no cloud account — and unlike every dedicated tracker, the *code state* is captured, not just the numbers.

**Microservice topology.** Version services independently under one root app. Each service keeps its own semver; the root gets a monotonic integer that ticks on every child stamp — one number for "what changed last" across the whole platform.

</details>

<details>
<summary><strong>Version formats vmn understands</strong></summary>

```
1.6.0                        # release
1.6.0-rc.23                  # prerelease
1.6.7.4                      # hotfix — an optional 4th segment
1.6.0-rc.23+build01.Info     # build metadata
1.6.0-dev.a1b2c3d.e4f5g6h    # dev snapshot (commit hash + diff hash)
```

Standard Semver 2.0, plus two additions. The **hotfix segment** lets you ship an emergency fix without burning a patch number, so your release train stays on schedule. The **dev snapshot** is content-addressed: identical code always produces the identical version string, so re-snapshotting an unchanged tree gives you back the same version instead of a duplicate.

</details>

---

## 🤖 Built for AI-assisted development

Coding agents are fast, parallel, and occasionally destructive. Every problem that creates is a *state* problem — which is the thing vmn is already built around.

| What goes wrong with agents | vmn's answer |
|:--|:--|
| The agent doesn't know your versioning conventions and invents its own | `vmn skill --install` — ships vmn's own manual into the agent's instruction file |
| Three agents editing one working tree, clobbering each other | `vmn worktrees` — one isolated island each, deps included |
| An agent trashed your tree and you want the last good state back | `vmn snapshot` / `vmn goto` |
| An agent shouldn't be cutting releases | `--no-stamp` islands where stamping is refused |
| "Which of these 30 runs actually produced the good result?" | `vmn exp` — each number anchored to the tree that produced it |

**The tool ships its own manual.** `vmn skill --install` writes vmn usage instructions straight into your agent's instruction file — `.claude/skills/vmn/SKILL.md`, `.cursorrules`, or `AGENTS.md`. The agent learns your versioning workflow from the tool that implements it, instead of guessing from the repo. The `cursor` and `agents` targets write a marker-delimited block, so re-running updates vmn's section and leaves the rest of your instructions untouched.

```sh
vmn skill --install                  # Claude Agent Skill
vmn skill --install --target cursor  # .cursorrules
vmn skill --install --target agents  # AGENTS.md
```

**Every agent gets its own island.** One command creates a git worktree for your repo *and* every dependency repo, pinned to a known-good state, alongside your work rather than on top of it. Point three agents at three islands and they cannot touch each other's files.

```sh
vmn worktrees create my_app --island-name agent-auth
vmn worktrees create my_app --island-name agent-perf
```

Each island drops an `island.json` manifest — paths, branches, dependency hashes — so an agent can orient itself without being told the layout. Add `--no-stamp` for a read-only island when the agent shouldn't be creating versions at all.

**An undo button that covers the mess.** Agents leave uncommitted edits, half-finished refactors, and untracked scratch files — the exact things `git stash` handles badly and a WIP commit handles worse. `vmn snapshot create` turns all of it (across every dependency repo) into a named version you can come back to. And restores auto-snapshot whatever is currently dirty *before* overwriting it, so an agent can't destroy work you hadn't saved yet.

**Judge the runs, not the vibes.** When an agent is iterating on something measurable — a prompt, a heuristic, a model — `vmn exp run` records the metrics *and* the exact tree that produced them. "Run 14 was best" stays answerable a month later, because run 14's code is still addressable.

> Prefer to read the instructions vmn gives your agent before installing them? They're in **[docs/agent-skill.md](docs/agent-skill.md)**.

---

## ⚡ Why vmn

<table>
<tr><th align="left">Capability</th><th>vmn</th><th>semantic-release</th><th>release-please</th><th>changesets</th></tr>
<tr><td>Language-agnostic</td><td align="center">✅</td><td align="center">JS-centric</td><td align="center">JS-centric</td><td align="center">JS only</td></tr>
<tr><td>Git-tag source of truth</td><td align="center">✅</td><td align="center">✅</td><td align="center">✅</td><td align="center">❌</td></tr>
<tr><td>Conventional commits + changelog</td><td align="center">✅</td><td align="center">✅</td><td align="center">✅</td><td align="center">partial</td></tr>
<tr><td>GitHub Release creation</td><td align="center">✅</td><td align="center">✅</td><td align="center">✅</td><td align="center">❌</td></tr>
<tr><td>Auto-embed version into project files</td><td align="center">✅</td><td align="center">per-plugin</td><td align="center">❌</td><td align="center">JS only</td></tr>
<tr><td><b>Multi-repo dependency tracking</b></td><td align="center">✅</td><td align="center">❌</td><td align="center">❌</td><td align="center">❌</td></tr>
<tr><td><b>State recovery (<code>vmn goto</code>)</b></td><td align="center">✅</td><td align="center">❌</td><td align="center">❌</td><td align="center">❌</td></tr>
<tr><td><b>Microservice / root-app topology</b></td><td align="center">✅</td><td align="center">❌</td><td align="center">❌</td><td align="center">monorepo</td></tr>
<tr><td><b>4-segment hotfix versioning</b></td><td align="center">✅</td><td align="center">❌</td><td align="center">❌</td><td align="center">❌</td></tr>
<tr><td><b>Zero-config start (auto-init)</b></td><td align="center">✅</td><td align="center">❌</td><td align="center">❌</td><td align="center">❌</td></tr>
<tr><td><b>Offline / air-gapped</b></td><td align="center">✅</td><td align="center">❌</td><td align="center">❌</td><td align="center">❌ *</td></tr>
<tr><td><b>Uncommitted-state capture</b></td><td align="center">✅</td><td align="center">❌</td><td align="center">❌</td><td align="center">❌</td></tr>
<tr><td><b>ML experiment tracking</b></td><td align="center">✅</td><td align="center">❌</td><td align="center">❌</td><td align="center">❌</td></tr>
<tr><td><b>Ships agent instructions (<code>vmn skill</code>)</b></td><td align="center">✅</td><td align="center">❌</td><td align="center">❌</td><td align="center">❌</td></tr>
<tr><td><b>Parallel agent isolation (islands)</b></td><td align="center">✅</td><td align="center">❌</td><td align="center">❌</td><td align="center">❌</td></tr>
</table>

**Bold rows are things only vmn does.**
<sub>\* changesets authors offline but needs GitHub/npm to publish.</sub>

<details>
<summary><strong>vs. experiment trackers (MLflow, W&amp;B, DVC, Neptune)</strong></summary>

| Capability | vmn | MLflow | W&B | DVC | Neptune |
|:-----------|:---:|:------:|:---:|:---:|:-------:|
| No server required | ✅ | ❌ \* | ❌ | ✅ | ❌ |
| No cloud account | ✅ | ✅ self-hosted | ❌ | ✅ | ❌ |
| Free & open source | ✅ | ✅ | free tier | ✅ | free tier |
| Metrics + live curves | ✅ | ✅ | ✅ | ❌ | ✅ |
| Web UI | ✅ one command | server + DB | cloud | ❌ | cloud |
| **Full code-state capture** | ✅ | ❌ | ❌ | partial \*\* | ❌ |
| **Uncommitted changes captured** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **One-command state restore** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Stamp-tree / version DAG view** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Built-in version management** | ✅ | ❌ | ❌ | ❌ | ❌ |
| Works offline / air-gapped | ✅ | self-hosted | ❌ | partial | ❌ |
| Install | `pip install vmn` | server + DB | account + pip | pip + git config | account + pip |
| Lock-in | none (git tags + files) | MLflow format | W&B cloud | DVC format | Neptune cloud |

<sub>\* MLflow can log to local files, but the comparison UI needs `mlflow server`. &nbsp; \*\* DVC versions data/model files via git but captures no uncommitted code.</sub>

**Use vmn when** you want a CLI-first, local-first workflow, you work offline or air-gapped, you want versioning and experiments in one tool, or you refuse to run infrastructure to track a training run.

**Use MLflow / W&B when** you need hosted dashboards, team collaboration features, reports, or sweep orchestration.

</details>

<details>
<summary><strong>Is vmn for me?</strong></summary>

| | |
|:--|:--|
| **Any language** — Python, Rust, Go, C++, Java, JS, anything in a git repo | **Microservices** — independent versions per service, one root counter |
| **Multi-repo** — reproducible state recovery across repositories | **Zero config** — no plugins, no pipelines, no ecosystem buy-in |
| **Offline / air-gapped** — works with no network at all | **Zero lock-in** — versions are plain git tags |
| **ML / research** — reproducible snapshots with metrics, no tracking server | **CI** — handles shallow clones automatically |
| **Vibe coding** — agents get their own islands, their own manual, and an undo button | **Fast-moving teams** — capture and roll back state without ceremony |

</details>

---

## 🔧 Commands

| Command | What it does | Example |
|:--------|:-------------|:--------|
| [`stamp`](#stamp) | Create a new version | `vmn stamp -r patch my_app` |
| [`release`](#release) | Promote a prerelease to final | `vmn release my_app` |
| [`show`](#show) | Display version info | `vmn show my_app` |
| [`goto`](#goto) | Restore repo + deps to a version | `vmn goto -v 1.2.3 my_app` |
| [`snapshot`](#snapshot) | Capture uncommitted working state | `vmn snapshot create my_app` |
| [`experiment`](#-experiments) | Track runs with metrics (alias `exp`) | `vmn exp run my_model -- python train.py` |
| [`worktrees`](#️-islands-parallel-worktrees) | Isolated parallel dev islands | `vmn worktrees create my_app` |
| [`ui`](#️-web-ui) | Serve the web dashboard | `vmn ui` |
| [`gen`](#gen) | Render a file from a Jinja2 template | `vmn gen -t ver.j2 -o ver.txt my_app` |
| [`add`](#add) | Attach build metadata to a version | `vmn add -v 1.0.0 --bm build42 my_app` |
| [`config`](#config) | Edit app config (TUI or scriptable) | `vmn config my_app` |
| [`skill`](#skill) | Emit AI-agent instructions for vmn | `vmn skill --install` |
| `init` / `init-app` | Explicit init — rarely needed, `stamp` auto-inits | `vmn init-app -v 1.4.2 my_app` |

**Global flags:** `--debug`, `--version`, `--completion[-install|-uninstall] [SHELL]`

### stamp

```sh
vmn stamp -r patch my_app             # => 0.0.1
vmn stamp -r minor my_app             # => 0.1.0
vmn stamp -r patch --pr rc my_app     # => 0.1.1-rc.1
vmn stamp my_app                      # no -r needed with conventional_commits
vmn stamp --dry-run -r patch my_app   # preview, commit nothing
vmn stamp --pull -r patch my_app      # pull first, retry on conflict
```

Idempotent — it won't re-stamp a commit that already has a version. Auto-initializes the repo and app on first run.

<details>
<summary><strong>Conventional commits, changelogs, GitHub Releases</strong></summary>

Turn on `conventional_commits` and stop typing `-r`. Commit prefixes map to release modes: `fix:` → patch, `feat:` → minor, `BREAKING CHANGE` or `!` after the type → major.

```sh
git commit -m "feat: add search endpoint"
vmn stamp my_app     # => 0.2.0, minor inferred
```

```yaml
conf:
  conventional_commits: true
  default_release_mode: optional   # or "strict"
  changelog:
    path: "CHANGELOG.md"
  github_release:
    draft: false
```

Changelog generation requires `conventional_commits`. GitHub Releases need the `gh` CLI and `GITHUB_TOKEN`.

</details>

<details>
<summary><strong><code>-r</code> vs <code>--orm</code>, and every stamp flag</strong></summary>

**Without `-r`:** works during an in-progress prerelease sequence, or always if `conventional_commits` is on. Otherwise it errors on a release commit.

| Flag | Behavior |
|:----:|:---------|
| `-r patch` | **Strict** — always advances. `0.0.1` → `0.0.2`; `0.0.2-rc.3` → `0.0.3`. |
| `--orm patch` | **Optional** — advances only if no prerelease already exists at the target. |

| Flag | Description |
|:-----|:------------|
| `-r`, `--release-mode` | `major`, `minor`, `patch`, `hotfix`, `micro` |
| `--orm`, `--optional-release-mode` | `major`, `minor`, `patch`, `hotfix` |
| `--pr`, `--prerelease` | Create a prerelease (`--pr rc` → `X.Y.Z-rc.N`) |
| `--pull` | Pull before stamping; retries on conflict |
| `--dry-run` | Preview without committing or tagging |
| `-e`, `--extra-commit-message` | Append text to the stamp commit message |
| `--ov`, `--override-version` | Force a specific version string |
| `--orv`, `--override-root-version` | Force a specific root-app version |
| `--dont-check-vmn-version` | Skip the vmn compatibility check |
| `--git-push-user` / `--git-push-token` | Push credentials (see below) |

**Push credentials.** For checkouts with no credentials of their own (CI runners, containers), `--git-push-user` / `--git-push-token` — or `VMN_GIT_PUSH_USER` / `VMN_GIT_PUSH_TOKEN` — make vmn rewrite the remote to an authenticated HTTPS URL *for that single push only*, leaving your git remote config untouched. `ssh://` and `git@host:` remotes are converted to HTTPS. Both values must be supplied together; a lone one is ignored with a warning. `vmn release` accepts them too.

**`vmn init-app` flags:** `-v/--version` (initial version, default `0.0.0`), `--dry-run`, `--orm/--default-release-mode` (`optional` | `strict`).

</details>

### release

```sh
vmn release my_app                  # auto-detect from the current commit
vmn release -v 0.0.1-rc.1 my_app    # explicit version — tag only
vmn release --stamp my_app          # full stamp flow: commit + tag + push
```

Promotes a prerelease to final. Idempotent. `-v` and `--stamp` are mutually exclusive.

<details>
<summary><strong>Iterating on release candidates</strong></summary>

```sh
vmn stamp -r major --pr alpha my_app   # 2.0.0-alpha.1
vmn stamp --pr alpha my_app            # 2.0.0-alpha.2
vmn stamp --pr mybeta my_app           # 2.0.0-mybeta.1
vmn release my_app                     # 2.0.0
```

</details>

### show

```sh
vmn show my_app              # current version
vmn show --verbose my_app    # full YAML metadata
vmn show --dev my_app        # dev version (commit + diff hash)
vmn show --type my_app       # release / prerelease / metadata
vmn show -u my_app           # unique ID (version + commit hash)
vmn show --root my_platform  # root-app version (an integer)
```

<details>
<summary><strong>Remaining show flags</strong></summary>

| Flag | Description |
|:--|:--|
| `-v`, `--version` | Show info for a specific version |
| `-t`, `--template` | Render with an ad-hoc template |
| `--raw` | Skip template formatting |
| `--conf` | Print the effective app configuration |
| `--from-file` | Read local state instead of git tags |
| `--ignore-dirty` | Don't fail on a dirty working tree |

</details>

### goto

```sh
vmn goto -v 1.2.3 my_app                        # repo + all deps
vmn goto my_app                                 # latest on the current branch
vmn goto -v 1.2.3 --deps-only my_app            # dependencies only
vmn goto -v 5 --root my_platform                # by root-app version
vmn goto -v 1.2.0-dev.a1b2c3d.e4f5g6h my_model  # restore a dev snapshot
vmn goto -v 1.2.3 --pull my_app                 # fetch first if not found locally
```

Missing dependency repos are cloned automatically, in parallel. Restoring a dev version checks out the base commit, replays local commits, then applies the working-tree patch.

### snapshot

Capture your exact working state — uncommitted changes, unpushed commits, untracked files, across every dependency — as a deterministic version you can restore. No WIP commits, no stash juggling.

> **Use it when:** you're three hours into a refactor that half-works, and you want to try a completely different approach without losing this one. Committing it pollutes history with something you may throw away. `git stash` drops your untracked files' relationship to the deps and gives you an unnamed blob you'll never find again. Snapshot it, get a version string, try the other approach — and if the new one is worse, restore and carry on.
>
> **Also good for:** handing a colleague a bug that only reproduces with your local debug instrumentation; parking work before an agent starts editing the same files; a nightly "what did today look like" marker.

```sh
vmn snapshot create my_app --note "promising results"
# => 1.2.0-dev.a1b2c3d.e4f5g6h

vmn snapshot list my_app
vmn snapshot diff my_app -v 1.2.0-dev.a1b   # second side defaults to your working tree
vmn snapshot restore my_app --latest        # dirty work is auto-saved first
```

<details>
<summary><strong>Snapshot vs. experiment — which do I want?</strong></summary>

An experiment *is* a snapshot plus an append-only metrics log. Use a plain snapshot to save or restore code state; use an experiment when you want to track and compare runs.

| | `vmn snapshot` | `vmn exp` |
|:--|:--|:--|
| Captures code state (tracked + untracked + deps) | ✅ | ✅ |
| Metrics / params / notes | one note | ✅ append-only log |
| Run a command, record its outcome | ❌ | ✅ (`exp run`) |
| Compare across runs | diff only | diff + metric deltas + `compare` |
| Typical use | saving WIP before a risky change | tracking and comparing runs |

</details>

<details>
<summary><strong>What's inside a snapshot</strong></summary>

```
.vmn/{app}/snapshots/{version}/
  metadata.yml            # version, branch, timestamp, note, dirty states
  working_tree.patch      # uncommitted changes (git diff HEAD)
  local_commits.patch     # commits not yet pushed
  untracked_files.tar.gz  # untracked files
  deps/{dep_name}/...     # the same three, per dependency repo
  artifacts/{filename}    # attached files
```

Dependency state feeds into the content hash, so two snapshots differing only inside a dep get different version strings.

> **Note:** unlike `vmn goto`, snapshot restore does *not* clone a missing dependency — it warns and skips it. Deps are expected to be on disk already.

</details>

<details>
<summary><strong>All snapshot flags</strong></summary>

Actions: `create` (default), `list`, `show`, `note`, `diff`, `export`, `restore`. Version-taking actions default to the latest and accept a full version, a unique prefix, `--latest`, or `@N`.

| Flag | Description |
|------|-------------|
| `-v`, `--version` | Target a specific snapshot |
| `--latest` | Use the most recent snapshot |
| `--last N` | Show only the N most recent (for `list`) |
| `--note` | Attach or update a note |
| `--to` | Second version for `diff` (default: `current`, your working tree) |
| `--tool` | External diff tool; falls back to `git config diff.tool` |
| `-o`, `--output` | Export destination |
| `--meta` / `--meta-file` | Extra metadata, repeatable `key=value` or a YAML file |
| `--filter` | Filter `list` by `key=value`, repeatable |
| `--verbose` | Full ISO timestamps |
| `--backend` / `--bucket` / `--endpoint-url` / `--prefix` | `local` (default) or `s3`; S3 works with MinIO, Spaces, etc. |

</details>

### gen

```sh
vmn gen -t version.j2 -o version.txt my_app
vmn gen -t version.j2 -o version.txt -c custom.yml my_app
```

Template variables: `version`, `base_version`, `name`, `release_mode`, `prerelease`, `previous_version`, `stamped_on_branch`, `release_notes`, `changesets`, `root_name`, `root_version`, `root_services`.

### add

```sh
vmn add -v 0.0.1 --bm build42 my_app
vmn add -v 0.0.1 --bm build42 --vmp ./build.yml --vmu https://ci/build/42 my_app
```

Attaches build metadata to an existing tag (`0.0.1+build42`). `--vmp` records a path to a YAML metadata file; `--vmu` an associated URL.

### config

```sh
vmn config                       # list all managed apps
vmn config my_app                # interactive TUI
vmn config my_app --vim          # open in $EDITOR
vmn config --branch my_app       # override for the current branch
vmn config --root my_platform    # root-app config
vmn config --global              # repo-level .vmn/conf.yml
```

<details>
<summary><strong>Non-interactive (<code>config gen</code>) — for CI and scripting</strong></summary>

Creates a config file with no TTY. Never overwrites an existing one.

```sh
vmn config gen my_app                              # .vmn/my_app/conf.yml
vmn config gen --branch my_app                     # branch config, seeded from the effective conf
vmn config gen --branch --root my_platform         # branch config for a root app
vmn config gen --branch --sync-dep-branches my_app # pin each branch-tracked dep to its current branch
```

`--sync-dep-branches` is only valid with `config gen --branch`.

</details>

### skill

Emits vmn's own usage instructions for AI coding agents — see [Built for AI-assisted development](#-built-for-ai-assisted-development).

```sh
vmn skill --install                     # .claude/skills/vmn/SKILL.md (default)
vmn skill --install --target cursor     # .cursorrules
vmn skill --install --target agents     # AGENTS.md
vmn skill --install --methodology       # + opinionated TDD / worktree rules
vmn skill --install --force             # overwrite an existing Claude SKILL.md
vmn skill                               # just print it
```

`--install` finds the managed repo root even from a nested directory. The Claude target refuses to clobber an existing skill without `--force`; the Cursor and AGENTS targets rewrite only vmn's marker block and leave your other instructions alone. Full text: **[docs/agent-skill.md](docs/agent-skill.md)**.

<details>
<summary><strong>Using vmn as a Python library</strong></summary>

```python
from version_stamp.cli.entry import vmn_run

ret, ctx = vmn_run(["show", "my_app"])
```

`vmn_run` takes an argument list and returns `(exit_code, context)`. It prints to stdout/stderr, so wrap calls in `contextlib.redirect_stdout` / `redirect_stderr` to capture output.

</details>

<details>
<summary><strong>Environment variables</strong></summary>

Read by vmn:

| Variable | Description |
|:---------|:------------|
| `VMN_WORKING_DIR` | Override the working directory |
| `VMN_LOCK_FILE_PATH` | Custom lock file path (default `.vmn/vmn.lock`) |
| `GITHUB_TOKEN` / `GH_TOKEN` | Required for GitHub Releases |
| `VMN_GIT_PUSH_USER` / `VMN_GIT_PUSH_TOKEN` | Fallbacks for the `--git-push-*` flags |
| `VMN_UI_TOKEN` | Fallback for `vmn ui --token` |

Set *by* vmn for the child process of `vmn exp run`:

| Variable | Description |
|:---------|:------------|
| `VMN_EXPERIMENT_ID` | The verstr of the running experiment |
| `VMN_APP_NAME` | The app name |
| `VMN_METRICS_FILE` | Path your command appends `key=value` metrics to |

</details>

---

## ⚙️ Configuration

vmn writes `.vmn/<app>/conf.yml` when an app is first stamped. Edit it directly or via [`vmn config`](#config).

<details>
<summary><strong>Full <code>conf.yml</code> reference</strong></summary>

```yaml
conf:
  template: '[{major}][.{minor}][.{patch}][.{hotfix}][-{prerelease}][.{rcn}][-dev.{dev_commit}.{dev_diff_hash}][+{buildmetadata}]'
  hide_zero_hotfix: true
  extra_info: false
  create_snapshots: false
  conventional_commits: true
  default_release_mode: optional   # "optional" (--orm) or "strict" (-r). Top-level, not nested.
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
    storage:            # same shape as snapshot_storage; CLI flags override
      backend: local
```

> `create_verinfo_files` was renamed to `create_snapshots`. The old key still works but warns.

</details>

<details>
<summary><strong>Auto-embedding the version into project files</strong></summary>

`vmn stamp` can write the version straight into your project files:

| Backend | File | Field |
|:--------|:-----|:------|
| `npm` | `package.json` | `version` |
| `cargo` | `Cargo.toml` | `version` |
| `poetry` | `pyproject.toml` | `[tool.poetry].version` |
| `pep621` | `pyproject.toml` | `[project].version` |

```yaml
version_backends:
  npm:
    path: "relative/path/to/package.json"
```

**Regex find-and-replace in any file:**

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

`{{VMN_VERSION_REGEX}}` matches any vmn version string ([playground](https://regex101.com/r/JoEvaN/1)).

**Jinja2 rendering:**

```yaml
version_backends:
  generic_jinja:
    - input_file_path: f1.jinja2
      output_file_path: jinja_out.txt
      custom_keys_path: custom.yml
```

Same variables as [`vmn gen`](#gen).

**Or skip file injection entirely** — with hatch-vcs, read the version from the tag at build time:

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[tool.hatch.version]
source = "vcs"
tag-pattern = "my_app_(?P<version>.*)"
```

</details>

<details>
<summary><strong>Per-branch configuration</strong></summary>

A branch can override the app config. The canonical location:

```
.vmn/<app>/branch_conf/<branch>/conf.yml        # slashes in the branch name
.vmn/<app>/branch_conf/<branch>/root_conf.yml   # become real directories
```

Create one with `vmn config --branch <app>` or `vmn config gen --branch <app>` — both seed it from the currently effective config. vmn resolves a branch config first and falls back to `conf.yml`.

Two older layouts are still *read*: flat `<branch-with-dashes>_conf.yml` and nested `<branch>/conf.yml` beside `conf.yml`. Precedence is canonical > flat > legacy, and legacy files are auto-migrated to canonical on the next `vmn stamp`. Stale branch configs from other branches are cleaned up on stamp.

</details>

---

## 🧬 Experiments

Local-first experiment tracking for any versioned app. Experiments are plain files under `.vmn/{app}/experiments/` — git-ignored, never committed or pushed. No server, no database, no account.

> **Use it when:** you're tuning something over days — hyperparameters, a cache policy, a retrieval prompt, compiler flags — editing code between every run. Two weeks later someone asks *"what did we do to get 0.91?"* and the honest answer is nobody knows, because the tree that produced it was overwritten twenty runs ago. An experiment pins each number to the exact code that produced it, so `exp diff` can show you the metric delta and the source change side by side.
>
> **Also good for:** benchmark and load-test runs where the config is the variable; agent-driven iteration loops; any "I tried 30 things and one worked" workflow.

```sh
# Capture code state, run the command, record metrics + exit code + duration
vmn exp run my_model --note "baseline CNN" -- python train.py
# => 0.1.0-dev.a1b2c3d.e4f5g6h

# Change the model, run again — a distinct experiment, even on the same commit
vmn exp run my_model --note "with dropout" -- python train.py

# Leaderboard, best loss first
vmn exp list my_model --sort loss --top 3

# Metric delta AND a real source diff between two runs
vmn exp diff my_model

# Winner — restore that exact state (dirty work auto-saved first)
vmn exp restore my_model --latest
```

**No training script required.** An experiment is a tree snapshot plus a metrics log — ML training is one use case; config sweeps, benchmarks, and load tests work identically.

Your command reports metrics by appending `key=value` lines to `$VMN_METRICS_FILE`. Prefix a line with `step=N` to build a per-step series — vmn tails the file *during* the run, so training curves appear live in the web UI.

<details>
<summary><strong>Subcommands at a glance</strong></summary>

| Command | What it does |
|:--------|:-------------|
| `exp run` | Capture state, run a command, record metrics + exit code + duration |
| `exp create` | Capture a snapshot with metrics/params/notes, no command |
| `exp add` | Append metrics, notes, or artifacts to an existing experiment |
| `exp list` | List experiments, filter and sort by any metric |
| `exp show` | Full detail for one experiment, including its log |
| `exp diff` | Metric delta + real source diff between two experiments |
| `exp compare` | Side-by-side metric table across N experiments |
| `exp restore` | Restore the exact code state (dirty work auto-saved) |
| `exp export` | Package an experiment as a directory or tarball |
| `exp prune` | Clean up by count (`--keep N`) or age (`--older-than 30d`) |

Version-taking actions default to the latest experiment and accept a full version, a unique prefix, `--latest`, or `@N` (the row index from `exp list`).

Re-running over an identical code state starts a new run (`.r2`, `.r3`, …) rather than overwriting — so "same code, different seed" never clobbers a previous run.

</details>

<details>
<summary><strong>Metrics schema — teaching vmn which direction is better</strong></summary>

```yaml
experiment:
  metrics:
    loss:     {goal: min, primary: true}   # lower is better; default sort key
    val_loss: {goal: min}
    acc:      {goal: max}
```

`goal: min` sorts best-first ascending, `goal: max` descending. `primary: true` sets the default sort for `list` and the web-UI leaderboard.

</details>

📖 **[Full experiments guide →](docs/experiments.md)** — the metrics protocol, structured params, addressing, S3 storage, and the no-script workflow.

---

## 🖥️ Web UI

A dashboard over data you already have. It reads git tags and `.vmn/` files directly; the whole SPA ships inside the wheel.

```sh
pip install "vmn[ui]"
vmn ui               # http://127.0.0.1:8265, opens your browser
```

- **Leaderboard** — sortable, goal-aware metric columns; `@N` indices matching the CLI.
- **Run detail** — params vs. metrics, **live training curves**, full log, copy-paste reproduce commands.
- **Compare** — pick two runs for a metric-delta table plus a color-coded code diff.
- **Stamp tree** — your version history as a DAG, colored by release mode, with root-app topology and cross-repo dependency pins. *No experiment tracker has this — it falls out of vmn's git-tag model.*
- **Actions** — run `stamp` / `restore` / `goto` / `release` / `prune` from the browser. Each runs as a real `vmn` subprocess, so it takes the repo lock correctly and streams its log live.

<details>
<summary><strong>Team / remote deployment</strong></summary>

```sh
vmn ui --host 0.0.0.0 --port 8265 \
       --token "$VMN_UI_TOKEN" \
       --data-dir /srv/vmn-ui \
       --repo /srv/checkouts/model-a --repo /srv/checkouts/model-b
```

- **Workspaces** — one server hosts many isolated checkouts. Several can be clones of the *same* repo (one per branch or user); a stamp in one never touches another. S3 buckets register as read-only experiment sources with no local repo at all.
- **Auth** — a shared bearer token; put TLS and user management behind a reverse proxy.
- **`--read-only`** disables every mutation endpoint.
- **`--data-dir`** (default `~/.vmn-ui`) holds the workspace registry and a derived SQLite cache that keeps leaderboards instant; `--no-index` reads sources directly.

The whole `/api/v1/...` surface is documented at `/api/docs`.

</details>

📖 **[Full UI guide →](docs/ui.md)**

---

## 🏝️ Islands (parallel worktrees)

An island is a set of git worktrees — your main repo plus every dependency — pinned to a known-good state, sitting *beside* your work instead of on top of it.

> **Use it when:** you want to run three agents on three features at once, in a product that spans four repos. Doing that by hand means a `git worktree add` per repo per feature, with every dependency checked out at the exact hash the last good version recorded — twelve checkouts you have to get right, and re-derive from tag metadata each time. One `vmn worktrees create` does it, and the agents physically cannot touch each other's files.
>
> **Also good for:** reproducing a customer bug on 2.1.0 while your current work stays exactly where it is — `vmn goto` would move *your* checkout, an island gives you that state alongside it. Or a throwaway `--no-stamp` island for a risky experiment you fully intend to delete.

| Problem | Without islands | With `vmn worktrees` |
|---------|----------------|---------------------|
| Parallel features | `git worktree` + manually clone each dep at the right hash | one command |
| Dependency alignment | `vmn goto` mutates your checkout | islands are non-destructive copies |
| Agent isolation | agents collide in one tree | each agent gets its own island |
| Reproducibility | "works on my machine" | `island.json` records the exact state |

```sh
vmn worktrees create my_app                                    # from current HEAD, auto-named
vmn worktrees my_app                                           # 'create' is the default action
vmn worktrees create my_app --island-name feat-auth -fv 2.1.0  # from a version
vmn worktrees create my_app --island-name feat-perf -fb develop # from a branch
vmn worktrees create my_app --island-name ci-test --no-stamp   # read-only: stamping disabled
vmn worktrees list
vmn worktrees remove feat-auth                                 # removes worktrees and branches
```

<details>
<summary><strong>Layout, branch model, and the manifest</strong></summary>

```
../vmn-islands/                # configurable with --base-path
  feat-auth/
    my_project/                # main repo — git worktree on a new branch
    auth_service/              # dep — git worktree, detached HEAD
    payment_gateway/           # dep — git worktree, detached HEAD
    island.json                # machine-readable manifest
```

- **Main repo** gets a new branch `island/{name}/{original-branch}` — ready for commits and PRs.
- **Dependencies** are detached HEAD at the exact hash recorded when the source version was stamped. Detaching sidesteps git's rule that the same branch can't be checked out in two worktrees.
- **`--editable-dep <name>`** gives that dep its own `island/{name}/{dep-branch}` for cross-repo work.

`island.json` records name, creation time, app, version, source ref, the main repo's path/branch/remote, and every dep's path/hash/branch/remote — so an agent can orient itself without being told the layout.

**`--shallow-deps`** is a fallback, not a speed knob: if a dependency repo is already on disk, vmn always makes a worktree from it. The flag only applies when a dep is *missing* locally, permitting a `--depth 1` clone from its remote. Without it, a missing dep is a hard error.

</details>

<details>
<summary><strong>Stamping inside an island</strong></summary>

`vmn stamp` works inside islands by default. The version commit stays on the local island branch and vmn pushes **only the tag**, so it never assigns the island branch to `origin/main` or publishes the branch. `--pull` fetches remote version state without merging another branch into the island.

Use `--no-stamp` for islands meant for CI, testing, review, or agents that shouldn't create versions.

</details>

---

## 🔄 CI

```yaml
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0          # required — vmn reads tags and history
  - uses: progovoy/vmn-action@latest
    with:
      app-name: my_app
      do-stamp: true
      stamp-mode: patch
    env:
      GITHUB_TOKEN: ${{ github.token }}
```

`fetch-depth: 0` is not optional — vmn computes the next version from git history and tags.

---

## 🔍 Troubleshooting

<details>
<summary><strong>vmn can't find tags / reports the wrong version</strong></summary>

Most CI systems shallow-clone by default. vmn needs full history:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
```

Or manually: `git fetch --tags --unshallow`

</details>

<details>
<summary><strong>"Another vmn process is running" / lock file error</strong></summary>

vmn takes a per-repo lock so concurrent stamps can't interleave. If a previous run crashed:

```sh
rm .vmn/vmn.lock            # default location
# or, if VMN_LOCK_FILE_PATH is set:
rm "$VMN_LOCK_FILE_PATH"
```

</details>

<details>
<summary><strong>Tag name collision</strong></summary>

vmn tags are `{app_name}_{version}` (slashes in app names become `-`). If your repo already has tags matching that pattern, rename the app or clean up the conflicting tags before the first stamp.

</details>

<details>
<summary><strong>"Dirty" state warnings on stamp</strong></summary>

vmn refuses to stamp over uncommitted changes or unpushed commits. Commit or stash first — or capture the mess with `vmn snapshot create` so you can come back to it. `vmn show --verbose` prints the exact flags (`pending`, `outgoing`, `detached`).

</details>

<details>
<summary><strong>App name rejected</strong></summary>

App names cannot contain `-` or start with `/`. Use `_`, or `/` to express root-app topology (`my_platform/auth`).

</details>

---

## 🔀 Coming from another tool?

| From | Guide |
|:--|:--|
| semantic-release | [migration guide](docs/vmn-vs-semantic-release.md) |
| release-please | [migration guide](docs/vmn-vs-release-please.md) |
| setuptools-scm | [migration guide](docs/vmn-vs-setuptools-scm.md) |
| standard-version *(archived 2023)* | [migration guide](docs/migrating-from-standard-version.md) |
| bump2version | [migration guide](docs/migrating-from-bump2version.md) |

Your existing tags keep working — vmn uses its own `{app}_{version}` format and won't collide with `v1.2.3`-style tags.

---

<h3 align="center">Stop archaeology. Start with a version you can go back to.</h3>

```sh
pip install vmn
```

<p align="center">
  Star the repo if vmn saved you an afternoon.
  <a href="https://github.com/progovoy/vmn/issues">File an issue</a> if it cost you one — we'll fix it.
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
