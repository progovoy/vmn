# Plan 1: `vmn-exp rerun <app> -v <ref>`

Inspired by MLflow Projects `mlflow run` / W&B Launch "re-run". vmn is the only tool
that has all three ingredients per run: the exact tree (dirty included), the command,
and the captured env.

> **Base:** re-verified against `master` @ `0096782` (feature-parity merged, incl.
> `157d864` code store). Paths below are relative to `packages/`:
> `SDK/` = `vmn-exp-sdk/src/vmn_exp/`, `EXP/` = `vmn-exp/src/vmn_exp/`,
> `VS/` = `vmn/src/version_stamp/`, `WEB/` = `vmn-exp/webui/src/`.

## 0. Findings

1. **Command is recorded by both runners, neither says which.** `_Supervision._supervise` (`EXP/cli/run.py:309-329`) writes `run_state.yml` `command: list(run_cmd)`; `_finish` appends a `run` log entry with the command (`run.py:404-413`). The SDK's `Run._initial_state` (`SDK/sdk/run.py:289-310`) writes `command: list(sys.argv)` (`["train.py", …]`, no interpreter) and its own `run` entry (`sdk/run.py:344-351`). **New `runner` field needed.**
2. **cwd is not recorded.** The child runs in `_child_cwd()` (`$VMN_WORKING_DIR` or `os.getcwd()`, `run.py:109-115`, used at `run.py:297`). `_Supervision` takes `extra_env` (`run.py:240-243,294`) but no cwd, and `_child_cwd()` reads the *supervisor's* `os.environ`, so a rerun cannot redirect the child via env alone. **New `cwd` field + a `cwd=` parameter needed.**
3. **Code is now stored once per code identity** (`SDK/core/code_store.py`). A run record carries `code: <code_verstr>.<full diff_hash>` naming an object of the reserved pseudo-app `vmn-code/<app>`; `record_run` (`EXP/gitmode/checkout.py:64-97`) builds the template, adds the object's summary (`has_*`, `untracked_skipped`) and `code`, and calls `create_run(..., patches={})`. `SnapshotStorage.load` (`SDK/storage/base.py:42-46`) resolves it via `resolve_code` (`code_store.py:47-57`); a gone/incomplete object → empty patches + transient `code_missing`. Clean trees have no `diff_hash` and no `code` key (`gitmode/capture.py:64-76`). Pre-`157d864` records still hold their patches in-record (no `code` key; `load` passes them through).
4. **So a rerun need not copy patches — it references the same code object.** Prune deletes a code object only when no remaining run name has its `code_verstr` as a `.`-bounded prefix (`drop_unused_code`, `code_store.py:60-82`, called at `EXP/cli/prune.py:345`). A rerun allocated under the original's `code_verstr` gets `C.rN` (`_run_verstr_candidates`/`allocate_run_verstr`, `SDK/core/writer.py:235-298`; `create_run` at `writer.py:301-361`), which keeps the object alive after the original is pruned. **Allocation under the original `code_verstr` is load-bearing.**
5. **Must not re-snapshot the worktree.** `_experiment_create_core` (`EXP/cli/experiment.py:443-502`) captures the live checkout (`capture.capture_snapshot` + `ensure_code`); `git am` in a worktree yields new commit hashes → a different `code_verstr`. **Build the rerun record from the original's metadata, not a capture.**
6. **Materialization helpers are too lenient.** `_materialize_workdir` (`VS/devversion/materialize.py:134-209`) clones (`clone --shared` locally, `materialize.py:50-102`), only *warns* on dep failures, places deps at `output/<dep_path>` (escapes with `../repo1`) and always writes `vmn_metadata.yml`. `_apply_patches_to_workdir` (`VS/devversion/apply.py:12-42`) only warns on `git am`/`git apply` failure and swallows tarball errors. Running the wrong code silently is unacceptable → failures must be fatal.
7. **Layout/worktree helpers exist in vmn, reachable only through the facade.** `_island_layout` (`VS/cli/worktree_create.py:151-169`, pure `os.path`) keeps the source's relative layout; `create_dep_worktree(repo, dest, {"start_point": sha}, None)` does `git worktree add --detach` and `remove_registered_worktree` removes it (`VS/cli/worktree_git.py:138-153,246-263`; the module imports only `core.constants`/`core.logging`). Import rules (`tests/test_packaging_split.py`): `vmn_exp.{cli,ui,snapshot,importers,gitmode}` reach vmn **only** via `version_stamp.api` (`:98-102`); `vmn_exp.{core,sdk,storage,registry,integrations,_base}` may **not import `version_stamp` at all**, not even the facade (`:83-96`). The facade surface is pinned by `tests/test_api_facade.py::test_exact_surface` (`_EXPECTED_ALL`). `_clone_at`, `_commit_exists`, `_resolve_remote`, `_apply_patches_to_workdir`, `_predates_untracked_capture` are already exported (`VS/api.py:73-106`).
8. **Records with incomplete code.** `no_code_reason` (`SDK/core/provenance.py:8-30`) covers no `base_commit` (MLflow imports) and `code_missing`; `refuse_no_code(meta, action=)` (`EXP/cli/provenance.py:113-127`) logs it. `from_snapshot` records (`SDK/core/from_snapshot.py:38-101`) have `code_verstr` = the exported snapshot's verstr, `has_*: False`, no `code`, no `diff_hash` — a dirty export's code is only recoverable if an object `<code_verstr>.*` exists in the same store (list via `storage.list_record_names(code_app(app))`). `start_run(snapshot=False)` **no longer exists** (`157d864`; `tests/test_code_store_dedup.py:237`) — that blocker is gone.
9. **Fork/rewind: reuse the ref resolution and the linking shape, not the seeding.** `resolve_run(storage, app, ref, action)` (`SDK/core/fork.py:42-50`) resolves `-v`/`latest` and checks existence; `rewind.py:_ref` (`EXP/cli/rewind.py:15-19`) maps `-v`/`--latest` to a ref. A fork is a *new snapshot of the live tree* plus an inherited log; `seed_fork` writes `forked_from: {verstr, step}` via `update_metadata` after creation (`fork.py:92-100`). A rerun is the inverse (same code, fresh log), so `rerun_of` goes into the template at claim time instead. `rewind_run`'s liveness check (`derive_status(prior_state, observed_at=run_state_observed_at(...)) == RUNNING`, `fork.py:118-131`) is the pattern for the "source still running" warning. `show` prints fork origin via `fork.print_lineage` (`EXP/cli/fork.py:33-39`, called at `experiment.py:734`) — the natural home for `Rerun of:`. Rows get `forked_from`/`forked_from_step` via `_fork_fields` (`SDK/core/fold.py:298-301`); detail via `EXP/ui/readers/experiment_detail.py:231`; UI via `WEB/pages/RunFork.tsx`.
10. **Output capture comes for free with `_Supervision`.** It tees stdout/stderr into the `output.log` artifact unless `--no-capture-output` (`EXP/cli/output_tee.py:23-34`); `popen_kwargs` sets `PYTHONUNBUFFERED=1` via `setdefault`, only when capturing. `--output-cap-mb` applies too. Nothing to add — but the child env must be merged via `extra_env`, which is applied *after* the defaults (`run.py:287-296`).
11. **Sweep trials depend on env the rerun won't have.** The sweep agent reuses `_create_experiment` + `_Supervision` (`EXP/cli/sweep/agent.py:71-104`) and passes `VMN_SWEEP_ID`, `VMN_SWEEP_TRIAL`, `VMN_SWEEP_PARAMS` via `extra_env`; `sweep_params()` reads `VMN_SWEEP_PARAMS` (`SDK/sdk/sweep.py`). The recorded command already carries the `--name=value` args, but a script reading `sweep_params()` would get `{}`. The trial's params are in its `create` entry (`extra_create_data={"params", "tags"}`).
12. **An SDK child becomes an inner run.** Under a supervisor, `start_run()` parents itself to `VMN_EXPERIMENT_ID` (`pick_parent`, `SDK/sdk/create.py:129-152`) and captures the checkout it runs in (`gitmode/checkout.py:33-61`) — inside the rerun workspace. So rerunning an SDK run yields outer rerun record + inner SDK run whose metrics live on the inner one.
13. **Nested runs must land in the original store.** Storage defaults to `<root>/.vmn/…/experiments` unless `VMN_EXPERIMENT_DIR` is set (`SDK/core/storage_resolve.py:79-100`); inside the workspace `root` is the workspace → deleted on cleanup. Child env must set `VMN_EXPERIMENT_DIR=<original vmn_root_path>` (unless already set) and `VMN_WORKING_DIR=<workspace cwd>`, and pop `VMN_RESUME_RUN_ID` (`SDK/sdk/resume.py:25-36`).
14. **Lock:** taken unless the action is in `read_only_actions` (`VS/cli/entry.py:51-63,209`; set at `EXP/cli/plugin.py:334-337`); `experiment_run` releases it after create (`run.py:231-232`); `handle_experiment` passes `repo_lock` only to `run` (`experiment.py:351-354`). Auto-init runs only for `create`/`run` (`experiment.py:337`).
15. **CLI surface:** actions are `EXPERIMENT_ACTIONS` in `EXP/cli/plugin.py:31-37`, flags in `_add_experiment_parser` (`plugin.py:40-170`, one shared parser — `--dry-run`, `--keep`, `-o` already exist for prune/export; help texts are action-prefixed). `vmn-exp <action>` is rewritten to `exp <action>` (`EXP/cli/main.py:15-19`). Git-free (`--from-snapshot`) dispatch is a fixed table (`plugin.py:267-276`); an action absent from it errors "requires a git repository" — right for rerun. `--` splitting gives `args.run_cmd` (`VS/cli/args.py:47-50`; `None` without `--`, `[]` with bare `--`).
16. **Rows/query:** `fold_row` (`SDK/core/fold.py:304-342`) builds rows from metadata; the index stores metadata, not rows, and fork added row keys without bumping `SCHEMA_VERSION` (`SDK/core/index_store.py:20`, `exp-index-7`) — a new metadata-derived key needs no bump. `ROW_FIELDS` is fixed (`SDK/core/query.py:62-69`); UI mirror `WEB/util/querySuggest.ts:5-11` (already lags: no `forked_from`). Run detail returns full `metadata` plus top-level `forked_from` (`experiment_detail.py:201-233`).
17. **UI jobs can't host a rerun** (`subprocess.run(capture_output=True, timeout=…)`, `EXP/ui/jobs.py:240-252`) → **no Rerun button in v1**. The run page's "reproduce" card lists CLI hints (`WEB/pages/Run.tsx:70-72`).
18. **File sizes** (edit minimally, put logic in new files): `EXP/cli/experiment.py` 1095, `EXP/cli/run.py` 485, `SDK/sdk/run.py` 603, `SDK/core/query.py` 485, `EXP/cli/plugin.py` 362, `SDK/core/fold.py` 342, `EXP/ui/readers/experiment_detail.py` 301; `VS/api.py` 142, `VS/devversion/apply.py` 153, `EXP/cli/fork.py` 39, `SDK/core/code_store.py` 82.

## 1. Behaviour

```
vmn-exp rerun <app> -v <ref> | --latest [-- <cmd> ...]
  --dry-run            print plan (source run, command, cwd, layout, dep sources, code key, env diff, warnings)
  --keep-worktree      keep the workspace; print its path
  --worktree-dir D     parent dir (default: mkdtemp "vmn-rerun-<app>-*" in $TMPDIR); must be empty/missing, not inside the repo
  --cwd P              child cwd relative to the restored app root (overrides recorded cwd)
  -- <cmd...>          replace the recorded command (bare `--` is an error)
  reused from run:     --note --name --parent --no-env --input -f --heartbeat-interval --kill-grace-sec
                       --no-system-metrics --sync-interval --no-capture-output --output-cap-mb
  rejected in v1:      --fork-from/--fork-step (see Q9), --from-snapshot / VMN_SNAPSHOT_METADATA (git required)
```

- Ref is **required** (no implicit latest — this launches work). Resolution via `resolve_run(storage, app, ref, "rerun")`.
- Flow: resolve → `storage.load` (code resolved) + `load_run_state` + merged log → validate code + invocation → capture env + print env diff → build workspace → claim record → release lock → supervise with `_Supervision(cwd=…, extra_env=child_env(…))` → cleanup in `finally` unless `--keep-worktree`.
- Exit code = child's (`128+N` on signal); 1 on setup errors. Prints the new verstr like `run`. `output.log` captured as for `run`.
- **Errors** (exit 1, no record, no worktree): no code / `code_missing` (`refuse_no_code(meta, action="rerun")`); dirty `from_snapshot` record whose code object can't be found by prefix; no command (`create`-only run → "pass one after `--`"); SDK run without override → hint `vmn-exp rerun app -v X -- python train.py`.
- **Warnings:** env diff (`env_diff(orig, new, cap=30)`, orig from `env.yml`); `untracked_skipped` files missing; `_predates_untracked_capture`; absolute argv paths under the live repo remapped into the worktree; legacy run with no `cwd` → running from app root; source run still `running`; SDK source → "metrics will be on the inner run"; sweep trial → `VMN_SWEEP_PARAMS` re-exported (Q6).

## 2. Data model

- **New record `metadata.yml`:** `rerun_of: <orig verstr>` + an **allowlist** copy of the original's code identity: `base_version, base_commit, branch, remote, app_name, dirty_states, has_working_tree_patch, has_local_commits_patch, has_untracked_files, has_dep_patches, diff_hash, untracked_skipped, changesets, code`. Fresh: `timestamp`, `note`, `env` (via `create_run(env=)`). Not copied: `verstr, code_verstr` (restamped by `create_run`), `parent, name, archived, tags, forked_from, rerun_of, from_snapshot, imported_from, code_missing`.
- **No patches copied.** `create_run(storage, app, code_verstr_of(orig), template, {}, …)` — the record shares the original's code object, and its `C.rN` name keeps that object alive through prune (Finding 4).
  - Legacy (pre-code-store) original with in-record patches and a `diff_hash`: promote them once with `store_code(storage, app, code_key(code_verstr, diff_hash), patches, _patch_summary(patches))` and reference that key (Q5). Without `diff_hash` (clean) there is nothing to store.
  - Dirty `from_snapshot` original: `find_code_key(storage, app, code_verstr)` (new, `code_store.py`, exactly one complete `<code_verstr>.*` object) → reference it; none/ambiguous → refuse.
- `create` entry: note defaults to `"rerun of <orig>"`; the original create entry's `params` (`-f`, sweep trial params) are copied; tags/inputs not.
- **`run_state.yml` (all future runs):** `runner: "exp run" | "sdk"`, `cwd` (repo-relative POSIX, `"."` at root, `null` outside the repo / git-free); `workdir` with `--keep-worktree`. Legacy records without `runner` = `exp run`. Sweep trials record `exp run`.
- Row + query: `fold_row` adds `rerun_of`; `ROW_FIELDS += rerun_of`; detail adds top-level `rerun_of` like `forked_from`.
- Parent via normal `_resolve_parent`; `rerun_of` points at the direct source (a rerun of a rerun points at the rerun).

## 3. Modules

| File | Change |
|---|---|
| **new** `SDK/core/rerun.py` (~150, pure, no `version_stamp` import) | `RUNNER_CLI/RUNNER_SDK`; `Invocation(command, cwd, runner)`; `rerun_blocker(meta)` (wraps `no_code_reason` + dirty-from_snapshot rule); `recorded_invocation(run_state, log)`; `resolve_command(inv, override)`; `rerun_template(meta, rerun_of, note, timestamp)`; `code_verstr_of(meta)`; `create_params(log)`; `repo_relative_cwd(cwd, root)`; `remap_live_paths(argv, live_root, work_root)`; `child_env(work_cwd, experiment_dir, sweep_params=None)` → dict for `extra_env` |
| `SDK/core/code_store.py` (+~10) | `find_code_key(storage, app, code_verstr)` |
| **new** `EXP/cli/rerun_workdir.py` (~220) | `plan_workdir(...)` for `--dry-run`; `prepare_workdir(vcs, metadata, patches, parent_dir) -> (Workdir, err)`: `git worktree prune`; layout via facade `island_layout` (deps = `{p: {"rel_path": p}}` from `changesets`); main + deps via facade `create_dep_worktree` at the recorded hash, `_clone_at` fallback when `_commit_exists` fails; patches strictly (failures fatal → cleanup); never writes `vmn_metadata.yml`. `Workdir.cleanup()` via `remove_registered_worktree`; `exit_on_termination()` turns SIGTERM/SIGHUP during *setup* into `SystemExit(128+N)` so cleanup runs (supervision has its own `SignalForwarder`) |
| **new** `EXP/cli/rerun.py` (~200) | `experiment_rerun(vcs, params, storage, args, repo_lock=None)`: the §1 flow; `create_run(...)`; release lock; `_Supervision(storage, app, verstr, args, exp_conf, extra_env=child_env(...), cwd=, root=).run(argv)` in `try/finally` |
| `EXP/cli/run.py` (+~10) | `_Supervision(..., cwd=None, root=None)`; `_start` uses `self.cwd or _child_cwd()`; run state adds `runner`, `cwd = repo_relative_cwd(...)`; `experiment_run` passes `root=vcs.vmn_root_path` (sweep agent unchanged → `cwd` from its vcs if passed, else `null`) |
| `SDK/sdk/run.py` (+~5) | `_initial_state` adds `runner: "sdk"`, `cwd` (best-effort; root known in git mode) |
| `EXP/cli/experiment.py` (+~4) | dispatch `rerun` with `repo_lock` (next to `run`); not in the auto-init branch |
| `EXP/cli/fork.py` (+~3) | `print_lineage` prints `Rerun of: <v>` |
| `EXP/cli/plugin.py` (+~10) | `rerun` in `EXPERIMENT_ACTIONS`; `--keep-worktree`, `--worktree-dir`, `--cwd`; `--dry-run` help mentions rerun. **Not** read-only; **not** in the git-free dispatch table |
| `SDK/core/fold.py`, `SDK/core/query.py` | `rerun_of` row key / field |
| `EXP/ui/readers/experiment_detail.py` (+1) | `"rerun_of": metadata.get("rerun_of")` |
| `VS/devversion/apply.py` | `_apply_patches_to_workdir` returns list of failed steps (callers ignore it → compatible), tarball failure included; `git am` gets a fallback identity only when none is configured |
| `VS/api.py` | expose `island_layout` (`cli.worktree_create:_island_layout`), `create_dep_worktree`, `remove_registered_worktree` (`cli.worktree_git`); update `tests/test_api_facade.py::_EXPECTED_ALL` first and the "All N names" docstring |
| `WEB/types.ts`, `WEB/pages/RunFork.tsx`, `WEB/pages/Run.tsx`, `WEB/util/querySuggest.ts` | "rerun of" link beside the fork origin, "reruns →" leaderboard link with `?q=rerun_of = "<verstr>"`, `vmn-exp rerun` hint in the reproduce card when a command exists, `rerun_of` (and missing `forked_from`) in `ROW_FIELDS`; rebuild bundle separately |

## 4. Tests first

- **`tests/test_exp_rerun_core.py`** (pure): `test_template_keeps_code_identity_fields_and_code_key`, `test_template_drops_run_identity`, `test_template_records_rerun_of`, `test_code_verstr_of_prefers_recorded_then_verstr`, `test_blocker_no_base_commit_names_import_source`, `test_blocker_code_missing_refused`, `test_blocker_from_snapshot_dirty_without_code_refused` / `…_clean_allowed`, `test_invocation_from_run_state`, `test_invocation_falls_back_to_last_run_log_entry`, `test_invocation_none_for_created_only`, `test_legacy_state_without_runner_is_exp_run`, `test_sdk_invocation_refused_without_override_and_hint_prefixes_python`, `test_override_replaces_command_keeps_recorded_cwd`, `test_empty_override_is_error`, `test_create_params_from_create_entry`, `test_repo_relative_cwd_inside_root_outside`, `test_remap_live_paths_moves_absolute_repo_paths_only`, `test_child_env_sets_working_dir_experiment_dir_and_drops_resume_id`, `test_child_env_reexports_sweep_params`.
- **Code store:** `test_find_code_key_by_code_verstr_prefix`, `test_find_code_key_none_when_missing_or_ambiguous`.
- **Row/query/detail:** `test_row_carries_rerun_of`, `test_query_filters_on_rerun_of_and_null`, `test_detail_returns_rerun_of`.
- **Run state:** `test_run_state_records_runner_and_repo_relative_cwd`, `test_run_state_cwd_is_dot_at_repo_root`, `test_supervision_cwd_param_overrides_child_cwd`, `test_sdk_run_state_records_runner_sdk`.
- **Materialize/facade:** `test_apply_patches_reports_failed_steps`, `test_apply_patches_success_returns_empty`, `test_exact_surface` (+`island_layout`, `create_dep_worktree`, `remove_registered_worktree`), existing `test_packaging_split.py` stays green.
- **`tests/test_exp_rerun_workdir.py`:** `test_prepare_creates_detached_worktree_at_base_commit_with_patches_and_untracked`, `test_prepare_layout_places_deps_beside_app`, `test_prepare_dep_at_recorded_hash_with_dep_patch`, `test_prepare_falls_back_to_clone_when_commit_missing_locally`, `test_prepare_patch_failure_is_fatal_and_leaves_nothing`, `test_missing_dep_is_fatal`, `test_cleanup_removes_worktree_registration_and_dir`, `test_prepare_never_writes_vmn_metadata_yml`, `test_exit_on_termination_raises_systemexit_and_restores_handlers`, `test_plan_workdir_reports_sources_without_touching_disk`.
- **`tests/test_exp_rerun.py`** (integration): `test_rerun_executes_recorded_command_against_original_code` (dirty + untracked original, live tree modified afterwards, metric reflects original, live tree untouched), `test_rerun_links_rerun_of_shares_code_verstr_and_code_key`, `test_rerun_uploads_no_new_code_object`, `test_rerun_survives_pruning_original` (code object kept while the rerun exists, dropped with the last one), `test_rerun_of_legacy_in_record_patches_promotes_code_object`, `test_rerun_of_clean_run`, `test_rerun_refuses_code_missing`, `test_rerun_uses_recorded_subdir_cwd`, `test_cwd_flag_overrides`, `test_cwd_outside_workspace_rejected`, `test_override_after_double_dash_is_recorded_as_command`, `test_child_exit_code_propagates_and_status_failed`, `test_output_log_captured`, `test_worktree_removed_by_default`, `test_keep_worktree_prints_and_keeps_path`, `test_setup_failure_creates_no_record`, `test_dry_run_creates_nothing_and_prints_plan`, `test_created_only_run_errors_no_command`, `test_sdk_run_errors_with_hint_and_override_yields_inner_run`, `test_imported_run_refused_no_code`, `test_ref_required`, `test_env_diff_warning_printed`, `test_no_env_skips_capture_and_diff`, `test_untracked_skipped_warning`, `test_sweep_trial_rerun_sees_sweep_params_and_is_not_a_trial`, `test_nested_create_inside_rerun_lands_in_original_store_with_parent`, `test_rerun_refused_in_from_snapshot_mode`, `test_show_prints_rerun_of`, `test_list_query_rerun_of`.
- **Lock/signals:** `test_rerun_supervision_leaves_repo_lock_free`, `test_sigterm_during_rerun_forwards_records_signal_and_cleans_worktree`.
- **Vitest** `WEB/pages/__tests__/RunRerun.test.tsx`: rerun-of link, reruns query link, CLI hint only with a command, `querySuggest` offers `rerun_of`.

## 5. Docs

`docs/experiments.md` (`### rerun`, run_state `runner`/`cwd`, row field, prune keeps code for reruns); `CLAUDE.md` (action + bullet, query field, run_state fields); `VS/cli/skill.py` + **regenerate** `docs/agent-skill.md` (`vmn skill --methodology`); `docs/ui.md` (links); `docs/sdk.md` (SDK runs rerunnable only with explicit `--`, and become inner runs).

## 6. Worktrees

A core (`core/rerun.py`, `find_code_key`, row/query/detail) · B run-state recording (`run.py`, `sdk/run.py`; agree `repo_relative_cwd` signature with A) · C workspace (`apply.py`, facade, `rerun_workdir.py`) · D UI · **E integration after A+B+C** (`cli/rerun.py`, plugin, dispatch, `print_lineage`, integration/lock/signal tests, docs, skill regen, `/simplify`).

## 7. Risks

- **Gitignored data (datasets, `.env`, checkpoints) won't exist in the worktree** — biggest usability risk; document loudly (maybe `--link`).
- Worktree inside the repo would dirty the checkout → default `$TMPDIR`, reject in-repo dirs.
- SIGKILL of the supervisor leaks a tmp dir + worktree registration → `git worktree prune` at each start.
- No `base_commit` locally → clone from `remote`; air-gapped with no remote fails clearly.
- Code object only on the remote store: `load` must reach it (cached backend `load_record` falls back to remote); verify on S3/GCS/Azure that `list_record_names(code_app)` works for `find_code_key`.
- An SDK child inside the workspace captures the workspace: with local commits (`git am` → new hashes) its inner run gets a different `code_verstr` than the original; with only working-tree/untracked dirt it should match. Document; don't try to fix in v1.
- `python` resolves from the current PATH — that's what the env diff is for.

## 8. Open questions

1. `-- cmd` replaces the whole command, or also an append / `--set k=v` (MLflow `-P`) mode?
2. Legacy records without `runner`: treat as `exp run`, or require `--`? Should the SDK also record `sys.executable` so SDK runs can be rerun without `--`?
3. Inherit create-entry params (yes), tags / inputs / name (no)?
4. Deps: always materialize and fail hard, or `--no-deps` / `--live-deps`?
5. Legacy in-record patches: promote into a code object (proposed) or pass them as the rerun record's own patches?
6. Sweep trials: re-export `VMN_SWEEP_PARAMS` from the create params (proposed), and `VMN_SWEEP_ID`/`VMN_SWEEP_TRIAL` too (no — the rerun is not a trial)?
7. SDK source runs: accept outer rerun record + inner SDK run, or have the SDK child adopt the rerun record (e.g. `VMN_RERUN_OF` read by `start_run`)?
8. Workspace: delete on failure too? `$TMPDIR` vs `../vmn-reruns/`? `--link <path>` for ignored data in v1?
9. `--fork-from` with rerun (same code, seeded history = "resume from step N"): reject in v1 (proposed), or support via the existing `fork.fork_source`/`fork.seed` calls?
10. Env diff: warn only, or `--strict-env`? Confirm no UI Rerun button in v1.
