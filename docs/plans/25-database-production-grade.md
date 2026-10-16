# Plan 25: production-grade database use (index cache, Postgres server, control plane)

> The data model is right. Storage is the source of truth, and every database is a
> rebuildable cache (plan 11 §2) or the control plane. Every query is parameterized.
> An audit on 2026-10-16 (three code reads, key claims re-checked against the source)
> found gaps on every layer:
>
> - **Per-command cost grows with every run in the app.** Each fresh CLI/SDK process
>   1. decodes every record from SQLite (`core/index_store.py:load` →
>      `decode_records`),
>   2. rebuilds every side table (`index_snapshot.py`, `index_views.py:lean_row`;
>      none of them are persisted),
>   3. and lists the whole store twice (`index_sweep.py:56`,
>      `DEFAULT_FULL_SWEEP_SEC = 0`; a full prefix LIST on S3).
>
>   `vmn-exp show -v <exact verstr>` loads every run to show one
>   (`cli/experiment.py:780`, `placement_snapshot`), and so does `reader.get_run`.
>   `refresh_if_stale(max_age_sec=0)` can never be fresh (`index.py:184`), so
>   `wait=False` callers (the sweep early-stopper, sweep agent claims, `vmn-exp watch`)
>   do a full listing each time. The audit estimates 5–15 s per `list`/`show`/
>   `similar`/`get_run` at 100k runs (unmeasured; F0 measures it).
> - **SQLite.**
>   - A delta fetches every record and filters in Python (`_delta` → `_records` →
>     `_select`), and there is no `seq` index.
>   - `_bump_generation` reads `gen` outside the implicit transaction, so concurrent
>     writers can both write `gen+1`.
>   - WAL runs with `synchronous=FULL` (the default), so every refresh fsyncs.
>   - Rebuild and corruption recovery delete `-wal`/`-shm` and replace the file under
>     live connections (`ui/cache_rebuild.py:46-53`, `_remove_database`).
>   - An open failure disables the store for the process; a failed save is lost
>     silently.
>   - A schema mismatch drops tables non-atomically, so two versions sharing a file
>     wipe each other.
>   - Nothing guards against a cache dir on NFS.
> - **Postgres.**
>   - The control plane and search hold one connection opened at start and never
>     reconnect (`control_plane_pg.py:22`, `search_pg.py:20`).
>   - Nowhere sets a statement or connect timeout or keepalives. There is no pool:
>     each store funnels every call through one connection behind a lock.
>   - `credential_org` filters `WHERE id = %s` against a `(org_id, id)` primary key,
>     with no index on `id`. That is a sequential scan per authenticated request, and
>     expired sessions are never deleted.
>   - API tokens are verified with scrypt per request (`auth/tokens.py`).
>   - The audit log is loaded whole per page and per count, with no retention.
>   - Deltas load the whole scope (`cache_pg.py:_records`).
>   - `vmn_search_rows` has no `org_id`/RLS, and replicas rewrite it with racing
>     DELETE+INSERT.
>   - Migrations re-run on every reconnect.
> - **Control-plane SQLite** (`ui/control_plane.py:75`) sets no pragmas (no WAL, no
>   busy_timeout) and has no backup command, although `server.md` says to back it up.
>
> **No compatibility.** Cache schemas are bumped and rebuilt. Control-plane tables migrate
> forward with no down path. Output and API shapes may change where that is simpler.

## 1. Targets (measured by F0, enforced as `@pytest.mark.serial` benches)

At 100k runs in one app, on a local store. "Cold process" is a fresh process reading
the persisted index, measured as wall time **minus an import-only process** of the same
run. The interpreter and import floor (0.16–0.25 s on Python 3.9; 0.23 s before the lazy
`questionary` import) is out of scope. A fresh `vmn` command in a git checkout also pays
about 0.1–0.2 s of fixed GitPython setup and `git` subprocesses, whatever the run count,
and that is included. The original wall-clock reading of these budgets could not be met
for `show`: the import alone took longer than 0.2 s.

| command | cold process | warm process / UI |
|---|---|---|
| `vmn-exp show -v <exact>` / `reader.get_run` | ≤ 0.2 s | ≤ 20 ms |
| `vmn-exp list --last 20` | ≤ 1 s | ≤ 50 ms |
| `vmn-exp list --query …` (whole app) | ≤ 2 s | ≤ 300 ms |
| `vmn-exp similar` (plan 24) | ≤ 1 s | ≤ 0.1 s |
| refresh after 100 changed runs | ≤ 0.2 s | ≤ 0.2 s |
| extra resident memory for `show`/`get_run` | ≤ 50 MB | — |

On S3, a cold short command does at most one LIST page per changed prefix, never a full
prefix LIST, unless the persisted listing baseline is missing.

Postgres server: p99 ≤ 10 ms for an authenticated request's database work at 1M sessions.
A database restart is survived with no process restart; requests fail fast
(≤ `statement_timeout`) while the database is down and recover within 5 s after it is back.

## 1.2 Results after F0–F6 (measured 2026-10-16, 100k runs, load ≈ 7)

Median of 5 fresh processes on the persisted index (`/tmp`-style bench of
`bench_scale.py`'s cases):

| command | wall | net of import (0.196 s) | target | |
|---|---|---|---|---|
| `vmn-exp show -v <exact>` | 0.352 s | 0.156 s | ≤ 0.2 s | met |
| `reader.get_run(<exact>)` | 0.139 s | below the CLI import (imports the SDK only) | ≤ 0.2 s | met |
| `vmn-exp list --last 20` | 0.453 s | 0.26 s | ≤ 1 s | met |
| `vmn-exp list --query 'status = "failed"'` | 1.37 s (load ≈ 26) | ≈ 1.1 s | ≤ 2 s | met |
| `vmn-exp similar --text-only` (plan 24) | 0.80 s (load ≈ 26) | ≈ 0.57 s | ≤ 0.3 s | see plan 24 F1 |
| peak RSS `show` / `get_run` | 82 / 64 MB | 40 / 22 MB over import | ≤ 50 MB | met |

A names-only scan of 100k record directories costs ~45 ms with a warm OS cache (0.3 s
cold). A point read skips it when the app directory's mtime has not moved since the last
sync. Building the index from an empty cache is still 40–80 s at 100k and 3.3 GB. That is
a one-time cost per host, not covered by these targets.

## 1.1 Baselines (measured 2026-10-16)

`packages/vmn-exp/tests/scale_store.py` writes the store: one app, layout 2, format-2
runs (params, a `features` entry, a 150-word intent over a 20k-word vocabulary with 5
keywords, 3 metrics × 20 steps in one `.vmx`), a third of them inner runs of an outer
run, 75% succeeded, 15% failed and 10% running (stuck once the cached store ages). It
takes 7 s for 20k runs and 38 s for 100k, and is cached under
`$TMPDIR/vmn-scale-store/v<VERSION>-n<N>`. `packages/vmn-exp/tests/bench_scale.py`
runs each case in a fresh process in a checkout whose `.vmn/store` links to it. *Cold*
starts with an empty `VMN_EXP_CACHE_DIR`; *warm* runs the same command again on the
index file the cold run left (93 MB at 20k, 467 MB at 100k).

The machine was an Apple M5 Pro (15 cores, APFS) on Python 3.9.6, shared with other
test runs (load average 3–25), so single numbers move by up to 2×. The table gives
the second of two runs; the first run's figure follows it where they differ by more
than 30%. Memory is the process's peak RSS; importing the CLI alone takes 0.25 s and
42 MB.

| command | 20k cold | 20k warm | 100k cold | 100k warm | peak RSS 20k / 100k |
|---|---|---|---|---|---|
| `vmn-exp show -v <exact>` | 5.5 s (8.6) | 3.9 s (12.8) | 66 s (42) | 45 s | 0.63 / 3.0 GB |
| `reader.get_run(<exact>)` | 5.3 s (12.1) | 3.6 s | 58 s | 24 s (50) | 0.61 / 2.9 GB |
| `vmn-exp list --last 20` | 6.0 s (11.7) | 4.4 s | 45 s (101) | 23 s (77) | 0.73 / 3.5 GB |
| `vmn-exp list --query 'status = "failed"'` | 6.0 s (19.0) | 4.4 s (9.9) | 58 s (88) | 41 s | 0.72 / 3.5 GB |
| `vmn-exp similar --text-only --context …` | 8.6 s (20.0) | 8.3 s | 55 s | 37 s | 0.94 / 4.6 GB |

Every row misses its §1 target by two orders of magnitude, warm as well as cold, and
memory by 50×. A warm process is barely faster than a cold one because it repeats the
expensive parts. A profile of a warm `list --last 20` at 100k (25 s under the profiler)
spends 11 s in the full stat sweep of the store (`index_sweep._full_listing` →
`local.list_files`, F2), 4 s copying every row (`index._row_copies`) and 1.6 s decoding
the persisted records (`index_store.load`, F1). `show` and `get_run` pay the same as
`list`, because they build the whole snapshot to resolve one exact verstr.

## 2. Decisions

- **Persist what is read, not what is folded.** `exp_index` keeps the full record for
  refolding. A new lean `exp_rows` table holds each run's lean row (the columns `list`
  sorts and filters on as real SQL columns: `idx`, `status`, `parent`, `root`,
  `timestamp`, `name`, `archived`, plus the row JSON). The side tables (`features`,
  `intents`, `outputs`, `metric_parts`, `declared_defs`, `hypotheses`) are persisted as
  well. All of them are written in the same transaction as the record.
- **Point reads stay point reads.** Resolving an exact verstr, `@N`, a unique prefix or
  `latest` is one indexed query on `exp_rows`. `show`/`get_run` need no snapshot.
  Building a full snapshot becomes lazy (only `list` over the whole app, `similar`, the
  UI).
- **Revalidation is incremental across processes.** The listing baselines
  (`ListingWatch._prints`, `RecordListings._settled`) are persisted per app. A cold
  process lists only names (one pass) and re-reads records whose signature moved. The
  full stat sweep runs on a schedule (`full_sweep_sec`, default 300), not on every
  command.
- **`max_age_sec` means what it says.** A `wait=False` caller gets the current snapshot
  without refreshing. Callers that need freshness pass a positive age (the sweep agent
  uses its check interval).
- **One SQLite connection policy** for every file (`core/sqlite_conn.py`, new): WAL,
  `synchronous=NORMAL`, `busy_timeout`, `cache_size`, `mmap_size`, `temp_store=MEMORY`,
  and writes in `BEGIN IMMEDIATE`. It also serves the control-plane SQLite and the
  plan-24 FTS file.
- **Never delete a live database's files.** A rebuild writes a new file under a new
  name (`<app>.<gen>.sqlite`) and atomically flips a small pointer file. Old files are
  removed only when no process holds them (an exclusive lock probe). Corruption is
  handled the same way: rebuild beside it and flip.
- **Fail loudly once, recover always.** Open failures retry with backoff. A failed save
  marks its records dirty again. A one-time stderr warning names the file and the
  reason. A cache dir on NFS/SMB (detected via `statfs`/`/proc/mounts`) warns once and
  falls back to `$TMPDIR` unless `VMN_EXP_CACHE_DIR` is set explicitly.
- **Postgres goes through one pool** (`psycopg_pool.ConnectionPool`, `vmn-exp[server]`
  extra) for the cache, control plane and search. Each pool sets `connect_timeout`,
  `statement_timeout`, `idle_in_transaction_session_timeout`, keepalives, and a health
  check on checkout. Election and LISTEN keep their own dedicated, reconnecting
  connections, and `server.md` documents that they need direct connections (no
  pgbouncer transaction mode).
- **API tokens are HMAC-SHA256** under a server-side key (stored in the control plane).
  The secrets are 256-bit random, so a slow KDF adds nothing. Existing token rows are
  dropped by the migration, so users re-issue their tokens; sessions are unaffected.

## 3. Work units

Each unit runs test-first, in its own worktree, as CLAUDE.md requires. F0 lands first.
F1–F3 depend on F0 only and run in parallel. F4–F6 are independent of F1–F3.

**F0. Benches and a 100k fixture.** Write a synthetic 100k-run local store generator
(`packages/vmn-exp/tests/scale_store.py`), shared with plan 24's F1. Add serial benches
for every row of the §1 table, failing today. Record the measured baselines in this
plan.

**F1. Lean persisted rows and point reads** (`core/index_store.py`,
`index_store_schema.py` → `exp-index-14`, `index_snapshot.py`, `core/refs.py`,
`cli/experiment.py`, `sdk/reader.py`).
- Add the `exp_rows` and side-table tables, indexed on `(app, idx)`, `(app, status)`,
  `(app, parent)`, `(app, root)` and `(app, timestamp)`.
- Add `resolve_one(app, ref)`, and switch `show`/`get_run`/`restore`/`export`/`goto` of
  a dev version to it.
- Build the snapshot from `exp_rows` with no `json.loads` of full records.

Tests:
- `show -v` performs no full load (counting queries);
- the lean tables equal `lean_row` for every record after build/refresh/remove/rewind;
- a warm restart reads no `exp_index` data.

**F2. Incremental revalidation** (`core/index_sweep.py`, `index_listing.py`,
`storage/listing_workers.py`, `storage/cached.py`).
- Persist the listing baselines and set `full_sweep_sec` to 300.
- Fix `refresh_if_stale` so that `max_age_sec=0` with `wait=False` returns the
  snapshot, and pass explicit ages from the sweep agent, watch and early-stopper.

Tests:
- a cold `list` after one changed run re-reads one record;
- a deleted record disappears by the next full sweep at the latest, and immediately
  when its name is gone from the names listing;
- the S3 test double counts one LIST page for a warm cold-start.

**F3. SQLite hardening** (`core/sqlite_conn.py`, new; `core/index_store.py`,
`ui/cache_rebuild.py`, `storage/host_dirs.py`).
- Apply the connection policy and `BEGIN IMMEDIATE` generation bumps
  (`UPDATE … RETURNING gen`). Delta reads use the `(app, seq)` index with
  `key IN (…)` in chunks. Columns are reordered so `seq` precedes `data`.
- Rebuilds and recovery go through the pointer flip; retries, dirty-on-failed-save and
  the NFS guard are added.

Tests:
- two processes saving concurrently never reuse a generation;
- a rebuild under an open reader loses nothing and corrupts nothing (the reader sees
  the old or the new file, then the new);
- a forced `SQLITE_BUSY` on save leaves the records dirty and the next refresh writes
  them;
- an NFS-typed dir warns once and falls back.

**F4. Postgres pool, timeouts, reconnects** (`ui/pg_pool.py`, new; `cache_pg.py`,
`control_plane_pg.py`, `search_pg.py`, `pg_election.py`, `pg_listen.py`,
`migrations/__init__.py`).
- Put one pool per DSN in place of the single connections and the store locks.
- Run migrations once per process, under the advisory lock, not per reconnect.

Tests (they need a Postgres, so they skip like the existing `cache_pg` tests):
- a backend kill mid-request fails that request within the timeout and the next one
  succeeds;
- concurrent requests run concurrently (no global lock);
- migrations run once across three replicas starting together.

**F5. Control-plane queries and security** (`migrations/0006_*.sql`,
`control_plane_pg.py`, `control_plane.py`, `auth/tokens.py`, `audit.py`,
`routes_admin.py`).
- Add a unique index on credential `id` for sessions/tokens/login states, and
  `expires_at` indexes with an expiry sweep (hourly, and on login).
- Switch tokens to HMAC.
- Page the audit log in SQL (`ORDER BY created DESC LIMIT/OFFSET` on a
  `(org_id, created)` index), compute the count in SQL, stream the export, and add
  `server.yml` `audit.retention_days` (default 365).
- Add `org_id` + RLS to `vmn_search_rows`. Each search sync becomes one
  `INSERT … ON CONFLICT` + `DELETE … WHERE NOT IN` per generation, run by the elected
  leader only.
- Push the cache delta key filter into SQL (`key = ANY(%s)`), and add a
  `vmn_tombstones (scope…, seq)` index.

Tests:
- `EXPLAIN` of the credential lookup uses an index;
- 1M expired sessions are gone after one sweep;
- an audit page reads `LIMIT` rows;
- a search row of org A is invisible to org B under RLS.

**F6. Control-plane SQLite and backups** (`ui/control_plane.py`, `cli` `vmn-exp ui
backup <path>`).
- Apply the F3 connection policy. Make `pop` atomic across processes (`DELETE …
  RETURNING`). Add a schema version table with the Postgres migration numbering, and
  use upserts that keep rowids.
- `backup` uses SQLite's online backup API (Postgres: prints the `pg_dump` command).
- Document it in `server.md`.

Tests:
- two processes popping the same login state get it once;
- a backup taken during writes opens and verifies.

**F7. Docs.** `docs/vmn-exp/server.md` (pool settings, timeouts, pgbouncer note, audit
retention, backup), `docs/vmn-exp/experiments.md` (cache location, NFS fallback,
`full_sweep_sec`), CLAUDE.md's storage/index paragraphs.

## 4. Out of scope

- Moving the run store itself into a database (storage stays the source of truth).
- Sharding one app's index across files.
- Replacing JSON-in-TEXT with typed columns beyond the lean-row columns F1 indexes.
