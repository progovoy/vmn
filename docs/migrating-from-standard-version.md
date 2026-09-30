# Migrating from standard-version to vmn

[standard-version](https://github.com/conventional-changelog/standard-version)
was deprecated and archived in May 2023. [vmn](https://github.com/progovoy/vmn)
covers its core loop (Conventional Commits → bump → changelog → commit → tag)
for any language, and adds multi-repo dependency tracking, `vmn goto` state
recovery, root apps for microservices, and hotfix versions. See the
[README](https://github.com/progovoy/vmn#readme) for the full feature set.

## Concept mapping

| standard-version | vmn | Notes |
| --- | --- | --- |
| `.versionrc` / `.versionrc.json` | `.vmn/<app>/conf.yml` | Per-app configuration |
| `"version"` in `package.json` | Git tag (source of truth) | The `npm` backend keeps `package.json` in sync |
| Conventional Commits bump | Same, on by default | `vmn stamp my_app` picks the mode |
| `--release-as major` | `-r major` | Same for `minor`, `patch`; `hotfix` adds a fourth segment |
| `--release-as 1.2.3` | `--ov 1.2.2 -r patch` | `--ov` sets the version the bump starts from |
| `--prerelease alpha` | `--pr alpha` | Promote later with `vmn release` |
| `--dry-run` | `--dry-run` | |
| `--first-release` | Nothing, or `vmn init-app -v <version> my_app` | The first stamp auto-initializes |
| `--tag-prefix v` | Not configurable | Tags are `<app>_<version>` |
| `CHANGELOG.md` generation | `changelog.path` in conf.yml | Opt-in |
| `--skip.changelog` | Omit `changelog` | |
| `--skip.tag` / `--skip.commit` | Not available | Tags are the source of truth; use `--dry-run` to preview |
| `--commit-all` | Not needed | vmn commits its own files and backend files |
| Lifecycle hooks (`prebump`, ...) | Not built in | Run steps around `vmn stamp` in CI or a script |
| `git push --follow-tags` | Not needed | vmn pushes the commit and tags |

## Step by step

1. **Install:** `pipx install vmn` (no Node.js needed).
2. **Start at your current version:** vmn does not read `v1.2.3` tags; both
   tag sets can coexist. Seed the app once:

   ```bash
   vmn init-app -v 1.4.2 my_app   # next stamp continues from 1.4.2
   ```

3. **Configure** `.vmn/my_app/conf.yml`:

   ```yaml
   conf:
     version_backends:
       npm:
         path: package.json
     changelog:
       path: CHANGELOG.md
   ```

   Other backends (`pep621`, `cargo`, `poetry`, Jinja2, regex selectors) are in
   the README's [configuration reference](https://github.com/progovoy/vmn#configuration).
   Combine as many as you need.

4. **Stamp:**

   ```bash
   vmn stamp my_app            # mode from Conventional Commits
   vmn stamp -r minor my_app   # or explicitly
   ```

   vmn updates the backends, prepends the changelog entry, commits, tags and
   pushes.

5. **Remove** `.versionrc*` and `npm uninstall standard-version`.
6. **CI and npm scripts:** replace `npx standard-version && git push
   --follow-tags` with `vmn stamp my_app` (install with `pip install vmn`),
   and e.g. `"release:minor": "vmn stamp -r minor my_app"`.

## FAQ

**What happens to my existing CHANGELOG.md?** With `changelog.path` pointing
at it, vmn inserts each new entry below the file's `# ` title, so the
standard-version history stays below it. Without `changelog`, vmn never touches
it.

**Monorepo?** Use one app name per package (`vmn stamp package_a`), or a root
app for services (`vmn stamp my_platform/service_a`; `vmn show --root
my_platform` prints the composition version).

**Custom commit message?** `-e "[skip ci]"` appends to vmn's commit message;
the message itself is not configurable.
