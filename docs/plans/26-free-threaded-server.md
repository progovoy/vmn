# Plan 26: `vmn-exp ui` on free-threaded Python at 500k runs

> A client served one app of 486k runs from `vmn-exp ui` 0.1.21. On the GIL build
> (3.10) the server reached 57.7 GiB after 4.3 h. On 3.14t it was 28.3 GiB at
> 161 s, 192.7 GiB at 75 min, and 210 → 229 → 251 GiB in later periodic dumps,
> while the row count stayed at 486,831 (generation 271). Each jump came with a
> process-wide stall of about 2 minutes (dump uptime moved 136 s and 144 s across
> 30 s intervals; event-loop lag reached 114 s).
>
> Part of that is fixed on master (2026-10-27):
> - the snapshot↔view cycle frozen per generation leaked every generation (plan
>   merge A);
> - `DeltaLog` could form a cycle that a request walked forever under its lock,
>   growing `chain` without bound (merge Q);
> - lean rows are about half their size (merge I).
>
> The rest is the free-threaded runtime itself, measured on macOS arm64 with 3.14.10
> vs 3.14.10t (merge R, scripts were in `/tmp/gcbench`; Linux and 3.15t unmeasured):
> - **Allocator retention.** A block freed by a thread other than the one that
>   allocated it can only be reused by its owner, while the owner lives.
>   - Rebuilding 300k rows freed that way: 940 → 1849 MB on 3.14t, 809 → 810 MB on
>     3.14.
>   - With 16–40 concurrent requests, RSS settled at 3–5× the live table on 3.14t
>     and 1.5–2× on 3.14.
>   - Memory held by a thread that exits is reclaimed.
>   - `PYTHON_GIL=1` on 3.14t keeps the retention (it's mimalloc, not the GIL), and
>     no `MIMALLOC_*` purge/reclaim option tried changed it.
> - **Stop-the-world collections that grow with the heap.**
>   - The free-threaded GC is non-generational: a collection scans every tracked
>     object.
>   - It triggers when objects grew 25% over the unfrozen survivors *and* RSS grew
>     10% since the last one. So retention itself triggers collections, and the
>     ~10% RSS steps in the client's dumps match.
>   - A full collection of 8M tracked objects: 0.47–0.66 s on 3.14t; the same live
>     objects on a heap with retained free memory scan 8× slower (17 → 135 ms).
>   - `gc.freeze()` skips frozen objects but still walks them (~18 ms/GB).
>
> Today `ui/gil_hint.py` stops recommending 3.14t from 200k runs and warns once on a
> free-threaded build. This plan makes the free-threaded build the better one at
> 500k runs, then flips that hint back.

## 1. Targets

Measured by F0's harness on Linux (the client's OS), 3.14 vs 3.14t vs 3.15t. The
workload: 500k runs (production-shaped, `uiload/s3bench.py` app `fastglobalmacro`),
200 live writers, 16 concurrent browser-like clients, 4 h.

| | GIL build today | Target on 3.14t/3.15t |
|---|---|---|
| RSS after 4 h / after warm-up | F0 measures | ≤ 1.3× (no growth trend) |
| RSS vs the GIL build at the same point | 1× | ≤ 1.5× |
| GC pause p99 / max | F0 measures | ≤ 150 ms / ≤ 500 ms |
| Event-loop lag p99 | F0 measures | ≤ 100 ms |
| `experiments` / `experiments-status` p95 | F0 measures | ≤ GIL build ÷ 3 |
| Tracked GC objects per indexed run | F0 measures | ≤ 8 |

The gate (F7): all six hold on 3.14t or 3.15t for two consecutive runs.

## 2. What we know vs what we assume

| Claim | Status |
|---|---|
| Cross-thread frees are only reusable by the owning thread | measured (R), macOS |
| A thread's exit releases its heap | measured (R) |
| GC trigger = +25% objects and +10% RSS | read from CPython `gc_should_collect` (3.14) |
| Collection pause ∝ tracked objects × heap sparsity | measured (R), one heap shape |
| Long-lived cache values are built on request threads | read from code: `_base` single-flight builds on the first requesting thread (`ui/leaderboard_cache.py`), as do `memo.LRU.per_snapshot` values, the lineage index (`ui/routes_lineage.py`), facets, search, similar |
| Index snapshots are built on the refresher thread (`vmn-ui-refresh`, one per watched index) and per-call load pools | read from code (`ui/refresher.py`, `core/index.py` `_REMOTE_WORKERS` = 32 per call) |
| ~100 long-lived threads | read from code (table below); the client's dumps showed 20–49 alive |
| 3.15t behaves like 3.14t | **assumed** — F0 measures it |
| Linux behaves like macOS | **assumed** — F0 measures it |

Threads the server keeps (from `grep` on master, 2026-10-27):

| Pool | Size | Lifetime | Allocates long-lived data? |
|---|---|---|---|
| anyio default worker pool (sync routes + `slow_read`) | ≤ 40 (+24 for slow reads) | idle 10 s, then pruned (`WorkerThread.MAX_IDLE_TIME`) | yes: cache values built inside requests |
| `vmn-ui-detail` (`readers/detail_reads.py`) | 32 | process | no (per-request reads) |
| `vmn-ui-series` (`routes_series.py`) | 8 | process | segment cache entries |
| `vmn-ui-refresh`, `vmn-ui-journal`, `vmn-ui-warm`, upkeep, tidy, diag, pg-listen, similar-sync | 1 each per index/workspace | process | yes: snapshots, bases, corpora |
| per-call pools: index load (32), subtree (32), journal (16), relist (8), listing (16), fan-out (≤ 160 shared) | per call | exit after the call | yes: decoded records handed to the caller |

## 3. Decisions

0. **Generations share memory instead of copying it.**
   - Every snapshot copies its per-run maps in full (`core/index_snapshot.py:292-297`,
     `RowCache.snapshot`): `run_states`, `edges`, `create_notes`,
     `run_state_observed_at`, `_by_verstr`, every side table, and a new rows tuple.
   - One copy of a 486k-entry dict is 10.6 ms and 21 MB (measured, 3.9, M-series).
     A generation is therefore ~100–170 MB and 60–80 ms of copies, almost all
     identical to the last one, at ~1 generation/s with live runs.
   - That is the allocation volume behind the retention on free-threaded builds,
     and the RSS growth that triggers their collections. On the GIL build it is
     ~7% of a core held under the GIL.
   - Instead, each map becomes a `SharedMap` (`core/shared_map.py`): a frozen base
     dict shared by generations plus a small overlay of changed or removed keys.
     Lookup checks the overlay, then the base. A new generation copies only the
     overlay. Once the overlay passes `FOLD_FRACTION` (a few %) of the base, it is
     folded into a new base, amortized O(1) per change.
   - The rows tuple gets the same treatment: an unchanged prefix is shared, a
     chunked tuple-of-tuples.
   - Rejected:
     - persistent HAMT maps (`immutables`): a C dependency with unknown
       free-threaded wheels, the orjson problem again, and slower lookups;
     - mutable shared maps with per-entry versions: readers of an old generation
       would see new values.
1. **Long-lived data is allocated on long-lived owner threads, never on request
   threads.**
   - A request that needs a cache value (board base, view, facets, lineage index,
     search index, rollups) submits the build to its index's builder thread and
     waits up to the existing bound (`BASE_WAIT_SEC`, merge Q), then serves the
     previous value.
   - Request threads allocate only the response.
   - The builder is the existing `vmn-ui-warm` worker (`ui/latest_worker.py`),
     generalized to keyed builds with single-flight. It then owns the pages of
     everything it built, and the frees that come back to it get reused, because it
     keeps allocating.
2. **Request threads recycle.** Sync routes run on our own executor, not anyio's
   default pool. A worker retires after `RECYCLE_TASKS` tasks or `RECYCLE_SEC` of
   life, whichever comes first, so the per-thread heaps of transient response data
   are released.
   - Retirement happens between tasks, so no request is affected.
   - Thread creation is ~100 µs; at 1 retirement per 500 tasks the overhead is
     noise.
   - The same executor replaces `vmn-ui-detail`/`vmn-ui-series`, as named sub-pools
     with their own bounds, since `tests/test_pool_names.py` keeps names.
3. **Per-call pools hand results to a long-lived thread before they become
   long-lived.**
   - The index's load pools (`core/index.py` `_REMOTE_WORKERS`, `index_workers.py`)
     return raw bytes/JSON. Decoding into the records a snapshot keeps happens on
     the refresher thread, which owns the snapshot.
   - Where decoding is the expensive part, it stays parallel, but its products are
     re-materialized (interned/packed, merge I's `index_intern.py`/`metric_pack.py`)
     on the owner thread.
   - F0 measures whether this matters: abandoned heaps of exited threads may already
     be reclaimed well.
4. **The bulk data stops being GC-tracked.**
   - CPython untracks tuples whose items are all untracked, and dicts of atomics in
     the default build. F1 verifies which of these holds on 3.14t/3.15t.
   - Lean rows, side tables and per-verstr maps move to untracked containers: rows
     as tuples keyed by a shared schema (a `RowSchema` → index map), per-verstr maps
     as one dict of tuples.
   - The collector then walks a few objects per run instead of dozens. Target: ≤ 8
     tracked objects per run (§1).
   - Row consumers keep reading rows through a `Mapping` view, so callers don't
     change, and F1 keeps it as a thin adapter.
5. **GC is scheduled, not left to the RSS trigger, on free-threaded builds only.**
   - A `GcPolicy` (`core/gc_policy.py`) chosen by `sys._is_gil_enabled()`: on a GIL
     build nothing changes.
   - On a free-threaded build: `gc.freeze()` after each published generation, which
     is safe once decision 4 leaves no cycles in the bulk data and A's weakref
     views hold.
   - Raise `gc.set_threshold` so allocation churn alone doesn't collect.
   - A collection runs on the builder thread right after a publish, when the
     unfrozen heap is smallest, at most every `GC_MIN_INTERVAL_SEC`.
   - The diag `gc` section (merge R) proves each step.
6. **No orjson dependency** (done, `be1fc217`). JSON rendering is measured in F0. If
   it's a top-3 allocator on 3.14t, F5 renders large pages in chunks instead of one
   string.
7. **Rejected:**
   - Several uvicorn worker processes: N× the snapshot memory.
   - Subinterpreters (3.14 `InterpreterPoolExecutor`): the snapshot can't be shared
     without serialization.
   - A native (Rust) row store: plan 16, not needed if decision 4 hits its target.
   - `MIMALLOC_*` env tuning: measured as no effect (R).

## 4. Work units

Each unit is test-first (red before green), in its own worktree, ≤ ~300 lines per
file. Units run in parallel unless marked *after*.

### F0. Linux harness and baselines (blocks F7; F1–F6 can start on R's macOS data)
- `packages/vmn-exp/tests/uiload/ft_bench.py`: Docker images of python 3.14,
  3.14t and 3.15t on Linux.
  - Seeds the §1 workload once with `s3bench_seed.py` (moto; minio if moto can't
    hold 500k).
  - Runs `vmn-exp ui` from the checkout with live writers (`uiload` live mode) and
    16 probe clients (`probe_routes.py`).
  - Samples every 30 s: diag dumps (`vmn-exp ui diag --url`), RSS, the `gc` section,
    event-loop lag, route p50/p95, and `sys.getallocatedblocks()` vs RSS.
  - Writes `report.json` plus a markdown table.
- A tracked-objects-per-run probe: `len(gc.get_objects())` / rows after warm-up, as
  a diag field (cheap enough in a dump, not per request).
- Allocation attribution: `tracemalloc` snapshots on 3.14t, if it works there, else
  `sys.getallocatedblocks()` deltas around builds, per thread name.
- **Acceptance:** baselines for all §1 rows on 3.14, 3.14t and 3.15t, committed
  to §1.1 of this plan. That includes which threads own the retained memory, from
  per-thread RSS deltas with `PYTHON_GIL=1` vs `0` and thread-recycling on/off
  toggles.
- Tests: the report schema and the sampler (fake server); the harness itself is
  `@pytest.mark.serial` and opt-in (`VMN_FT_BENCH=1`).

### F00. Shared generations (decision 0; first, helps both builds)
- `core/shared_map.py`: `SharedMap(base, overlay, removed)`, a read-only
  `Mapping` (get, `in`, len, iteration in the base's order plus overlay
  additions).
  - `derive(changes, removed)` returns the next generation, copying only the
    overlay.
  - `FOLD_FRACTION` folds the overlay into a new base.
  - Pure; tests first: equivalence with a dict under random change streams,
    per-derive cost O(overlay) (count dict copies by size), fold amortization.
- `RowCache.snapshot` passes `SharedMap`s instead of `dict(...)` copies. Fix the
  consumers that need a real dict: `isinstance(..., dict)`, `json.dumps` of a
  whole map, in-place mutation. Grep before changing.
- Rows: share the unchanged prefix (a chunked rows container with
  `__getitem__`/`__len__`/iteration). Only if F0 shows the 0.9 ms/3.9 MB tuple
  matters; else keep the tuple.
- **Acceptance:**
  - A test drives 100 generations of 50k runs with 50 changes each. Total bytes
    allocated by snapshot construction (tracemalloc) are ≤ 2% of today's.
  - Every index/leaderboard/status/settled test is unchanged.
  - In F0, RSS slope and GC collections per hour drop on 3.14t, and refresher CPU
    per generation drops on 3.14.

### F1. Untracked rows (decision 4)
- Probe test first: on the running interpreter, assert which containers
  `gc.is_tracked()` reports false after a collection (tuple of str/float, dict of
  atomics). On 3.9/3.14 now and 3.14t in F0's image. The design depends on the
  answer.
- `core/row_schema.py`: `RowSchema` (field → slot, shared, interned) and `Row`, a
  `Mapping` over a tuple. Lean rows decode into `Row`
  (`core/index_lean_store.py`, `index_views.lean_row`); `metrics`/`params`/`tags`
  become tuples of `(key, value)` pairs behind `Mapping` views, built once.
- Consumers that mutate row dicts: find them (`grep "row\[" ... "] ="`) and convert
  to copies. Most already copy, per the plan-25 rule.
- **Acceptance:** tracked objects per run ≤ 8 on 3.14 (unit test with 10k realistic
  rows from `index_footprint.py`, merge I). Every leaderboard/facets/query/columns
  test unchanged. `test_index_run_footprint.py` budget lowered by what this saves
  (a new number, red first).

### F2. Builder-owned cache values (decision 1)
- `ui/builder.py`: per-index `Builder` on the `vmn-ui-warm` thread.
  - `build(key, fn, wait_sec)` runs single-flight. On timeout it returns the
    previous value for the key, else waits; this replaces merge Q's `stale=`
    plumbing in `memo.LRU`.
  - Coalescing keeps only the newest pending snapshot per key (`latest_worker.py`).
- Route `leaderboard_cache._base`, `memo.per_snapshot` values that outlive a
  request, `routes_lineage` index builds, facets, `search_index`, `job_rollup_cache`
  and `status_counts` through it.
- **Acceptance:**
  - A test asserts every long-lived value is created on the builder thread: record
    `threading.current_thread().name` at construction via a hook in each
    constructor, or a `sys.setprofile`-free check through a builder context var.
  - Answers are unchanged.
  - F0 shows retention no longer scales with request-thread count.

### F3. Recycling request executor (decision 2)
- `ui/executor.py`: `RecyclingExecutor(name, max_workers, recycle_tasks,
  recycle_sec, idle_sec)`.
  - Workers retire between tasks; the executor is bounded and named, with stats in
    diag `pools`.
- `ui/offload.py`: generalizes `slow_read` so every sync route runs as an async
  wrapper on the executor's named sub-pools (`default`, `slow`, `detail`,
  `series`), keeping the 499 client-gone behaviour.
  - Replace `ThreadPoolExecutor`s in `detail_reads.py` and `routes_series.py`.
- **Acceptance:**
  - Unit tests: a worker retires after N tasks, never mid-task, and the pool never
    exceeds its bound.
  - Concurrent load keeps the request bound; `test_pool_names.py` still passes.
  - F0: RSS with recycling on vs off.

### F4. Owner-thread materialization (decision 3; *after* F0 says it matters)
- The index load pools return raw payloads; the refresher thread decodes and packs
  them (`core/index.py` `_load_records`, `index_rows_first.py`).
- Keep the parallel S3 fetches; move only the object creation.
- **Acceptance:**
  - Cold-load time within 10% of today on 3.14 (serial bench).
  - On 3.14t, RSS after cold load ≤ 1.2× live bytes.

### F5. Free-threaded GC policy (decision 5; *after* F1, F2)
- **Done ahead of F1/F2 (2026-10-30, a 705k-run ui on 3.15t paused 4-9 s per
  automatic collection):** `core/gc_policy.py` `GcPolicy`, from
  `FREE_THREADED_LARGE_RECORDS` (= the gil_hint bound) on a free-threaded build:
  automatic collection off (`gc_pause.set_automatic`, which a running
  `gc_paused` ends into), then after a refresher publish collect + freeze at
  most every `GC_MIN_INTERVAL_SEC` (300). Collect runs *before* freeze, so no
  garbage cycle is frozen. No threshold change (collection is off). Diag
  `gc.policy`. Tests: `test_ft_gc_policy.py`, and
  `test_ft_gc_policy_generations.py` (no cyclic garbage per generation;
  50 generations frozen after each publish are freed; passes on 3.14.10t).
  Still open: the acceptance run in F0.
- `core/gc_policy.py`: `policy_for(gil_enabled)` returns `DefaultPolicy` (no-op) or
  `FreeThreadedPolicy`, which does three things:
  - `after_publish(snapshot)`: freeze, then collect if due;
  - thresholds at start;
  - `GC_MIN_INTERVAL_SEC`.
- Wired into the refresher's publish and the builder.
- Test with injected `gil_enabled` and a fake `gc` module: thresholds, ordering,
  rate limit.
- **Acceptance (F0):** GC pause p99 ≤ 150 ms; no growth of `gc.get_freeze_count()`
  beyond live data. Check: frozen-count ≈ tracked objects of the live generation,
  verified by a test driving 50 generations.

### F6. Response allocations (decision 6; *after* F0 ranks them)
- Only if F0 ranks JSON rendering, gzip or row copies in the top 3 allocators on
  3.14t:
  - chunked rendering (`ui/responses.py` `json_response` streaming above 1 MB);
  - a byte cache per ETag for the hottest pages.
- **Acceptance:** allocation per `experiments` page ↓ 2× in F0.

### F7. Gate and flip (*after* F0–F6)
- Run F0 twice. If §1 holds:
  - `ui/gil_hint.py` recommends 3.14t/3.15t again at every size (drop the 200k
    cap and the free-threaded warning, red tests first);
  - update `docs/vmn-exp/ui.md` (the measured table) and CLAUDE.md.
- If not: keep the hint, record the numbers here, and list what's left.

## 5. Risks

- **Decision 4 touches every row consumer.** The `Mapping` adapter keeps reads
  working, but writers that mutate rows in place will raise. F1 starts with that
  grep and fixes them first.
- **A wrong freeze leaks.** F5 freezes per generation again. That is safe only if
  no generation object takes part in a cycle. A's weakref views removed the known
  one. F5's 50-generation test must show old generations freed with `gc.freeze()`
  on, or F5 doesn't merge.
- **Builder serialization.** One builder per index serializes builds. A slow build
  delays others for the same index. The bounded wait plus previous-value fallback
  (merge Q's semantics) keeps requests answering. F2's test covers a slow build
  beside a fast one.
- **3.15t differs.** F0 may show 3.15t already fixes retention or changes the GC
  trigger. Then F3/F4 shrink or drop, by measurement.

## 6. Out of scope

- The SDK and `vmn-exp run` processes: short-lived, small heaps.
- Postgres-backed servers: same code paths, measured only if F0's SQLite numbers pass.
- A native row store (plan 16).
