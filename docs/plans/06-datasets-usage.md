# Plan 6 (remaining): datasets in the registry + recorded model/dataset usage

> Master already has **run-level lineage**: `vmn-exp lineage <app> -v <ref> [--depth N] [--json]`
> (`packages/vmn-exp/src/vmn_exp/cli/lineage.py`), SDK `vmn_exp.sdk.reader.get_lineage`
> (`packages/vmn-exp-sdk/src/vmn_exp/sdk/reader.py:248`), UI
> `GET .../workspaces/{ws}/apps/{app_tag}/experiments/{verstr}/lineage?depth&limit`
> (`packages/vmn-exp/src/vmn_exp/ui/routes_lineage.py`, `webui/src/components/RunLineage.tsx`),
> all over the pure graph in `packages/vmn-exp-sdk/src/vmn_exp/core/lineage.py`.
> This plan covers only what's missing: datasets as registry entries and "run X used
> model/dataset V" edges — **as an extension of that graph, not a new one.**
> Paths below are relative to `packages/vmn-exp-sdk/src/vmn_exp/` unless they start with
> `packages/`, `tests/` or `docs/`.

## Existing lineage shape (what we extend)

- Graph is **run-to-run only**, a join over index rows (no log reads). `LineageIndex(rows, outputs_of)` builds `producers` (output digest -> runs), `digest_consumers`, `uri_consumers` ((app, verstr) -> consumers).
- Two edge kinds: **uri** — an input whose URI is `vmn://<app tag>/<verstr>/<path>` (`artifact_ref_uri`, what `Run.use_artifact` records in `sdk/run_artifacts.py:71`) names its producer outright, cross-app; **digest** — any other input whose digest equals an output's sha256, **same app only**.
- Downstream (`_downstream_edges`) searches only the run's own app, so consumers in *other* apps are invisible from the producer side.
- Node: `{app, verstr, name, timestamp, status, depth, found, links: [{input, artifact, digest, via}]}`. Payload: `{app, verstr, upstream, downstream, models, truncated}`.
- The **"produced" registry edge already exists**: `models` = `registry/view.py:models_for_run(storage, app, verstr)` -> `[{model, version, aliases, status, artifact_path}]`, backed by `_run_models`, cached on `storage.list_files("vmn-registry")`. `registered_runs()` (prune guard) reads the same map.
- "Produced" outputs: since commit 840cc43 artifacts **and** logged images/tables are run outputs (`core/fold.py` `OUTPUT_TYPES = ("artifact", "image", "table")`, digest `sha256:<hex>`), so a copied dataset logged as an artifact is already a lineage producer; no new produced-edge concept is needed.

## Findings (re-verified on master 0096782)

- `sdk/models.py` imports `vmn_exp.registry.*`. `tests/test_packaging_split.py` allows it: the SDK distribution is `vmn_exp.{sdk,storage,core,registry,integrations,_base}` and may import any of those, never `vmn_exp.{cli,ui,snapshot,importers,gitmode}` (gitmode only lazily) and **never `version_stamp.*` at all** (not even `version_stamp.api`). CLAUDE.md's SDK rule ("only `vmn_exp.core`, `vmn_exp.storage`, `vmn_exp.snapshot`, `version_stamp.api`") is stale on all three counts.
- `register_model()` returns `get_model_version(f"{name}@{n}")` (`sdk/models.py:136`) and `download_model()` calls it too (`sdk/models.py:191`) -> **`get_model_version` / `resolve_ref` must never record a use**; recording belongs in `download_model` / `use_*` only.
- `input` entries carry `ts` but no `timestamp` (`core/inputs.py:33`, `sdk/run.py:442`); `storage/files.py:flatten_logs` sorts by `timestamp` (default `""`), so every input sorts to the front of the merged log. Existing quirk; new entries must not depend on log position relative to metrics.
- Input fold is latest-wins **by name** (`core/fold.py:_apply_inputs`, keyed by log position) and the lineage index reads only the folded `row["inputs"]` -> using `m@3` then `m@4` under one input name loses `m@3`. Fix at the source: **the input name includes the pinned version** (`<name>@<N>`), so both survive the fold; lineage keeps reading rows only.
- `valid_input_entry` rejects unknown fields (`core/inputs.py:15`), and the fold keeps only `uri/digest/kind` -> registry pin must be encoded in `uri` / `name`, not a new field.
- Registry = pseudo-app `vmn-registry` (`registry/names.py:REGISTRY_APP`); `fold_registry` puts **every** dict entry in `audit` (`registry/fold.py:97`). Every registry write does read-all-entries -> append (`registry/log.py:_build_entry`).
- `_scan_run_models` skips versions whose `run_ref` isn't a dict with app+verstr (`registry/view.py`) -> an optional `run_ref` is safe for prune and `models_for_run`.
- `_run_models`' cache key is the full registry listing, which includes log file `(size, mtime)` -> **appending a `use` entry to a model's log invalidates it** and forces a full rescan (every model log + every version record) on the next lineage/prune call.
- `list_models` keeps only names passing `valid_model_name`; model names cannot contain `-`, so a sibling record `<model>-uses` can never collide with a model and is ignored by `list_models`/`list_versions` for free.
- Doc drift in `docs/models.md`: `get_model_version` is documented to return `status` and `aliases` but returns the raw version record (`model, n, run_ref, timestamp, artifact_path?, description?` + format key); `vmn-exp model delete ... --force` is documented but the parser has no `--force`, and `set_version_status` just refuses while aliases point at the version.
- Storage resolution mismatch still holds: `sdk/reader.py:_resolve` opens `open_storage(vmn_root_path=resolve_root_path())` (local checkout only), while `sdk/models._resolve_storage` -> `core/storage_resolve.resolve_experiment_storage` honours `VMN_EXPERIMENT_DIR` and `VMN_EXPERIMENT_STORE/BUCKET/...`. It now also affects `get_lineage` (it calls `models_for_run` on the reader's storage).
- `NoOpRun.use_artifact` (`sdk/ranks.py:80`) already resolves without recording -> pattern for `NoOpRun.use_model/use_dataset`; `NoOpRun.register_model` is ignored.
- Registry CLI lives in the SDK distribution (`registry/cli.py`, `vmn-exp model ...`); UI routes in `packages/vmn-exp/src/vmn_exp/ui/routes_models.py` + `ui/readers/models.py`, workspace-scoped (`/workspaces/{ws}/models/...`).

## Decisions

- **One namespace + `kind`** (`model|dataset`) on the header; legacy header = model; `ensure_model(kind=)` raises on mismatch. `models_for_run` entries gain `kind`.
- **Datasets default to reference mode** (URI + digest, no bytes copied). Copied mode = log an artifact on a data-prep run and `register_dataset(name, run=, artifact_path=)` (gets prune protection via `registered_runs`, shows in that run's lineage `models`). Local file/dir digests: `sha256` / manifest digest over sorted `relpath\0filesha\n`. Remote URIs: caller digest or none (S3 ETag manifest -> v2). `dedupe=True` returns the latest version with the same digest.
- **Forward edge = an ordinary `input` entry, reusing existing edge kinds:**
  - Run-backed version (model, copied dataset): `uri = artifact_ref_uri(app, verstr, artifact_path)` — byte-for-byte what `use_artifact` records — `digest` = the producer output's digest, `kind = model|dataset`, `name = <name>@<N>`. The existing **uri** edge links consumer -> producer run (cross-app) with **no change to `resolve_lineage`**.
  - Reference dataset (no run): `uri = vmn-registry://<name>@<N>` (always pinned, never an alias), `digest` = registry digest, `kind = dataset`, `name = <name>@<N>`. `LineageIndex` learns this scheme (below).
- **Reverse edge** = a `use` entry in the sibling registry record `<model>-uses` (not the model's own log): best-effort, never breaks `download_model`; keeps `audit` and the `_run_models` cache untouched; answers "who used V" across apps without scanning every app. Per-run `_used` dedupe.
- **What records:** `use_model(ref)`, `use_dataset(ref)` (also `run.use_*`), and `download_model(..., record=True)` when a run is open (`current_run()`). `NoOpRun.use_*` resolves without recording. `get_model_version` never records.
- **Lineage extension (same payload, additive):**
  - Run-rooted (`resolve_lineage` / `get_lineage` / UI route): each upstream `link` with `via == "uri"` whose `(producer app, verstr, artifact)` matches a live version in `models_for_run(producer)` gains `model`, `version`, `kind`. New top-level `datasets: [{model, version, kind, input, digest, found}]` for `vmn-registry://` inputs (reference datasets have no producer run, so no run node). `models` unchanged (plus `kind`).
  - Version-rooted (new): `version_lineage(storage, name, n)` -> `{model, version, kind, status, producer: <run node or None>, consumers: [run nodes]}` — producer from `run_ref`, consumers from the `-uses` fold, each consumer's `found`/`status` from its app's index (missing when pruned). Run nodes reuse `core/lineage._node`'s shape.

## Formats

- Header: `{"model", "type": "model_header", "kind", "timestamp", "description"?, "actor"?}` (absent `kind` = `model`).
- Version: `{"model", "n", "timestamp", "run_ref"?, "artifact_path"?, "uri"?, "digest"?, "size"?, "files"?, "description"?, "actor"?}` + format key (`stamped`).
- Use entry (log of record `<model>-uses`): `{"type": "use", "version": N, "run": {"app", "verstr"}, "ts", "writer", "pos", "actor"}` via the existing `_build_entry`; `fold_uses(entries) -> {n: [{app, verstr, ts}]}` (dedup, earliest ts, chunking-invariant, same `_sort_key`).
- `registry/names.py`: `registry_uri(name, n)`, `parse_registry_uri(uri)`, `uses_record_name(model)`.

## Modules

- SDK distribution (`packages/vmn-exp-sdk/src/vmn_exp/`): `registry/names.py` (+25), `registry/store.py` (kind, optional `run_ref`, uri/digest, `list_models(kind=)`), `registry/fold.py` (`fold_uses`), `registry/log.py` (`record_use` on `<model>-uses`), **new** `registry/digest.py` (~70), `registry/view.py` (`kind` in `models_for_run`/`model_state`, `version_lineage`), `core/lineage.py` (`vmn-registry://` inputs -> `datasets`; link annotation via an injected `models_of(app, verstr)` so it stays pure), `sdk/models.py` (`download_model(record=True)`, ValueError for reference datasets), **new** `sdk/usage.py` (~110), **new** `sdk/datasets.py` (~100: `register_dataset`, `get_dataset_version`), thin `run.use_*` delegates in `sdk/run.py`, `sdk/ranks.py`, `sdk/__init__` exports, `sdk/reader.py:get_lineage` (pass `models_of`, add `datasets`), `registry/cli.py` (`register --kind dataset --uri --digest`, `list --kind`, `delete` warns "used by K runs").
- Full distribution (`packages/vmn-exp/`): `src/vmn_exp/cli/lineage.py` (print link model/version, `Datasets:` section), `src/vmn_exp/ui/routes_lineage.py` (same `models_of`), `src/vmn_exp/ui/routes_models.py` + `ui/readers/models.py` (`?kind=`, new `GET .../models/{name}/versions/{n}/lineage`), `webui/src/components/RunLineage.tsx` (link badges, datasets group), `webui/src/pages/Models.tsx` (kind badge/filter), `webui/src/pages/ModelDetail.tsx` (producer + consumers panel).

## Tests first

- Registry (`tests/test_registry_names_fold.py`, `tests/test_registry_store.py`, `tests/test_registry_view.py`): `test_registry_uri_round_trip`, `test_parse_registry_uri_rejects_other_schemes_and_bad_numbers`, `test_uses_record_name_is_not_a_valid_model_name`, `test_fold_uses_deduped_earliest_ts`, `test_fold_uses_chunking_invariant`, `test_use_entries_not_in_model_audit`, `test_use_entry_does_not_invalidate_run_models_cache`, `test_ensure_model_writes_kind_default_model`, `test_ensure_model_kind_mismatch_raises`, `test_legacy_header_kind_is_model`, `test_register_version_without_run_ref_stores_uri_digest`, `test_list_models_kind_filter`, `test_registered_runs_ignores_reference_versions`, `test_models_for_run_includes_kind`.
- Digest (new `tests/test_registry_digest.py`): `test_file_digest_is_sha256`, `test_dir_manifest_digest_is_order_independent_and_content_sensitive`, `test_size_and_file_count`.
- Usage (`tests/test_sdk_models.py` or new `tests/test_sdk_usage.py`): `test_use_model_logs_vmn_artifact_uri_with_producer_digest`, `test_use_model_input_name_is_pinned_name_at_n`, `test_use_model_alias_is_pinned_to_number`, `test_use_two_versions_both_survive_input_fold`, `test_use_model_appends_use_entry_to_uses_record`, `test_use_model_twice_records_once`, `test_download_model_in_run_records_use`, `test_download_model_outside_run_records_nothing`, `test_download_model_record_false_records_nothing`, `test_register_model_never_records_self_use`, `test_get_model_version_never_records`, `test_registry_write_failure_is_warned_not_raised`, `test_noop_run_use_model_returns_meta_without_writes`, `test_use_dataset_on_model_raises`.
- Datasets (new `tests/test_sdk_datasets.py`): `test_register_dataset_reference_local_file_computes_digest`, `test_register_dataset_dir_manifest`, `test_register_dataset_dedupes_same_digest_returns_existing_n`, `test_register_dataset_copied_mode_points_at_run_artifact`, `test_register_dataset_requires_exactly_one_mode`, `test_use_reference_dataset_logs_registry_uri`, `test_download_model_on_reference_dataset_raises_value_error`, `test_s3_reference_dataset_round_trip`.
- Lineage extension (`tests/test_exp_lineage_core.py`, `tests/test_exp_lineage_sdk.py`, `tests/test_ui_lineage_api.py`): `test_used_model_is_uri_edge_to_producer_run_cross_app`, `test_uri_link_annotated_with_model_version_kind`, `test_registry_uri_input_listed_in_datasets_not_as_node`, `test_version_lineage_producer_and_consumers`, `test_version_lineage_pruned_consumer_marked_missing`, `test_version_lineage_deleted_version_status`, `test_lineage_payload_keys_unchanged_plus_datasets`.
- CLI/prune/UI (`tests/test_cli_model.py`, `tests/test_exp_lineage_cli.py`, `tests/test_fix_exp_prune_registry.py`, `tests/test_ui_models_api.py`): `test_register_kind_dataset_with_uri`, `test_list_kind_filter`, `test_delete_consumed_version_warns_consumer_count`, `test_lineage_cli_prints_used_model_and_datasets`, `test_prune_consumer_run_allowed_version_lineage_marks_missing`, `test_prune_refuses_producer_of_copied_dataset`, `test_models_list_includes_kind_and_filters`, `test_version_lineage_endpoint`; vitest: kind badge/filter (Models), ModelDetail producer/consumers, RunLineage link badges + datasets group.

## Docs

`docs/models.md` (Datasets, Using versions, prune notes; fix `get_model_version` return shape and drop `delete --force`); `docs/sdk.md` (`use_model`/`use_dataset`/`register_dataset`, lineage `datasets` + link fields); `docs/experiments.md` "Lineage" section; `docs/ui.md` "Lineage" + models endpoints; `CLAUDE.md` (fix the SDK dependency rule to match `tests/test_packaging_split.py`, new SDK names, `vmn-exp model` flags).

## Worktrees

B1 registry data model (names/store/fold/log/digest/view) -> (B2 sdk usage/datasets ∥ B3 core/lineage + reader + CLI) -> B4 UI routes + webui.

## Risks

- `-uses` record scan cost on S3 for version-rooted lineage (lazy endpoint, TTL memo); unbounded `use` entries for popular models (per-run dedupe; compaction later); every `record_use` reads the whole `-uses` log (`_build_entry`).
- Non-atomic two-store write: the run-log input is the source of truth for run-rooted lineage; a missing `use` entry only hides the run from version-rooted consumers.
- Downstream digest/uri edges stay same-app; cross-app consumers of a model are only visible through `version_lineage`.
- Two versions registered from the same `(run, artifact_path)` annotate one link with both.
- Cross-storage runs show `found: false`; namespace clash model<->dataset (one namespace by decision).

## Open questions

1. Block or warn on deleting a consumed version? (warn)
2. `--input vmn-registry://m@prod` CLI resolution in `cli/inputs_arg.py` now?
3. `vmn-exp dataset` alias or `vmn-exp model --kind dataset`? (latter)
4. S3 ETag-manifest digests now or v2?
5. Should `get_run`/`list_runs`/`get_lineage` honour `VMN_EXPERIMENT_DIR`/store env like the registry? (behaviour change; lineage `models` currently comes from the reader's local storage)
