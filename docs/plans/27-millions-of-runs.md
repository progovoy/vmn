# Plan 27: `vmn-exp ui` at millions of runs

> A client's store reached 576,580 runs in one app (2026-10-27). Two costs grow with
> the total number of runs, not with what anyone looks at:
>
> 1. **Every server builds the whole index itself, from the store.**
>    - A cold start reads about 3 objects per run: `metadata.yml`, `run_state.yml`,
>      and the metric index or segments.
>    - Measured: 100k runs in 915 s on master (~109 runs/s, merge T). The client's
>      0.1.23 server did ~263 GetObject/s, about 1.5 h for 576k runs.
>    - That load is CPU-bound in the GIL (95% held, 1.22 cores; 58% of it in botocore's
>      per-request work) and 16% in garbage collection.
>    - A new host pays it again, and so does a version whose derived tables changed.
>      Before plan S, so did every upgrade.
> 2. **Every run lives in the server's memory as Python objects.**
>    - Lean rows, side tables and per-verstr maps are held per run. Measured: 387 MB
>      idle at 100k runs, 3.7 GB while indexing (bench J, before T).
>    - Garbage-collection pauses scale with the object count. That is plan 26's
>      problem, and free-threaded builds make it worse.
>
> At 10M runs, the first cost is ~25 h per host and the second ~40 GB of RAM. No
> interpreter or tuning fixes either. The work below makes both independent of the
> total, so the tool keeps working as a store grows. Users never prune or re-layout to
> stay fast.

## 1. Targets

Measured by M0's harness on Linux: synthetic stores of 1M and 10M runs,
production-shaped (`uiload/s3bench_seed.py` shapes), 200 live writers, 16 clients.

| | Today at 576k | Target at 10M |
|---|---|---|
| New host, store with a published snapshot: first page | ~1 s after listing (T) | ≤ 30 s |
| New host, store with a published snapshot: everything served | ~1.5 h | ≤ 5 min |
| First build ever (no snapshot) | ~109 runs/s | ≥ 1,000 runs/s, serving from the first chunk |
| Upgrade that changes derived tables | re-derive locally, ~5 min at 486k (S) | answers at once; new version published ≤ 30 min |
| Server RSS, steady state | ~4 KB per run (grows with the total) | ≤ 2 GB, independent of the total |
| `experiments` p95, default sort / any metric sort | ~100 ms / ~100 ms at 100k | ≤ 300 ms / ≤ 1 s |
| facets / `experiments-status` p95 | ~100–170 ms | ≤ 500 ms / ≤ 200 ms |
| Idle S3 requests | ∝ live runs (34k/min with 8 long live runs) | ∝ live runs, never ∝ total |
| A record edited behind vmn's back shows up | ≤ 300 s (full sweep) | ≤ 1 h; journaled changes within seconds as today |

Gate (M8): all rows hold at 10M for two consecutive runs.

## 2. Invariants (plan 11 §2) and how this plan keeps them

- **I1, storage is the source of truth.** The snapshot (M1) is a derived file in the
  store, rebuildable from the records, like the index cache is rebuildable today.
  Records are untouched.
- **I2, the cache is disposable.** Deleting every snapshot costs one first build (M5),
  never data.
- **I3/I4, jobs never depend on the server, and the server never writes run data.**
  Jobs don't read or write snapshots. The server writes them under `server/index/`,
  which is already in its read + edits permission set (`docs/vmn-exp/byo-bucket.md`).
  A read-only server consumes snapshots but doesn't publish them; `vmn-exp ui index
  publish` (M1) lets someone with write access publish under their own credentials.
- **I5, journal entries carry no data.** Unchanged. A snapshot is not a journal entry:
  it is produced by our own code from the records, and every part is checksummed. Its
  trust boundary is the same as the records': anyone who can write `server/*` can
  already write `runs/*`.

## 3. Decisions

1. **One index per store, published into the store, consumed by every server.**
   - The leading replica (the existing `leading` election that store upkeep uses)
     writes immutable *parts* plus a manifest:
     - path `server/index/v<DERIVED_VERSION>/<app>/<generation>/`;
     - `part-<n>.sqlite.zst` holds lean rows and their side tables for a contiguous
       range of runs in storage order (newest parts first);
     - `manifest.json` lists each part's range, row count, checksum and listing
       baseline, plus the journal mark the snapshot is consistent with.
   - A new generation rewrites only the parts whose runs changed, and copies the rest
     of the manifest by reference. That is LSM-style: base parts + small delta parts,
     compacted when deltas pass a share of the base.
   - A consumer downloads the parts in parallel, newest first, and serves after the
     first. It then catches up from the journal mark (the existing journal follow,
     `ui/journal_follow.py`). Past the journal's retention (2 days), it reconciles
     with the parallel relist (`core/index_relist.py`).
   - The leader republishes at most every `PUBLISH_EVERY_SEC` (10 min) when something
     changed, and at least daily so a consumer's catch-up stays inside the journal's
     retention.
   - Rejected:
     - Writers publish row summaries next to their records. The writers' code would
       define the index, every reader would still read millions of objects, and I5
       forbids trusting summaries in the journal.
     - A central database every server queries. That is the Postgres tier, and it
       stays available; but the files-only and SQLite tiers need a path that works
       with nothing but a bucket.
2. **The board answers from disk; memory holds only a bounded hot set.**
   - The persisted index (`exp_rows`/`exp_sides`, plan 25) becomes the query engine:
     - lists, filters, sorts, paging and group-by run as SQL (the CLI `list` already
       does, `core/index_list_sql.py`);
     - metric sorts use `exp_metric_values(app, key_id, value, seq)` indexed on
       `(app, key_id, value)`.
   - The query language compiles to SQL where it can. The rest runs as a streaming
     scan over the table in chunks: bounded memory, slower but correct, and reported
     in diag.
   - In memory: live runs (running/stuck/created) plus the newest `HOT_RUNS` (100k).
     The default views (Outer runs, the first pages, status) answer from memory as
     today; history pages come from SQL.
   - Snapshot generations (F00 `SharedMap`) cover the hot set only, so generation cost
     and garbage-collection work are bounded too.
   - Counts, facets and rollups stay incremental (`ui/status_counts.py`, job rollups).
     They are persisted with the rows so a restart doesn't recompute them.
3. **Consistency sweeps are bounded by time, not by the total.**
   - The journal is the primary change source. The rolling consistency sweep
     (`SLICE_BUDGET`) covers the whole store within `SWEEP_WINDOW_SEC` (1 h) at 10M.
     It lists record names per partition with persisted baselines, and stats only what
     a listing says changed.
   - A store without a journal gets the same window, at the listing's cost.
4. **The first build is parallel and lean.**
   - It reads with worker processes (T), at most ~1.5 GETs per finished run:
     - the metric footer and summary in one tail read;
     - `run_state.yml` skipped when the metadata shows the run ended and a later
       state can't change its row.
   - Its products are written straight to parts.
   - The first build of a store happens once; after that every host consumes.
5. **Upgrades publish, then switch.**
   - A server whose `DERIVED_VERSION` is newer than the published snapshot's keeps
     serving the old version's rows, read-only for the changed fields.
   - It re-derives from its records (S), or from a first build when it has none, then
     publishes `v<new>`.
   - Servers of the old version keep using `v<old>` until they upgrade. Old versions
     are deleted by the leader after 7 days unread.
6. **Free-threaded Python is not on this path.** Once memory and GC work no longer
   depend on the total, plan 26 shrinks:
   - F00 is done;
   - F2/F3 (builder-owned values, recycling executor) are kept if M8 still shows
     request-thread retention;
   - F1/F5 are dropped unless M8 needs them.

## 4. Work units

Each unit is test-first (red before green), in its own worktree, ≤ ~300 lines per
file. M1–M4 run in parallel after M0. M5 is independent.

### M0. A 10M harness that fits a laptop
- Seeding 10M S3 objects into moto is not feasible. `uiload/s3bench_fast.py` (merge T)
  gains a generated mode: an object's bytes are a pure function of its key (the seed
  shapes in `s3bench_seed.py`), so a 10M-run store costs no disk.
- An index-only bench builds a 10M-row `exp_rows` file from the same generator, with
  no S3, to measure queries and memory on their own.
- Records `report.json`: every §1 row, RSS, GC pauses, S3 requests by kind.
- **Acceptance:** baselines at 1M and 10M (or the point where today's code falls
  over), committed to §1.1.

### M1. Published snapshot: format, publish, consume
- `core/index_parts.py` (part writer/reader, checksums) and
  `core/index_manifest.py` (manifest, generations, delta compaction): pure, over a
  storage interface.
- `ui/index_publish.py`: the leader's publish loop. Its consume side is
  `core/index_consume.py`, which plugs into the cold path where rows-first loading
  starts today (`core/index_rows_first.py`).
- CLI `vmn-exp ui index publish|status [--store]`.
- **Acceptance:**
  - A new host with a published 1M snapshot serves its first page ≤ 30 s and
    everything ≤ 1 min (bench).
  - Equivalence: the rows equal a first build's, for random change streams.
  - A corrupt or truncated part is rejected (checksum), refetched or rebuilt, never
    served.
  - A snapshot older than the journal's retention reconciles through the relist.

### M2. SQL-served board
- `core/index_query_sql.py` compiles the query language to SQL, with a streaming-scan
  fallback.
- `exp_metric_values` and its index, filed with the row save (`index_lean_store.py`).
- Routes (`experiments`, `experiments-facets`, groups, `scope=`) read SQL past the hot
  set.
- **Acceptance:**
  - Every existing leaderboard/query/groups/facets test passes against the SQL path
    (run both paths in those tests).
  - At 10M (M0's index-only bench): §1 latencies.

### M3. Bounded hot set
- `core/index_hot.py`: which runs stay in memory (live + newest `HOT_RUNS`), with
  moves in and out by deltas. Snapshot generations cover it only.
- **Acceptance:** RSS ≤ 2 GB at 10M, flat from 1M to 10M (bench). Hot-set boards are
  unchanged.

### M4. Sweeps bounded by time
- `index_sweep.py`: the slice budget is derived from `SWEEP_WINDOW_SEC` and the total,
  with partitioned listing baselines.
- **Acceptance:**
  - An out-of-band edit at 10M shows up ≤ 1 h.
  - Idle S3 requests are flat from 1M to 10M with the same live writers.

### M5. Lean, parallel first build
- Merge-C findings first: the logging fix (done), metric reads, listings, GC during
  the bulk load.
- Then the one-tail-read metric footer and skipped `run_state.yml` reads (decision 4).
  Products go straight into M1 parts.
- **Acceptance:** ≥ 1,000 runs/s sustained on an 8-core host (serial bench at 1M),
  ≤ 1.5 GETs per finished run.

### M6. Upgrades publish, then switch (decision 5; *after* M1)
- **Acceptance:** a version bump at 1M answers at once on the old rows, publishes
  `v<new>` ≤ 30 min, and an old-version server beside it is unaffected.

### M7. Postgres tier parity (*after* M2)
- The same SQL path on Postgres (`ui/pg_pool.py`). N replicas consume the published
  snapshot instead of each building.
- **Acceptance:** M2's tests pass on Postgres; two replicas at 1M share one first
  build.

### M8. Gate
- Run M0 twice at 10M. If §1 holds:
  - update `docs/vmn-exp/server.md` (sizing, the snapshot, `index publish`), CLAUDE.md
    and `ui/gil_hint.py` (no size-based advice);
  - re-scope plan 26 (decision 6).
- If not: record the numbers here and list what's left.

## 5. Risks

- **The SQL path diverges from the in-memory one.** Two engines for one query language.
  M2 runs every board test through both, and the hot set and SQL must answer
  identically at the boundary (a test pages across it).
- **Snapshot size.** Lean rows plus side tables persist at ~14.5 KB per run today
  (merge I): 145 GB at 10M is too much to download in 5 min.
  - Parts carry lean rows plus the sides the boards read (metric summaries, notes),
    compressed. Target ≤ 1.5 KB per run, 15 GB at 10M, ~2 min on a 1 Gbit/s link with
    parallel GETs.
  - Outputs, features and intents stay per-part, fetched on first use.
  - M0 measures the real size; if it misses, parts shrink before M1 merges.
- **A stale leader keeps publishing.** Every manifest carries the publisher's journal
  mark, and a consumer refuses a manifest older than the one it has. Two leaders after
  a split brain write different generations; the newest journal mark wins.
- **Metric-sort cardinality.** Thousands of distinct metric keys make
  `exp_metric_values` large. Only metrics on lean rows are filed; `sys_*` metrics stay
  in their side table.
- **First build still costs hours at 10M** (≥ 1,000 runs/s ⇒ ≤ 3 h). It runs once per
  store, serving from its first chunk, and resumes after a crash (T).

## 6. Out of scope

- Metric series storage (plan 12): already per-run, range-read, and independent of the
  total.
- Run detail: per-run reads, already bounded (merge F/O, the request lane `0d26d12d`).
- A native row store (plan 16), unless M2 misses its latency targets.
- Sharding one app across servers. One server can serve 10M runs once memory is
  bounded; scaling out is replicas reading the same snapshot (M7).
