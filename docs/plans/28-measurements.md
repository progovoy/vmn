# Plan 28: measurements (2026-10-28)

Numbers for appendix A row 6 (GC pauses on 3.15.2t) and the B0 follow-up
"measure over HTTP on free-threaded Python". One laptop (Apple silicon), shared
with other agents' test runs: the load average swung between 20 and 520 while
these ran, so each number carries the load it ran under. Treat single runs as
noisy; the paired (ABAB) runs are the ones to compare.

Interpreters: CPython 3.15.2t and 3.15.1t (free-threaded, uv builds, GIL off,
the same package versions in both venvs, no libyaml in either), and the repo
venv's 3.12.13 (GIL) for reference.

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

### 30k runs, ABAB (3.15.2t, 3.15.1t, 3.15.2t, 3.15.1t; load average 85 → 37)

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

### The collector alone (`gc.collect()` on a built heap, min of 3; load ~25)

A list of N `{"a": [i], "b": (i, "x")}` items, collection off while building:

| N | 3.15.2t | 3.15.1t | 3.12 |
|---|---|---|---|
| 1M | 34 ms (frozen 15 ms) | 34 ms (frozen 15 ms) | 365 ms (frozen 0) |
| 2M | 68 ms (frozen 29 ms) | 68 ms (frozen 30 ms) | 801 ms (frozen 0) |
| 4M | 135 ms (frozen 58 ms) | 136 ms (frozen 59 ms) | 1,118 ms (frozen 0) |

The same heap of 2M built by 1, 8 or 32 threads, collected with or without 32
idle live threads: 67-110 ms on both 3.15 builds, no version difference.

### What the numbers say

1. **The collector itself did not regress in 3.15.2t.** On a heap built by one
   thread or many, with or without idle threads, a full collection costs the
   same on 3.15.1t and 3.15.2t (~34 ms per million items).
2. **In vmn's cold load, 3.15.2t pauses ~3.5x longer at equal collection
   counts** (45 collections each; max 292-297 ms against 83-84 ms at 30k), and
   the whole cold path is ~2x slower (46-55 s against 26-27 s; board pages in
   the steady state 2-5x fewer). Warm restarts do not differ. Since the
   collector costs the same in isolation, the extra time is likely in what a
   multi-threaded collection waits for (the free-threaded build stops the
   world, and the pause hook probably spans that wait; not verified) and in
   3.15.2t's slower
   multi-threaded interpreter on this workload. A pure-Python YAML parse
   (the cold path's main work: neither venv has libyaml) ran 1,150/875
   records/s on one 3.15.2t thread against 1,714/410 on 3.15.1t, at load 500:
   too noisy to conclude more. Whether this is CPython's side is open (see
   the verdict).
3. **On free-threaded builds `gc.freeze()` does not shorten a collection.**
   A full collection still walks every frozen object: 58 ms per 4M frozen
   items (micro), 0.2-1.4 s after `freeze_long_lived()` at 100k cold, against
   exactly 0 on 3.12. `freeze_long_lived()` (`core/gc_pause.py`, called by
   `LeaderboardCache._new_base`) therefore only helps GIL builds; on 3.14t/3.15t
   a pause is proportional to everything alive.
4. **What is alive is vmn's lever.** After a cold 100k load the process holds
   5.6M objects (~56 per run); a warm restart on the same index holds 2.6M (~26
   per run: the persisted lean rows and side tables, `core/index_lazy.py`). The
   cold process keeps roughly twice the objects for the same board, so every
   later collection walks twice the heap. Scaled to the soak's 588k runs that is
   ~33M objects cold against ~15M warm, matching the 1.5-2.9 s pauses reported.
5. **The steady state does not collect.** 60 s of board pages and no-change
   refreshes triggered no collection on either free-threaded build (3.12 ran
   15k small ones), so the long pauses come with loads and refreshes that
   allocate many objects, not with serving.

### Verdict proposal for appendix A row 6

**Investigating: partly explained.** Established: on free-threaded builds a
pause scales with the whole live heap, and `gc.freeze()` does not exempt
frozen objects (point 3), so vmn's resident heap after a cold load sets the
pause length (point 4). Open: why 3.15.2t pauses ~3.5x longer than 3.15.1t
inside vmn's multi-threaded cold load while the collector alone is no slower
(points 1-2). The stop-the-world wait and a slower interpreter are guesses;
the bench's `callback` and `threshold` policies, or timing the stop-the-world
phase apart from the collection, are needed to tell the collector's work from
the wait before calling it a CPython regression. vmn-side mitigation (not
done): after a cold load has published and persisted its rows, drop the
per-run full-fold objects and serve from the lean rows a warm start reads, so
the resident heap is the warm one (~2.6M instead of 5.6M objects at 100k,
about half of each later pause). Interim note while the gap is open, not a
recommendation against 3.15.2t (the target build): restarting a server after
its first cold load gives the smaller heap, and on these measurements 3.15.1t
paused less.

Not run: the bench's `GC_BENCH_POLICY` experiments (`callback`, `index`,
`threshold`).

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
pins the same query to the same minute) had already built that order. The
probe now asks a minute further back on each request (`ago("61m")`,
`ago("62m")`, ...) so each one rebuilds, and reports `waiting_cold_ms`, the
first `ago()` order built after the index is ready; those numbers are not
measured yet.

Every run read the seeded settings back: attention `waiting 372,
handed_back 103, unstable 761, failed_trials 834`, the summary's default split
`tags.kind` (10 kinds). The full 588k-run shape was not measured: its cold
index took over 55 minutes on the GIL build, past this session's bench budget.
