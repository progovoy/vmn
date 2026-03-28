# vmn vs setuptools-scm

> [vmn](https://github.com/final-israel/vmn) is a language-agnostic, git-tag-based versioning CLI.
> This page compares vmn with [setuptools-scm](https://github.com/pypa/setuptools-scm) to help Python developers choose the right tool.

## Overview

**setuptools-scm** extracts Python package versions from git tags at build time.
It hooks into setuptools (or hatchling) so that `python -m build` automatically
derives the version string from `git describe`. There is no explicit "stamp"
step; the version is inferred from the repository state.

**vmn** takes an explicit approach: you run a command to stamp a version, and vmn
creates an annotated git tag with structured YAML metadata. vmn is not tied to
Python and works with any language or build system.

## Feature Comparison

| Feature | vmn | setuptools-scm |
| --- | --- | --- |
| Language support | Any (Python, Node, Rust, Go, ...) | Python only |
| Build system integration | Separate CLI tool | setuptools, hatchling, flit |
| Version source of truth | Annotated git tags with YAML metadata | `git describe` output |
| Version determination | Explicit (`vmn stamp -r patch`) | Implicit (derived at build time) |
| Conventional commits | Supported (optional) | Not supported |
| Manual release mode | `vmn stamp -r patch/minor/major` | Manual `git tag` |
| Multi-repo dependency tracking | Built-in | Not available |
| Root app / microservice topology | Built-in (`root_app/service`) | Not available |
| State recovery (`goto`) | `vmn goto -v 1.2.3 app` | Not available |
| 4-segment hotfix versions | `major.minor.patch.hotfix` | Not supported |
| Prerelease support | Built-in (`--pr` flag) | Dev versions from distance to tag |
| Version auto-embedding | package.json, Cargo.toml, pyproject.toml, Jinja2 | `_version.py` or `pyproject.toml` |
| pyproject.toml integration | pep621 version backend | Native (build-time write) |
| Dirty version handling | Stamps are always clean | Appends `.d{date}` for dirty trees |
| CI requirement | None (works locally) | None (works locally) |
| Offline / air-gapped use | Local file backend | Works offline (git-only) |

## When vmn Is a Better Fit

### You version more than Python packages

setuptools-scm is designed exclusively for the Python packaging ecosystem. If
your project includes services written in Rust, Go, Node.js, or any other
language, vmn versions all of them with the same tool and the same workflow.

### You want explicit version control

setuptools-scm infers the version from git state. Between tags, it produces
development versions like `1.2.3.dev4+gabc1234`. This is convenient for
automated builds but means you do not control exactly which version string
appears until you manually create a git tag.

vmn gives you explicit control: `vmn stamp -r patch my_app` increments the
version, creates the tag, and optionally writes the version into your project
files, all in one atomic operation.

### You manage multi-repo dependencies

vmn records the exact commit hash of every tracked dependency repository when
a version is stamped. setuptools-scm has no concept of cross-repo dependencies.

### You need state recovery

`vmn goto -v 1.2.3 my_app` restores every tracked repository to the exact
commit recorded at stamp time. setuptools-scm does not track this information.

### You use microservice or root-app topologies

vmn's root-app concept lets you version a parent application together with
its child services, recording which service versions compose each release.

### You need hotfix versioning

vmn supports a fourth version segment (`major.minor.patch.hotfix`) for hotfix
workflows that do not map to standard three-segment semver.

### You want conventional commits integration

vmn can read conventional commit messages to automatically determine the release
mode (major, minor, or patch) without manual input. setuptools-scm does not
analyze commit messages.

## When setuptools-scm Is a Better Fit

- You work exclusively in the Python ecosystem and want zero-configuration
  version management that "just works" with setuptools or hatchling.
- You prefer implicit versioning where every build gets a unique version
  string derived from git state, including development builds.
- You want tight integration with Python build tools (`pyproject.toml`
  `[tool.setuptools_scm]`) with no additional CLI to learn.
- You need every intermediate commit to produce a valid, installable Python
  package version automatically.

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

### Writing the Version into pyproject.toml

vmn can embed the version directly into `pyproject.toml`, achieving a similar
result to setuptools-scm's build-time version injection:

```yaml
# .vmn/my_app/conf.yml
conf:
  version_backends:
    pep621:
      - path: pyproject.toml
```

After each `vmn stamp`, the `version` field in your `[project]` table is
updated automatically.

### Using vmn with hatchling

If you use hatchling as your build backend, you can pair vmn with the
[hatch-vcs](https://github.com/ofek/hatch-vcs) plugin or simply rely on
vmn's pep621 backend to write the version into `pyproject.toml` before each
build.

### Optional: Enable Conventional Commits

```yaml
# .vmn/my_app/conf.yml
conf:
  conventional_commits: true
```

Then stamp without specifying `-r`:

```bash
vmn stamp my_app
# vmn reads commits since the last stamp and picks major/minor/patch
```

## Migrating from setuptools-scm

1. **Install vmn:** `pip install vmn`
2. **Initialize:** `vmn init && vmn init-app my_app`
3. **Stamp your current version:** If you already have git tags in the format
   setuptools-scm uses (e.g., `v1.2.3`), you can stamp a new vmn version to
   establish a baseline: `vmn stamp -r patch my_app`.
4. **Configure the pep621 backend** in `.vmn/my_app/conf.yml` so vmn writes
   the version into `pyproject.toml` on each stamp.
5. **Update pyproject.toml:** Remove the `[tool.setuptools_scm]` section and
   the `setuptools-scm` build dependency. Set a static `version` field under
   `[project]` (vmn will maintain it).
6. **Update your build workflow:** Before `python -m build`, run
   `vmn stamp -r <mode> my_app` (or rely on conventional commits).

### Before (setuptools-scm)

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=64", "setuptools-scm>=8"]

[project]
dynamic = ["version"]

[tool.setuptools_scm]
```

### After (vmn)

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=64"]

[project]
version = "1.2.3"  # maintained by vmn
```

```yaml
# .vmn/my_app/conf.yml
conf:
  version_backends:
    pep621:
      - path: pyproject.toml
```

## Further Reading

- [vmn GitHub repository](https://github.com/final-israel/vmn)
- [vmn README](https://github.com/final-israel/vmn#readme)
- [setuptools-scm documentation](https://setuptools-scm.readthedocs.io/)
