# Migrating from bump2version to vmn

> [vmn](https://github.com/final-israel/vmn) is a language-agnostic, git-tag-based versioning CLI.
> This guide helps you migrate from [bump2version](https://github.com/c4urself/bump2version) (and its predecessor bumpversion), which are no longer actively maintained.

## Why Migrate

bump2version (and the original bumpversion) have seen minimal maintenance for
years. Open issues and pull requests go unaddressed, and the tools do not
support modern Python packaging conventions like `pyproject.toml` natively.

vmn is an actively maintained alternative that offers:

- **Git-tag-based source of truth**: no `current_version` field to keep in sync
- **Language-agnostic**: works with Python, Node.js, Rust, Go, and any other language
- **Multi-repo dependency tracking** for products spanning several repositories
- **State recovery** via `vmn goto` to check out the exact repo state at any version
- **Root app / microservice topology** for versioning parent apps and child services
- **4-segment hotfix versions** (`major.minor.patch.hotfix`) for hotfix workflows
- **Conventional commits** for automatic release mode detection
- **Offline / air-gapped support** via a local file backend
- **CI-agnostic**: works in GitHub Actions, GitLab CI, Jenkins, Bitbucket Pipelines, or locally

## Concept Mapping

| bump2version | vmn | Notes |
| --- | --- | --- |
| `.bumpversion.cfg` / `setup.cfg [bumpversion]` | `.vmn/{app}/conf.yml` | Per-app configuration |
| `current_version = 1.2.3` | Git tag (source of truth) | No version in config files |
| `[bumpversion:file:setup.py]` | `version_backends: {pep621: [{path: pyproject.toml}]}` | Auto-embed version in files |
| `[bumpversion:file:package.json]` | `version_backends: {npm: [{path: package.json}]}` | Auto-embed version in files |
| `part = major/minor/patch` | `-r major/minor/patch` | Release mode argument |
| `--allow-dirty` | Not applicable (vmn manages git state) | vmn commits changes automatically |
| `--dry-run` | `--dry-run` | Preview without changes |
| `--tag / --no-tag` | vmn always creates tags | Tags are the core mechanism |
| `--commit / --no-commit` | vmn always commits | Part of the stamp workflow |
| `tag_name = v{new_version}` | Tag format: `{app_name}_{version}` | vmn uses its own convention |
| `commit_message` config | Not configurable | vmn generates structured commits |
| `search` / `replace` patterns | Version backends + Jinja2 templates | Different approach to file updates |
| `serialize` / `parse` format | `template` in conf.yml | Version display format |

## Step-by-Step Migration

### 1. Install vmn

```bash
pip install vmn
# or: pipx install vmn
# or: uvx vmn
```

### 2. Initialize vmn in Your Repository

```bash
vmn init
```

This creates the `.vmn/` directory and a root configuration. Run this once per
repository.

### 3. Initialize Your Application

```bash
vmn init-app my_app
```

This registers `my_app` for versioning and creates
`.vmn/my_app/conf.yml` and `.vmn/my_app/last_known_app_version.yml`.

### 4. Map Your bump2version File Patterns

bump2version uses `[bumpversion:file:...]` sections with `search` and `replace`
patterns to update version strings in source files. vmn replaces this with
version backends and Jinja2 templates.

#### Python Projects (pyproject.toml)

**Before (bump2version):**

```ini
[bumpversion]
current_version = 1.2.3

[bumpversion:file:setup.py]
search = version="{current_version}"
replace = version="{new_version}"

[bumpversion:file:mypackage/__init__.py]
search = __version__ = "{current_version}"
replace = __version__ = "{new_version}"
```

**After (vmn):**

```yaml
# .vmn/my_app/conf.yml
conf:
  version_backends:
    pep621:
      - path: pyproject.toml
```

For files like `__init__.py` that are not covered by a built-in backend, use
a Jinja2 template with `vmn gen`:

```bash
vmn gen -t version.j2 -o mypackage/__init__.py my_app
```

Where `version.j2` contains:

```jinja2
__version__ = "{{ version }}"
```

#### Node.js Projects (package.json)

**Before (bump2version):**

```ini
[bumpversion:file:package.json]
search = "version": "{current_version}"
replace = "version": "{new_version}"
```

**After (vmn):**

```yaml
# .vmn/my_app/conf.yml
conf:
  version_backends:
    npm:
      - path: package.json
```

#### Rust Projects (Cargo.toml)

**Before (bump2version):**

```ini
[bumpversion:file:Cargo.toml]
search = version = "{current_version}"
replace = version = "{new_version}"
```

**After (vmn):**

```yaml
# .vmn/my_app/conf.yml
conf:
  version_backends:
    cargo:
      - path: Cargo.toml
```

### 5. Enable Conventional Commits (Optional)

If you want vmn to automatically determine the release mode from commit
messages:

```yaml
# .vmn/my_app/conf.yml
conf:
  conventional_commits:
    enabled: true
```

### 6. Stamp Your First vmn Version

```bash
# Explicit release mode
vmn stamp -r patch my_app

# Or, with conventional commits enabled
vmn stamp my_app
```

vmn creates an annotated git tag, updates configured version backends, commits
the changes, and pushes.

### 7. Remove bump2version Configuration

```bash
# Remove config file
rm -f .bumpversion.cfg

# If using setup.cfg, remove the [bumpversion] and [bumpversion:file:...] sections

# Uninstall
pip uninstall bump2version
```

### 8. Update CI Pipelines

Replace bump2version commands in your CI configuration:

**Before (bump2version):**

```yaml
# GitHub Actions example
- run: pip install bump2version
- run: bump2version patch
- run: git push --follow-tags
```

**After (vmn):**

```yaml
# GitHub Actions example
- run: pip install vmn
- run: vmn stamp -r patch my_app
```

vmn handles the git commit, tag, and push internally.

## Command Mapping Quick Reference

| bump2version command | vmn equivalent |
| --- | --- |
| `bump2version patch` | `vmn stamp -r patch my_app` |
| `bump2version minor` | `vmn stamp -r minor my_app` |
| `bump2version major` | `vmn stamp -r major my_app` |
| `bump2version --dry-run patch` | `vmn stamp -r patch --dry-run my_app` |
| `bump2version --allow-dirty patch` | `vmn stamp -r patch my_app` (vmn manages state) |
| `bump2version --list patch` | `vmn show my_app` |
| `bump2version --tag --commit patch` | `vmn stamp -r patch my_app` (always tags and commits) |

## Key Differences to Be Aware Of

### No `current_version` in Config

bump2version stores `current_version` in `.bumpversion.cfg` and updates it on
every bump. vmn does not store the version in any config file. The version
lives exclusively in git tags, eliminating a common source of merge conflicts
and desynchronization.

### No `search` / `replace` Patterns

bump2version uses regex-like `search` and `replace` directives to find and
update version strings in arbitrary files. vmn uses structured version backends
for well-known file formats (package.json, Cargo.toml, pyproject.toml) and
Jinja2 templates for everything else. This is less flexible for unusual
patterns but more reliable for standard formats.

### Tags Are Required

bump2version can be configured to skip tagging (`--no-tag`). vmn always creates
annotated git tags because tags are the source of truth. If you need to test
without creating tags, use `--dry-run`.

### Commit Messages Are Not Configurable

bump2version allows custom `commit_message` templates. vmn generates its own
structured commit messages. If you need specific commit message formats, wrap
vmn in a script that amends the commit.

## FAQ

### Can I keep my existing git tags?

Yes. vmn uses its own tag format (`{app_name}_{version}`), so it will not
conflict with tags created by bump2version. Both sets of tags can coexist.

### Can I use vmn for non-Python projects?

Absolutely. Unlike bump2version, vmn is language-agnostic. It works with any
project that lives in a git repository.

### What about bumpversion (the original)?

The migration process is identical. bumpversion and bump2version use the same
configuration format, so the steps above apply to both.

### Can I use vmn in a monorepo?

Yes. Initialize a separate app for each component:

```bash
vmn init-app service_a
vmn init-app service_b
vmn stamp -r patch service_a
vmn stamp -r minor service_b
```

For microservice topologies, use the root-app feature:

```bash
vmn init-app my_platform/service_a
vmn init-app my_platform/service_b
```

### Does vmn support custom version parts?

bump2version allows defining custom version parts (e.g., `release_num`). vmn
uses the standard semver segments (major, minor, patch) plus an optional hotfix
segment and prerelease labels. Custom parts are not supported, but the
four-segment format covers most real-world workflows.

## Further Reading

- [vmn GitHub repository](https://github.com/final-israel/vmn)
- [vmn README](https://github.com/final-israel/vmn#readme)
- [bump2version repository](https://github.com/c4urself/bump2version)
