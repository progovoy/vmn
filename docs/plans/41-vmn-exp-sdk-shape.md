# Plan 41: vmn-exp review fixes, SDK footprint, API consistency and storage contract

> Workstream D of the 2026-11-11 vmn-exp product review. The index, the
> milestone order and the cross-stream conflicts are in
> [37-vmn-exp-review-fixes.md](37-vmn-exp-review-fixes.md). Each item was drafted by a
> planner that read the code, then revised by a critic that re-checked the
> evidence and looked for tests pinning today's behaviour.
>
> Sizes: S under a day, M 1-3 days, L about a week, XL more. Priorities: P0 security or data loss, P1 blocks adoption or misleads users, P2 quality, P3 nice to have.

Status: **proposed** (2026-11-11). Owner decisions of 2026-11-11 are applied in this file.

Solo impact: see each item's risk line; nothing here may make the single-user case worse.

## Summary

All six findings are real and current. The evidence was re-opened at master `59becdd5` (26 commits after the draft's `25f03f3d`). None of those commits does any item's work: they touch the registry (`registry/store.py`, `view.py`, `lineage.py`, `registry/cli.py`), `sdk/models.py`, `sdk/usage.py`, `storage/base.py` (+11 lines, 322 now), `storage/cached.py`, `gcs.py`, `azure.py` and `core/storage_resolve.py`, and every line cited below was re-read there.

Footprint, re-measured at HEAD (`python -B`, Python 3.12, scripts in the scratchpad, nothing written to the repo): `import vmn_exp.sdk` loads 225 vmn_exp modules (148 core, 47 core.index*, 8 registry) plus sqlite3, asyncio, subprocess and urllib.request. The static top-level closure is 224 modules; cutting D1's edges gives 153 with no index, similar, sqlite or journal_reader module left; lazy registry exports (D2) give 137. The numbers are the same as at the draft commit.

What the owner decided, as applied here:

- **D3** moves all three sets out of the SDK wheel: `reports/`, `registry/cli*` and `core/push_*`. The test import repoints are approved. It lands after plan 40's C2 and C6, which edit `core/push_*`.
- **D5, D7, D9, D11** warn now and remove later. The distance between the warning and the removal is the removal rule in plan 43 F9; releases stay 0.1.x patch releases, and every behaviour change gets a `docs/vmn-exp/upgrading.md` row and a changelog entry.
- **D8** raises on unknown keywords at once.
- **D10** ships `resolve_storage` as a thin SDK function, not an alias of the core resolver, so plan 44 can thread a clock and an env through the core function.
- **D15** stage 1 (real GCS and Azure SDKs in the test requirements, GCS signature parity) now; stage 2 (emulators in CI) before D13 or D14 ships.
- **D17** is not started; see [Parked](#parked).
- Test edits named in this file are approved up front. An edit this file does not name still stops and asks.
- Python floor is `>=3.10` for both packages (plan 43 F12). No item here carried 3.8 or 3.9 work; the one place the floor shows is D10, whose new function can annotate `str | None` without quoting.

Two facts found while re-reading that change the draft:

- D3's guard "no SDK module imports argparse" would be green on arrival: no SDK module imports `argparse` today (`registry/cli_parser.py` receives the subparsers object). The guard is now on calls that build a parser (`add_argument`, `add_parser`, `add_subparsers`), which is red today for `registry/cli_parser.py` (34 calls) and `core/storage_resolve.py` (4, in `add_storage_flags`).
- D3's "22 test files": at HEAD 15 test files import a moved module path (10 for `core.push_*`, 5 for `registry.cli*`). The 8 test files that import `vmn_exp.reports` need no edit because the import path does not change.

Order: D4, D16 (small, no prerequisite) -> D8 -> D1 -> D2 -> D10 -> D6 -> D5 -> D7 -> D9 -> D11 -> D12 -> D15 stage 1 -> D15 stage 2 -> D13, D14 -> D3. Prerequisites in other plans: plan 43 F9 (which creates `upgrading.md` and states the removal rule) lands before D8, D5, D7, D9, D11 and D3; plan 38's A3 and A5 land before D6 and D5 (they change `resume.locate` and `start_run` first); plan 40's C3 lands before D12 and its C2 and C6 before D3; D15 stage 1 lands before plan 43 F12.

## Items

| Id | Pri | Size | Item | Owner decision |
|---|---|---|---|---|
| [D1](#d1) | P1 | M | Import-budget ratchet test, and cut core.index out of `import vmn_exp.sdk` |  |
| [D2](#d2) | P2 | S | Lazy registry exports and lazy filelock: no sqlite3, asyncio or registry store code at SDK import |  |
| [D3](#d3) | P3 | M | Move `reports/`, `registry/cli*` and `core/push_*` from the SDK wheel to vmn-exp | decided |
| [D4](#d4) | P1 | S | Test that keeps docs/vmn-exp/sdk.md "Public names" equal to `vmn_exp.sdk.__all__`, and fix the list |  |
| [D5](#d5) | P1 | S | `start_run`: keyword-only after `app_name`; positional calls warn, then are removed | decided |
| [D6](#d6) | P1 | S | `start_run(run_id=)` on a missing run: error names `create_run`, and the docs say "reopen" in one place |  |
| [D7](#d7) | P2 | S | Argument-order traps: swapped-argument guards on `log_*`; positional `app_name`/`ref` on `get_metric_history` warn, then are removed | decided |
| [D8](#d8) | P1 | S | `define_metric` raises on unknown keywords | decided |
| [D9](#d9) | P1 | M | `list_runs`: `limit=` after sorting, explicit `descending=`, and `incomplete=` (warns now, raises later) | decided |
| [D10](#d10) | P1 | S | `resolve_storage` as a thin SDK function, and reader names at the SDK top level | decided |
| [D11](#d11) | P1 | M | Storage plugins: the default `create_exclusive` warns now and becomes abstract later; ship a conformance kit | decided |
| [D12](#d12) | P2 | M | Write down the optional storage surface and stop it growing (probe ratchet and documented table) |  |
| [D13](#d13) | P3 | M | GCS and Azure: batch `delete_objects` instead of one request per key |  |
| [D14](#d14) | P3 | S | Azure listing resume: spike on a server-side start key, then feature-detect |  |
| [D15](#d15) | P2 | M | GCS/Azure fake fidelity: real SDKs and GCS signature parity now, emulator runs of the contract before D13/D14 | decided |
| [D16](#d16) | P3 | S | Stale references and the twin `_Listing` classes |  |

<a id="d1"></a>
### D1. Import-budget ratchet test, and cut core.index out of `import vmn_exp.sdk`

P1 · M

**Problem.** `import vmn_exp.sdk` loads 225 vmn_exp modules (148 core, 47 of them core.index*) for a job that only logs metrics. Re-measured at HEAD. core.index is reached through three small edges: (a) `relisted`/`object_read`, leaf helpers in core/index_metric_reads.py with no imports of their own, imported at top level by core/metric_compact.py, core/series_reader.py and storage/files.py; (b) core/refs.py imports core.index, index_point, index_snapshot and direct_placement at module top although an exact-verstr ref never touches the index; (c) core/alerts/transitions.py imports core.index at top for one call at :130. No test guards the closure. A static simulation of the cuts gives 153 modules (224 today) with no index, similar, sqlite or journal_reader module left.

**Approach.**

1. New test file computes the static top-level import closure of `vmn_exp.sdk` by AST (same technique as `_imports`/`_files` in test_packaging_split.py; copy the 20 lines rather than import across test modules if that is the local convention). Function-level imports do not count. It asserts FORBIDDEN prefixes are absent (`vmn_exp.core.index`, `vmn_exp.core.similar`, `vmn_exp.core.sqlite`, `vmn_exp.core.journal_reader`) and `len(closure) <= BUDGET`.
2. Move `MetricObjectGone`, `object_read` and `relisted` to a leaf module core/metric_object_reads.py; core/index_metric_reads.py re-exports them. Repoint metric_compact.py, series_reader.py and storage/files.py.
3. core/refs.py: drop the four top-level index imports, but KEEP `refs.point_view`, `refs.direct_placement` and the `experiment_index` access as module-level names, because test_sdk_run_states_batch.py:60-61 monkeypatches `refs.point_view` and `refs.placement_snapshot`. Do it with thin module-level trampolines (`def point_view(storage, app_name): from vmn_exp.core.index_point import point_view as real; return real(storage, app_name)`), and import `IndexSnapshot` and `core.index` inside `_listed_snapshot` and `placement_snapshot`. `point_placement` keeps calling the module-level `point_view`, so the existing patch still intercepts it. No existing test is edited.
4. core/alerts/transitions.py: import core.index inside the function at :130. Grep found no test patching `transitions.experiment_index`.
5. Set BUDGET to the closure measured when D1 lands. D1 lands in M3, after the M1/M2 items that add modules on the `start_run` import path (plan 40's final_retry, log_sync, process_hooks, exit_code; plan 38's checkout_guard, adoption, guest_run), so the number will be above 153.

Budget rule (owner, ratchet timing): the FORBIDDEN-prefix test is the hard gate. BUDGET may be lowered freely; it may be raised only in a commit whose message names the module it adds. The test's docstring states the rule.

**Tests first.**

- packages/vmn-exp/tests/test_sdk_import_budget.py::test_sdk_import_closure_has_no_index_modules (red today: 47 index modules)
- packages/vmn-exp/tests/test_sdk_import_budget.py::test_sdk_import_closure_within_budget (red today at 224 against the post-cut number)
- packages/vmn-exp/tests/test_sdk_import_budget.py::test_exact_parent_ref_resolves_without_importing_index (subprocess, fake storage whose exists() is True; asserts `vmn_exp.core.index` not in sys.modules after `resolve_parent`)
- packages/vmn-exp/tests/test_sdk_import_budget.py::test_relisted_still_importable_from_index_metric_reads
- existing packages/vmn-exp/tests/test_sdk_run_states_batch.py stays green unedited (it pins `refs.point_view` as a patchable attribute)

**Files.** `packages/vmn-exp/tests/test_sdk_import_budget.py (new)`, `packages/vmn-exp-sdk/src/vmn_exp/core/metric_object_reads.py (new)`, `packages/vmn-exp-sdk/src/vmn_exp/core/index_metric_reads.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/metric_compact.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/series_reader.py`, `packages/vmn-exp-sdk/src/vmn_exp/storage/files.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/refs.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/alerts/transitions.py`

**Risk.** Low. No public name moves; the old import path is kept by re-export and the patchable names in core/refs.py are kept. The first relative-ref resolution (`latest`, `@N`) pays the index import then instead of at import time. The static closure ignores imports under `if TYPE_CHECKING` only if the helper is written that way; state the rule in the test docstring.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/__init__.py:40-61`; `packages/vmn-exp-sdk/src/vmn_exp/core/refs.py:18-23`; `packages/vmn-exp-sdk/src/vmn_exp/core/refs.py:28-68`; `packages/vmn-exp-sdk/src/vmn_exp/core/index_metric_reads.py:12-40`; `packages/vmn-exp-sdk/src/vmn_exp/core/metric_compact.py:22`; `packages/vmn-exp-sdk/src/vmn_exp/core/series_reader.py:14`; `packages/vmn-exp-sdk/src/vmn_exp/storage/files.py:18`; `packages/vmn-exp-sdk/src/vmn_exp/core/alerts/transitions.py:15`; `packages/vmn-exp-sdk/src/vmn_exp/core/alerts/transitions.py:130`; `packages/vmn-exp/tests/test_sdk_run_states_batch.py:60-61`; `packages/vmn-exp/tests/test_packaging_split.py:39-64`

<a id="d2"></a>
### D2. Lazy registry exports and lazy filelock: no sqlite3, asyncio or registry store code at SDK import

P2 · S · depends on D1

**Problem.** After D1 the import still pays for two things a metrics-only job never uses. (1) The third-party `filelock` package (4.1.1 installed) imports asyncio and sqlite3 by itself; confirmed with a bare `import filelock`. It is imported at the top of `_base.py` and storage/ship_state.py. (2) sdk/__init__.py eagerly imports sdk.models, sdk.datasets and sdk.usage, which load registry.log/store/view/datasets. Simulated closure after making those three lazy: 137 modules, with `vmn_exp.registry` and `vmn_exp.registry.names` the only registry modules left. Two things do NOT go away: `vmn_exp.registry.names` stays (core.lineage imports it, via sdk.run_artifacts), and `subprocess` stays (core/env.py:20, core/alerts/sinks.py:10, and core/identity.py:12 via core.snapshot_features <- core.from_snapshot <- sdk.create).

**Approach.**

1. sdk/__init__.py: replace the eager imports of the ten registry names (`register_model`, `set_alias`, `remove_alias`, `get_model_version`, `list_models`, `download_model`, `register_dataset`, `get_dataset_version`, `use_model`, `use_dataset`) with a PEP 562 module `__getattr__` driven by a `_LAZY = {name: module}` table, plus `__dir__`. `__all__` is unchanged, so `from vmn_exp.sdk import register_model` and `import *` still work.
2. `_base.py`: import FileLock inside `get_repo_lock`. storage/ship_state.py: import FileLock/Timeout inside the function that locks (:226). No test patches `_base.FileLock` or `ship_state.FileLock` (grepped); tests import `filelock` directly.
3. Extend test_sdk_import_budget.py: a subprocess test that `sqlite3` and `asyncio` are absent from sys.modules after `import vmn_exp.sdk`; a static test that the closure's registry modules are a subset of `{vmn_exp.registry, vmn_exp.registry.names}`; lower BUDGET to the measured value.
4. Before coding, grep tests and src for attribute access that relied on the eager import as a side effect (`vmn_exp.sdk.models.`, `sdk.datasets.`, `sdk.usage.` reached without their own import) and add the explicit import in src where found.

**Tests first.**

- packages/vmn-exp/tests/test_sdk_import_budget.py::test_import_sdk_loads_no_sqlite3_or_asyncio (subprocess; red today)
- packages/vmn-exp/tests/test_sdk_import_budget.py::test_sdk_import_closure_has_only_the_registry_names_leaf (static; red today: 8 registry modules)
- packages/vmn-exp/tests/test_sdk_lazy_exports.py::test_every_name_in_all_resolves (getattr on each `__all__` name)
- packages/vmn-exp/tests/test_sdk_lazy_exports.py::test_star_import_exposes_registry_functions
- packages/vmn-exp/tests/test_sdk_lazy_exports.py::test_unknown_attribute_raises_attribute_error

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/__init__.py`, `packages/vmn-exp-sdk/src/vmn_exp/_base.py`, `packages/vmn-exp-sdk/src/vmn_exp/storage/ship_state.py`, `packages/vmn-exp/tests/test_sdk_import_budget.py`, `packages/vmn-exp/tests/test_sdk_lazy_exports.py (new)`

**Risk.** `mock.patch('vmn_exp.sdk.register_model')` still works (getattr resolves through `__getattr__`, then a real attribute is set). Import errors in registry modules surface at first use instead of at import; the `__all__` resolution test covers that. The sqlite3/asyncio test depends on no other closure module importing them; grep shows only index*/similar*/sqlite_* modules do, all gone after D1. Upstream's absolute `artifact_path` work (a0ab2953, f6fdec47) added storage-backend lookups to sdk/models.py and sdk/usage.py; both modules become lazy here, so that code costs nothing at import.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/_base.py:10`; `packages/vmn-exp-sdk/src/vmn_exp/_base.py:147-149`; `packages/vmn-exp-sdk/src/vmn_exp/storage/ship_state.py:27`; `packages/vmn-exp-sdk/src/vmn_exp/storage/ship_state.py:226`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/__init__.py:42-52`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/__init__.py:61`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/ranks.py:122-127`; `packages/vmn-exp-sdk/src/vmn_exp/core/env.py:20`; `packages/vmn-exp-sdk/src/vmn_exp/core/alerts/sinks.py:10`; `packages/vmn-exp-sdk/src/vmn_exp/core/identity.py:12`

<a id="d3"></a>
### D3. Move `reports/`, `registry/cli*` and `core/push_*` from the SDK wheel to vmn-exp

P3 · M · depends on D1, and on plan 40's C2 and C6

**Problem.** The SDK wheel ships CLI and server code that no SDK module imports: `vmn_exp.reports` (6 modules plus `__init__`), `registry/cli.py` and `registry/cli_parser.py` (handlers and parser of `vmn-exp model`) and nine `core/push_*.py` modules (`vmn-exp push`); 1,868 lines together. At HEAD their only importers outside themselves are in packages/vmn-exp (cli/comment.py, cli/settings.py, cli/report.py, cli/report_export.py, cli/prune.py, cli/plugin.py:504, cli/push.py, ui/report_index.py, ui/routes_reports.py, ui/routes_comments.py) and tests; none of the three sets is in the SDK import closure. The reader/server core (index*, similar*, query*, app_settings) cannot move: sdk/reader.py imports it at module top and docs/packaging.md places the reader API in the SDK wheel. So this is hygiene worth about 4% of the wheel, not a footprint fix; D1/D2 are the footprint fix.

**Approach.**

Three moves, each its own commit and worktree. Every commit also regenerates plan 44's G1/G18 allowlists if those have landed.

(a) `reports/`. `git mv packages/vmn-exp-sdk/src/vmn_exp/reports packages/vmn-exp/src/vmn_exp/reports`. The import path `vmn_exp.reports` is unchanged (namespace package), so no importer and none of the 8 test files that import it changes.

(b) `registry/cli*`. Move registry/cli.py to packages/vmn-exp/src/vmn_exp/cli/model_cmd.py and registry/cli_parser.py to cli/model_parser.py. Move `add_storage_flags` (core/storage_resolve.py:147-158) to a new cli/storage_flags.py together with `_add_storage_args`; its only callers are cli_parser.py:15 and cli/sweep/parser.py:34, both in vmn-exp after the move. Repoint the importers: cli/settings.py:9-10, cli/comment.py:6-7, cli/report.py:10-11, cli/plugin.py:504, cli/sweep/parser.py:2, and the moved handler module's own import of its parser (registry/cli.py:32, which becomes `from vmn_exp.cli.model_parser import add_model_parser`). Fix the docstring at core/storage_resolve.py:5 (`vmn_exp.registry.cli._get_storage` becomes `vmn_exp.cli.model_cmd._get_storage`).

(c) `core/push_*`. Move the nine modules, file names unchanged, to a new package packages/vmn-exp/src/vmn_exp/cli/pushing/ (with an `__init__.py`; `cli` is a regular package). It is NOT `cli/push/`: `cli/push.py` exists and a package of that name would shadow it. Every import becomes a prefix substitution, `vmn_exp.core.push_` to `vmn_exp.cli.pushing.push_`: cli/push.py:18-22 and the moved modules' own cross-imports (push_run.py:26-31, push_rename.py:23-24, push_plan.py:3-4). The same substitution fixes the `:mod:`/`:func:` docstring references (cli/push.py:6, push_run.py:9-12 and :51, push_files.py:3). Lands after plan 40's C2 (edits core/push_files.py) and C6, so those are not rebased across the move.

Approved test edits (import lines only, 15 files at HEAD):

- for (b): test_registry_artifact_uri.py:55, test_storage_store_flags.py:66, test_ui_jobs_store.py:15-16, test_cli_model.py:88 and :322, test_experiment_storage_resolve.py:93.
- for (c): test_child_markers_write_path.py:99, test_children_complete_flag.py:142-145, test_exp_push_core.py:13-16, test_exp_push_merge.py:15, test_exp_push_rename.py:23-28 (including `from vmn_exp.core import push_rename`), test_host_state_dirs.py:7, test_storage_multi_clone_copy_pushes.py:20-21, test_storage_multi_clone_moves.py:33, test_storage_multi_clone_rename_copy.py:24-25, test_storage_stream_adopt.py:26-27.

Re-run the grep before each commit; C2 and C6 may add test files that import `core.push_*`, and those are repointed the same way.

Docs and the split test, changed in the same commits. What each says today and the edit:

- **packages/vmn-exp/tests/test_packaging_split.py.** Docstring lines 4-5 list `reports` under vmn-exp-sdk; line 14 has `"reports"` in `SDK_SUBPACKAGES`; line 15 `FULL_SUBPACKAGES` lacks it. Edit in (a): move `reports` from the SDK line to the vmn-exp line in the docstring, drop it from `SDK_SUBPACKAGES`, add it to `FULL_SUBPACKAGES`. `test_every_vmn_exp_subpackage_belongs_to_one_distribution` (:110-115) is the red test for the move, and `test_full_platform_reaches_vmn_only_through_the_facade` then covers `reports`.
- **CLAUDE.md** "Development Setup" (lines 78-81) lists `sdk`/`storage`/`core`/`registry`/`integrations`/`_base` for vmn-exp-sdk and `cli`/`ui`/`snapshot`/`importers`/`gitmode` for vmn-exp; `reports` is in neither list. Edit in (a): add `reports` to the vmn-exp list.
- **docs/vmn-exp/architecture.md** "Three packages" diagram: the vmn-exp subgraph title (line 91) reads `vmn_exp.cli · ui · snapshot · importers · gitmode`; the vmn-exp-sdk title (line 98) reads `vmn_exp.sdk · core · storage · registry · integrations · _base`. `reports` is in neither. Edit in (a): add `· reports` to line 91. Line 98 does not change.
- **docs/packaging.md.** The Distributions table row for vmn-exp (line 55) lists `.cli`, `.ui`, `.snapshot`, `.importers`, `.gitmode`; the vmn-exp-sdk row (line 56) lists `.sdk`, `.storage`, `.core`, `.registry`, `.integrations`, `._base`; the Repository layout block (lines 131-132) repeats both sets; `reports` appears nowhere. Edits: in (a) add `.reports` to line 55 and `reports` to line 132; in (b) and (c) add one bullet to the "### vmn-exp" section (lines 85-96) saying the `vmn-exp model` handlers (`cli/model_cmd.py`), the push engine (`cli/pushing/`) and reports live in vmn-exp. The vmn-exp-sdk section (lines 98-111) stays true: the registry functions and the reader API stay in the SDK.
- **docs/vmn-exp/upgrading.md** (created by plan 43 F9): one row saying `vmn_exp.reports` is no longer in an SDK-only install and `vmn_exp.registry.cli`, `vmn_exp.registry.cli_parser`, `vmn_exp.core.push_*` and `vmn_exp.core.storage_resolve.add_storage_flags` moved to vmn-exp.

Not moved: index*, similar*, query*, app_settings*, alerts/sinks, index_io_process. Other modules unreachable from the SDK are a recorded follow-up.

**Tests first.**

- packages/vmn-exp/tests/test_packaging_split.py::test_every_vmn_exp_subpackage_belongs_to_one_distribution with the two tuples edited as above (red until (a) moves the directory)
- packages/vmn-exp/tests/test_packaging_split.py::test_sdk_wheel_builds_no_argparse_parsers (new; AST scan of the SDK src for calls to `.add_argument`, `.add_parser`, `.add_subparsers`; red today: registry/cli_parser.py and core/storage_resolve.py; green after (b))
- packages/vmn-exp/tests/test_packaging_split.py::test_sdk_wheel_ships_no_push_modules (new; no `core/push_*.py` under the SDK src; red until (c))
- packages/vmn-exp/tests/test_installation.py::test_upgrading_the_pair_keeps_the_moved_modules (new; install the previous released pair, upgrade to the built wheels, import `vmn_exp.reports` and `vmn_exp.cli.pushing.push_run`). This one is a real venv test; the three above are pure and come first.
- existing `test_sdk_subpackages_stay_off_vmn_and_the_full_platform`, `test_no_file_ships_in_two_wheels` and `test_each_wheel_ships_its_own_subpackages` stay green unedited

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/reports/ -> packages/vmn-exp/src/vmn_exp/reports/`, `packages/vmn-exp-sdk/src/vmn_exp/registry/cli.py -> packages/vmn-exp/src/vmn_exp/cli/model_cmd.py`, `packages/vmn-exp-sdk/src/vmn_exp/registry/cli_parser.py -> packages/vmn-exp/src/vmn_exp/cli/model_parser.py`, `packages/vmn-exp/src/vmn_exp/cli/storage_flags.py (new)`, `packages/vmn-exp-sdk/src/vmn_exp/core/push_*.py (9 files) -> packages/vmn-exp/src/vmn_exp/cli/pushing/`, `packages/vmn-exp-sdk/src/vmn_exp/core/storage_resolve.py`, `packages/vmn-exp/src/vmn_exp/cli/{settings,comment,report,plugin,push}.py`, `packages/vmn-exp/src/vmn_exp/cli/sweep/parser.py`, `packages/vmn-exp/tests/test_packaging_split.py`, `packages/vmn-exp/tests/test_installation.py`, the 15 test files listed above, `CLAUDE.md`, `docs/vmn-exp/architecture.md`, `docs/packaging.md`, `docs/vmn-exp/upgrading.md`

**Risk.** `vmn_exp.registry.cli`, `vmn_exp.core.push_*` and, for SDK-only installs, `vmn_exp.reports` stop importing; all are undocumented as SDK API and vmn-exp pins `vmn-exp-sdk==<same version>`. Moving files between two distributions that share a namespace directory has one hazard: if the old SDK wheel is uninstalled after the new vmn-exp is installed, pip deletes the freshly written files. pip installs dependencies first, so a normal upgrade is safe; the upgrade test above covers it. Plan 44's G11 Part A, G13 and G16 cite the SDK paths of reports/ and registry/cli.py; D3 lands before them or their paths are updated. Plan 44's G12 edits core/storage_resolve.py, the file (b) takes `add_storage_flags` out of; serialize the two. The upgrade test installs the previous release from the package index; like the other tests in test_installation.py (:8-9) it skips when the index is unreachable, so it does not gate an offline run. The CLAUDE.md line is a one-word addition to the package list; it is not one of the three CLAUDE.md amendments the owner approved on 2026-11-11 (docs layout, the no-Docker lane, the entry points), so the implementer shows the owner that line before committing it.

**Owner decision (2026-11-11).** Move `registry/cli*`, `reports/` and `core/push_*` to vmn-exp. The reader/server core (index*, similar*, query*, app_settings) stays in the job wheel. The test import repoints are approved. The move lands after plan 40's C2 and C6, and CLAUDE.md's package list, architecture.md's package diagram, docs/packaging.md and test_packaging_split.py change with it.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/registry/cli.py:22-32`; `packages/vmn-exp-sdk/src/vmn_exp/registry/cli_parser.py:1-15`; `packages/vmn-exp-sdk/src/vmn_exp/core/storage_resolve.py:5`; `packages/vmn-exp-sdk/src/vmn_exp/core/storage_resolve.py:147-158`; `packages/vmn-exp-sdk/src/vmn_exp/core/push_run.py:26-31`; `packages/vmn-exp/src/vmn_exp/cli/push.py:18-22`; `packages/vmn-exp/src/vmn_exp/cli/settings.py:9-10`; `packages/vmn-exp/src/vmn_exp/cli/comment.py:6-7`; `packages/vmn-exp/src/vmn_exp/cli/report.py:10-11`; `packages/vmn-exp/src/vmn_exp/cli/plugin.py:504`; `packages/vmn-exp/src/vmn_exp/cli/sweep/parser.py:2`; `packages/vmn-exp/src/vmn_exp/cli/prune.py:43`; `packages/vmn-exp/src/vmn_exp/cli/report_export.py:11`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:31-63`; `docs/packaging.md:55-56`; `docs/packaging.md:98-103`; `docs/packaging.md:131-132`; `docs/vmn-exp/architecture.md:91`; `docs/vmn-exp/architecture.md:98`; `CLAUDE.md:77-81`; `packages/vmn-exp/tests/test_packaging_split.py:1-15`; `packages/vmn-exp/tests/test_packaging_split.py:110-115`; `packages/vmn-exp/tests/test_installation.py:101-119`

<a id="d4"></a>
### D4. Test that keeps docs/vmn-exp/sdk.md "Public names" equal to `vmn_exp.sdk.__all__`, and fix the list

P1 · S

**Problem.** sdk.md's "Public names in `vmn_exp.sdk`" paragraph lists 20 names; `__all__` has 24. `RunExistsError`, `background_paused`, `pause_background` and `resume_background` are missing.

**Approach.**

New test: a pure function `public_names(markdown_text)` extracts the backticked identifiers between "Public names in `vmn_exp.sdk`:" and the sentence starting "Readers live in"; the test passes it the text of docs/vmn-exp/sdk.md and asserts the set equals `set(vmn_exp.sdk.__all__)`. The extractor is unit-tested on an inline string. Then add the four names to the paragraph.

**Tests first.**

- packages/vmn-exp/tests/test_docs_sdk_public_names.py::test_public_names_extracts_the_backticked_list (inline markdown string, no file IO)
- packages/vmn-exp/tests/test_docs_sdk_public_names.py::test_sdk_md_public_names_equal_dunder_all (red today: 4 missing)

**Files.** `packages/vmn-exp/tests/test_docs_sdk_public_names.py (new)`, `docs/vmn-exp/sdk.md`

**Risk.** None at run time. The parser is tied to two anchor phrases; the test fails with a message naming them if they are edited. docs/vmn-exp is symlinked into the vmn-exp package (cli/docs), so the fix ships with the wheel automatically.

**Evidence.** `docs/vmn-exp/sdk.md:42-48`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/__init__.py:63-88`

<a id="d5"></a>
### D5. `start_run`: keyword-only after `app_name`; positional calls warn, then are removed

P1 · S · after plan 38's A3 and A5, which change `start_run` first

**Problem.** `start_run` takes 25 positional-or-keyword parameters (run.py:125-149). A positional call binds silently wrong when a parameter is inserted, and nothing stops `start_run(app, "note", {...})`. `create_run` is already keyword-only after `app_name`, so the two entry points disagree.

**Approach.**

Step 1, warn (now):

1. New sdk/positional.py (about 30 lines): `keyword_only_after(n, legacy)` decorator. The decorated function is declared with `*` after its first n parameters. The wrapper takes `*args, **kwargs`; when `len(args) > n` it maps the extras onto the names in `legacy` (a tuple literal at the decoration site), raises TypeError if there are more extras than names or a name is given twice, emits one `FutureWarning` (stacklevel 2) and forwards. The warning names the parameters to pass by keyword and says positional use will be removed, pointing at docs/vmn-exp/upgrading.md. `FutureWarning`, not `DeprecationWarning`: the latter is hidden by default outside `__main__`, and with removal arriving in a patch release a job must see the notice in its log. `functools.wraps` is enough: `inspect.signature` follows `__wrapped__` and shows the keyword-only form.
2. sdk/run.py: `def start_run(app_name=None, *, note=None, ...)` decorated with `@keyword_only_after(1, legacy=("note", "params", "parent", ..., "export_env"))` in today's exact order. Any parameter A3 or A5 added before D5 lands goes after the legacy tuple as keyword-only from birth.
3. A repo test scans packages/*/src by AST for `start_run(...)` calls with more than one positional argument and asserts none. Grep found none in src, tests or docs.
4. sdk.md states the rule; upgrading.md gets a row for the warning.

Step 2, remove (a later patch release, per the removal rule in plan 43 F9): delete the decorator from `start_run`; a second positional argument is then a plain TypeError. Approved test edits at that step: `test_start_run_note_positional_warns_in_disabled_mode` becomes `test_start_run_extra_positional_raises_type_error`, and `test_start_run_legacy_order_matches_the_0_1_signature` is deleted. upgrading.md gets the removal row. sdk/positional.py stays while D7 still uses it.

No options object and no body refactor.

**Tests first.**

- packages/vmn-exp/tests/test_sdk_positional.py::test_extra_positional_maps_to_legacy_name_and_warns (decorator over a plain function, no IO)
- packages/vmn-exp/tests/test_sdk_positional.py::test_keyword_call_does_not_warn
- packages/vmn-exp/tests/test_sdk_positional.py::test_too_many_positionals_raise_type_error
- packages/vmn-exp/tests/test_sdk_positional.py::test_positional_and_keyword_for_the_same_name_raise_type_error
- packages/vmn-exp/tests/test_sdk_positional.py::test_signature_shows_keyword_only
- packages/vmn-exp/tests/test_sdk_positional.py::test_warning_is_a_future_warning_naming_the_keywords
- packages/vmn-exp/tests/test_sdk_positional.py::test_start_run_note_positional_warns_in_disabled_mode (`mode="disabled"` returns NoOpRun before any store or git access; red today)
- packages/vmn-exp/tests/test_sdk_positional.py::test_start_run_legacy_order_matches_the_0_1_signature (pins the tuple against a literal copy of today's order)
- packages/vmn-exp/tests/test_sdk_positional.py::test_no_source_call_passes_start_run_more_than_one_positional

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/positional.py (new)`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py`, `packages/vmn-exp/tests/test_sdk_positional.py (new)`, `docs/vmn-exp/sdk.md`, `docs/vmn-exp/upgrading.md`

**Risk.** Step 1 is behaviour-compatible: positional calls keep working and print a warning. Step 2 breaks any caller still passing `note` or `params` positionally, in a patch release; the warning window and the upgrading.md row are the notice. Tools that introspect the signature see keyword-only parameters from step 1. sdk/positional.py is a new module on the `start_run` import path, so D1's BUDGET is raised by one in the commit that adds it.

**Owner decision (2026-11-11).** Warn, then remove. Positional arguments after `app_name` warn from the release that ships step 1 and stop working at the distance the removal rule in plan 43 F9 sets; both steps need an upgrading.md row.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:124-150`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:222-285`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:56-59`

<a id="d6"></a>
### D6. `start_run(run_id=)` on a missing run: error names `create_run`, and the docs say "reopen" in one place

P1 · S · after plan 38's A3 and A5, which change `resume.locate` first

**Problem.** `run_id=` means "reopen this existing run" in `start_run` but "create exactly this name, else RunExistsError" in `create_run`. `start_run(run_id="my-name")` on a name that does not exist raises `ValueError("Cannot resume run 'my-name' of '<app>': no such experiment")` with no hint. The same message fires for a stale `VMN_RESUME_RUN_ID`. The message is built in core/fork.py `resolve_run`, shared with the fork action.

**Approach.**

Leave core/fork.py alone (the fork action must not get a resume hint). In sdk/resume.py add a small function `existing_run(storage, app_name, ref, from_env)` that calls `resolve_run(storage, app_name, ref, "resume")` and, on ValueError, re-raises ValueError with the original text plus the hint: for an argument, "start_run(run_id=...) reopens an existing run; to create a run with this exact id call create_run(run_id=...) first, or pass name= for a display name"; for the environment, "VMN_RESUME_RUN_ID names a run that does not exist in this store". `locate` gains a `from_env=False` parameter and uses `existing_run` only when action is "resume" (not for fork, and not for the `adopt` action plan 38's A5 adds); run.py:238 passes `from_env=not run_id`, as it already does for `check_reopenable`. Add a three-row table to sdk.md and the `start_run` docstring: `start_run(run_id)` takes an existing run; `create_run(run_id)` registers exactly this id; `name=` is a label.

**Tests first.**

- packages/vmn-exp/tests/test_sdk_resume_errors.py::test_unknown_run_id_error_points_at_create_run (calls `resume.existing_run` with a fake storage whose exists() is False and a ref without `-dev.`, so no index or listing is touched; red today: function missing)
- packages/vmn-exp/tests/test_sdk_resume_errors.py::test_unknown_env_run_id_error_names_the_env_var
- packages/vmn-exp/tests/test_sdk_resume_errors.py::test_error_still_starts_with_cannot_resume_run (pins the original prefix so callers matching on it keep working)
- packages/vmn-exp/tests/test_sdk_resume_errors.py::test_existing_run_returns_the_verstr_unchanged

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/resume.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py`, `packages/vmn-exp/tests/test_sdk_resume_errors.py (new)`, `docs/vmn-exp/sdk.md`

**Risk.** Only the error text grows; type and prefix are unchanged. Grep found no test or doc asserting "Cannot resume" or "no such experiment", so nothing pinned is disturbed.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/core/fork.py:44-52`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/resume.py:34-44`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/resume.py:52-64`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/resume.py:67-85`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:238-241`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:56-66`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/fork.py:23`

<a id="d7"></a>
### D7. Argument-order traps: swapped-argument guards on `log_*`; positional `app_name`/`ref` on `get_metric_history` warn, then are removed

P2 · S · depends on D5

**Problem.** `Run.log_table(name, data)`, `log_image(name, image)` and `log_histogram(name, values)` take the name first; `log_dict(obj, name)`, `log_text(text, name)` and `log_figure(figure, name)` take it last. A swapped `log_dict("cfg.json", cfg)` fails inside `os.path.splitext` with an unrelated TypeError; a swapped `log_table(rows, "name")` formats the rows into the stored path. In the reader, `get_metric_history(metric, app_name, ref)` puts the metric first while `get_run(app_name, ref)` does not, so `get_metric_history("my_app", "loss")` reads metric "my_app" of app "loss".

**Approach.**

Positions are not reordered.

Step 1 (now):

1. sdk/run_artifacts.py: `log_dict` and `log_figure` raise TypeError("log_dict(obj, name): name must be a str file name, got <type>; the arguments look swapped") when `name` is not a str; `log_text` does the same when `text` is not str.
2. sdk/run_media.py: `log_table`, `log_image` and `log_histogram` raise the equivalent TypeError when `name` is not a str.
3. sdk/reader.py: decorate `get_metric_history` with D5's `keyword_only_after(1, legacy=("app_name", "ref"))`. The documented form becomes `get_metric_history("loss", app_name="my_app", ref="@3")`. The docs teach the positional form today, so update sdk.md:989, sdk.md:1018 and client-guide.md:350 in the same commit. test_exp_reader_dataframe.py:188-201 is left unedited at this step: a positional call there still passes, with a warning.
4. NoOpRun is left alone: its `log_*` are `_ignore(*args, **kwargs)` and validate nothing today.
5. sdk.md: one sentence stating the two families (file artifacts are payload then file name; keyed media are key then payload). upgrading.md: one row for the new TypeErrors and the warning.

Step 2, remove (a later patch release, per the removal rule in plan 43 F9): drop the decorator from `get_metric_history`; `app_name` and `ref` are then plain keyword-only parameters. Approved test edits at that step: any call in test_exp_reader_dataframe.py:188-201 that passes `app_name` positionally is rewritten to the keyword form, and `test_get_metric_history_legacy_tuple_is_app_name_then_ref` becomes `test_get_metric_history_positional_app_name_raises_type_error`. upgrading.md gets the removal row.

**Tests first.**

- packages/vmn-exp/tests/test_sdk_swapped_args.py::test_log_dict_with_name_first_raises_type_error_naming_the_order (mixin class over a fake `_log_produced`; red today: unrelated TypeError text)
- packages/vmn-exp/tests/test_sdk_swapped_args.py::test_log_figure_with_name_first_raises
- packages/vmn-exp/tests/test_sdk_swapped_args.py::test_log_text_with_a_non_string_text_raises
- packages/vmn-exp/tests/test_sdk_swapped_args.py::test_log_table_with_data_first_raises_before_anything_is_stored
- packages/vmn-exp/tests/test_sdk_swapped_args.py::test_log_image_with_image_first_raises
- packages/vmn-exp/tests/test_sdk_swapped_args.py::test_get_metric_history_legacy_tuple_is_app_name_then_ref (inspects the decorator's mapping; no pandas or storage)
- packages/vmn-exp/tests/test_sdk_swapped_args.py::test_correct_orders_still_reach_the_store

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/run_artifacts.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/run_media.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py`, `packages/vmn-exp/tests/test_sdk_swapped_args.py (new)`, `docs/vmn-exp/sdk.md`, `docs/vmn-exp/client-guide.md`, `docs/vmn-exp/upgrading.md`

**Risk.** Calls that were already wrong fail with a clear TypeError instead of an obscure one. `log_text` with two strings swapped stays undetectable. The `get_metric_history` warning hits the form the docs taught, so the production client very likely uses it: it keeps working with a visible `FutureWarning` until step 2, then fails with TypeError in a patch release. The upgrading.md row is the notice.

**Owner decision (2026-11-11).** Warn, then remove: positional `app_name`/`ref` on `get_metric_history` warn now and stop working per the removal rule in plan 43 F9; the docs that teach the positional form change with step 1.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/run_artifacts.py:110-125`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run_media.py:153`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run_media.py:173-180`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:376`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:230`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/ranks.py:133-139`; `docs/vmn-exp/sdk.md:989`; `docs/vmn-exp/sdk.md:1018`; `docs/vmn-exp/client-guide.md:350`; `packages/vmn-exp/tests/test_exp_reader_dataframe.py:188-201`

<a id="d8"></a>
### D8. `define_metric` raises on unknown keywords

P1 · S

**Problem.** `Run.define_metric(name, step_metric, summary, goal, hidden, chart, **fields)` writes every extra keyword into the `define_metric` log entry. `define_metric("val_loss", gaol="min")` succeeds, stores `gaol`, and the run ranks with no goal. The only src caller passes `goal=` (integrations/optuna_study.py:220); test_ui_metric_schema.py:42 forwards `**define` built from the five named keywords.

**Approach.**

Remove `**fields` from `MetricDefinitions.define_metric` and build the dict locally: `fields = {**summary_fields(summary, goal), **hidden_fields(hidden), **chart_fields(chart)}`. Python then raises TypeError for an unknown keyword. Fix the module docstring line that says every keyword lands in the entry (metric_defs.py:5-8). `core.step_metric.create_define_metric_entry(**fields)` stays as is. In sdk/ranks.py give `NoOpRun` its own `define_metric(self, name, step_metric=None, summary=None, goal=None, hidden=None, chart=None)` returning None (today it is the catch-all `_ignore`, ranks.py:136), so a typo fails the same on rank 0, secondary ranks and disabled mode. `test_noop_run_accepts_define_metric` still passes unedited. Add the upgrading.md row and say in sdk.md that unknown keywords are a TypeError.

**Tests first.**

- packages/vmn-exp/tests/test_sdk_define_metric_strict.py::test_unknown_keyword_raises_type_error_and_appends_nothing (MetricDefinitions subclass with a list-backed `_append`; red today)
- packages/vmn-exp/tests/test_sdk_define_metric_strict.py::test_known_keywords_produce_the_same_entry_as_before (expected entry written out literally for step_metric/summary/goal/hidden/chart)
- packages/vmn-exp/tests/test_sdk_define_metric_strict.py::test_noop_run_rejects_the_same_unknown_keyword (red today)

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/metric_defs.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/ranks.py`, `packages/vmn-exp/tests/test_sdk_define_metric_strict.py (new)`, `docs/vmn-exp/sdk.md`, `docs/vmn-exp/upgrading.md`

**Risk.** Deliberate break in a patch release, with no warning step: a client passing a custom keyword gets TypeError at `define_metric`, normally at job start. Readers of existing records are unaffected.

**Owner decision (2026-11-11).** Raise on unknown keywords at once. The change needs an upgrading.md row and a changelog entry.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/metric_defs.py:5-8`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/metric_defs.py:18-21`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/metric_defs.py:49-52`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/ranks.py:133-136`; `packages/vmn-exp-sdk/src/vmn_exp/integrations/optuna_study.py:220`; `packages/vmn-exp/tests/test_ui_metric_schema.py:42`

<a id="d9"></a>
### D9. `list_runs`: `limit=` after sorting, explicit `descending=`, and `incomplete=` (warns now, raises later)

P1 · M · after D7 (same file)

**Problem.** Three traps in `vmn_exp.sdk.reader.list_runs`. (1) `last=` is applied before sorting (reader.py:180-181), so `list_runs(sort="loss", last=5)` is the five newest runs sorted by loss, not the five best; there is no top-N. (2) The docstring says "oldest first", but the real default is the app's primary metric when one is configured, storage order otherwise; direction cannot be chosen although `sort_by_metric` already accepts `descending`. Newest-first already exists as `sort="timestamp"` or `sort="idx"` but is not documented for the SDK. (3) While the index is loading the function returns some of the rows with only an `IndexingWarning`; a script computing a best run or a count gets a wrong answer with exit code 0.

**Approach.**

Step 1 (now):

1. `list_runs(..., descending=None, limit=None, incomplete=None)`. `descending` goes to `sort_by_metric`. `limit` slices after sorting and must be a positive int (ValueError otherwise). `last` keeps its meaning; its docstring gains the contrast with `limit`.
2. `incomplete` takes `"warn"`, `"raise"` or None (not passed); any other value is ValueError. `"raise"` raises the existing `IndexingWarning` (it is an Exception subclass) with the same `incomplete_text` message, which is what `warnings.simplefilter("error", IndexingWarning)` already produces (test_reader_indexing.py:51-53), so there is one type to catch and no new exception class. `"warn"` warns as today. None warns too, and appends to the warning text that incomplete rows will raise in a later release and that `incomplete="warn"` keeps partial rows. The existing tests match the warning with `pytest.warns(match=...)`, a search, so the longer text keeps test_reader_indexing.py green unedited. Thread the flag through `_rows_and_declared` to `_warn_loading`.
3. Put the row selection in a pure function `select(rows, schema, *, last, sort, descending, limit)` in a new sdk/reader_select.py (reader.py is already 393 lines), tested on plain dict rows. Put the loading check beside it as `check_loading(loading, incomplete, stacklevel)` so it is testable without a snapshot.
4. `runs_dataframe` already forwards `**list_runs_kwargs`; `param_importance` gains `incomplete=` too since it shares `_rows_and_declared`.
5. sdk.md reader section: real default order, `sort="timestamp"` for newest first, `last` vs `limit`, `incomplete`. Fix the docstring's stale `version_stamp.core.experiment_query.QueryError` reference (reader.py:165). upgrading.md: one row for the new keywords and the announced change.

Step 2, raise (a later patch release, per the removal rule in plan 43 F9): `incomplete` not passed means `"raise"`. Approved test edits at that step, both in test_reader_indexing.py: `test_list_runs_warns_while_the_index_loads` (:36-40) and `test_list_runs_names_what_it_loaded_before_the_total_is_known` (:43-46) pass `incomplete="warn"` explicitly, and one new test asserts the default raises. upgrading.md gets the row. The default order is not changed in either step, since `last=` depends on storage order.

**Tests first.**

- packages/vmn-exp/tests/test_sdk_list_runs_select.py::test_limit_takes_the_best_n_after_sorting (pure `select` over dict rows; red: module missing)
- packages/vmn-exp/tests/test_sdk_list_runs_select.py::test_last_still_slices_before_sorting
- packages/vmn-exp/tests/test_sdk_list_runs_select.py::test_descending_forces_the_metric_direction
- packages/vmn-exp/tests/test_sdk_list_runs_select.py::test_limit_must_be_a_positive_int
- packages/vmn-exp/tests/test_sdk_list_runs_select.py::test_incomplete_raise_raises_indexing_warning_with_the_progress_text (calls `check_loading` with `(120, 734)`)
- packages/vmn-exp/tests/test_sdk_list_runs_select.py::test_incomplete_warn_keeps_the_warning_text_unchanged
- packages/vmn-exp/tests/test_sdk_list_runs_select.py::test_incomplete_not_passed_warns_and_announces_the_raise
- packages/vmn-exp/tests/test_sdk_list_runs_select.py::test_unknown_incomplete_value_is_a_value_error
- packages/vmn-exp/tests/test_sdk_list_runs_select.py::test_the_warning_points_at_the_caller_of_list_runs (asserts the reported file name; guards the stacklevel)
- existing packages/vmn-exp/tests/test_reader_indexing.py stays green unedited at step 1

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader_select.py (new)`, `packages/vmn-exp/tests/test_sdk_list_runs_select.py (new)`, `docs/vmn-exp/sdk.md`, `docs/vmn-exp/upgrading.md`; at step 2 also `packages/vmn-exp/tests/test_reader_indexing.py`

**Risk.** Step 1 changes no result; a caller that never passed `incomplete` sees a longer warning. Step 2 turns a partial listing into an exception for such callers, in a patch release: a script that ran during indexing and got partial rows now fails until it passes `incomplete="warn"` or waits. That is the intent. `_warn_loading` uses `stacklevel=4`; moving it changes the frame depth, which the last test above pins.

**Owner decision (2026-11-11).** `list_runs` warns on incomplete rows now and raises later, at the distance the removal rule in plan 43 F9 sets; `limit=`, `descending=` and `incomplete=` are added now. Both steps need an upgrading.md row.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:107-134`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:142-183`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:186`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:362`; `packages/vmn-exp-sdk/src/vmn_exp/core/log.py:148-160`; `packages/vmn-exp-sdk/src/vmn_exp/core/load_progress.py:8-16`; `packages/vmn-exp/tests/test_reader_indexing.py:20`; `packages/vmn-exp/tests/test_reader_indexing.py:36-53`

<a id="d10"></a>
### D10. `resolve_storage` as a thin SDK function, and reader names at the SDK top level

P1 · S · depends on D2, D4

**Problem.** To pass `storage=` a user must import an internal: sdk.md tells them to call `vmn_exp.core.storage_resolve.resolve_experiment_storage(store="s3://...")` in two places (sdk.md:94 and :973). Top-level `vmn_exp.sdk` exports ten registry functions but none of the readers, which need a second import path.

**Approach.**

Uses D2's `_LAZY` table, so the import cost does not grow.

1. New module sdk/store_resolve.py with one function:

   ```python
   def resolve_storage(*, dir: str | None = None, store: str | None = None,
                       bucket: str | None = None, prefix: str | None = None,
                       endpoint_url: str | None = None, repo_root=None):
       return resolve_experiment_storage(dir=dir, store=store, bucket=bucket, prefix=prefix,
                                         endpoint_url=endpoint_url, repo_root=repo_root)
   ```

   It is a function of its own, not the core function re-exported: its six keyword-only parameters are the public contract, and the core resolver stays free to change. Plan 44's G10 and G12 give `core.storage_resolve.resolve_experiment_storage` a clock and an env; when they land, `resolve_storage` is the place that builds the real ones and passes them (a public SDK function is an entry point that may build real IO, as approved for CLAUDE.md). The module is not named `resolve_storage.py`, because a submodule of that name would overwrite the lazy attribute once imported. The name `open_store` is not used: `vmn_exp.storage.registry.open_store(uri, area)` is the plugin-contract function with a different signature.
2. Add `resolve_storage` and the reader names to `_LAZY` and `__all__`: `list_runs`, `get_run`, `get_run_state`, `get_run_states`, `get_lineage`, `similar_runs`, `runs_dataframe`, `get_metric_history`, `param_importance`. `vmn_exp.sdk.reader` stays the canonical module. None of the names collides with a submodule of `vmn_exp.sdk` (checked against the directory listing at HEAD; `run_states.py` is not `get_run_states`).
3. sdk.md: replace both `vmn_exp.core.storage_resolve...` mentions with `vmn_exp.sdk.resolve_storage` and extend the Public names paragraph (D4's test enforces it).

`vmn_exp.sdk.manage` is not re-exported: its `log_metrics`, `log_note` and `set_tags` would be confused with the Run methods.

**Tests first.**

- packages/vmn-exp/tests/test_sdk_lazy_exports.py::test_resolve_storage_takes_the_six_documented_keywords_only (`inspect.signature`; red today: name missing)
- packages/vmn-exp/tests/test_sdk_lazy_exports.py::test_resolve_storage_is_its_own_function (`sdk.resolve_storage is not resolve_experiment_storage`, and its `__module__` is `vmn_exp.sdk.store_resolve`)
- packages/vmn-exp/tests/test_sdk_lazy_exports.py::test_resolve_storage_with_dir_opens_a_store_under_it (`dir=tmp_path`, `repo_root=False`, `VMN_EXPERIMENT_*` cleared; the thin real path)
- packages/vmn-exp/tests/test_sdk_lazy_exports.py::test_reader_names_resolve_to_reader_module_functions
- packages/vmn-exp/tests/test_sdk_import_budget.py::test_import_sdk_does_not_import_reader (static closure excludes `vmn_exp.sdk.reader` and `vmn_exp.sdk.store_resolve`)
- packages/vmn-exp/tests/test_docs_sdk_public_names.py::test_sdk_md_public_names_equal_dunder_all (red until sdk.md lists the new names)
- packages/vmn-exp/tests/test_docs_sdk_public_names.py::test_sdk_md_does_not_send_users_to_core_storage_resolve

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/store_resolve.py (new)`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/__init__.py`, `packages/vmn-exp/tests/test_sdk_lazy_exports.py`, `packages/vmn-exp/tests/test_sdk_import_budget.py`, `packages/vmn-exp/tests/test_docs_sdk_public_names.py`, `docs/vmn-exp/sdk.md`

**Risk.** Additive. `from vmn_exp.sdk import *` now also loads the reader and its index imports, and binds names that can shadow a user's own `list_runs`; acceptable for star imports, but say so in sdk.md. Old import paths keep working. Until plan 44's G12 gives the core resolver an env parameter, the behaviour test cannot run on a fake env: `merge_env_into_params` reads `os.environ` directly (core/writer.py:113-119), so the test clears the variables with monkeypatch and is rewritten onto a fake env by G12.

**Owner decision (2026-11-11).** The public resolver is `vmn_exp.sdk.resolve_storage`, a thin SDK function, not an alias of the core function. Plan 44 threads clock and env through the core resolver behind it.

**Evidence.** `docs/vmn-exp/sdk.md:94`; `docs/vmn-exp/sdk.md:973`; `docs/vmn-exp/sdk.md:42-48`; `packages/vmn-exp-sdk/src/vmn_exp/core/storage_resolve.py:27-64`; `packages/vmn-exp-sdk/src/vmn_exp/core/storage_resolve.py:106-110`; `packages/vmn-exp-sdk/src/vmn_exp/core/writer.py:113-119`; `packages/vmn-exp-sdk/src/vmn_exp/storage/registry.py:66-69`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/models.py:43-48`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/__init__.py:63-88`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:142-152`

<a id="d11"></a>
### D11. Storage plugins: the default `create_exclusive` warns now and becomes abstract later; ship a conformance kit

P1 · M

**Problem.** `SnapshotStorage.create_exclusive` defaults to check-then-save (base.py:112-117). On a shared plugin store two hosts can both get True for one verstr, and one record overwrites the other. experiments.md says the default is not safe on a shared store but nothing at run time says so. Plugin authors have nothing to run: the contract cases live in packages/vmn-exp/tests/test_storage_object_stores.py, are parametrised over the built-ins only and are not shipped. Built-in local, S3 (inherited by GCS and Azure) and cached stores all override the method.

**Approach.**

Step 1 (now), two commits.

(a) storage/base.py: the default `create_exclusive` logs one VMN_LOGGER warning per storage class ("<Class>.create_exclusive is the non-atomic default; two hosts can claim the same name. Override it with a conditional create; the default will be removed, see upgrading.md"), then behaves as today. The existing once-only mechanism is `_first_sighting(owner, name)` in core/record_format.py:66-77, which keeps a set on the owner instance; that is per instance, not per class, so add a small class-keyed helper next to the default (a module-level set in storage/base.py keyed by `type(self)`, not by class name, since two plugins may name their class alike) rather than bending `_first_sighting`. The set lives for the process, so each unit test defines its own subclass inside the test. core/writer.py:359's `hasattr(storage, "create_exclusive")` branch stays: duck-typed fakes that are not `SnapshotStorage` subclasses go through `_claim`.

(b) New module packages/vmn-exp-sdk/src/vmn_exp/storage/conformance.py, no pytest import, under 250 lines. `CHECKS` is a tuple of plain functions `check(make_store)` that raise AssertionError; `check_store(make_store)` runs them all against fresh stores and returns `[(name, error_or_None)]`. First set, taken from the experiments.md contract bullets and the existing object-store cases: save/load_record round trip; `metadata.yml` makes a record exist (a claimed, unfinished name is invisible to `list_snapshots`); `create_exclusive` claims once; N threads released by a `threading.Barrier` get exactly one True; delete makes the record invisible; `save_file`/`load_file` round trip; `update_metadata` keeps other keys; `list_apps`.
Add ONE new parametrised test that runs `CHECKS` against local, S3 (moto), GCS and Azure (fakes). Leave test_storage_object_stores.py as it is; folding its cases into the kit is a later cleanup. Add a "Check your backend" paragraph with a short example to experiments.md "Storage backends (plugins)" (experiments.md:1749), and an upgrading.md row for the warning.

Step 2, abstract (a later patch release, per the removal rule in plan 43 F9): `create_exclusive` gets `@abstractmethod` and its body is deleted, so a `SnapshotStorage` subclass without it cannot be instantiated. Approved test edits at that step: the three test subclasses that rely on the default gain a `create_exclusive` (`_AreaLessStorage` in test_app_settings_no_areas.py:12-23, `EmptyStorage` in empty_storage.py:10, `_OldSignatureStore` in test_storage_cached_plugin_root.py:14), and the two step 1 tests of the default are replaced by `test_a_subclass_without_create_exclusive_cannot_be_instantiated`. experiments.md moves the method from the defaulted list to the required list; upgrading.md gets the row. The `hasattr` branch in core/writer.py still stays, for non-subclass duck storages.

**Tests first.**

- packages/vmn-exp/tests/test_storage_conformance.py::test_default_create_exclusive_warns_once_per_class (in-memory subclass implementing the 9 abstract methods; two instances, one warning; logger captured; red today)
- packages/vmn-exp/tests/test_storage_conformance.py::test_default_create_exclusive_still_claims_a_free_name
- packages/vmn-exp/tests/test_storage_conformance.py::test_kit_passes_an_atomic_in_memory_store (dict-backed fake with a lock-guarded create_exclusive)
- packages/vmn-exp/tests/test_storage_conformance.py::test_kit_fails_the_race_check_for_a_check_then_save_store (fake whose exists() waits on an injected barrier so both threads see the name free; deterministic)
- packages/vmn-exp/tests/test_storage_conformance.py::test_kit_reports_every_check_by_name
- packages/vmn-exp/tests/test_storage_conformance_builtins.py::test_builtin_store_passes_the_kit[local|s3|gs|az] (thin real implementations; tmp_path, moto, fakes)

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/storage/base.py`, `packages/vmn-exp-sdk/src/vmn_exp/storage/conformance.py (new)`, `packages/vmn-exp/tests/test_storage_conformance.py (new)`, `packages/vmn-exp/tests/test_storage_conformance_builtins.py (new)`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/upgrading.md`; at step 2 also `packages/vmn-exp/tests/test_app_settings_no_areas.py`, `packages/vmn-exp/tests/empty_storage.py`, `packages/vmn-exp/tests/test_storage_cached_plugin_root.py`

**Risk.** Step 1's warning is new log output for plugin stores using the default; intended. Step 2 stops a plugin store that never overrode the method from being constructed at all, in a patch release, including a working single-host one; the warning window, the kit and the upgrading.md row are the notice. The race check proves atomicity only probabilistically for a real store (it can pass a racy one by luck); say so in the kit's docstring. The kit ships in the SDK wheel and is imported only on demand; D1's ratchet keeps it out of the import closure. storage/base.py is 322 lines; the warning adds a few.

**Owner decision (2026-11-11).** The default `create_exclusive` warns now and becomes abstract later, at the distance the removal rule in plan 43 F9 sets. Both steps need an upgrading.md row.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/storage/base.py:112-117`; `packages/vmn-exp-sdk/src/vmn_exp/storage/base.py:102-105`; `packages/vmn-exp-sdk/src/vmn_exp/core/record_format.py:38-77`; `packages/vmn-exp-sdk/src/vmn_exp/core/writer.py:355-367`; `docs/vmn-exp/experiments.md:1749`; `docs/vmn-exp/experiments.md:1779-1786`; `packages/vmn-exp-sdk/src/vmn_exp/storage/local.py:124`; `packages/vmn-exp-sdk/src/vmn_exp/storage/s3_records.py:54`; `packages/vmn-exp-sdk/src/vmn_exp/storage/cached.py:66`; `packages/vmn-exp/tests/test_storage_object_stores.py:1-7`; `packages/vmn-exp/tests/test_storage_object_stores.py:58-160`; `packages/vmn-exp/tests/test_app_settings_no_areas.py:12-23`; `packages/vmn-exp/tests/empty_storage.py:10`; `packages/vmn-exp/tests/test_storage_cached_plugin_root.py:14`

<a id="d12"></a>
### D12. Write down the optional storage surface and stop it growing (probe ratchet and documented table)

P2 · M · depends on D11, and on plan 40's C3

**Problem.** Callers discover optional storage methods by `hasattr(storage, "x")` / `getattr(storage, "x", None)`. A scan of both src trees at HEAD finds about 50 distinct names probed on storage-like receivers, led by `metric_objects` and `is_remote` (7 sites each), `direct_files` and `list_record_names` (5), `record_files`, `load_logs_by_writer`, `list_run_verstrs` and `cache_identity` (3), plus private `_local`/`_remote` reach-ins (4 and 3). The surface is written down nowhere: experiments.md names 9 abstract and about 8 defaulted methods, so a plugin author cannot tell what a missing method costs, and nothing stops new probes being added.

**Approach.**

Two stages, each its own commit. No production behaviour changes.

1. Ratchet test: AST-scan the two vmn_exp src roots for `hasattr(<expr>, "<name>")` and `getattr(<expr>, "<name>", <default>)` and compare `{name: count}` with a checked-in table in the style of architecture_known_violations.py. Fail on a new name or a higher count; fail on a stale entry so the table shrinks as probes go. The scan cannot know `<expr>` is a storage (all receivers together give 263 names), so the table is seeded from the full result and reviewed once by hand to drop non-storage names (`path`, `root`, `depth`, `busy` and similar); record that judgement in the table module's docstring.
2. Add an "Optional methods" table to experiments.md "Storage backends (plugins)": name, what a store without it gets (the fallback the caller takes), and the cost. A test keeps the doc table's names equal to the checked-in table, as D4 does for `__all__`.

The table is seeded after plan 40's C3, which adds `getattr(storage, "defer_ships", None)` in `Run._open`, so `defer_ships` is listed from the start (owner, ratchet timing). No probe is removed here; removing them is the parked D17.

**Tests first.**

- packages/vmn-exp/tests/test_storage_optional_surface.py::test_probe_scanner_finds_hasattr_and_three_argument_getattr (pure function over an inline source string)
- packages/vmn-exp/tests/test_storage_optional_surface.py::test_no_new_optional_storage_probes (red first by seeding the table without one known name, then completed)
- packages/vmn-exp/tests/test_storage_optional_surface.py::test_probe_table_has_no_stale_entries
- packages/vmn-exp/tests/test_storage_optional_surface.py::test_experiments_md_optional_table_matches_the_code_table (red until the doc table exists)

**Files.** `packages/vmn-exp/tests/test_storage_optional_surface.py (new)`, `packages/vmn-exp/tests/storage_optional_probes.py (new, the table)`, `docs/vmn-exp/experiments.md`

**Risk.** None at run time. A ratchet that is green by construction is weak TDD; the scanner's own unit test and the doc-equality test are the real red tests. Writing the "cost of not overriding" cells needs reading each call site; budget for it. D3 moves probe sites between the two src roots (core/push_* to cli/pushing/); the scan covers both roots, so counts do not change.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/storage/base.py:11-12`; `packages/vmn-exp-sdk/src/vmn_exp/storage/cached_logs.py:293-294`; `packages/vmn-exp-sdk/src/vmn_exp/storage/s3_listing.py:215-216`; `packages/vmn-exp-sdk/src/vmn_exp/core/writer.py:359`; `docs/vmn-exp/experiments.md:1749`; `packages/vmn-exp/tests/test_app_settings_no_areas.py:1-30`

<a id="d13"></a>
### D13. GCS and Azure: batch `delete_objects` instead of one request per key

P3 · M · depends on D15 (both stages)

**Problem.** `ObjectClient.delete_objects` loops `delete_object` per key and always returns `{"Errors": []}` (object_client.py:113-116). `S3SnapshotStorage._delete_keys` splits keys into batches of 1000 and runs the batches concurrently, expecting one request per batch; on GCS and Azure each batch is 1000 sequential round trips. Deleting or pruning a record with thousands of segment objects is therefore much slower there than on S3.

**Approach.**

1. object_client.py: `delete_objects` delegates to an overridable `_remove_many(keys)` returning `[(key, error_text)]` for failures; the default is today's loop. The result becomes `{"Errors": [{"Key": k, "Message": m}, ...]}`, so `_delete_batch`'s existing RuntimeError path works for all three stores.
2. gcs.py: `_remove_many` in chunks of 100 inside `with self._client.batch(raise_exception=False):`, calling `bucket.delete_blob(key)`; 404 counts as success.
3. azure.py: `_remove_many` in chunks of 256 through `self._container.delete_blobs(*keys, raise_on_any_failure=False)`; non-2xx, non-404 sub-responses become errors.
4. Both SDK calls, their limits and their behaviour at the pinned minimums (google-cloud-storage>=2.7, azure-storage-blob>=12.14) are from memory: neither SDK is installed in the repo venv. Verify them first; D15 stage 1 puts the SDKs in the test requirements.
5. Extend object_store_fakes.py with `FakeGCSClient.batch()` and `FakeContainerClient.delete_blobs()`, counting requests.
6. Before shipping, the delete checks run against fake-gcs-server and Azurite (D15 stage 2).

If step 4 shows either batch API is unusable, the fallback design is the default `_remove_many` fanning the per-key deletes through the existing `parallel_map`, which needs no SDK-specific code.

**Tests first.**

- packages/vmn-exp/tests/test_storage_object_delete.py::test_default_remove_many_reports_a_failed_key_in_errors (ObjectClient subclass whose `_remove` raises for one key; red today: Errors is always empty)
- packages/vmn-exp/tests/test_storage_object_delete.py::test_gcs_delete_of_250_keys_uses_3_batches (fake counts batch contexts; red today)
- packages/vmn-exp/tests/test_storage_object_delete.py::test_azure_delete_of_600_keys_uses_3_delete_blobs_calls (red today)
- packages/vmn-exp/tests/test_storage_object_delete.py::test_missing_key_in_a_batch_is_not_an_error
- packages/vmn-exp/tests/test_storage_object_delete.py::test_failed_key_in_a_batch_raises_from_storage_delete
- existing delete cases in test_storage_object_stores.py stay green for s3/gs/az

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/storage/object_client.py`, `packages/vmn-exp-sdk/src/vmn_exp/storage/gcs.py`, `packages/vmn-exp-sdk/src/vmn_exp/storage/azure.py`, `packages/vmn-exp/tests/object_store_fakes.py`, `packages/vmn-exp/tests/test_storage_object_delete.py (new)`

**Risk.** The batch APIs behave differently from hand-written fakes, which is what D15 contains. Azure blob batch can be refused by some account types; on a batch-level refusal fall back to the per-key loop and log a warning each time it happens, never silently (plan 32). Today a per-key error propagates as an exception mid-loop; after step 1 it is collected and raised at the end of the batch, so more keys are deleted before the failure surfaces.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/storage/object_client.py:108-116`; `packages/vmn-exp-sdk/src/vmn_exp/storage/s3_records.py:27`; `packages/vmn-exp-sdk/src/vmn_exp/storage/s3_records.py:88-97`; `packages/vmn-exp-sdk/src/vmn_exp/storage/gcs.py:70-75`; `packages/vmn-exp-sdk/src/vmn_exp/storage/azure.py:81-86`

<a id="d14"></a>
### D14. Azure listing resume: spike on a server-side start key, then feature-detect

P3 · S · depends on D15 (both stages)

**Problem.** `AzureObjectClient` sets `server_side_start_after = False` and skips `item.name <= start_after` client-side. Effects: a walk cannot jump past a subtree and pages through every object; `list_files_between` returns None on Azure, so the index falls back to about three LISTs per record instead of one per 1000 objects; a resumed listing re-reads everything before the start key.

**Approach.**

Spike first, at most half a day; the Azure SDK is not installed in the repo venv, so nothing about it could be verified here. Find out whether `ContainerClient.list_blobs`/`walk_blobs` accept a start key in the supported range (`azure-storage-blob>=12.14`) and from which SDK and service API version.
If it exists: `AzureObjectClient.__init__` takes an injected `supports_start_from` bool decided by the factory in azure.py (the entry-point side), sets `self.server_side_start_after` per instance, passes the start key when supported, and keeps the client-side `<=` filter because the service's start key may be inclusive. No pin bump. The path runs against Azurite (D15 stage 2) before it ships.
If it does not exist: no code change. Document the cost in byo-bucket.md (an Azure index refresh lists every object under the prefix) and close the item.
Not planned: emulating jumps by splitting the prefix.

**Tests first.**

- Only if the spike finds a start key: packages/vmn-exp/tests/test_storage_azure_listing.py::test_iter_passes_the_start_key_when_supported (FakeContainerClient records kwargs)
- packages/vmn-exp/tests/test_storage_azure_listing.py::test_iter_filters_client_side_when_unsupported (green today; pins the fallback)
- packages/vmn-exp/tests/test_storage_azure_listing.py::test_list_files_between_answers_when_the_start_key_is_supported
- packages/vmn-exp/tests/test_storage_azure_listing.py::test_start_key_itself_is_never_returned
- If the spike finds none: a docs-only change, no test

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/storage/azure.py`, `packages/vmn-exp/tests/object_store_fakes.py`, `packages/vmn-exp/tests/test_storage_azure_listing.py (new)`, `docs/vmn-exp/byo-bucket.md`

**Risk.** The premise is unverified; the spike decides. A fake that accepts the keyword proves nothing about the service, which is why Azurite comes before shipping. Keeping the client-side filter means a wrong assumption costs performance, not correctness.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/storage/azure.py:27`; `packages/vmn-exp-sdk/src/vmn_exp/storage/azure.py:69-79`; `packages/vmn-exp-sdk/src/vmn_exp/storage/object_client.py:80-85`; `packages/vmn-exp-sdk/src/vmn_exp/storage/s3_listing.py:211-216`

<a id="d15"></a>
### D15. GCS/Azure fake fidelity: real SDKs and GCS signature parity now, emulator runs of the contract before D13/D14

P2 · M · depends on D11

**Problem.** S3 storage is tested against moto. GCS and Azure are tested only against packages/vmn-exp/tests/object_store_fakes.py; neither `google-cloud-storage` nor `azure-storage-blob` is in the test requirements or installed in the repo venv. A wrong keyword or a mis-modelled behaviour passes every test and fails in a real bucket.

**Approach.**

Stage 1 (S, no Docker; now, in M3, before plan 43's F12 sets the extras' lower bounds). Add `google-cloud-storage` and `azure-storage-blob` to packages/vmn-exp/tests/test_requirements.txt. Tests that need the SDKs absent already hide them explicitly (test_ui_storage_extras.py `_hide`, test_storage_uri_registry.py `_hide_modules`), and `install_fake_*` replace `sys.modules` entries, so installing the real packages should not disturb them; run the exp suite to confirm. New test for GCS: each fake method's parameter names are a subset of the real method's (`inspect.signature`), from a table such as `{FakeBlob.upload_from_string: google.cloud.storage.Blob.upload_from_string}`. The same test is written for Azure only for the methods whose real signatures name their parameters: as far as recalled the Azure SDK takes most options through `**kwargs`, which makes a subset test pass for any keyword. Confirm once the SDK is installed, and list in the test's docstring which Azure methods are covered by signature and which only by stage 2.

Stage 2 (M, Docker; in M4, before D13 or D14 ships). Run `conformance.CHECKS` (D11) against fake-gcs-server and Azurite containers under an `emulator` marker, as a separate stage in ci/pipeline.py next to `tests_exp`. Fixtures use the existing constructor seams: `GCSSnapshotStorage(client=<real client pointed at the emulator>)` and `AzureSnapshotStorage(container=<real ContainerClient>)`. The regular passes exclude the marker: `tests_exp` and tests/run_pytest.sh select `not serial` today (ci/pipeline.py:150, run_pytest.sh:131), which becomes `not serial and not emulator`. The fakes stay as the millisecond unit layer.

**Tests first.**

- packages/vmn-exp/tests/test_object_store_fakes_parity.py::test_fake_gcs_methods_accept_only_real_sdk_parameters (red until the SDK is in the test requirements; may then expose real drift)
- packages/vmn-exp/tests/test_object_store_fakes_parity.py::test_gcs_storage_code_passes_only_keywords_the_real_sdk_accepts (AST over storage/gcs.py call keywords)
- stage 2, first and without Docker: ci/test_pipeline.py::test_the_pipeline_runs_the_storage_emulator_stage (the stage exists, selects `-m emulator`, and `tests_exp` excludes it; red until the stage is added)
- packages/vmn-exp/tests/test_storage_emulators.py::test_conformance_checks_pass_on_fake_gcs_server (emulator mark; Docker)
- packages/vmn-exp/tests/test_storage_emulators.py::test_conformance_checks_pass_on_azurite (emulator mark; Docker)

**Files.** `packages/vmn-exp/tests/test_requirements.txt`, `packages/vmn-exp/tests/test_object_store_fakes_parity.py (new)`, `packages/vmn-exp/tests/test_storage_emulators.py (new)`, `packages/vmn-exp/tests/object_store_fakes.py`, `ci/pipeline.py`, `ci/test_pipeline.py`, `tests/run_pytest.sh`

**Risk.** Stage 1 adds two test-only dependencies to a list that already carries torch, tensorflow and ray; the core suite has its own requirements file. Stage 2 depends on emulator images whose conditional-write semantics are imperfect; a failing emulator check is triaged against the real service before code changes. Neither stage changes shipped code. The emulator tests are Docker tests by nature, which the repo allows for thin real implementations. Not settled by reading: plan 37 (conflict 24) leaves open whether pipeline-stage tests live in ci/test_pipeline.py or in packages/vmn-exp/tests/test_ci_pipeline_stages.py (plan 44's G3); this item uses ci/test_pipeline.py, the file that exists today, and follows whichever home G3 and plan 43's F15 settle on.

**Owner decision (2026-11-11).** Real GCS and Azure SDKs in the test requirements and signature parity now (stage 1); the emulator stage in CI before D13 or D14 ships (stage 2).

**Evidence.** `packages/vmn-exp/tests/test_storage_object_stores.py:1-7`; `packages/vmn-exp/tests/object_store_fakes.py:50`; `packages/vmn-exp/tests/object_store_fakes.py:131`; `packages/vmn-exp/tests/object_store_fakes.py:161`; `packages/vmn-exp/tests/object_store_fakes.py:261`; `packages/vmn-exp/tests/object_store_fakes.py:298`; `packages/vmn-exp/tests/test_requirements.txt:1-28`; `packages/vmn-exp-sdk/pyproject.toml:25-26`; `packages/vmn-exp/tests/test_ui_storage_extras.py:19-29`; `packages/vmn-exp/tests/test_storage_uri_registry.py:116`; `ci/pipeline.py:146-152`; `ci/test_pipeline.py:70-93`; `tests/run_pytest.sh:129-132`

<a id="d16"></a>
### D16. Stale references and the twin `_Listing` classes

P3 · S

**Problem.** (1) storage/base.py's docstring names backends `snapshot_storage_local`, `snapshot_storage_s3` and `snapshot_storage_cached`, modules that no longer exist (they are storage/local.py, s3.py, cached.py). (2) sdk/__init__.py cites `tests/test_packaging_split.py`; the file is packages/vmn-exp/tests/test_packaging_split.py. (3) sdk/reader.py's module docstring says it depends on `version_stamp.core`, and `list_runs` cites `version_stamp.core.experiment_query.QueryError`; the SDK may not import `version_stamp` at all. (4) cached_logs.py and cached_metrics.py each define a private `_Listing` with the same constructor, `objects` and `refresh`, differing only in the call that fetches the groups.

The stale references to where `reports` and `registry.cli` live (core/storage_resolve.py:5, docs/packaging.md, the test_packaging_split.py docstring) are fixed by D3, which moves them.

**Approach.**

Boy-scout commits, each in its own worktree.
(a) Docstring fixes for (1)-(3). These change no behaviour and get no test. The `QueryError` line in reader.py is also touched by D9; whichever lands first fixes it.
(b) One `StreamListing(fetch)` class in a new storage/stream_listing.py (about 15 lines) with `objects(stream)` and `refresh()`; `fetch` is a zero-argument callable returning `{stream: [objects]}`. cached_logs.py constructs it with `lambda: _groups(remote, app_name, verstr)`, cached_metrics.py with `lambda: remote.metric_objects(app_name, verstr)`. Delete both private classes. No test names either `_Listing` (grepped at HEAD).

**Tests first.**

- packages/vmn-exp/tests/test_storage_stream_listing.py::test_fetches_once_until_refreshed (counting fake fetch; red: module missing)
- packages/vmn-exp/tests/test_storage_stream_listing.py::test_unknown_stream_is_an_empty_list
- packages/vmn-exp/tests/test_storage_stream_listing.py::test_refresh_makes_the_next_objects_call_fetch_again
- existing test_storage_cached_* suites stay green unedited

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/storage/base.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/__init__.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py`, `packages/vmn-exp-sdk/src/vmn_exp/storage/stream_listing.py (new)`, `packages/vmn-exp-sdk/src/vmn_exp/storage/cached_logs.py`, `packages/vmn-exp-sdk/src/vmn_exp/storage/cached_metrics.py`, `packages/vmn-exp/tests/test_storage_stream_listing.py (new)`

**Risk.** Negligible.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/storage/base.py:8-9`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/__init__.py:6`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:23`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:165`; `packages/vmn-exp-sdk/src/vmn_exp/storage/cached_logs.py:278-294`; `packages/vmn-exp-sdk/src/vmn_exp/storage/cached_metrics.py:285-297`

## Parked

<a id="d17"></a>
- **D17. Replace storage probes with base-class defaults.** Not started (owner, 2026-11-11). Duck-typed storages stay supported: test_app_settings_no_areas.py pins them, storage/base.py:11-12 documents them and about 15 test files pass duck fakes through production code. D12's table is the work list if a concrete cost ever shows up (a bug caused by a missing probe, or a plugin author confused by the surface).

## Dropped

Nothing in this stream was dropped by the decisions, and none of the 26 commits in `25f03f3d..HEAD` does an item's work.

## Review findings corrected or dropped

- **Finding 1 (partly): move the reader/server modules (index*, similar*, query*, app_settings, alerts/sinks) out of the job-side wheel** Not feasible as stated. packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:31-63 imports core.index, index_rows, query, query_extra, similar_search and app_settings_store at module top, and docs/packaging.md:98-103 places the reader API in the SDK wheel. Only reports/, registry/cli* and core/push_* (1,868 lines) have no SDK-side importer (grep-verified). D3 moves that set; the reader/server core stays in the job wheel. D1/D2 remove the import-time cost, which is what a job actually pays.
- **Finding 2 (partly): `start_run` is a 164-line function** The span run.py:124-288 is right, but most of it is the parameter list and the docstring; the executable body is run.py:222-285 (about 64 lines) and already delegates to resume, fork, create_record and Run. The real trap is the 25 positional-or-keyword parameters (run.py:125-149), which D5 fixes. No body refactor is planned.
- **Finding 2 (partly): `list_runs` returns oldest first** Half right. `sort_by_metric` (core/log.py:148-183) orders by the app's primary metric when one is configured and keeps storage order (oldest first) only otherwise; `sort="timestamp"` and `sort="idx"` already give newest first. The docs under-describe this, and `last` before sort plus the partial-rows warning are real. D9 documents the actual order and adds `limit`, `descending` and `incomplete`.
- **Finding 4 (partly): the racy default `create_exclusive` endangers runs today** Real for plugin stores only. Every built-in overrides it: storage/local.py:124, storage/s3_records.py:54 (inherited by GCS and Azure), storage/cached.py:66. docs/vmn-exp/experiments.md:1779-1786 already tells plugin authors the default is unsafe. Planned as a run-time warning now, an abstract method later, and a conformance kit (D11), not as a P0.
- **Finding 4 (partly): there is no conformance testing of the backend contract** A contract suite exists for the built-in object stores: packages/vmn-exp/tests/test_storage_object_stores.py:58-160 runs the same cases, including the `create_exclusive` race, against S3 (moto), GCS and Azure (fakes). What is missing is a kit a plugin author can run, which D11 adds.

## Non-goals

- Re-planning the two review fixes that already landed: ui/jobs.py metric-name validation (859da19b) and storage/buffered.py keeping the buffer after a failed final ship (59becdd5).
- A fourth distribution (vmn-exp-reader), or moving index*/similar*/query*/app_settings out of the SDK wheel.
- Reordering positional parameters of any public function, or renaming `run_id`. Fixes are guards, keyword-only with a warning step, and docs.
- Replacing `start_run`'s parameters with an options object, or splitting its body.
- Changing `list_runs`' default order.
- Removing `subprocess` or `urllib.request` from the SDK import (core/env.py, core/alerts/sinks.py, core/identity.py). They are stdlib and cheap; the ratchet targets vmn_exp module count, sqlite3 and asyncio.
- A wall-clock import-time threshold in CI. Timing is machine-dependent (82-150 ms measured across runs).
- Splitting `SnapshotStorage` into several interfaces, or removing the `_local`/`_remote` reach-ins.
- Dropping duck-typed storage support. D17 is parked; D12 only documents and freezes the surface.
- Emulating server-side StartAfter on Azure by prefix splitting.
- Replacing the hand-written GCS/Azure fakes, or folding test_storage_object_stores.py into the conformance kit.
- A pytest-wide `-W error::DeprecationWarning` setting; the repo has no pytest config file and adding one is its own change.
- A docstring cross-reference checker for the SDK.
- Migrating existing `clock=time.time`-style defaults or other direct IO in the touched modules beyond what each item touches; that is plan 44.
- Any change to core vmn (packages/vmn, version_stamp) or to the web UI.

## What the critic changed in the draft

- Re-measured the footprint: 225 vmn_exp modules, 147 core, 47 core.index*, 8 registry; 150 ms with `python -B` (no cached bytecode). The draft 'refuted' the reviewer's 180-300 ms on the strength of an 82-90 ms warm run; I removed that refutation because a cold import here is already 150 ms.
- Reproduced the draft's closure simulation with my own AST script: 224 static today, 153 after D1's cuts, 137 after lazy registry exports. D1's numbers hold.
- D1: the draft's step 3 would have broken packages/vmn-exp/tests/test_sdk_run_states_batch.py:60-61, which does `monkeypatch.setattr(refs, "point_view", ...)` and `(refs, "placement_snapshot", ...)`. The draft said to 'patch at the source module instead', which is editing a test to make it pass. Revised to keep the names as module-level trampolines so the test stays unedited.
- D2: title and tests corrected. `subprocess` cannot leave the import (core/env.py:20, core/alerts/sinks.py:10, core/identity.py:12 via sdk.create), and `vmn_exp.registry.names` stays via core.lineage, so the draft's `test_import_sdk_loads_no_registry_modules` would never go green. Confirmed that a bare `import filelock` (4.1.1) loads asyncio and sqlite3, and that no test patches `_base.FileLock`.
- D3: `cli/push/` collides with the existing packages/vmn-exp/src/vmn_exp/cli/push.py; renamed the target package. Corrected the counts (6 reports modules), added the importers the draft missed (cli/report_export.py, cli/prune.py, three ui modules and the test files), added the pip uninstall-order hazard of moving files between distributions sharing a namespace, and lowered priority to P3 because it does not affect footprint.
- D4: dropped `test_dunder_all_is_sorted_and_unique` (green on arrival, not asked for) and made the extractor a pure function with its own unit test.
- D5: dropped the `-W error::DeprecationWarning` step; there is no pytest config file in the repo (run_pytest.sh builds the command line). Replaced with an AST test that no source call passes more than one positional. Dropped `__signature__` handling (functools.wraps suffices). Size M -> S.
- D6: the draft located the message in sdk/resume.py; it is raised in core/fork.py:44-52 and shared with the fork action (sdk/fork.py:23). Revised to wrap it in sdk/resume.py so fork errors are untouched, and made the unit test reachable without index or git (a ref without `-dev.` and a fake storage). Removed the draft's owner decision about a `resume=` keyword: nobody asked for it. Verified no test or doc pins the old text.
- D7: the positional form of `get_metric_history` is the one the docs teach (sdk.md:1018, client-guide.md:350); added those doc updates. Added `log_histogram` to the name guards. Confirmed NoOpRun's `log_*` are catch-all `_ignore`, so they are left alone. Removed the unverified MLflow-order claim from the rationale.
- D8: confirmed NoOpRun.define_metric is `_ignore(*args, **kwargs)` (ranks.py:133-136) and that test_step_metric.py and test_ui_metric_schema.py:42 keep passing with an explicit signature.
- D9: replaced the new `IndexingIncomplete` exception with raising the existing `IndexingWarning`, which is what `warnings.simplefilter("error", IndexingWarning)` already yields in test_reader_indexing.py:51; one type, no new class. Corrected the 'oldest first' premise (primary metric sorts by default; `sort="timestamp"` is already newest first). Flagged the `stacklevel=4` dependency.
- D10: flipped the naming recommendation. `vmn_exp.storage.registry.open_store(uri, area)` already exists with a different signature; a second `open_store` would add a trap while fixing one.
- D11: kept the `hasattr(storage, "create_exclusive")` branch in core/writer.py because duck-typed fakes go through `_claim`. Changed 'parametrise test_storage_object_stores.py over the kit' to one new test file, leaving the existing tests unedited. Noted that the race check cannot prove atomicity for a real store.
- D12 split into D12 and D17. The draft recommended making `SnapshotStorage` subclassing mandatory and removing probes; packages/vmn-exp/tests/test_app_settings_no_areas.py explicitly pins duck-typed storages, base.py:11-12 documents them, and about 15 test files use duck fakes. D12 is the ratchet plus the documented table (M, P2); D17 is the migration (L, P3), now parked. Also corrected the draft's worry about JournaledStorage: it is a mixin placed in front of a backend class, so the result still subclasses SnapshotStorage.
- D12: the draft's ratchet was 'green on arrival by construction'; added a unit test of the scanner itself and noted the scan cannot tell storage objects from others, so the seed table needs one manual review.
- D13: lowered to P3, corrected the description (batches already run concurrently via parallel_map; the cost is sequential deletes inside each 1000-key batch), added a pure unit test of the error-collection default, noted the behaviour change in when a per-key failure surfaces, and recorded a simpler fallback design if the SDK batch APIs do not check out.
- D14: made the tests conditional on the spike's outcome; a spike that finds nothing ends as a docs change with no test. Added that a fake accepting the keyword proves nothing, so Azurite is required before shipping.
- D15: the Azure signature-parity test is likely vacuous because the Azure SDK takes most options through `**kwargs` (from memory; the SDK is not installed here). Made Azurite the check with authority for Azure. Verified that tests needing the SDKs absent hide them explicitly, so adding the real packages to test requirements should be safe.
- D16: dropped the docstring-reference guard test as speculative; docstring fixes carry no behaviour. Added two stale references the draft missed (reader.py module docstring, core/storage_resolve.py:5).
- Coverage check: every sub-point of findings 1-6 maps to an item (1: D1-D3; 2: D5-D10; 3: D4; 4: D11, D12, D17; 5: D13-D15; 6: D16). Nothing in the workstream overlaps the two review fixes that landed.
