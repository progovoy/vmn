# vmn vs release-please

> [vmn](https://github.com/final-israel/vmn) is a language-agnostic, git-tag-based versioning CLI.
> This page compares vmn with [release-please](https://github.com/googleapis/release-please) to help you choose the right tool.

## Overview

**release-please** is a Google-maintained tool that automates releases by
opening GitHub Pull Requests. When conventional commits land on the main branch,
release-please creates (or updates) a "Release PR" that bumps the version and
updates the changelog. Merging the PR triggers a GitHub Release.

**vmn** stamps versions directly as annotated git tags with rich metadata. It
works from the command line, with any git host, and adds capabilities like
multi-repo dependency tracking and repository state recovery.

## Feature Comparison

| Feature | vmn | release-please |
| --- | --- | --- |
| Language support | Any (Python, Node, Rust, Go, ...) | Any (via release-type config) |
| Git host | Any (GitHub, GitLab, Bitbucket, self-hosted) | GitHub only (GitLab support experimental) |
| Release mechanism | Direct CLI command + git tags | Pull Request bot |
| Runtime dependency | Python 3 | Node.js |
| Conventional commits | Supported (optional) | Required |
| Manual release mode | `vmn stamp -r patch/minor/major` | Not supported |
| Multi-repo dependency tracking | Built-in | Not available |
| Root app / microservice topology | Built-in (`root_app/service`) | Manifest plugin (monorepo, not multi-repo) |
| State recovery (`goto`) | `vmn goto -v 1.2.3 app` | Not available |
| 4-segment hotfix versions | `major.minor.patch.hotfix` | Not supported |
| Prerelease support | Built-in (`--pr` flag) | Via prerelease branches |
| Version auto-embedding | package.json, Cargo.toml, pyproject.toml, Jinja2 templates | Updates version files per release-type |
| Changelog generation | Supported | Built-in (core feature) |
| CI requirement | None (works locally) | GitHub Actions or CI |
| Offline / air-gapped use | Local file backend | Not supported |
| Monorepo support | Root app + child services | Manifest plugin with linked components |

## When vmn Is a Better Fit

### You are not on GitHub

release-please is tightly coupled to GitHub. It uses the GitHub API to create
pull requests, manage releases, and track state. If your code lives on GitLab,
Bitbucket, or a self-hosted git server, vmn works identically because it only
needs git.

### You want direct control over versioning

release-please follows an opinionated PR-based workflow: commits accumulate,
a bot opens a PR, and merging that PR creates the release. vmn lets you stamp
a version whenever you choose, from CI or from your laptop, with a single
command.

### You manage multi-repo dependencies

vmn can record the exact commit hash and remote of every dependent repository
at stamp time. release-please does not track cross-repository state.

### You need state recovery

`vmn goto -v 1.2.3 my_app` checks out every tracked repository to the precise
state recorded when version 1.2.3 was stamped. release-please has no equivalent.

### You use a microservice topology

vmn's root-app concept versions a parent application alongside its child
services, recording which service versions were active in each root-app release.
release-please's manifest plugin supports monorepos but not multi-repo service
topologies.

### You need hotfix versioning

vmn provides a fourth version segment (`major.minor.patch.hotfix`) for
hotfix workflows that fall outside standard three-segment semver.

### You work in air-gapped environments

vmn's local file backend allows version management without any network access,
which is critical for air-gapped or classified environments.

## When release-please Is a Better Fit

- You want a fully automated, PR-based release workflow on GitHub with no
  manual version decisions.
- You rely on automatically generated, well-formatted changelogs as a core
  part of your release process.
- Your team prefers a review step (the Release PR) before any version is
  finalized.
- You are already using Google's release tooling and want consistency across
  your organization.

## Quick Start with vmn

Install vmn and stamp your first version in under a minute:

```bash
# Install
pip install vmn
# or: pipx install vmn
# or: uvx vmn

# Initialize vmn in your repository (once per repo)
vmn init

# Initialize your application (once per app)
vmn init-app my_app

# Stamp a patch release
vmn stamp -r patch my_app

# Show the current version
vmn show my_app

# Check out the repo state at a specific version
vmn goto -v 1.0.1 my_app
```

### Optional: Enable Conventional Commits

If you want vmn to detect the release mode automatically from commit messages
(similar to release-please), add this to `.vmn/my_app/conf.yml`:

```yaml
conf:
  conventional_commits:
    enabled: true
```

Then stamp without specifying `-r`:

```bash
vmn stamp my_app
# vmn reads commits since the last stamp and picks major/minor/patch
```

### Auto-Embed Versions

Write the version into your project files automatically:

```yaml
# .vmn/my_app/conf.yml
conf:
  version_backends:
    npm:
      - path: package.json
    pep621:
      - path: pyproject.toml
    cargo:
      - path: Cargo.toml
```

## Migrating from release-please

1. **Install vmn:** `pip install vmn`
2. **Initialize:** `vmn init && vmn init-app my_app`
3. **Start at your current version:** vmn will discover existing version tags
   or you can stamp a new version to establish a baseline.
4. **Configure version backends** in `.vmn/my_app/conf.yml` to replace any
   version-file updates that release-please was performing.
5. **Remove release-please config:** Delete `release-please-config.json`,
   `.release-please-manifest.json`, and the GitHub Actions workflow that runs
   release-please.
6. **Update CI:** Replace the release-please action with
   `vmn stamp -r <mode> my_app` (or use conventional commits for automatic
   mode detection).

## Further Reading

- [vmn GitHub repository](https://github.com/final-israel/vmn)
- [vmn README](https://github.com/final-israel/vmn#readme)
- [release-please documentation](https://github.com/googleapis/release-please)
