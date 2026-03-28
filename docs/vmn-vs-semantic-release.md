# vmn vs semantic-release

> [vmn](https://github.com/final-israel/vmn) is a language-agnostic, git-tag-based versioning CLI.
> This page compares vmn with [semantic-release](https://github.com/semantic-release/semantic-release) to help you choose the right tool.

## Overview

**semantic-release** automates version management and package publishing for
Node.js projects. It reads conventional commit messages, determines the next
version, generates release notes, and publishes artifacts to npm (or other
registries via plugins).

**vmn** takes a different approach: it stamps explicit semantic versions as
annotated git tags with rich metadata, works with any language, and leaves
publishing decisions to you.

## Feature Comparison

| Feature | vmn | semantic-release |
| --- | --- | --- |
| Language support | Any (Python, Node, Rust, Go, ...) | Primarily Node.js; others via plugins |
| Runtime dependency | Python 3 | Node.js |
| Version source of truth | Annotated git tags with YAML metadata | Git tags (created after publish) |
| Conventional commits | Supported (optional) | Required |
| Manual release mode | `vmn stamp -r patch/minor/major` | Not supported (fully automated) |
| Multi-repo dependency tracking | Built-in (`deps` in conf.yml) | Not available |
| Root app / microservice topology | Built-in (`root_app/service`) | Not available |
| State recovery (`goto`) | `vmn goto -v 1.2.3 app` | Not available |
| 4-segment hotfix versions | `major.minor.patch.hotfix` | Not supported |
| Prerelease support | Built-in (`--pr` flag) | Via branches configuration |
| Version auto-embedding | package.json, Cargo.toml, pyproject.toml, Jinja2 templates | package.json (npm publish) |
| Changelog generation | Supported | Built-in |
| CI requirement | None (works locally) | Designed for CI |
| Plugin system | None needed | Extensive (publish, analyze, etc.) |
| Offline / air-gapped use | Local file backend | Not supported |
| Git host | Any | Any (via plugins) |

## When vmn Is a Better Fit

### You work across multiple languages

semantic-release is rooted in the Node.js ecosystem. While plugins exist for
other languages, the tool still requires a Node.js runtime and npm
configuration. vmn is a single `pip install` away and works identically whether
you are versioning a Python library, a Rust binary, or a Go service.

### You manage multi-repo dependencies

If your product spans several git repositories, vmn can track the exact commit
of every dependency at the moment a version is stamped. No semantic-release
plugin offers this capability.

### You need state recovery

`vmn goto -v 1.2.3 my_app` checks out every tracked repository to the exact
state recorded when version 1.2.3 was stamped. This is invaluable for
reproducing bugs or auditing past releases.

### You want to stamp versions locally

vmn does not require CI. Developers can stamp versions from their local machine,
which is useful during early development, in air-gapped environments, or when
CI pipelines are not yet configured.

### You use a microservice topology

vmn's root-app concept lets you version a parent application and its child
services together, tracking which service versions compose a given root-app
release.

### You need hotfix versioning

vmn supports a fourth version segment (`major.minor.patch.hotfix`) for
hotfix workflows that do not fit the standard three-segment semver model.

## When semantic-release Is a Better Fit

- You want fully automated, zero-touch releases driven entirely by commit
  messages with no manual version decisions.
- You need deep npm integration (automated npm publish, GitHub Releases,
  changelogs) out of the box.
- Your team is already invested in the semantic-release plugin ecosystem.
- You prefer a mature, widely adopted tool with a large community
  (23k+ GitHub stars).

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
(similar to semantic-release), add this to `.vmn/my_app/conf.yml`:

```yaml
conf:
  conventional_commits: true
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

## Migrating from semantic-release

1. **Install vmn:** `pip install vmn`
2. **Initialize:** `vmn init && vmn init-app my_app`
3. **Start at your current version:** vmn will pick up existing version tags
   or you can stamp a new version to establish a baseline.
4. **Configure version backends** in `.vmn/my_app/conf.yml` to replace any
   semantic-release publish plugins that write version numbers into files.
5. **Remove semantic-release config:** Delete `.releaserc`, `.releaserc.json`,
   or `release.config.js` and uninstall the Node.js dependencies.
6. **Update CI:** Replace the semantic-release step with `vmn stamp -r <mode> my_app`
   (or use conventional commits for automatic mode detection).

## Further Reading

- [vmn GitHub repository](https://github.com/final-israel/vmn)
- [vmn README](https://github.com/final-israel/vmn#readme)
- [semantic-release documentation](https://semantic-release.gitbook.io/)
