# Plan 28: measurements (2026-10-28)

Numbers for appendix A row 6 (GC pauses on 3.15.2t) and the B0 follow-up
"measure over HTTP on free-threaded Python". One laptop (Apple silicon, 16
cores: 12 performance + 4 efficiency). The first session shared it with other
agents' test runs (load average 20-520); the second (marked *low load*) ran
alone, each timed run started only once the 1-minute load average was below
12. Every number carries the load it ran under: the before/after 1-minute
load average for the low-load runs.

Interpreters: CPython 3.15.2t and 3.15.1t (free-threaded, uv builds, GIL off,
the same package versions in both venvs, no libyaml in either, both on the
same master checkout), and the repo venv's 3.12.13 (GIL) for reference.

## 1. GC pauses: `packages/vmn-exp/tests/gc_pause_bench.py`

*cold* = the index loads a `scale_store` store as a remote one while a thread
pages the board of each published snapshot, then the board is warmed; *warm* =
a restart on the index file the cold case left. Pauses are timed by the diag
dump's `gc.callbacks` hook. "collect" = a `gc.collect()` after the load, and
again after `freeze_long_lived()`.

### 100k runs, one pass per interpreter (load average 70 → 336 → 80)

| | 3.15.2t | 3.15.1t | 3.12 |
|---|---|---|---|
| cold: load | 316 s | 457 s | 269 s |
| cold: collections, max pause | 74, **2.12 s** | 74, **2.74 s** | 8,796, 0.69 s |
| cold: total paused, pauses > 500 ms | 22.5 s, 18 | 35.5 s, 25 | 14.6 s, 1 |
| cold: objects after load (frozen) | 5.68M | 5.63M | 3.97M |
| cold: collect after load / after freeze | 1.13 s / 1.10-1.38 s | 0.56-0.62 s / 0.21-0.35 s | 6 ms / 0 |
| steady state (60 s of board pages + refreshes) | 520 requests, 0 collections | 2,300 requests, 0 collections | 1,060 requests, 15,115 collections, max 130 ms |
| warm: load | 197 s | 7.8 s | 18 s |
| warm: collections, max pause | 1, 10.7 s | 1, 0.15 s | 330, 2.61 s |
| warm: objects (frozen) | 2.56M | 2.56M | 2.04M |
| warm: collect after freeze | 0.11-0.47 s | 19 ms | 0 |

The 3.15.2t pass ran at the peak of the load (~336), so its warm row (a
197 s restart, one 10.7 s collection) is not comparable; the paired runs below
show no warm difference.

### 30k runs, ABAB under load (3.15.2t, 3.15.1t, 3.15.2t, 3.15.1t; load average 85 → 37)

| | 3.15.2t (1) | 3.15.1t (1) | 3.15.2t (2) | 3.15.1t (2) |
|---|---|---|---|---|
| cold: load | 55.5 s | 27.3 s | 45.8 s | 26.3 s |
| cold: collections | 45 | 45 | 45 | 45 |
| cold: max pause | **292 ms** | **84 ms** | **297 ms** | **83 ms** |
| cold: total paused | 3.42 s | 1.54 s | 2.69 s | 1.50 s |
| cold: collect after load | 57-77 ms | 41-44 ms | 110-148 ms | 41 ms |
| cold: collect after freeze | 47-51 ms | 45-50 ms | 74-98 ms | 42 ms |
| steady state, 10 s | 360 requests | 1,880 | 1,100 | 2,480 |
| warm: load, max pause | 3.0 s, 58 ms | 2.2 s, 42 ms | 2.2 s, 43 ms | 7.8 s, 164 ms |

The low-load runs below do not reproduce this gap: it came with the load
(see "What the numbers say").

### 30k runs, ABAB at low load, per `GC_BENCH_POLICY`

Order per policy: 3.15.2t, 3.15.1t, 3.15.2t, 3.15.1t; policies run baseline,
callback, threshold, index; `--serve-sec 10`. *baseline* = no policy;
*callback* = `gc.freeze()` from a `gc.callbacks` hook after every collection
over 50 ms; *threshold* = `gc.set_threshold(100_000, 10, 10)`; *index* =
`freeze_long_lived()` each time a published snapshot grew 25 %. Cells: cold
load s / collections / max pause ms / total paused s; then `gc.collect()`
after the load (ms, two calls) and 10 s of steady-state board requests.

| policy, build (load before → after) | cold: load, collections, max, total | collect after load | steady state, 10 s |
|---|---|---|---|
| baseline, 3.15.2t (7.7 → 13.4) | 25.0 s, 43, **76 ms**, 1.31 s | 39 / 39 ms | 2,640 requests |
| baseline, 3.15.1t (11.2 → 12.5) | 25.0 s, 43, **75 ms**, 1.32 s | 41 / 41 ms | 2,720 |
| baseline, 3.15.2t (9.8 → 12.8) | 26.0 s, 44, **68 ms**, 1.37 s | 40 / 41 ms | 2,500 |
| baseline, 3.15.1t (11.2 → 13.3) | 25.1 s, 42, **68 ms**, 1.31 s | 41 / 39 ms | 2,740 |
| callback, 3.15.2t (9.9 → 10.1) | 24.2 s, 43, 69 ms, 1.25 s | 38 / 40 ms | 2,720 |
| callback, 3.15.1t (10.1 → 10.1) | 25.2 s, 43, 74 ms, 1.30 s | 41 / 40 ms | 2,700 |
| callback, 3.15.2t (10.1 → 12.2) | 25.7 s, 44, 76 ms, 1.36 s | 40 / 40 ms | 2,700 |
| callback, 3.15.1t (10.5 → 9.9) | 25.8 s, 43, 72 ms, 1.33 s | 43 / 43 ms | 2,720 |
| threshold, 3.15.2t (9.9 → 13.7) | 25.5 s, 41, 75 ms, 1.32 s | 41 / 39 ms | 2,680 |
| threshold, 3.15.1t (11.2 → 11.4) | 24.7 s, 41, 76 ms, 1.33 s | 44 / 44 ms | 2,680 |
| threshold, 3.15.2t (11.4 → 11.4) | 25.3 s, 40, 78 ms, 1.32 s | 41 / 41 ms | 2,480 |
| threshold, 3.15.1t (11.4 → 12.6) | 26.6 s, 42, 77 ms, 1.34 s | 36 / 36 ms | 2,700 |
| index, 3.15.2t (11.3 → 17.4) | 26.7 s, 55, 77 ms, 1.48 s | 41 / 38 ms | 2,460 |
| index, 3.15.1t (10.0 → 11.2) | 25.5 s, 55, 77 ms, 1.48 s | 42 / 41 ms | 2,660 |
| index, 3.15.2t (11.2 → 13.2) | 25.8 s, 54, 74 ms, 1.48 s | 44 / 45 ms | 2,700 |
| index, 3.15.1t (11.7 → 10.0) | 24.8 s, 55, 76 ms, 1.48 s | 43 / 44 ms | 2,720 |

Both builds, every policy: 1.74-1.84M objects after the cold load (all but
~17k frozen by the warm-up), collect after `freeze_long_lived()` 33-46 ms.
Warm restarts: 1.9-2.1 s, one collection of 37-42 ms (*index*: two, 43-46 ms
max), on both builds.

### Stop-the-world wait (`gc.collect()` on a near-empty heap; low load)

On the free-threaded build the `gc.callbacks` "start" hook runs before
`gc_collect_internal()` calls `_PyEval_StopTheWorld()`, and the "stop" hook's
`duration` is timed around that call
([`Python/gc_free_threading.c` at v3.15.2](https://github.com/python/cpython/blob/v3.15.2/Python/gc_free_threading.c)),
so both the bench's pauses and CPython's own `duration` include the wait for
every attached thread to reach a safe point. To time that wait apart, a main
thread collected a heap of almost nothing 60 times while K threads ran Python
code that keeps nothing alive (*spin*: integer adds; *alloc*: build and drop
small dicts). Median / p90 / max ms, two runs per build (load 9-12):

| busy threads | spin, 3.15.2t | spin, 3.15.1t | alloc, 3.15.2t | alloc, 3.15.1t |
|---|---|---|---|---|
| 0 | 1.2-1.9 / 2.3 / 5-6 | 0.7-0.9 / 1.9-2.4 / 3 | 1.1-1.8 / 2.4-2.7 / 4-8 | 1.2-1.9 / 2.8-3.0 / 3-4 |
| 8 | 2.0-2.1 / 2.3 / 2.4-2.5 | 1.9-2.0 / 2.1-2.2 / 2.2-4.4 | 2.0 / 2.2-2.3 / 2.4-2.5 | 1.9-2.1 / 2.2-2.3 / 2.9-4.6 |
| 15 | 2.1-2.2 / 2.3-2.6 / 3-8 | 2.0-2.2 / 2.2-2.4 / 3 | 2.2 / 2.5-3.1 / 3.7-3.8 | 2.0-2.2 / 2.3-2.6 / 2.6-10 |
| 32 | 4.4-5.3 / 12-20 / 15-61 | 4.6-5.3 / 13-14 / 32-86 | 3.9 / 8-12 / 22-35 | 4.6-5.3 / 14-16 / 75-166 |
| 64 | 13-14 / 44-60 / 81-133 | 9-16 / 56-77 / 127-237 | 14-19 / 43-67 / 163-221 | 10-18 / 41-51 / 96-198 |

While the runnable threads fit the cores the wait is ~2 ms; past the 16 cores
a stop waits for threads the OS has descheduled, median 4-19 ms with tails of
60-240 ms, the same on both builds. Machine load from other processes
oversubscribes the cores the same way.

### The collector alone (`gc.collect()` on a built heap, min of 3; load ~25)

A list of N `{"a": [i], "b": (i, "x")}` items, collection off while building:

| N | 3.15.2t | 3.15.1t | 3.12 |
|---|---|---|---|
| 1M | 34 ms (frozen 15 ms) | 34 ms (frozen 15 ms) | 365 ms (frozen 0) |
| 2M | 68 ms (frozen 29 ms) | 68 ms (frozen 30 ms) | 801 ms (frozen 0) |
| 4M | 135 ms (frozen 58 ms) | 136 ms (frozen 59 ms) | 1,118 ms (frozen 0) |

The same heap of 2M built by 1, 8 or 32 threads, collected with or without 32
idle live threads: 67-110 ms on both 3.15 builds, no version difference.

### CPython 3.15.2's GC and free-threading changes

From [`Misc/NEWS.d/3.15.2.rst`](https://github.com/python/cpython/blob/v3.15.2/Misc/NEWS.d/3.15.2.rst)
and a diff of `Python/gc_free_threading.c` between v3.15.1 and v3.15.2:

- [gh-159111](https://github.com/python/cpython/issues/159111): the vendored
  mimalloc went from 2.1.2 to 2.5.2 (3.15 backport
  [#160178](https://github.com/python/cpython/pull/160178), merged
  2026-10-22). It replaces the per-interpreter abandoned pool with mimalloc
  sub-processes, so the GC now visits dead threads' abandoned segments through
  `mi_abandoned_visit_blocks(subproc, ...)`; abandoned segments are reclaimed
  when a thread frees into them. The issue carries no benchmark results.
  vmn's cold load churns threads (a new 32-thread pool per 500-record chunk,
  `core/index.py:_refresh_all`), so this was the prime suspect, but at low
  load the cold pauses, collect times and load times are equal on both builds.
- The GC itself only gained `cleanup_worklist()` calls on the early-abort
  path (the "reference leaks when free-threaded garbage collection aborts
  early because of an allocation error" entry); the collection path is
  otherwise unchanged.

### What the numbers say

1. **3.15.2t does not pause longer than 3.15.1t.** At low load, ABAB at 30k,
   the baseline cold load takes 25.0-26.0 s on both builds, with 42-44
   collections, max pause 68-76 ms against 68-75 ms, 1.31-1.37 s paused in all
   against 1.31-1.32 s, and the same steady-state throughput (2,500-2,740
   board requests in 10 s). The ~3.5x gap of the first session (292-297 ms
   against 83-84 ms, cold loads 46-55 s against 26-27 s) came with load
   averages of 37-85 and does not reproduce: it was the load, not the build.
   The 100k single passes (load 70-336) are not comparable either.
2. **A pause includes the stop-the-world wait, and the wait is what load
   inflates.** The hooks time from before `_PyEval_StopTheWorld()` to after
   `_PyEval_StartTheWorld()`. With no more runnable threads than cores that
   wait is ~2 ms; oversubscribed, it is tens of ms at the median and up to
   ~240 ms at the tail, on either build. vmn's cold load runs 32 load threads
   plus the request thread on 16 cores, so even at low load its longest
   in-load pause (68-78 ms) sits above a quiescent collection of the same heap
   (36-45 ms); with the machine at load 40-500 every collection waits for
   descheduled threads, which is how the first session saw 0.3 s at 30k and
   2-2.7 s at 100k.
3. **The collector itself costs the same on both builds** (~34 ms per million
   items, single- or multi-threaded heap, with or without idle threads), and
   ~40 ms for the 1.8M objects a cold 30k load leaves.
4. **None of the bench's policies helps on free-threaded builds.** *callback*
   and *index* freeze objects, but a free-threaded collection still walks
   every frozen object (point 5); *index* adds ~12 collections of its own
   (55 against 43, 1.48 s paused against 1.31 s). *threshold* changes nothing
   (40-42 collections): `gc_should_collect()` also requires the young count
   to exceed a quarter of `long_lived_total`, so past ~400k live objects the
   heap's growth, not the threshold, sets when a collection runs.
5. **On free-threaded builds `gc.freeze()` does not shorten a collection.**
   A full collection still walks every frozen object: 58 ms per 4M frozen
   items (micro), 33-46 ms after `freeze_long_lived()` at 30k cold, 0.2-1.4 s
   at 100k cold (under load), against exactly 0 on 3.12.
   `freeze_long_lived()` (`core/gc_pause.py`, called by
   `LeaderboardCache._new_base`) therefore only helps GIL builds; on
   3.14t/3.15t a pause is proportional to everything alive.
6. **What is alive is vmn's lever.** After a cold load the process holds
   56-61 objects per run (1.74-1.84M at 30k, 5.6M at 100k); a warm restart
   on the same index holds ~26 per run (0.80M at 30k, 2.56M at 100k: the persisted
   lean rows and side tables, `core/index_lazy.py`). The cold process keeps
   roughly twice the objects for the same board, so every later collection
   walks twice the heap. Scaled to the soak's 588k runs that is ~33M objects
   cold against ~15M warm, matching the 1.5-2.9 s pauses reported there.
7. **The steady state does not collect.** 60 s of board pages and no-change
   refreshes triggered no collection on either free-threaded build (3.12 ran
   15k small ones), so the long pauses come with loads and refreshes that
   allocate many objects, not with serving.

### Verdict for appendix A row 6

**Explained.** There is no 3.15.2t regression: at low load the paired cold
loads pause the same on 3.15.2t and 3.15.1t (max 68-78 ms against 68-77 ms
at 30k, every policy), and the collector alone costs the same. The earlier
~3.5x gap and the second-long pauses came with machine load: a free-threaded
collection stops the world, the pause the hooks report includes waiting for
every attached thread to reach a safe point, and that wait grows from ~2 ms
to tens or hundreds of ms once runnable threads outnumber cores (on both
builds). The rest of a pause scales with the whole live heap, frozen objects
included (point 5), so a pause is (live objects × ~34 ms/M) + the
stop-the-world wait. CPython 3.15.2's mimalloc 2.5.2 update (gh-159111),
its change to how free-threaded memory is allocated and visited, shows no measurable
effect here. None of the bench's GC policies helps.

vmn-side mitigations, proposed and not done: (a) after a cold load has
published and persisted its rows, drop the per-run full-fold objects and
serve from the lean rows a warm start reads, so the resident heap is the warm
one (~26 instead of 56-61 objects a run, about half of each later pause);
(b) keep the cold load's CPU-bound threads at or under the core count (a
local store's reads parse YAML in Python on 32 threads; an S3 load's threads
mostly wait on the network, detached), which trims the stop-the-world wait;
not measured. Interim: restarting a server after its first cold load gives
the smaller heap.

## 2. The fgm probe over HTTP: `packages/vmn-exp/tests/uiload/probe_fgm.py`

`fgm-small` (51,506 runs: two finished launches and a live one), seeded once
with `seed_fgm.py` (68 s, 8 workers) including the fgm-like store settings
(`ui.attention`: waiting > 1 h via `ago("1h")`, handed back in 2 h, unstable,
failed trials; `ui.split_by: tags.kind`). Each interpreter served a fresh copy
of the index (`VMN_EXP_CACHE_DIR` per run) in-process; 20 requests a route,
p50 / p95 / first request, ms. Budgets are `slo.FGM_BUDGETS["fgm-small"]`.

| route (budget p95) | 3.15.2t, load ~80 | 3.15.2t, load ~300 | 3.15.1t, load ~80 | 3.12, load ~150 |
|---|---|---|---|---|
| status (250) | 4 / 8 / 8 | 15 / 128 / 171 | 3 / 9 / 9 | 69 / 193 / 147 |
| summary (300) | 6 / 214 / 693 | 3 / 31 / 796 | 2 / 2 / 575 | 48 / **770** / **3,051** |
| summary_split (300) | 4 / 18 / 24 | 7 / 47 / 47 | 2 / 3 / 2 | 24 / 85 / 40 |
| board_kind (500) | 3 / 3 / 75 | 9 / 46 / 102 | 2 / 3 / 70 | 56 / 240 / 415 |
| board_dates (500) | 3 / 7 / 145 | 5 / 57 / 193 | 2 / 60 / 204 | 29 / 367 / 1,017 |
| board_app (1000) | 4 / 7 / 448 | 40 / 648 / 800 | 3 / 115 / 432 | 2 / 254 / 881 |
| waiting, `ago("1h")` (1000) | 3 / 5 / 5 | 33 / 108 / 86 | 2 / 2 / 4 | 2 / 4 / 4 |
| index ready | 84 s | 177 s | 148 s | 110 s |
| budget breaches | none | none | none | summary p95, first |

The `waiting` column above measures cache hits: the probe sent the seeded
`ago("1h")` text every time, and the `status` route (whose attention count
pins the same query to the same minute) had already built that order.

### Low load, per-request minute shift

The probe now asks a minute further back on each request (`ago("61m")`,
`ago("62m")`, ...), so every `waiting` request misses the cache and rebuilds
the order, and reports `waiting_cold_ms`, one `ago("59m")` count right after
the index is ready (the first `ago()` order the server builds). Same seed
(copied fresh with `cp -c` per run, `VMN_EXP_CACHE_DIR` and `--data-dir` new
per run), run alone; p50 / p95 / first request, ms:

| route (budget p95) | 3.15.2t (load 9.6 → 8.7) | 3.15.1t (11.8 → 10.8) | 3.15.2t (11.2 → 10.6) |
|---|---|---|---|
| status (250) | 1.4 / 1.7 / 2.4 | 1.6 / 2.9 / 12 | 1.4 / 1.7 / 3.3 |
| summary (300) | 1.3 / 43 / 506 | 1.4 / 2.6 / 455 | 1.3 / 2.4 / 447 |
| summary_split (300) | 1.2 / 1.3 / 1.3 | 1.3 / 1.4 / 1.4 | 1.4 / 1.8 / 1.3 |
| board_kind (500) | 1.3 / 1.6 / 56 | 1.4 / 1.8 / 57 | 1.5 / 1.8 / 60 |
| board_dates (500) | 1.5 / 1.9 / 101 | 1.5 / 37 / 109 | 1.5 / 2.2 / 113 |
| board_app (1000) | 1.8 / 3.3 / 291 | 2.0 / 23 / 319 | 1.7 / 3.5 / 330 |
| waiting, `ago()` a minute back per request (1000) | **25 / 45 / 32** (max 62) | **34 / 38 / 64** (max 64) | **27 / 57 / 37** (max 63) |
| `waiting_cold_ms` | **37** | **45** | **48** |
| index ready | 50 s | 51 s | 51 s |
| budget breaches, errors | none, 0 | none, 0 | none, 0 |

A cold `ago()` order over the 51.5k runs costs 25-34 ms at the median and at
most 64 ms, 37-48 ms for the first one, far inside the 1,000 ms budget and
the same on both builds. The summary's first request (447-506 ms) is the
slowest single request; `slo.fgm_evaluate` reported no breach. At low load every route's p50 is 1-2 ms on either build, against 2-69 ms in
the loaded first session.

Every run read the seeded settings back: attention `waiting 372,
handed_back 103, unstable 761, failed_trials 834` in the first session,
`waiting 786, handed_back 96-102` in the second (the seed's `created` runs
aged past an hour and its releases past two in between); the summary's
default split `tags.kind` (10 kinds). The full 588k-run shape was not measured: its cold
index took over 55 minutes on the GIL build, past this session's bench budget.

## 3. fgm at full scale (594k runs) over HTTP on 3.15.2t

The remote path (what fgm's S3 store takes) is measured in full in §3.2.
§3.1 is the local-store path, which was cut short.

### 3.1 Local store (incomplete)

**Incomplete: the cold index did not finish.** The laptop went into clamshell
sleep on battery 40 minutes into the cold load (`pmset -g log`: "Entering
Sleep state due to 'Clamshell Sleep'" at 18:56:26), and after that the
machine ran only in short maintenance wakes. No route was timed and there was
no warm restart. The numbers below cover the 40 minutes before the sleep
(18:16-18:56, load average 6-10, checked every 2 s), on master `692601da`
(a cold load drops its full folds once saved; cold-load threads capped at the
core count on free-threaded builds).

Seed: `seed_fgm.py --profile fgm --workers 12` wrote 594,129 runs (550,000
succeeded, 26,239 failed, 10,276 running, 3,931 created, 3,121 released, 562
stuck) in 134 s, 6.8 GB on APFS. Probe: `probe_fgm.measure` through a
scratch driver that serves the root in-process like `probe_fgm.main` (fresh
`VMN_EXP_CACHE_DIR` and `--data-dir`). It also polls `experiments-status`
every 2 s and samples the RSS of the server and its children.

| | fgm-small (51.5k), §2 low load | fgm (594k), this run |
|---|---|---|
| seed | 68 s (8 workers) | 134 s (12 workers) |
| index ready | 50-51 s | not reached; ≥ 72 min projected |
| index rows persisted | 51.5k | 250k at 16.5 min, 322.5k at 27 min, 383k at 37 min, ~395k at the sleep |
| ingest rate | ~1,000 runs/s | ~250 runs/s for the first 250k, then ~100-110 runs/s |
| first publish (`total > 0`) | (not recorded) | none in 40 min |
| `experiments-status` while loading | (loads in under a minute) | `indexing {loaded: 0, total: null}` for all 40 min |
| server process RSS | (not recorded) | peak 1.24 GB while listing (first ~2 min), then 63-85 MB |
| I/O helper RSS | (not recorded) | peak 4.76 GB, then 1.3-2.0 GB |
| index file | (not recorded) | 3.1 GB + 0.66 GB WAL at ~400k rows |
| routes, `waiting_cold_ms`, budget breaches, GC pauses, objects per run | §2 | not measured |

What the run shows:

1. **A local store's cold load runs in the I/O helper process
   (`core/index_io_process.py`), so the server holds almost nothing during
   it.** The server process stays at 63-85 MB. The helper, one thread at
   ~100 % CPU, does the reading and the saving, and peaked at 4.8 GB. The
   threads-capped-at-core-count change does not reach this path. The heap
   that GC pauses scan is in the server only after the helper streams the
   rows back, which this run never reached.
2. **The load does not scale linearly.** Linear scaling from fgm-small (×11.5)
   would mean ~10 minutes. Instead the first 250k rows went at ~250 runs/s
   and the rate then fell to ~100 runs/s as the SQLite file grew past 1.5 GB.
   Even at a steady 100 runs/s, the ~200k rows left would take another
   ~33 minutes, so ready at ≥ 72 minutes (~7× the linear figure). macOS
   `sample` of the helper at ~380k rows: `pwrite`, `pread` and `fsync` took
   ~60 % of its samples, then `walFindFrame` and B-tree seeks. The save
   (exp_rows, exp_sides and the similar-FTS tables in one file with a
   0.4-0.66 GB WAL) is the bottleneck, not YAML parsing.
3. **This cold load shows no progress and publishes no first chunk.** The
   chunked publish (`_REMOTE_CHUNK` = 500, `indexing {loaded, total}`)
   applies to remote stores. The local helper path reported
   `{loaded: 0, total: null}` and `total: 0` for 40 minutes, so the web shows
   neither a count nor rows until the whole load is saved.

### 3.2 Remote path (complete)

On AC power with `caffeinate -s`, master `f687091c`, 3.15.2t. The seeded
root is served as a remote store (`is_remote()` true, as
`gc_pause_bench._remote_storage` does), so the cold load takes S3's path:
`_REMOTE_CHUNK` = 500 records published at a time, parallel readers. The
driver is in-process like `probe_fgm.main`. Routes are 50 requests each,
taken after the index is ready; budgets are `slo.FGM_BUDGETS["fgm"]`. Two
cold loads (each from a fresh index) and one warm restart on the index the
first left.

| | cold 1 | cold 2 | warm restart |
|---|---|---|---|
| load average before / at ready | 7.6 / 181 | 7.0 / 7.8 | 5.7 / 8.7 |
| server up | 0.66 s | - | 0.67 s |
| first publish | 58.8 s (6,383 runs) | 43.5 s | 0.74 s |
| index ready (594,129 runs) | 612 s | 608 s | 37 s |
| RSS peak / after the probe | 26.1 / 19.8 GB | 22.1 / 14.3 GB | 11.2 / 10.3 GB |
| GC: collections, total paused, max pause | 79, 50.0 s, 3.22 s | 82, 50.1 s, 3.09 s | 14, 2.2 s, 1.24 s |
| `gc.collect()` after the probe | 5.8 s, 4.0 s | 11.4 s, 10.3 s | 7.3 s, 6.6 s |
| `waiting_cold_ms` | 453 | - | 529 |
| budget breaches | `board_app` p95 2.06 s, first 5.8 s; `waiting` p95 1.48 s (load 155) | `board_app` p95 1.87 s | `board_app` p95 2.16 s |

Routes after ready, p50 / p95 / first, ms (cold 1 at load ~155, warm at ~9):

| route (budget p95) | cold 1 | warm restart |
|---|---|---|
| status | 1.4 / 1.6 / 172 | 1.9 / 3.2 / 163 |
| summary | 1.5 / 1.9 / 134 | 1.6 / 2.7 / 145 |
| summary_split | 1.3 / 1.7 / 1.4 | 2.3 / 3.8 / 3.3 |
| board_kind | 1.4 / 1.7 / 39 | 2.0 / 2.8 / 45 |
| board_dates | 1.5 / 1.9 / 168 | 4.3 / 9.4 / 45 |
| board_app (1,000) | 1.7 / **2,057** / **5,769** | **1,963** / **2,164** / 1,854 |
| waiting, `ago()` shifting a minute a request (1,000) | 548 / **1,476** / 6 | 451 / 596 / 131 |

While loading (cold 1, before ready), routes were answered from the
published chunks with p50s of 0.3-3 s and p95s of 6-12 s, at load 14-180:
the load itself (32 readers, YAML parsing, folds, saves) competes with
serving on the same cores.

What the run shows:

1. **The remote cold load scales about linearly.** It was ready in 608-612 s,
   against fgm-small's ~51 s × 11.5 ≈ 590 s. It answers from its first chunk
   at 44-59 s and shows `indexing {loaded, total}` throughout. That is unlike
   the local path in §3.1, which shows nothing for over an hour.
2. **The fold drop (mitigation 1) takes effect at full scale.** Cold 2
   checked the index every 30 s for 3 minutes after the probe. Each check
   showed `cold: False` with nothing unsaved and no listing in flight, the
   state `_drop_folds` leaves, while RSS fell from 20.3 to 14.2 GB. A
   rebuild's folds are now dropped by the adopting index (`6a527942`).
3. **Objects per run is not a fold measure at this scale.** It was 61 (cold 1),
   109 (cold 2, rising 58 → 109 over 3 idle minutes) and 82 (warm), with
   `gc.collect()` then taking 4-11 s. The free-threaded GC policy (automatic
   collection off, collecting on its own 300 s clock) let an idle server's
   cyclic garbage pile up between its collections. Background refresh and
   board polls make cyclic garbage: `test_ft_gc_policy_generations` counts 88
   cyclic objects per HTTP board poll against its 50 budget. Most of it comes
   from the `@app.middleware` (BaseHTTPMiddleware) layers. The settings scope
   is now plain ASGI (`f687091c`); the audit, auth and tenancy layers still
   are BaseHTTPMiddleware.
4. **`board_app` misses its budget at 594k runs even warm.** The whole-app
   board took 1.9-2.4 s per request at load ~9 (budget 1 s p95). Scoped
   boards (`board_kind`, `board_dates`) and status/summary stay in
   single-digit ms. `waiting` (an `ago()` count rebuilt every request) holds
   450-600 ms at low load, inside its 1 s budget.
5. **The GC pauses during a cold load are as long as the soak saw** (max
   3.1-3.2 s, ~50 s paused in all over the 10-minute load). That matches
   §1's model: a pause is the live heap (~31-36M objects here) plus the
   stop-the-world wait. The fold drop shrinks the heap after the load, not
   during it.

Follow-ups (not plan 28 items): the whole-app board at this scale; the
remaining BaseHTTPMiddleware layers; the local-store cold load (one helper
thread bound on SQLite writes, nothing published until it ends); whether the
GC policy's clock should shorten when an idle server's garbage grows.
