# Packaging

Status: **implemented.** This replaced the single `setup.py` and its
`VMN_DIST=exp` switch. Where the implementation differs from the original
design, the section says so under "Differs from the design".

## Installing

| You want | Install | Commands you get |
|---|---|---|
| Versioning only | `pipx install vmn` (or `pip install vmn`) | `vmn` |
| Experiment tracking, the model registry, the dashboard | `pip install "vmn-exp[ui]"` (drop `[ui]` without the dashboard) | `vmn-exp`, and `vmn goto` for dev versions |
| Recording metrics from a training job or container | `pip install vmn-exp-sdk` (`[s3]` for a bucket, `pynvml` for GPU `sys_*`) | none; `from vmn_exp.sdk import start_run` |

`vmn-exp` pulls in `vmn` and `vmn-exp-sdk`, so one install gives you all three.
A job image needs only `vmn-exp-sdk`: it records runs git-free, with
`VMN_SNAPSHOT_METADATA` (from `vmn-exp export`) and `VMN_EXPERIMENT_DIR` or
`VMN_EXPERIMENT_BUCKET`.

Upgrading from vmn 0.10.x or earlier, where `vmn exp`, `vmn model` and `vmn ui`
were part of `vmn`: install `vmn-exp` and use `vmn-exp …` instead (for example
`vmn-exp run my_app -- python train.py`, `vmn-exp model list`, `vmn-exp ui`).
Experiment records on disk and in S3 are unchanged.

From a checkout (development): see "Repository layout" below, or run `uv sync`.

## Goals

- Three independent installs from one repo:
  - `vmn`: stamping only.
  - `vmn-exp`: the experiment platform (CLI, UI, capture).
  - `vmn-exp-sdk`: the metrics writer for jobs.
- No file is shipped by more than one distribution.
- `vmn-exp` can later move to its own repository and build on `vmn` as a normal
  dependency, with no code changes.

## Problems with the current setup

1. Both wheels ship `version_stamp`, so installing `vmn` and the slim
   `vmn-exp` overwrites files, and uninstalling either breaks the other.
2. One `setup.py` builds two products, switched by an environment variable, and
   the package lists are written out twice.
3. Runtime dependencies are read from `tests/requirements.txt`.
4. The slim wheel includes `version_stamp.cli` and `vmn_exp.cli` only because of
   incidental module-level imports.
5. Releases rewrite `version.py` with `gen_ver.py`, then revert it. The build uses
   the deprecated `setup.py bdist_wheel`, and there is no `pyproject.toml`.
6. Loose extras: an empty `exp` extra, and extras that only pin framework versions.

## Distributions

| Install | Import packages | Commands | Depends on |
|---|---|---|---|
| `vmn` | `version_stamp` | `vmn` | GitPython, PyYAML, Jinja2, git-cliff, … (as today) |
| `vmn-exp` | `vmn_exp.cli`, `.ui`, `.snapshot`, `.importers`, `.gitmode` | `vmn-exp` | `vmn<1`, `vmn-exp-sdk==<same version>`; extras `ui`, `s3`, `mlflow` |
| `vmn-exp-sdk` | `vmn_exp.sdk`, `.storage`, `.core`, `.registry`, `.integrations`, `._base` | none | PyYAML, filelock, psutil; extra `s3` |

`vmn_exp` is a PEP 420 namespace package: it has no `__init__.py`, and each
subpackage belongs to exactly one distribution.

### vmn

- Knows nothing about experiments: the `exp`/`experiment`, `model` and `ui`
  commands are gone, and no module names `vmn_exp`.
- **`vmn goto <dev-version>`** is provided by `vmn-exp` through the
  `vmn.plugins` entry point group (`dev_version`), which registers the loader
  that restores a recorded dev version. `vmn` loads whatever that group lists.

  *Differs from the design,* which kept dev-version records inside `vmn`. Their
  storage and record format live in `vmn_exp` (the SDK needs them), so `vmn`
  alone cannot restore one; installing `vmn-exp` adds it. The plugin hook
  replaced the hardcoded `BUILTIN_PLUGINS` list rather than being removed.
- **`vmn snapshot`** is built in (`version_stamp.snapshot`): it records and
  restores working state in local stores with `vmn` alone. `vmn-exp` registers
  a snapshot store opener (`plugin_api.register_snapshot_store_opener`) so
  `--store`/`VMN_EXPERIMENT_STORE`/conf `experiment.storage.uri` put snapshots
  in a remote store. See [snapshots.md](snapshots.md).
- `version_stamp.api` becomes vmn's public, versioned contract:
  - documented;
  - covered by contract tests;
  - names are deprecated before they are removed.
- `import version_stamp.api` loads no `git` module (its names resolve lazily),
  so no change to the GitPython imports was needed.

### vmn-exp

- The full experiment platform: the `vmn-exp` command (experiment actions
  directly — `vmn-exp run app -- cmd` — plus `model` and `ui`),
  the dashboard, and the MLflow importer.
- *Differs from the design:* `vmn skill` still carries the experiment section
  (now with `vmn-exp` commands); there is no separate `vmn-exp skill`.
- `vmn_exp.gitmode` holds the git-dependent parts of the SDK: cold start
  (`_init_app`, `handle_init`) and snapshot capture. `start_run()` loads it only
  when needed.
- Reaches `version_stamp` only through `version_stamp.api`.

### vmn-exp-sdk

- Meant for job images: `start_run()` in git-free mode, using
  `VMN_EXPERIMENT_DIR` or a bucket, plus `VMN_SNAPSHOT_METADATA` or resuming a
  run id. Covers logging metrics, params and artifacts, autolog, the framework
  integrations, the reader API and the model registry.
- If `start_run()` would need git (a cold start or a snapshot capture), it fails
  with "install vmn-exp for git mode".
- `vmn_exp._base` holds the few helpers the SDK used to take from
  `version_stamp` (logger, `now_iso`, path validation, `yaml_safe_load`,
  `sha256_file`, `resolve_root_path`, the repo lock); tests/test_exp_base.py
  keeps each copy behaving like the original. They are copied, not shared, so the SDK has no dependency on
  `vmn`. `parse_record_metadata` moves here, since the record format belongs to
  experiments.

## Import rules (enforced by tests)

1. `version_stamp.*` never imports `vmn_exp` (tests/test_packaging_split.py).
2. `vmn-exp-sdk` subpackages import neither `version_stamp` nor the `vmn-exp`
   subpackages, except a lazy `vmn_exp.gitmode` import (same file).
3. `vmn-exp` subpackages import `version_stamp` only through `version_stamp.api`
   (same file).
4. No path appears in two built wheels, and the SDK wheel alone records a run
   with no `git` or `version_stamp` installed (tests/test_installation.py).

## Repository layout

One uv workspace:

```
pyproject.toml   workspace root (uv workspace, mypy config); not a package
packages/
  vmn/          pyproject.toml  src/version_stamp/
  vmn-exp-sdk/  pyproject.toml  src/vmn_exp/{sdk,storage,core,registry,integrations,_base}
  vmn-exp/      pyproject.toml  src/vmn_exp/{cli,ui,snapshot,importers,gitmode}  webui/
tests/           one suite for all three
```

- For development, `uv sync` (or `pip install -e` of each package) installs all
  three editable. tests/conftest.py puts the three `src/` folders first on
  `sys.path`, and `helpers._SRC_PATH` is the matching `PYTHONPATH` for
  subprocesses, so a worktree tests its own tree.
- `uv build --all-packages` builds the three wheels.
- `setup.py`, `VMN_DIST`, `gen_ver.py` and `MANIFEST.in` are deleted.
- Runtime dependencies live in each `pyproject.toml`; `tests/requirements.txt`
  and `tests/constraints.txt` are dev-only pins.
- *Differs from the design:* the tests were not split per package; they stay
  in one `tests/` folder. Split them when `vmn-exp` moves out.

Moving `vmn-exp` to its own repository later: run `git filter-repo` on
`packages/vmn-exp*`, then change its `vmn` dependency from the workspace copy to
the PyPI release.

## Versioning and release

- Two vmn apps: `vmn` (for the `vmn` distribution) and `vmn_exp` (a shared
  version for `vmn-exp` and `vmn-exp-sdk`, so the dashboard and the job writer
  always agree on the record format).
- Each app's `version_backends` (`generic_selectors` in
  `.vmn/vmn/conf.yml` and `.vmn/vmn_exp/conf.yml`) writes the new version into
  `project.version`, into `version_stamp/version.py` (vmn), and into vmn-exp's
  `vmn-exp-sdk==` pin, as part of `vmn stamp`. That replaces `gen_ver.py` and
  the checkout revert. tests/test_workspace.py checks the selectors against the
  real files and through a real `vmn stamp`.
- `./release_exp.sh` releases vmn-exp and vmn-exp-sdk with a patch bump (a minor
  bump the very first time, past the 0.0.1 placeholders). It refuses a dirty
  tree. vmn is released on its own (`vmn stamp vmn`, `make _build`,
  `make upload`).
- `make upload` sends each file to its project's `~/.pypirc` section
  (`[pypi]` for vmn, `[vmn-exp]`, `[vmn-exp-sdk]`), so per-project tokens
  work; a missing section falls back to `[pypi]`, for one account-wide token.
  `--skip-existing` makes a rerun safe.
- `make patch` releases vmn; `make patch NAME=vmn_exp` releases vmn-exp and
  vmn-exp-sdk. `_build` runs `uv build` for the matching packages (and builds
  the web UI for vmn_exp). In `ci/pipeline.py` the `app` param (`vmn` or
  `vmn_exp`) picks which.

### PyPI

- `vmn` is on PyPI (0.10.1 is the last release before the split). `vmn-exp`
  and `vmn-exp-sdk` are claimed by placeholder `0.0.1` releases (uploaded
  2026-09-28), which contain nothing usable.
- Release order for the split: first a vmn newer than 0.10.2rc9 (the last
  version with its own `vmn exp`), since vmn-exp requires `vmn>0.10.2rc9,<1`;
  then vmn-exp and vmn-exp-sdk together (`make minor NAME=vmn_exp`, giving
  0.1.0 — 0.0.1 is taken by the placeholder).
- A project is created by its first upload, which needs an account-wide token.
  After that, switch to per-project tokens.

## Migration

Done in six steps, each test-first: the import-rule tests; `vmn_exp._base`;
`vmn_exp.gitmode`; the `vmn-exp` command; the workspace layout; release
versioning through `version_backends`.
