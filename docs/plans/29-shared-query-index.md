# Plan 29: fast queries on big stores (CLI/SDK answered by the server's index)

> fgm (app `fastglobalmacro`, plan 28) has an S3 store with about 667k runs, served
> by a `vmn-exp ui` server (free-threaded Python 3.15) that keeps a warm,
> journal-following index of it. Their agents and CI use the CLI and SDK, and both
> are unusable on the whole store:
>
> - `vmn-exp list --query …` timed out after 5 minutes.
> - A store-cleanup dry run (SDK `list_runs` + `archive_runs(dry_run=True)`) was
>   still building its index after 2h20m.
>
> Wishlist #2 (P0): *"Fast queries on big stores: let the CLI/SDK use the UI server's
> index, or a shared index that only needs refreshing."* Wishlist #10 (P3, fork
> safety) is **plan 30** (`docs/plans/30-fork-safety.md`); this plan only adds the
> cross-plan requirement in §13.
>
> Paths: `core/`, `storage/`, `sdk/` = `packages/vmn-exp-sdk/src/vmn_exp/…`;
> `ui/`, `cli/` = `packages/vmn-exp/src/vmn_exp/…`.

Status: **proposal** (2026-10-30, revised after review).

## 0. Why it is slow today (code at `ce017f21`)

The CLI and SDK never use the server. Each host builds its own index, and builds it
the slow way:

1. **A separate per-host index that never follows the journal.** It lives at
   `host_dirs.index_cache_path` (`storage/host_dirs.py:108-117`), one file per app.
   `index.journaled = True` is set only on the server (`ui/journal_follow.py:87`,
   `ui/cache_resync.py:37`, forwarded by `ui/elected_index.py:47`). So on S3, any
   call more than 300 s after the last full listing walks every object again
   (`core/index_sweep.py:71` `DEFAULT_FULL_SWEEP_SEC`), one `list_objects_v2` after
   another (`storage/s3_listing.py:124-184`). The walk is never persisted, so a CLI
   killed at 5 minutes keeps nothing. There is no cross-process coordination either:
   N agents on one host do N walks.
2. **No worker processes.** Remote loaders start only when `storage.worker_spec()` is
   not None (`core/index.py:809-818` `_remote_loaders`). `storage/s3.py:124` returns
   None unless `type(self) is S3SnapshotStorage`. `journaled()` does not wrap: it
   builds a mixin subclass (`JournaledS3SnapshotStorage`, with `read_class`,
   `storage/journal.py:139-160`), so the exact-type check fails. A pure-remote reader
   gets that journaled S3 storage directly from `open_storage`; a checkout gets
   `CachedSnapshotStorage`, a buffered writer `BufferedRemoteStorage`
   (`storage/open.py`). Cold loads run on the in-process `LoadPool`
   (`core/index_load_pool.py`), which on free-threaded builds is capped at the core
   count: ~109–200 runs/s (plan 27), i.e. ~1–1.7 h of reads at 667k.
3. **The parallel `Relisting`** (`core/index_relist.py`, 8 workers) runs only for a
   journaled index (`core/index_sweep.py:207-213`), so the CLI never uses it.
4. **The SDK loads everything into memory.** `list_runs` and `archive_runs` use
   `indexed_snapshot(wait=True)` (`sdk/reader.py:120`, `sdk/manage.py:69-79`), about
   4 KB per run. The CLI `list` already selects in SQL through `index_list.list_view`
   (`core/index_list.py`) without a snapshot; the SDK does not. `prune --query` calls
   `indexed_snapshot` twice (`cli/prune.py:204`, `cli/prune_query.py:23`); the second
   hits the same in-process `shared_index`, so it costs one refresh plus a second
   annotation pass, not a second build.
5. **A silent fallback.** If the index raises, `indexed_snapshot` reads every record
   serially through `direct_snapshot` (`core/index.py:1060-1099`), logged at debug.
   Prune passes `fallback=None`, so this applies to `list_runs`/`archive_runs` only.

Already there, and reused below:
- Server: `GET …/experiments` with keyset paging, `{rows, total, next_cursor}`
  (`ui/routes_leaderboard.py:86-156`, `ui/leaderboard_cache.py:516`, `MAX_PAGE = 1000`
  in `ui/http_params.py:7`); bulk actions by query with `dry_run` → `{count, sample}`
  (`ui/bulk_actions.py`, `ui/server.py:599-636`); bulk jobs with
  `progress {done, total}` (`ui/jobs.py:234-251` `submit_bulk`); `GET …/jobs/{id}`.
- Client: `vmn-exp login` saves a token whose `load_token` (`cli/login.py:49`) nobody
  calls; SDK `archive_runs` already writes through `parallel_map` → `fan_out`
  (`storage/s3_base.py:17,46-49`, `S3_WORKERS = 10`); `VMN_INDEX_CACHE_DIR` already
  relocates the host index (`storage/host_dirs.py:84-90`); `record_name_pages`
  (`storage/s3_listing.py:186`) and `Relisting(files=False)` list names only.
- Two server-side urllib clients exist (`ui/diag_cli.py`, `ui/cache_cli.py`).

## 1. Goals and non-goals

Goals:
- `vmn-exp list|archive|unarchive|tag|prune --query` and the SDK readers
  (`list_runs`, new `iter_runs`, `archive_runs`, `unarchive_runs`, new `tag_runs`)
  answer in seconds on the whole store when a server serves it.
- A cleanup (query → dry run → bulk archive) covers 667k runs in ~15–20 min with
  progress, resumable, cancelable, without blocking the UI's own edits.
- **An answer never silently drops runs.** Every answer says how fresh and complete
  it is; the client checks it; mutations refuse stale or partial answers.
- With no server, the local path stops costing hours, and a shared index that only
  needs refreshing is available as a seed (§3.5).

Non-goals (v1):
- A published snapshot in the store (plan 27 M1). It plugs in later under
  `core/query_source.py` (§9).
- A server advertisement in the store (`server/endpoint.json`). Rejected: anyone who
  can write the bucket could plant it to harvest tokens. Discovery stays explicit.
- A batched archive format (one object per many runs).
- Server memory at 10M runs (plan 27 M3).

## 2. Targets

Throughput assumptions are stated, not hoped: per-prefix cap `C` = 64 slots
(`storage/s3_prefix_cap.py`), measured S3 latency `L` (fgm: 20–60 ms), `k` calls per
run on the worker thread. Runs/s ≈ `C / (k × L)`.

| | Today at 667k | Target at 667k | Target at 10M |
|---|---|---|---|
| `list --query` count / first page, server path | > 5 min (timeout) | < 2 s | < 5 s (needs plan 27 M2) |
| Cleanup projection export (`verstr,status,archived,timestamp,tags`, ~100 B/row) | — | < 10 s, ~70 MB raw, ~8–15 MB gzip | < 60 s |
| Full lean-row export | — | **not a target** (~2.7 GB); `fields=` required past 50k rows | — |
| `archive --query --dry-run`, server path | > 2h20m | < 5 s | < 30 s (needs M2) |
| Archive execution (server or hybrid) | serial on the server (`ui/jobs_store.py:90-95`) | 500–800 runs/s (k=2, L=40 ms): 212k in ~5–7 min, 667k in ~15–20 min | same rate, resumable |
| Tag execution | serial | measured in W10 (tag = `exists` + log append + `flush_log`, each journaled; k ≈ 4) | — |
| Local path, cold host (no server, no seed) | ~2 h+ | ≤ 15 min on ≥ 8 cores; on 2 cores (`worker_count` = CPUs − 1) ~45 min, use a seed | not a target |
| Local path, warm host, gap ≤ 1 h | full re-walk if > 300 s | ≤ 5 s (journal catch-up) | ≤ 10 s |
| Local path, warm host, gap 1–47 h | full re-walk | measured in W1 against fgm's journal rate; parallel relist above the switch point (§3.4 L1) | — |
| Host RSS of a verstr-only selection (local) | multi-GB | ≤ 300 MB | O(matches) |
| S3 requests per server-path query | millions (cold) / thousands (warm) | 0 | 0 |

Before committing to the 1–47 h row, fgm is asked for one number: journal entries per
minute at peak (`vmn-exp ui diag` journal stats).

Gate: W10's benches hold twice: on a 100k MinIO store **with 30 ms injected per S3
call** (the bench wraps the client; MinIO's 1–3 ms would hide the real limits),
extrapolated, plus a synthetic 667k index for the server routes.

## 3. Design

```
 CLI (list/archive/tag/prune)                SDK readers / manage
                \                               /
          core/query_source.choose(storage, server=…)          [vmn-exp-sdk]
            ├─ server found  → core/server_query  ──urllib──►  vmn-exp ui
            │                   capabilities → NDJSON export,  GET  /api/v1/capabilities
            │                   else /experiments paging (S0)  GET  …/experiments(.ndjson)
            │                   bulk by query (dry run, job)   POST …/actions/exp_* ; /jobs/{id}
            └─ no server     → local: host index (seed? → L0 → L1), selection via list_view (L2)
                               (later: plan 27 M1 published snapshot)
```

Import rules hold: the client is in `core/` (vmn-exp-sdk), urllib only, never
imports `vmn_exp.ui`/`cli`/`version_stamp`. Job-side code (`start_run`, logging,
heartbeat) never runs discovery or calls the server; only readers and manage calls
do. Read-only actions never take the repo lock on either path, and a reader writes
nothing into the store.

### 3.0 S0: ship in days, on what exists

Day 0, no code (tell fgm now):
- The UI's bulk archive by query and `curl -X POST …/actions/exp_archive` with
  `{"q": …, "dry_run": true}` already answer the dry run from the warm index.
- Persist `VMN_INDEX_CACHE_DIR` on CI (actions/cache or a runner volume) and on
  agent hosts, so the host index survives between jobs.

S0 code (one small worktree each side):
- **Server:** the bulk job's fan-out with the batched hint (§3.1 item 5), and an
  optional `fields=` projection on the existing `GET …/experiments`.
- **Client:** `core/server_query.py` v0 (~150 lines): pages `…/experiments` with
  `limit=1000` and the cursor, uses `dry_run`, polls `/jobs/{id}`; wired into
  `vmn-exp list/archive --query` and SDK `list_runs`/`archive_runs` behind
  `--server` / `VMN_EXP_SERVER` + `load_token`. It fails if the row count ≠ `total`
  (pages can span snapshots: one retry, then `IncompleteAnswer`).

Everything below is the hardening that follows S0.

### 3.1 Server side (`ui/`)

1. **`GET /api/v1/capabilities`** (new, viewer): `{api_version, features:
   [ndjson_export, fresh_after, bulk_fanout, bulk_queue, needs_local, fields,
   index_loading]}`. The client picks the best path it supports: NDJSON, else S0
   paging, else exit 4 `server too old: upgrade it, or --server off`. Routes the
   client uses reject unknown params with `400 {"code": "unknown_param"}`; the web
   UI ships with its server, so it cannot skew.
2. **`GET …/apps/{app}/experiments.ndjson`** (new `ui/routes_export.py`). Params:
   `q, status, archived, scope, sort, order, last, fields, fresh_after, schema`.
   - Streams every matching row from **one** published snapshot (plan 27's M1
     snapshot term for the in-memory `IndexSnapshot`), in `vmn-exp list` order, no
     1000 cap. The ordered list is the memo `cache.page` already uses
     (`ui/leaderboard_cache.py:507`), so it never lists the store. After plan 27
     M2/M3 remove the full in-memory snapshot, the export streams from one SQLite
     read transaction in keyset chunks (same contract).
   - Ends with a trailer `{"_end": true, "total": N, "freshness": {…}, "now": …}`.
   - `fields=` projects rows; required (`400 fields_required`) past 50k rows.
   - gzip when accepted; a `StreamingResponse` generator.
   - A semaphore caps concurrent exports (`EXPORT_SLOTS = 4`); past it, `429` with
     `Retry-After`. The client honours it.
3. **Freshness on every list, export and bulk-preview answer.** One core function,
   `core/index_freshness.answer_freshness(index, snapshot)`, extends the existing
   `Freshness` (`as_of`, phase, progress, stalled) with `journal_ms` (cursor
   `last_seen_ms`), `complete` (false while `snapshot.loading`,
   `ui/routes_shell.py:120-126`), `unreadable`, `reconciled_at`,
   `reconcile_round_sec`. `ui/freshness.py` and the client both build from it; the
   client-side value is `AnswerFreshness` (no second `Freshness` class). A
   `_with_freshness` helper adds it to the body and an `X-Vmn-Freshness` header.
4. **`fresh_after=<now | verstrs>`** — read-your-writes:
   - `fresh_after=now` is the **server's** now (no client clock). The route waits
     (≤ 30 s) for a journal tick that started after `now + skew` (the reader's
     window), then for the refresh that completes after that tick. Implemented as
     two counters + a `Condition` in `ui/refresher.py` (`wait_past(index, t)`), since
     the journal thread and the refresh thread tick separately.
   - `wrote=<verstr,…>` (≤ 10k, POST body for more): wait until each named record is
     adopted or re-read in the published snapshot. Exact; the hybrid write uses it.
   - On timeout: `freshness.waited_out = true`. Documented limit: a journal put that
     failed stays queued in the writer until its next write (`storage/journal.py`
     `_JournalState.flush`), so only `wrote=` is exact for such a write.
5. **Bulk actions** (`ui/bulk_actions.py`, `ui/jobs_store.py`, `ui/jobs.py`):
   - **Batched hint, write-through.** Today `_bulk_action` passes
     `hint=… source.touched(…)`, which runs a full `shared_index(...).refresh()` per
     verstr (`ui/experiment_source.py:271-276`, `ui/index.py:50-52`). Instead,
     `perform` collects `(verstr, metadata, etag)` from `update_metadata` and calls
     `index.adopt_metadata(batch)` once per `MAX_ARCHIVE_BATCH` (500): rows updated
     in place, the etag recorded so the journal entry for that write is recognised
     as already applied and **not re-read**. One refresh per batch publishes the
     snapshot. Single-run actions keep `touched`.
   - **Fan-out** through `storage/fanout.fan_out` at the per-prefix cap. Note the
     shared budget (`SHARED_WORKERS` 160 − 32 `REQUEST_WORKERS`), which index loads
     also draw from; the job's width is the measured `C`, not a new constant.
   - **Fewer calls per run.** When the index holds the record's metadata etag, send
     the `IfMatch` PUT directly; GET + retry only on 412. The job's journal keys are
     flushed off the worker thread in batches (the writer's queue already allows it;
     one key per run, reader format unchanged). So `k` = 1–2, not 3.
   - **Own lane, queued.** Bulk jobs get a per-workspace FIFO queue, separate from
     single-run actions (`_active_workspaces`, `ui/jobs.py:273-276`, keeps gating
     single-run actions only). Job status reports `queued`/`position`. A bulk job
     yields between batches. `DELETE …/jobs/{id}` cancels after the current batch.
   - **Refuse on a partial index.** `resolve()` and the dry run return
     `409 {"code": "index_loading", "freshness": …}` while the snapshot is loading or
     is the empty cold placeholder.
   - Optional `max_count` (refuse if the resolve finds more) and `expect_count`
     (warn in the job log and status when the resolve finds < 90% of it).
   - Job status: `progress {done, total, failed, skipped}`; failures counted, not
     fatal. Idempotent: acts only on rows still needing the change, so a re-submit
     after a restart (jobs are in memory) does the rest.
6. **Roles and coded errors.** `dry_run` is gated at VIEWER (the EDITOR check moves
   into the handler for non-dry runs, `ui/auth/authz.py:95-96`), so audit tokens can
   preview. Every refusal carries a `code`: `read_only`, `no_edit_capability`,
   `forbidden_role`, `needs_local`, `index_loading`, `unknown_param`,
   `fields_required`, `export_busy`.
7. **`store_key`** on each entry of `GET /api/v1/workspaces` (`ui/server.py:305`).

### 3.2 Discovery and auth (`core/`)

**Store identity.** `store_key(storage)` = sha24 of `(scheme, bucket, prefix)` for
object stores — **not** `cache_identity()`, which includes `endpoint_url`
(`storage/s3.py:117-118`) and so differs between a k8s server (internal endpoint) and
a client outside (ingress/VPC endpoint). `file://` stores use the resolved path.
`--workspace` / `VMN_EXP_SERVER_WORKSPACE` overrides the mapping. A mismatch is
reported: `server <url> serves workspaces [ml: s3://a/x]; this store is s3://b/y`.

**Server URL**, first match wins (all explicit):
1. CLI `--server URL|off`, SDK `server=URL|"off"|"auto"`.
2. `VMN_EXP_SERVER` (a URL or `off`).
3. The credentials file: `vmn-exp login --server X` also calls `/api/v1/workspaces`
   and records `stores: {store_key: workspace}` next to the token.
4. None → the local path.

**Token**, first match wins: `--token` / `VMN_EXP_SERVER_TOKEN`; the credentials
entry for that URL (`load_token`), refused with the login hint once its saved
`expires_at` has passed. `VMN_UI_TOKEN` (the server's own master token) is used only
for a loopback URL.

**Transport rules.** https, or http to loopback; any other http URL needs an explicit
`--insecure-http` / `VMN_EXP_SERVER_INSECURE=1`. A no-redirect handler: a 30x is an
error naming the target, so the bearer token is never re-sent elsewhere.

**Roles** are today's: queries, streams and dry runs need viewer; bulk actions need
editor and the server's EDIT capability. CI mints a `vmnx_` API token with editor.

**Code move.** `credentials_path`/`save_token`/`load_token` move from `cli/login.py`
to `core/server_creds.py`; login imports them. A move, not a shim.

### 3.3 Client (`core/`, `sdk/`, `cli/`)

| Module | Lines | Role |
|---|---|---|
| `core/server_creds.py` | ~90 | token helpers (moved), `expires_at` check, store-key map |
| `core/server_http.py` | ~180 | urllib transport: connect 3 s / read 60 s, gzip, NDJSON iteration, no redirects, 429 Retry-After; errors by `code`: `ServerUnavailable` (refused, DNS, timeout, 502/503/504), `ServerAuthError` (401, `forbidden_role`), `ServerRefused` (other codes) |
| `core/server_discovery.py` | ~110 | `find_server(storage, flag) -> ServerTarget(url, token, workspace, app, features) \| None` |
| `core/server_query.py` | ~240 | `iter_rows` (trailer present and rows == `total`, else `IncompleteAnswer`; S0 paging when no `ndjson_export`), `count`, `bulk(action, q, status, dry_run, wait, max_count, expect_count)`: follows a queued job, polls progress, waits on `index_loading`, re-submits on a 404 job ≤ 3 times |
| `core/query_source.py` | ~140 | the policy of §4–§6 and the shared stderr messages |

`ui/diag_cli.py` and `ui/cache_cli.py` move onto `core/server_http` as a follow-up
(W11), so there is one transport.

The client sends `schema=<sha of its effective metrics schema>` with every query:
the SDK takes the schema from the checkout's conf over store settings
(`sdk/reader.py` `_metrics_schema`), which decides `metrics.x` and sort direction.
The server answers `needs_local` when it differs from the workspace's schema.

SDK (`sdk/reader.py`, `sdk/manage.py`, `sdk/__init__.py`):
- `list_runs(…, server="auto", max_staleness=None, fresh_after=None, stale_ok=False)`
  keeps its row shape and order, and returns `RunList(list)` with `.freshness`
  (per answer; no process-global `last_answer_freshness`, which is ambiguous across
  threads).
- `iter_runs(…, fields=…)` streams rows without holding 667k dicts.
- `archive_runs`/`unarchive_runs`/new `tag_runs(query=…)` gain `server=`, `wait=True`,
  `write="auto"|"server"|"local"`; they return the verstrs acted on (or that would
  be, with `dry_run`) as a `RunList`. `wait=False` returns the job id.

CLI (new `cli/server_args.py`, wired into `cli/experiment.py` `_listed`,
`cli/manage.py` `_archive_by_query`, `cli/prune.py`/`cli/prune_query.py`):
`--server URL|off`, `--workspace`, `--insecure-http`, `--max-staleness SEC`,
`--fresh-after now`, `--write server|local`, `--stale-ok`, `--strict`, `--no-wait`,
and `list --ndjson`; new `vmn-exp jobs wait|cancel <id>`. CI can submit with
`--no-wait` after the dry-run check and follow with `jobs wait`. Every answered
command prints one stderr line, or puts it under `freshness` with `--json`:

```
served by https://vmn.example (ws ml): as of 2s ago, complete, 667,112 runs
index: this host, as of 14:03:07Z (journal +8m, reconciled 3h ago, 12 live runs probed)
```

### 3.4 The local path (server off or none)

New logic goes into new modules; `core/index.py` (1,113 lines) only gains call sites.

- **L0a, worker processes for journaled S3.** `storage/s3.py` `worker_spec` checks
  `getattr(type(self), "read_class", type(self)) is S3SnapshotStorage` (as
  `storage/local.py:76-79` does). `CachedSnapshotStorage` and
  `BufferedRemoteStorage` get **no** worker spec: their reads merge local-only,
  unpushed records and unshipped segments that a bare-S3 worker would miss. A
  checkout's cold build therefore uses the in-process pool, or a seed (§3.5).
- **L0b, parallel resumable first listing.** A cold S3 refresh uses `Relisting`
  key-range walks (`core/index_relist.py`) instead of the serial `_walk`, with range
  progress in kv (`relist-progress:<app>`) so a killed process resumes. **Before** the
  listing starts, the index records the journal mark `listing_start − skew_window_sec`
  (300 s) and persists it with the records, as the server's first full listing does
  (`core/index_sweep_behind.py` `journal_at`/`persistable_mark`), so writes made
  during a multi-minute listing are replayed by L1.
- **L0c, per-host build lease** (new `core/index_lease.py`). A file lock next to the
  host index (`host_dirs` index dir, outside the store). The holder builds or
  catches up; other processes wait, printing the holder's progress from kv, or serve
  persisted rows with `--stale-ok`.
- **L0d, prune resolves once** (`cli/prune.py:204`, `cli/prune_query.py:23`): saves
  one refresh and one annotation pass. Small.
- **L0e, no silent full read.** The `direct_snapshot` fallback is removed for remote
  stores (the error raises); local stores keep it with a WARNING naming the reason
  and the record count.
- **L1, journal catch-up.** New `core/index_journal_catchup.py`: the single-app
  replay-from-mark now in `ui/journal_follow.WorkspaceJournal` moves here and the
  server calls it, so the paths cannot diverge. `catch_up(index, storage, now)`:
  `resume_journal(mark)` → `JournalReader` ticks (`core/journal_reader.py:42`) →
  `hint(name)` per entry, `overflowed(names)` on overflow → `journal_at(cursor)` →
  `refresh()`. Live records get a `run_state.yml` probe (heartbeats are not
  journaled).
  - The journal is one store-wide stream (`docs/vmn-exp/server.md:244-252`): a gap
    of G minutes lists ~G partitions plus extra pages for busy minutes. Above a
    switch point (initially 6 h or 200k entries, set from W1's bench and fgm's
    journal rate) catch-up does an L0b parallel relist instead.
  - The reader filters keys by the app's scope **before** recording them in `_seen`,
    so its memory is bounded by this app's entries, not the store's.
  - A mark past retention − `REPLAY_MARGIN_SEC` → parallel relist (L0b).
  - **Bounded drift.** The host index persists `reconciled_at` (last full relist).
    When it is older than 24 h, an L0b relist runs behind serving (under the lease)
    and the answer says `reconciled 26h ago, relisting`. Mutations warn past 24 h
    and refuse past 7 days unless `--stale-ok`.
- **L2, selection by SQL = an extension of `index_list.list_view`.** No new selector.
  `list_view` (already SQL-first for the CLI) gains a streaming mode for the SDK and
  prune: SQL survivors are grouped **by root**, each chunk is decoded with its tree
  closure (`_with_trees`: ancestors plus all descendants) and re-checked by
  `filter_rows`, so depth/root/`under()`/children/`tree_status`/`child_counts` stay
  exact. Status is always re-derived. A pure-SQL answer (no decode) is allowed only
  when every clause is on a value that cannot drift: `archived`, `parent`, `verstr`,
  `name`, and terminal statuses (`succeeded`/`failed`); `running`/`stuck`/`created`
  always decode (`_narrow` widens them for this reason). The "≥ half kept → full
  snapshot" rule (`core/index_list.py:110-119`) becomes the chunked decode.
  `archive_runs`, `list_runs`, `iter_runs` and prune use it instead of
  `indexed_snapshot(wait=True)`.
- **L3, local writes.** The SDK path already fans out (`parallel_map`,
  `S3_WORKERS = 10`); it moves to the measured prefix cap with progress. Write-through:
  `update_metadata` returns `(metadata, etag)` and the process adopts it
  (`index.adopt_metadata`, the same call as §3.1 item 5), so its next query re-reads
  none of the archived records.

### 3.5 A shared index that only needs refreshing (seed)

The other half of wishlist #2, for hosts that cannot use the server for queries
(air-gapped laptops, `--server off`, an outage) and for ephemeral CI.

1. **CI cache recipe** (docs + an e2e test, no new code once L1 lands): persist
   `VMN_INDEX_CACHE_DIR`; the next job runs L1 catch-up from the cached mark.
2. **`GET …/apps/{app}/index-seed`** (viewer): the server's database is per store
   (`ui/index.py:82`) and the client's per app, so the server writes a per-app,
   read-only SQLite extract through `core/sqlite_conn` (backup API into a temp file),
   gzip-streamed, with its journal mark and `reconciled_at`. The client verifies it,
   installs it at `host_dirs.index_cache_path`, then runs L1. Same trust model as the
   queries (the URL is explicit). The size at 667k is measured (W10) before this
   ships; if it is too big, it waits for plan 27 M1's parts.
3. **`vmn-exp index export|import FILE <app>`** for sneakernet: the same file format,
   produced from any host's index.

`core/query_source` treats a seed as a source of the local path: seed (if offered and
the host has none) → L1.

## 4. Freshness and correctness contract (never silently miss runs)

Both paths return the same `AnswerFreshness`: `source` (`server` | `host+journal` |
`seed+journal` | `first-build`), `as_of`, `journal_ms`, `complete`, `unreadable`,
`reconciled_at`, `reconcile_round_sec`, `waited_out`.

| Condition | Lists | Mutations (archive/unarchive/tag/prune) |
|---|---|---|
| Server `complete=false` / `index_loading` | wait with progress up to `--wait-index` (10 min), then exit 3 | same |
| Trailer missing or rows ≠ `total` | retry once, then `IncompleteAnswer`, exit 3 | same |
| Job `total` < 90% of the dry-run count | — | job warns; client prints it and exits 3 with `--strict` |
| `unreadable.count > 0` | answer + stderr warning; `--strict` fails | fail unless `--stale-ok` |
| `refresh_failing`, or `as_of` older than `max_staleness` (default none for lists, **600 s for mutations**) | warn | refuse, exit 3 (`--max-staleness 0` disables) |
| Local `reconciled_at` > 24 h / > 7 d | relist behind serving, warn | warn / refuse |
| Local: journal LIST fails, or mark past retention and the relist fails | `IndexStaleError`, exit 3 | same |
| `--stale-ok` / `stale_ok=True` | answer from persisted rows, as-of printed | same |
| During a cold local build | wait (lease holder's progress); never the empty "loading" snapshot | same |

How stale an answer can be:
- A journaled write: ~1–2 s on the server; `fresh_after=now` bounds it, `wrote=` makes
  it exact. **After a bulk write** of other clients (each run is one journal entry;
  above 10,000 per scope per tick the reader overflows and re-reads at
  `HINTS_PER_REFRESH = 2000` per refresh, ~3 LISTs + GETs each), a server or L1 host
  that did not adopt the writes is stale for minutes. The server's own jobs adopt
  (no re-read). Hybrid writers post `wrote=` verstrs with their etags to
  `POST …/apps/{app}/adopt` (editor; the server re-reads only names whose etag it
  does not hold). W10 benches staleness after 100k writes.
- A write whose journal entry was lost, or an out-of-band edit: until the next
  consistency round (`MAX_RECHECK_PER_SEC = 50` → ~3.7 h at 667k on the server, the
  local bound above on hosts). Reported in `reconcile_round_sec` / `reconciled_at`.
- `--verify-names` (audits): a names-only listing built on `record_name_pages`,
  split at the answer's verstrs as `StartAfter` boundaries so it runs in parallel
  (~670 LIST pages at 667k), diffed against the answer; missing runs are reported
  and, locally, hinted.
- Status is derived at answer time (server: its clock, `now` in the trailer); never
  stored, never answered from the stored column for non-terminal statuses.

**Parity.** Server rows must equal `list_runs(server="off")` row for row: keys,
order, status, `last`/sort/archived semantics, under the same metrics schema (the
`schema` hash). A parity matrix (§10) enforces it; on `needs_local` the client warns
and answers locally.

## 5. The cleanup flow end to end

```
$ vmn-exp archive --query 'status = "failed" and created_at < ago("30d")' --dry-run fastglobalmacro
served by https://vmn.example (ws ml): as of 1s ago, complete, 667,112 runs
would archive 212,480 runs, e.g. fastglobalmacro_0.0.1-… (10 shown)
$ vmn-exp archive --query '…' fastglobalmacro
job j_42: queued (1 ahead)
job j_42: 98,000 / 212,480 done, 0 failed, 640 runs/s, ETA 3m
archived 212,480 runs
```

1. Dry run (viewer) → `{count, sample, freshness}`; `index_loading` → wait.
   Mutations check the 600 s staleness bound first.
2. Submit with `max_count = count × 1.05`, `expect_count = count` → the job queues in
   the bulk lane, resolves the query again (refusing on a partial index), and acts
   at the prefix cap on rows still needing it, adopting each batch.
3. The client follows the job (queued position, progress, ETA). On a server restart
   (job 404) it re-submits, and the job does only the remainder. Ctrl-C asks whether
   to cancel (`DELETE /jobs/{id}`) or leave it running; `--no-wait` prints the id.
4. UI single-run actions keep working during the job (separate lane).

SDK: `archive_runs(app, query=…, dry_run=True)`, then `archive_runs(app, query=…)`;
`iter_runs(app, query=…, fields=…)` for audits.

**Server cannot write** (`read_only` or `no_edit_capability`). With `write="auto"`
the client streams `fields=verstr,archived` and writes locally with its own
credentials through `fan_out` (L3), then posts `adopt`. `forbidden_role` never falls
back.

**Prune.** Candidates come from the server (or L2); deletion is always local, and
each candidate's record is re-read before it is deleted.

## 6. Failure modes, offline, server down

| Condition | Server set explicitly (flag/env/credentials) | `server="auto"` with no configured server |
|---|---|---|
| Unreachable, timeout, 5xx | fail fast, exit 4: `server <url> unreachable; --server off to use this host's index` | — (local path) |
| 401, `forbidden_role`, token expired | fail: `run: vmn-exp login --server <url>`; never a fallback | — |
| `read_only` / `no_edit_capability` | hybrid local write (§5) | — |
| No workspace serves this store | fail, exit 4, naming the served stores | — |
| No `capabilities` route / too old | S0 paging if `/experiments` works, else exit 4 `server too old` | — |
| `index_loading` | wait ≤ `--wait-index`, then exit 3 | — |
| 429 `export_busy` | retry after `Retry-After` | — |
| `needs_local` | warn, answer locally | — |
| 30x redirect | fail, naming the target | — |

An unreachable explicit server never falls back silently. Air-gapped: a LAN server
works over plain urllib; with no server the local path needs only the store, and
`vmn-exp index import` can seed it.

## 7. Auth and security

- No credentials are issued by the server (plan 11 invariant): hybrid and local paths
  use the caller's own store credentials.
- Every server URL comes from the user, so a bucket writer cannot redirect a client.
- Tokens: never logged, never in `--json` output, never sent over non-loopback http
  without `--insecure-http`, never re-sent on a redirect, refused past `expires_at`.
  `VMN_UI_TOKEN` only to loopback. The credentials file stays mode 0600.
- A seed file is SQLite opened read-only through `core/sqlite_conn`, schema-version
  checked before install.
- Rows carry only what records carry (changeset remotes are already redacted).

## 8. S3 cost

- Server path: 0 requests per query. The server already pays ~1 LIST/s for the
  journal (~86k/day) whether or not anyone queries.
- Archive, end to end: GET (skipped when the etag is known) + `IfMatch` PUT +
  journal PUT, plus on every follower that did not adopt: ~3 LISTs + GETs per
  overflowed name. Adopted writes: ~2–3 per run (212k ≈ 0.6M requests ≈ $3);
  unadopted: ~6–7 per run per follower (212k ≈ 1.4M). Tags: measured (k ≈ 4 + log).
- Local warm (L1): one LIST (plus pages) per journal minute of the gap + hinted
  records + 1 GET per live run. ~60 LISTs for a 1 h gap; a 47 h gap is ~2,800+
  partitions, which is why the switch point exists.
- Local cold (L0): one parallel object walk + ~3 GETs per run (~2M at 667k), once per
  host (or per lease) instead of every 300 s; zero with a seed.

## 9. Relation to plan 27

- **Delivered here:** the server answers the CLI/SDK, the freshness contract, the
  bulk lane, and the local path's L0a (`worker_spec`), L0b (resumable parallel
  listing + mark) and L1 (`core/index_journal_catchup.py`, the catch-up plan 27 M1's
  consumer also needs). Plan 27 M5 (lean, parallel first build) builds on L0a/L0b.
- **Later (plan 27 M1, published snapshot):** a third `query_source` option,
  consuming into `host_dirs.index_cache_path` then running L1; §3.5's seed is the
  per-request precursor and shares its install step. It reuses `AnswerFreshness`,
  `RunList` and `IndexStaleError` unchanged.
- **Depends on plan 27:** the 10M targets need M2 (queries compiled to SQL; L2's
  pushdown is replaced by M2's `core/index_query_sql.py`, and the conformance corpus
  is shared with it) and M3 (bounded hot set; the export moves to keyset chunks from
  one SQLite read transaction, §3.1 item 2).
- Follow-up: plan 27's text should name L0a/L0b as M5's base and the export's
  post-M3 shape (an edit to plan 27, outside this plan).

## 10. Work units and test plan (TDD: red first in each worktree, ≤ 300 lines/file)

| # | Unit | Files | Depends on |
|---|---|---|---|
| S0s | Server: bulk fan-out + batched adopt hint; `fields=` on `/experiments` | `ui/jobs_store.py`, `ui/bulk_actions.py`, `ui/experiment_source.py`, `core/index_adopt.py` (new: `adopt_metadata`), `ui/routes_leaderboard.py` | — |
| S0c | Client v0: `/experiments` paging, dry run, job polling; list/archive + SDK wiring | `core/server_query.py`, `core/server_creds.py` (move), `cli/login.py`, `cli/server_args.py`, `sdk/reader.py`, `sdk/manage.py` | — |
| W0a | `worker_spec` via `read_class`; none for Cached/Buffered | `storage/s3.py` | — |
| W0b | Resumable parallel first listing + pre-listing mark | `core/index_first_listing.py` (new), `core/index_sweep.py` | — |
| W0c | Prune once; no silent `direct_snapshot` for remote | `cli/prune*.py`, `core/index.py` (call site) | — |
| W0d | Per-host build lease | `core/index_lease.py` (new), `storage/host_dirs.py` | — |
| W1 | L1 catch-up, scope-filtered `_seen`, switch point, `reconciled_at` + drift relist; server reuses it | `core/index_journal_catchup.py`, `core/journal_reader.py`, `ui/journal_follow.py` | W0b |
| W2 | Transport: no redirects, insecure-http rule, `expires_at`, coded errors | `core/server_http.py`, `core/server_creds.py` | S0c |
| W3a | NDJSON export + export cap + `schema`/`needs_local` | `ui/routes_export.py` | — |
| W3b | `answer_freshness` + header + `store_key` + `capabilities` + coded errors + viewer dry run | `core/index_freshness.py`, `ui/freshness.py`, `ui/routes_leaderboard.py`, `ui/server.py`, `ui/routes_capabilities.py` (new) | — |
| W4 | `fresh_after=now` (journal tick + refresh) and `wrote=`; `POST …/adopt` | `ui/refresher.py`, `ui/routes_adopt.py` (new) | W3b, S0s |
| W5 | Bulk lane: FIFO queue, cancel, yield, `index_loading` refusal, `max_count`/`expect_count`, etag-direct PUT, async journal flush | `ui/jobs.py`, `ui/jobs_queue.py` (new), `ui/jobs_store.py`, `storage/s3_records.py`, `storage/journal.py` | S0s |
| W6 | Discovery + `query_source` + full `server_query` (NDJSON, capabilities, queue following) | `core/server_discovery.py`, `core/server_query.py`, `core/query_source.py` | W2, W3a, W3b |
| W7 | L2 streaming `list_view` by root with closure + L3 local writes | `core/index_list.py`, `core/index_list_stream.py` (new), `sdk/manage.py` | W0a |
| W8 | SDK: `list_runs`/`iter_runs`/`archive_runs`/`tag_runs`, `RunList`, `wait=False` | `sdk/reader.py`, `sdk/manage.py`, `sdk/__init__.py` | W6, W7 |
| W9a | CLI flags, wiring, exit codes 3/4, `--ndjson`, `--no-wait`, `jobs wait|cancel` | `cli/server_args.py`, `cli/experiment.py`, `cli/manage.py`, `cli/prune*.py`, `cli/jobs.py` (new) | W8 |
| W9b | `--verify-names` on `record_name_pages` with StartAfter splits | `core/name_verify.py` (new) | W8 |
| W12 | Seed: `index-seed` route, install, `index export|import` (after the size bench) | `ui/routes_seed.py`, `core/index_seed.py`, `cli/index_cmd.py` | W1 |
| W10 | Parity matrix, MinIO e2e with latency injection, serial benches | `packages/vmn-exp/tests/` | W8, W9a |
| W11 | Docs + skill regeneration; diag/cache CLIs onto `server_http`; then `/simplify` | `docs/vmn-exp/*.md`, `docs/vmn-exp/agent-skill.md`, CLAUDE.md env line, plans README row, `ui/diag_cli.py`, `ui/cache_cli.py` | all |

S0s, S0c, W0a–d, W3a, W3b run in parallel. Tests (exp suite; targeted runs only):

- **S0s/W5:** a 1,000-run bulk archive calls `index.refresh()` at most
  ⌈1000/500⌉ + 1 times and the next list sees every change; concurrency of
  `update_metadata` reaches the cap (fake storage counting it); adopted writes are
  not re-read when their journal entries arrive; a single-run UI action succeeds
  while a bulk job runs; a second bulk job queues and reports its position;
  `DELETE` cancels after the current batch; resolve during `snapshot.loading` → 409
  `index_loading`; `max_count` refusal; `expect_count` warning; an interrupted job
  re-submitted acts only on the remainder; a 412 on the etag-direct PUT falls back
  to GET + retry.
- **S0c:** paging across a snapshot change with a count mismatch retries once, then
  `IncompleteAnswer`.
- **W0a:** `worker_spec()` is not None for `journaled(S3)`, None for
  `CachedSnapshotStorage` and `BufferedRemoteStorage`; a checkout with a local-only
  record does a cold load and the record is in the answer.
- **W0b:** > 1 range walk at once; killed mid-walk, a restart resumes (LIST pages
  counted); a write made mid-listing is in the index after L1.
- **W0c/W0d:** prune resolves once; an injected index error on a remote store raises
  and never calls `direct_snapshot`; two processes, one walk (the second waits and
  then reads the first's rows).
- **W1:** catch-up from a mark hints exactly the journaled names, persists the new
  mark, returns None past retention − margin, probes live records with 1 GET and 0
  LISTs; `_seen` holds only the app's scope (other apps' keys not retained); a gap
  past the switch point relists; `reconciled_at` > 24 h starts a relist behind
  serving; `ui/journal_follow` tests stay green unchanged.
- **W2/W6 (fake transport):** discovery precedence; store-key lookup ignores the
  endpoint; `--workspace` override; non-loopback http refused without
  `--insecure-http`; a 30x is an error and the token never reaches the target;
  expired token → login hint; `VMN_UI_TOKEN` not sent to a non-loopback URL;
  trailer/count checks; `index_loading` waits then fails; stale → mutation refused,
  list warns; 401 → no fallback; unreachable → exit 4; job 404 → re-submit;
  `read_only` and `no_edit_capability` → hybrid write, `forbidden_role` → fail; no
  capabilities route → S0 paging.
- **W3/W4 (TestClient, local-file store):** NDJSON returns every row from one
  snapshot even with a run created mid-stream; `fields`; `fields_required` past 50k;
  trailer; gzip; 429 past `EXPORT_SLOTS`; `X-Vmn-Freshness` on 304; schema mismatch →
  `needs_local`; viewer dry run allowed, viewer bulk refused with `forbidden_role`;
  `fresh_after=now` returns only after a journal tick and a refresh both started
  after the call; `wrote=` waits for named records; server `store_key` == client's.
- **W7:** conformance corpus incl. tree fields (depth, root, `under()`, children,
  `tree_status`, `child_counts`) and `running`/`stuck`/`created`: the streamed
  selection == `filter_rows` over the full snapshot; pure-SQL answers only for
  non-drifting clauses (a stuck run whose stored status is `running` is selected by
  `status = "stuck"`). Peak memory of a verstr-only selection over a 200k synthetic
  index under a bound (tracemalloc). No `indexed_snapshot` on the SDK paths. After a
  local bulk archive, the next query in the same process re-reads 0 records.
- **W10 parity:** one fixture store with nested parents, archived runs, tags, params,
  metrics and running/stuck/failed runs; for a query matrix,
  `list_runs(server=<testclient>) == list_runs(server="off")`, both dry runs agree,
  `vmn-exp list --json` agrees; a case where the checkout conf's `experiment.metrics`
  differs from store settings (→ `needs_local`, same final answer); an old-server
  case (no capabilities route) with a new client. **e2e:** a real `vmn-exp ui
  --store` subprocess on MinIO plus CLI subprocesses: discovery via the credentials
  map, exit 4 when the server is killed, zero S3 calls on the server path
  (`s3_stats`); the CI cache recipe (cached `VMN_INDEX_CACHE_DIR` → catch-up only).
  **Serial benches** (`@pytest.mark.serial`, 30 ms injected per S3 call): synthetic
  667k index for the projection export < 10 s and dry run < 5 s, server RSS delta
  < 200 MB while streaming, UI p95 with 4 concurrent exports; bulk archive runs/s on
  100k (archive and tag); staleness of a follower after 100k unadopted writes; local
  cold build runs/s at 2 and 8 cores; warm catch-up time at 1 h and 24 h gaps; seed
  size at 667k (extrapolated).

Rollout: S0 first (days), then server endpoints (additive), then the client
defaulting to `auto`. fgm's CI gets the speed once it sets `VMN_EXP_SERVER` +
`VMN_EXP_SERVER_TOKEN` (or ran `vmn-exp login` once); their cleanup script then
needs no change. No compat shims.

## 11. Risks

- **Row parity.** A parity gap silently changes a cleanup's selection. Mitigated by
  the matrix, the schema hash and `needs_local`; a new row field joins the matrix.
- **10M on the server** is Python over the snapshot until plan 27 M2.
- **Bulk jobs live in server memory.** Queue + re-submit cover restarts; 10M-run jobs
  need persisted jobs (open question 4).
- **Unadopted bulk writes** (other writers, out-of-band scripts) flood followers'
  overflow re-reads for minutes. Measured; a one-entry-per-batch journal format is
  open question 6.
- **Unjournaled writes** stay invisible until a consistency round (server ~3.7 h) or
  the local drift bound (24 h). Reported; `--verify-names` catches new/deleted runs,
  not content edits.
- **Explicit-only discovery**: a host with no configuration takes the local path; the
  stderr line names the source, so agents see it.
- **Moving the journal replay into core** must keep the server's election and relay
  paths unchanged (W1's gate).
- **urllib has no keep-alive**: fine for one NDJSON stream, slow for S0 paging (667
  requests for the whole store; S0 is the stopgap).
- **Unknowns about fgm:** their vmn_exp version, whether their CLI runs in a checkout
  (`storage/cached.py:223-227`) or pure-remote, whether their server has EDIT
  capability, their endpoints (inside/outside k8s), their journal rate, and where the
  2h20m went. Ask for a py-spy dump or debug log of one run.

## 12. Open questions

1. Should `server="auto"` with a configured but unreachable server ever fall back
   (with a cost warning) instead of exit 4? Proposed: no.
2. Default `max_staleness` for mutations: 600 s, or tie it to `reconcile_round_sec`?
3. Bulk archive role: editor for any count, or admin past N runs (plan 23 §8 item 2)?
4. Persist jobs (SQLite next to the index, via `core/sqlite_conn`) in v1, or later?
5. Should `prune` ever run server-side? Proposed: no.
6. A one-entry-per-batch journal record for bulk writes (a reader format change),
   if W10's follower-staleness bench misses?

## 13. Fork safety (wishlist #10) — see plan 30

Plan 30 is the canonical plan. Cross-plan requirement: every thread, pool or lock
this plan adds (`Relisting` workers in the first listing, the catch-up
`JournalReader` workers, the bulk/`fan_out` writers, `core/index_lease.py`, the
`server_http` client, the export/streaming iterators) is created through plan 30's
`core/fork_reset` factories and covered by its ratchet (`test_fork_reset_coverage.py`)
and storage quiesce. W10 adds one test: `os.fork` in a pool worker while the parent
is inside `iter_runs` (both paths), and the child neither hangs nor corrupts the
host index. Plan 30's W6 (readers and SQLite) is sequenced after W0b/W1/W7 here.

## 14. Out of scope

- The published snapshot in the store (plan 27 M1; §9).
- A query→SQL compiler beyond today's pushdown (plan 27 M2).
- A batched archive format (one object per many runs).
- Server-side prune.
