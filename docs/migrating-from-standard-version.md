# Migrating from standard-version to vmn

> [vmn](https://github.com/final-israel/vmn) is a language-agnostic, git-tag-based versioning CLI.
> This guide helps you migrate from [standard-version](https://github.com/conventional-changelog/standard-version), which was deprecated and archived in May 2023.

## Why Migrate

standard-version was archived by its maintainers in 2023. The repository is
read-only, no new releases will be published, and open issues will not be
addressed. If you rely on standard-version today, you are running unsupported
software.

vmn is an actively maintained alternative that offers:

- **Language-agnostic versioning** that works beyond the Node.js ecosystem
- **Git-tag-based source of truth** with structured YAML metadata in annotated tags
- **Multi-repo dependency tracking** for products that span several repositories
- **State recovery** via `vmn goto` to check out the exact repo state at any version
- **Root app / microservice topology** for versioning parent apps and child services
- **4-segment hotfix versions** (`major.minor.patch.hotfix`) for hotfix workflows
- **Offline / air-gapped support** via a local file backend
- **CI-agnostic** operation: works in GitHub Actions, GitLab CI, Jenkins, Bitbucket Pipelines, or locally

## Concept Mapping

| standard-version | vmn | Notes |
| --- | --- | --- |
| `.versionrc` / `.versionrc.json` | `.vmn/{app}/conf.yml` | Per-app configuration |
| `"version"` in `package.json` | Git tag (source of truth) | vmn's npm backend can also update `package.json` |
| `--release-as major` | `-r major` | Same for `minor`, `patch` |
| `--release-as 1.2.3` | Not supported (vmn increments, never sets absolute) | Use `vmn stamp -r patch` to increment |
| `--prerelease alpha` | `--pr alpha` | Prerelease tagging |
| `--dry-run` | `--dry-run` | Preview without changes |
| `--first-release` | `vmn init-app my_app` | Initializes versioning for the app |
| `--tag-prefix v` | Tag format is `{app_name}_{version}` | vmn uses its own tag convention |
| `CHANGELOG.md` generation | Changelog config in `conf.yml` | vmn supports changelog generation |
| `--skip.changelog` | Omit changelog config | Changelog is opt-in in vmn |
| `--skip.tag` | `--dry-run` | vmn always tags on stamp; use dry-run to skip |
| `--commit-all` | vmn commits `.vmn/` changes automatically | Handled internally |
| lifecycle hooks (`prebump`, etc.) | Not built-in | Use CI pipeline steps around `vmn stamp` |

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

This registers `my_app` for versioning. vmn will create
`.vmn/my_app/conf.yml` and `.vmn/my_app/last_known_app_version.yml`.

### 4. Configure Version Backends

If standard-version was updating `package.json`, configure vmn's npm backend:

```yaml
# .vmn/my_app/conf.yml
conf:
  version_backends:
    npm:
      - path: package.json
```

For Python projects, use the pep621 backend:

```yaml
conf:
  version_backends:
    pep621:
      - path: pyproject.toml
```

For Rust projects, use the cargo backend:

```yaml
conf:
  version_backends:
    cargo:
      - path: Cargo.toml
```

You can combine multiple backends if your project has several files that need
version updates.

### 5. Enable Conventional Commits (Optional)

If you relied on standard-version's automatic release mode detection from
conventional commit messages, enable the same behavior in vmn:

```yaml
# .vmn/my_app/conf.yml
conf:
  conventional_commits: true
```

With this enabled, `vmn stamp my_app` (without `-r`) reads commit messages
since the last stamp and automatically selects major, minor, or patch.

### 6. Stamp Your First vmn Version

```bash
# Explicit release mode
vmn stamp -r patch my_app

# Or, with conventional commits enabled
vmn stamp my_app
```

vmn creates an annotated git tag, updates configured version backends, commits
the changes, and pushes.

### 7. Remove standard-version Configuration

```bash
# Remove config files
rm -f .versionrc .versionrc.json .versionrc.js

# Uninstall the package
npm uninstall standard-version
# or remove from devDependencies manually
```

### 8. Update CI Pipelines

Replace standard-version commands in your CI configuration:

**Before (standard-version):**

```yaml
# GitHub Actions example
- run: npx standard-version
- run: git push --follow-tags
```

**After (vmn):**

```yaml
# GitHub Actions example
- run: pip install vmn
- run: vmn stamp -r patch my_app
```

vmn handles the git commit, tag, and push internally (unless `--dry-run` is
used).

### 9. Update npm Scripts (If Applicable)

**Before:**

```json
{
  "scripts": {
    "release": "standard-version",
    "release:minor": "standard-version --release-as minor",
    "release:major": "standard-version --release-as major"
  }
}
```

**After:**

```json
{
  "scripts": {
    "release": "vmn stamp -r patch my_app",
    "release:minor": "vmn stamp -r minor my_app",
    "release:major": "vmn stamp -r major my_app"
  }
}
```

## Command Mapping Quick Reference

| standard-version command | vmn equivalent |
| --- | --- |
| `npx standard-version` | `vmn stamp -r patch my_app` |
| `npx standard-version --release-as minor` | `vmn stamp -r minor my_app` |
| `npx standard-version --release-as major` | `vmn stamp -r major my_app` |
| `npx standard-version --prerelease alpha` | `vmn stamp -r patch --pr alpha my_app` |
| `npx standard-version --dry-run` | `vmn stamp -r patch --dry-run my_app` |
| `npx standard-version --first-release` | `vmn init-app my_app && vmn stamp -r patch my_app` |

## FAQ

### Can I keep my existing git tags?

Yes. vmn uses its own tag format (`{app_name}_{version}`), so it will not
conflict with tags created by standard-version (typically `v1.2.3`). Both sets
of tags can coexist in the same repository.

### What happens to my CHANGELOG.md?

vmn does not modify files created by standard-version. Your existing
`CHANGELOG.md` will remain untouched. If you configure vmn's changelog support,
future entries will be appended according to vmn's format.

### Can I use vmn in a monorepo?

Yes. Initialize a separate app for each package:

```bash
vmn init-app package_a
vmn init-app package_b
vmn stamp -r patch package_a
vmn stamp -r minor package_b
```

For microservice topologies, use the root-app feature:

```bash
vmn init-app my_platform/service_a
vmn init-app my_platform/service_b
```

### Does vmn support lifecycle hooks?

vmn does not have built-in lifecycle hooks like standard-version's `prebump`
or `postcommit`. Instead, wrap `vmn stamp` in your CI pipeline or a shell
script to run pre- and post-stamp steps.

### Do I need Node.js to run vmn?

No. vmn is a Python CLI. Install it with `pip`, `pipx`, or `uvx`. It has no
Node.js dependency.

## Further Reading

- [vmn GitHub repository](https://github.com/final-israel/vmn)
- [vmn README](https://github.com/final-israel/vmn#readme)
- [standard-version deprecation notice](https://github.com/conventional-changelog/standard-version#deprecated)
