# Plan 33: index upgrades that keep serving

> fgm upgraded 0.1.34 → 0.1.35 (`RECORDS_VERSION` 18 → 19, copyable with a
> re-read predicate; `DERIVED_VERSION` 21) on a 40 GB index of ~734k runs. The
> upgrade took about 40 minutes. It needed free disk about the size of the
> index (theirs hit 91%), and for all 40 minutes every experiments query
> answered `total=0` with no message, while `/apps` showed 734k. Plan 32's rule
> 3 (missing is missing) applies: an index still loading must say so, never
> answer an empty board.
>
> Paths: `core/` = `packages/vmn-exp-sdk/src/vmn_exp/core/`; `ui/` =
> `packages/vmn-exp/src/vmn_exp/ui/`; tests in `packages/vmn-exp/tests/`.

Status: **in progress** (2026-11-09). Found by a code read plus a local
measurement (20k synthetic runs, ~22 KB/run).

## 1. What happened

- **Duplicate copies.** `regenerate` runs inside the `SqliteStore`
  constructor (`core/index_store.py:58-60` → `core/index_store_conn.py:73,94`),
  on whichever thread opens the file first, with no lock. Until the flip
  (`core/index_store_upgrade.py:38`) each opener sees the old pointer and
  starts its own copy (reproduced: 3 threads built `c.1`, `c.2`, `c.3`).
  Request threads open their stores while holding `ExperimentSource._lock` or
  `_SHARED_LOCK`, so requests block during the copy.
- **A silent empty board.** After the flip, the re-derive (`core/index.py:563-590`)
  publishes empty snapshots with `loading=(done, total)`. `/apps` counts the
  copied `exp_index` rows (734k), while the board has no rows yet (total=0).
  `list_experiments` (`ui/routes_leaderboard.py:98-172`) carries no `indexing`;
  only experiments-status does (`ui/routes_shell.py:129-135`). The web shows
  "indexing X / Y" from its status poll; the API and SDK get a silent 0.
- **Time.** The copy is ~0.055 ms/run (1–2 min at their size). The re-derive
  is ~0.5 ms/run and dominates (likely 15–25 min there): similar-run FTS
  filing ~39%, `lean_row` ~26%. Then the warm load and the S3 re-reads of the
  runs the predicate picked. fsync and the WAL are not the cause.
- **Disk.** The old file plus a full new one; there is no free-space check.
  The docstring's reason against in-place upgrades (dropping tables holds the
  write lock for minutes) does not apply to a copyable bump, which drops
  nothing.

## 2. Fixes

1. **One upgrader per index file.** A thread lock plus a file lock on
   `<path>.upgrade`; the pointer is re-read once the lock is held, so a waiter
   opens the new generation instead of copying again.
   Test: 3 threads open an outdated file; one generation is built.
2. **`indexing` on experiments answers.** While the snapshot is loading,
   `list_experiments` (and the other board answers built from the same
   snapshot) carry `indexing {loaded, total}`, as experiments-status does.
   The SDK/CLI readers say "indexing N%" instead of returning an empty list
   as if final. The web shows it on the board.
   Test: mid-derive, an experiments answer carries `indexing`.
3. **In-place copyable upgrade.** When the found records version is in
   `COPYABLE_RECORDS`, upgrade the file in place, with no new generation:
   - a lock-free read pass picks the stale keys;
   - chunked `DELETE`s remove those records and their run states;
   - the re-read list, derive markers and the records mark are written last.
   Existing derived rows stay and are served, marked `indexing`, while the
   derive rewrites them chunk by chunk (the gate at `core/index_store_reads.py:107`).
   The journal mark is kept.
   Tests:
   - a records-18 file upgrades with no new generation;
   - the picked rows are deleted and listed to re-read;
   - the mark is kept;
   - a snapshot taken mid-derive has total > 0 and `indexing`.
4. **Free-space check.** An upgrade that needs a fresh file (not copyable)
   checks `shutil.disk_usage` first. When there isn't room, it refuses with a
   message naming the bytes needed and the path, rather than filling the disk.
   Test: a monkeypatched `disk_usage` refuses and builds no generation.
5. **File similar-run search after the derive.** The derive writes rows only;
   the background filer (`similar_corpora` `filer.sync`) files similar-run
   documents afterwards. Test: the derive leaves the similar docs to the
   filer, which fills them in.

Dropped: a faster record copy (ATTACH + `INSERT … SELECT`). After fix 3 a
copyable bump copies nothing, and a non-copyable one reloads from storage.

## 3. Order

Three TDD worktrees in parallel: (1, 3, 4) the upgrade path; (2) the
answers and the web; (5) the derive and filing. `/simplify` on each.

## 4. Client note

The next upgrade in place needs no extra disk. The board keeps its rows,
marked "indexing N%", until the derive finishes. Values that the bump
changed (here: summary types, params sharing a metric's name) are the old
ones until their row is re-derived.

The next upgrade (records 19 → 20: a metric's last write from older `.vmx`
footers, and the step-restart mark on rows) is in place too and reads no run
again up front. It lists the runs with compacted metrics logged more than
once (nearly every training run) for a background check that reads each
one's `.vmx` footers (one ranged GET per file, 64 KB) and, for a footer an
older vmn-exp wrote over 64 KB, its stepped keys' timestamps (one more GET per
key and 65,536 points). Only the runs whose steps went back are read again.
The status says `checking N / M compacted runs` meanwhile, the board serves
its rows, and the check resumes after a restart.
