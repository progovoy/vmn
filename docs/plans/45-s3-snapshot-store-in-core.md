# Plan 45: S3 and directory snapshot stores in core vmn

> `vmn snapshot --store s3://…` (and `--store file://…` / a shared NFS
> directory) works with `pip install 'vmn[s3]'` alone. The S3 record code lives
> once, in core (`version_stamp.store`); vmn-exp-sdk builds its run layers
> (logs, metrics, children, artifacts, caching, journal) on top of it.
>
> Paths: `vs/` = `packages/vmn/src/version_stamp/`,
> `sdk/` = `packages/vmn-exp-sdk/src/vmn_exp/`,
> `exp/` = `packages/vmn-exp/src/vmn_exp/`.

Status: **done** (2026-11-15) on branch plan37.

Solo impact: none for a single-user setup: the repo-local store, `VMN_EXPERIMENT_*`
and conf `experiment.storage` keep working (`vmn stamp` moves the latter to `store:`),
and `vmn snapshot` gains `--store` without needing vmn-exp.

What landed:

- P1: `vs/store/` git-free leaf (`names`, `areas`, `uri`, `code`,
  `per_process`, `s3_errors`) with the import-boundary test
  (`tests/test_store_imports.py`).
- P2: `vs/store/s3_{client,base,records,reads,store}.py`, `tests/s3_fakes.py`,
  the `vmn[s3]` extra.
- P3: `vs/store/marker.py` (`store.yml`, `marker_roots.py`) and shared-directory
  record stores (`LocalRecordStore.at_root`).
- P4: `vs/store/{config,open}.py`, `vs/snapshot/stores.py`,
  `vs/cli/snapshot_cmd.py`: `vmn snapshot --store s3://` / `file://` without
  vmn-exp; docs/snapshots.md.
- P4c: conf `store:` (`core/models.py`, `vmn config`), `experiment.storage` →
  `store` migration on `vmn stamp`, `VMN_STORE*` env names.
- P5a: vmn-exp-sdk depends on `vmn>0.11.2,<1`; uv.lock, packaging tests,
  docs/packaging.md.
- P5b–f: the SDK takes uri/areas/per_process (b), the S3 backend (c,
  `sdk/storage/s3*.py` on `store.s3_*`), the marker (d), code objects (e,
  `sdk/core/code_store.py`) and record names (f, `sdk/storage/files.py`) from
  `version_stamp.store`.
- P7: SDK store resolution through `store.config.resolve_store`
  (`sdk/core/storage_resolve.py`, `sdk/core/writer.py`): one precedence table
  for vmn and vmn-exp.

Follow-ups:

- P6: collapse `LocalSnapshotStorage` ↔ `LocalRecordStore` and the
  `vmn_exp._base` copies.
- Unify `atomic_write` (SDK: umask mode, no fsync; core: keeps the mode,
  fsyncs). Deferred by the user (2026-11-15).
- SDK functions that still read `os.environ` directly: `merge_env_into_params`,
  `offline_mode`, `drop_remote_if_offline`, `experiment_dir`.
- ~~`resolve_experiment_storage` reads the environment only (never conf) in a
  checkout: decide whether it should read conf `store:` too.~~ Done
  (2026-11-16): yes. It takes the app's `conf:` mapping (`conf=`); the SDK
  readers and registry functions pass it through `checkout_storage`
  (`sdk/sdk/store_resolve.py`; the app read, else `VMN_APP_NAME`; app conf
  only, no branch conf), so in a checkout they resolve the writer's table.
  Outside a checkout, or with no app named, the environment alone. A non-zero
  rank's `NoOpRun.use_artifact` reads `start_run`'s `storage=`, else
  `checkout_storage`, as rank 0 does. `vmn-exp model` and
  `vmn-exp import-mlflow` resolve through the vcs core loads
  (`exp/cli/checkout_store.py`: `--app`/the imported app, else `VMN_APP_NAME`,
  else the sole stamped app), as the other `vmn-exp` commands.
- The `index_io_process` helper subprocess puts only the SDK `src` on
  `sys.path`.
- `VMN_EXP_OFFLINE`: a neutral name (open question 1).
- Failures on master unrelated to plan 45:
  `test_panel_spec::test_schema_file_matches_generated`,
  `test_pool_names::test_every_sdk_pool_names_its_threads`, and timing benches
  that miss their budgets on this machine (`test_index_warm_restart_bench`,
  `test_schema_policies` 50k, `test_ui_attention_bench`).

Motivation: snapshots are the sharing unit for working state between people
and agents (for example, a teammate's agent forking another's Claude session
against an exported snapshot). That needs a shared store without the
experiment platform.

## Decisions

| Question | Decision |
|---|---|
| Who owns S3 | Core. vmn-exp-sdk **depends on vmn** (it never imported `version_stamp` before). |
| Backends in core | `s3://` and `file://`/plain directory. `gs://`, `az://` and plugin schemes stay in the SDK, reached through the existing opener plugin. |
| Bytes | Unchanged layout (plan 14). Core stamps `format_version: 1` (as core local), the SDK keeps 2; both readable. |
| Conf key | Top-level `store: {uri, bucket, prefix, endpoint_url}`, a real field of core's config model. `experiment.storage` is still read when `store` is absent and is moved to `store` on the next `vmn stamp` (like branch_conf migration). |
| Env vars | New `VMN_STORE`, `VMN_STORE_BUCKET`, `VMN_STORE_PREFIX`, `VMN_STORE_ENDPOINT_URL`, each read before its `VMN_EXPERIMENT_*` twin, which keeps working. Core and vmn-exp share one resolver, so installing vmn-exp never moves snapshots (plan 32). |
| Old tests | The two "`--store s3://` needs vmn-exp" tests switch to `gs://` (approved 2026-11-14). |
| Duplicates | Collapse `code_store` ×2 and the leaf format helpers now; `LocalRecordStore` ↔ `LocalSnapshotStorage` and `_base` later (P6). |

## Where it is today

| Piece | Location | Note |
|---|---|---|
| Store opening | `vs/snapshot/stores.py:46-57` | `--store` without a registered opener raises `REMOTE_NEEDS_EXP` |
| Local record store | `vs/snapshot/local_store.py` | byte-compatible copy of `sdk/storage/local.py`; stamps format 1; no `store.yml` |
| Code objects | `vs/snapshot/code_store.py`, `sdk/core/code_store.py` | same semantics; SDK goes through `in_area(CODE)` |
| S3 backend | `sdk/storage/s3*.py` (~1.9K lines) | `S3SnapshotStorage` = `S3Children, S3Listing, S3Records, S3Logs, S3Metrics, S3Base, SnapshotStorage` |
| Entanglement | `sdk/storage/files.py:10-21` | imports logfiles, metric reads, rewind, series reader, streams — the class cannot move whole |
| Subclasses | `sdk/storage/gcs.py:89`, `azure.py:97` | subclass `S3SnapshotStorage` with an `ObjectClient`; signature must hold |
| `parallel_map` | `sdk/storage/s3_base.py` | imported by 22 modules; `s3_base` stays an SDK module |
| S3 tests | `packages/vmn-exp/tests/` | moto in-process (`s3_helpers.py`); core suite has no boto3/moto |

## Design

### 1. `vs/store/` — a git-free leaf package

Imports only stdlib, `yaml`, `vs/core/{utils,constants}` and itself; boto3
only lazily. Never `snapshot`, `cli`, `devversion`, `stamping`, `backends`,
`git`. Logger: `logging.getLogger("vmn")`, not the `VMN_LOGGER` proxy (it
raises until the CLI initializes it).

| Module | Contents | From |
|---|---|---|
| `names.py` | `METADATA_FILE`, `PATCH_FILES`, `safe_verstr`/`unsafe_verstr`/`safe_dep_name`, `checked_app_path`, `apply_metadata_updates`, patch dir read/write | `vs/snapshot/{record,identity,local_store}.py`, `sdk/storage/files.py` |
| `areas.py`, `uri.py`, `per_process.py` | verbatim | `sdk/storage/` |
| `code.py` | `code_key`, `stored_code`, `store_code`, `publish_code`, `resolve_code`, `CODE_MISSING` | `vs/snapshot/code_store.py` |
| `s3_errors.py` | error codes, `is_missing`/`is_taken`, `put_condition`, `NO_FILE` | `sdk/storage/s3_base.py:33-56` |
| `s3_client.py` | timeouts/retries, `boto3_module()` (error names `vmn[s3]`), `boto3_client(endpoint_url)` | `sdk/storage/s3_base.py` (subset) |
| `s3_base.py` | `S3ObjectBase`: bucket/prefix/key helpers, head/get/put/create/list primitives, `_open_area`, `_map` hook. **No record-API names** (R3). | `sdk/storage/s3_base.py:149-267` |
| `s3_records.py` | `S3RecordWrites`: claim, save (metadata last), delete (metadata first), ETag-CAS `update_metadata`; `_stamped` hook | `sdk/storage/s3_records.py` |
| `s3_reads.py` | `read_record()`/`read_patches()` functions + `S3RecordReads` mixin (exists, load, list) | `sdk/storage/s3.py:49-89`, `s3_listing.py` (subset) |
| `s3_store.py` | `S3RecordStore`, `open_s3_store(uri, area, client_factory)` | — |
| `marker.py` | `store.yml` check, clock/sleep injected | `sdk/storage/store_marker.py` |
| `config.py` | pure `resolve_store_uri(params, env, conf)`, `drop_remote_if_offline`; precedence `--local` > `--store` > `VMN_STORE` > `VMN_EXPERIMENT_STORE` > bucket shorthand (`VMN_STORE_*` before `VMN_EXPERIMENT_*`, prefix default `vmn`) > conf `store.*` > conf `experiment.storage.*`; `VMN_EXP_OFFLINE` drops remotes | `sdk/core/{writer,storage_resolve}.py` |
| `open.py` | `open_record_stores(uri, s3_client_factory)` for `file`/`s3`; else `UnsupportedScheme` | — |

`LocalRecordStore` gains a store-root form (`at_root(root, kind)`) for
`file://`, without v1 adoption. `vs/snapshot/{identity,record,code_store}.py`
re-export from `store`.

### 2. Opening

```
open_snapshot_stores(vcs, params, env, s3_client_factory)
  --local                 -> repo-local stores (unchanged)
  registered opener       -> its result if not None (vmn-exp keeps control)
  resolve_store_uri(...)  -> None: repo-local
                             file:// / path: LocalRecordStore.at_root
                             s3://: S3RecordStore areas snapshots/code/runs, one client
                             other: "<scheme>:// snapshot stores need vmn-exp"
  writer: marker.check_store; read-only: marker.require_store
```

Composition root: `vs/cli/snapshot_cmd.py:_open_stores` passes `os.environ`
and `store.s3_client.boto3_client`. `api.open_snapshot_stores` keeps its
signature through a wrapper.

vmn-exp's opener (`exp/snapshot/stores.py`) stays registered and unchanged:
gs/az/plugins, local-first caching, runs sharing the code area. Its S3 objects
become SDK classes built on core.

### 3. The SDK on core

- `sdk/storage/{uri,areas,per_process,store_marker}.py` become re-exports
  (incl. `_lock`, `forget_checked`).
- `S3Base(S3ObjectBase)` keeps its constructor, PerProcess clients, fork
  proxies, instrumentation, prefix cap, `parallel_map` (`_map = parallel_map`)
  and the module globals tests patch (`boto3_client`, `parse_timestamp`).
- `S3Records(S3RecordWrites)` sets `_stamped = with_format_version` (format 2).
- `S3SnapshotStorage` keeps its bases; record loads delegate to
  `store.s3_reads.read_record`. The read mixin is not inherited (R3).
- `sdk/core/code_store.py` delegates to `store.code` via `code_storage()`.
- `sdk/storage/files.py` takes the leaf helpers from `store.names`.

## Phases (one worktree each, TDD, each green alone)

| Phase | Content | After | Parallel with |
|---|---|---|---|
| P1 | `store/{names,areas,uri,code,per_process,s3_errors}`; snapshot re-exports; import-boundary test (subprocess import loads no git/boto3) + AST rule | — | — |
| P2 | `store/s3_*`; `tests/s3_fakes.py` (`FakeS3Client`) + moto contract test; `vmn[s3]` extra; boto3/moto in `tests/test_requirements.txt` | P1 | P3, P5a |
| P3 | `LocalRecordStore.at_root`; `store/marker.py` with `FakeClock` tests | P1 | P2, P5a |
| P4 | `store/{config,open}`; `snapshot/stores.py`; CLI wiring; Docker e2e for `file://` and `s3://` (moto); docs/snapshots.md | P2, P3 | — |
| P4c | conf `store:` field (`core/models.py`, `vmn config` TUI, README conf table); `experiment.storage` → `store` migration on stamp; `VMN_STORE*` env names; docs | P1 | P2, P3, P5a |
| P5a | SDK depends on vmn; uv.lock; test_workspace / test_packaging_split / test_installation / test_exp_import_boundary; docs/packaging.md | P1 | P2–P4 |
| P5b–f | SDK re-exports (b), S3 on core with MRO characterization tests first (c), marker (d), code_store (e), files.py (f) | P5a (+P2 for c, P3 for d) | each other |
| P6 | later: collapse `LocalSnapshotStorage` ↔ `LocalRecordStore`, `_base` copies | P5 | — |
| P7 | **required** (the P4c migration moves keys the SDK would otherwise stop seeing): SDK store resolution from `store.config` — one precedence table, conf `store:` and `VMN_STORE*` honored by vmn-exp | P4c, P5a | P4, P5b–f |

Release order: vmn with `version_stamp.store` before the SDK/vmn-exp that
require it. `version_stamp.store` becomes a second public contract next to
`version_stamp.api` (documented, contract-tested).

## Tests that change

These encode the old requirement ("`--store s3://` needs vmn-exp"). Approved:
switch them to `gs://bucket/prefix`, where the assertion still holds.

- `tests/test_snapshot_stores.py:34` `test_store_flag_without_opener_is_an_error`
- `tests/test_snapshot_cli.py:125` `test_store_flag_without_vmn_exp_is_an_error`

Packaging tests that assert "the SDK needs no vmn" change with P5a:
`test_workspace.py:47`, `test_installation.py:94-96,199,205-212`,
`test_packaging_split.py:81-94`.

## Risks

- **R1 job-image weight.** The SDK now installs vmn's deps (GitPython, git-cliff
  binary wheel, Jinja2, questionary, rich, …). Not imported, but bigger images,
  and a platform without a git-cliff wheel fails to install. Mitigation (later):
  move CLI-only deps of vmn behind an extra.
- **R2 git at import.** GitPython raises at import without a git binary; the
  P1 import test and AST rule guard `store/`.
- **R3 MRO shadowing.** Bases of `S3Base` precede `SnapshotStorage`; if
  `S3ObjectBase` defined `load_metadata`/`list_snapshots`/…, it would replace the
  SDK's format-gated versions. Primitives only; characterization tests first.
- **R4 format_version.** Core S3 writes 1, the SDK 2; both readable.
- **R5 store.yml.** Core writers create it on a fresh `--store` and refuse a
  migrating store; repo-local `.vmn/store` keeps today's behavior.
- **R6 fork safety (plan 30).** Marker lock is a `PerProcessLock`; SDK keeps
  PerProcess clients.
- **R7 cycles.** `store` → `core` only; SDK → `store` only.
- **R8 startup cost.** boto3 and `store.s3_*` load lazily;
  `test_cli_startup_imports` lists them as not loaded.
- **R10 plan 35.** Both touch `snapshot/`; sequence them, or allowlist the
  `store/` filesystem modules in its IO ratchet.

## Open questions

1. `VMN_EXP_OFFLINE` keeps its name for now; a neutral `VMN_STORE_OFFLINE`
   can follow if wanted.
