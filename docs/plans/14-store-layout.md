# 14 — Store layout v2

Status: **accepted 2026-10-02, not started**, from a sweep of the current folder and file structure,
done before implementing plans 11–13. Old clients don't need supporting, so this is a clean
layout change plus one migration command.

Paths are under `packages/`; `S` = `vmn-exp-sdk/src/vmn_exp`.

---

## 1. What the sweep found

### 1.1 Today's layouts: three of them

| Backend | Where a run lives | Where a snapshot lives | Code objects / sweeps / registry |
|---|---|---|---|
| Repo-local (`.vmn/` in the checkout) | `.vmn/<app>/experiments/<verstr>/` | `.vmn/<app>/snapshots/<verstr>/` | `.vmn/vmn-code/<app~>/experiments/…`, `.vmn/vmn-sweeps/<app>~<sweep>/experiments/…`, `.vmn/vmn-registry/experiments/…` |
| `file:///dir` | `<dir>/.vmn/<app>/experiments/<verstr>/` (mimics a repo) | same, `snapshots/` | same as above |
| S3 / GCS / Azure | `<prefix>/<app-key>/<verstr>/` | `<prefix>/<app-key>/<verstr>/` **(same!)** | `<prefix>/vmn-code-<app>/…`, `<prefix>/vmn-sweeps-…`, `<prefix>/vmn-registry/…` |

- Local stores are app-first then kind (`<app>/experiments`). Object stores are kind-first
  through `subdir` (`vmn-experiments` / `vmn-snapshots` default prefixes), except when the URI
  has a path (§1.2).
- System records are **pseudo-apps** mixed into the app namespace (`S/core/reserved.py`), with
  three name encodings: `/`→`-` (S3 tag form), `/`→`~` (code and sweeps), and the legacy
  `/`→`_` (still probed with a HEAD per record, `S/storage/s3_base.py:45`, `_record_prefix`).
- Records share directories with vmn core's own files (`.vmn/<app>/conf.yml`,
  `last_known_app_version.yml`, `branch_conf/`). Each records dir carries its own
  `.gitignore` of `*`, because the repo-level rule only matches one level deep
  (`S/storage/local.py:67`).

### 1.2 Bug: runs and snapshots collide on object stores with a URI path

`default_prefix` returns the URI's path and ignores `subdir` when there is one
(`S/storage/registry.py:40`). So with `--store s3://bucket/team`:

```
experiments → team/my_app/1.0.0-dev.abc
snapshots   → team/my_app/1.0.0-dev.abc        (checked: same key)
```

A first run's verstr is its code verstr (`S/core/writer.py:271`), and a snapshot's verstr is
the same deterministic dev verstr of the same tree. So a `vmn snapshot create` and the first
`vmn-exp run` of the same working tree **claim the same record name**: one of them fails its
claim, or treats the other's record as its own. Runs and snapshots also show up in each
other's listings. The `file://` tests don't catch it, because the local layout separates
`experiments/` and `snapshots/` by folder. Only the no-path default (`vmn-experiments` /
`vmn-snapshots` prefixes) is safe today.

### 1.3 System files share a namespace with user artifacts

`output.log` (`S/core/output_log.py:17`), images (`media/<name>/<step>.png`) and tables
(`tables/<name>/<step>.json`, `S/sdk/run_media.py:153-172`) are stored as artifacts, and
`checked_artifact_name` reserves nothing (`S/sdk/run_artifacts.py:34`). A user's
`run.log_artifact("output.log")` or an artifact tree containing `media/…` overwrites, or is
overwritten by, vmn's own outputs.

### 1.4 Per-host state lives inside the store

- The index cache `.index.sqlite` sits beside the records it summarizes (`S/storage/files.py:22`).
  On a `file://` store shared over NFS, several hosts open one SQLite file over NFS, which
  is exactly where SQLite locking is unreliable. The code already copes with "a filesystem
  without shared memory" (`S/core/index_store.py`).
- The push ledger `.push/<remote_id>/` sits inside the app's records dir
  (`S/core/push_ledger.py:26`).

### 1.5 Legacy read paths still in the code

`log.yml` (YAML logs), the `_` app-key encoding (HEAD probes), in-record patches ("promoted
once"), and records without `format_version`. With no old clients, all of them can go once
data is migrated.

---

## 2. Proposal: one root, top-level areas

The same layout for every backend. `<root>` is `s3://bucket/prefix`, `gs://…`, `az://…`,
`file:///dir`, or the repo-local store.

```
<root>/
  store.yml                                   store marker (§2.3)
  runs/<app-key>/<verstr>/                    experiment runs            (was experiments/)
  snapshots/<app-key>/<verstr>/               vmn snapshot records
  code/<app-key>/<code_verstr>.<diff_hash>/   shared code objects        (was vmn-code/<app~>)
  sweeps/<app-key>~<sweep-verstr>/<slot>/     sweep trial claims t<N>, t<N>.a<K>  (was vmn-sweeps/…)
  registry/<model>/<record>/                  header, v<N>, uses         (was vmn-registry/<model>…)
  reports/<rid>/<record>/                     header, v<N>, comments     (plan 13)
  comments/<app-key>/<verstr>/                run comment threads        (plan 13)
  journal/<YYYYMMDDHHMM>/<entry>              change journal             (plan 11 §5.2)
```

### 2.1 What this fixes or simplifies

| Change | Effect |
|---|---|
| Kind-first areas instead of `subdir` + pseudo-apps | Fixes §1.2 by construction: runs and snapshots can't share a key. No reserved app names, no `is_reserved_app` filtering in every listing, `list_apps` = one delimiter listing of `runs/`. |
| One area per system feature | Each feature's records sit under one prefix: a model's versions are one listing of `registry/<model>/` (today: list `vmn-registry` and filter by name). Deleting a report is one prefix. |
| Literal prefixes per area | Plan 11's permission sets and lifecycle rules become plain prefix lists: jobs write `runs/ snapshots/ code/ sweeps/ journal/` and read `registry/`; the server's edit set writes `runs/*/*/metadata.yml`, `registry/ reports/ comments/ journal/`; one lifecycle rule for `journal/`. Customers can grant per area. |
| One layout everywhere | `vmn-exp push` and `vmn-exp export` copy paths as they are; a `file://` store is laid out like a bucket (no fake `.vmn/<app>/` tree); the docs describe one layout. |
| One app-key encoding | **Tag form** (`/` → `-`, bijective because `-` is illegal in app names; the same form as git tags and UI URLs) in every area and backend, local too. Removes the `~` and `_` encodings and the HEAD probes. |

### 2.2 Storage API change

Today the storage takes `(subdir)` at construction and `(app_name, verstr)` per call. With
areas:
- `open_storage(store, root, area="runs")`: `area` replaces `subdir` (same mechanism, more
  values). Each area is a `SnapshotStorage` over `<root>/<area>/`, so backends, claims,
  listings, logs and sync are untouched.
- Within an area, the first path segment is the **scope** (an app key, a model name, a report
  id, `<app-key>~<sweep>`), the second the record name. That's exactly today's
  `(app_name, verstr)`.
- The code store opens area `code` with scope = app key, instead of pseudo-app
  `vmn-code/<app~>` (`S/core/code_store.py:code_app`). Sweeps, registry, reports and comments
  the same way.
- `S/core/reserved.py` is deleted.

### 2.3 `store.yml`

```yaml
layout: 2
created_at: "2026-10-02T12:00:00Z"
journal: {partition: minute}
```

- Created by the first writer with a create-if-absent put (`IfNoneMatch` / `O_EXCL`).
- **Writers and readers refuse a root whose `layout` they don't know**, and a root that has
  vmn records but no `store.yml` (a v1 store: "run `vmn-exp migrate`").
- It lets the server's onboarding probe (plan 11 §6.3) tell "empty prefix" from "a vmn
  store", and catches a mistyped prefix that today silently starts a new empty store: commands
  that only read print "no vmn store at <uri>" instead of listing nothing.
- `migrating: true` while `vmn-exp migrate` runs; writers refuse until it's done.

### 2.4 Inside a record

```
runs/<app-key>/<verstr>/
  metadata.yml                written last: the existence marker (unchanged)
  env.yml
  run_state.yml               volatile (heartbeat)
  alerts_sent.yml
  log/<w>.jsonl               events (plan 12: no metrics in here)
  log/<w>@<seq>.jsonl         segments; log/<w>@<a>-<b>.jsonl compacted
  metrics/<w>.vms             metric stream (plan 12)
  metrics/<w>@<seq>.vms       stream segments
  metrics/<w>.vmx             indexed metrics (plan 12)
  outputs/output.log          vmn-generated outputs (was artifacts/output.log)
  outputs/media/<name>/<step>.png
  outputs/tables/<name>/<step>.json
  artifacts/<user paths>      user artifacts only
  .claim                      object stores only (unchanged)
```

- **System outputs move to `outputs/`**, so user artifacts can be named anything (fixes §1.3).
  Lineage keeps one path namespace for `vmn://<app>/<verstr>/<path>` URIs and `outputs`
  rows: `outputs/…` paths for vmn's own files, `artifacts/…` for the user's. Both are
  explicit, so a URI says which one it means, and `run.use_artifact(ref, "outputs/media/…")`
  works.
- **Logs and metrics get their own folders**, so one prefix listing returns exactly one kind,
  and the plan 12 files have a home. Log naming inside is unchanged (`S/core/logfiles.py`).
- Snapshots: `metadata.yml` (with `code:`) plus `deps/<dep>/…` as today. Code objects keep
  their patch files (`working_tree.patch`, `local_commits.patch`, `untracked_files.tar.gz`,
  `deps/`).

### 2.5 Per-host state leaves the store

The store holds only shareable data. Per-host caches and state go to standard user
directories, keyed by the store's identity (`cache_identity()`, already on every backend):

| What | Today | v2 |
|---|---|---|
| Index cache | `<records dir>/.index.sqlite` | `$XDG_CACHE_HOME/vmn-exp/index/<store-id>.sqlite` (macOS `~/Library/Caches/vmn-exp/…`) |
| Push ledger | `.vmn/<app>/experiments/.push/<remote_id>/` | `$XDG_STATE_HOME/vmn-exp/push/<store-id>/<remote_id>/` |
| `vmn-exp ui` data dir | `--data-dir` (unchanged) | unchanged |

`VMN_EXP_CACHE_DIR` overrides both (for containers with a read-only home).

### 2.6 The repo-local store

Default local root becomes **`<repo>/.vmn/store/`**, with the same areas as any store and
**one** `.gitignore` of `*` at its top. vmn core's `.vmn/<app>/conf.yml` and friends no longer
share directories with records, and the per-records-dir `.gitignore` workaround goes away.
`VMN_EXPERIMENT_DIR` and `--dir` point at a root with this layout.

---

## 3. Drop the legacy read paths

Once `vmn-exp migrate` exists, delete:
- `log.yml` reading (`LEGACY_LOG_FILE`, `S/core/logfiles.py:17`, and its branches in
  `parsed_logs`, `index_logs`, `flatten_logs`)
- the `_` app-key fallback and its HEAD probes (`app_keys`, `_record_prefix`,
  `_legacy_owners` in `S/storage/s3_base.py`)
- in-record patches and their one-time promotion (rerun, restore)
- treating a missing `format_version` as 1. Every v2 record carries it.

---

## 4. One migration command

`vmn-exp migrate [--store <uri> | --dir <path>] [--dry-run]` does both changes in one pass,
replacing plan 12's separate `migrate-metrics`:

1. Write `store.yml` with `migrating: true` (writers refuse from then on).
2. For each record of each old location: copy it to its v2 path (area, tag-form key,
   `log/`, `metrics/`, `outputs/`), converting metrics (plan 12 §9) on the way. Then delete the
   old copy. Record by record, so it's **resumable**: a record whose v2 `metadata.yml` exists
   is done, and its old copy is deleted on the rerun.
3. Move per-host caches out (or just drop them; they're disposable).
4. Set `layout: 2` and clear `migrating`.

- Running and stuck runs make it stop with a list, unless `--skip-live` is given (those
  are migrated by a later rerun).
- The repo-local store moves from `.vmn/<app>/experiments/` to `.vmn/store/` the same way
  (a local move, not a copy).
- `vmn snapshot` (core vmn) reads snapshots through vmn-exp's store opener when vmn-exp is
  installed; without it, core vmn's local snapshot store moves to the same
  `.vmn/store/snapshots/` layout. That's the one core-vmn change: a path in
  `version_stamp.snapshot`. Core keeps no dependency on vmn-exp.

---

## 5. Effect on plans 11–13

Plans 11–13 have been updated to the v2 paths:

| Plan | Change |
|---|---|
| 11 | Journal is `journal/` at the root (done, with `area` in the key). Permission sets become area prefix lists (§2.1). |
| 12 | Metric files under `metrics/`; migration folded into `vmn-exp migrate` (§4). |
| 13 | `reports/<rid>/{header,v<N>,comments}`; run threads under `comments/<app-key>/<verstr>/`; `vmn-reports`/`vmn-comments` pseudo-apps are gone. |

---

## 6. Implementation plan

TDD per CLAUDE.md. **Do this first, before plans 11–13**, since they all write new paths.

| Step | Tests first | Code |
|---|---|---|
| 0 bug regression | `s3://bucket/team` runs and snapshots get different keys; a snapshot and the first run of one tree both succeed (fails today) | test only, then fixed by step 1 |
| 1 areas | each area opens under `<root>/<area>/` on local, `file://`, S3 (MinIO), GCS (fake), Azure (Azurite); tag-form keys everywhere; code, sweeps and registry use areas; `reserved.py` gone and nothing lists a system record as an app | `storage/open.py`, `storage/registry.py`, `core/code_store.py`, `core/sweep/claims.py`, `registry/names.py` |
| 2 store marker | created once under a race; unknown layout refused; v1 store refused with the migrate hint; read-only commands on a missing store print "no vmn store at …" | `S/storage/store_marker.py` |
| 3 record internals | `log/`, `outputs/` paths; a user artifact named `output.log` or `media/x.png` no longer collides; lineage URIs for `outputs/…` resolve | `storage/*` log and artifact paths, `core/output_log.py`, `sdk/run_media.py`, `core/lineage.py` |
| 4 per-host state | index cache and push ledger under the cache/state dirs; `VMN_EXP_CACHE_DIR` override; two hosts on one `file://` store keep separate caches | `storage/index_cache_dir.py`, `core/push_ledger.py` |
| 5 migrate | v1 → v2 on every backend: idempotent, resumable after a kill, writers refuse while `migrating`; live runs stop it unless `--skip-live`; repo-local move | `vmn_exp/cli/migrate.py` |
| 6 legacy removal | the §3 paths deleted; their tests replaced by "v1 store refused" tests | deletions |

Then update the docs: `docs/vmn-exp/experiments.md` (storage layout section and the plugin
contract), `docs/snapshots.md` (local path), `client-guide.md` (store setup), CLAUDE.md.

---

## 7. Decisions (agreed 2026-10-02)

1. The runs area is named **`runs`**.
2. The repo-local root is **`.vmn/store/`**.
3. **One layout:** core vmn without vmn-exp also moves its local snapshots to
   `.vmn/store/snapshots/`.
