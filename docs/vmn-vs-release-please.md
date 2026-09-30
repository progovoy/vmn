# vmn vs release-please

[release-please](https://github.com/googleapis/release-please) automates
releases through GitHub pull requests: as Conventional Commits land on the main
branch it opens (or updates) a "Release PR" that bumps versions and the
changelog; merging it creates the GitHub Release.

[vmn](https://github.com/progovoy/vmn) stamps versions directly as annotated
git tags with YAML metadata, from the command line, with any git host, and
records the exact revision of every dependency repository.

## Feature comparison

| Feature | vmn | release-please |
| --- | --- | --- |
| Language support | Any | Any (via release-type config) |
| Git host | Any, including internal/air-gapped servers | GitHub (GitLab support experimental) |
| Release mechanism | CLI command → commit + tags | Release PR bot |
| Review step before release | Your own PR flow | The Release PR |
| Runtime | Python 3.8+ | Node.js |
| Conventional Commits | On by default; `-r` overrides | Required |
| Manual release mode | `vmn stamp -r major/minor/patch/hotfix` | Not supported |
| Multi-repo dependency tracking | Built-in | Not available |
| Monorepo / services | Root app + independently versioned services | Manifest with linked components (monorepo only) |
| State recovery | `vmn goto -v 1.2.3 app` | Not available |
| 4-segment hotfix versions | `major.minor.patch.hotfix` | Not supported |
| Prereleases | `--pr <id>`, promoted with `vmn release` | Via prerelease configuration |
| Writing the version into files | npm, Cargo, Poetry, PEP 621, Jinja2, regex selectors | Per release-type |
| Changelog / GitHub Releases | `changelog.path`, `github_release` in conf.yml | Built-in (core feature) |
| Where it runs | Locally or in any CI | GitHub Actions or CI |

## When vmn is a better fit

- **You are not on GitHub.** release-please depends on the GitHub API; vmn only
  needs git, so GitLab, Bitbucket and self-hosted or air-gapped servers work
  the same.
- **You want to release when you decide.** One command, from CI or a laptop,
  instead of accumulating commits in a bot PR.
- **Products that span repositories.** vmn records the commit and remote of
  every dependency at stamp time, and `vmn goto` restores all of them.
- **Multi-repo microservices.** Root apps version services that live in
  different repositories; release-please's manifest covers a single monorepo.
- **Hotfix lines.** A fourth segment (`1.6.7.4`) outside three-segment SemVer.

## When release-please is a better fit

- You want a fully automated, PR-based release flow on GitHub.
- You want the Release PR as the review step before any version is final.
- You already standardize on Google's release tooling.

## Migrating from release-please

1. **Install:** `pipx install vmn` (see the
   [README quick start](https://github.com/progovoy/vmn#quick-start)).
2. **Start at your current version:** vmn tags are `<app>_<version>` and it
   does not read release-please's tags or manifest. Seed each app once with
   `vmn init-app -v <current> <app>` (for a monorepo, one app per component,
   or `root/service` names for a root app).
3. **Files:** configure `version_backends` (plus `changelog.path` and
   `github_release` if you want them) in `.vmn/<app>/conf.yml` for the
   version-file updates release-please performed.
4. **Remove** `release-please-config.json`, `.release-please-manifest.json` and
   the release-please workflow.
5. **CI:** stamp on merge to the main branch with `vmn stamp --pull <app>`
   (Conventional Commits pick the mode) or
   [vmn-action](https://github.com/marketplace/actions/automated-versioning).

## Further reading

- [vmn README](https://github.com/progovoy/vmn#readme) (configuration and command reference)
- [release-please documentation](https://github.com/googleapis/release-please)
