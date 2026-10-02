# Plan 9: record offline, push later (`VMN_EXP_OFFLINE=1` + `vmn exp push`)

Inspired by `WANDB_MODE=offline` + `wandb sync`.

> **Base:** re-verified against `master` @ `0096782` (after the `feature-parity` merge and
> `157d864` "store run code once per code identity"). Paths below are real:
> `S` = `packages/vmn-exp-sdk/src/vmn_exp`, `X` = `packages/vmn-exp/src/vmn_exp`.
> Nothing in the tree implements offline recording or push today.

> **The orphan-write bug (§0.3) is still real, and it is worse than first described.** It now
> has more write-through paths (alerts, output.log, media, SDK resume) and a second variant
> in which a local-only run's writes go *into another host's real record of the same name*.
> The code store adds a sibling bug (§0.4). WT1 fixes both and must merge before
> anything else.

## 0. Findings

1. **Nothing does this today.** `vmn exp export` (`X/cli/experiment.py:1028-1086`) materializes
   the workdir + a `vmn_experiment.yml` (metadata + merged log) + local artifacts into a
   tarball. That is lossy: no per-writer logs, `run_state.yml`, `env.yml`, `alerts_sent.yml`
   or code object, and nothing imports it. Its output feeds `--from-snapshot`
   (`S/core/from_snapshot.py`). It does not re-upload a record. `vmn snapshot export` is
   code only. No `push`/`sync`/`OFFLINE` exists anywhere (`EXPERIMENT_ACTIONS`,
   `X/cli/plugin.py:31-37`).
2. **Local root + remote does not work offline. It fails before the claim.** A CLI or SDK
   create goes through `CachedSnapshotStorage` (`S/storage/cached.py`), built by `open_storage`
   (`S/storage/open.py:13-36`), and fails at the first step that touches the remote:
   - `ensure_code` → `store_code` → `Cached.save` (`cached.py:38-46`) writes the code object
     locally, then **re-raises** the remote error (`X/gitmode/capture.py:63-76`,
     `S/core/code_store.py:42-44`). This only applies to a dirty tree.
   - allocation → `Cached.list_run_verstrs` (`cached.py:112-120`) calls the remote listing
     directly (not best-effort) (`S/core/writer.py:219-232`).
   - `Cached.create_exclusive` (`cached.py:48-62`) claims locally, then remotely, and
     **deletes the local copy** when the remote raises or refuses.
   - `save_file`/`save_artifact_file` (`cached.py:247-270`) re-raise remote errors.

   Only heartbeat/log sync and the `RunStatePublisher` background upload are best-effort.
3. **Existing bug: orphan writes. STILL PRESENT.**
   - **Root cause:** `Cached._ensure_local_record` (`cached.py:230-245`) returns True as soon
     as the *local* record exists. Every write-through then goes to the remote
     unconditionally, whether or not the remote holds that record.
   - **When a local-only run appears alongside a remote:** the run was created with
     `VMN_EXPERIMENT_DIR` only, or before `experiment.storage` was added to conf.yml, or by
     a git-free run that had only `--dir`, or (after this plan) offline.
   - **Every write path that leaks objects under `<prefix>/<app key>/<X>/`** (these objects
     have no `metadata.yml` and no `.claim`):
     - **Log shipping:** `flush_log` → `sync_log_to_remote` → `_ship` → `remote.save_file`
       (`S/storage/cached_logs.py:170-185`). Reached by `tag_run` (`S/core/manage.py:29-42`),
       `exp add --metrics/--note`, and the SDK heartbeat of a **resumed** run
       (`start_run(run_id=X)`, `S/sdk/resume.py:39-57`).
     - **`run_state.yml`:**
       - `RunStatePublisher` (`S/sdk/state_publisher.py:20-33,46-47`) splits the cache into
         `_local`/`_remote` and uploads raw `remote.save_file` from a background thread. It
         bypasses `_ensure_local_record` entirely.
       - `save_run_state` (`S/core/writer.py:168-173`), used by `exp run` (`X/cli/run.py:449`)
         and importers.
     - **`alerts_sent.yml`:** `_mark_sent` → `save_file` (`S/core/alerts/transitions.py:37-39,76-87`).
       It is triggered *without any user write*: `vmn exp watch` (`X/cli/watch.py`) alerts
       on every listed stuck/failed run, local-only ones included. `exp run`'s
       `alert_if_failed` and the SDK's `run_alerts` also reach it.
     - **Artifacts:** `save_artifact` → `Cached.save_artifact_file` → `upload_file`
       (`S/core/writer.py:190-196`, `S/storage/s3.py:120-125`). This covers:
       - `exp add --attach` and `run.log_artifact(s)`;
       - **`output.log`** (`S/core/output_log.py:158-159`, uploaded by `X/cli/run.py:485` and
         by `S/sdk/output_capture.py`);
       - **media**: `MediaUploads(self._save_artifact_file)` (`S/sdk/run.py:275,453-454`,
         `S/sdk/media_uploads.py`).
     - `env.yml` (`writer.py:346-349`) is written only right after a claim through the
       cache, so it is not an orphan path.
   - **Paths that are safe** (they no-op when the remote has no `metadata.yml`):
     - `update_metadata`: S3 CAS returns False (`S/storage/s3_records.py:106-113`). This
       covers archive, the sweep spec (`X/cli/sweep/handler.py:58`), `forked_from` and
       sweep `attach_run`.
     - `update_note`, for the same reason.
   - **Is S3 `save_file` guarded?** No, it is unconditional (`s3.py:114-116`).
   - **Consequence A (as before): a host claiming bare `X` inherits the offline writer's
     log lines.**
     - For the bare code verstr, `list_run_verstrs` only HEADs `metadata.yml`
       (`S/storage/s3_listing.py:164`). `create_exclusive` then checks only metadata and
       `.claim` (`s3_records.py:62-73`), so the next host claims `X` and adopts the leaked
       `log.<writer>@*.jsonl`, `run_state.yml`, `alerts_sent.yml` and artifacts.
     - `.rN`/`.<writer>` names are protected only because `list_run_verstrs` also lists the
       common prefixes (`s3_listing.py:166`), and an orphan prefix counts as "taken".
       `create_exclusive` itself never checks for leftovers.
   - **Consequence B (new, worse): write-through into a foreign record.** A local-only run
     `X` was named without seeing the remote, so the remote may already hold a *different*
     run `X`.
     - The merged listing shows only the local one: local wins in
       `list_snapshots`/`list_files` (`cached.py:135-171`).
     - Every write above then lands in the foreign record: its log grows a foreign writer,
       its `run_state.yml` and `alerts_sent.yml` are overwritten unconditionally, and
       same-named artifacts are replaced.
     - A "does the remote have `metadata.yml` for X" check (the old WT1 design) does
       **not** catch this. The gate must compare identity.
   - **Backends:** GCS and Azure (`S/storage/gcs.py:82`, `S/storage/azure.py:93`) subclass
     `S3SnapshotStorage` over an `ObjectClient` (`S/storage/object_client.py`) and sit behind
     the same `CachedSnapshotStorage` (`open.py:23-26`). So all three are affected
     identically, and one fix in `cached.py` + `state_publisher.py` covers them. Plugin
     schemes (entry points, `S/storage/registry.py`) get the same wrapper. The fix does not
     depend on the backend.
4. **New sibling bug: code-object write-through is local-first.**
   - `stored_code` reads the marker via `load_metadata` → `Cached.load_file`, which is
     local-first (`code_store.py:35-39`, `S/storage/base.py:70-76`, `cached.py:219-228`).
   - So when the code object exists *locally only*, `ensure_code` skips `store_code`. The
     run is then created on the remote with `code: <key>` pointing at nothing, and every
     other host reads it with `code_missing` (`code_store.py:47-57`, `S/core/provenance.py:17`).
   - It is reachable today with no offline mode:
     1. The first `exp create` stores the code object locally.
     2. The remote leg of `Cached.save` raises (a transient S3 error) and create fails.
     3. The retry sees the local marker, skips `store_code`, and succeeds.
   - Offline mode would make it systematic: every tree recorded offline and later re-run
     online.
   - Fix (WT1): `ensure_code` on a cache with a remote must check the marker *on the
     remote* (one GET). If the marker is local-only, upload the local payload.
5. **Code store vs push:** runs carry `code: <code_verstr>.<full diff hash>`. The payload
   lives in the pseudo-app record `vmn-code/<app with / → ~>` (`code_store.py:21-32`).
   - Objects are content-addressed, so the remote may already hold an identical one from
     another host. Push must upload it only when the remote marker is missing, and upload
     the payload before the marker (`store_code` via the remote's `save`).
   - Prune: `drop_unused_code` (`code_store.py:60-72`, called at `X/cli/prune.py:345`)
     deletes a code object once no record name of the app has its code verstr as a
     `.`-bounded prefix. On S3, claims and orphan prefixes count as names
     (`s3_listing.py:139-142`).
   - Renames keep the prefix (`<code>.rN`, `<code>.<writer>`), so ownership survives a
     rename.
   - Race: between uploading the code object and claiming the run, a remote prune can delete
     the object. Push therefore re-checks the marker *after* the claim and re-uploads it if
     it is gone.
   - `prune --local-only` (`prune.py:184-185,287`) runs `drop_unused_code` on the local half
     only. That is correct: local runs keep their local code objects until they are pushed.
6. **Collisions are names, not content.**
   - Hash-extension (`_unique_snapshot_verstr`, `X/snapshot/__init__.py:145`) applies to
     snapshots only.
   - Runs use `code_verstr`, then `.rN`, or `.<VMN_WRITER_ID>[.N]` when the env var is set
     (`S/core/writer.py:235-258`).
   - So a push collision is resolved by allocating a new run name.
7. **Mutable state:**
   - Tags and notes are append-only log entries, so they merge naturally.
   - Mutable `metadata.yml` fields, via `update_metadata`:
     - `archived` (`S/core/manage.py:20-26`);
     - `sweep` (the outer run of a sweep);
     - `forked_from` (`S/core/fork.py:97`);
     - `note` (`update_note`).
   - `alerts_sent.yml` is a mutable top-level file (a set union is safe).
8. **Sweeps.**
   - Trial slots are records of `vmn-sweeps/<app>~<sweep verstr>`, claimed with
     `create_exclusive` (`S/core/sweep/claims.py:1-110`).
   - Offline sweeps work single-host (local `O_EXCL`). The slot namespace embeds the outer
     run's verstr, so a push rename of the outer run orphans its slots unless they move too.
   - v1: push does not push `vmn-sweeps/*`. It refuses to rename a run that has `sweep`
     metadata ("skip (sweep outer run collides)").
9. **Log shipping resumes but can't be reused as-is.**
   - `_remote_log_state` assumes the same verstr.
   - When the remote holds more bytes, `_ship_new_lines` overwrites the base object and
     deletes the segments (`cached_logs.py:196-203`). That is unsafe for push.
   - The conditional `put_log_segment` (`S/storage/s3_logs.py:57-71`, `If-None-Match`, it
     bumps `seq` on conflict) is the right primitive.
10. Registry `run_ref = {app, verstr}` (`S/registry/cli.py:73`); `registry/view.registered_runs`
    exists. Registering a model against a local-only run with a remote configured writes a
    remote registry record that points at a run the remote lacks. This is the same class as
    §0.3; warn in push output, and the fix is deferred.
11. The S3 `.claim` body is empty (`s3_records.py:69`), so a crash mid-create leaves an
    unresumable invisible name.
12. **Conditional create per backend** (all flow through `ObjectClient.put_object(IfNoneMatch="*")`,
    `object_client.py:96-98`):
    - S3 uses native `If-None-Match` (AWS since 2024; MinIO supports it too).
    - GCS uses `if_generation_match=0` (`gcs.py:43-46`).
    - Azure uses `upload_blob(overwrite=False)`, which returns 409 → `TAKEN`
      (`azure.py:57-63`).
    - CAS overwrite: S3 ETag, GCS generation, Azure etag.
    - So a claim token (body = identity) and resume-by-token work unchanged on all three.
    - Plugin schemes: unknown. Push checks the capabilities it needs (`put_log_segment`,
      `log_objects`, `list_artifacts`, `create_exclusive(claim_token=)`) and refuses otherwise.
    - A `file://` store (NFS) is the *local root* in `open_storage` (`open.py:21-22`) and
      has no `put_log_segment`. It is not a push target in v1; rsync the directory instead.
13. **Storage resolution** now takes a URI:
    - Order: `--store` > `VMN_EXPERIMENT_STORE` > conf `experiment.storage.uri`.
    - `--bucket/--prefix/--endpoint-url` remain the `s3://` shorthand (`store_uri`,
      `S/core/storage_resolve.py:64-76`; `S/storage/uri.py:39-44`).
    - Env and conf mapping: `S/core/writer.py:28-44,68-90`.
    - Flags come from `add_storage_flags` (`storage_resolve.py:103-114`).
    - Factories: `_get_experiment_storage` (CLI, `storage_resolve.py:96-100`) and
      `resolve_experiment_storage` (registry, import, `sdk.models`, `storage_resolve.py:24-61`).
      Both end in `_open` → `open_storage(store_uri(params), root, buffer_logs=True)`.
14. **Tests:**
    - moto via `tests/s3_helpers.py` (`mocked_bucket`, `s3_storage`, `cached_host`,
      `record_calls`, `op_counts`, `raw_keys`, `put_raw`, `meta`, `entry`, `concurrently`).
    - In-memory GCS/Azure fakes live in `tests/object_store_fakes.py` (`install_fake_gcs`,
      `install_fake_azure`), used by `tests/test_storage_object_stores.py`.

## 1. Behaviour

**Recording with `VMN_EXP_OFFLINE=1`** (`1/true/yes/on`):
- One helper, `drop_remote_if_offline(params)`, clears `store/bucket/prefix/endpoint_url`
  after the flags/env/conf merge. It is called in `_open` (`storage_resolve.py:79-82`), so the
  CLI, the SDK and `resolve_experiment_storage` (registry, import, `sdk.models`) all get it.
- It requires a local root; otherwise it raises a `ValueError` naming `VMN_EXPERIMENT_DIR`.
  It exists because conf.yml is committed and shared with compute nodes.
- Offline runs are named `<code_verstr>.<writer_id>[.N]` (Q1).
- Code objects are stored locally only; push ships them (§2).
- **Rejected:** silently falling back to local when the remote is unreachable.

**Pushing:**
```
vmn exp push <app> (-v <ref>... | --all) [--include-running] [--prune-local] [--dry-run]
                   [--store URI | --bucket B --prefix P --endpoint-url U] [--experiment-dir D]
```
- **Local root:** `--experiment-dir` > `VMN_EXPERIMENT_DIR` > checkout.
- **Target:** `store_uri(params)`, i.e. `--store` > `VMN_EXPERIMENT_STORE` > conf
  `experiment.storage.uri` > bucket shorthand. It is opened with `open_store` directly (not
  through `CachedSnapshotStorage`).
  - A target is required and must be `is_remote()` and push-capable (§0.12). `s3://`,
    `gs://` and `az://` work; `file://` is an error with an rsync hint.
  - Push ignores `VMN_EXP_OFFLINE`.
  - It runs git-free via `_exp_run_without_repo` (`X/cli/plugin.py:226`).
  - `push` is in `read_only_actions` (`plugin.py:334-337`): no repo lock, no auto-init.
- **Selection:** `-v` (repeatable) or `--all`; neither is an error. Unpushed ancestors
  (`parent`) are included automatically, and runs are pushed in topological order (parents
  first).
- **Status gate:**
  - `running` is skipped unless `--include-running`.
  - Children of a skipped parent are skipped.
  - `stuck`, `created`, `succeeded` and `failed` are pushed.
- **Output:** one line per run (`new`, `update`, `renamed X -> T`, `up-to-date`,
  `skip (running)`, `skip (sweep outer run collides)`, `failed: …`), plus a summary that
  includes `code objects: uploaded N, already present M`. Exit 1 on any failure.
  `--dry-run` makes read-only network calls only.
- **`--prune-local`** deletes local copies that meet all of these:
  - terminal;
  - verified on the remote: metadata, per-writer log sizes, artifacts by name+size,
    `run_state` bytes, and the code marker;
  - no kept local descendants;
  - not in the local registry.

  It then runs `drop_unused_code` on the local half only, reusing `prune --local-only`'s
  path.
- **Concurrency:** a FileLock at `.push/<remote_id>/.lock`; a second push fails fast.
  `remote_id` = sha of `target.cache_identity()` (`s3.py:106-107`, it includes the scheme).
- **`--include-running`** pushes and continues. Between pushes the run reads `stuck`
  remotely (documented).
- **Deferred:**
  - `vmn exp pull`;
  - registry push (version numbers collide; warn instead);
  - `vmn-sweeps/*` slots;
  - `--query` selection.
- **No-shared-FS recipe:** rsync/tar `.vmn/<app>/experiments/` (it includes `vmn-code/`),
  then `push --experiment-dir`.

## 2. Design

- **Run identity** = sha256(`app_name|timestamp|base_commit|diff_hash|code_verstr|imported_from.run_id`).
  It excludes `verstr`, `archived`, `code` and other mutable fields. Online-mirrored and
  previously pushed runs compare equal and count as an update.
- **Code objects first:**
  1. For each run with `code: K`, `stored_code(target, app, K)`.
  2. If there is no marker, load `K` from local (`load_record(code_app(app), K)`) and
     `store_code(target, …)`: payload, then marker.
  3. After the run's claim, re-check the marker and re-upload it if a concurrent remote
     prune removed it (§0.5).
  4. If the local code object is missing (pruned locally), the run is pushed anyway and
     reported (`code missing locally`). It reads as `code_missing`, as it would anyway.
- **Collisions rename on both sides**, so the local and remote verstr stay equal. A
  name-mapping ledger would cause duplicate listings and break `CachedLogs`.
  - Renames apply only to `succeeded/failed/created` runs with no local registry ref and no
    `sweep` metadata. Running and stuck runs are skipped ("finish the run first").
  - The target is `.rN` above the union of names; the rename keeps the `<code_verstr>.`
    prefix, so code ownership is preserved.
  - Metadata gets `verstr: T` and `renamed_from: X`. Locally: `update_metadata`, `os.rename`,
    rewrite the children's `parent`, and move the ledger entry.
- **Claim token:** `create_exclusive(..., claim_token=None)` on `S3Records`, so S3, GCS and
  Azure all get it.
  - The `.claim` object stores the identity.
  - A claim without metadata whose body matches resumes.
  - An empty or mismatching claim is treated as taken.
  - Rename crash recovery goes through the ledger's `pending_target`.
- **Ledger** per run: `.vmn/<app>/experiments/.push/<remote_id>/<safe_verstr>.yml`.
  - It is a dot-dir, so listings skip it, and the storage dir's `.gitignore` of `*` already
    covers it.
  - Fields: `remote_verstr, identity, fingerprint, code_key, code_pushed, archived,
    files{sha256, etag}, log_bytes{writer}, complete, pending_target, pushed_at`.
  - A matching fingerprint plus `complete` means zero remote calls.
- **Push one run:**
  1. Push the code object.
  2. Claim, or match an existing claim.
  3. Push the other top-level files (`env.yml`, `run_state.yml`, `alerts_sent.yml`) by sha.
     - `run_state.yml`: don't clobber a copy that changed elsewhere (compare against the
       ledger etag).
     - `alerts_sent.yml`: set union.
  4. Push logs per writer from the remote offset via conditional `put_log_segment`.
     - On a mismatch, prefix-verify and **fail loudly; never start over**.
     - Compact once the run is finished.
  5. Push artifacts (including `output.log` and media) that are missing or differ in size.
  6. Three-way merge `archived` against the ledger base: the remote wins conflicts, with a
     warning. `note` gets the same rule.
  7. Final LIST, then write the ledger.
- **Fix the orphan writes first (WT1).** `CachedSnapshotStorage` writes through only when the
  remote holds *this* record.
  - A process-wide `_on_remote[(app, verstr)]` memo:
    - set True by `create_exclusive` or `save` through the cache, and by a remote-only
      pull in `_ensure_local_record`;
    - otherwise one remote metadata GET, compared by run identity with the local metadata,
      and memoized.
  - A local-only run, or a name collision with a foreign record, means local writes only,
    plus a one-time debug log.
  - Gated paths: `save_file`, `save_artifact_file`, `sync_log_to_remote`, and a new
    `remote_for(app, verstr)` that `state_publisher.split_storage` uses (it currently reads
    `_remote` directly).
  - `ensure_code`: check the remote marker, not the merged one (§0.4).

## 3. Modules

**New (<300 lines each):**

| Module | Size |
|---|---|
| `S/storage/remote_presence.py` (identity-checked memo) | ~90 |
| `S/core/push_identity.py` | ~60 |
| `S/core/push_ledger.py` | ~130 |
| `S/core/push_code.py` (code objects + post-claim recheck) | ~80 |
| `S/core/push_logs.py` | ~110 |
| `S/core/push_run.py` | ~250 |
| `S/core/push_rename.py` | ~200 |
| `S/core/push.py` | ~220 |
| `S/core/push_prune.py` | ~110 |
| `X/cli/push.py` | ~150 |

**Edits:**
- `S/storage/cached.py`: memo and gates.
- `S/sdk/state_publisher.py`: use `remote_for`.
- `S/storage/s3_records.py`: `claim_token`.
- `X/gitmode/capture.py`: remote-marker check in `ensure_code`.
- `S/core/writer.py`: `OFFLINE_ENV`, `offline_mode()`, and a `suffix=` keyword through
  `allocate_run_verstr`.
- `S/core/storage_resolve.py`: offline drop in `_open`.
- `X/cli/experiment.py`: push dispatch before the storage build.
- `X/cli/plugin.py`: the action choice, `read_only_actions`, flags, and the git-free
  intercept.

## 4. Tests first (moto; GCS/Azure fakes where noted)

- **`tests/test_fix_storage_local_only_guard.py` (WT1):**
  - `test_tag_on_local_only_run_writes_nothing_to_remote`
  - `test_run_state_on_local_only_run_stays_local`
  - `test_artifact_on_local_only_run_stays_local`
  - `test_output_log_on_local_only_run_stays_local`
  - `test_media_upload_on_local_only_run_stays_local`
  - `test_alerts_sent_on_local_only_run_stays_local`
  - `test_state_publisher_skips_remote_for_local_only_run`
  - `test_sdk_resume_of_local_only_run_writes_nothing_to_remote`
  - `test_other_host_claim_does_not_inherit_offline_log`
  - `test_local_only_run_colliding_with_foreign_remote_record_does_not_write_into_it`
  - `test_run_created_through_cache_still_syncs_without_extra_head`
  - `test_remote_only_record_is_still_written_through`
  - `test_guard_applies_to_gcs_and_azure_backends` (fakes)
- **`tests/test_fix_code_store_remote_marker.py` (WT1):**
  - `test_code_stored_locally_only_is_uploaded_on_next_online_create`
  - `test_retry_after_remote_code_save_failure_uploads_code`
  - `test_remote_marker_present_makes_no_upload`
- **`tests/test_exp_offline_mode.py` (WT2):**
  - `test_offline_drops_store_uri_from_cli_storage`
  - `test_offline_drops_bucket_shorthand_from_cli_storage`
  - `test_offline_drops_remote_from_resolve_experiment_storage`
  - `test_offline_without_local_root_raises`
  - `test_offline_false_values_keep_remote`
  - `test_offline_sdk_start_run_with_unreachable_store_records_locally`
  - `test_offline_code_object_stays_local`
  - `test_offline_run_names_carry_writer_suffix`
  - `test_allocate_suffix_none_ignores_writer_env`
- **`tests/test_fix_storage_s3_claim_token.py` (WT3; parametrized over s3/gcs/azure):**
  - `test_claim_token_resumes_own_crashed_claim`
  - `test_claim_token_mismatch_is_taken`
  - `test_empty_claim_is_taken_even_with_token`
  - `test_existing_metadata_is_taken_even_with_matching_token`
  - `test_claim_body_is_the_token`
- **`tests/test_exp_push_core.py` (WT4):**
  - Identity: `test_identity_ignores_verstr_and_archived`, `test_identity_uses_imported_run_id`
  - Round trip and resume:
    - `test_push_new_run_roundtrips_everything`
    - `test_second_push_makes_no_remote_calls`
    - `test_repush_ships_only_new_lines`
    - `test_partial_line_is_not_shipped`
    - `test_repush_uploads_only_new_artifact`
    - `test_output_log_and_media_are_pushed`
    - `test_push_resumes_after_artifact_upload_failure`
    - `test_push_resumes_own_crashed_claim`
  - Code objects:
    - `test_code_object_pushed_before_claim`
    - `test_code_object_already_on_remote_not_reuploaded`
    - `test_code_object_recreated_if_pruned_between_upload_and_claim`
    - `test_runs_sharing_code_upload_it_once`
    - `test_missing_local_code_object_reported_not_fatal`
  - Adopting existing remote state:
    - `test_online_mirrored_run_is_same_run`
    - `test_orphan_log_from_old_versions_is_adopted`
    - `test_foreign_bytes_under_same_writer_id_fail_loudly`
  - Mutable files and fields:
    - `test_local_run_state_change_is_pushed`
    - `test_remote_run_state_changed_elsewhere_is_not_clobbered`
    - `test_alerts_sent_merged_as_union`
    - `test_local_archive_propagates`
    - `test_remote_archive_kept_when_local_unchanged`
    - `test_conflicting_archive_remote_wins_with_warning`
  - Logs: `test_finished_run_segments_compacted`, `test_legacy_log_yml_pushed`
  - Backends: `test_push_to_gcs_and_azure` (fakes)
- **`tests/test_exp_push_rename.py` (WT5):**
  - `test_collision_renames_both_sides`
  - `test_rename_target_avoids_local_names`
  - `test_rename_keeps_code_verstr_prefix_so_prune_keeps_code`
  - `test_rename_rewrites_children_parent_locally_and_remotely`
  - `test_running_run_with_collision_is_skipped_not_renamed`
  - `test_stuck_run_with_collision_is_skipped`
  - `test_registry_referenced_run_not_renamed`
  - `test_sweep_outer_run_not_renamed`
  - `test_rename_recovers_after_crash_between_claim_and_local_move`
  - `test_rename_ledger_entry_moves`
- **`tests/test_cli_exp_push.py` (WT6):**
  - Arguments and target:
    - `test_push_requires_remote_store`
    - `test_push_rejects_file_store_with_rsync_hint`
    - `test_push_accepts_store_uri_and_bucket_shorthand`
    - `test_push_requires_v_or_all`
  - Selection and status gate:
    - `test_ancestors_auto_included_and_pushed_first`
    - `test_running_skipped_by_default`
    - `test_include_running_then_later_push_completes`
    - `test_child_of_skipped_running_parent_skipped`
  - Output: `test_dry_run_writes_nothing`, `test_summary_format_and_exit_1_on_failure`
  - `--prune-local`:
    - `test_prune_local_deletes_verified_finished_runs_and_unused_local_code`
    - `test_prune_local_keeps_running_unverified_registry_and_parent_of_kept_child`
  - Environment and locking:
    - `test_push_git_free_with_experiment_dir`
    - `test_push_in_repo_uses_conf_store`
    - `test_push_takes_no_repo_lock`
    - `test_push_ignores_offline_env`
    - `test_second_concurrent_push_fails_fast`
  - End to end:
    - `test_registry_warning_printed`
    - `test_offline_record_then_push_e2e`
    - `test_push_1k_up_to_date_is_local_only`

## 5. Docs

- `docs/experiments.md`: an "Offline recording & push" section and a `### push`
  subsection. Include the storage write-through rule and the `file://`/rsync recipe.
- `docs/sdk.md`: `start_run()` under `VMN_EXP_OFFLINE`.
- `CLAUDE.md`: the action, the env var, the write-through rule, `claim_token`, and code
  objects being pushed.
- README: one line.

## 6. Worktrees

- **Parallel:**
  - WT1: the guard plus the code-marker fix.
  - WT2: offline mode plus `suffix`.
  - WT3: the claim token.
  - WT4: push core, including `push_code` (merge WT1 and WT3 first).
- **Then:** WT5 (rename) and WT6 (CLI/prune).
- **Last:** WT7 (docs).

## 7. Risks

- **R1:** the WT1 guard changes behaviour. Existing tests that save through `_local`, or that
  build a local-only record under a cache with a remote and expect remote writes, may fail.
  Per TDD, **stop and ask** rather than edit them. The identity-check GET adds one request
  per (process, record) for records not created through the cache.
- **R2:** hostname writer ids (`localhost` in containers) can collide. This is detected and
  fails; recommend `VMN_WRITER_ID`.
- **R3:** a crash mid-push leaves a visible partial remote record until the next push.
- **R4:** during a local rename there is a brief window where metadata `verstr` and the
  directory name disagree.
- **R5:** artifact resume is per file only.
- **R6:** a run reads `stuck` remotely between pushes.
- **R7:** the fingerprint skip misses remote-side deletes until `.push/` is removed.
- **R8:** a remote prune racing a push can delete a just-uploaded code object before the
  claim. The post-claim recheck covers the pushed run. A remote prune that runs later
  behaves as normal prune.
- **R9:** plugin backends that don't honour conditional create cannot be pushed to (they are
  refused). Their online use still has the §0.3 bug until WT1 lands, because the guard is
  wrapper-level.

## 8. Open questions

- **Q1:** offline naming `<code>.<writer_id>[.N]`?
- **Q2:** is neither `-v` nor `--all` an error?
- **Q3:** rename on both sides OK?
- **Q4:** `archived`/`note` conflict: the remote wins?
- **Q5:** push never-run `created` records?
- **Q6:** defer registry push and `pull`?
- **Q7:** `--query` now or later?
- **Q8:** confirm there is no automatic local fallback.
- **Q9 (new):** should WT1 ship alone as a bug fix, ahead of the offline feature?
- **Q10 (new):** push to a `file://` (NFS) target: never, or later via a
  `LocalSnapshotStorage` segment API?
- **Q11 (new):** sweeps: push `vmn-sweeps/<app>~<outer>` slots (and move them on rename), or
  keep refusing to rename sweep outer runs?
- **Q12 (new):** should the identity-checked gate also block model registration against a
  local-only run (§0.10), or only warn?
