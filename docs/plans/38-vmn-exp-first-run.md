# Plan 38: vmn-exp review fixes, first-run experience and onboarding

> Workstream A of the 2026-11-11 vmn-exp product review. The index, the
> milestone order, the cross-stream conflicts and the owner decisions are in
> [37-vmn-exp-review-fixes.md](37-vmn-exp-review-fixes.md). Each item was drafted by a
> planner that read the code, then revised by a critic that re-checked the
> evidence and looked for tests pinning today's behaviour.
>
> Sizes: S under a day, M 1-3 days, L about a week, XL more. Priorities: P0 security or data loss, P1 blocks adoption or misleads users, P2 quality, P3 nice to have.

Status: **proposed** (2026-11-11). Owner decisions of 2026-11-11 are applied in this file.

Solo impact: see each item's risk line; nothing here may make the single-user case worse.

## Summary

All six findings are real on master (59becdd5). Nothing was run: every claim is from reading the code, and each item says what the implementer must still check.

The plan was drafted at 25f03f3d. The 26 commits since then touch none of the Python or doc files this plan cites (`git diff --stat 25f03f3d..HEAD` shows only `cli/skill.py`, `sdk/models.py` and `sdk/usage.py` under the cited directories), so those line numbers hold. The web UI files A6 cites did move (`ExperimentsPage.tsx`, `SinglesView.tsx`); A6 is rewritten against HEAD. No item was done upstream.

What the owner decided, and what it changed here:

- **A1 (cold start)** fixes the crash without a remote and announces the commits, the tag and the push. The CLI keeps pushing when a remote exists. The item that would have stopped the push (A11) is dropped.
- **A3 (clear error outside a checkout)** does not depend on the core fix. The SDK already has a logger-free root resolver (`_base.resolve_root_path`, `try_repo_root`), so the check sits in the SDK before git mode is entered.
- **A5 (one run instead of wrapper + child)** is on by default with the direct-child rule: only the supervisor's direct child adopts. Opt out with `--no-adopt` or `VMN_EXP_ADOPT=0`. The design is redrawn: the guest SDK run appends to a stream of its own (`<writer id>-sdk~<owner>`) on the adopted record, and the supervisor stays the only writer of run state, the final state, the `run` entry and alerts. The guest also declines, with a warning, when the child resolves a store that does not hold the wrapper's record.
- **A12 (rerun and sweep trials adopt too)** ships with A5, in the same release. `test_exp_rerun_cli.py:50-72` is rewritten.
- **A6 (default board)** changes now: an app with single runs and no outer runs opens on the runs board with metric columns. `JobsKind.test.tsx:94-102` is rewritten.
- **A10 (code-less run)** is built, by explicit opt-in only (`code=False` / `VMN_EXP_CODE=none`), after a verstr spike.

Order: A2, A3, A1, A7 (independent, small) -> A4 -> A5 and A12 together -> A6 -> A8, A9 -> A10 spike -> A10.

Releases: every item ships in a 0.1.x patch release. An item that changes behaviour needs an `upgrading.md` row and a changelog entry, per the removal rule in plan 43 F9; each such item says so in its Risk.

Test edits: the edits to existing tests named in this file are approved. An edit this file does not name still stops and asks.

## Items

| Id | Pri | Size | Item | Owner decision |
|---|---|---|---|---|
| [A1](#a1) | P1 | S | CLI cold start works without a remote and says what it commits, tags and pushes |  |
| [A2](#a2) | P1 | S | core: resolve_root_path must not need the logger to report 'not a repo' |  |
| [A3](#a3) | P1 | S | SDK: start_run() outside a git checkout raises one clear, documented error |  |
| [A4](#a4) | P1 | S | vmn-exp run: export an adoption token to the supervised child |  |
| [A5](#a5) | P1 | L | SDK: the script vmn-exp run launched adopts the wrapper's run and writes its own stream | decided |
| [A12](#a12) | P1 | S | Rerun and sweep trials adopt too (ships with A5) | decided |
| [A6](#a6) | P2 | S | UI: an app with no outer runs opens on the runs board with metric columns | decided |
| [A7](#a7) | P1 | S | Quickstart: one page that installs the dashboard, logs a metric and says what the first run does to git |  |
| [A8](#a8) | P2 | S | client-guide: first run before concepts, and a glossary for the jargon |  |
| [A9](#a9) | P2 | S | Notebook guide |  |
| [A10](#a10) | P3 | L | Code-less run in a non-git directory or notebook, by explicit opt-in | decided |

<a id="a1"></a>
### A1. CLI cold start works without a remote and says what it commits, tags and pushes

P1 · S

**Problem.** `vmn-exp create/run` in a fresh repo calls `auto_init_if_needed` unwrapped (cli/experiment.py:303-307). `init_repo` then calls `be.push()` (stamping/init.py:63), which raises 'No git remote is configured; cannot push' when `selected_remote is None` (backends/git_ops.py:187-192); the entry point rewrites that to 'No git remote configured. vmn needs a remote to push version tags.' (cli/entry.py:263-268). With a remote the same path pushes the init commit(s) and tag `<app>_0.0.0` with only core's generic 'Auto-initializing...' info lines (stamping/init.py:121,129) and nothing about the push; the code comment admits 'this path commits, tags and pushes as a side effect' (cli/experiment.py:290-292). The SDK does the same init with pushes shadowed (gitmode/coldstart.py:79-81). Docs disagree: experiments.md:66-67 and examples/01_minimal.py:5 say a remote is needed; sdk.md:116-122 and examples/README.md:18-20 say it is optional.

**Approach.**

1. In `gitmode/coldstart.py` add `init_tracking(vcs, init, push)`: `vcs.ensure_on_branch()`, then `init(vcs, extra_optional=DIRTY_OK)` inside `local_only(vcs.backend)` when `push` is false, bare when true; returns `(err, initialized)`. `init` is injected (production: `auto_init_if_needed`). `cold_start` calls it with `push=False` (no behaviour change for the SDK).
2. `cli/experiment.py:auto_init` keeps its new-app guard and replaces lines 303-307 with `init_tracking(vcs, auto_init_if_needed, push=vcs.backend.selected_remote is not None)`. No remote means a local-only init instead of a crash. With a remote the CLI pushes as today; that is the decided behaviour (plan 17 F6: a CI checkout's first run commits on the real branch and pushes it).
3. A pure `cold_start_notice(app, repo_missing, app_missing, pushed, remote)` builds the message from what `init_needed` reported (one or two commits, the tag name) and ends with either 'Pushed to <remote>.' or 'Nothing was pushed; share them with git push --follow-tags.' With a remote it is logged before the init, so the user sees the push announced; without one, after.
4. Docs in the same change: experiments.md:66-67 drops 'needs a git remote' and states both cases (CLI: pushes when a remote exists, announced; SDK: never pushes); fix the 01_minimal.py:5 docstring; client-guide.md '1. Install' closing paragraph names the commits, the tag and the push.

Afterwards: `vmn-exp run my_app -- python train.py` succeeds in a repo with no remote, and a first run with a remote announces the push.

**Tests first.**

- packages/vmn-exp/tests/test_coldstart_init_tracking.py (unit, fake vcs/backend/init): test_push_false_never_calls_backend_push
- same file: test_push_true_leaves_the_backend_untouched
- same file: test_push_is_restored_after_init_even_when_init_raises
- same file: test_a_detached_head_is_put_on_its_branch_before_init
- packages/vmn-exp/tests/test_cold_start_notice.py (unit, pure): test_notice_counts_one_commit_when_only_the_app_is_new; test_notice_names_the_tag; test_notice_says_pushed_to_the_remote; test_notice_gives_the_push_command_when_nothing_was_pushed
- packages/vmn-exp/tests/test_cli_coldstart_local.py (real git, mirrors test_sdk_coldstart_local.py): test_cli_cold_start_without_a_remote_succeeds_and_tags_locally
- same file: test_cli_cold_start_with_a_remote_announces_the_push (asserts the log text; remote refs still advance, so test_exp_coldstart_detached.py stays green)

**Files.** `packages/vmn-exp/src/vmn_exp/gitmode/coldstart.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment.py`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/client-guide.md`, `packages/vmn-exp/examples/01_minimal.py`

**Risk.** No existing test changes. Not verified: whether the CLI path reaches `auto_init` at all without a remote. The entry point and `vmn-exp create`'s own status checks may have other remote assumptions; the SDK passes through `build_vcs` + `repo_status` without one (test_sdk_coldstart_local.py:32-41), but the CLI goes through cli/entry.py. The real-git test is written first for that reason. A baseline created without a remote is local; teammates who each cold-start create different `<app>_0.0.0` tags, an exposure the SDK path already has. The docs should say one person pushes the baseline for a shared repo. The CLI and the SDK keep differing on the first run with a remote (the CLI pushes, the SDK does not); that is decided and now documented. Release: 0.1.x patch with an `upgrading.md` row (a command that failed now succeeds; a new notice), per plan 43 F9.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/experiment.py:283-307`; `packages/vmn/src/version_stamp/stamping/init.py:39-67`; `packages/vmn/src/version_stamp/stamping/init.py:111-138`; `packages/vmn/src/version_stamp/backends/git_ops.py:186-197`; `packages/vmn/src/version_stamp/cli/entry.py:263-268`; `packages/vmn-exp/src/vmn_exp/gitmode/coldstart.py:1-10`; `packages/vmn-exp/src/vmn_exp/gitmode/coldstart.py:70-102`; `packages/vmn-exp/tests/test_sdk_coldstart_local.py:32-58`; `packages/vmn-exp/tests/test_exp_coldstart_detached.py:22-32`; `docs/vmn-exp/experiments.md:66-69`; `docs/vmn-exp/sdk.md:116-122`; `packages/vmn-exp/examples/01_minimal.py:5`; `packages/vmn-exp/examples/README.md:18-20`

<a id="a2"></a>
### A2. core: resolve_root_path must not need the logger to report 'not a repo'

P1 · S

**Problem.** `resolve_root_path` walks up from cwd; at the filesystem root it raises an internal RuntimeError, catches it with `except Exception` and calls `VMN_LOGGER.debug(...)` (core/utils.py:236-246). VMN_LOGGER is a proxy that raises `AttributeError: VMN_LOGGER is not initialized (call init_stamp_logger first)` until a logger is installed (core/logging.py:30-36). A library caller outside a repo gets that AttributeError instead of `RuntimeError('Running from an unmanaged directory')`. `_find_vmn_root` catches only RuntimeError (cli/completion.py:20-25), so it leaks through `_complete_apps` too. This is the traceback in finding 3. The SDK's own copy of the function has no such bug (vmn_exp/_base.py:133-143).

**Approach.**

Add a pure `find_managed_root(start, exists)` in core/utils.py returning the first ancestor holding `.git` or `.vmn`, or None: no logging, no exception for control flow. `resolve_root_path()` stays the thin real wrapper: read cwd/VMN_WORKING_DIR, call `find_managed_root(root, os.path.exists)`, raise `RuntimeError('Running from an unmanaged directory')` on None. The debug log of a made-up exception is dropped. No caller signature changes.

**Tests first.**

- tests/test_find_managed_root.py (core suite, unit, fake `exists` over a set of paths): test_returns_the_start_dir_when_it_holds_dot_git
- same file: test_returns_the_nearest_ancestor_holding_dot_vmn
- same file: test_returns_none_at_the_filesystem_root
- same file: test_resolve_root_path_raises_runtime_error_with_no_logger_installed (reset_logger() first, VMN_WORKING_DIR at an unmanaged tmp dir; asserts RuntimeError, not AttributeError)

**Files.** `packages/vmn/src/version_stamp/core/utils.py`, `tests/test_find_managed_root.py`

**Risk.** Core vmn change, but every caller that had a logger sees the same RuntimeError and message (tests/test_skill.py:150-159 pins the message). Existing sync test packages/vmn-exp/tests/test_exp_base.py:47-53 compares the result with the SDK copy for the found case and must stay green. Moving the cwd/env reads behind interfaces is plan 35's job.

**Evidence.** `packages/vmn/src/version_stamp/core/utils.py:227-250`; `packages/vmn/src/version_stamp/core/logging.py:21-45`; `packages/vmn/src/version_stamp/core/logging.py:54-65`; `packages/vmn/src/version_stamp/cli/completion.py:20-30`; `packages/vmn-exp-sdk/src/vmn_exp/_base.py:128-143`; `packages/vmn-exp/tests/test_exp_base.py:47-53`; `tests/test_skill.py:150-159`

<a id="a3"></a>
### A3. SDK: start_run() outside a git checkout raises one clear, documented error

P1 · S

**Problem.** In a plain directory `start_run()` reaches `gitmode().checkout_source` (sdk/create.py:135-136), which calls `_resolve_app_name(app_name, stamped_apps)` and then `resolve_root_path()` (gitmode/checkout.py:42-43) before `build_vcs` installs version_stamp's logger (coldstart.py:20-24). The `ensure_logger()` that `start_run` calls (sdk/run.py:228-230) is vmn_exp._base's, which returns a plain logging logger and does not fill version_stamp's holder (_base.py:12-13, 22-23). Result: the internal AttributeError (A2). Even with A2 in, the user would get the bare 'Running from an unmanaged directory', or, with no VMN_APP_NAME, the misleading 'Cannot infer the vmn app name from this repository (candidates: none)' (sdk/__init__.py:33-37). Neither says what to do. `resume.locate` has the same order (sdk/resume.py:75-78).

**Approach.**

Do the check in the SDK, before git mode is entered, using the SDK's own logger-free resolver, so this item does not depend on A2.
1. New small module `sdk/checkout_guard.py` with a pure `require_checkout(root, cwd)`: returns `root`, or raises `RuntimeError(NOT_A_CHECKOUT)` when `root` is None. The message names `cwd` and the ways out: `git init && git commit --allow-empty -m init` here; or VMN_SNAPSHOT_METADATA for an exported tree (sdk.md 'Runs without a git checkout'). A10 adds the third way out to the message when it lands (`code=False` / `VMN_EXP_CODE=none`).
2. `record_source` (sdk/create.py:129-136), in its checkout branch, calls `require_checkout(try_repo_root(), os.getcwd())` before `gitmode().checkout_source(...)`. `resume.locate`'s checkout branch (resume.py:75-76) does the same before `checkout.stamped_apps`. A non-repo is then reported as a non-repo, not as a missing app name or a missing logger.
3. Document the RuntimeError in sdk.md next to the GIT_MODE_MISSING case.

With only vmn-exp-sdk installed and no checkout, NOT_A_CHECKOUT wins over GIT_MODE_MISSING: installing vmn-exp would not help in a plain directory. The first subprocess test pins that order.

**Tests first.**

- packages/vmn-exp/tests/test_sdk_checkout_guard.py (unit, pure): test_require_checkout_returns_the_root
- same file: test_require_checkout_raises_runtime_error_naming_the_directory_and_the_ways_out
- same file: test_the_message_never_mentions_vmn_logger
- packages/vmn-exp/tests/test_sdk_outside_checkout.py (subprocess in an empty tmp dir, no git): test_start_run_in_a_plain_directory_raises_not_a_checkout_with_app_and_store_env_set
- same file: test_start_run_in_a_plain_directory_without_app_name_reports_the_checkout_not_the_app
- same file: test_resume_run_id_in_a_plain_directory_raises_not_a_checkout
- same file: test_not_a_checkout_wins_over_git_mode_missing_on_an_sdk_only_path
- same file: test_snapshot_metadata_mode_is_not_affected (VMN_SNAPSHOT_METADATA set, no checkout: no guard)

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/checkout_guard.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/resume.py`, `docs/vmn-exp/sdk.md`

**Risk.** The error type for the no-app-name case changes from ValueError to RuntimeError when the directory is not a repo; inside a repo nothing changes. `try_repo_root` honours VMN_WORKING_DIR like the core function (_base.py:135-137), so reruns that set it are unaffected. A directory holding a bare `.vmn` and no `.git` passes the guard and fails later as today; out of scope. The read side (`list_runs`/`get_run`) already uses `try_repo_root` (sdk/reader.py:86) and was not audited further. `sdk/resume.py:locate` is also changed by A5 and plan 41 D6; order A3 -> A5 -> D6. Release: 0.1.x patch with an `upgrading.md` row for the changed error type, per plan 43 F9.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:32-37`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:129-136`; `packages/vmn-exp/src/vmn_exp/gitmode/checkout.py:27-30`; `packages/vmn-exp/src/vmn_exp/gitmode/checkout.py:39-46`; `packages/vmn-exp/src/vmn_exp/gitmode/coldstart.py:20-32`; `packages/vmn-exp-sdk/src/vmn_exp/_base.py:12-23`; `packages/vmn-exp-sdk/src/vmn_exp/_base.py:133-143`; `packages/vmn-exp-sdk/src/vmn_exp/core/storage_resolve.py:114-118`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:228-230`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/__init__.py:13-37`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/resume.py:67-85`

<a id="a4"></a>
### A4. vmn-exp run: export an adoption token to the supervised child

P1 · S

**Problem.** `_Supervision._start` builds the child env inline and exports only VMN_EXPERIMENT_ID, VMN_APP_NAME, VMN_METRICS_FILE and the sampling marker (cli/run.py:312-327). The child cannot tell 'I am the workload of this run' from 'I am a job launched under this run', so `start_run()` can only nest (sdk/create.py:200-223). There is a precedent for a supervisor-to-SDK marker: `SUPERVISOR_SAMPLES_ENV` (cli/run.py:323-325).

**Approach.**

1. Extract the env construction out of `_start` into a pure `supervised_env(base_env, verstr, app_name, metrics_path, samples_tree, extra_env, adopt_pid)` in a new `cli/supervised_env.py` (cli/run.py is 539 lines; the name avoids the existing `core.rerun.child_env`). It returns the dict `_start` passes to Popen, including the existing 'None value removes a variable' rule.
2. The function always drops `VMN_EXP_ADOPT_RUN_ID` and `VMN_EXP_ADOPT_PID` inherited from `base_env` (a `vmn-exp run` started inside an adopted script must not pass its launcher's token on). When `adopt_pid` is not None it then sets `VMN_EXP_ADOPT_RUN_ID=<verstr>` and `VMN_EXP_ADOPT_PID=<supervisor pid>`. VMN_EXPERIMENT_ID stays exported, so nesting of everything else is unchanged.
3. In the same module, a pure `adopt_requested(args, env)`: True unless `getattr(args, "adopt", True)` is False (`--no-adopt`; a Namespace built without the flag counts as True) or `env['VMN_EXP_ADOPT']` is one of `0`, `false`, `no`, `off` (any case).
4. `_Supervision.__init__` takes a keyword-only `adopt=False` (the class is built positionally in test_exp_rerun_recording.py:140,155,165, which must keep working unedited). A small method `_child_env(base_env, pid)` calls `supervised_env(..., adopt_pid=pid if self.adopt else None)`; `_start` calls `self._child_env(dict(os.environ), os.getpid())`. This is the one path the token takes to a child, for every call site.
5. `experiment_run` builds its supervision through a small `run_supervision(storage, app_name, verstr, args, exp_conf, root, env)` that passes `adopt=adopt_requested(args, env)`; the handler passes `os.environ` (plan 44 G8 later passes `io.env`).
6. `--no-adopt` (`dest="adopt"`, `action="store_false"`, default True) on the experiment parser next to `--no-system-metrics` (cli/plugin.py:194). The parser is flat, so `run` and `rerun` both get it; A12 adds the flag to the sweep parser and turns adoption on for rerun and sweep trials.

This item alone changes nothing observable: no SDK reads the token until A5.

**Tests first.**

- packages/vmn-exp/tests/test_cli_supervised_env.py (unit, plain dicts): test_exports_experiment_id_app_and_metrics_file
- same file: test_adds_the_adoption_run_id_and_pid_when_adopting
- same file: test_no_adoption_vars_without_adopt_pid
- same file: test_inherited_adoption_vars_are_dropped_when_not_adopting
- same file: test_extra_env_none_value_removes_a_variable (pins cli/run.py:326-327 through the extraction)
- same file: test_supervisor_samples_marker_set_only_when_sampling
- packages/vmn-exp/tests/test_cli_adopt_flag.py (unit, argparse.Namespace + dict env): test_adopt_is_requested_by_default; test_args_without_the_attribute_request_adoption; test_no_adopt_flag_turns_it_off; test_vmn_exp_adopt_0_false_no_off_turn_it_off
- packages/vmn-exp/tests/test_cli_adopt_call_sites.py (unit; an `EmptyStorage` subclass from tests/empty_storage.py, a Namespace with `capture_output=False`, `kill_grace_sec=1`, an explicit `cwd`, so `_Supervision.__init__` reads no env and no disk): test_run_supervision_adopts_by_default; test_run_supervision_with_no_adopt_does_not
- same file: test_supervision_child_env_carries_the_token_only_when_adopting (calls `_child_env({}, 4242)`)

**Files.** `packages/vmn-exp/src/vmn_exp/cli/supervised_env.py`, `packages/vmn-exp/src/vmn_exp/cli/run.py`, `packages/vmn-exp/src/vmn_exp/cli/plugin.py`

**Risk.** None on its own (new env vars nothing reads). Naming is the lasting commitment: `VMN_EXP_ADOPT_RUN_ID`, `VMN_EXP_ADOPT_PID`, `--no-adopt`, `VMN_EXP_ADOPT`. Unrelated to the existing `core/adopt.py` (stream inheritance after a copy). `--no-adopt` must be in plan 39 B5a's ACTION_FLAGS for `run` and `rerun` (and for `sweep agent`, A12), so A4 lands before B5a. Same file as plan 39 B9b and plan 44 G8 (`_Supervision`): order A4 -> A5/A12 -> B9b -> G8. If plan 44 G1 has landed, the two new `os.environ`/`os.getpid` reads in `_start` and the handler go on its allowlist in the same commit.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/run.py:254-257`; `packages/vmn-exp/src/vmn_exp/cli/run.py:269-287`; `packages/vmn-exp/src/vmn_exp/cli/run.py:312-339`; `packages/vmn-exp/src/vmn_exp/cli/output_tee.py:23-28`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:200-223`; `packages/vmn-exp-sdk/src/vmn_exp/core/rerun.py:159-171`; `packages/vmn-exp/src/vmn_exp/cli/plugin.py:69-71`; `packages/vmn-exp/src/vmn_exp/cli/plugin.py:194`; `packages/vmn-exp/tests/test_exp_rerun_recording.py:140`; `packages/vmn-exp/tests/empty_storage.py:1-30`

<a id="a5"></a>
### A5. SDK: the script vmn-exp run launched adopts the wrapper's run and writes its own stream

P1 · L · depends on A4 · ships together with A12

**Problem.** A script that calls `start_run()` and is launched by `vmn-exp run` produces two runs: the wrapper (state, output.log, no metrics) and a nested `.r2` child with the metrics, because `pick_parent` falls back to the launcher's VMN_EXPERIMENT_ID (sdk/create.py:218-223, sdk/context.py:148-153). The docs teach this as the model (client-guide.md:34-36; sdk.md:66-69). The dashboard then lists each simple run as an outer run with a 1/1 rollup and no metric columns.

The first draft of this item had the supervisor and the guest SDK run append to the same stream of the one record. On a shared local record copy both processes resolve the same stream: `own_stream` is `<writer id>~<owner>`, the writer id is the host name in both, and the owner is the record directory's (core/writer.py:95-102; storage/local_streams.py:14-22). In the code a stream's owner is the record copy, not a process (core/streams.py:4-8; storage/stream_owner.py:5, 13-14), and experiments.md:1837-1838 says every process of one checkout appends to the same stream. The owner decided against using that here: the SDK run must not append to the files the supervisor writes (architecture.md:310-312, 'a writer ... never rewrites another writer's files'). So the guest gets a stream of its own, and each stream of an adopted record has one appending process.

**Approach.**

Model: one record, two processes, two streams.

- The supervisor is the only writer of `run_state.yml` (heartbeat, exit code, final state), the `run` log entry, `output.log`, its system metrics, the metrics-file lines and the failure alert. It appends to `<writer id>~<owner>` as today.
- The adopted SDK run is a guest. It appends only to a stream of its own, `<writer id>-sdk~<owner>`, and it flushes, ships and compacts that stream the way any `Run` does with its own. It never writes run state, a `run` entry or a finish alert.

How the guest gets its own stream:

1. `core/streams.py` (pure): `GUEST_WRITER_SUFFIX = "-sdk"` and `guest_writer_id(writer)` returning `clean_writer_id(writer) + GUEST_WRITER_SUFFIX`. A suffix, not a prefix: a bucket policy that allows a pod `log/<its writer id>*` keeps matching.
2. `core/writer.py`: `own_stream(storage, app_name, verstr, writer=None)` uses `writer or get_writer_id()` both in the stream key and in the `storage.stream_owner(app_name, verstr, writer)` call it already makes (lines 100-102). `append_metric_entries`, `append_entries_to_log` and `sync_to_remote` gain a keyword `writer=None` that they pass to `own_stream` (lines 188-217, 234-241). Nothing else in the module changes; no storage method is added or changed.
3. `sdk/run.py`: `Run.__init__` takes a keyword `writer=None`, kept as `self._writer`, and uses it in the four places a run names its stream: the `LogBuffer` append (368-371), the `_log_sync` job (373-381), the compaction at close (592-593) and the sync after `set_intent` on a finished run (724-726). A run without a writer passes no extra argument, so the tests that replace `sync_to_remote` or `compact_by` on `vmn_exp.sdk.run` with positional fakes (test_sdk_detach.py:86, test_exp_push_metrics.py:90,131) keep working. The process-wide writer id (`set_default_writer_id`, `VMN_WRITER_ID`) is not touched: it also names the runs the same process opens later, and `VMN_WRITER_ID` would override it.

What the storages do with the guest's writer id (read, not run):

- Shared local record copy (the usual `vmn-exp run` case: both processes open the checkout's store). `LocalStreams.stream_owner` returns the copy's one owner for any writer (storage/local_streams.py:14-22), so the two streams are `host~o1` and `host-sdk~o1`: two log files and two metric files, each with one appending process. There is precedent for a second writer id on one copy: the UI server writes as `vmn-server` beside a live run (ui/cli.py:170-178).
- `BufferedRemoteStorage` or a plain remote. The owner is already per process (storage/buffered.py:129-131; storage/base.py:287-290 with core/streams.py:47-51), so the streams differ in both parts.
- Shipping is per record copy, not per process: `sync_log_to_remote` and `sync_metrics_to_remote` ship every stream the copy owns, whatever writer id the caller names, under the copy's ship lock, and a segment is created only if it does not exist (storage/cached_logs.py:15-19, 193-216; storage/cached_metrics.py:179-203; storage/ship_state.py:1-12). So on a shared copy either process's sync may upload bytes of either stream. This is today's arrangement for any two processes of one copy and A5 does not change it.
- Compaction is per stream, but compacting a stream retires the copy's owner for every writer (storage/local_streams.py:42-47; storage/cached_metrics.py:122-135). When the guest compacts `host-sdk~o1` at finish, the copy moves to owner `o2`; the supervisor's later appends go to `host~o2` (core/writer.py:95-102 resolves per call; storage/local_metrics.py:64-78 redirects a block for a retired stream), and its `host~o1` metric file would stay uncompacted, because the supervisor compacts only the stream `own_stream` names at the end (cli/run.py:457-459). The same happens in the other direction if a long guest seals its stream (core/metric_compact.py:189-197). Step 7 handles it.

What a reader does with two streams on one record: nothing new. A record with several streams is the normal multi-writer case. The log view merges every stream's entries (storage/files.py:167-176), the metric reader merges every stream's points per key in writer order (core/series_reader.py:225-229), a `.vmx` is per stream (core/metric_compact.py:96-116), and status comes from `run_state.yml` alone. Displays show the writer id (experiments.md:1840-1841), so the guest's entries read `_writer: <host>-sdk`. No record-format or store-layout change: `RECORD_FORMAT_VERSION` stays 2.

Steps:

4. New `sdk/adoption.py` (pure): `requested(env, getppid, parent, nested, fork_from, active)` returns the token's verstr only when none of parent/nested/fork_from was given and `getppid() == int(env['VMN_EXP_ADOPT_PID'])`, that is, the caller is the supervisor's direct child. It removes both variables from `env` when it grants, following `resume.requested_run_id` (resume.py:41-44), so the process's own subprocesses never see the token and a later `start_run()` in the process nests under the run as today. A process further down the tree never matches and nests as today. A malformed pid is a refusal, not an error. `start_run` calls it only when no resume ref was resolved (`run_id=` or `VMN_RESUME_RUN_ID`, run.py:234-236), with `os.environ` and `os.getppid`. It also takes `active` (the run open on this thread, `context.context_run()`) and refuses without consuming the token while one is open: the call then reaches `create_record`, whose re-entry guard raises as today (create.py:115, 147-170). Adoption must not become a way past that guard.
5. `start_run` (sdk/run.py:232-256) gains one branch. When adoption is granted it calls `resume.locate(app_name, verstr, storage, action="adopt")` to resolve app, storage and conf. A ValueError there means the wrapper's record is not in the store the child resolved (the supervisor was given `--store` on the command line, which the child does not inherit: cli/run.py:318-326 exports no storage; core/fork.py:44-52 raises it). Then the guest declines: it warns once, naming the run, the store it resolved and `--no-adopt`, and `start_run` creates a nested run exactly as today. Any other error from `locate` (no checkout, git mode missing) propagates, as it does from `create_record` today. Otherwise it builds a `GuestRun` with `writer=guest_writer_id(get_writer_id())`, `prior_state=None` and `capture_output=False`. The step counter starts at 0 without reading the log (sdk/steps.py:36-43 with `resumed=False`). Both new modules are imported inside the branch (plan 41 D1's import budget).
6. New `sdk/guest_run.py`: `GuestRun(Run)`, overriding only what a guest must not do.
   - `_publish` and `_publish_heartbeat` write nothing (run.py:762-764, 778-782; state_publisher.py:63-76). The heartbeat thread stays, to flush the log buffer and drive the sync (run.py:766-776).
   - `_record_final` and `_record_release` call `_close_attempt(deadline, outcome)` with an outcome that appends the `error` entry when one was given and returns no state: no `run` entry (the supervisor appends its own, cli/run.py:446-455), no final state, no finish alerts (run.py:515-543, 572-575). `on_sigterm="release"` therefore has no effect on a guest; the supervisor records the real exit.
   - Everything else is inherited: `_close_remote_writers` closes the log sync and compacts the guest's own stream (run.py:586-595, now with `self._writer`); atexit and the SIGTERM handler go through the two overridden methods (run.py:795-829).
   - `capture_output=True` is ignored with one debug line (sdk.md:108 already says to leave it off under `vmn-exp run`). The sampler stays off under a sampling supervisor as today (sdk/sysmetrics.py:91-96).
7. `cli/run.py`: `_Supervision._ingest` notes `own_stream(...)` in a set each time it has records to append, and `_finish` compacts every noted stream and the current one (an append can be redirected to the copy's next stream after it was noted, storage/local_metrics.py:70) under the one deadline, instead of only the current one (457-459). A stream already compacted is skipped by `compact_writer` (core/metric_compact.py:106-109). The supervisor still compacts only streams it appended to.
8. Inputs given to the adopting call are appended as entries, like a resume: params and note via `_record_resume_inputs` (run.py:295-300), tags via `set_tags`, intent via `set_intent`. `name=` warns once that the name comes from `vmn-exp run --name`.
9. Docs in the same change, listed under Files. architecture.md 'The life of a run' (235-239) gains the two token variables on the spawn line and replaces 'start_run() opens an inner run under VMN_EXPERIMENT_ID' with 'start_run() in the direct child records into this run, in its own stream'; 'Outer runs and inner runs' (270-273) names the exception. CLAUDE.md:229 becomes: '`VMN_EXPERIMENT_ID` set in the environment auto-parents any new run, except the first plain `start_run()` in the direct child of `vmn-exp run`, `rerun` or a sweep trial, which records into that run (`--no-adopt` / `VMN_EXP_ADOPT=0` turn it off).' experiments.md's Streams paragraph (1825-1841) says 'Every process of one checkout appends to the same stream'; add the guest's `-sdk` stream there. `cli/skill.py:18-21` gains one line ('or call `start_run()` in the script: it records into the same run'), and docs/vmn-exp/agent-skill.md is regenerated from it.

Unchanged: `nested=True`, `parent=`, `fork_from=`, `create_run/create_runs`, `start_run(run_id=)`, remote pods and any process that is not the supervisor's direct child. A launcher that is itself the direct child and wants its own outer run under the wrapper passes `parent=os.environ["VMN_EXPERIMENT_ID"]` or runs with `--no-adopt`.

**Tests first.**

- packages/vmn-exp/tests/test_streams_guest_writer.py (unit, pure): test_guest_writer_id_keeps_the_writer_as_prefix_and_adds_the_suffix; test_guest_writer_id_replaces_a_tilde
- packages/vmn-exp/tests/test_writer_own_stream_writer.py (unit; an `EmptyStorage` subclass that records appends and answers `stream_owner` with one fixed owner, as a shared local copy does): test_supervisor_and_guest_on_one_copy_append_to_different_streams (the invariant, written before any other A5 code)
- same file: test_own_stream_asks_the_storage_for_the_given_writers_owner; test_own_stream_without_a_writer_is_unchanged
- same file: test_metric_and_log_entries_with_a_writer_go_to_that_writers_streams; test_sync_to_remote_with_a_writer_names_that_writers_stream
- packages/vmn-exp/tests/test_sdk_adoption_request.py (unit, dict env, fake getppid): test_direct_child_gets_the_token_and_it_is_removed_from_env
- same file: test_a_grandchild_is_refused_and_the_env_is_left_alone
- same file: test_no_adoption_with_explicit_parent / _nested / _fork_from
- same file: test_second_request_in_the_same_env_gets_none
- same file: test_a_malformed_pid_is_refused_not_raised
- same file: test_refused_and_the_token_kept_while_a_run_is_open_on_this_thread
- packages/vmn-exp/tests/test_sdk_guest_run.py (unit, the same recording storage fake): test_guest_appends_metrics_to_the_guest_stream_of_the_adopted_run
- same file: test_guest_never_writes_run_state_on_open_heartbeat_finish_or_release
- same file: test_guest_finish_writes_no_run_entry_and_fires_no_alerts
- same file: test_guest_finish_with_error_records_the_error_entry
- same file: test_guest_syncs_and_compacts_only_its_own_stream (the stream names passed to the fake's `sync_*_to_remote` and to `compact_by`)
- same file: test_guest_appends_params_note_and_tags_as_entries; test_guest_warns_that_name_is_ignored; test_guest_ignores_capture_output
- same file: test_a_run_without_a_writer_passes_no_writer_argument (pins step 3's compatibility with the positional fakes)
- packages/vmn-exp/tests/test_sdk_adoption_declined.py (unit, two in-memory stores): test_adoption_is_declined_with_a_warning_when_the_wrapper_record_is_not_in_the_childs_store_and_a_nested_run_is_created
- packages/vmn-exp/tests/test_cli_supervision_streams.py (unit, recording storage whose owner changes between two ingests): test_supervision_notes_each_stream_it_appends_to_across_an_owner_change; test_finish_compacts_the_noted_streams_and_the_current_one
- packages/vmn-exp/tests/test_storage_two_writers_one_copy.py (the real local storage on tmp_path; pins the storage behaviour the design rests on, expected green on arrival): test_two_writer_ids_on_one_copy_share_the_owner_and_get_separate_files; test_compacting_one_writers_stream_moves_both_writers_to_a_new_owner
- packages/vmn-exp/tests/test_run_adopts_wrapper.py (real git, app_layout, subprocess): test_script_with_start_run_under_vmn_exp_run_is_one_run_with_its_metrics
- same file: test_the_record_holds_a_supervisor_stream_and_a_guest_stream (two log writers, the guest's ending in `-sdk`)
- same file: test_adopted_run_status_and_exit_code_are_the_processs (script exits 3 after finish(0))
- same file: test_exactly_one_run_entry_and_one_final_state_are_recorded
- same file: test_adopted_run_ends_fully_compacted (`record_compacted` is True with system metrics on)
- same file: test_second_plain_start_run_in_the_script_nests_under_the_run
- same file: test_no_adopt_flag_keeps_wrapper_plus_child
- same file: test_workers_spawned_by_a_shell_launcher_all_nest_and_none_adopts

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/core/streams.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/writer.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/adoption.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/guest_run.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/resume.py` (the `action="adopt"` call only), `packages/vmn-exp/src/vmn_exp/cli/run.py`, `packages/vmn-exp/src/vmn_exp/cli/skill.py`, `docs/vmn-exp/agent-skill.md` (regenerated), `docs/vmn-exp/architecture.md`, `docs/vmn-exp/client-guide.md` (idea 4), `docs/vmn-exp/sdk.md` ('CLI or SDK?', 'Nesting', the env table at 1446), `docs/vmn-exp/experiments.md` (run's env table at 175, the nesting section at 375-400, Streams at 1825-1841, the env-var table at 2081-2104), `docs/vmn-exp/ai-fleet-tracking.md` (line 102), `CLAUDE.md` (line 229)

**Risk.** The largest behaviour change in the workstream.

1. Users of `vmn-exp run` + `start_run()` get one run where they had two: saved queries on `kind = "outer"` or `parent = ...` and anything reading metrics from the child change for new runs; old runs are untouched.
2. A launcher script that is itself the direct child and opens its own outer run has that run merged into the wrapper, one level less; its children still nest under the same id.
3. A script that opens several top-level runs in sequence gets the first merged into the wrapper and the rest nested under it. `--no-adopt` restores today's shape in all three.
4. The run's result is the process's exit code. A script that calls `run.finish(exit_code=2)` and then exits 0 reads succeeded; today its child run would read failed. The docs say to exit non-zero.
5. The direct-child rule is deliberately conservative: where a wrapper spawns rather than execs, nothing is adopted and behaviour equals today's, never a wrong merge. Whether `uv run`, `conda run` and Windows venv launchers exec or spawn cannot be settled by reading this repo; where they spawn, the docs show `uv run vmn-exp run app -- python train.py`.
6. Shipping stays per record copy (see Approach). The repo rule 'only a stream's owner appends/ships/compacts it' holds as the code defines it: the owner is the copy, and both processes are processes of that copy (storage/stream_owner.py:13-14). What A5 adds is one appending process per stream and compaction of a stream only by the process that appended to it. Plan 37's invariant note 1 reads further ('never ships ... the supervisor's'): on a shared copy that would need `sync_log_to_remote` and `sync_metrics_to_remote` to select by their `writer_id` argument, a storage change this item does not make. Open for the owner: accept shipping per copy, or add that storage item.
7. A guest killed without a chance to finish leaves its stream uncompacted. On a shared copy the supervisor's final sync still ships its bytes; `vmn-exp compact` compacts it later (core/metric_compact.py:5-8). On a log buffer of its own the loss is the one plan 40 C5/C6 addresses.
8. The same metric key logged through both `$VMN_METRICS_FILE` and `run.log_metric` lands in two streams and is merged like any two writers' points.
9. If two different stores both hold a record with the wrapper's verstr, a child that resolves the other one adopts there. Not handled; the token carries no store identity.
10. An adopted run's final state is written only by the supervisor, whose final sync is logged at debug when it fails (cli/supervisor.py:87-126). Plan 40's new supervisor item (off-thread ships and the final-state retry) matters more once A5 ships.
11. `-sdk` in the stream name is a lasting commitment: it is an object name in every store.
12. Not read: `split_storage` in core/state_cas.py, which `RunStatePublisher.__init__` calls (state_publisher.py:45-61). The guest still constructs a publisher it never uses; the implementer confirms construction does no IO or gives `Run` a keyword to skip it.

File size: `sdk/run.py` is 889 lines; the item adds one branch and one keyword there and puts the rest in two new modules. It must land before plan 44 G18 caps the file, or extract first. Order within `sdk/run.py` across plans stays C1 -> C7 -> C4 -> C3 -> C9 -> C8 -> A5 -> D5/D6 -> G9 -> G10 (plan 37). No test in packages/vmn-exp/tests that combines `vmn-exp run` with an SDK script and asserts two runs was found, apart from the rerun case (A12); the implementer greps again before starting. Release: 0.1.x patch, together with A12, with an `upgrading.md` row (one run instead of two; the `-sdk` stream; the two switches), per plan 43 F9.

**Owner decision (2026-11-11).** Adoption is on by default with the direct-child rule; `--no-adopt` and `VMN_EXP_ADOPT=0` turn it off. The guest writes its own stream. Rerun and sweep trials adopt too and ship with this item (A12).

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/core/writer.py:77-110`; `packages/vmn-exp-sdk/src/vmn_exp/core/writer.py:171-241`; `packages/vmn-exp-sdk/src/vmn_exp/core/streams.py:1-51`; `packages/vmn-exp-sdk/src/vmn_exp/storage/stream_owner.py:1-26`; `packages/vmn-exp-sdk/src/vmn_exp/storage/local_streams.py:14-59`; `packages/vmn-exp-sdk/src/vmn_exp/storage/local_metrics.py:64-88`; `packages/vmn-exp-sdk/src/vmn_exp/storage/local_metrics.py:107-115`; `packages/vmn-exp-sdk/src/vmn_exp/storage/cached.py:297-306`; `packages/vmn-exp-sdk/src/vmn_exp/storage/cached.py:320-325`; `packages/vmn-exp-sdk/src/vmn_exp/storage/cached_logs.py:1-19`; `packages/vmn-exp-sdk/src/vmn_exp/storage/cached_logs.py:193-216`; `packages/vmn-exp-sdk/src/vmn_exp/storage/cached_metrics.py:122-135`; `packages/vmn-exp-sdk/src/vmn_exp/storage/cached_metrics.py:164-203`; `packages/vmn-exp-sdk/src/vmn_exp/storage/ship_state.py:1-12`; `packages/vmn-exp-sdk/src/vmn_exp/storage/buffered.py:129-140`; `packages/vmn-exp-sdk/src/vmn_exp/storage/base.py:287-290`; `packages/vmn-exp-sdk/src/vmn_exp/core/metric_compact.py:1-13`; `packages/vmn-exp-sdk/src/vmn_exp/core/metric_compact.py:96-116`; `packages/vmn-exp-sdk/src/vmn_exp/core/metric_compact.py:166-197`; `packages/vmn-exp-sdk/src/vmn_exp/storage/files.py:167-176`; `packages/vmn-exp-sdk/src/vmn_exp/core/series_reader.py:225-229`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:232-300`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:366-383`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:428-434`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:493-595`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:716-726`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:762-829`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/steps.py:36-43`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/resume.py:34-44`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/resume.py:67-85`; `packages/vmn-exp-sdk/src/vmn_exp/core/fork.py:44-52`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:108-115`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:147-170`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:200-223`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/context.py:148-153`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/state_publisher.py:40-76`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/sysmetrics.py:91-96`; `packages/vmn-exp/src/vmn_exp/cli/run.py:99-110`; `packages/vmn-exp/src/vmn_exp/cli/run.py:312-339`; `packages/vmn-exp/src/vmn_exp/cli/run.py:420-462`; `packages/vmn-exp/src/vmn_exp/cli/run.py:523-539`; `packages/vmn-exp/src/vmn_exp/cli/supervisor.py:87-126`; `packages/vmn-exp/src/vmn_exp/ui/cli.py:170-178`; `packages/vmn-exp/src/vmn_exp/cli/skill.py:14-22`; `packages/vmn-exp/tests/test_sdk_detach.py:84-86`; `packages/vmn-exp/tests/test_exp_push_metrics.py:87-90`; `docs/vmn-exp/architecture.md:235-239`; `docs/vmn-exp/architecture.md:270-273`; `docs/vmn-exp/architecture.md:310-312`; `docs/vmn-exp/experiments.md:1825-1841`; `docs/vmn-exp/client-guide.md:34-36`; `docs/vmn-exp/sdk.md:66-69`; `docs/vmn-exp/ai-fleet-tracking.md:102`; `CLAUDE.md:229`

<a id="a12"></a>
### A12. Rerun and sweep trials adopt too (ships with A5)

P1 · S · depends on A4, A5 · same release as A5

**Problem.** Reruns and sweep trials go through the same `_Supervision` (cli/rerun.py:159-165, cli/sweep/agent.py:99-103) and double the same way: sweeps.md:112 documents 'nests under the trial run', and the sweep summary carries a `metric_source` indirection to find the metric on a descendant (core/sweep/summary.py:57-78; sweep/agent.py:140-148). Existing tests pin the nested shape: test_exp_rerun_cli.py:50-72 asserts a rerun of an SDK script creates exactly two runs with `inner.parent == outer`, and sdk.md:66-69 documents it.

**Approach.**

Both call sites pass the adoption flag to `_Supervision`; the token then reaches the child through the one path A4 built (`_child_env` -> `supervised_env`).

1. `cli/rerun.py`: extract the construction at 159-164 into `rerun_supervision(storage, source, verstr, args, exp_conf, cwd, workdir, exp_dir, env)`, which builds the `_Supervision` with today's arguments plus `adopt=adopt_requested(args, env)`. `_execute` computes `experiment_conf(vcs)` and `experiment_dir(vcs, params)` and passes `os.environ`. The rerun child keeps `VMN_WORKING_DIR`, `VMN_EXPERIMENT_DIR` and the removed `VMN_RESUME_RUN_ID` (core/rerun.py:159-171). `--no-adopt` is already on the experiment parser (A4).
2. `cli/sweep/agent.py`: extract the construction at 99-101 into `trial_supervision(storage, app_name, verstr, trial_args, exp_conf, sweep_env, on_tick, root, env)` with `adopt=adopt_requested(trial_args, env)`. Add `--no-adopt` to the sweep parser next to `--no-system-metrics` (cli/sweep/parser.py:59), for `sweep agent`.
3. Why the rerun child finds the record: the rerun exports `VMN_EXPERIMENT_DIR` (cli/rerun.py:161; core/rerun.py:166-168), so the child's `resume.locate` opens the same local store root and the same record copy as the supervisor. If the restored workspace's conf names a remote that does not hold the record, the guest ships nothing there (`remote_for`, storage/cached.py:320-325) and the supervisor ships the copy's streams. If the record is not found at all, A5's decline path gives today's nested run.
4. `metric_source` logic stays: it already returns the trial's own verstr when the trial has the metric (core/sweep/summary.py:73-78; test_sweep_summary.py:112-118), and it is still needed for old sweeps and for trials that launch children. Update the comment at sweep/agent.py:141-143.
5. Test edit: rewrite `test_sdk_run_errors_with_hint_and_override_yields_inner_run` (test_exp_rerun_cli.py:50-72) as `test_sdk_run_errors_with_hint_and_override_records_into_the_rerun`: the first half (the hint for an SDK-run original) is unchanged; the second half expects one new run that carries `rerun_of == orig` and the metric `m`, and no run with a parent.
6. Docs: sdk.md:66-69 ('the script's `start_run()` then opens an inner run of the rerun record' becomes 'records into the rerun record'); sweeps.md:101-103 (the trial child also gets the adoption token) and :112 (the comment `# nests under the trial run` becomes `# records into the trial run`); experiments.md's rerun section; `--no-adopt` in the flag tables for `run`, `rerun` and `sweep agent`.

**Tests first.**

- packages/vmn-exp/tests/test_cli_adopt_call_sites.py (unit, the file A4 starts; `EmptyStorage` subclass, Namespace args, SimpleNamespace source and workdir, dict env): test_rerun_supervision_adopts_and_keeps_the_rerun_env
- same file: test_rerun_supervision_with_no_adopt_does_not
- same file: test_trial_supervision_adopts_and_keeps_the_sweep_env
- same file: test_trial_supervision_with_vmn_exp_adopt_0_does_not
- packages/vmn-exp/tests/test_sweep_parser_adopt.py (unit, the sweep parser alone): test_sweep_agent_takes_no_adopt
- packages/vmn-exp/tests/test_exp_rerun_cli.py: the rewrite in step 5
- packages/vmn-exp/tests/test_rerun_adoption.py (real git): test_rerun_child_resolves_the_same_store_and_adopts; test_rerun_with_no_adopt_keeps_wrapper_plus_inner
- packages/vmn-exp/tests/test_sweep_trial_adoption.py (real git): test_trial_metric_is_the_trial_runs_own_and_metric_source_is_the_trial
- same file: test_early_stop_reads_the_adopted_trials_points

**Files.** `packages/vmn-exp/src/vmn_exp/cli/rerun.py`, `packages/vmn-exp/src/vmn_exp/cli/sweep/agent.py`, `packages/vmn-exp/src/vmn_exp/cli/sweep/parser.py`, `packages/vmn-exp/tests/test_exp_rerun_cli.py`, `docs/vmn-exp/sweeps.md`, `docs/vmn-exp/sdk.md`, `docs/vmn-exp/experiments.md`

**Risk.** Changes a documented, tested shape for sweeps and reruns. Sweep dashboards that expand a trial to see its inner run show a leaf instead; sweeps recorded before the change keep their shape. A sweep whose `command:` goes through a shell (`sh -c ...`) or another launcher that spawns does not adopt and behaves as today. Not read: `PeerPoints` (the early-stop reader); the real-git early-stop test is there to show it reads a trial's points from both of its streams. A rerun's restored workspace is another checkout of the same repo; `resume.locate` in it follows the path the nested child's `checkout_source` takes today, but that was not run. Release: with A5, one `upgrading.md` row covering run, rerun and sweep trials, per plan 43 F9.

**Owner decision (2026-11-11).** Rerun and sweep trials adopt too, and this ships with A5, not after it.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/rerun.py:142-168`; `packages/vmn-exp/src/vmn_exp/cli/sweep/agent.py:73-107`; `packages/vmn-exp/src/vmn_exp/cli/sweep/agent.py:140-156`; `packages/vmn-exp/src/vmn_exp/cli/sweep/parser.py:53-59`; `packages/vmn-exp-sdk/src/vmn_exp/core/rerun.py:159-171`; `packages/vmn-exp-sdk/src/vmn_exp/core/sweep/command.py:25-32`; `packages/vmn-exp-sdk/src/vmn_exp/core/sweep/summary.py:57-78`; `packages/vmn-exp-sdk/src/vmn_exp/core/storage_resolve.py:136-140`; `packages/vmn-exp-sdk/src/vmn_exp/storage/cached.py:320-325`; `packages/vmn-exp/tests/test_exp_rerun_cli.py:50-72`; `packages/vmn-exp/tests/test_sweep_summary.py:96-118`; `docs/vmn-exp/sweeps.md:98-123`; `docs/vmn-exp/sdk.md:66-69`

<a id="a6"></a>
### A6. UI: an app with no outer runs opens on the runs board with metric columns

P2 · S · depends on A5

**Problem.** The experiments page defaults to the Jobs view (experimentsView.ts:41). When facets answer with no outer runs, `useJobsKind` returns `kind: null` with `top: true` and the page renders `JobsView`, the job-shaped table (jobsKind.ts:22-29; ExperimentsPage.tsx:79-82). `SinglesView`'s own header says why that is the wrong table for single runs: it uses the All runs board's columns because 'a single run has no progress, best or spread to show' (SinglesView.tsx:1-4). After A5 a new user's app is exactly this case.

**Approach.**

1. `useJobsKind` (jobsKind.ts:17-30) returns one more field, `singlesOnly`: true when the facets answered (`facets.data` defined) with `jobs === 0` and `singles > 0`. Facets without the two counts (an older server; most test fixtures, such as `FACETS` at JobsKind.test.tsx:32) are not singles-only and keep today's view. In that state `top` is `"singles"` instead of `true`. `kind` stays null, so the switch still reads `Runs | All runs` (ExperimentsPage.tsx:32-34) and the presets stay hidden (71-76).
2. `AppExperiments` (ExperimentsPage.tsx:46-83) renders `SinglesView` when `kind.singlesOnly`, under the same switch with `Runs` pressed. With `jobs = 0` every top-level run is a single run, so `top=singles` lists the same rows the Jobs table listed with `top=true`, on the runs board's columns (SinglesView.tsx:37-39).
3. `useViewPrefetch` (useViewPrefetch.ts:25-35, 39-47): for the singles-only state the shown view is `"singles"` and `viewFilters` returns the `singles` and `all` filters, so the page no longer prefetches a `top: true` page nothing shows.
4. Unchanged: an app with outer runs; facets that fail or have not answered (the Jobs view with `top: true`, JobsKind.test.tsx:104-110); an app whose facets answer with no runs at all (`jobs = 0`, `singles = 0`), which keeps the Jobs view and its empty state.
5. Test edit: rewrite 'an app without jobs reads Runs | All runs and lists its single runs' (JobsKind.test.tsx:94-102): the options and the pressed `Runs` stay, and the request assertion becomes `objectContaining({ top: "singles" })`.

**Tests first.**

- packages/vmn-exp/webui/src/pages/Experiments/__tests__/JobsKind.test.tsx: the rewrite in step 5
- same file: 'an app whose facets answer with no runs at all keeps the Jobs view' (`jobs: 0, singles: 0` -> `top: true`)
- same file: 'kind=jobs in the URL does not bring the Jobs table back for an app without outer runs'
- same file: 'facets without jobs and singles counts keep the Jobs view' (`FACETS` alone -> `top: true`)
- packages/vmn-exp/webui/src/pages/Experiments/__tests__/ExperimentsPage.test.tsx: 'an app without outer runs opens the runs board with a metric column' (facets with a goal metric key; the column header is in the document)
- same file: 'without facets the Jobs view still lists every top-level run' (existing behaviour at lines 51-58, pinned again by name)
- packages/vmn-exp/webui/src/pages/Experiments/__tests__/ViewPrefetch.test.tsx (new, unit on `viewFilters`): 'a singles-only app prefetches All runs and no top page'

**Files.** `packages/vmn-exp/webui/src/pages/Experiments/jobsKind.ts`, `packages/vmn-exp/webui/src/pages/Experiments/ExperimentsPage.tsx`, `packages/vmn-exp/webui/src/pages/Experiments/useViewPrefetch.ts`, `packages/vmn-exp/webui/src/pages/Experiments/__tests__/JobsKind.test.tsx`, `packages/vmn-exp/webui/src/pages/Experiments/__tests__/ExperimentsPage.test.tsx`, `packages/vmn-exp/webui/src/pages/Experiments/__tests__/ViewPrefetch.test.tsx`, `docs/vmn-exp/ui.md` (the paragraph on the experiments page's default view)

**Risk.** Users of apps with only single runs see a different table on the same URL, and Jobs-view sort and column prefs do not apply to it. The runs board's count reads 'N single runs' and its CLI hint `kind = "single"` (SinglesView.tsx:23, 49-50, 93); both are correct for this state. A metric column shows only for declared goal metrics; a run with no declared goal still reads '(no goal)' (util.ts:120-122), which this item does not change. The web bundle is build output (`make _build_ui`). Does nothing for wrapper + child pairs recorded before A5. Plan 43 F13's solo-store text is written against this default, not today's fallback. Web tests are not in CI until plan 43 F15 lands; run `npm test` locally. Release: 0.1.x patch with an `upgrading.md` row, per plan 43 F9.

**Owner decision (2026-11-11).** Change the default now: an app with no outer runs opens on the runs board with metric columns. `JobsKind.test.tsx:94-102` is rewritten.

**Evidence.** `packages/vmn-exp/webui/src/pages/Experiments/experimentsView.ts:39-49`; `packages/vmn-exp/webui/src/pages/Experiments/jobsKind.ts:1-30`; `packages/vmn-exp/webui/src/pages/Experiments/ExperimentsPage.tsx:32-39`; `packages/vmn-exp/webui/src/pages/Experiments/ExperimentsPage.tsx:46-83`; `packages/vmn-exp/webui/src/pages/Experiments/useViewPrefetch.ts:25-47`; `packages/vmn-exp/webui/src/pages/Experiments/SinglesView.tsx:1-4`; `packages/vmn-exp/webui/src/pages/Experiments/SinglesView.tsx:37-39`; `packages/vmn-exp/webui/src/pages/Experiments/SinglesView.tsx:89-93`; `packages/vmn-exp/webui/src/pages/Experiments/__tests__/JobsKind.test.tsx:32-37`; `packages/vmn-exp/webui/src/pages/Experiments/__tests__/JobsKind.test.tsx:80-110`; `packages/vmn-exp/webui/src/pages/Experiments/__tests__/ExperimentsPage.test.tsx:49-58`; `packages/vmn-exp/webui/src/util.ts:120-122`

<a id="a7"></a>
### A7. Quickstart: one page that installs the dashboard, logs a metric and says what the first run does to git

P1 · S

**Problem.** Both entry READMEs show `pip install vmn-exp` and then `vmn-exp ui` in the same block, with the `[ui]` extra only in a trailing comment (docs/vmn-exp/README.md:8-13, packages/vmn-exp/README.md:7-12); without the extra `vmn-exp ui` stops with an install hint (ui/cli.py:257-266). Neither shows what goes in train.py, so `vmn-exp list my_app --sort loss` has nothing called loss. Neither says the first run commits vmn's init files and tags `<app>_0.0.0`, or that the repo needs a commit and a git identity. The only runnable path is in packages/vmn-exp/examples/README.md, listed third under Guides (docs/vmn-exp/README.md:25).

**Approach.**

Rewrite the opening of docs/vmn-exp/README.md as a quickstart of about 25 lines and mirror the short form in packages/vmn-exp/README.md (the PyPI page):
1. `pip install "vmn-exp[ui]"`.
2. Prerequisite line: a git repo with one commit and a git identity (`git init && git commit --allow-empty -m init`).
3. A six-line train.py: `from vmn_exp.sdk import start_run`, `with start_run("my_app") as run:`, a loop with `run.log_metric("loss", ..., step=...)`.
4. `python train.py`. The SDK path keeps the quickstart independent of A1 and A5: it already never pushes and makes one run.
5. One sentence on the side effect: the first run commits vmn's init files and tags `my_app_0.0.0` locally; nothing is pushed.
6. `vmn-exp list my_app --sort loss`, then `vmn-exp ui` with its URL.
7. One line each for 'wrap a script you cannot edit: `vmn-exp run my_app -- <cmd>`', with the note that a first run through the CLI pushes the baseline when the repo has a remote, and 'no git checkout: see sdk.md'.

Move 'Runnable examples' to the first Guides bullet. The top-level README.md keeps its single install line and link, per the docs rule.

**Tests first.**

- packages/vmn-exp/tests/test_docs_quickstart.py (unit, reads the two markdown files): test_any_block_that_runs_vmn_exp_ui_installs_the_ui_extra
- same file: test_quickstart_names_the_local_baseline_commit_and_tag
- same file: test_quickstart_says_the_cli_first_run_pushes_when_there_is_a_remote
- same file: test_package_readme_quickstart_matches_the_docs_quickstart_commands
- same file (real git, app_layout, same harness as test_examples.py): test_the_quickstart_train_py_block_runs_and_records_loss (extracts the fenced python block and executes it)

**Files.** `docs/vmn-exp/README.md`, `packages/vmn-exp/README.md`, `packages/vmn-exp/tests/test_docs_quickstart.py`

**Risk.** Docs only. `packages/vmn-exp/src/vmn_exp/cli/docs` is a symlink to docs/vmn-exp, so the bundled copy follows. The executed-snippet test follows the existing pattern (test_examples.py runs every example as a subprocess), so the quickstart cannot rot silently. docs/vmn-exp/README.md's opening is also edited by plan 43 F1 (the canonical storage sentence at lines 5-6); F1 lands first and A7 keeps its sentence and test.

**Evidence.** `docs/vmn-exp/README.md:1-25`; `packages/vmn-exp/README.md:1-16`; `packages/vmn-exp/src/vmn_exp/ui/cli.py:257-266`; `packages/vmn-exp/examples/README.md:14-40`; `packages/vmn-exp/tests/test_examples.py:1-45`; `README.md:434-446`

<a id="a8"></a>
### A8. client-guide: first run before concepts, and a glossary for the jargon

P2 · S · depends on A7

**Problem.** client-guide.md is labelled 'start here' (docs/vmn-exp/README.md:22) and opens with 'The five ideas you need' (lines 24-41): verstr, code identity, derived status, automatic nesting via VMN_EXPERIMENT_ID, refs. After install comes storage layout, then 'Submit: an outer run with inner jobs' (lines 12-14); the SDK logging a metric is section 4. A reader meets verstr, outer/inner run, store, writer id and git-mode/git-free before seeing a metric recorded.

**Approach.**

Reorder, do not rewrite: (1) Install; (2) a new short unnumbered 'Your first run' section that links the A7 quickstart and shows the same train.py plus `vmn-exp show --latest`; (3) 'The five ideas', each tied to something the reader just saw (the id that was printed is a verstr, and so on); then the existing sections in their current order, with 'Choose where runs live' opening by saying the default needs no action. Idea 4 (nesting) is rewritten by A5; if A5 has not landed, leave its text alone. Add a 'Terms' table at the end: verstr, ref, outer/inner/single run, store, writer id, git mode vs git-free (snapshot) mode, tree_status; one line each with a link to the canonical section in experiments.md or sdk.md.

**Tests first.**

- packages/vmn-exp/tests/test_docs_client_guide.py (unit, reads the markdown): test_first_run_section_comes_before_the_five_ideas
- same file: test_every_glossary_term_links_to_an_existing_anchor
- same file: test_table_of_contents_matches_the_section_headings

**Files.** `docs/vmn-exp/client-guide.md`, `packages/vmn-exp/tests/test_docs_client_guide.py`

**Risk.** Docs only. Keep every existing numbered heading text so anchors such as `#3-submit-an-outer-run-with-inner-jobs` keep working; 'Your first run' is inserted unnumbered.

**Evidence.** `docs/vmn-exp/client-guide.md:1-21`; `docs/vmn-exp/client-guide.md:24-41`; `docs/vmn-exp/client-guide.md:45-66`; `docs/vmn-exp/client-guide.md:70-90`; `docs/vmn-exp/README.md:22-24`

<a id="a9"></a>
### A9. Notebook guide

P2 · S · depends on A3

**Problem.** There is no notebook guidance. In sdk.md notebooks appear only as two caveats in the `start_run` reference (sdk.md:108, 112-114). The behaviours a notebook user hits are real and undocumented as a set: re-running a cell with an open run raises RuntimeError (sdk/create.py:147-170); `capture_output` redirects fds 1/2 away from the kernel (sdk.md:108); every run snapshots the working tree, which includes the .ipynb, within the 50 MB / 200 MB caps (experiments.md:70-73); a restarted kernel leaves a run that will read `stuck`; and outside a git checkout `start_run()` fails (A3).

**Approach.**

New docs/vmn-exp/notebooks.md (sdk.md is already 1490 lines), linked from docs/vmn-exp/README.md Guides, client-guide section 4 and sdk.md:112-114; add its line to CLAUDE.md's docs layout list (approved). Contents, each with a two-to-four-line cell: one run across cells (`run = start_run("my_app")`, logging in later cells, `run.finish()` in the last) versus `with` in one cell; what the re-run error means and the two ways out (`run.finish()` or `nested=True`); leave `capture_output` off; the notebook file is part of the snapshot, so saving it with new outputs gives a new verstr (state it; prescribe nothing unverified); after a kernel restart, close the orphan with sdk.md 'Finishing a run from outside it'; reading runs back into a DataFrame; the notebook's directory must be inside a git checkout, with the A3 error text. The guide makes no Colab or no-git promise; A10 adds a 'Without a git checkout' section to it when it lands. No code change.

**Tests first.**

- packages/vmn-exp/tests/test_docs_notebook_cells.py (unit, reads markdown): test_notebook_guide_is_linked_from_the_docs_index_client_guide_and_sdk
- same file (real git, app_layout): test_the_guides_cells_run_in_order_in_one_interpreter_and_record_one_run (extracts the python blocks and execs them sequentially in a subprocess)
- same file: test_rerunning_the_start_cell_raises_the_documented_error_text

**Files.** `docs/vmn-exp/notebooks.md`, `docs/vmn-exp/README.md`, `docs/vmn-exp/client-guide.md`, `docs/vmn-exp/sdk.md`, `CLAUDE.md`, `packages/vmn-exp/tests/test_docs_notebook_cells.py`

**Risk.** Docs only. A new file in docs/vmn-exp is bundled through the `cli/docs` symlink; check whether any packaging test enumerates the bundled docs. Not verified: whether Jupyter's kernel process sets a cwd that is the notebook's directory in every front end; the guide should say 'the kernel's working directory'. Plan 43 F14's notebook row should point at this guide.

**Evidence.** `docs/vmn-exp/sdk.md:108`; `docs/vmn-exp/sdk.md:112-114`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:147-170`; `docs/vmn-exp/experiments.md:70-73`; `docs/vmn-exp/sdk.md:116-122`

<a id="a10"></a>
### A10. Code-less run in a non-git directory or notebook, by explicit opt-in

P3 · L · depends on A3 · the spike comes first

**Problem.** There is no way to just log metrics. `record_source` has two sources: an exported snapshot named by VMN_SNAPSHOT_METADATA, or a git checkout via gitmode (sdk/create.py:129-136); with only vmn-exp-sdk installed and no export the answer is GIT_MODE_MISSING (create.py:33-37). A Colab or scratch-directory user cannot record at all. The store can already hold runs with no code: MLflow imports are written with a synthetic verstr `0.0.0-mlflow.<id>` (importers/import_records.py:61-63) and readers describe a run without base_commit as 'no code snapshot' (core/provenance.py:22-38).

**Approach.**

A third `RecordSource`, chosen only on request, never as a fallback (plan 32: a run must not silently change what it means).

Step 0, the spike (its own commit, tests only plus a short note in this file): settle the code verstr that code-less runs share. It must parse everywhere a run verstr is parsed, take the `.rN` suffix (`run_hint.run_name` / `run_number`, core/run_hint.py:24-36) and the `<code_verstr>.<writer id>` suffix (core/writer.py:323-352, 380-387), and be claimed with `create_exclusive` like any run (core/writer.py:355-367). Candidates: a fixed dev-grammar verstr, or `0.0.0-nocode` in the style of `0.0.0-mlflow.<id>`. The spike reads the dev grammar in `version_stamp/core/constants.py`, the UI index and `similar`, and answers whether `RECORD_FORMAT_VERSION` (core/record_format.py:17) must change for the `code: none` marker. Expected answer: no, it is one more metadata key. If it must change, stop and report: plan 43 F9 then asks for more than a patch release.

Then the build:
1. Opt-in: `start_run(..., code=False)` or `VMN_EXP_CODE=none`. Without it, behaviour is A3's error, whose text gains this option.
2. New `sdk/codeless.py` with `codeless_source(app_name, parent, nested, storage, capture_env, env)`: app name must be explicit (argument or VMN_APP_NAME); storage from `storage=` or `snapshot_mode_storage()` (create.py:173-184) with its existing error; a template with no base_commit/branch/remote and a `code: none` marker; lock `_shared_dir_lock`; parent via `pick_parent`.
3. `record_source` gets the branch: snapshot metadata, else code-less when asked, else the checkout. Works with vmn-exp-sdk alone. The module is imported inside the branch (plan 41 D1's import budget).
4. Readers: rerun/restore/goto/export/diff refuse with the existing 'no code snapshot' reason (a rerun already refuses an imported run, test_exp_rerun_cli.py:75-80); `vmn-exp show` marks `code = none`.
5. Docs: sdk.md 'Runs without a git checkout', a 'Without a git checkout' section in notebooks.md (A9), A3's error text, and a row in plan 43 F14's roadmap record.

**Tests first.**

- packages/vmn-exp/tests/test_codeless_verstr.py (unit): test_the_codeless_code_verstr_parses_as_a_run_verstr_and_takes_the_r_suffix; test_it_takes_a_writer_id_suffix (the spike's outcome, written first)
- packages/vmn-exp/tests/test_sdk_codeless_source.py (unit, in-memory storage fake, dict env): test_requires_an_explicit_app_name; test_requires_an_explicit_store; test_template_has_no_base_commit_and_marks_code_none; test_two_codeless_runs_get_distinct_verstrs; test_record_source_never_goes_codeless_without_the_opt_in; test_codeless_run_nests_under_vmn_experiment_id_like_any_run
- packages/vmn-exp/tests/test_sdk_checkout_guard.py: test_the_message_names_the_codeless_option (added to A3's file)
- packages/vmn-exp/tests/test_sdk_codeless_e2e.py (subprocess, empty tmp dir, no git, sdk only on sys.path): test_start_run_code_false_logs_metrics_readable_by_list_runs; test_rerun_and_diff_refuse_a_codeless_run_with_no_code_snapshot

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/codeless.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/checkout_guard.py`, `docs/vmn-exp/sdk.md`, `docs/vmn-exp/notebooks.md`

**Risk.** Product positioning: 'every run is a snapshot of your code' is the pitch (docs/vmn-exp/README.md:3-4); a code-less run weakens it, which is why it is opt-in, visibly marked and never a fallback. Technical risk sits in the verstr shape and in every reader that assumes a base commit; only provenance.py and the rerun guard were read. The verstr grammar, the UI index and `similar` were not read, so the verstr is undecided until the spike and the size depends on it: if no existing grammar fits, this grows to XL. `start_run` gains a `code` keyword; plan 41 D5 (positional arguments) lists it. Release: 0.1.x patch with a changelog entry; an `upgrading.md` row only if the spike changes a format, per plan 43 F9.

**Owner decision (2026-11-11).** Build it, as an explicit opt-in only (`code=False` / `VMN_EXP_CODE=none`), never as a fallback, after the verstr spike.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:32-37`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:129-136`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:173-184`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:226-251`; `packages/vmn-exp-sdk/src/vmn_exp/core/writer.py:323-367`; `packages/vmn-exp-sdk/src/vmn_exp/core/writer.py:380-387`; `packages/vmn-exp-sdk/src/vmn_exp/core/run_hint.py:24-36`; `packages/vmn-exp-sdk/src/vmn_exp/core/record_format.py:17`; `packages/vmn-exp/src/vmn_exp/importers/import_records.py:61-63`; `packages/vmn-exp-sdk/src/vmn_exp/core/provenance.py:22-38`; `packages/vmn-exp/tests/test_exp_rerun_cli.py:75-80`

## Dropped

<a id="a11"></a>
- **A11 (CLI cold start never pushes, even with a remote).** Dropped by the owner on 2026-11-11: the CLI keeps pushing on a cold start when a remote exists (plan 17 F6, pinned by test_exp_coldstart_detached.py:22-32), and A1 announces it. No test changes.

## Review findings corrected or dropped

- **Finding 2 (part): there is no warning 'in the top-level README quickstart'** The side effect is real, but the top-level README has no vmn-exp quickstart: it carries one install line and a link (README.md:434-446), and the repo's docs rule keeps experiment material out of core docs beyond that link. The warning belongs in docs/vmn-exp/README.md and packages/vmn-exp/README.md (A7) and in the CLI's own output (A1).
- **Finding 3 (part): the traceback goes checkout.py -> completion.py -> resolve_root_path 'even when VMN_APP_NAME is set'** By code reading, the crash is real in both cases but the path differs. With VMN_APP_NAME set, `_resolve_app_name` returns before calling its candidates (sdk/__init__.py:22-27), so the failure comes from the direct `resolve_root_path()` at gitmode/checkout.py:43. The completion.py path (`_complete_apps` -> `_find_vmn_root`, cli/completion.py:20-30) is taken only when no app name is given. A2 and A3 cover both. Not reproduced here.
- **Finding 5 (part): the quickstart 'installs without the [ui] extra but runs vmn-exp ui'** Accurate but softer than stated: the install line's trailing comment names the extra (docs/vmn-exp/README.md:9, packages/vmn-exp/README.md:8), and `vmn-exp ui` without it stops with an install hint, not a traceback (ui/cli.py:257-266). Still planned in A7, because a copy-pasted block should work as written.
- **Draft claim: A3 must land after A2 because start_run can only reach a clean error once core is fixed** The SDK already ships a logger-free resolver: `_base.resolve_root_path` (vmn_exp/_base.py:133-143) behind `try_repo_root` (core/storage_resolve.py:114-118), already used by start_run's state (sdk/run.py:307) and the reader (sdk/reader.py:86). Checking with it before entering git mode gives the clear error without touching core.
- **Draft claim: an atomic first-claim marker keeps fleets safe under adoption** It only makes the race safe, not the outcome right: among N sibling workers that inherit the token, whichever calls start_run() first becomes the outer run and the fleet loses a member. The token is inherited by the whole process tree (cli/run.py:318-327 builds the env from os.environ). A5 now uses a direct-child rule instead.

## Non-goals

- Re-planning the two review fixes that landed before this plan (859da19b: ui/jobs.py metric names; 59becdd5: storage/buffered.py keeps the buffer after a failed final ship).
- Stopping the CLI cold-start push when a remote exists (A11, dropped).
- Migrating or merging wrapper + single-child run pairs recorded before A5; the store is append-only and old runs keep their shape.
- A UI heuristic that collapses an outer run with one child into one row. A5 fixes the cause at write time; a display heuristic would make a row's metrics silently come from another run, against plan 32.
- Adoption for processes that are not the supervisor's direct child (workers spawned by a launcher, torchrun ranks, wrappers that spawn rather than exec). They keep today's nesting; the docs show putting `vmn-exp run` innermost.
- Changing how fleets, create_run/create_runs, nested=True, parent= or start_run(run_id=) nest.
- Making the supervisor and the SDK share run state or a stream. The supervisor stays the only writer of run_state.yml, the final run entry and alerts for an adopted run, and each of the two processes appends to its own stream.
- Changing how a record copy ships its streams. A sync still uploads every stream the copy owns, whichever of its processes runs it.
- Exporting the supervisor's storage flags to the child so a `--store` run can be adopted; A5 declines with a warning instead. Worth its own item if it turns out to be common.
- Removing the cold-start commits and tag, or making git-mode runs work without a baseline tag. That is a core vmn versioning question.
- Moving resolve_root_path's cwd/env reads, or the rest of core vmn's direct IO, behind interfaces beyond the one pure function A2 extracts; plan 35 owns that.
- Making the code-less run an automatic fallback when no checkout is found.
- Adding vmn-exp material to the top-level README beyond its existing install line and link.
- A hint in the UI to declare a goal metric when a board reads '(no goal)'.
- A notebook-specific API (magics, widgets, auto-finish on kernel shutdown).

## What the critic changed in the draft

- A1: the draft made 'never push' the fix and put the pinned test (test_exp_coldstart_detached.py:31, plan 17 F6) behind a decision, which blocked the crash fix too. A1 now fixes the no-remote crash and announces the push without changing any test. The critic also added the CI risk the draft missed: local-only cold starts in fresh CI clones record runs on commits and tags that exist nowhere else.
- A1: the draft's fixed notice text ('2 local commits') is wrong when only the app is new (stamping/init.py:118-134); the notice is now a pure function of repo_missing/app_missing. Added that the CLI path without a remote is unverified beyond the push call.
- A2 kept. Added the existing tests it must keep green: test_exp_base.py:47-53 (SDK copy stays in step with core) and tests/test_skill.py:150-159 (message text).
- A3 redesigned and decoupled from A2. The draft put a new module in gitmode and called version_stamp's ensure_logger in two places; the SDK already has a logger-free resolver, so one pure guard in the SDK called from record_source and resume.locate is smaller and independent. Added a test that snapshot-metadata mode is unaffected and the question of which error wins on an sdk-only install.
- A4: renamed the extracted function (a `child_env` already exists at core/rerun.py:159). The token now carries the supervisor pid.
- A5 adoption rule changed from 'first claimer wins' to 'supervisor's direct child only'. The draft rejected the pid rule for missing uv/torchrun wrappers, but its own rule lets one fleet worker become the outer run by race, which the finding said not to break. The conservative rule degrades to today's behaviour, never to a wrong merge. The claim marker and its storage API question are gone.
- A5 guest scope corrected. The draft said run.py 'only gains the constructor parameter' and a null state publisher suffices. Reading run.py:495-593 and cli/run.py:420-457 shows a guest must also skip the `run` log entry, finish alerts and the SIGTERM release/fail state. Proposed a small GuestRun subclass and tests for each.
- A5: added the store-mismatch case. The supervisor exports no storage to the child (cli/run.py:319-326), so a `vmn-exp run --store ...` child may resolve a different store; adoption must decline with a warning and nest as today, with a unit test.
- New A12: adoption for rerun and sweep trials. The draft's A5 silently broke test_exp_rerun_cli.py:50-72, which asserts wrapper + inner for a rerun of an SDK script, and promised 'metric_source is empty', which contradicts test_sweep_summary.py:112-118 (it is the trial's own verstr).
- A6: the draft missed that JobsKind.test.tsx:94-102 pins the exact case it changes (jobs: 0 -> Jobs page with top: true). The facets-error path stays unchanged (JobsKind.test.tsx:104-110).
- A7: added the git prerequisite line (one commit, identity) the draft left implicit, and noted that cli/docs is a symlink to docs/vmn-exp so bundled docs follow.
- A9: moved the guide to its own docs/vmn-exp/notebooks.md (sdk.md is 1490 lines) and added the CLAUDE.md docs-layout line; dropped two evidence lines I did not open.
- A10: lowered to P3 and put a verstr spike first; the draft specified a build whose central design point (the verstr) it had not read. Evidence trimmed to lines I opened.
- Checked and kept: the draft's partial refutations of findings 2, 3 and 5; the non-goal of a display-side collapse heuristic; the suggested order, with A7 moved earlier since it depends on nothing.
