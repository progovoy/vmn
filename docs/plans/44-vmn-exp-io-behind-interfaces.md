# Plan 44: vmn-exp review fixes, IO behind interfaces and oversized modules in vmn-exp

> Workstream G of the 2026-11-11 vmn-exp product review. The index, the
> milestone order, the cross-stream conflicts and the owner decisions are in
> [37-vmn-exp-review-fixes.md](37-vmn-exp-review-fixes.md). Each item was drafted by a
> planner that read the code, then revised by a critic that re-checked the
> evidence and looked for tests pinning today's behaviour.
>
> Sizes: S under a day, M 1-3 days, L about a week, XL more. Priorities: P0 security or data loss, P1 blocks adoption or misleads users, P2 quality, P3 nice to have.

Status: **proposed** (2026-11-11). Owner decisions of 2026-11-11 are applied in this file.

Solo impact: see each item's risk line; nothing here may make the single-user case worse.

## Summary

Every item was drafted against commit 25f03f3d and re-checked against master at 59becdd5 (26 commits later). All three findings are real and current. This file is the vmn-exp counterpart of plan 35 (core IO), which is still only proposed.

WHAT THE OWNER DECIDED (2026-11-11), as applied below:
- G2: the ports are small Protocols duplicated in `vmn_exp/core/ports.py` and `version_stamp/core/ports.py`, kept in step by a parity test, with the fakes shared in `tests/fakes/`.
- G7, G10: handlers take `io` explicitly. The `cli/plugin.py` shims build the real io per invocation until plan 35 provides `vmn_ctx.io`. `start_run` and the public `vmn_exp.sdk` functions are entry points that build real IO. The CLAUDE.md lines to add are listed once, under [CLAUDE.md lines](#claudemd-lines).
- G14: `SnapshotStorage` is the filesystem interface for store data. The local storage implementation modules are exempt from the IO ratchet, with a reason each.
- G11 Part B (the status clock and the clock aliases) is in this plan, as a staged mechanical migration.
- G17 (the `core/index.py` split) is in this plan, sequenced after G11 Part B.
- Test edits: every test edit named in this file is approved up front. Edits not named here still stop and ask. Every new behaviour still starts with a failing unit test on fakes.
- Releases stay 0.1.x patch releases. Nothing in this plan changes CLI output, the HTTP API or the store layout. One documented call changes: docs/vmn-exp/experiments.md:267 names `vmn_exp.core.status.derive_status(state, observed_at=...)`, and G11 Part B makes its `now` argument required. That commit updates the doc line and adds an `upgrading.md` row, per the removal rule in plan 43 F9. Any other item that turns out to change behaviour does the same.

WHAT UPSTREAM CHANGED SINCE THE DRAFT (`git diff --stat 25f03f3d..HEAD -- packages/*/src`: 39 files, +919/-306). None of it did this plan's work, so no item is dropped. What moved:
- `ui/server.py` grew from 834 to 839 lines; `create_app` is now lines 115-838 with 63 nested defs, 14 inline routes, 2 middlewares and 21 `routes_*.register` calls. Every server.py line number below is re-read at HEAD.
- `ui/registry_snapshot.py` (Models page snapshot: 8951f280, c796563f, 2d3374a4) now holds two classes built inside `create_app` (`RegistryListings`, `RegistrySnapshots`, server.py:791-792 and 809) with five new direct `time.monotonic()` calls (registry_snapshot.py:181, 193, 200, 228, 231) and one inline thread start (184). G19 gains a step for them.
- `ui/thread_limiters.py` is new (cddf6651); it has no clock, env or process IO. The source tree is now 582 files (281 + 301).
- `ui/jobs.py` (859da19b) and `storage/buffered.py` (59becdd5) carry the two review fixes; G5's and G10's line numbers are re-read. `storage/open.py` and `core/storage_resolve.py` changed for absolute artifact downloads; the `buffer_logs` lines G10 cites are open.py:17, 49 and storage_resolve.py:110.
- `core/index.py`, `core/status.py`, `sdk/run.py`, `cli/run.py` and `cli/experiment.py` did not change.

HOW THE COUNTS WERE MADE: an AST scan (ast.walk over Call nodes, dotted names, plus default-argument values) over the two `src/vmn_exp` roots at the draft commit; `packages/vmn-exp/build/lib` was excluded. G1's scanner reproduces it. Numbers are calls/files; "Path fs" is a method-name heuristic (upper bound).
- ui (208 files at the draft): time 47/18 (52/19 at HEAD with registry_snapshot.py); real-IO default args 16/14 (same at HEAD); env 9/7; pid/kill 5/4; os fs 53/21; Path fs <=21/14; open 14/8; shutil/tempfile 4/3; subprocess 3/3; uuid/secrets/urandom 17/12; net 5/2; thread starts 18/15 (19/16 at HEAD); print 8/4.
- cli (56 files): time 15/7; defaults 1; env 14/6; pid 3/3; os fs 45/10; open 12/8; shutil/tempfile 7/4; subprocess 1; net 3/2; print 144/30; input 1.
- gitmode/importers/snapshot (16 files): os fs 5; Path fs <=23; subprocess 1; print 8.
- vmn-exp-sdk (301 files): time 49/21; defaults 8/7; env 51/26; pid/kill 37/17; os fs 180/43; Path fs <=61/34; open 34/26; shutil/tempfile 21/15; subprocess 5/5; uuid/secrets/random 10/10; net 5/4; sqlite 3/3; thread starts 11/11; print 22/3.
- The call scan misses: 10 module-level clock aliases (8 in core: index.py:123, index_bulk.py:24, index_store_conn.py:36, index_sweep.py:93, index_freshness.py:29, index_relist.py:51, index_store.py:41, similar_match.py:33; sdk/sysmetrics.py:79; cli/similar_hint.py:59), 2 `from time import monotonic` modules (core/activity.py:13, core/traced_lock.py:19), about 12 `Event/Condition.wait(timeout)` sleeps and 2 asyncio.sleep. The ratchet scanner (G1) must resolve import aliases.
- 205 of the files have non-print direct IO. 41 files exceed 300 lines at HEAD (39 at the draft).
- Sizes at HEAD: ui/server.py 839 (create_app 115-838); cli/experiment.py 1227; core/index.py 1217 (ExperimentIndex 133-1071); sdk/run.py 889.

WHERE THE VALUE IS (grep over the 1017 test_*.py files in packages/vmn-exp/tests at HEAD; 1004 at the draft): 198 use the Docker app_layout fixture, 555 already use tmp_path, 124 call real time.sleep (210 calls), 93 spawn real subprocesses, 119 build the whole create_app, and 74 files patch `status._now` (89 sites). So the order is: ratchet, ports + fakes, fast lane, composition roots, clock/sleep, processes, env, then random/console/filesystem, with the index split after the clock migration.

WHAT CONSTRAINS THE MIGRATION (AST count of call sites in the tests at HEAD): the classes that would gain parameters are constructed directly by many tests: create_app 172 sites/119 files, WorkspaceManager 150/125, ExperimentIndex 255/111, LeaderboardCache 292/96, open_storage 175/127, SqliteStore 133/38, Run 29/19, Refresher 28/21, BufferedRemoteStorage 9/8, TokenService 13/5, AuditLog 11/3, JobRunner 7/3. And tests patch module globals of the files to be split (core/index: `_monotonic` x11, `_SHARED` x9, `_REMOTE_CHUNK` x8, `indexed_snapshot` x6, `shared_index` x6, `RETRY_UNREADABLE_SEC` x6, `refresh_record` x6, `FIRST_ROWS` x5, `direct_rows` x3, `update_record` x2, `FIRST_ROWS_MAX`, `kept_parts`, `first_rows` x1 each; sdk/run: `compact_by`, `sync_to_remote`, `FINAL_REMOTE_TIMEOUT_SEC`, `error_from_exception`, `_finalize_signaled`; cli/experiment: `_resolve_experiment_version`, `_resolve_experiment_bundles`, `load_run_state`; ui/server: `workspace_storage`). A moved function reads its new module's globals, so a re-export does not keep such a patch working. Every refactor item below names the patches it must keep honouring.

TEST-EDIT POLICY (decided, see G4): classes built in a handful of test files get a mechanical, constructor-arguments-only commit; widely built names keep their name and signature as the real-wired form and gain the injected form beside it. The approved clock migration (G11 Part B) is the one large test-touching change.

SHARING WITH PLAN 35: vmn-exp-sdk may not import version_stamp (test_packaging_split.py:84-97) and plan 35's ports do not exist yet. The Protocols are duplicated under the same names and shapes (G2), kept in step with a parity test (precedent: _base.py + test_exp_base.py), and the fakes are shared physically in tests/fakes/.

EFFECTS OF OTHER PLANS THIS FILE ALREADY ASSUMES:
- Plan 41 D3 moves `reports/`, `registry/cli*` and `core/push_*` out of the SDK wheel before G11, G13 and G16 touch them. This file cites the post-move paths: `packages/vmn-exp/src/vmn_exp/reports/`, `packages/vmn-exp/src/vmn_exp/cli/model_cmd.py` and `packages/vmn-exp/src/vmn_exp/cli/pushing/`.
- Plan 42 E1 adds `ui/job_argv.py` (validators and the argv builder leave `ui/jobs.py`) before G5.
- Plan 40 lands its buffered-store chain (C3, C13, C5, C6) and its two new items C15 (the `vmn-exp run` supervisor's final sync) and C16 (the UI server's store actions) before G8 and G10 touch `cli/run.py`, `cli/supervisor.py`, `storage/buffered.py` and the edit-storage open at ui/server.py:614.
- Plan 38 A4 (`cli/supervised_env.py`) and plan 39 B9b (`cli/supervise_loop.py`) land before G8, which injects io into their code.
- Both packages require Python >=3.10 (plan 43 F12), so ports and fakes may use `X | None` annotations and `match` freely; nothing here needs 3.8/3.9 compatibility.

## Items

| Id | Pri | Size | Item | Owner decision |
|---|---|---|---|---|
| [G1](#g1) | P1 | S | Ratchet: no new direct IO in vmn-exp (AST scan + shrinking allowlist) and the plan index row |  |
| [G18](#g18) | P2 | S | Size ratchet: no source file grows past its recorded size |  |
| [G2](#g2) | P2 | S | Ports, real implementations and shared fakes for vmn-exp | decided |
| [G3](#g3) | P2 | S | A no-Docker, no-sleep unit pass for the exp suite, run first in CI |  |
| [G4](#g4) | P2 | M | UI composition root: build_app(manager, deps) with create_app as the real-wired factory | decided |
| [G19](#g19) | P2 | L | Remove the remaining UI real-clock defaults, by construction site |  |
| [G5](#g5) | P2 | M | JobRunner and the three UI subprocess sites take injected processes, ids and a thread starter |  |
| [G6](#g6) | P2 | L | Split the 724-line create_app closure into a ServerContext and route modules |  |
| [G7](#g7) | P2 | S | CLI composition root: vmn-exp handlers receive io | decided |
| [G8](#g8) | P2 | M | cli/run.py supervision on injected clock, processes, env and host |  |
| [G9](#g9) | P3 | M | Split sdk/run.py (889 lines) along its mixin seams without breaking module-global patches |  |
| [G10](#g10) | P2 | L | SDK composition root: start_run builds real IO; Run and sysmetrics take clock and host; buffered store takes a clock | decided |
| [G11](#g11) | P2 | XL | Clock into status derivation and the clock aliases (Part A: sdk defaults; Part B: status and aliases, 119 test patch sites) | decided |
| [G12](#g12) | P2 | L | Environment variables read through an injected Env, staged ui -> cli -> sdk |  |
| [G13](#g13) | P3 | M | Ids and tokens from an injected Random |  |
| [G14](#g14) | P3 | XL | Filesystem: declare the real Storage implementations, then move logic-side file access behind the FileSystem port | decided |
| [G15](#g15) | P3 | M | Split cli/experiment.py (1227 lines) by command |  |
| [G16](#g16) | P3 | L | CLI output through a Console port |  |
| [G17](#g17) | P2 | L | Split core/index.py (1217 lines) into mixin modules behind the ExperimentIndex facade | decided |

Order inside the stream: G1 -> G2 -> G3; G18 at the start of the structural milestone; UI lane G4 -> G19 -> G5 -> G6 -> G13; CLI lane G7 -> G8, G15 -> G16; SDK lane G9 -> G10 -> G11 Part A -> G11 Part B -> G17 -> G12 stage C. G11 Part B needs G4, G7 and G10 (every root must be able to hand out a clock). G17 needs G11 Part B (the split relies on the index holding a clock instead of the `_monotonic` alias) and G18.

<a id="g1"></a>
### G1. Ratchet: no new direct IO in vmn-exp (AST scan + shrinking allowlist) and the plan index row

P1 · S

**Problem.** Nothing stops new direct IO. 205 of the 582 vmn-exp source files call time/env/fs/subprocess/uuid/net directly, 25 parameters default to a real implementation (CLAUDE.md forbids that in new code) and 10 modules keep a patchable clock alias. The two existing boundary tests scan imports only.

**Approach.**

Add packages/vmn-exp/tests/io_scan.py: a pure function `scan(source) -> Counter[kind]` with kinds time, real_default, clock_alias, env, process_self, fs, subprocess, random, net, sqlite, thread, console. It resolves `import x as y` and `from time import monotonic` before matching (the draft's scan missed two modules that way) and does not count seeded `random.Random(seed)`. packages/vmn-exp/tests/test_io_boundary.py scans only the two src/ roots (not packages/vmn-exp/build/lib, which exists on disk) against packages/vmn-exp/tests/io_boundary_known.py (module -> {kind: count}, generated with `--regen` like architecture_known_violations.py). It fails when a count exceeds its entry, when an unlisted module has any, or when an entry is higher than reality (so the list only shrinks). A short REAL_IO dict (module -> one-line reason) names the real implementations that are never expected to reach zero. A REAL_IO module keeps its counted entry in io_boundary_known.py like every other module, so real IO cannot grow inside it unnoticed; the dict only records why the entry stays. It starts empty and is filled by G2 (real_io.py), G14 (the local storage modules) and the process roots named in G10, G11 and G19. A second short dict, REAL_WIRED (name -> defining module and reason), lists the widely built names that keep a real-wired form (G4, list 2); it starts empty and each entry is added by the item that introduces it. Outside the entry points named in CLAUDE.md, only the modules in REAL_IO and REAL_WIRED may call `real_io()`; test_only_entry_points_and_listed_modules_call_real_io pins that from G2 on. Path-method calls (`p.exists()`) cannot be typed statically, so the fs kind counts os/open/shutil/tempfile calls only and the docstring says so. The scan is seeded from HEAD, so the direct calls upstream added since the draft (five `time.monotonic()` in ui/registry_snapshot.py) are recorded as they are. Same commit adds this plan's row to docs/plans/README.md (the README has no row for plans 37-44 at HEAD), unless plan 43 F8 has added it already. No production change.

**Tests first.**

- packages/vmn-exp/tests/test_io_scan.py: test_counts_time_env_fs_subprocess_calls_by_kind (source strings in, counters out)
- test_io_scan.py: test_real_default_argument_is_counted (def f(clock=time.time))
- test_io_scan.py: test_module_level_clock_alias_is_counted (_now = time.time)
- test_io_scan.py: test_from_import_and_import_as_are_resolved (from time import monotonic; import time as t)
- test_io_scan.py: test_seeded_random_and_injected_calls_are_not_counted (random.Random(seed), self._clock())
- packages/vmn-exp/tests/test_io_boundary.py: test_no_module_exceeds_its_known_io, test_known_io_has_no_stale_entries, test_real_io_entries_name_existing_modules_and_carry_a_reason, test_real_wired_entries_name_existing_names_and_carry_a_reason

**Files.** `packages/vmn-exp/tests/io_scan.py`, `packages/vmn-exp/tests/test_io_scan.py`, `packages/vmn-exp/tests/test_io_boundary.py`, `packages/vmn-exp/tests/io_boundary_known.py`, `docs/plans/README.md`

**Risk.** None at runtime (tests only). Friction: any change that removes a direct call must lower the allowlist in the same commit; the failure message prints the regen command. Plans 38-43 land items after G1 that add or remove direct calls (plan 37, conflict 13); each must lower or extend io_boundary_known.py in its own commit. `Event.wait(timeout)` and asyncio.sleep are not detectable by name and stay outside the ratchet (stated in the docstring) rather than pretending to cover them.

**Evidence.** `packages/vmn-exp/tests/test_packaging_split.py:39-58 (import-only AST scan, the style to copy)`; `packages/vmn-exp/tests/test_architecture_boundary.py:1-5 (existing --regen known-violations ratchet)`; `packages/vmn-exp/src/vmn_exp/ui/refresher.py:132 (clock=time.monotonic default)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index.py:123 (_monotonic = time.monotonic alias)`; `packages/vmn-exp-sdk/src/vmn_exp/core/activity.py:13 and core/traced_lock.py:19 (from time import monotonic: invisible to a dotted-name scan)`; `docs/plans/35-core-io-behind-interfaces.md:67-72 (core ratchet design)`

<a id="g18"></a>
### G18. Size ratchet: no source file grows past its recorded size

P2 · S

**Problem.** 41 of the 582 vmn-exp source files exceed the 300-line guideline and nothing stops them growing. The draft enforced size with one-off `files_stay_under_N_lines` tests per refactor item, used as an artificial red test for pure moves; that is three bespoke tests for one rule.

**Approach.**

One test in packages/vmn-exp/tests/test_file_size_ratchet.py with a KNOWN_OVERSIZED dict (module -> current line count) beside it: a file over 300 lines must be listed and may not exceed its recorded count; a listed file that shrank must have its entry lowered or removed. G6, G9, G15 and G17 lower entries as they land. It lands at the start of the structural milestone, after the feature work of plans 38-42 has stopped adding lines to the listed files (plan 37, conflict 13). This replaces the per-item line-count tests in the draft. Pure moves need no invented red test (CLAUDE.md: refactor keeps tests green); their safety net is a characterization test written first.

**Tests first.**

- packages/vmn-exp/tests/test_file_size_ratchet.py: test_no_file_exceeds_its_recorded_size
- test_file_size_ratchet.py: test_recorded_sizes_are_not_stale
- test_file_size_ratchet.py: test_limit_helper_counts_lines_of_a_given_text (pure helper, strings in)

**Files.** `packages/vmn-exp/tests/test_file_size_ratchet.py`, `packages/vmn-exp/tests/file_size_known.py`

**Risk.** Adds a second allowlist to maintain. A one-line addition to a listed file fails the test, which is the point; the message names the file and its cap.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/experiment.py (1227 lines)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index.py (1217 lines)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py (889 lines)`; `packages/vmn-exp/src/vmn_exp/ui/server.py (839 lines; create_app 115-838)`; `CLAUDE.md 'Splitting tasks' (~200-300 lines max per file)`

<a id="g2"></a>
### G2. Ports, real implementations and shared fakes for vmn-exp

P2 · S · depends on G1

**Problem.** vmn-exp has no shared definition of an injected clock/env/process runner. About 80 files already take ad hoc parameters (clock, sleep, env, post_json, say) and tests define 38 one-off Fake*/Stub* classes. The SDK cannot import `version_stamp.core.ports` (import rule), and that module does not exist yet (plan 35 is proposed). The existing `clock=` parameters are bare callables on three different time bases (time.time, time.monotonic, time.perf_counter).

**Approach.**

Duplicate the small Protocols in both packages under the same names and shapes.

`packages/vmn-exp-sdk/src/vmn_exp/core/ports.py` (stdlib only) defines `Clock` (`now()` -> aware UTC datetime, `monotonic()` -> float, `sleep(sec)`), `Env` (read-only Mapping), `Processes` (`run(cmd, ...)`, `popen(cmd, ...)`), `Random` (`hex_id()`, `token_hex(n)`, `token_urlsafe(n)`, `token_bytes(n)`), `Host` (`pid()`, `hostname()`), `Console` (`out`, `err`, `read_line`) and an `IO` dataclass bundling them. `packages/vmn/src/version_stamp/core/ports.py` is the same text for the ports both sides share (`Clock`, `Env`, `Processes`, `Random`, `Console`); it is created by whichever of plan 35 stage 0 or this item lands first. If this item lands first it adds that one file to core vmn and nothing else there; plan 35 then builds on it. `Host` and `Processes.popen` are vmn-exp additions; the parity test compares only the names and method signatures present on both sides, and lists the vmn-exp-only ones explicitly so a new difference fails.

Existing classes keep their callable-shaped `clock` parameters: roots pass `io.clock.monotonic` or `lambda: io.clock.now().timestamp()`, so classes and the tests that already hand them a fake callable do not change shape.

`vmn_exp/core/real_io.py` holds thin stdlib classes and `real_io()`; it is the first entry in G1's REAL_IO. No FileSystem port here (G14).

Fakes go in `tests/fakes/` (repo root) as plain classes importing neither package: `FakeClock` (its `sleep` advances `monotonic` and `now` together), `FakeEnv`, `FakeProcesses` (scripted results), `FakeRandom`, `FakeHost`, `FakeConsole`. Both suites already have `tests/` on `sys.path`. Each fake has a contract test run against the real class.

**Tests first.**

- packages/vmn-exp/tests/unit/test_ports_contract.py: test_clock_contract[fake|real] (monotonic never goes back; now() is timezone-aware UTC; sleep(0) returns)
- test_ports_contract.py: test_fake_clock_sleep_advances_monotonic_and_now_together
- test_ports_contract.py: test_processes_contract[fake|real] (returncode, stdout, timeout raises subprocess.TimeoutExpired, missing binary raises FileNotFoundError)
- test_ports_contract.py: test_random_contract[fake|real] (hex_id is 32 hex chars; token lengths)
- test_ports_contract.py: test_real_random_is_backed_by_secrets
- test_ports_contract.py: test_host_contract[fake|real]
- packages/vmn-exp/tests/test_ports_parity.py: test_shared_ports_have_the_same_methods_and_signatures_in_both_packages (red until both files exist; compares `inspect.signature` per method)
- test_ports_parity.py: test_vmn_exp_only_ports_are_exactly_the_listed_ones (`Host`, `Processes.popen`)
- packages/vmn-exp/tests/test_exp_import_boundary.py: existing test_sdk_import_skips_heavy_deps must stay green (ports.py and real_io.py import only the stdlib)

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/core/ports.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/real_io.py`, `packages/vmn/src/version_stamp/core/ports.py`, `tests/fakes/__init__.py`, `tests/fakes/clock.py`, `tests/fakes/env.py`, `tests/fakes/processes.py`, `tests/fakes/random.py`, `tests/fakes/host.py`, `tests/fakes/console.py`, `packages/vmn-exp/tests/unit/test_ports_contract.py`, `packages/vmn-exp/tests/test_ports_parity.py`

**Risk.** Two copies of the Protocols can drift; the parity test contains it. Plan 35's text does not state the return type of `Clock.now()` (35:28-33); this item pins it as an aware UTC datetime because status derivation needs one (core/status.py:88-89). If plan 35 wants another shape, both files change in one commit and the parity test says so. Plan 35 writes `Processes.run(cmd, ...) -> CompletedProcess | None` (35:31) without saying when `None` is returned; this item's contract test has a missing binary raise `FileNotFoundError`, as `subprocess.run` does. That cannot be settled by reading plan 35 and must be agreed with it before either `ports.py` is written. `tests/fakes/` is collected by neither suite as tests (no test_ prefix) and must not import version_stamp or vmn_exp. Adding `version_stamp/core/ports.py` from a vmn-exp plan is a core change of one file with no caller; it must not import anything from vmn_exp (the core suite makes vmn_exp unimportable).

**Owner decision (2026-11-11).** The ports are duplicated small Protocols in `vmn_exp/core/ports.py` and `version_stamp/core/ports.py`, with a parity test and shared fakes in `tests/fakes/`.

**Evidence.** `packages/vmn-exp/tests/test_packaging_split.py:84-97 (sdk subpackages may not import version_stamp)`; `packages/vmn-exp-sdk/src/vmn_exp/_base.py:114-116,133-152 (helpers copied from vmn)`; `packages/vmn-exp/tests/test_exp_base.py:17-70 (the keep-in-step tests)`; `docs/plans/35-core-io-behind-interfaces.md:28-33 (port names and methods; `now()` return type not stated)`; `packages/vmn/src/version_stamp/core/ports.py and tests/fakes/ do not exist at HEAD`; `packages/vmn-exp/src/vmn_exp/ui/audit.py:31 (clock=time.time), ui/refresher.py:132 (clock=time.monotonic), ui/diag/gc_pauses.py:28 (clock=time.perf_counter, wall=time.time)`; `packages/vmn-exp-sdk/src/vmn_exp/core/status.py:88-89 (_now returns an aware UTC datetime)`; `packages/vmn-exp/tests/conftest.py:8-12 (exp suite has tests/ on sys.path)`; `tests/conftest.py:12-14 (core suite blocks vmn_exp, so shared fakes may import neither package)`

<a id="g3"></a>
### G3. A no-Docker, no-sleep unit pass for the exp suite, run first in CI

P2 · S · depends on G2

**Problem.** There is no fast lane. The exp suite is one flat directory of 1017 test files run in a 29-worker pass that needs Docker, and nothing tells a contributor that a new fake-based test accidentally sleeps or spawns a process. Without it the migration's benefit cannot be measured or protected.

**Approach.**

New fake-based tests go in packages/vmn-exp/tests/unit/ (no __init__.py; test file basenames must be unique across the whole tests tree because pytest imports by basename). Its conftest.py has one autouse fixture that fails a test which requests app_layout or reaches real time.sleep / subprocess.Popen; this guard is the only place allowed to patch those globals. tests/run_pytest.sh gains `--suite exp-unit` (pytest on that directory, no Docker needed) and ci/pipeline.py gains a `tests_exp_unit` stage with its own declared inputs that tests_exp runs after. The directory is still collected by the full exp run. The stage's test count and wall time are the migration's progress metric.

**Tests first.**

- packages/vmn-exp/tests/unit/test_unit_guard.py: test_real_sleep_fails_a_unit_test (calls the guard function directly)
- test_unit_guard.py: test_real_popen_fails_a_unit_test
- test_unit_guard.py: test_requesting_app_layout_fails_a_unit_test
- packages/vmn-exp/tests/test_ci_pipeline_stages.py: test_exp_unit_stage_exists_and_tests_exp_runs_after_it (reads the stage list from ci/pipeline.py)

**Files.** `packages/vmn-exp/tests/unit/conftest.py`, `packages/vmn-exp/tests/unit/test_unit_guard.py`, `tests/run_pytest.sh`, `ci/pipeline.py`, `CLAUDE.md` (the Running Tests lines under [CLAUDE.md lines](#claudemd-lines))

**Risk.** The parent conftest's autouse fixtures (register_all, VMN_EXP_CACHE_DIR in a tmp dir, vmn_env_guard) still apply to unit/ and touch the filesystem; acceptable, they are milliseconds. Whether ci/pipeline.py is importable in a test without muster installed must be checked first; if not, the pipeline assertion parses the file's AST instead. Plan 43 F15 puts its pipeline-stage test in ci/test_pipeline.py (muster venv only) while this item uses packages/vmn-exp/tests/test_ci_pipeline_stages.py (plan 37, conflict 24); if F15 has landed, add this item's assertion to its file instead of creating a second home. ci/pipeline.py is also edited by F15 and plan 41 D15, so re-read the stage list first.

**Evidence.** `tests/run_pytest.sh:27-34,64 (suite is core or exp only)`; `tests/run_pytest.sh:129-142 (one parallel pass plus one serial pass)`; `ci/pipeline.py:134-152 (tests_exp runs the whole directory, with declared inputs/outputs)`; `tests/vmn_fixtures.py:318-344 (the app_layout fixture shells out to docker)`; `packages/vmn-exp/tests (no unit/ directory exists today)`; `docs/plans/35-core-io-behind-interfaces.md:108-111 (core stage 7: tests/unit + --suite unit)`

<a id="g4"></a>
### G4. UI composition root: build_app(manager, deps) with create_app as the real-wired factory

P2 · M · depends on G2, G3

**Problem.** create_app constructs JobRunner(), Refresher()/InlineRefresher(), StoreUpkeep(), AuditLog and TokenService itself, so no test can drive the server with a fake job runner or fake clock; 119 test files build the full app instead.

**Approach.**

Add ui/app_deps.py: a `ServerDeps` dataclass (io, jobs, refresher, upkeep, audit, token_service) and `real_deps(io, control_plane, background_refresh, read_only, keep_warm)` that builds exactly the objects create_app builds today. Rename create_app's body to `build_app(manager, deps, **options)`; `create_app(manager, **options)` stays, with the same signature, as a few lines calling `build_app(manager, real_deps(real_io(), ...), ...)`. CLAUDE.md already names the ui app factory as an entry point, so the 172 existing call sites do not change. Scope is deliberately only what create_app constructs; the clock defaults of classes built elsewhere are G19. `app.state.refresher`, `app.state.audit` and `app.state.store_upkeep` keep being set as today (tests read them). `RegistryListings` and `RegistrySnapshots` (added upstream, built at server.py:791-792 and 809 from `refresher.background`) and `LeaderboardCache` (server.py:209) stay built inside `build_app`; they receive their clock from `deps.io` in G19 and G11.

The test-edit policy this item sets for the whole plan:
1. A class built in a handful of test files gets its real default removed and its test constructions edited in one mechanical commit that changes constructor arguments only: JobRunner (7 sites, 3 files; G5), AuditLog (11, 3), TokenService (13, 5), SessionService (3, 2), OIDCAuthenticator (2, 2), ControlPlaneSweeper (2, 1), StoreUpkeep (5, 4), AppUpkeep (23, 7), SettingsCache (4, 2), WorkspaceCache (6, 5), WorkspaceJournal (10, 9), RegistrySnapshots and RegistryListings (4, 1) (all G19), OutputLog (6, 1) and ReportIndex (2, 2) (G11 Part A), Sampler (3, 3), BufferedRemoteStorage (9, 8) and Run (29, 19) (G10), `_Supervision` (3, 1; G8). Each owning item repeats its own counts. `GcPauses` is not in this list: it is a process-level singleton and goes on REAL_IO (G19).
2. A widely built name keeps its name and signature as the real-wired form, and the injected form is added beside it with no test edits: create_app (172 sites, 119 files), WorkspaceManager (150, 125), ExperimentIndex (255, 111), LeaderboardCache (292, 96), open_storage (175, 127), SqliteStore (133, 38), Refresher (28, 21), and the three process-wide index functions `shared_index`, `indexed_snapshot` and `indexed_status_rows` (G11 Part B). Each such name keeps one entry in G1's REAL_WIRED dict with the reason "real-wired form"; a ratchet test asserts that no production module calls it without passing its IO. `open_storage` is in this list only for its name and signature: its one new keyword (`clock`, G10) has no real default.

**Tests first.**

- packages/vmn-exp/tests/unit/test_ui_build_app.py: test_build_app_uses_the_given_job_runner (POST an action on a store workspace; a recording runner sees the submit)
- test_ui_build_app.py: test_build_app_uses_the_given_refresher (a stub refresher receives the snapshot call)
- test_ui_build_app.py: test_build_app_without_control_plane_has_no_audit_or_token_service
- test_ui_build_app.py: test_create_app_wires_a_background_refresher_only_when_asked (create_app(...).state.refresher type)
- test_ui_build_app.py: test_real_deps_builds_upkeep_only_for_background_writable_servers

**Files.** `packages/vmn-exp/src/vmn_exp/ui/app_deps.py`, `packages/vmn-exp/src/vmn_exp/ui/server.py`, `packages/vmn-exp/tests/unit/test_ui_build_app.py`

**Risk.** The unit tests need a WorkspaceManager; they use the real one on tmp_path (it is a local registry, no Docker) until G14. create_app's public signature and route table do not change; the 119 existing TestClient test files are the safety net and are not edited. Policy 2 keeps a real implementation reachable through an omitted argument for the names in list 2, which CLAUDE.md forbids in new code ("don't hide a real implementation in a default argument"). The plan uses it as the migration state (plan 37, invariant 5), enforced by the REAL_WIRED entry and the "production always passes it" test, and removes it name by name when their tests move to the injected form. The owner's decisions approve the test edits named in the plans; they do not say whether this deviation is accepted, so it is listed for the owner. The alternative is to edit every construction site (about 1,200 across list 2), which this file does not name and which would therefore stop and ask.

**Owner decision (2026-11-11).** Every test edit named in this plan is approved up front, so the classes in list 1 get their mechanical constructor-argument commits without a further question. The names in list 2 need no test edits; whether their real-wired form is an accepted exception to the CLAUDE.md default-argument rule was not part of the decision (see Risk).

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/server.py:169 (jobs = JobRunner())`; `packages/vmn-exp/src/vmn_exp/ui/server.py:171,176 (AuditLog(control_plane), TokenService(control_plane) built inline)`; `packages/vmn-exp/src/vmn_exp/ui/server.py:184 (Refresher(keep_warm=...) or InlineRefresher())`; `packages/vmn-exp/src/vmn_exp/ui/server.py:194 (StoreUpkeep())`; `packages/vmn-exp/src/vmn_exp/ui/server.py:209 (LeaderboardCache(conf_of=_board_conf))`; `packages/vmn-exp/src/vmn_exp/ui/server.py:791-792,809 (RegistryListings(), RegistrySnapshots(refresher.background, ...))`; `packages/vmn-exp/src/vmn_exp/ui/server.py:115 (create_app, called at 172 sites in 119 test files)`; `packages/vmn-exp/src/vmn_exp/ui/cli.py:176 (server_app: env=None falls back to os.environ)`

<a id="g19"></a>
### G19. Remove the remaining UI real-clock defaults, by construction site

P2 · L · depends on G4

**Problem.** 16 parameters in 14 ui files default to time.* (same at HEAD), and upstream added five direct `time.monotonic()` calls in ui/registry_snapshot.py. Only AuditLog, TokenService and Refresher among the defaulted classes are built in create_app. The others are built deep in the tree (SettingsCache, WorkspaceCache and WorkspaceJournal in ExperimentSource, AppUpkeep in StoreUpkeep, FailureStreak in the refresher, TokenService again per request in routes_admin, ControlPlaneSweeper in its `install`, a module-level GcPauses singleton), so each needs its clock threaded from its own caller. `StoreUpkeep` itself takes no clock and reads `time.monotonic()` directly.

**Approach.**

One small step per construction chain, each with its own unit test, in parallel worktrees where files are disjoint:
- (a) AuditLog and TokenService (server.py and routes_admin.py read `app.state.token_service` built in real_deps instead of constructing one per request), and `ControlPlaneSweeper` through `control_plane_sweep.install(app, store, retention_days, clock)`. Epoch seconds.
- (b) `OIDCAuthenticator` gets its clock from the auth builder in ui/cli.py (cli.py:166) and already hands it to the `SessionService` it builds (oidc.py:75) and, through `DeviceFlow`, to its TokenService (device.py:32); the defaults on OIDCAuthenticator and SessionService are removed. Epoch seconds.
- (c) Refresher -> FailureStreak. The refresher already passes its clock to the streaks it builds (refresher.py:227, 342, refresh_watch.py:22), so FailureStreak's default is simply removed. Refresher is a list-2 name (G4): `real_deps` passes its clock explicitly and the keyword's default stays as the real-wired form.
- (d) `ExperimentSource` (built once, server.py:196) takes a `Clock` and gives `clock.monotonic` to SettingsCache (experiment_source.py:108) and WorkspaceCache (227), and the epoch-seconds callable to WorkspaceJournal (90); the three defaults are removed.
- (e) `StoreUpkeep` (built at server.py:194 in `real_deps` after G4) gains a keyword-only `clock` (monotonic), reads it at store_upkeep.py:210 and 220, and passes it to the `AppUpkeep` it builds at 174; AppUpkeep's default is removed.
- (f) `RegistrySnapshots` and `RegistryListings` take a keyword `clock` (a monotonic callable) from `build_app`; the five direct calls read it. Their refresh thread start (registry_snapshot.py:184) stays; threads are not abstracted (non-goal).
- (g) live_events.event_stream gets clock and sleep from routes_events.register.

ui/diag/gc_pauses.py and ui/diag/latency.py measure the real process and are module-level singletons: they go on G1's REAL_IO list with that reason rather than being rewired.

Test edits (approved, constructor arguments only, one commit per class; a site that already passes a clock is left alone): AuditLog (11 sites in 3 files, 9 without a clock), TokenService (13 in 5, 11 without), SessionService (3 in 2, 2 without), OIDCAuthenticator (2 in 2), ControlPlaneSweeper (2 in 1, 1 without), StoreUpkeep (5 in 4), AppUpkeep (23 in 7, 21 without), SettingsCache (4 in 2, 2 without), WorkspaceCache (6 in 5, 5 without), WorkspaceJournal (10 in 9, 2 without), ExperimentSource (3 in 3), and the RegistrySnapshots/RegistryListings constructions in test_ui_registry_shared_listing.py (4 sites, the only test file that builds them). Each edit passes the real callable the default named (`time.time` or `time.monotonic`), so no test's timing changes.

**Tests first.**

- packages/vmn-exp/tests/unit/test_ui_clock_injection.py: test_audit_entry_timestamp_comes_from_the_clock
- test_ui_clock_injection.py: test_api_token_last_used_comes_from_the_clock
- test_ui_clock_injection.py: test_admin_routes_use_the_app_token_service (no second TokenService is constructed)
- test_ui_clock_injection.py: test_session_expires_when_the_fake_clock_passes_the_ttl
- test_ui_clock_injection.py: test_settings_are_rechecked_after_recheck_sec_on_the_given_clock
- test_ui_clock_injection.py: test_experiment_source_gives_its_caches_monotonic_and_its_journal_wall_time
- test_ui_clock_injection.py: test_store_upkeep_spaces_its_passes_on_the_given_clock_and_hands_it_to_app_upkeep
- test_ui_clock_injection.py: test_control_plane_sweep_cutoff_follows_the_given_clock
- test_ui_clock_injection.py: test_event_stream_heartbeats_on_the_given_clock_without_real_sleeping
- test_ui_clock_injection.py: test_registry_snapshot_is_rebuilt_only_after_refresh_sec_on_the_given_clock
- test_ui_clock_injection.py: test_registry_listing_is_reused_inside_refresh_sec_on_the_given_clock
- G1 allowlist: real_default and time entries removed per step

**Files.** `packages/vmn-exp/src/vmn_exp/ui/app_deps.py`, `packages/vmn-exp/src/vmn_exp/ui/audit.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/tokens.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/sessions.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_admin.py`, `packages/vmn-exp/src/vmn_exp/ui/control_plane_sweep.py`, `packages/vmn-exp/src/vmn_exp/ui/experiment_source.py`, `packages/vmn-exp/src/vmn_exp/ui/settings_cache.py`, `packages/vmn-exp/src/vmn_exp/ui/refresher.py`, `packages/vmn-exp/src/vmn_exp/ui/store_upkeep.py`, `packages/vmn-exp/src/vmn_exp/ui/cache_resync.py`, `packages/vmn-exp/src/vmn_exp/ui/journal_follow.py`, `packages/vmn-exp/src/vmn_exp/ui/failure_streak.py`, `packages/vmn-exp/src/vmn_exp/ui/live_events.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_events.py`, `packages/vmn-exp/src/vmn_exp/ui/registry_snapshot.py`, `packages/vmn-exp/src/vmn_exp/ui/server.py`, `packages/vmn-exp/src/vmn_exp/ui/cli.py`

**Risk.** Each class uses a specific time base (AuditLog, tokens, sessions, OIDC, the control-plane sweeper and WorkspaceJournal: epoch seconds; refresher, SettingsCache, WorkspaceCache, the upkeep classes, streaks and registry snapshots: monotonic). Passing the wrong one silently breaks expiry; each test asserts the stored value against the fake clock's base. Plan 42 E5a changes the TokenService, SessionService and AuditLog constructors (TTL wiring, revoke-by-owner) and lands first; step (a) and (b) then remove the clock defaults from the constructors as E5a left them, and the site counts above are re-taken then. test_ui_models_list_snapshot.py:63 patches `registry_snapshot.REFRESH_SEC`; the constant stays a module global read at call time in that module.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/experiment_source.py:108 (SettingsCache built inside ExperimentSource)`; `packages/vmn-exp/src/vmn_exp/ui/routes_admin.py:39 (TokenService(_control_plane(app)) per request, default clock)`; `packages/vmn-exp/src/vmn_exp/ui/auth/device.py:32 (TokenService(oidc.store, clock=oidc.clock): already threaded)`; `packages/vmn-exp/src/vmn_exp/ui/refresh_watch.py:22 and ui/refresher.py:227,342 (FailureStreak built with the refresher's clock)`; `packages/vmn-exp/src/vmn_exp/ui/diag/gc_pauses.py:28,79 (defaults plus module-level PAUSES = GcPauses())`; `packages/vmn-exp/src/vmn_exp/ui/registry_snapshot.py:148,219 (RegistrySnapshots and RegistryListings constructors, no clock); 181,193,200,228,231 (time.monotonic()); 184 (thread start)`; `the 16 defaults, re-read at HEAD with their class names: ui/store_upkeep.py:56 (AppUpkeep), ui/settings_cache.py:29 (SettingsCache), ui/cache_resync.py:55 (WorkspaceCache), ui/control_plane_sweep.py:26 (ControlPlaneSweeper), ui/journal_follow.py:46 (WorkspaceJournal), ui/failure_streak.py:15 (FailureStreak), ui/live_events.py:151 (event_stream: clock and sleep), ui/diag/latency.py:64 (sleep), ui/diag/gc_pauses.py:28 (clock and wall), ui/auth/oidc.py:70 (OIDCAuthenticator), ui/auth/tokens.py:55 (TokenService), ui/auth/sessions.py:19 (SessionService), ui/audit.py:31 (AuditLog), ui/refresher.py:132 (Refresher)`; `packages/vmn-exp/src/vmn_exp/ui/store_upkeep.py:160 (StoreUpkeep constructor, no clock); 174 (AppUpkeep(storage, app_name) with the default); 210,220 (time.monotonic())`; `packages/vmn-exp/src/vmn_exp/ui/experiment_source.py:90,227 (WorkspaceJournal and WorkspaceCache built there) and ui/server.py:196 (the one ExperimentSource construction)`; `packages/vmn-exp/src/vmn_exp/ui/control_plane_sweep.py:68-70 (install builds the sweeper with the default clock)`; `packages/vmn-exp/src/vmn_exp/ui/cli.py:166 (OIDCAuthenticator(config, control_plane)) and ui/auth/oidc.py:75 (SessionService(store, clock=clock))`; `grep of packages/vmn-exp/tests at HEAD for each constructor name (the site counts under Test edits)`

<a id="g5"></a>
### G5. JobRunner and the three UI subprocess sites take injected processes, ids and a thread starter

P2 · M · depends on G2, G4; plan 42 E1 and E6 land first

**Problem.** ui/jobs.py calls subprocess.run, shutil.which, uuid.uuid4() and threading.Thread inline, so every job test needs a real subprocess and a 0.2s poll loop. ui/git_context.py and ui/tree_cache.py also call subprocess.run directly.

**Approach.**

JobRunner gains keyword-only `processes`, `random`, `spawn`, `which`: `run_command` calls `processes.run(argv, cwd=..., timeout=..., stdin=DEVNULL-equivalent)`, job ids come from `random.hex_id()`, `_start` calls `spawn(target, args)` (real: a daemon thread; unit tests: run inline or hold the job). real_deps (G4) builds it. `git_context(path, processes)` and `versions_fingerprint(root_path, app_name, processes)` take the port; routes_shell.register and the ui index receive it from build_app. `build_command` and `_metric_args` are not touched: plan 42 E1 moves the validators and the argv builder to `ui/job_argv.py` before this item, and they do no IO.

**Tests first.**

- packages/vmn-exp/tests/unit/test_ui_job_runner.py: test_submit_runs_the_command_and_records_exit_code_and_log
- test_ui_job_runner.py: test_timeout_fails_the_job_with_exit_code_minus_one_and_frees_the_workspace (FakeProcesses raises TimeoutExpired)
- test_ui_job_runner.py: test_second_submit_in_a_busy_workspace_is_refused (a spawn that holds the job)
- test_ui_job_runner.py: test_missing_console_script_falls_back_to_python_dash_m (which returns None)
- test_ui_job_runner.py: test_job_stdin_is_closed (the run call carries the no-stdin argument)
- test_ui_job_runner.py: test_finished_jobs_beyond_max_jobs_are_evicted_oldest_first
- packages/vmn-exp/tests/unit/test_ui_git_context_unit.py: test_git_timeout_is_reported_not_raised; test_status_text_is_parsed (scripted git output)

**Files.** `packages/vmn-exp/src/vmn_exp/ui/jobs.py`, `packages/vmn-exp/src/vmn_exp/ui/app_deps.py`, `packages/vmn-exp/src/vmn_exp/ui/git_context.py`, `packages/vmn-exp/src/vmn_exp/ui/tree_cache.py`, `packages/vmn-exp/src/vmn_exp/ui/index.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_shell.py`

**Risk.** The 7 existing direct `JobRunner()` constructions (3 test files) gain the new keywords in one mechanical, arguments-only commit (approved; G4 list 1). test_ui_jobs_store.py also patches `JobRunner.submit` on the class, which keeps working. Job semantics (one per workspace, closed stdin, timeout) must pass through unchanged; test_fix_ui_security_jobs.py and test_ui_jobs*.py stay as the real-subprocess safety net. Plan 42 E6 adds workspace and org to `Job` and E7 an optional job store; the keyword-only parameters here go after whatever E6 left in the constructor (plan 37 order: E1 -> E6 -> G5 -> E7).

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/jobs.py:209 (JobRunner.__init__(timeout_sec, max_jobs); line numbers re-read at HEAD after 859da19b)`; `packages/vmn-exp/src/vmn_exp/ui/jobs.py:232,237,244 (uuid.uuid4().hex)`; `packages/vmn-exp/src/vmn_exp/ui/jobs.py:264-275 (shutil.which + subprocess.run with stdin=DEVNULL and timeout)`; `packages/vmn-exp/src/vmn_exp/ui/jobs.py:288-289 (threading.Thread started inline)`; `packages/vmn-exp/src/vmn_exp/ui/git_context.py:46-50 (subprocess.run in _status)`; `packages/vmn-exp/src/vmn_exp/ui/tree_cache.py:19-26 (versions_fingerprint runs git tag); called from ui/index.py:143 and tree_cache.py:42`; `packages/vmn-exp/src/vmn_exp/ui/routes_shell.py:91 (git_context called inside the route module)`; `packages/vmn-exp/tests/test_ui_jobs.py:31-38 (time.sleep(0.2) polling)`; `packages/vmn-exp/tests/test_fix_ui_security_jobs.py:25,36,47,58; test_ui_jobs_bulk.py:20,41; test_ui_jobs_store.py:155 (JobRunner() built directly, 7 sites)`

<a id="g6"></a>
### G6. Split the 724-line create_app closure into a ServerContext and route modules

P2 · L · depends on G4, G5; plan 42's route changes (E5a, E6, E9, E10, E12a-c) land first

**Problem.** create_app (server.py:115-838) is one closure with 63 nested functions: 14 inline routes, 2 middlewares, an exception handler and about 45 helpers (_workspace, _exp_storage_for, _settings, _leaderboard_inputs, _capabilities, _bulk_action...). The helpers cannot be tested without building the whole FastAPI app.

**Approach.**

Pure refactor in four separately landing steps, each new file under 300 lines, each following the existing `routes_x.register(app, API_PREFIX, ...)` pattern: (1) ui/server_context.py: `ServerContext` holding the resolver closures as methods (workspace, git_workspace, app_name, segment, exp_storage_for, any_exp_storage, settings, app_schema, leaderboard_inputs, capabilities, edit_storage). It receives its collaborators as constructor arguments, including `open_workspace_storage=lambda ws: workspace_storage(ws)` defined in server.py so the name is still looked up in ui.server at call time (the existing patch keeps working). (2) ui/routes_workspaces.py: meta, list/add/remove workspace, list_apps. (3) ui/routes_actions.py: run_action, bulk action, store action, get_job. (4) ui/routes_experiment.py and ui/routes_versions.py. server.py keeps middleware, wiring (including the `RegistryListings`/`RegistrySnapshots` objects upstream added at 791-792 and 809) and the register calls; the ValueError handler is wherever plan 42 E12c left it (`api_errors.install`). Written first and green through every step: a characterization test pinning the ordered route table.

**Tests first.**

- packages/vmn-exp/tests/test_ui_route_table.py: test_route_table_is_unchanged (ordered (path, sorted methods) list equals a golden list captured before step 1 and after plan 42's route changes, e.g. E5a's `DELETE /api/v1/tokens`)
- packages/vmn-exp/tests/unit/test_ui_server_context.py: test_unknown_workspace_is_404
- test_ui_server_context.py: test_store_workspace_storage_is_built_once_and_reused (counting opener)
- test_ui_server_context.py: test_unusable_store_is_404_with_its_message
- test_ui_server_context.py: test_invalid_app_tag_is_rejected
- packages/vmn-exp/tests/unit/test_ui_routes_actions.py: test_read_only_server_refuses_actions; test_store_action_without_edit_capability_is_403; test_bulk_dry_run_returns_a_preview_without_a_job (recording job runner from G4/G5)
- existing, must stay green unedited: test_fix_simplify_read_path.py (workspace_storage patch), test_ui_audit.py and test_ui_authz.py (iterate app.routes)

**Files.** `packages/vmn-exp/src/vmn_exp/ui/server.py`, `packages/vmn-exp/src/vmn_exp/ui/server_context.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_workspaces.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_actions.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_experiment.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_versions.py`, `packages/vmn-exp/tests/test_ui_route_table.py`, `packages/vmn-exp/tests/file_size_known.py`

**Risk.** FastAPI matches routes in registration order and several paths overlap under `.../apps/{app_tag}/...`; the route-table test pins order and each step moves one block without reordering. Functions moved out of server.py stop seeing names patched on ui.server: `workspace_storage` is handled as above, and before each step grep the tests for patches of `meta_payload` and `app_exists` on ui.server (none found today) and treat any new one the same way. ServerContext must be built after `leaderboards`, `source` and `jobs` exist. The line ranges under Evidence are HEAD's; plan 42 changes this function before this item, so the blocks are re-located by route path, not by line.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/server.py:115 (def create_app; body to 838, re-read at HEAD)`; `packages/vmn-exp/src/vmn_exp/ui/server.py:236,248,262 (middlewares and exception handler)`; `packages/vmn-exp/src/vmn_exp/ui/server.py:317-360 (meta and workspace routes inline)`; `packages/vmn-exp/src/vmn_exp/ui/server.py:584-670 (actions and jobs inline)`; `packages/vmn-exp/src/vmn_exp/ui/server.py:673-734 (experiments-diff, changelog, config inline)`; `packages/vmn-exp/src/vmn_exp/ui/server.py:750-834 (21 routes_*.register calls: the pattern to follow)`; `packages/vmn-exp/src/vmn_exp/ui/server.py:211,785 (refresher.on_refresh assigned mid-function; forget_git returned by routes_shell.register and used at 356)`; `packages/vmn-exp/tests/test_fix_simplify_read_path.py:245-255 (patches server_mod.workspace_storage and expects create_app to use it)`

<a id="g7"></a>
### G7. CLI composition root: vmn-exp handlers receive io

P2 · S · depends on G2

**Problem.** vmn-exp commands run through vmn's `vmn_run`, which calls each CommandSpec handler with only `vmn_ctx`. There is no way to hand cli/ logic a fake clock, env or console, so it reaches for globals (15 time calls, 14 env reads, 144 prints). Binding io into the CommandSpecs at registration cannot work: the registry is an append-only list, `find` returns the first match and `_register` skips names already present, so a second `register_all(io)` would silently keep the first io, and the suite's autouse fixture registers once per process.

**Approach.**

Every command function takes an explicit `io` parameter: `handle_experiment(vmn_ctx, io)`, `handle_sweep(vmn_ctx, io)`, `handle_ui(args, io)`, `run_login(argv, io)`, `run_migrate(argv, io)`, `run_skill(argv, io)`, and the `run_without_repo` handlers (`model_run_without_repo(args, io)` and its siblings). The composition roots are the thin shims in cli/plugin.py (`_handle_experiment`, `_handle_sweep`, `_handle_ui`, the run_without_repo shims) and the three early exits of `vmn_exp_run` in cli/main.py: each builds `real_io()` once per invocation and passes it. Nothing is stored in the registry, so there is no global to rebind. Unit tests call `handle_experiment(ctx, fake_io)` directly.

When plan 35 stage 0 lands and `vmn_ctx.io` exists, each shim's `real_io()` becomes `vmn_ctx.io` (a one-line change per shim, recorded here as the follow-up). The early exits in cli/main.py keep building `real_io()`: `vmn_exp.cli.main:main` is already a named entry point.

CLAUDE.md gains the entry-point bullet under [CLAUDE.md lines](#claudemd-lines) in this item's commit. This item only delivers io to the handler boundary; G8, G12 and G16 consume it.

**Tests first.**

- packages/vmn-exp/tests/unit/test_cli_root.py: test_handle_experiment_passes_io_to_the_action (a stub action records the io it got)
- test_cli_root.py: test_plugin_shim_builds_real_io_once_per_invocation (the shim's handler receives an IO whose clock is the real class; two invocations get two IO objects)
- test_cli_root.py: test_login_receives_io (run_login(argv, fake_io) writes its prompt to the fake console)
- test_cli_root.py: test_wrong_command_hint_goes_to_stderr_with_exit_code_2 (vmn_exp_run(['stamp'], fake_io))
- test_cli_root.py: test_no_handler_module_calls_real_io (AST scan: `real_io(` appears in cli/ only in plugin.py and main.py)

**Files.** `packages/vmn-exp/src/vmn_exp/cli/main.py`, `packages/vmn-exp/src/vmn_exp/cli/plugin.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment.py`, `packages/vmn-exp/src/vmn_exp/cli/sweep/handler.py`, `packages/vmn-exp/src/vmn_exp/cli/login.py`, `packages/vmn-exp/src/vmn_exp/cli/migrate.py`, `packages/vmn-exp/src/vmn_exp/cli/skill.py`, `packages/vmn-exp/src/vmn_exp/cli/model_cmd.py`, `packages/vmn-exp/src/vmn_exp/ui/cli.py`, `CLAUDE.md`

**Risk.** `handle_experiment` and friends are called directly by a few tests and by cli/rerun and sweep code; grep each for direct callers before adding the parameter (handle_experiment has one production caller) and add `io` to the test calls in the same commit (approved, argument-only). cli/plugin.py and cli/main.py are also edited by A4, B1, B5a, B8 and C6; this item lands after them (plan 37 order A4 -> B1 -> B5a -> B8 -> C6 -> G7), so the shim list must be re-read at start: B5a moves the parser out of plugin.py and C6 registers `buffers`, which needs a shim too. The `vmn.plugins` entry point (`register_dev_version`, plugin.py:493) is a second root for `vmn goto` of dev versions and builds its own `real_io()` in `_dev_version_loader` when that path starts needing it.

**Owner decision (2026-11-11).** Handlers take `io` explicitly. The plugin.py shims build `real_io()` per invocation until plan 35 provides `vmn_ctx.io`. The shims are approved in CLAUDE.md as entry points that may build real IO.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/main.py:25-51 (vmn_exp_run -> vmn_run(argv); main builds nothing; three early exits for skill, migrate, login)`; `packages/vmn-exp/src/vmn_exp/cli/plugin.py:339-354 (handler shims take vmn_ctx only)`; `packages/vmn-exp/src/vmn_exp/cli/plugin.py:482-484 (_register skips a name that is already registered)`; `packages/vmn/src/version_stamp/cli/plugin_api.py:71-89 (registry is a module-level list; register appends; find returns the first match)`; `packages/vmn-exp/tests/conftest.py:37-45 (autouse register_all() for every test)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:327-337 (handle_experiment reads os.environ at 335)`; `docs/plans/35-core-io-behind-interfaces.md:38-47 (plan 35: run_command(argv, io) and vmn_ctx.io)`; `CLAUDE.md:44 (the entry-point list this item extends)`

<a id="g8"></a>
### G8. cli/run.py supervision on injected clock, processes, env and host

P2 · M · depends on G2, G7, plan 38 A4, plan 39 B9b

**Problem.** `_Supervision` (the `vmn-exp run` child supervisor) calls time.monotonic, time.sleep, subprocess.Popen, os.environ, socket.gethostname and tempfile.mkstemp inline, and `SignalForwarder` reads time.monotonic for its kill grace. Heartbeat cadence, sync cadence, the final-state retry (sleep(1) between attempts) and the env handed to the child can only be tested by running a real child and waiting; test_fix_exp_run_supervisor.py has 6 real sleeps. Two earlier items change the same code first: A4 extracts the child env into `cli/supervised_env.py` (`supervised_env(base_env, ...)`), and B9b replaces the fixed-sleep loop with `cli/supervise_loop.py` `watch(child_exited, wait_child, tick, clock, interval)` and builds the loop body as a `tick` callable in `_Supervision._supervise`.

**Approach.**

No second loop or tick extraction: this item only injects io into what A4 and B9b leave.

`_Supervision.__init__` gains keyword-only `io` (from G7), after A4's keyword-only `adopt`. Then:
- `_start` passes `io.env` as `supervised_env`'s `base_env` and starts the child with `io.processes.popen`.
- `_supervise` passes `io.clock.monotonic` as `watch`'s clock (replacing the `time.monotonic` B9b picks inside `_Supervision`) and uses it for the tick's sync and heartbeat cadence and for the run duration.
- run state uses `io.host.hostname()`.
- `_publish_final` sleeps through `io.clock.sleep`; the final-sync deadline reads `io.clock.monotonic()`.
- `SignalForwarder(grace_sec, clock)` takes the monotonic callable for its kill deadline.
- `_child_cwd(env)`, `_kill_grace_sec(args, env)` and the from_snapshot lookup take `env`.

The metrics temp file stays a real mkstemp in `run()` (the tailer reads a real file) and is listed in G1's allowlist with that reason. The unit tests exercise `_start`, the tick callable and `_publish_final`, not `run()`. All three construction sites pass io.

Test edits (approved, argument-only): the three positional `_Supervision(...)` constructions in test_exp_rerun_recording.py:140,155,165 gain `io=`. `_Supervision` is built in no other test file.

**Tests first.**

- packages/vmn-exp/tests/unit/test_cli_supervision.py: test_heartbeat_is_published_once_per_interval (FakeClock; call the tick with advancing `now`)
- test_cli_supervision.py: test_sync_is_requested_after_sync_interval_and_not_before
- test_cli_supervision.py: test_final_state_write_is_retried_with_one_second_sleeps (a storage stub failing twice; FakeClock records the sleeps)
- test_cli_supervision.py: test_child_env_is_built_from_the_given_env_not_the_process_env (FakeEnv; a marker variable only in the fake reaches the popen call)
- test_cli_supervision.py: test_command_not_found_returns_1_and_publishes_no_run_state (FakeProcesses.popen raises FileNotFoundError)
- test_cli_supervision.py: test_kill_grace_reads_the_given_env_then_the_default
- test_cli_supervision.py: test_signal_forwarder_kills_after_the_grace_on_the_given_clock
- test_cli_supervision.py: test_run_state_host_comes_from_the_host_port
- test_cli_supervision.py: test_on_tick_hook_is_called_each_tick_and_its_error_is_guarded

**Files.** `packages/vmn-exp/src/vmn_exp/cli/run.py`, `packages/vmn-exp/src/vmn_exp/cli/supervisor.py`, `packages/vmn-exp/src/vmn_exp/cli/rerun.py`, `packages/vmn-exp/src/vmn_exp/cli/sweep/agent.py`, `packages/vmn-exp/tests/unit/test_cli_supervision.py`, `packages/vmn-exp/tests/test_exp_rerun_recording.py`

**Risk.** SignalForwarder and OutputTee use the real Popen object; the fake process must offer poll/wait/pid/terminate/kill and stdout, and `wait(timeout)` because B9b's loop wakes on the child's exit. `sysmetrics.Sampler` is built inside `_supervise` (run.py:370 today) and keeps its own clock until G10. test_fix_exp_run_supervisor.py patches `cli.run._FINAL_SYNC_TIMEOUT_SEC`; the constant stays in cli/run.py. The line numbers under Evidence are HEAD's and will have moved after A4, B9b and plan 40 C15 (which gives `BackgroundSync` a `final_sync` and a retry in cli/supervisor.py and splits `_sync_once` in cli/run.py); re-read `_Supervision` before starting. C15's retry (C1's `FinalRetry`) takes its sleep and deadline from the same `io.clock`.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/run.py:269-287 (constructor; builds SignalForwarder, BackgroundSync, output artifact)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:290 (tempfile.mkstemp)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:318-329 (dict(os.environ) and subprocess.Popen)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:352 (socket.gethostname)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:379-397 (poll loop on time.monotonic / time.sleep, replaced by B9b)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:424,459 (duration and final-sync deadline on time.monotonic)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:497-511 (final state retry with time.sleep(1))`; `packages/vmn-exp/src/vmn_exp/cli/run.py:126,133,170 (env reads in helpers)`; `packages/vmn-exp/src/vmn_exp/cli/supervisor.py:187,192 (SignalForwarder kill grace on time.monotonic)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:254, cli/rerun.py:159, cli/sweep/agent.py:99 (the three construction sites)`; `docs/plans/39-vmn-exp-cli-surface.md (B9b: watch(child_exited, wait_child, tick, clock, interval) in cli/supervise_loop.py)`; `docs/plans/38-vmn-exp-first-run.md (A4: supervised_env(base_env, ...) in cli/supervised_env.py)`

<a id="g9"></a>
### G9. Split sdk/run.py (889 lines) along its mixin seams without breaking module-global patches

P3 · M · depends on G18 and on plan 40's and plan 38's sdk/run.py items having landed

**Problem.** sdk/run.py holds start_run, the 485-line Run class and the process-exit/signal finalizers in one file, three times the file-size guideline. Tests patch names on the run module that the close path and the finalizers read (compact_by, sync_to_remote, error_from_exception, FINAL_REMOTE_TIMEOUT_SEC, _finalize_signaled); if those functions moved behind re-exports they would read their new module's globals and the patches would silently stop applying.

**Approach.**

Move only what no test patches through the run module. This item runs last in the sdk/run.py chain (plan 37 order: C1 -> C7 -> C4 -> C3 -> C9 -> C8 -> A5 -> D5/D6 -> G9 -> G10), so the method list is re-read at start; the cut below is by responsibility.

Step 0, before plan 40 C1 starts: the characterization tests for the patched names (below) are written and green, so C1's move of the sync worker into `sdk/log_sync.py` is already guarded. C1 must hand LogSync its job as a callable defined in run.py so the `sync_to_remote` and `compact_by` patches keep applying.

Step 1: sdk/run_records.py with a `RunRecords` mixin (log_params, log_note, log_input, log_artifact, _save_artifact_file, register_model, use_model, use_dataset, set_tag(s), remove_tag, similar). `set_intent` stays in run.py because it reads the patched `sync_to_remote`.

Step 2: sdk/run_close.py with a `RunClose` mixin for the close path, where the two patched collaborators are reached through the instance (`self._compact_by`, `self._error_from_exception`: small methods defined in run.py that read run.py's module names at call time), so a patch on vmn_exp.sdk.run still takes effect. A5's `GuestRun` overrides `_publish`, `_record_final`, `release` and `_close_remote_writers`; the mixin is placed so those overrides still win (GuestRun subclasses Run, so they do) and the MRO test covers it.

The finalizer functions, signal handlers, `FINAL_REMOTE_TIMEOUT_SEC` and `final_upload_timeout_sec` stay in run.py. Their registration (excepthook, atexit) lives in `sdk/process_hooks.py` after plan 40 C9 and is not touched here. Target: run.py about 550 lines; the G18 entry is lowered, not removed. No behaviour change.

**Tests first.**

- packages/vmn-exp/tests/unit/test_sdk_run_layout.py: test_run_module_still_exposes_its_public_and_patched_names (Run, start_run, _finalize_open_runs, _finalize_signaled, install_signal_handlers, final_upload_timeout_sec, FINAL_REMOTE_TIMEOUT_SEC, compact_by, sync_to_remote, error_from_exception; green before and after)
- test_sdk_run_layout.py: test_patching_compact_by_on_the_run_module_reaches_the_close_path (characterization: written at step 0, green before the move, must stay green)
- test_sdk_run_layout.py: test_patching_sync_to_remote_on_the_run_module_reaches_the_sync_worker (step 0; guards C1)
- test_sdk_run_layout.py: test_patching_error_from_exception_on_the_run_module_reaches_record_error
- test_sdk_run_layout.py: test_no_run_method_is_defined_by_two_bases (MRO check over Run's mixins)
- existing, unedited: test_sdk_finalize_bounds.py, test_sdk_detach.py, test_sdk_run_error.py, test_exp_push_metrics.py, test_exp_import_boundary.py

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/run_records.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/run_close.py`, `packages/vmn-exp/tests/unit/test_sdk_run_layout.py`, `packages/vmn-exp/tests/file_size_known.py`

**Risk.** Method resolution order changes when methods move to mixins: new mixins go last in the base list and the MRO test rejects duplicate names. run.py does not reach 300 lines in this plan: cutting the finalizers out would require editing the four test files that patch them, and those edits are not named here, so they still stop and ask. Fork handlers (sdk/fork_safety.py) reference Run by attribute, not module, and are unaffected. The new modules are on the start_run import path; plan 41 D1's import budget is raised in the commit that adds each, naming the module.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:310 (class Run(RunMetrics, MetricDefinitions, RunArtifacts, RunMedia, RunAlerts, RunBackground): existing mixin pattern)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:630-737 (params, inputs, artifacts, models, tags, intent, similar)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:502,592 (error_from_exception and compact_by used in the close path)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:377,725 (sync_to_remote used in __init__ and set_intent)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:843,864,879 (FINAL_REMOTE_TIMEOUT_SEC, _finalize_signaled, install_signal_handlers)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:888 (atexit.register(_finalize_open_runs), moved by plan 40 C9)`; `packages/vmn-exp/tests/test_exp_push_metrics.py:90,131, test_sdk_detach.py:86, test_sdk_finalize_bounds.py, test_sdk_run_error.py (the files that setattr those five names on vmn_exp.sdk.run)`; `sdk/run.py is unchanged between 25f03f3d and HEAD`

<a id="g10"></a>
### G10. SDK composition root: start_run builds real IO; Run and sysmetrics take clock and host; buffered store takes a clock

P2 · L · depends on G2, G3, G9, plan 40's buffered-store chain (C3, C13, C5, C6)

**Problem.** The SDK's run lifecycle reads time.monotonic, os.getpid and socket.gethostname inline, so run duration, sync throttling, the final-upload deadline, the sampler's minimum interval and the buffered store's flush interval are tested with real sleeps (test_exp_sysmetrics.py has 11, test_sdk_background_pause.py 6). A library has no `main` to receive IO from.

**Approach.**

`start_run` and the other public `vmn_exp.sdk` functions are the SDK's entry points: each builds `real_io()` and passes what it needs down. Their public signatures do not change. CLAUDE.md gains the bullet under [CLAUDE.md lines](#claudemd-lines) (same bullet as G7; whichever lands first adds it). Plan 41 D10's `vmn_exp.sdk.resolve_storage` is one of these entry points: a thin SDK function that builds real IO and calls the core resolver, so the core function may take `clock` (here) and `env` (G12) as required parameters.

Three steps.

1. Run: `start_run` calls `real_io()` and passes keyword-only `clock` and `host` to `Run(...)`. Run uses them for `_monotonic_start`, `_duration`, `_maybe_sync`, `_initial_state` (which takes host as an argument) and `_in_owner`; `_final_upload_deadline` and `_left` become Run methods using the run's clock, and the atexit finalizer calls them on each open run. A5's `GuestRun` and any other Run subclass pass the same two keywords through.
2. sysmetrics: `Sampler` and `_ProcessProbe` take `clock` (monotonic, wall, sleep); the `_clock` alias (sysmetrics.py:79) is deleted; both construction sites pass it (sdk/run.py and cli/run.py, the latter from G8's io).
3. BufferedRemoteStorage takes keyword-only `clock` (a monotonic callable) in its constructor and in plan 40 C6's `reopen` classmethod. `open_storage` gains a keyword `clock` that is required together with `buffer_logs=True` (a `TypeError` otherwise) and is passed by its two production callers from their roots: core/storage_resolve.py:110 (from the SDK or CLI entry point) and the UI edit storage at ui/server.py:614 (from `deps.io`). `in_area` forwards it. Plan 40 C16 keeps that open where it is (store actions ship inline on the job thread and storage/buffered.py is not changed by it), so the clock is passed at that line.

Timestamps written by `now_iso()` are untouched here. sdk/context.py and sdk/fork_safety.py keep `os.getpid` (they detect a real fork), and storage/buffered.py keeps its `os.getpid` fork checks (47, 75, 89, 98); all three go on REAL_IO or the allowlist with that reason.

Test edits (approved, mechanical, one commit per class, constructor arguments only):
- `Run(...)`: 29 construction sites in 19 test files gain `clock=` and `host=`.
- `Sampler(...)`: 3 sites in 3 files (test_fix_sysmetrics_fork.py:37, test_sysmetrics_cost.py:66, test_fork_ungated_threads.py:71) gain `clock=`.
- `BufferedRemoteStorage(...)`: 9 sites in 8 files gain `clock=`.
- the 2 `monkeypatch.setattr(sysmetrics, "_clock", ...)` sites in test_sysmetrics_cost.py are replaced by a FakeClock handed to the Sampler.
- `open_storage` (175 sites in 127 files) is not edited: only calls with `buffer_logs=True` need the keyword, and the tests that pass it gain `clock=` in the BufferedRemoteStorage commit.

**Tests first.**

- packages/vmn-exp/tests/unit/test_sdk_run_clock.py: test_duration_is_elapsed_fake_clock_plus_prior_attempts
- test_sdk_run_clock.py: test_log_sync_is_skipped_inside_the_sync_interval_and_runs_after_it
- test_sdk_run_clock.py: test_final_upload_deadline_is_the_run_clock_plus_timeout
- test_sdk_run_clock.py: test_initial_state_records_host_and_pid_from_the_host_port
- test_sdk_run_clock.py: test_run_is_inert_when_host_pid_differs_from_the_owner (fork case without forking)
- test_sdk_run_clock.py: test_start_run_hands_the_run_a_real_clock_and_host (the root wires real IO)
- packages/vmn-exp/tests/unit/test_sysmetrics_clock.py: test_probe_waits_only_the_remaining_minimum_interval (FakeClock records the sleep); test_tree_walk_is_skipped_until_its_duty_cycle_allows
- packages/vmn-exp/tests/unit/test_buffered_flush_clock.py: test_log_ships_once_per_flush_interval; test_metric_block_ships_when_the_interval_elapsed (remote built on the in-memory bucket fakes in tests/object_store_fakes.py, FakeClock, tmp_path buffer dir)
- test_buffered_flush_clock.py: test_open_storage_with_buffer_logs_requires_a_clock
- test_buffered_flush_clock.py: test_a_reopened_buffer_uses_the_given_clock (after plan 40 C6)

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/run_close.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/sysmetrics.py`, `packages/vmn-exp/src/vmn_exp/cli/run.py`, `packages/vmn-exp-sdk/src/vmn_exp/storage/buffered.py`, `packages/vmn-exp-sdk/src/vmn_exp/storage/open.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/storage_resolve.py`, `packages/vmn-exp/src/vmn_exp/ui/server.py`, `CLAUDE.md`, and the test files named under Test edits

**Risk.** core/storage_resolve.py:110 is reached from many SDK and CLI paths; its clock comes from the same root that already passes `params`, and each public SDK function on the way is an entry point that may build it. Plan 40 changes storage/buffered.py four times before this item (C3 defer_ships, C13 buffer_state.py, C5 buffers_dir and buffer_owner.py, C6 reopen); the line numbers under Evidence are HEAD's and must be re-read. If plan 40 C3's off-thread ship worker adds a timer, it takes the same clock. Which functions of `vmn_exp.sdk` count as "public" is what `vmn_exp/sdk/__init__.py` exports (start_run, create_run(s), the model, dataset and alias functions, autolog, sweep_params) plus the reader functions sdk.md documents; G1's test_only_entry_points_and_listed_modules_call_real_io pins that in the SDK package only those modules, and the REAL_IO and REAL_WIRED modules, call `real_io()`.

**Owner decision (2026-11-11).** `vmn_exp.sdk.start_run` and the public SDK functions are entry points that may build real IO, recorded in CLAUDE.md. The test edits listed above are approved.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:256 (start_run constructs Run: the SDK's root)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:348,353 (os.getpid, time.monotonic in Run.__init__)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:408-409 (pid and socket.gethostname in the staticmethod _initial_state)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:609,787-789 (duration, sync throttle)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:846-851 (module-level _final_upload_deadline and _left use time.monotonic; called from Run methods and the atexit finalizer)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/sysmetrics.py:79,147-148,157-171,224-243,338 (module clock alias plus direct time.monotonic/time.time/time.sleep)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:390 and packages/vmn-exp/src/vmn_exp/cli/run.py:370 (the two Sampler construction sites)`; `packages/vmn-exp-sdk/src/vmn_exp/storage/buffered.py:63 (constructor); 172,189,209,219 (flush interval on time.monotonic); 47,75,89,98 (os.getpid fork checks); 54 (tempfile + uuid buffer dir, moved by plan 40 C5); 250 (_close, as fixed by 59becdd5)`; `packages/vmn-exp-sdk/src/vmn_exp/storage/open.py:17,49 and core/storage_resolve.py:110, packages/vmn-exp/src/vmn_exp/ui/server.py:614 (open_storage's buffer_logs parameter and the only two callers passing buffer_logs=True)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/__init__.py (the exported public functions)`; `packages/vmn-exp/tests/test_sysmetrics_cost.py:86 (the _clock patch)`

<a id="g11"></a>
### G11. Clock into status derivation and the clock aliases

P2 · XL (Part A: M, Part B: L) · depends on G2, G4, G7, G10; plan 41 D3 lands before it

**Problem.** Run status (running/stuck) is derived from the current time. core/status.py accepts `now` but falls back to the real clock in `_now()`: of 32 production call sites of `derive_status`, `status_fields` and `last_alive_at`, 26 pass no `now`, and ten more places read `experiment_status._now()` directly. Ten modules keep a patchable global (`_monotonic = time.monotonic`, `_wall = time.time`, `_now = time.time`, `_clock = time.monotonic`) and 8 sdk-side parameters default to time.*. Tests reach all of this by patching module globals: 121 `setattr` sites in 95 test files. Nearly every `status._now` patch has the form `lambda now=None: now or T0`, so the moment a production caller passes a real `now` the patch returns the real time and the test stops exercising what it asserts. Status and the aliases therefore move in one staged series, not caller by caller.

**Approach.**

Part A (M, small test edits): remove the sdk-side `clock=time.x` defaults of classes built in few places, passing the clock from their constructing caller, which gets it from start_run (G10) or the UI root (G4): `MetricStream` (core/metric_stream.py:64), `OutputLog` (core/output_log.py:112), the alert dispatcher (core/alerts/dispatch.py:42), the vmx check (core/index_vmx_check.py:110), the journal follower (storage/journal.py:176) and `ReportIndex` (reports/index.py:56, in vmn-exp after plan 41 D3). core/gc_policy.py:37-38 is a process-level GC tuner and goes on REAL_IO with that reason. Test edits (approved, constructor arguments only): OutputLog (6 sites, 1 file), ReportIndex (2 sites, 2 files), and any direct MetricStream or dispatcher construction found by grep at start.

Part B (L, the approved mechanical migration). End state:
- `derive_status(run_state, now, observed_at=None)`, `status_fields(run_state, now, observed_at=None)` and `last_alive_at(run_state, now, observed_at=None)` take a required aware-UTC `now`. `status._now` is deleted.
- A pure derivation takes `now` as a parameter from its caller; a long-lived object holds a `now` callable (or a `Clock`) given at construction and reads it once per build or request, never once per object lifetime.
- The 26 call sites and the ten direct `_now()` reads get it from their root:
  - UI (`deps.io.clock` through `build_app`): `LeaderboardCache(..., now=)` for leaderboard_cache.py:110 and 367; job_rollup_cache.py:36, 83, 159; attention.py:38; metrics_feed.py:39; routes_shell.py:102, 116; readers/baselines.py:21; readers/experiment_detail.py:44, 159; readers/last_good_index.py:44; routes_lineage.py:105; search_rank.py:79; store_upkeep.py:151 (`AppUpkeep` takes a `now` callable beside the monotonic clock G19 gives it, both handed down by `StoreUpkeep`).
  - Index internals (the index's clock, below): index_snapshot.py:166 (`IndexSnapshot.status_of(verstr, now)`; its callers in ui/leaderboard_cache.py, leaderboard_delta.py, leaderboard_live.py, search_index.py, search_rank.py, job_views.py, store_upkeep.py, readers/, core/similar_rows.py, similar_items.py, sdk/reader.py and cli/similar_backfill.py pass it), index_lean_store.py:56 (`run_status(record, now)`), index_sweep_state.py:70.
  - CLI (`io.clock.now()` from G7's handlers): cli/compact.py:24, cli/experiment.py:793, cli/migrate.py:92, cli/prune.py:121, cli/rerun_report.py:109, cli/views.py:188, and `derive_status` in cli/pushing/ (core/push_rename.py:39 before plan 41 D3).
  - SDK and core (the public function's `real_io().clock.now()`, or the run's clock): sdk/resume.py:63, sdk/run_states.py:43, core/fork.py:131, core/run_finish.py:144, core/alerts/transitions.py:115, core/tree.py:221, 303, 345, 400, core/query_ago.py:25.
- The index family holds a clock instead of aliases. `ExperimentIndex(..., *, clock=...)` passes `clock.monotonic` to its own reads (index.py:163, 306, 355, 424, 507, 558, 649, 658, 767, 996) and to `BulkPublish` (index_bulk.py:24), and the wall clock to `Sweep` (index_sweep.py:93), `Freshness` (index_freshness.py:29) and `Relisting` (index_relist.py:51). `SqliteStore(path, *, clock=...)` uses it for tombstone times (index_store.py:41, read at 280 and 284, and from ui/cache_pg.py:273, 278) and gives `StoreConnection` its monotonic retry clock (index_store_conn.py:36). `similar_match.deadline(conn, at, clock)` (similar_match.py:33) and `cli/similar_hint.print_hint` (similar_hint.py:59) take the monotonic callable that computed `at`. `shared_index`, `indexed_snapshot` and `indexed_status_rows` take a keyword `clock` and pass it on. All nine aliases are deleted (the tenth, sdk/sysmetrics.py:79, goes in G10).
- `ExperimentIndex`, `SqliteStore`, `LeaderboardCache`, `shared_index`, `indexed_snapshot` and `indexed_status_rows` are list-2 names (G4): a call that omits the clock gets `real_io().clock`. Every production call passes it explicitly, and a ratchet test asserts that:
    - `ExperimentIndex(`: 7 sites (ui/index.py:137, ui/elected_index.py:20, ui/cache_resync.py:35, core/index.py:335, 1107, 1112, core/index_io_process.py:258).
    - `LeaderboardCache(`: 1 site (ui/server.py:209).
    - `SqliteStore(`: 10 sites (ui/cache_rebuild.py:18, 37, 51, 60; ui/index.py:102, 118; ui/cache_resync.py:45; ui/report_index.py:83; ui/experiment_source.py:90, 238).
    - `shared_index(`, `indexed_snapshot(`, `indexed_status_rows(`: 19 sites (ui/index.py:40, 52, 112; ui/experiment_source.py:173; cli/compact.py:22; cli/similar_backfill.py:75, 88; cli/prune.py:159; core/index.py:1197, 1212; core/index_list.py:77, 97; core/refs.py:46; core/similar_search.py:77, 110; core/alerts/transitions.py:130; core/sweep/summary.py:30; sdk/reader.py:119; registry/lineage.py:85). The module-level functions among their callers gain a `clock` parameter and get it from their own caller, up to a handler, `build_app` or a public SDK function.
  core/index_io_process.py:258 builds the index inside the helper process. That process has its own `main()` (index_io_process.py:305, started with `python -c` at 137), which is its entry point: `main()` builds `real_io()` and `_Helper` passes the clock on (REAL_IO, with that reason).

How the series is staged: one worktree, three commits, merged together without squashing. Each commit is green on its own.

1. Accept (production plus new unit tests). Every function and class above accepts `now` or `clock`. Where the caller gives none, the existing seam is used, read at call time: `status._now` for status, the module alias for the index family. The injected roots (`build_app` given deps, handlers given io, `Run` given a clock) route what they are given; the real-wired roots (`real_deps`, the plugin shims, `start_run`) pass `None` for the status and index clock in this commit. So production behaviour and all existing patches are unchanged, and the new unit tests (red first) drive the injected path with a FakeClock.
2. Migrate (tests only; no file under `src/` changes; reviewed by diff). Each patch site is replaced by a FakeClock handed to the object the test builds:
   - `status._now`: 89 sites in 74 files. By a grep of each file: 56 build `LeaderboardCache(...)` directly and gain `now=clock.now`; 13 use an app client (8 of them also build a cache) and switch from `create_app` to `build_app(manager, fake_deps(clock))`, with `fake_deps` a helper in packages/vmn-exp/tests/unit_deps.py; test_index_list_sql.py calls the handler with a fake io; test_exp_reader.py, test_index_live_relist.py, test_query_ago.py and uiload/fgm_records.py pass `now` to the function they call.
   - `core.index._monotonic`: 11 sites in 11 files, all building `ExperimentIndex(...)` directly: `clock=clock`.
   - `core.index_sweep._wall` 4 sites in 4 files; `core.index_freshness._wall` 3 in 2 (test_ui_status_freshness.py through `build_app`); `core.index_store._now` 2 in 2 and `core.index_store_conn._monotonic` 2 in 1 (`SqliteStore(path, clock=clock)`); `core.similar_match._clock` 5 in 2; `cli.similar_hint._clock` 3 in 2.
   - Total 119 sites (121 with the two sysmetrics sites G10 migrates) in 95 files.
   - The 53 direct test calls without `now` (`derive_status` 42 in 16 files, `status_fields` 11 in 5 files) gain an explicit `now`, and the two reads of `status_mod._now()` in job_rollup_reference.py:154 and test_ui_rollup_gauges_bench.py:48 read the test's clock.
   - The commit changes nothing but how a test supplies time: no assertion, fixture scope or test name changes. A reviewer checks that with `git diff --stat` (tests only) and by reading the diff.
3. Remove (production, plus the commit-3 tests under Tests first, written first and red). `now` becomes required, `status._now` and the nine aliases are deleted, the `None` fallbacks go, the real-wired roots pass `io.clock`, the list-2 constructors resolve an omitted clock to `real_io().clock`, and the G1 allowlist is lowered. Apart from those new tests, packages/vmn-exp/tests/unit_deps.py is the only test file touched. The same commit changes docs/vmn-exp/experiments.md:267 to `derive_status(state, now, observed_at=...)` and adds the `upgrading.md` row for it (plan 43 F9), with a `!` in the commit subject.

Until the series merges, `status._now` and the aliases stay as they are; no half-step is merged.

**Tests first.**

- Part A, packages/vmn-exp/tests/unit/test_sdk_clock_defaults.py: test_metric_stream_stamps_blocks_with_the_given_clock; test_output_log_throttles_on_the_given_clock; test_alert_dispatch_cooldown_follows_the_given_clock; test_report_index_full_sweep_is_due_after_full_sweep_sec; test_journal_follower_reads_the_given_clock
- Part B commit 1, packages/vmn-exp/tests/unit/test_status_clock.py: test_running_becomes_stuck_when_the_given_now_passes_the_stale_window; test_status_fields_uses_the_given_now_for_durations; test_last_alive_at_ignores_a_writer_time_after_the_given_now
- Part B commit 1, packages/vmn-exp/tests/unit/test_status_callers_pass_now.py: test_leaderboard_rows_flip_to_stuck_when_the_fake_clock_advances (no patching); test_cli_list_derives_status_at_the_io_clock; test_now_is_read_per_snapshot_build_not_once_per_refresher; test_snapshot_status_of_uses_the_given_now
- Part B commit 1, packages/vmn-exp/tests/unit/test_index_clock.py: test_refresh_if_stale_uses_the_given_clock; test_full_listing_is_due_after_full_sweep_sec; test_unreadable_record_is_retried_after_the_backoff; test_tombstones_are_stamped_and_swept_on_the_store_clock; test_store_reconnect_waits_out_its_backoff_on_the_given_clock; test_similar_search_stops_at_its_deadline_on_the_given_clock; test_freshness_as_of_follows_the_given_wall_clock; test_index_helper_builds_its_index_on_the_given_clock (`_Helper` built in-process on tmp_path with a FakeClock; no helper process is started)
- Part B commit 3, test_status_clock.py: test_derive_status_without_now_is_a_type_error; packages/vmn-exp/tests/test_io_boundary.py: test_no_clock_alias_remains_in_core_or_cli (the `clock_alias` kind is zero outside REAL_IO); test_production_code_passes_a_clock_to_every_list_2_name (AST scan over both `src/` roots)

**Files.** Part A: `packages/vmn-exp-sdk/src/vmn_exp/core/metric_stream.py`, `core/output_log.py`, `core/alerts/dispatch.py`, `core/index_vmx_check.py`, `storage/journal.py`, `packages/vmn-exp/src/vmn_exp/reports/index.py`. Part B, sdk package: `core/status.py`, `core/index.py`, `core/index_bulk.py`, `core/index_sweep.py`, `core/index_sweep_state.py`, `core/index_freshness.py`, `core/index_relist.py`, `core/index_store.py`, `core/index_store_conn.py`, `core/index_snapshot.py`, `core/index_lean_store.py`, `core/index_io_process.py`, `core/index_list.py`, `core/similar_match.py`, `core/similar_search.py`, `core/similar_rows.py`, `core/similar_items.py`, `core/tree.py`, `core/fork.py`, `core/run_finish.py`, `core/query_ago.py`, `core/alerts/transitions.py`, `core/refs.py`, `core/sweep/summary.py`, `registry/lineage.py`, `sdk/resume.py`, `sdk/run_states.py`, `sdk/reader.py`. Part B, vmn-exp package: `ui/app_deps.py`, `ui/server.py`, `ui/leaderboard_cache.py`, `ui/leaderboard_delta.py`, `ui/leaderboard_live.py`, `ui/job_rollup_cache.py`, `ui/job_views.py`, `ui/attention.py`, `ui/metrics_feed.py`, `ui/routes_shell.py`, `ui/routes_lineage.py`, `ui/search_rank.py`, `ui/search_index.py`, `ui/store_upkeep.py`, `ui/readers/baselines.py`, `ui/readers/experiment_detail.py`, `ui/readers/last_good_index.py`, `ui/experiment_source.py`, `ui/index.py`, `ui/elected_index.py`, `ui/cache_resync.py`, `ui/cache_rebuild.py`, `ui/report_index.py`, `ui/cache_pg.py`, `cli/views.py`, `cli/experiment.py`, `cli/compact.py`, `cli/migrate.py`, `cli/prune.py`, `cli/rerun_report.py`, `cli/similar_hint.py`, `cli/similar_backfill.py`, `cli/pushing/` (the moved push_rename). Tests: the 95 patching files, the 21 files with direct status calls, `packages/vmn-exp/tests/unit_deps.py`, `packages/vmn-exp/tests/io_boundary_known.py`. Docs: `docs/vmn-exp/experiments.md`, `docs/vmn-exp/upgrading.md` (created by plan 43 F9).

**Risk.** Status is the product's most visible derived value. A caller that captures `now` once per long-lived object instead of per derivation would delay `stuck`; a Part B test pins per-build reads. The process-wide `_SHARED` registry returns the first index built for a store, so the first caller's clock is the one that index keeps; production has one clock per process, and tests that need a fake clock build `ExperimentIndex` directly or reset `_SHARED` as they do today. Commit 2 is the single largest test-touching change in the plan (119 sites plus 53 call edits, about 110 files); it stays reviewable only if it is purely mechanical, so any test that needs more than a different way of supplying time is taken out of the commit and handled on its own with a note. Whether `IndexSnapshot.status_of` gaining a `now` parameter costs anything measurable on the board path cannot be settled by reading: run the G17 benchmark list before and after commit 3. Snapshots built by `direct_snapshot` and `snapshot_of_folds` have no index; their callers pass `now` to `status_of` like everyone else. Plans 38 and 39 add status callers (A5 adoption, B3 sorted list); they must take `now` from io from the start, and the commit-3 ratchet test catches one that does not. `derive_status` is named in docs/vmn-exp/experiments.md:267, so a user script may call it without `now`; after commit 3 that call raises `TypeError`. `vmn_exp.core.status` is not exported by `vmn_exp.sdk` and sdk.md does not document it, so this plan treats the change as a behaviour change with an `upgrading.md` row and no deprecation window. Whether plan 43 F9's window (warn first, remove later) applies to it cannot be settled by reading and is listed for the owner; if it does, commit 3 keeps `now=None` on `derive_status` alone, warning and reading the real clock, until the window has passed. Threading `clock` through module-level functions (core/refs.py, core/index_list.py, core/similar_search.py, core/sweep/summary.py, registry/lineage.py, sdk/reader.py) changes their signatures; grep each for direct test callers at start and add `clock=` there in commit 2 (argument-only, covered by this item's approval). The index helper process's `main()` and the list-2 defaults build real IO outside the entry points the approved CLAUDE.md bullet names (see [CLAUDE.md lines](#claudemd-lines)).

**Owner decision (2026-11-11).** Part B is approved and is in this plan: the mechanical migration of the 119 `monkeypatch.setattr(<module>, "_now"|"_monotonic"|"_wall"|"_clock", ...)` sites to FakeClock, and the 53 direct-call edits, staged as above after G4, G7 and G10.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/core/status.py:88-89 (_now falls back to datetime.now)`; `packages/vmn-exp-sdk/src/vmn_exp/core/status.py:190,213,253 (last_alive_at / derive_status / status_fields take now=None)`; `AST scan of both src roots at HEAD: 32 calls of the three functions, 6 pass now (status.py:209,250,263; core/alerts/transitions.py:62,154; core/tree.py:223)`; `direct reads of experiment_status._now(): ui/leaderboard_cache.py:367, ui/job_rollup_cache.py:36,83,159, ui/attention.py:38, ui/metrics_feed.py:39, ui/routes_shell.py:102,116, core/tree.py:221, core/query_ago.py:25`; `packages/vmn-exp/src/vmn_exp/ui/leaderboard_cache.py:105-111 (_status(snapshot, row) calls status_fields with no now); 312-314 (LeaderboardCache constructor, no clock)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index_snapshot.py:163-167 (IndexSnapshot.status_of)`; `packages/vmn-exp/tests/test_ui_experiment_status.py:328 (monkeypatch.setattr(status_mod, "_now", lambda now=None: now or later))`; `AST scan of packages/vmn-exp/tests at HEAD for setattr/patch targets: core.status._now 89 sites/74 files; core.index._monotonic 11/11; core.similar_match._clock 5/2; core.index_sweep._wall 4/4; core.index_freshness._wall 3/2; cli.similar_hint._clock 3/2; core.index_store_conn._monotonic 2/1; core.index_store._now 2/2; sdk.sysmetrics._clock 2/1; index_bulk and index_relist aliases are not patched`; `the ten aliases: core/index.py:123, core/index_bulk.py:24, core/index_store_conn.py:36, core/index_sweep.py:93, core/index_freshness.py:29, core/index_relist.py:51, core/index_store.py:41, core/similar_match.py:33, sdk/sysmetrics.py:79, packages/vmn-exp/src/vmn_exp/cli/similar_hint.py:59`; `packages/vmn-exp-sdk/src/vmn_exp/core/index.py:143-147,155,163 (ExperimentIndex builds IndexStore, Freshness, Sweep, BulkPublish and Unreadable itself: the place its clock fans out)`; `packages/vmn-exp-sdk/src/vmn_exp/core/metric_stream.py:64, core/output_log.py:112, core/index_vmx_check.py:110, core/gc_policy.py:37-38, core/alerts/dispatch.py:42, storage/journal.py:176, reports/index.py:56 (the 8 real defaults, re-scanned at HEAD)`; `grep of both src roots at HEAD for the list-2 names (the site lists in Approach)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index_io_process.py:137,305 (the helper is started as its own interpreter and has a main())`; `docs/vmn-exp/experiments.md:267 (names vmn_exp.core.status.derive_status(state, observed_at=...)); no other file under docs/ or README.md names derive_status or status_fields`; `packages/vmn-exp/src/vmn_exp/ui/store_upkeep.py:53,151,157 (the derive_status call is in AppUpkeep, which StoreUpkeep builds)`; `core/status.py and core/index.py are unchanged between 25f03f3d and HEAD`

<a id="g12"></a>
### G12. Environment variables read through an injected Env, staged ui -> cli -> sdk

P2 · L · depends on G2, G7, G10; stage B after G15, stage C after G17

**Problem.** 74 direct os.environ / os.getenv uses in 39 files (ui 9/7, cli 14/6, sdk 51/26). Writer-id resolution, offline mode, stale thresholds, host cache directories and kill grace read the process environment wherever they run.

**Approach.**

`Env` is a read-only Mapping (real: os.environ, a live view). Stage A, ui (S): handle_ui, build_server, server_app, ui/config.py, diag_cli take `env` from the root (G7's io); the `env=None -> os.environ` fallbacks are deleted. Stage B, cli (M): handle_experiment, _resolve_parent, experiment_create, plugin.py, login.py and the run.py helpers take `io.env`. Stage C, sdk (L): start_run passes `env` to create/resume/release/mode/ranks, sysmetrics.sdk_enabled, storage_resolve, host_dirs, alerts config and writer.py's get_writer_id / offline_mode / merge_env_into_params; positive_env_sec takes env. Env writes stay in roots and on REAL_IO with a reason: sdk/context.py (exports VMN_EXPERIMENT_ID for child processes) and cli/experiment.py:264 (exports the conf writer id). `_base.resolve_root_path` and `_base.get_repo_lock` are NOT changed here: they are copies kept identical to vmn's and change in the same commit as plan 35 changes the originals.

**Tests first.**

- packages/vmn-exp/tests/unit/test_env_ui.py: test_token_comes_from_the_given_env; test_server_config_reads_only_the_given_env
- packages/vmn-exp/tests/unit/test_env_cli.py: test_parent_defaults_to_VMN_EXPERIMENT_ID_of_the_given_env; test_from_snapshot_env_skips_auto_init; test_kill_grace_env
- packages/vmn-exp/tests/unit/test_env_writer.py: test_writer_id_priority_env_then_conf_then_hostname (FakeEnv + FakeHost); test_offline_mode_reads_the_given_env; test_env_params_fill_only_missing_keys
- packages/vmn-exp/tests/unit/test_env_status.py: test_min_stale_sec_from_the_given_env_and_default
- packages/vmn-exp/tests/unit/test_env_host_dirs.py: test_cache_dir_env_overrides_the_default
- G1 allowlist: env entries removed per stage; sdk/context.py listed in REAL_IO with its reason

**Files.** `packages/vmn-exp/src/vmn_exp/ui/cli.py`, `packages/vmn-exp/src/vmn_exp/ui/config.py`, `packages/vmn-exp/src/vmn_exp/ui/diag_cli.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment.py`, `packages/vmn-exp/src/vmn_exp/cli/plugin.py`, `packages/vmn-exp/src/vmn_exp/cli/login.py`, `packages/vmn-exp/src/vmn_exp/cli/run.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/writer.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/status.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/storage_resolve.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/alerts/config.py`, `packages/vmn-exp-sdk/src/vmn_exp/storage/host_dirs.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/resume.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/release.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/mode.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/ranks.py`

**Risk.** `get_writer_id` is called 20 times in 8 test files with no arguments and its result is cached in a module global; the injected form is added as the function's required parameter only where callers have an env, and the cache's first-resolution timing must not change. Tests use monkeypatch.setenv in 156 files; they keep working because roots still read the real environment. Plan 41 D10's `vmn_exp.sdk.resolve_storage` is a thin SDK entry point (G10), so core/storage_resolve.py may take `env` as a required parameter. After G15 the `cli/experiment.py` lines under Evidence are in the modules G15 names; stage B follows the code. Plan 38 A4 and A5 add `--no-adopt`/`VMN_EXP_ADOPT` and plan 40 C5/C7 add env reads (`VMN_EXP_CACHE_DIR`, the finalize budget); they are read through the same `env`. Stage C threads a parameter through many module-level functions: one worktree per subpackage (sdk/, core/, storage/ are disjoint), and never an `env=os.environ` default.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/core/writer.py:66,87-89,109,120-121,328 (7 reads; `_WRITER_ID` module cache)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/context.py:107,153,157-158,166-168 (reads and writes the exported run env)`; `packages/vmn-exp-sdk/src/vmn_exp/_base.py:136,150 (VMN_WORKING_DIR, VMN_LOCK_FILE_PATH)`; `packages/vmn-exp/tests/test_exp_base.py:47-53,61-70 (call _base.resolve_root_path() and _base.get_repo_lock(root) with today's signatures and compare with vmn's)`; `packages/vmn-exp-sdk/src/vmn_exp/core/status.py:131`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:213,262-264,335,432`; `packages/vmn-exp/src/vmn_exp/ui/cli.py:176,284 and ui/config.py:92,215 (env=None falls back to os.environ)`; `packages/vmn-exp/src/vmn_exp/ui/diag_cli.py:60`; `packages/vmn-exp/tests/conftest.py:26-34 (autouse reset of writer._WRITER_ID)`

<a id="g13"></a>
### G13. Ids and tokens from an injected Random

P3 · M · depends on G2, G19; plan 41 D3 and plan 42 E5a land first

**Problem.** About 22 direct uuid/secrets/os.urandom calls (ui: job ids, audit entry ids, API tokens, session ids, OIDC state/nonce/verifier, probe keys, tenancy external ids; sdk: stream ids, attempt ids, report and comment ids, buffer dir names) make outputs non-deterministic in tests. CLAUDE.md lists randomness/uuid as IO.

**Approach.**

Classes that already receive a clock in G19 take `random` beside it (AuditLog, TokenService, SessionService, OIDCAuthenticator, DeviceFlow); the probe-key and tenancy helpers take it as a parameter from their route's context. SDK side: the attempt-id, stream-id, report-id and comment-id functions take `random` from their caller's root. The real implementation is backed by `secrets` for every method; report and comment ids are derived from `token_bytes` with their existing alphabet and length. The two module-level nonces are per-process cache salts and go on REAL_IO with that reason. Seeded `random.Random(seed)` is deterministic and untouched.

**Tests first.**

- packages/vmn-exp/tests/unit/test_random_ui.py: test_api_token_id_and_secret_come_from_random_and_keep_their_lengths
- test_random_ui.py: test_session_id_comes_from_random
- test_random_ui.py: test_audit_entry_id_is_time_key_plus_random_suffix
- test_random_ui.py: test_oidc_state_nonce_and_verifier_come_from_random
- packages/vmn-exp/tests/unit/test_random_sdk.py: test_attempt_id_is_12_hex_chars_from_random; test_report_id_is_r_plus_12_base32_chars; test_comment_id_keeps_its_prefix_and_length

**Files.** `packages/vmn-exp/src/vmn_exp/ui/audit.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/tokens.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/sessions.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/device.py`, `packages/vmn-exp/src/vmn_exp/ui/tenancy.py`, `packages/vmn-exp/src/vmn_exp/ui/storage_access.py`, `packages/vmn-exp/src/vmn_exp/ui/onboarding_probe.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/streams.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/state_cas.py`, `packages/vmn-exp/src/vmn_exp/reports/store.py`, `packages/vmn-exp/src/vmn_exp/reports/comments.py`

**Risk.** Security: a predictable generator must never reach production. Contained by building Random only in real_io(), by the G2 contract test that the real one is secrets-backed, and by FakeRandom living only under tests/. Token formats and lengths must not change (stored tokens and sessions stay valid); every test pins them. Value is low (determinism only); it is in the plan because the rule names randomness, and it rides on G19's constructor changes rather than making its own.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/audit.py:37`; `packages/vmn-exp/src/vmn_exp/ui/auth/tokens.py:61`; `packages/vmn-exp/src/vmn_exp/ui/auth/sessions.py:26`; `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py:47,94 and ui/auth/device.py:47`; `packages/vmn-exp/src/vmn_exp/ui/storage_access.py:36, ui/onboarding_probe.py:69, ui/tenancy.py:92`; `packages/vmn-exp-sdk/src/vmn_exp/core/streams.py:44, core/state_cas.py:56`; `reports/store.py:36 (secrets.choice over a base32 alphabet), reports/comments.py:48 (os.urandom(10)); under packages/vmn-exp-sdk at HEAD, under packages/vmn-exp/src/vmn_exp/reports/ after plan 41 D3`; `packages/vmn-exp-sdk/src/vmn_exp/storage/buffered.py:54 (buffer dir name; moved by plan 40 C5, which may leave nothing random here)`; `packages/vmn-exp/src/vmn_exp/ui/leaderboard_cache.py:104 and ui/settled_subtree.py:21 (module-level per-process nonces)`

<a id="g14"></a>
### G14. Filesystem: declare the real Storage implementations, then move logic-side file access behind the FileSystem port

P3 · XL (step 1: S; step 2: L, after plan 35 stage 4) · depends on G1, G2

**Problem.** About 375 filesystem calls (os fs 283, open 60, shutil/tempfile 32) plus up to 113 Path-method calls. Roughly half are in the modules that implement the SnapshotStorage port for a local directory and are legitimately real IO. The rest is logic mixed with file access: ui/diag_cli.py (29 sites, including polling for a dump), ui/workspaces.py (15), cli/rerun_workdir.py (21), cli/migrate_tree.py (18), importers/mlflow_filestore.py (20), core/env.py (12).

**Approach.**

`SnapshotStorage` (storage/base.py:44) is the filesystem interface for store data. Logic reaches a store only through it; its local implementation is real IO by definition and is not put behind a second port.

Step 1 (S, no production change): put the local Storage implementation modules on G1's REAL_IO list, each with its reason:

| Module | Reason it is real IO |
|---|---|
| `storage/local.py` | the local-disk SnapshotStorage backend itself |
| `storage/local_metrics.py` | its metric streams: `O_APPEND` writes to `metrics/<stream>.vms` |
| `storage/local_streams.py` | picks the stream file a local record copy appends to |
| `storage/files.py` | atomic write (temp + rename) and patch-file helpers shared by the backends |
| `storage/store_marker.py` | `store.yml` create-if-absent (`O_EXCL`-style link) at the store root |
| `storage/listing.py` | directory listings of local records (`scandir`/`stat`), the cost the index is built around |
| `storage/child_markers.py` | empty `children/<verstr>` marker objects in a parent's record |
| `storage/children_flag.py` | the `.children_complete` flag file beside an app's records |
| `storage/ship_state.py` | per-record ship state shared by the copy's processes (file + lock) |
| `storage/host_dirs.py` | resolves and creates the per-host cache and state dirs |
| `storage/s3.py` (download paths only) | writes downloaded objects to local files |
| `storage/buffered.py` | the local log buffer directory of a direct-to-bucket run; its clock is injected (G10), its files are not |
| `storage/buffer_owner.py`, `storage/buffer_state.py` | added by plan 40 C5 and C13: the buffer's owner lock and its kept final state; listed when they exist |
| `core/sqlite_conn.py` | the one SQLite connection policy (CLAUDE.md invariant) |
| `core/sqlite_files.py` | rebuilds a SQLite cache file under its readers (rename, link) |
| `core/index_io_process.py` | a helper process whose whole job is the index's filesystem work; also a process root (G11) |

They stay tested on tmp_path, which needs no Docker. An entry is per module and carries a count cap like every allowlist entry, so real IO cannot grow inside an exempt module unnoticed.

Step 2 (L, only after plan 35 stage 4 provides `MemFS` and its contract test in tests/fakes/): add the same `FileSystem` Protocol to vmn_exp/core/ports.py (and the parity test covers it) and migrate the logic-side modules by value:
1. ui/diag_cli.py first (clock + fs + a `signal_process` callable: removes real sleeps and a helper process from test_ui_diag_cli.py).
2. ui/workspaces.py: `WorkspaceManager(data_dir, ...)` is a list-2 name (150 constructions in 125 test files) and keeps its signature as the real-wired form; the logic moves to an inner class taking `fs` and a `clone` callable.
3. cli/rerun_workdir.py, cli/migrate_tree.py, core/env.py.
4. importers/mlflow_filestore.py reads a foreign tree with pathlib and is last.

`_base.sha256_file` / `resolve_root_path` follow plan 35, not this item.

**Tests first.**

- packages/vmn-exp/tests/test_io_boundary.py: test_real_io_entries_name_existing_modules_and_carry_a_reason (step 1; already in G1, extended list); test_no_ui_or_cli_module_is_on_the_real_io_list_as_storage (only `storage/` and the three `core/` modules above may carry a storage reason)
- packages/vmn-exp/tests/unit/test_storage_is_the_fs_port.py: test_a_record_written_through_the_storage_port_reads_back_on_the_in_memory_bucket_fakes (step 1's unit test on fakes: the same SnapshotStorage calls pass on tests/object_store_fakes.py with no local store directory, which is what makes the port, not the local module, the interface)
- packages/vmn-exp/tests/unit/test_diag_cli_unit.py: test_pid_mode_signals_then_returns_the_new_dump (MemFS + FakeClock; the dump appears after two polls)
- test_diag_cli_unit.py: test_pid_mode_times_out_without_real_waiting
- test_diag_cli_unit.py: test_url_mode_writes_the_default_timestamped_name_from_the_clock
- packages/vmn-exp/tests/unit/test_workspace_manager_unit.py: test_failed_clone_removes_the_directory_it_created; test_failed_clone_keeps_a_directory_that_existed; test_clone_into_a_non_empty_path_is_refused; test_remove_deletes_only_managed_checkouts
- packages/vmn-exp/tests/unit/test_rerun_workdir_unit.py and test_migrate_tree_unit.py: one test per branch of the copy/move logic on MemFS

**Files.** `packages/vmn-exp/tests/io_boundary_known.py`, `packages/vmn-exp/tests/unit/test_storage_is_the_fs_port.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/ports.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/real_io.py`, `packages/vmn-exp/src/vmn_exp/ui/diag_cli.py`, `packages/vmn-exp/src/vmn_exp/ui/workspaces.py`, `packages/vmn-exp/src/vmn_exp/cli/rerun_workdir.py`, `packages/vmn-exp/src/vmn_exp/cli/migrate_tree.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/env.py`

**Risk.** Lowest value per line changed: 555 exp test files already run on tmp_path without Docker, so the gain is consistency with the rule more than speed. Step 1 is done now; step 2 waits for plan 35's MemFS so the fake and its contract test are written once, and plan 35 is still only proposed, so step 2 has no date. Splitting WorkspaceManager into a wrapper plus an inner class is a real abstraction cost and should be cut if diag_cli turns out to be the only module whose tests get faster. `SnapshotStorage` exposes real paths in two methods (`local_record_dir`, `artifact_local_path`); callers that use those paths do file IO outside the port and stay counted by the ratchet in their own modules.

**Owner decision (2026-11-11).** `SnapshotStorage` is the filesystem interface for store data. The local storage implementation modules in the table are exempt from the IO ratchet, with the reason given for each.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/storage/base.py:44 (SnapshotStorage ABC: the existing port)`; `packages/vmn-exp-sdk/src/vmn_exp/storage/base.py:239,252 (local_record_dir / artifact_local_path expose real paths; line numbers re-read at HEAD after upstream's +11 lines)`; `module docstrings of the files in the table (read at HEAD) for each reason`; `packages/vmn-exp/tests/object_store_fakes.py:1-5,50,113 (in-memory bucket fakes already exist; storage on them needs no filesystem)`; `packages/vmn-exp/src/vmn_exp/ui/workspaces.py:52-66,92 (WorkspaceRegistry is already an interface with Yaml and Db implementations)`; `packages/vmn-exp/src/vmn_exp/ui/workspaces.py:74,88,111,166,170,228 (open, constructor, git.Repo.clone_from, shutil.rmtree)`; `packages/vmn-exp/tests (WorkspaceManager(...) is constructed at 150 sites in 125 test files)`; `docs/plans/35-core-io-behind-interfaces.md:88 (core stage 4: MemFS + contract test)`

<a id="g15"></a>
### G15. Split cli/experiment.py (1227 lines) by command

P3 · M · depends on G18; plan 39 B2, B3, B5a, B5b and B6 land first

**Problem.** One file holds dispatch, storage resolution, auto-init, create/add, and the list, show, compare, diff, restore and export commands with their formatting (42 prints), four times the file-size guideline. The draft said two test patches depend on the module; there are six, on three names, and the moved commands call two of them.

**Approach.**

Pure move in separately landing steps of what plan 39 leaves in the file. Plan 39 creates `cli/list_layout.py` (B3) and `cli/compare_view.py` (B6) first; this item keeps those names and adds no second list or compare module: the rest of the list code (651-770 at HEAD) joins cli/list_layout.py and the rest of compare/diff (962-1158) joins cli/compare_view.py, each split again if it would pass 300 lines. New modules: cli/experiment_show.py (771-960), cli/experiment_create.py (425-609), cli/experiment_export.py (1159-1225). experiment.py keeps the helpers at 129-325, handle_experiment and re-imports the names other modules and tests use. The new modules reach the three patched names through the experiment module at call time (`from vmn_exp.cli import experiment as _exp` inside the function, then `_exp._resolve_experiment_version(...)`), so a patch on vmn_exp.cli.experiment keeps taking effect; handle_experiment's dispatch keeps resolving command functions through the experiment module for the same reason. Each step is preceded by a characterization test for its patched name. The G18 entry is lowered per step.

**Tests first.**

- packages/vmn-exp/tests/unit/test_cli_experiment_layout.py: test_experiment_module_still_exposes_the_names_tests_import (experiment_list, _describe_log_entry, _app_name, READ_ONLY_ACTIONS, _get_experiment_storage, _MetricsTailer, load_run_state, _resolve_experiment_version, _resolve_experiment_bundles; green before and after)
- test_cli_experiment_layout.py: test_patching_resolve_experiment_version_on_the_experiment_module_reaches_show_and_export (green before the move, must stay green)
- test_cli_experiment_layout.py: test_patching_load_run_state_on_the_experiment_module_reaches_show
- test_cli_experiment_layout.py: test_dispatch_resolves_handlers_through_the_experiment_module
- packages/vmn-exp/tests/unit/test_cli_list_format.py: test_format_list_row_columns_and_missing_values; test_status_token_and_lost_text (pure formatting)
- packages/vmn-exp/tests/unit/test_cli_show_format.py: test_describe_log_entry_for_each_entry_type

**Files.** `packages/vmn-exp/src/vmn_exp/cli/experiment.py`, `packages/vmn-exp/src/vmn_exp/cli/list_layout.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment_show.py`, `packages/vmn-exp/src/vmn_exp/cli/compare_view.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment_create.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment_export.py`, `packages/vmn-exp/tests/file_size_known.py`

**Risk.** The call-time lookup through the experiment module is a deliberate wart that exists only to keep six patches working; it is removed when those tests move to injected collaborators. The lazy import also avoids the import cycle (experiment.py imports the new modules, they import it back). CLI output must be byte-identical; the existing CLI tests are the safety net and are not edited. The line ranges are HEAD's (cli/experiment.py is unchanged since the draft) and will have moved after plan 39; re-read the file and cut by function, not by line.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/experiment.py:327 (handle_experiment dispatch)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:425-609 (create/add)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:651-770 (list rows and formatting)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:771-960 (show, status block, log description)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:962-1158 (bundles, compare, diff)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:1159-1227 (restore, export, prune)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:233,550,830,1005,1160,1180 (_resolve_experiment_version defined and used by add, show, compare, restore, export)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:98,782 (load_run_state imported and used by show's _subtree)`; `packages/vmn-exp/tests/test_exp_provenance_cli.py, test_exp_reader.py, test_experiment_nesting.py, test_fix_exp_prune_index.py, test_ui_job_routes.py (patch _resolve_experiment_version, _resolve_experiment_bundles or load_run_state on vmn_exp.cli.experiment)`; `packages/vmn-exp/tests/test_architecture_boundary.py:23-29 (glob `vmn_exp.cli.experiment` already covers experiment_*.py)`

<a id="g16"></a>
### G16. CLI output through a Console port

P3 · L · depends on G7, G15; plan 41 D3 lands first

**Problem.** 182 bare print calls in 38 files (144 in cli/ across 30 files, 20 in registry/cli.py (cli/model_cmd.py after plan 41 D3), 8 in ui, 8 elsewhere), plus 1 input() and 3 sys.std* writes. Formatting logic and output are fused, so formatting is only testable through capsys.

**Approach.**

Handlers get `io.console` from G7 and pass `out` (a callable taking a line) down; functions that build text return lines and one caller writes them. Migrate per file from G15 (list, show, compare, export), then the remaining cli/ files, then cli/model_cmd.py. `login(..., say=print)` loses its default. The real console looks up sys.stdout/sys.stderr at call time so capsys/capfd tests keep passing. Done last so the ratchet's console kind reaches zero outside real_io.py.

**Tests first.**

- packages/vmn-exp/tests/unit/test_cli_console.py: test_list_writes_one_line_per_row_to_the_console (FakeConsole.lines)
- test_cli_console.py: test_show_json_goes_to_out_and_warnings_to_err
- test_cli_console.py: test_run_prints_only_the_verstr_on_stdout (the output contract)
- test_cli_console.py: test_wrong_command_hint_goes_to_err_with_exit_code_2
- packages/vmn-exp/tests/unit/test_ports_contract.py: test_real_console_writes_to_the_current_sys_stdout (replaced after construction, still receives the line)
- packages/vmn-exp/tests/unit/test_model_cmd_console.py: test_model_list_lines

**Files.** `packages/vmn-exp/src/vmn_exp/cli/list_layout.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment_show.py`, `packages/vmn-exp/src/vmn_exp/cli/compare_view.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment_export.py`, `packages/vmn-exp/src/vmn_exp/cli/run.py`, `packages/vmn-exp/src/vmn_exp/cli/main.py`, `packages/vmn-exp/src/vmn_exp/cli/login.py`, `packages/vmn-exp/src/vmn_exp/cli/model_cmd.py`

**Risk.** Scripts parse this output (the run verstr on stdout, `--json` outputs); stdout/stderr routing and trailing newlines must not change. cli/model_cmd.py is reached through `model_run_without_repo(args, io)`; its io comes from the plugin shim like the others (G7). Plan 39 B6 adds `--json` to `compare` and `comments`; those outputs go to `out` whole, with nothing else on stdout.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/experiment.py (42 print calls; e.g. the status block at 790-820)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:309 (print(self.verstr): the output contract of `vmn-exp run`)`; `packages/vmn-exp/src/vmn_exp/cli/main.py:40-45 (print to stderr)`; `packages/vmn-exp/src/vmn_exp/cli/login.py:84 (say=print default: the pattern already in use)`; `docs/plans/35-core-io-behind-interfaces.md:104-107 (core stage 6: console last, lowest value)`

<a id="g17"></a>
### G17. Split core/index.py (1217 lines) into mixin modules behind the ExperimentIndex facade

P2 · L · depends on G18 and G11 Part B

**Problem.** core/index.py is 1217 lines, four times the file-size guideline. `ExperimentIndex` alone is lines 133-1071 (82 methods on 40 fields of state), followed by a process-wide registry and module-level access functions (1078-1217). It is the hottest read path of the product and its refresh state machine was changed for production incidents in plans 23, 27, 29, 33 and 34. Two things make a naive move unsafe:
- Tests replace names on `vmn_exp.core.index` with `monkeypatch.setattr`: `_SHARED` (9 sites), `_REMOTE_CHUNK` (8), `indexed_snapshot` (6), `shared_index` (6), `RETRY_UNREADABLE_SEC` (6), `refresh_record` (6), `FIRST_ROWS` (5), `direct_rows` (3), `update_record` (2), `FIRST_ROWS_MAX`, `kept_parts`, `first_rows` (1 each); 46 test files in all, plus the 11 `_monotonic` sites G11 Part B removes. A method moved to another module reads that module's globals, so a re-export would leave those patches rebinding a name nobody reads.
- `adopt()` (401-421) swaps a dozen private fields between two indexes, and `_lean_copy()` (334-338) builds a second index sharing the store. Splitting the state into collaborator objects would mean redesigning both.

**Approach.**

Split the class into mixins that keep all state on `self`, the pattern the same package already uses (`class Sweep(SweepBehind, SweepRetake, SweepState)`, `class SqliteStore(LeanReads, KeyValues, Rederive)`). `adopt()` and `_lean_copy()` keep working unchanged because no field moves. core/index.py stays the facade: the class statement, the constructor, the module globals tests patch, the few methods that read those globals, and the process-wide access functions.

What moves (line ranges are HEAD's; each new module is under 300 lines):

| New module | Mixin | Methods (today's lines) | About |
|---|---|---|---|
| `core/index_surface.py` | `IndexSurface` | the properties and journal pass-throughs (190-267), `freshness`, `_reported_freshness`, `full_listing_due`, `reconcile` (269-310), `snapshot_now`, `snapshot`, `_revalidate_in_background`, `_revalidate`, `wait_revalidated`, `rows`, `run_states` (1002-1071) | 200 lines |
| `core/index_refresh.py` | `IndexRefresh` | `refresh`, `sync`, `refresh_if_stale`, `_first_load` (314-369), `use_io_process`, `close`, `adopt` (371-421), `_refresh_locked`, `_check_step`, `check_vmx`, `_paused_unless_remote` (423-483), `_refresh_from_storage`, `_serve_first_rows`, `_set_published`, `_drop_folds` (485-550) | 240 lines |
| `core/index_load.py` | `IndexLoad` | the module function `_listed_at` (126-130, used only by `_load_queue`), `_more_relisted`, `_bulk_listing`, `_load_listed`, `_listed_record`, `_load_work` (552-611), `_derive_first`, `_derived` (613-659), `_listing_phase`, `_listing_position` (661-671), `_take`, `_load_queue`, `_unloaded_parents`, `_refresh_part` (673-723) | 190 lines |
| `core/index_publish.py` | `IndexPublish` | `_apply`, `_publish`, `_publish_pending`, `_backlog`, `_loading`, `_number_later` (725-804), `_publish_persisted`, `_refresh_from_cache` (812-835), `_sorted_keys`, `_build_snapshot` (969-1000) | 150 lines |
| `core/index_persist.py` | `IndexPersist` | `_keeps_baseline` (806-810), `_load_records`, `_refresh_and_persist` (837-860), `_persist`, `_mark_puts`, `_save_mark` (866-896) | 80 lines |
| `core/index_read.py` | `IndexRead` | `_refresh_local` (862-864), `_refresh_records`, `_remote_loaders`, `_close_loaders`, `_refresh_all`, `_remote` (898-944) | 80 lines |
| `core/index_direct.py` | (functions) | `_direct_folds`, `_run_states`, `snapshot_of_folds`, `direct_snapshot` (1140-1175), imported back into core/index.py | 50 lines |

What stays in core/index.py (about 280 lines):
- the module docstring, shortened to name the six mixin modules;
- the constants tests patch (`_REMOTE_CHUNK`, `RETRY_UNREADABLE_SEC`, `FIRST_ROWS`, `FIRST_ROWS_MAX`) `_REMOTE_WORKERS` (read by the constructor at 161), and re-imports of the unpatched ones from the module their code moved to (`BEHIND_REFRESH_SEC` and `MIGRATING_PUBLISH_SEC` from index_load.py, `FIRST_SNAPSHOT_WAIT_SEC` from index_surface.py, `_BISECT_NEW` from index_publish.py) and of every name importers use today (`IOProcessError`, `DEFAULT_FULL_SWEEP_SEC`, `IndexSnapshot`, `refresh_record`, `update_record`, `first_rows`, `kept_parts`);
- `class ExperimentIndex(IndexSurface, IndexRefresh, IndexLoad, IndexPublish, IndexPersist, IndexRead)` with `__init__` and `follower` (136-188), `_lean_copy` (it names the class), and the seam methods. A seam method is a one- or two-line method defined in core/index.py whose only job is to read a patched module global at call time, so a patch on `vmn_exp.core.index` still reaches the moved code through `self`:
  - `_chunk()` returns `_REMOTE_CHUNK` (read today at 299, 571, 703, 762, 783, 793; the moved code calls `self._chunk()`);
  - `_retry_sec()` returns `RETRY_UNREADABLE_SEC` (431, 952);
  - `_newest_rows()` stays whole (528-531: reads `FIRST_ROWS`, `FIRST_ROWS_MAX`, `first_rows`);
  - `_kept_parts()` wraps `kept_parts` (635);
  - `_refresh_one()` and `_update()` stay whole (946-967: read `refresh_record`, `update_record`);
- the process-wide access functions, unmoved, because they call each other through this module's globals and that is exactly what the tests patch: `_SHARED`, `_SHARED_LOCK`, `shared_index`, `_process_index`, `direct_rows`, `indexed_snapshot`, `indexed_status_rows` (1078-1137, 1178-1217). ui code reaches them as `experiment_index.shared_index(...)`, so those patches keep working too.

The logger keeps its name: every new module logs through `logging.getLogger("vmn_exp.core.index")`, not `__name__`, because three test files filter captured records by that name and two of the three `_LOGGER` calls move (`check_vmx` at 462 to index_refresh.py, `_revalidate` at 1049 to index_surface.py).

Tests also patch methods on the class (`ExperimentIndex._refresh_locked`, `_refresh_from_storage`, `refresh`, `snapshot`, `published`, `use_io_process`); a `setattr` on the subclass shadows the mixin's method and pytest removes it again, so they need no change.

The clock: after G11 Part B the index holds `self._clock` and the `_monotonic` alias is gone, so the moved methods read time through `self` and no time seam is needed. That is why this item is sequenced after Part B; doing it first would add a tenth seam method only to delete it.

Steps, each its own commit, each a pure move that keeps every existing test green and lowers the G18 entry:
0. The characterization tests below, green on today's file.
1. `index_direct.py` (functions) and `index_surface.py`.
2. `index_persist.py` and `index_read.py`.
3. `index_publish.py`.
4. `index_load.py`.
5. `index_refresh.py`; the G18 entry for core/index.py is removed (under 300).

Before step 1 and after step 5, run the benchmark list below on the same machine and record both sets of numbers in the commit message of step 5. No test file is edited: the seam methods exist so that none has to be.

**Tests first.**

Characterization tests, written at step 0 and green before any move (packages/vmn-exp/tests/unit/test_core_index_layout.py, on fakes: an in-memory storage stub with `list_files`/`load_file`, tmp_path for the SQLite file, FakeClock):
- test_core_index_still_exposes_the_names_importers_use (ExperimentIndex, shared_index, indexed_snapshot, indexed_status_rows, direct_rows, direct_snapshot, snapshot_of_folds, IOProcessError, FIRST_ROWS, FIRST_ROWS_MAX, `_REMOTE_CHUNK`, `_REMOTE_WORKERS`, RETRY_UNREADABLE_SEC, refresh_record, update_record, kept_parts, first_rows, `_SHARED`)
- test_every_name_tests_patch_on_core_index_is_read_inside_core_index (the guard: an AST scan of packages/vmn-exp/tests collects every name set on `vmn_exp.core.index` by `setattr`/`patch`, and asserts three things. Each name is bound at module level in core/index.py. No other `core/index_*.py` module that core/index.py imports a mixin or function from loads a global of that name, so a moved reader fails it. Each name except `direct_rows` is loaded inside a function body of core/index.py; `direct_rows` has no reader inside core/index.py today, its callers reach it as a module attribute from other modules)
- test_index_warnings_are_logged_as_vmn_exp_core_index (a failing vmx check and a failing background revalidation each log under the name "vmn_exp.core.index")
- test_patching_remote_chunk_on_core_index_changes_the_load_chunk_size
- test_patching_retry_unreadable_sec_on_core_index_changes_when_a_failed_record_is_reread
- test_patching_refresh_record_on_core_index_reaches_a_refresh
- test_patching_update_record_on_core_index_reaches_a_refresh
- test_patching_first_rows_on_core_index_bounds_what_snapshot_now_serves
- test_shared_index_registry_is_one_object_per_process
- test_patching_the_registry_through_core_index_isolates_a_test (`_SHARED` replaced by `{}` gives a new index)
- test_patching_shared_index_on_core_index_reaches_indexed_snapshot
- test_experiment_index_public_surface_is_unchanged (the sorted public attribute names of the class equal a golden list captured at step 0)
- test_no_index_method_is_defined_by_two_bases (MRO check over the mixins)
- test_adopt_serves_the_other_indexes_records_and_keeps_its_own_hints
- test_a_lean_copy_shares_the_store_and_builds_no_snapshot

Size: G18's test_no_file_exceeds_its_recorded_size, with core/index.py's entry lowered per step and removed at step 5, and no new module listed.

Existing tests that must stay green unedited: the 161 test files that import `vmn_exp.core.index` (among them test_fix_index_incremental.py, test_fix_index_snapshot.py, test_fix_index_wiring.py, test_index_first_rows_trees.py, test_index_upgrade_first_publish.py, test_index_store_throttled.py, test_ui_warm_first_rows.py, test_reader_indexing.py, test_listing_loading.py).

Benchmarks that must not regress (all exist today; a move changes no algorithm, so any change beyond run-to-run noise is a bug in the move):
- serial timing benchmarks (`@pytest.mark.serial`, run by `run_pytest.sh`'s one-process pass and the CI `tests_exp_serial` pass): test_index_warm_first_rows_bench.py (`FIRST_ROWS_SEC = 0.3`), test_index_warm_restart_bench.py (`RESTART_SEC = 1.0`), test_index_upgrade_first_publish_bench.py (`FIRST_PUBLISH_SEC = 0.5`), test_index_cold_load_bench.py (first publish within 15 s, 200 runs/s sustained on a remote store), test_ui_cold_index_routes.py (`PROMPT_SEC = 3.0` per route while a cold index loads), test_scale_targets.py (20k-run targets per command; the 100k targets with `VMN_SCALE_BENCH=1`, run once before step 1 and once after step 5);
- work-count benchmarks (not timing, so they run in the parallel pass): test_fix_index_bench.py, test_fix_index_refresh_bench.py, test_fix_index_refresh_scale.py (per-record work bounded by what changed);
- the UI load harness: `VMN_UILOAD_PROFILE=smoke python -m pytest -s packages/vmn-exp/tests/test_uiload_profile.py` in CI's serial pass, and `python packages/vmn-exp/tests/uiload/run.py check --profile load` once before step 1 and once after step 5 (packages/vmn-exp/tests/uiload/README.md).

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/core/index.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/index_surface.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/index_refresh.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/index_load.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/index_publish.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/index_persist.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/index_read.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/index_direct.py`, `packages/vmn-exp/tests/unit/test_core_index_layout.py`, `packages/vmn-exp/tests/file_size_known.py`, `packages/vmn-exp/tests/io_boundary_known.py`, `docs/vmn-exp/architecture.md` (the index section names the modules)

**Risk.** This is the hottest read path; the mitigation is that every step is a pure move with the guard test, the benchmark list and 161 unedited test files behind it. A seam method adds one Python call where a global was read (`self._chunk()` on the load path, a handful of times per chunk, never per row); the benchmarks above are what confirms it is not measurable. Method resolution: a name defined by two mixins would silently pick one; the MRO test rejects it. The guard test's first version would have failed on today's file for `direct_rows` (patched in 3 sites, called from no function in core/index.py), which is why it is exempted by name; a second such name appearing later must be added to the exemption with its reason, not silently skipped. `core/index_io_process.py` builds an `ExperimentIndex` in the helper process and calls `_refresh_and_persist` on it; it imports the class from core/index.py, which keeps working. The seam methods are a deliberate wart that exists to keep 46 test files' patches working; they go when those tests move to constructor parameters (a chunk size, a retry interval, a record reader), which is not in this plan because those test edits are not named here. Plan 41 D1's start_run import budget: core/index.py is imported by sdk/reader.py, so the six new modules are on a reader import path; if D1's budget counts them, it is raised in the commit that adds each, naming the module. `index_surface.py` at about 200 lines and `index_refresh.py` at about 240 are estimates from today's line ranges plus imports; if `index_refresh.py` comes out over 300, `use_io_process`/`close`/`adopt` (371-421) go to their own `core/index_handover.py`.

**Owner decision (2026-11-11).** The core/index.py split is in this plan, after the clock migration (G11 Part B), designed around the module-global patches so that no test is edited, with the benchmarks above as its gate.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/core/index.py:133-179 (constructor: 40 fields)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index.py:334-338 (_lean_copy builds a second ExperimentIndex on the same store); 401-421 (adopt swaps _records, _order, _stamps, _rows, _sweep, _bulk, _store, _unsaved, _cold, _baseline, _mark)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index.py:104-123 (the module constants and the _monotonic alias)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index.py:299,571,703,762,783,793 (_REMOTE_CHUNK reads); 431,952 (RETRY_UNREADABLE_SEC); 530-531 (FIRST_ROWS, FIRST_ROWS_MAX, first_rows); 635 (kept_parts); 955,967 (refresh_record, update_record)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index.py:1078-1115 (_SHARED, _SHARED_LOCK, shared_index, _process_index); 1117-1217 (direct_rows, snapshot_of_folds, direct_snapshot, indexed_snapshot, indexed_status_rows)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index_sweep.py:108 and core/index_store.py:56 (the mixin pattern already used by the index's own helpers)`; `AST scan of packages/vmn-exp/tests at HEAD: 13 names patched on vmn_exp.core.index in 46 files (counts in Problem); class-level patches on ExperimentIndex: _refresh_locked x3, refresh x4, published x2, use_io_process x2, snapshot x1, _refresh_from_storage x1`; `packages/vmn-exp/tests/test_exp_point_resolve.py:57 (monkeypatch.setattr(experiment_index, "_SHARED", {}))`; `packages/vmn-exp/tests/test_fix_index_wiring.py:101 (monkeypatch.setattr(experiment_index, "shared_index", broken))`; `packages/vmn-exp/tests/test_ui_experiment_status.py:327 (monkeypatch.setattr(index_mod, "direct_rows", _boom))`; `packages/vmn-exp/src/vmn_exp/ui/index.py:40,52,112 and ui/experiment_source.py:173 (production reaches shared_index through the module attribute)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index_io_process.py:258 (ExperimentIndex built in the helper process)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index.py:101 (_LOGGER = logging.getLogger(__name__)); 462,1049,1201 (its three uses)`; `packages/vmn-exp/tests/test_index_remote_workers_throttled.py:73, test_index_store_throttled.py:76,80, test_ui_warnings_name_the_record.py:33,36 (caplog filtered by the logger name "vmn_exp.core.index")`; `packages/vmn-exp-sdk/src/vmn_exp/core/index.py:126,703 (_listed_at defined and its one use); 161 (_REMOTE_WORKERS read in the constructor); 1117 (direct_rows defined; no call inside the file)`; `packages/vmn-exp-sdk/src/vmn_exp/core/ (48 index_*.py helper modules exist; none is named index_surface, index_refresh, index_load, index_publish, index_persist, index_read or index_direct)`; `packages/vmn-exp/tests/test_index_warm_first_rows_bench.py:15,34, test_index_warm_restart_bench.py:15,30, test_index_upgrade_first_publish_bench.py:17,37, test_index_cold_load_bench.py:21-23,79, test_ui_cold_index_routes.py:21,107, test_scale_targets.py:25,171-190, test_uiload_profile.py:13-16 (the benchmarks and their limits)`; `tests/run_pytest.sh:129-142 and ci/pipeline.py:150-152 (the serial pass)`; `core/index.py is unchanged between 25f03f3d and HEAD`

<a id="claudemd-lines"></a>
## CLAUDE.md lines

Approved by the owner on 2026-11-11. Each is added by the item named, in that item's commit.

G7 or G10, whichever lands first, adds this bullet directly after the "Production wires the real implementations in the entry point ..." bullet in "IO behind interfaces (dependency injection)" (CLAUDE.md:44):

```
- vmn-exp has two more kinds of entry point that build real IO (`vmn_exp.core.real_io.real_io()`), because neither is handed one: the command handler shims in `vmn_exp/cli/plugin.py` (one `real_io()` per invocation, until core vmn passes `vmn_ctx.io`), and the public functions of `vmn_exp.sdk` (`start_run` and the other functions `vmn_exp/sdk/__init__.py` exports or docs/vmn-exp/sdk.md documents; a library has no main). Everything they call takes its IO as a parameter.
```

G3 adds this line to the first "Running Tests" code block, after the `./packages/vmn-exp/tests/run_pytest.sh` line:

```
./tests/run_pytest.sh --suite exp-unit       # packages/vmn-exp/tests/unit: fakes only, no Docker, no real sleep or subprocess
```

and this sentence after the "Two suites" list:

```
New vmn-exp behaviour gets its first test in `packages/vmn-exp/tests/unit/` (shared fakes in `tests/fakes/`); a guard there fails a test that sleeps, spawns a process or asks for `app_layout`.
```

G2 adds no CLAUDE.md line. When plan 35 stage 0 lands and the shims switch to `vmn_ctx.io`, the first half of the bullet is removed in that commit.

Not covered by the approved wording, and therefore not added without the owner: two more places build real IO in this plan. The index helper process's `main()` (core/index_io_process.py, G11) is a process entry point in the sense of the existing rule ("the real one is chosen in main"), but the bullet above does not name it. The list-2 names (G4) resolve an omitted clock to the real one, which the rule forbids in new code. If the owner accepts both, the bullet gains: "; the index helper process's `main()` in `vmn_exp/core/index_io_process.py` is a third. The names in `REAL_WIRED` (packages/vmn-exp/tests/io_boundary_known.py) fall back to real IO when called without it; production never calls them that way."

## Dropped

Nothing in this workstream is dropped: no owner decision removes an item, and none of the 26 upstream commits since 25f03f3d did any of this work (checked item by item against `git diff 25f03f3d..HEAD -- packages/*/src`). Upstream added direct IO instead (ui/registry_snapshot.py), which G19 step (f) now covers.

## Review findings corrected or dropped

- **Finding 2: 'only ~14 of 301 files take an injected clock/env/fs' in vmn-exp-sdk** Direction right, number low. A name-based AST scan finds 39 sdk-package files (and 43 vmn-exp files) with a parameter named clock/now/sleep/env/fs/http/runner or similar, e.g. core/metric_stream.py:64, core/output_log.py:112, core/gc_policy.py:37-38, storage/journal.py:176, reports/index.py:56. Most still default to the real implementation, which is the actual defect (G11 Part A, G19).
- **Finding 2 worst list: core/writer.py among the worst sdk offenders** core/writer.py has 9 direct sites (7 env reads at 66, 87-89, 109, 120-121, 328, one hostname, one fs call). By count it is behind storage/store_marker.py (24), storage/local_metrics.py (19), storage/files.py (17), storage/listing.py (13), storage/ship_state.py (12), sdk/context.py (11) and storage/host_dirs.py (11). It still matters for env injection (G12).
- **Finding 1 worst list: cli/experiment.py and ui/jobs.py among the worst direct-IO offenders** By non-print IO, cli/experiment.py has 12 sites and ui/jobs.py has 6. cli/rerun_workdir.py (21), cli/migrate_tree.py (18) and importers/mlflow_filestore.py (20) are higher. experiment.py is a size and print problem (1227 lines, 42 prints: G15/G16); jobs.py matters because of what it blocks in tests, not its count (G5).
- **Implied premise: direct filesystem IO is what keeps vmn-exp tests on Docker** Of 1004 test files, 198 use the Docker app_layout fixture and 555 already run on tmp_path. storage/local.py (43 sites) is the real implementation of the SnapshotStorage port (storage/base.py:44) and is tested without Docker today. The cost is time (210 real sleeps in 124 files, about 115 clock patches), subprocesses (93 files) and building the whole app (116 files). The filesystem is therefore last (G14).
- **Finding 3: create_app and core/index.py as undifferentiated monoliths** Both are real by size, but both are already partly decomposed: create_app registers 21 routes_* modules (server.py:750-834) and has 14 inline routes left (not 20 as the draft said); core/ has dozens of index_* helper modules that ExperimentIndex delegates to. G6 finishes the server split; G17 splits the index class along the same lines, as mixins.
- **Finding 1/2 counts taken as exact** They are approximate greps and differ from the AST scan in both directions: ui time calls 47 not ~36; ui real-IO defaults 16 not 19; sdk time 49 not ~43; sdk os filesystem calls 180 not 117; sdk shutil/tempfile 21 not 16; sdk pid/kill 37 not 31. Confirmed as stated: ui subprocess 3, ui environ 9, cli time 15, sdk subprocess 5, cli print 144 (reported 145), sdk environ 51 (reported 52), sdk open 34 (reported 35).
- **Draft premise: the two excluded fixes are still in flight, so G5 and G10 must land after them** Both are already on master: 859da19b 'fix(ui): reject option-like metric names in job actions' and 59becdd5 'fix(sdk): keep the log buffer when the final ship fails'. No sequencing is needed; line numbers in storage/buffered.py and ui/jobs.py cited by the draft were shifted by these commits and are corrected in the items (re-read again at HEAD 59becdd5).

## Non-goals

- Re-planning the two fixes already merged (ui/jobs.py _metric_args; storage/buffered.py _close).
- Core vmn (version_stamp): plan 35 owns it. This plan only requires matching port names and shapes and shares tests/fakes/. `_base.resolve_root_path`, `_base.get_repo_lock`, `_base.now_iso` and `_base.sha256_file` change only together with plan 35's originals, because test_exp_base.py pins them to vmn's behaviour and signatures.
- A big-bang rewrite or a deadline for zero direct IO. The ratchets (G1, G18) make the counts monotone; items land one at a time.
- A FileSystem port under the local Storage implementation (storage/local*.py, files.py, store_marker.py and the other modules G14 lists). They are the real implementation of SnapshotStorage and stay on the permanent list.
- A new in-memory SnapshotStorage fake. Unit tests that need a store use the real storage classes on tmp_path or on the existing in-memory bucket fakes (packages/vmn-exp/tests/object_store_fakes.py).
- Abstracting threading. Thread-owning classes stay thin loops over a tick function that takes a clock; the ratchet counts thread starts so they do not spread, but no Thread port is introduced (JobRunner's `spawn` callable is the one exception, because it is what makes job tests synchronous).
- Injecting os.getpid in sdk/context.py and sdk/fork_safety.py: their pid comparisons exist to detect a real fork and are tested with real forks (plan 30).
- Rewiring ui/diag/gc_pauses.py and ui/diag/latency.py: they instrument the real process through module-level singletons and are exempted with a reason.
- Replacing VMN_LOGGER or routing logging through Console; plan 35 also leaves it a module global.
- Editing or deleting existing Docker or real-subprocess tests beyond the edits this file names. Coverage moves by adding tests; the approved mechanical constructor and clock migrations (G4 list 1, G10, G11 Part B) land in commits that change nothing else.
- Cutting the finalizers out of sdk/run.py, or removing the seam methods G17 leaves in core/index.py: both need test migrations this file does not name (G9, G17).
- The other files over 300 lines not named in the finding (core/query.py, ui/leaderboard_cache.py, core/writer.py, cli/plugin.py, cli/run.py and about 30 more): capped by G18 and split when touched, under the boy scout rule.
- Any change to CLI output, HTTP API, route order, store layout, token formats, or the public start_run / create_app signatures. Two signatures do change: `open_storage` gains one keyword, `clock`, needed only together with `buffer_logs=True` (G10; no doc names that call), and `derive_status`, `status_fields` and `last_alive_at` take a required `now` (G11 Part B, with its `upgrading.md` row).
- The React webui and the uiload harness.

## What the critic changed in the draft

- G11 restructured: the draft's step 1 claimed production callers could start passing `now` while the 85 existing `status._now` patches kept working. They would not: the patches are `lambda now=None: now or T0` (test_ui_experiment_status.py:328 and about 85 sites in 75 files), so a passed real `now` wins and the tests stop asserting anything. Status + alias migration is therefore one staged series (Part B), separate from the small sdk default removals (Part A). Size raised from L to XL, and the 37 call sites corrected to 32 (6 already pass now, counted again at HEAD).
- G17: the draft's 'extract lines 1078-1217 behind re-exports' was rejected. 22 test files setattr `_SHARED`, `shared_index`, `indexed_snapshot` or `direct_rows` on vmn_exp.core.index (e.g. test_fix_index_wiring.py:101); a re-export does not keep those patches effective after a move. The draft's own risk note mentioned `_SHARED` but proposed a test that would not have caught the broken patches. The split now in G17 leaves those functions in core/index.py and guards every patched name with a test.
- G9 narrowed: tests patch compact_by, sync_to_remote, error_from_exception, FINAL_REMOTE_TIMEOUT_SEC and _finalize_signaled on vmn_exp.sdk.run (test_sdk_finalize_bounds.py, test_sdk_detach.py, test_sdk_run_error.py, test_exp_push_metrics.py). The finalizers and constants stay in run.py; the close path moves only with call-time lookups preserved; characterization tests for the patches are written first. run.py lands near 550 lines, not under 350.
- G15 corrected: six patches on three names (not 'two setattr patches'), and the moved commands call two of them; added call-time lookup through the experiment module plus characterization tests.
- G6 corrected: 14 inline routes (not 20); added the existing test that patches ui.server.workspace_storage (test_fix_simplify_read_path.py:245-255) and how ServerContext keeps honouring it.
- G4 split into G4 (root + the five objects create_app actually constructs) and new G19 (remaining clock defaults). The draft said all 16 defaults could be fed from real_deps, but most of those classes are built elsewhere: SettingsCache in experiment_source.py:108, TokenService per request in routes_admin.py:39, FailureStreak in refresher.py/refresh_watch.py, a module-level GcPauses singleton at diag/gc_pauses.py:79. G19 is sized L and exempts the diag singletons.
- G7 wiring replaced: functools.partial binding in register_all(io) cannot rebind because vmn's registry is an append-only list with first-match lookup (plugin_api.py:71-89) and _register skips existing names (plugin.py:482-484), while conftest registers once per process. Replaced by: handlers take io explicitly and the plugin.py shims build real_io() until plan 35 provides vmn_ctx.io.
- G2: added the clock-shape problem the draft skipped. Existing classes take bare callables on three time bases (time.time, time.monotonic, time.perf_counter); pinned `Clock.now()` as an aware UTC datetime (what status needs), kept callable-shaped parameters fed by bound methods from the roots, added token_bytes and a FakeConsole, and listed the three points plan 35 must adopt. The parity test exists from the start rather than being 'added later'.
- G1: scanner must resolve `from time import monotonic` and `import x as y` (core/activity.py:13 and core/traced_lock.py:19 were invisible to the draft's scan), must skip packages/vmn-exp/build/lib, and states that Event.wait/asyncio.sleep are outside it. Priority raised to P1: it is tests-only, small, and the only thing that makes the CLAUDE.md rule enforceable while the rest is negotiated.
- New G18 (size ratchet) replaces the three per-item `files_stay_under_N_lines` tests, which were invented red tests for pure moves; CLAUDE.md treats refactors as keep-green, so characterization tests plus one shrinking size list are the right tool. It also gives finding 3 a ratchet, which the draft lacked.
- G10: `_final_upload_deadline` and `_left` are module-level functions used by the atexit finalizer, so they become Run methods; `open_storage` is called 175 times in 127 test files, so its clock keyword is required only with buffer_logs=True (2 production callers); buffered.py line numbers corrected; unit tests reuse the existing in-memory bucket fakes instead of a new storage fake.
- G12: removed `_base.resolve_root_path` / `get_repo_lock` from the env migration. test_exp_base.py:47-70 calls them with today's signatures and compares with vmn's; they must change together with plan 35. Fixed wrong evidence lines (sdk/context.py reads/writes are at 107 and 153-168, not 21-44; ui/cli.py fallback is 176, ui/config.py 92 and 215).
- G5: evidence line numbers updated after the merged _metric_args fix; new parameters are keyword-only; added the closed-stdin test; size S -> M because git_context and versions_fingerprint are called from routes_shell.py:91 and ui/index.py:143, not from create_app.
- G14: WorkspaceManager is constructed in 123 test files, so the draft's new `WorkspaceManager(data_dir, registry, fs, clone)` signature would break them; it keeps its signature as the real-wired form. Step 2 explicitly waits for plan 35's MemFS and can be cut down to diag_cli if nothing else gets faster.
- G13 kept at P3 but tied to G19's constructor changes and made format-preserving (report ids use secrets.choice over a base32 alphabet, comments use os.urandom; the port needs token_bytes).
- Consolidated the scattered 'may tests be edited' questions into one policy on G4 (small sets: mechanical edits; widely constructed names: keep the name as a real-wired factory), with measured construction counts, and reference it from G5, G8, G10, G19.
- Counts re-verified by re-running the AST scan (same totals as the draft) and corrected the test-suite survey by grep: 1004 test files (1017 at HEAD), 198 app_layout, 555 tmp_path, 124 files with real sleeps (210 calls), 93 spawning subprocesses, 116 building create_app.
- Added a refuted entry: the draft treated the two excluded fixes as still in flight; both are on master (859da19b, 59becdd5).
