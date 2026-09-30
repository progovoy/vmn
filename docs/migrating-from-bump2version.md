# Migrating from bump2version to vmn

[bump2version](https://github.com/c4urself/bump2version) (and the original
bumpversion, which uses the same configuration) is no longer actively
maintained. [vmn](https://github.com/progovoy/vmn) replaces its bump → rewrite
files → commit → tag loop for any language, keeps the version in git tags
instead of a `current_version` field, and adds Conventional Commits,
multi-repo dependency tracking and `vmn goto` state recovery. See the
[README](https://github.com/progovoy/vmn#readme) for the full feature set.

## Concept mapping

| bump2version | vmn | Notes |
| --- | --- | --- |
| `.bumpversion.cfg` / `setup.cfg [bumpversion]` | `.vmn/<app>/conf.yml` | Per-app configuration |
| `current_version = 1.2.3` | Git tag | No version stored in config |
| `part = major/minor/patch` | `-r major/minor/patch/hotfix` | Or omit: Conventional Commits pick it (on by default) |
| `[bumpversion:file:X]` + `search`/`replace` | `generic_selectors` backend | Regex search-and-replace in any file |
| package.json / pyproject.toml / Cargo.toml | `npm` / `pep621` or `poetry` / `cargo` backends | Structured, no patterns needed |
| `--dry-run` | `--dry-run` | |
| `--allow-dirty` | Not available | vmn refuses to stamp uncommitted changes; commit first |
| `--no-tag` / `--no-commit` | Not available | Tags are the source of truth; use `--dry-run` to preview |
| `tag_name = v{new_version}` | Not configurable | Tags are `<app>_<version>` |
| `commit_message` | `-e/--extra-commit-message` | Appends to vmn's message |
| `serialize` / `parse` | `template` in conf.yml | Display format only |
| Custom parts (`release_num`, ...) | Not supported | major, minor, patch, optional hotfix, prerelease, build metadata |
| `bump2version --list` | `vmn show my_app` | `--verbose` for full metadata |

## Step by step

1. **Install:** `pipx install vmn`.
2. **Start at your current version:** seed the app once with your
   `current_version`; vmn ignores existing `v1.2.3` tags, and both sets coexist.

   ```bash
   vmn init-app -v 1.2.3 my_app
   ```

3. **Map each `[bumpversion:file:...]` section.** Structured files use a
   dedicated backend; everything else uses `generic_selectors`:

   ```ini
   # .bumpversion.cfg, before
   [bumpversion]
   current_version = 1.2.3

   [bumpversion:file:pyproject.toml]

   [bumpversion:file:mypackage/__init__.py]
   search = __version__ = "{current_version}"
   replace = __version__ = "{new_version}"
   ```

   ```yaml
   # .vmn/my_app/conf.yml, after
   conf:
     version_backends:
       pep621:
         path: pyproject.toml
       generic_selectors:
         - paths_section:
             - input_file_path: mypackage/__init__.py
               output_file_path: mypackage/__init__.py
           selectors_section:
             - regex_selector: '(__version__ = "){{VMN_VERSION_REGEX}}"'
               regex_sub: '\1{{version}}"'
   ```

   `{{VMN_VERSION_REGEX}}` matches any vmn version; `{{version}}` is the new
   one. A file you would rather generate from scratch can use the
   `generic_jinja` backend (see the README's
   [version backends](https://github.com/progovoy/vmn#configuration)).

4. **Stamp:** `vmn stamp -r patch my_app` (or `vmn stamp my_app` with
   Conventional Commit messages). vmn rewrites the files, commits, tags and
   pushes — drop the separate `git push --follow-tags`.
5. **Remove** `.bumpversion.cfg` (or the `[bumpversion*]` sections of
   `setup.cfg`) and `pip uninstall bump2version`.

## FAQ

**Monorepo?** One app per component (`vmn stamp -r patch service_a`), each
auto-initialized on first stamp, or a root app for services
(`vmn stamp -r patch my_platform/service_a`).

**Non-Python projects?** vmn works with any project in a git repository.
