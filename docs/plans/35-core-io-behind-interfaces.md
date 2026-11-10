# Plan 35: core vmn IO behind interfaces

> CLAUDE.md now requires all IO to go through interfaces that the entry point
> wires (real in production, fakes in tests). Core vmn (`version_stamp`,
> 89 files, ~14.8K lines) does not follow it: one injected clock, everything
> else direct. This plan migrates core vmn only; vmn-exp is a later plan.
>
> Paths: `vs/` = `packages/vmn/src/version_stamp/`.

Status: **proposed** (2026-11-10).

## Where the IO is today (grep survey, approximate)

| Kind | Sites | Files | Main places |
|---|---|---|---|
| Time / sleep / random | 9 | 7 | `backends/git_ops.py` (tag-second wait), `cli/commands.py` (push retry sleep), `core/utils.py` (`now_iso`), `backends/git.py` (fetch cache TTL), `snapshot/listing.py`, `cli/worktree_create.py` |
| Env vars | 18 | 10 | `cli/completion.py`, `core/utils.py` (`VMN_WORKING_DIR`), `backends/branch_resolver.py` (CI hints), `stamping/publisher.py`, `cli/commands.py`, `core/repo_lock.py` |
| Subprocess | 8 | 5 | `core/git_cmd.py` (`run_git`), `stamping/template_data.py`, `stamping/publisher.py` (`gh`), `cli/config_tui.py` (editor), `devversion/materialize.py` (difftool) |
| Filesystem | ~210 | 35 | `snapshot/local_store.py`, `stamping/base.py`, `stamping/publisher.py`, `core/utils.py`, `devversion/*`, `compat/branch_conf.py` |
| Git (GitPython) | ~40 | 11 | `backends/git*.py`, `backends/branch_*.py`; leaks via `backend._be` in `stamping/publisher.py` (3), `devversion/capture.py` (3), `devversion/materialize.py` (1) |
| Lock | 1 | 1 | `core/repo_lock.py` (`FileLock`) |
| stdout / stdin | ~60 | 11 | `cli/config_tui.py`, `cli/completion.py`, `snapshot/listing.py` |

Tests: 66 of 100 core test files go through the Docker + real-git fixture;
all commands are driven through `vmn_run([...])` (`tests/helpers.py`).

## Design

1. **Ports** — `vs/core/ports.py`: small `Protocol`s, one per IO kind:
   `Clock` (`now()`, `monotonic()`, `sleep(sec)`), `Env` (read-only mapping),
   `Processes` (`run(cmd, ...) -> CompletedProcess | None`), `FileSystem`
   (read/write text and bytes, exists, is_dir, listdir, walk, mkdir, remove,
   rename, rmtree, copy, mtime, touch), `Random`, `LockFactory`, `Console`
   (`out`, `err`, `read_line`).
2. **Real implementations** — `vs/core/real_io.py`: thin classes over the
   stdlib, plus `real_io()` returning an `IO` dataclass that bundles them.
   This and `vs/backends/git*.py` are the only modules allowed to touch the
   stdlib IO modules.
3. **Composition root** — `main()` stays byte-for-byte as it is (its comment
   asks for that). `vmn_run(command_line)` becomes the root: it builds
   `real_io()` and calls a new `run_command(command_line, io)` that holds
   today's body. Every existing caller of `vmn_run` (tests, vmn-exp) keeps
   working unchanged; unit tests call `run_command(argv, fake_io)`.
4. **Passing it down** — `VMNContainer` gets `io` and exposes `vmn_ctx.io`
   (so `CommandSpec` plugin handlers receive it too); `VersionControlStamper`
   takes `io` and its `backend` from the container instead of calling
   `get_client` itself (`stamping/base.py:84`). Module-level helpers
   (`run_git`, `now_iso`, `resolve_root_path`, `get_repo_lock`) take the port
   as a parameter.
5. **Git** — `VMNBackend` (ABC) already is the interface, but it declares 11
   methods while callers use ~39 and reach into `backend._be` in 7 places.
   Widen the ABC to what callers use, close the `_be` leaks, and add an
   in-memory `FakeBackend` (commits, branches, annotated tags with messages,
   one remote).
6. **Fakes** — `tests/fakes/`: `FakeClock` (advance by hand; `sleep` advances
   it), `FakeEnv`, `FakeProcesses` (scripted results, records calls),
   `MemFS`, `FakeBackend`, `FakeConsole`. Each fake has a **contract test**
   that runs the same assertions against the real implementation (real FS in
   `tmp_path`, real `GitBackend` in the Docker fixture), so fakes cannot
   drift.
7. **Ratchet** — `tests/test_io_boundary.py` (same style as
   `test_packaging_split.py`): an AST scan that fails when a `version_stamp`
   module outside an allowlist imports or calls `time`, `datetime.now`,
   `subprocess`, `os.environ`, `open`, `shutil`, `git`, `filelock`, `print`.
   The allowlist starts as today's offender list and each stage deletes the
   entries it cleaned; it may never grow.

## Stages

Each stage is TDD (fake-based unit test red, then the change), one worktree
per bullet where files are disjoint, `/simplify` at the end, and both suites
green before merge. The existing Docker tests are not edited; they are the
safety net.

- **0. Foundations** (serial, first). `ports.py`, `real_io.py`, `IO` bundle,
  `run_command(argv, io)` + `vmn_ctx.io`, `tests/fakes/` for clock/env/
  processes, contract tests, the ratchet test with the full allowlist. No
  behaviour change.
- **1. Time and random** (9 sites). First fast tests: "a second tag in the
  same second waits for the next one" and "push retry backs off" with no real
  sleeping.
- **2. Env** (18 sites). `entry.py:254` *writes* `VMN_WRITER_ID` for child
  processes; that write stays in the root. `publisher.py:292` snapshots the
  whole env into the tag info and reads it from `io.env`.
- **3. Processes** (8 sites). `run_git` and friends in `core/git_cmd.py`
  take `Processes`; callers in `cli/worktree_*`, `devversion/*`,
  `snapshot/*` pass it.
- **4. Filesystem** (~210 sites; the bulk of the work). `MemFS` + contract
  test first, then parallel worktrees by directory, which do not share files:
  `snapshot/` · `devversion/` · `compat/` + `core/utils.py` ·
  `stamping/` · `cli/worktree_*` + `cli/config_*` + `cli/completion.py` +
  `cli/skill.py`. YAML/TOML/JSON loads go through `fs.read_text`.
- **5. Git backend**. Widen `VMNBackend`, remove the 7 `_be` leaks, inject
  the backend (`get_client` is called from `stamping/base.py`,
  `stamping/repo_status.py`, `cli/output.py`, `devversion/capture.py`),
  write `FakeBackend` + contract test. This is the stage that lets stamp /
  release / show / version-math flows (`stamping/`, ~2.5K lines) run as
  millisecond unit tests.
- **6. Lock and console**. `LockFactory` into `get_repo_lock`; `print`/
  `input` sites take `Console`. Lowest value (pytest's `capsys` already
  covers output), done last so the ratchet allowlist reaches its final form.
- **7. Fast suite**. `tests/unit/` runs with no Docker; add a
  `./tests/run_pytest.sh --suite unit` pass and put it first in
  `ci/pipeline.py`. Port flow coverage from Docker tests to unit tests only
  by *adding* tests.

Stages 1–3 touch overlapping files (`publisher.py`, `commands.py`,
`backends/git.py`), so they run one after another; they are small. Stage 4
is where the parallel worktrees pay off. Stage 5 depends on 4 (the stamper
reads conf files through `fs`).

## Constraints to keep

- `version_stamp.api` is vmn-exp's only way in, and it re-exports `now_iso`,
  `resolve_root_path`, `get_repo_lock`, `sha256_file`, `yaml_safe_load`,
  `VersionControlStamper` and `core_utils` (used for call-time patching).
  When one of these gains a port parameter, the `api` name keeps its current
  signature as a wrapper bound to real IO until vmn-exp has its own plan.
- `tests/test_git_process_budget.py` caps git processes for detached
  stamp/goto: injection must not add git calls.
- `cli/__init__.py` lazy loading stays: `ports.py` imports nothing heavy.
- `VMN_LOCK_FILE_PATH` is a user override only and is never injected into a
  child.

## Decisions needed

1. **Git fake**: in-memory `FakeBackend` behind a widened `VMNBackend`
   (proposed), or keep real git everywhere and only drop Docker. The fake is
   more work (~39 methods to model) but is what makes stamping unit-testable.
2. **Filesystem fake**: our own narrow `FileSystem` port + `MemFS`
   (proposed), or `pyfakefs`. `pyfakefs` needs no production change but works
   by patching globals, which the CLAUDE.md rule forbids.
3. **`api` wrappers**: keep real-IO wrappers in `version_stamp.api` until a
   vmn-exp plan (proposed), or change vmn-exp callers in the same stages.

## Not in this plan

- vmn-exp (`vmn_exp.*`): ~43 `clock=time.time` defaults to move into its
  entry points and ~400 direct IO sites. Separate plan after this one proves
  the pattern.
- `VMN_LOGGER` stays a module global.
