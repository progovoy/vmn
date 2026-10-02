# Plan 10: `vmn snapshot` back as a vmn command; experiments reuse it

> Base: master @ f5a2b2d (rerun workspace merged: `apply._apply_patches_to_workdir` returns failed steps;
> facade has `island_layout`/`create_dep_worktree`/`remove_registered_worktree`; code store has
> `publish_code`/`find_code_key`).
> Prefixes: `VS/` = packages/vmn/src/version_stamp/, `SDK/` = packages/vmn-exp-sdk/src/vmn_exp/,
> `EXP/` = packages/vmn-exp/src/vmn_exp/.

## Decisions taken (open questions answered for implementation)

1. Store: with vmn-exp installed, `vmn snapshot create` follows the configured experiment store
   (`--store` > `VMN_EXPERIMENT_STORE` > conf), so snapshots, runs and code share one store;
   `--local` forces local only. Without vmn-exp, local only.
2. No hidden `--backend/--bucket/--prefix/--endpoint-url` aliases; `--store` only.
3. Add `vmn snapshot delete -v REF` (so snapshot-referenced code can be collected) and `--json` for `list`/`show`.
4. Same diff + new dep commits → extended verstr (identity unchanged for experiments).
5. Re-create of the same state keeps the timestamp (stable `@N`).
6. UI `/snapshots` endpoints: later (not in this change).
7. Keep the `.vmn/vmn-code/<app~>/experiments/` code dir layout.
8. The tests that assert the snapshot command is absent (§9) are replaced/inverted — the user explicitly
   asked to bring the command back.

## 0. Findings

1. d4954f8 removed the `snapshot` CommandSpec (`EXP/cli/plugin.py` `_add_snapshot_parser`, `_handle_snapshot`), the create/list/show/note/diff/export/restore functions (old `EXP/snapshot/__init__.py`), UI `/snapshots` (`EXP/ui/readers/snapshots.py`) and the `snapshot_create` job. Still there: capture/materialize/apply in `VS/devversion/`; `_build_snapshot_metadata`, `_patch_summary`, `_save_safety_snapshot`, `_restore_with_safety_net` in `EXP/snapshot/__init__.py` (176 lines); capture + code store in `EXP/gitmode/capture.py` (`Capture`, `capture_snapshot`, `ensure_code`).
2. Code store (`SDK/core/code_store.py`): objects are records `<code_verstr>.<full diff_hash>` of pseudo-app `vmn-code/<app~>` in the experiment-subdir store (locally `.vmn/vmn-code/<app~>/experiments/<key>/`); `metadata.yml` is the completion marker holding only the payload summary (`has_*`, `untracked_skipped`) — no `base_commit`, no `changesets`, dep commit hashes aren't in the diff hash. **A code object cannot be a full snapshot → a snapshot is a reference record, like a run.**
3. Packaging (`tests/test_packaging_split.py`): `version_stamp` never imports `vmn_exp`; SDK core/storage never import `version_stamp` → the record/code-store *format* must be implemented on both sides.
4. Local layout `.vmn/<app>/snapshots/<verstr>/metadata.yml` is where safety snapshots live today and every test reads it via `_storage(app_layout, subdir="snapshots")`. The same dir also holds committed `create_snapshots` verinfo files (`VS/stamping/publisher.py:948`); they lack `verstr`, so `parse_record_metadata` already filters them. Keeping this path = no test changes, no migration.
5. **Remote collision bug:** `open_store(uri, subdir)` uses `uri.path or vmn-<subdir>` as prefix (`SDK/storage/registry.py` `default_prefix`). With an explicit `s3://bucket/prefix`, "snapshots" and "experiments" share one key space, so a safety snapshot uploads as `<prefix>/<app>/<verstr>/` and lists as a run (`file://` unaffected).
6. **Data-loss bug:** `_reset_worktree` runs `git clean -fd` (`VS/devversion/apply.py`); untracked files over `VMN_SNAPSHOT_MAX_FILE_MB`/`TOTAL_MB` are excluded from the safety tarball (`untracked_skipped`) and then deleted — permanent loss on restore/goto today.
7. `_unique_snapshot_verstr` compares only `diff_hash`: same diff with moved dep HEADs reuses the old verstr and an idempotent re-save rewrites its `changesets`.
8. `--from-snapshot` container runs (`SDK/core/from_snapshot.py`) set every `has_*` False and no `code:`; `no_code_reason` passes (base_commit set), so goto/restore of a *dirty* exported snapshot silently restores the clean base. Only rerun guards it (`SDK/core/rerun.py`).
9. `prune` → `drop_unused_code(storage, app, code_verstrs)` only knows runs; it would delete a code object a snapshot references.
10. Built-in commands always take the repo lock (`VS/cli/entry.py _takes_repo_lock`); dispatch needs `add_arg_<cmd>` in `VS/cli/args.py`; `verify_user_input_version` skipped via `set_defaults(strict_version=False)`.
11. `test_sdk_capture.py` monkeypatches `vmn_exp.gitmode.capture.capture_snapshot` (called as a module attribute in `checkout.py`); dedup tests spy on `version_stamp.devversion.untracked._collect_untracked_tarball` — the shim must keep both working.
12. Over-300-line files (minimal edits, logic in new files): `VS/cli/args.py` 590, `VS/cli/commands.py` 1188, `VS/cli/entry.py` 354, `EXP/cli/experiment.py` 1095, `EXP/cli/plugin.py` ~370, `EXP/cli/prune.py` 349.

## 1. Behaviour & CLI

`vmn snapshot [action] <app>`, default `create`. `local` command. Lock-free: `list`, `show`, `diff`, `export`. `create`, `note`, `restore`, `delete` take the repo lock.

| action | behaviour |
|---|---|
| `create [--note T] [--meta k=v]... [--meta-file F] [--store URI] [--local]` | capture identity (lightweight); clean tree → stderr "No local changes to snapshot (working tree is clean)", exit 0 (UI noop marker relies on it); build payload only when the code object is missing (`ensure_code`); write thin record; last stdout line = verstr; warn with names of cap-skipped paths. Re-create of the same state keeps the record (same verstr, timestamp unchanged) and only updates note/user_meta when given |
| `list [--last N] [--filter k=v]... [--verbose] [--json]` | `[N] verstr  (2m ago) - note k=v`; N = storage index (oldest first) regardless of filters; safety snapshots listed ("auto-saved before restore"); verinfo dirs skipped |
| `show [-v REF/--latest] [--json]` | metadata YAML + patches + tarball member list; default latest |
| `note -v REF --note T` | update note |
| `diff [-v A] [--to B/current] [--tool X]` | real-tree diff (`_diff_real_tree`/`_diff_with_external_tool`); `--to` defaults to `current`; stamped versions synthesized from the tag |
| `export [-v REF] [-o out.tar.gz/dir]` | materialize (`_materialize_workdir`), strip `.git`, write `vmn_metadata.yml` (with `code`, `code_verstr`), tarball when output ends .tar.gz/.tgz; default `<verstr>.tar.gz`; any failed step from `_apply_patches_to_workdir` → exit 1 |
| `restore [-v REF/--latest] [--force]` | safety net (§4), reset, `_apply_snapshot_patches`; default latest |
| `delete -v REF` | delete the record; then drop its code object if no run/snapshot references it |

Refs: full verstr, unique dev-verstr prefix (ambiguous lists candidates), `--latest`/`latest`/`@latest`, `@N`. `vmn goto -v <full dev verstr>` keeps working for snapshots and runs.

Store: `--store URI` (remote needs vmn-exp; without it → error "remote snapshot stores need vmn-exp: pip install vmn-exp"); with vmn-exp, `VMN_EXPERIMENT_STORE` and conf `experiment.storage.uri` apply too; `--local` forces local.

Hints: dirty-tree hint in `_get_repo_status` → `'vmn snapshot create <app>' to save your work`. Safety net keeps printing `Current work saved as X — restore it anytime with: vmn goto -v X <app>`.

## 2. Storage layout & format

- **Snapshot record** local: `.vmn/<app>/snapshots/<safe_verstr>/metadata.yml` (+ `.gitignore` `*`). Fields: `verstr`, `code_verstr` (7-char), `base_version`, `base_commit`, `branch`, `remote`, `timestamp`, `note`, `app_name`, `dirty_states`, `has_*`, `untracked_skipped`, `diff_hash` (full), `changesets`, `user_meta`, `code: <key>`; `auto: safety` on safety snapshots. Clean trees never saved.
- Legacy fat records (inline patches, no `code:`) stay readable; `load` resolves `code:` only when present.
- **Code object:** unchanged (`vmn-code/<app~>` records of the experiment-subdir store); `version_stamp` writes the same bytes (`PATCH_FILES`, `deps/<safe_dep>/`, `yaml.dump(sort_keys=True)`, `+` → `_plus_`).
- **Remote** (vmn-exp opener only): records → reserved pseudo-app `vmn-snapshot/<app~>` of the experiment store (S3 tag form `vmn-snapshot-<app~>`), fronted locally by `LocalSnapshotStorage(root, "snapshots")`; code → the experiment store; `ensure_code` calls `mirror_record`/`publish_code` when the object is local-only. Add `"vmn-snapshot"` to `RESERVED_APPS`.
- **Identity:** verstr `<base>-dev.<commit7>.<diff7>`, deterministic; collision → extend the hash (`_DIFF_HASH_LENGTHS`); "same state" = same full `diff_hash` **and** same dep `changesets` hashes (legacy record without `diff_hash` = collision). Code key stays `<code_verstr>.<diff_hash>` (7-char) even when the snapshot verstr is extended.

## 3. Modules

### vmn (`version_stamp`)
New package `VS/snapshot/`:
- `__init__.py` (~10) docstring.
- `record.py` (~120): `METADATA_FILE`, `PATCH_FILES`, `safe_verstr`/`unsafe_verstr`, `safe_dep_name`, `patch_summary`, `skipped_untracked`, `build_record_metadata` (moved from `_build_snapshot_metadata`, + `code_verstr`), `same_state(stored_meta, diff_hash, changesets)`.
- `local_store.py` (~190): `LocalRecordStore(root, subdir)` — `save`, `load_record` (via `parse_record_metadata`), `load` (resolves `code:`), `load_metadata`, `exists`, `list_verstrs`, `list_snapshots` (by timestamp), `list_record_names`, `update_metadata`, `update_note`, `delete`, `load_file`; atomic writes.
- `code_store.py` (~90): mirror of `SDK/core/code_store.py` (`CODE_APP`, `CODE_MISSING`, `code_app`, `code_key`, `stored_code`, `store_code`, `publish_code` duck-typed on `mirror_record`, `resolve_code`).
- `capture.py` (~130): moved from `EXP/gitmode/capture.py` — `SnapshotCapture`, `capture_identity(vcs, status=None)`, `ensure_code(code_store, vcs, captured)`, `_with_untracked_payloads`, `_repos_with_untracked` (calls `devversion.untracked.untracked_payload` so existing spies keep working).
- `refs.py` (~70): `resolve_snapshot_ref(store, app, ref, latest=False)` (port of `SDK/core/resolve_ref._resolve_verstr`).
- `stores.py` (~90): `SnapshotStores(records, code, where)`; `open_snapshot_stores(vcs, params)` — registered opener first, else local; `--store` without opener → error.
- `create.py` (~150), `listing.py` (~150, incl. `relative_timestamp`, `--json`), `restore.py` (~160: `load_snapshot`, `save_safety_snapshot`, `restore_with_safety_net(vcs, params, metadata, patches, stores=None, force=False)`, `snapshot_restore`, `goto_snapshot`), `export.py` (~160: `snapshot_export`, `snapshot_diff`, `_load_or_synthesize`), `delete.py` (small).

Other vmn files:
- `VS/cli/snapshot_cmd.py` (~200): `add_arg_snapshot` (old flags minus backend/bucket/prefix/endpoint, plus `--store`, `--local`, `--force`, `--json`, `strict_version=False`), `handle_snapshot`.
- `VS/cli/constants.py`: `VMN_ARGS["snapshot"]="local"`, `SNAPSHOT_ACTIONS`, `READ_ONLY_ACTIONS={"snapshot": {"list","show","diff","export"}}`.
- `VS/cli/args.py`: one-line import. `VS/cli/entry.py`: import `handle_snapshot`; `_takes_repo_lock` consults `READ_ONLY_ACTIONS`.
- `VS/cli/plugin_api.py`: `register_snapshot_store_opener(fn)`, `snapshot_store_opener()`; `load_dev_version` falls back to `snapshot.restore.goto_snapshot` when no loader is registered ("Dev version X not found in local snapshots (experiment runs need vmn-exp)").
- `VS/cli/commands.py`: hint text. `VS/devversion/capture.py`: `_unique_snapshot_verstr(..., changesets=None)`.
- `VS/api.py`: new block at the end of `_LAZY_REGISTRY`: `SnapshotCapture`, `capture_identity`, `ensure_code`, `build_record_metadata`, `patch_summary`, `open_snapshot_stores`, `load_snapshot`, `restore_with_safety_net`, `register_snapshot_store_opener`, `relative_timestamp`, `LocalRecordStore`; update the docstring count and `tests/test_api_facade.py::_EXPECTED_ALL` first.

### vmn-exp
- `gitmode/capture.py` → shim (~30): `Capture = api.SnapshotCapture`, `capture_snapshot = api.capture_identity`, `ensure_code = api.ensure_code` (module attributes).
- `snapshot/__init__.py`: drop moved bodies; keep re-exports ~40 tests import; alias `_build_snapshot_metadata`, `_patch_summary`, `_restore_with_safety_net`, `_relative_timestamp` to api names; keep `_get_storage` as the legacy snapshots store.
- New `snapshot/stores.py` (~120): `open_exp_snapshot_stores(vcs, params)` → `SnapshotStores(records=CachedSnapshotStorage(LocalSnapshotStorage(root,"snapshots"), _SnapshotAppRemote(open_store(uri,"experiments"))), code=_get_experiment_storage(vcs, params))`; None when nothing configured or `--local`. `_SnapshotAppRemote` maps `app` → `vmn-snapshot/<app~>`.
- `cli/plugin.py`: `register_dev_version()` also registers the store opener (idempotent). `_dev_version_loader` uses `api.restore_with_safety_net`.
- `cli/code_record.py`: search order local experiments → remote experiments → snapshot records → legacy snapshots store; refuse dirty from-snapshot records without code.
- `cli/prune.py`: pass `keep=` (code keys referenced by local + remote snapshot records) to `drop_unused_code`; skip dropping when the snapshot listing fails.

### vmn-exp-sdk
- `core/code_store.py`: `SNAPSHOT_APP="vmn-snapshot"`, `snapshot_app()`, `drop_unused_code(..., keep=())`, `referenced_code_keys(metadatas)`.
- `core/reserved.py`: add `"vmn-snapshot"`.
- `core/from_snapshot.py`: when `snap_meta` has `code`, copy `rerun.CODE_IDENTITY_FIELDS` and allocate under `snap_meta.get("code_verstr") or verstr`.

## 4. Safety net (restore/goto)

1. Capture current state (`allow_clean=True`); clean or same state as target → save nothing.
2. Else save a snapshot record (`note: auto-saved before restore`, `auto: safety`).
3. Save raises → abort (exit 1, tree untouched).
4. Safety capture skipped untracked paths (caps) → refuse, list the paths, advise raising `VMN_SNAPSHOT_MAX_FILE_MB`/`TOTAL_MB`; `vmn snapshot restore --force` overrides; goto has no override.
5. Then `_reset_worktree` (unless `deps_only`) and `_apply_snapshot_patches`.

## 5. Container flow

`vmn snapshot create app [--store s3://…] && vmn snapshot export app -o ctx.tar.gz` on the build host (needs only `vmn`); image needs only `vmn-exp-sdk` + `VMN_SNAPSHOT_METADATA`. Runs carry `code:` → goto/restore/rerun work when the store has the object, refuse clearly otherwise. `vmn-exp export` unchanged.

## 6. UI

Not in this change. goto/restore jobs reach snapshots via the shared lookup. Keep `test_ui_has_no_snapshots_endpoints`, `test_ui_has_no_snapshot_create_action`, the webui AppShell test.

## 7. Removed tests to resurrect/port (bring back `tests/helpers.py::_snapshot` + `store=`)

From `tests/test_snapshot.py`@d4954f8^: test_snapshot_create_clean_tree_message_on_stderr, test_snapshot_create_and_list, test_snapshot_latest, test_snapshot_prefix_match, test_snapshot_note_update, test_snapshot_content_addressable, test_snapshot_restore, test_snapshot_diff, test_snapshot_diff_current, test_snapshot_diff_current_no_noise, test_snapshot_metadata_hooks, test_snapshot_metadata_file, test_snapshot_export, test_snapshot_actions_require_init, test_snapshot_export_workdir, test_snapshot_export_tarball, test_snapshot_untracked_files_roundtrip, test_snapshot_untracked_ignores_gitignored, test_snapshot_diff_dev_vs_stamped, test_snapshot_list_skips_legacy_stamp_snapshots, test_snapshot_export_without_remote, test_snapshot_show_defaults_to_latest, test_snapshot_create_stdout_last_line_is_verstr, test_snapshot_at_index_addressing, test_snapshot_ambiguous_prefix_lists_candidates, test_snapshot_restore_action, test_snapshot_restore_dirty_tree_auto_saves, test_restore_same_state_skips_safety_snapshot, test_goto_dev_dirty_tree_auto_saves, test_snapshot_diff_single_version_defaults_to_current. Plus `test_fix_snapshot_list_numbers.py` (test_last_keeps_storage_numbers, test_filter_keeps_storage_numbers) and `test_fix_snapshot_capture.py` (test_skipped_untracked_recorded_in_snapshot_metadata, test_colliding_diff_hash_extends_instead_of_overwriting, test_same_diff_hash_stays_idempotent). Already ported (don't duplicate): show_dev*, dev_version_parsing, goto_dev_version, s3_*, cached_storage_*, untracked-hash, cap unit tests, materialize tests in test_dev_version_export.py. Adjust for thin records (`show` includes `code:`) and export default `<verstr>.tar.gz`.

## 8. New TDD tests

- `tests/test_snapshot_store_format.py` (A): test_vmn_record_reads_back_in_vmn_exp_storage, test_vmn_exp_record_reads_back_in_vmn_store, test_code_object_written_by_vmn_is_stored_code_for_exp, test_code_store_constants_match_the_sdk, test_verinfo_dir_is_not_a_record, test_plus_in_verstr_round_trips.
- `tests/test_snapshot_refs.py` (A): parametrized over `resolve_snapshot_ref` and `_resolve_verstr` — latest, @N, out-of-range, unique prefix, ambiguous prefix, stamped pass-through.
- `tests/test_snapshot_capture_move.py` (B): test_facade_exposes_snapshot_names, test_gitmode_capture_is_the_vmn_capture, test_same_diff_new_dep_commit_gets_a_new_verstr, test_legacy_callers_without_changesets_keep_old_behaviour.
- `tests/test_snapshot_cli.py` (C): test_vmn_snapshot_is_a_builtin_command, test_create_writes_a_thin_record_and_one_code_object, test_recreating_the_same_state_keeps_verstr_and_number, test_create_warns_about_skipped_untracked_paths, test_read_only_actions_take_no_lock, test_dirty_tree_hint_points_at_vmn_snapshot_create, test_store_flag_without_vmn_exp_is_an_error, test_list_and_show_json, test_delete_drops_unreferenced_code.
- `tests/test_snapshot_restore.py` (D): test_restore_refuses_when_safety_snapshot_would_drop_untracked_files, test_restore_force_overrides_the_cap_refusal, test_restore_aborts_when_the_safety_snapshot_cannot_be_saved, test_safety_snapshot_is_listed_and_restorable, test_goto_restores_a_legacy_fat_snapshot_record, test_restore_of_missing_code_object_refuses_before_touching_the_tree.
- `tests/test_snapshot_plain_vmn.py` (D): test_create_list_restore_without_vmn_exp, test_goto_dev_version_without_vmn_exp_finds_local_snapshot, test_goto_of_an_unknown_dev_version_names_where_it_searched.
- `tests/test_snapshot_export_diff.py` (D): test_export_writes_vmn_metadata_with_code_key, test_export_fails_when_a_patch_does_not_apply, test_diff_defaults_to_current, test_diff_against_stamped_version.
- `tests/test_installation.py` (D): test_vmn_alone_snapshots_and_restores.
- `tests/test_snapshot_code_dedup.py` (E): test_experiment_of_a_snapshotted_tree_builds_no_tarball, test_snapshot_of_an_experiment_tree_reuses_its_code_object, test_prune_keeps_code_referenced_by_a_snapshot, test_prune_drops_code_once_no_run_or_snapshot_uses_it.
- `tests/test_snapshot_remote.py` (E, moto): test_remote_snapshot_records_live_under_the_reserved_app, test_remote_snapshot_never_lists_as_a_run_or_app, test_local_only_code_object_is_published_on_remote_create, test_vmn_exp_restore_finds_a_teammates_remote_snapshot, test_legacy_remote_snapshot_store_is_still_searched.
- `tests/test_from_snapshot_code.py` (E): test_from_snapshot_run_of_dirty_snapshot_references_its_code, test_goto_of_that_run_restores_the_dirty_tree, test_dirty_from_snapshot_run_without_code_is_refused, test_run_is_named_under_the_code_verstr.

## 9. Tests contradicted by the new requirement (replace/invert — user asked for the command back)

- `test_vmn_exp_cli.py::test_vmn_has_no_snapshot_command` → test_vmn_snapshot_is_a_builtin_command (C).
- `test_vmn_exp_cli.py::test_vmn_exp_has_no_snapshot_command` → test_vmn_exp_points_snapshot_at_vmn (E).
- `test_vmn_exp_cli.py::test_dirty_tree_hint_points_at_vmn_exp_create` → replaced by the C hint test.
- `test_skill.py::test_skill_has_no_snapshot_usage` → invert (F).
- Unchanged: `test_installation::...find('snapshot') is None`, `test_dev_version_restore.py`, UI "no snapshots" tests.

## 10. Docs (F)

README `<details>` "Snapshots (WIP save points)"; docs/packaging.md; docs/experiments.md (shared code objects, prune keep, `vmn-snapshot` reserved app, lookup order, container flow); docs/client-guide.md; docs/sdk.md; docs/experiment-tracking-guide.md; CLAUDE.md (CLI bullet, plugin sentence, storage bullet, env var line); `VS/cli/skill.py` + regenerate docs/agent-skill.md; docs/plans/README.md row 10.

## 11. Worktrees

A store core → B capture move + facade → (C CLI ∥ D restore/export/goto fallback) → E vmn-exp integration → F docs/skill. Optional G UI.

## 12. Risks

Format duplicated in vmn and SDK (contract tests guard); lookup order must keep experiments first; remote alias moves new safety snapshots (old read via legacy store; phantom runs on shared prefixes not cleaned — changelog); cap refusal on restore/goto is a behaviour change (actionable message); prune keep set can't see unreadable remotes (skip dropping on listing failure); re-save keeps timestamp (document); keep `entry.py`/`args.py` edits to 1–2 lines.
