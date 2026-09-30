# vmn vs setuptools-scm

[setuptools-scm](https://github.com/pypa/setuptools-scm) derives a Python
package's version from git tags at build time: `python -m build` asks git where
HEAD is relative to the last tag, and there is no explicit release step.

[vmn](https://github.com/progovoy/vmn) is explicit: `vmn stamp` computes the
next version, writes it into your files, and records it in an annotated git tag
with YAML metadata, including the exact revision of every dependency
repository. It is not tied to Python.

## Feature comparison

| Feature | vmn | setuptools-scm |
| --- | --- | --- |
| Language support | Any | Python |
| Build system integration | Separate CLI; writes the version into files | setuptools, hatchling (via hatch-vcs), others |
| Version source of truth | Annotated git tags with YAML metadata | Nearest git tag + distance |
| Version determination | Explicit stamp | Derived at build time |
| Release mode | `-r major/minor/patch/hotfix`, or Conventional Commits (on by default) | Manual `git tag` |
| Multi-repo dependency tracking | Built-in | Not available |
| Root app / microservice topology | Built-in (`root_app/service`) | Not available |
| State recovery | `vmn goto -v 1.2.3 app` | Not available |
| 4-segment hotfix versions | `major.minor.patch.hotfix` | Not supported |
| Prereleases | `--pr <id>`, promoted with `vmn release` | Dev versions from distance to tag |
| Between-release versions | `vmn show --dev` / `vmn snapshot` (`1.2.0-dev.<commit>.<diff>`) | `1.2.4.dev3+g<hash>[.d<date>]` on every build |
| Writing the version into files | npm, Cargo, Poetry, PEP 621, Jinja2, regex selectors | `_version.py` / package metadata |
| Network | Any Git remote, including internal/air-gapped | None (local git only) |

## When vmn is a better fit

- **More than Python.** Rust, Go and Node services get the same workflow.
- **You want to decide the version.** `vmn stamp -r patch my_app` bumps, tags,
  and updates your files in one step; nothing depends on how far HEAD is from
  a tag at build time.
- **Products that span repositories.** vmn records every dependency's commit
  at stamp time, and `vmn goto` restores all of them.
- **Microservices and hotfix lines.** Root apps and the fourth version segment.

## When setuptools-scm is a better fit

- You are purely in the Python packaging ecosystem and want zero-configuration
  versions with no extra CLI.
- You want every build of every commit to get a unique, installable version.

## Migrating from setuptools-scm

1. **Install:** `pipx install vmn` (see the
   [README quick start](https://github.com/progovoy/vmn#quick-start)).
2. **Start at your current version:** vmn does not read `v1.2.3` tags. Seed
   the app once with `vmn init-app -v 1.2.3 my_app`.
3. **Let vmn maintain `pyproject.toml`:** replace the dynamic version with a
   static one and add the `pep621` backend:

   ```toml
   # pyproject.toml, before
   [build-system]
   requires = ["setuptools>=64", "setuptools-scm>=8"]

   [project]
   dynamic = ["version"]

   [tool.setuptools_scm]
   ```

   ```toml
   # pyproject.toml, after
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
         path: pyproject.toml
   ```

   A generated `_version.py` can be kept with a `generic_jinja` backend (see
   the README's
   [version backends](https://github.com/progovoy/vmn#configuration)).
4. **Build:** run `vmn stamp my_app` (or `-r <mode>`) before `python -m build`.

## Further reading

- [vmn README](https://github.com/progovoy/vmn#readme) (configuration and command reference)
- [setuptools-scm documentation](https://setuptools-scm.readthedocs.io/)
