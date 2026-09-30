# vmn vs semantic-release

[semantic-release](https://github.com/semantic-release/semantic-release)
automates version management and package publishing, mainly for Node.js: it
reads Conventional Commits in CI, picks the next version, generates release
notes and publishes to npm (or other registries via plugins).

[vmn](https://github.com/progovoy/vmn) stamps versions as annotated git tags
with YAML metadata, works with any language, records the exact revision of
every dependency repository, and leaves publishing to your pipeline.

## Feature comparison

| Feature | vmn | semantic-release |
| --- | --- | --- |
| Language support | Any | Primarily Node.js; others via plugins |
| Runtime | Python 3.8+ | Node.js |
| Version source of truth | Annotated git tags with YAML metadata | Git tags |
| Conventional Commits | On by default; `-r` overrides | Required |
| Manual release mode | `vmn stamp -r major/minor/patch/hotfix` | Not supported (fully automated) |
| Multi-repo dependency tracking | Built-in (`deps` in conf.yml) | Not available |
| Root app / microservice topology | Built-in (`root_app/service`) | Not available |
| State recovery | `vmn goto -v 1.2.3 app` | Not available |
| 4-segment hotfix versions | `major.minor.patch.hotfix` | Not supported |
| Prereleases | `--pr <id>`, promoted with `vmn release` | Via branch configuration |
| Writing the version into files | npm, Cargo, Poetry, PEP 621, Jinja2, regex selectors | package.json (npm plugin) |
| Changelog / GitHub Releases | `changelog.path`, `github_release` in conf.yml | Built-in |
| Package publishing | Not included | Built-in via plugins |
| Where it runs | Locally or in any CI | Designed for CI |
| Plugin system | None | Extensive (analyze, publish, notify, ...) |
| Git host | Any, including internal/air-gapped servers | Any (via plugins) |

## When vmn is a better fit

- **Several languages.** semantic-release needs a Node.js runtime and npm
  configuration even for non-JS projects; vmn is one `pipx install` and treats
  a Python library, a Rust binary and a Go service the same way.
- **Products that span repositories.** vmn records the commit of every
  dependency at stamp time and `vmn goto` restores all of them. No
  semantic-release plugin does this.
- **Human-chosen versions.** `vmn stamp -r minor` works from a laptop or CI;
  Conventional Commits are a default, not a requirement.
- **Microservices.** Root apps give each service its own version plus a
  monotonic version of the whole composition.
- **Hotfix lines.** A fourth segment (`1.6.7.4`) for hotfixes that do not fit
  three-segment SemVer.

## When semantic-release is a better fit

- You want zero-touch releases driven entirely by commit messages.
- You need npm publishing and its plugin ecosystem out of the box.
- Your team is already invested in semantic-release plugins.

## Migrating from semantic-release

1. **Install:** `pipx install vmn` (see the
   [README quick start](https://github.com/progovoy/vmn#quick-start)).
2. **Start at your current version:** vmn tags are `<app>_<version>` and it
   does not read semantic-release's `v1.2.3` tags. Seed the app once with
   `vmn init-app -v 1.2.3 my_app`; the next stamp continues from there.
3. **Commit messages:** Conventional Commits already drive the release mode, so
   `vmn stamp my_app` picks major/minor/patch from commits since the last stamp.
4. **Files:** configure `version_backends` in `.vmn/my_app/conf.yml` to replace
   plugins that wrote the version into files:

   ```yaml
   conf:
     version_backends:
       npm:
         path: package.json
     changelog:
       path: CHANGELOG.md
     github_release:
       draft: false
   ```

5. **Remove** `.releaserc*` / `release.config.js` and the semantic-release
   dependencies.
6. **CI:** replace the semantic-release step with `vmn stamp --pull my_app`
   (or [vmn-action](https://github.com/marketplace/actions/automated-versioning)),
   and keep `npm publish` as a separate step if you publish packages.

## Further reading

- [vmn README](https://github.com/progovoy/vmn#readme) (configuration and command reference)
- [semantic-release documentation](https://semantic-release.gitbook.io/)
