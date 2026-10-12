# 20 — Per-root remote streams

Status: **done**.

## Problem

A run's log and metric objects were keyed by writer id only
(`log/<writer>[@<seq>].jsonl`, `metrics/<writer>[@<seq>].vms`). The writer id
is the host name by default, so two local roots on one host — two clones of a
repo, a clone and a cached `vmn-exp ui`, a cache cleared and fetched again —
appended to the *same* remote stream, each from its own local file. Keeping
that stream consistent took a seed/merge/catch-up protocol in
`storage/cached_logs.py` + `storage/cached_log_merge.py` (seed the local file
from the remote before the first append, merge foreign lines in, catch up the
offset after a lost response), a `LocalLogLock` around it, `_seed_failed`
fallbacks, and metric parts (`@p<k>.vmx`) with `reopen_writer`/`drop_indexed`
for a writer resuming after compaction. Interleavings of two roots, lost
responses, failed listings, restarts and compaction still lost or duplicated
entries (the parked multi-clone tests and the review probes reproduce them).

## Design

- **Stream key** `<writer>~<owner>` (`core/streams.py`): `stream_key`,
  `display_writer` (the part before `~`), `owner_of`. The writer id users see
  and set is unchanged; a `~` in an explicit writer id becomes `-`.
- **One appending owner per stream.** The owner is per local *record copy*:
  `<record>/.stream-owner` (`storage/stream_owner.py`, JSON with the id, the
  directory's realpath and `[st_dev, st_ino]`, the retired ids and the
  inherited ones), minted under the copy's owner lock (`.ship/owner.lock`,
  re-reading the file first, so all processes opening a fresh copy at once get
  the same owner) and read by every other process of the copy. A copy is the
  physical directory: the same `(st_dev, st_ino)` keeps the owner whatever
  path reached it (a symlink, a bind mount, macOS `/tmp` vs `/private/tmp`, a
  rename on one filesystem, a `vmn-exp push` `.rN` rename). Another directory
  — a `cp -r`, a backup restored at the original's path, a cross-filesystem
  move — never keeps the owner (the original may have gone on appending and
  shipping, so the copy's file can be a stale prefix of the remote): the copy
  mints a new owner and *inherits* the old one's streams (and those it
  retired or inherited), each with the record (realpath + identity) it came
  from. An inherited stream's local file never grows again. Unless its record
  is another directory still there, the copy ships and pushes what the remote
  lacks of it — nothing when the remote is ahead, the missing suffix when behind, from a fresh
  listing, never once the remote compacted it — and never compacts it nor puts
  it as a `.vmx` from its local file (an inherited local `.vmx` was built by
  its owner from the whole file, so it goes up while the remote has none).
  While the original still lives it alone ships its streams: its ship state
  trusts that. A process that sees the same directory with another identity
  (a container's `st_dev` for a bind-mounted dir, overlayfs) mints too and
  ships every inherited stream whose record is this directory as it sees it,
  so a disagreement costs an extra stream, never an unshipped one. A
  `.stream-owner` without an identity (older) counts as another directory. A copy deleted and fetched again also mints a new owner. The brief suggested a root-level id; a per-record
  owner also covers `prune --local-only` / a cleared cache followed by a
  re-fetch, which would otherwise append to a stream whose local file is
  shorter than its remote copy.
  - No local copy (straight to a bucket): the process's owner
    (`process_owner`, re-minted after `fork`).
  - A log buffer (`storage/buffered.py`): its own owner, rotated when the
    buffer is cleaned up.
  - `core/writer.py:own_stream(storage, app, verstr)` is the one way callers get
    it; `append_to_log`, metric writers, registry/comment/report-header logs,
    `similar-backfill` and compaction all go through it.
  - A copy owns the streams of its current and retired owners only. Another
    owner's local log or metric file (a `cp -r` of the original's root holds a
    stale prefix of its streams) is read and compacted from the remote, never
    shipped, compacted from the copy, pushed (`vmn-exp push`) nor put as a
    `.vmx`: the original's ship state assumes it alone ships its stream, and a
    segment it creates behind a range the copy compacted would be hidden
    (inherited streams whose record is gone only get their missing part, as
    above). A log
    line or metric block appended under an owner the copy does not own (a
    one-off owner, named while the record could not be fetched) goes to the
    copy's own stream.
  - Processes and threads of one copy append metric blocks under the copy's
    append lock (`.ship/append.lock`, never held across remote calls) from
    choosing the stream to writing the block; a compaction retires its stream
    under the same lock before it reads the file, so a block lands in the file
    the build reads or in the next stream, never in one `put_indexed` drops.
- **The remote is a replica of the owner's local file.** A sync ships every
  local stream of the copy (`cached_logs.py`, `cached_metrics.py`): the bytes
  past what the remote holds go as the next segment through
  `create_log_segment` / `create_metric_segment`, which create it only if it
  does not exist (S3 `If-None-Match: *`, `S3Base._create`). A taken segment
  means another process of the copy shipped it: list again and resume from the
  remote size. What the remote holds is kept in `<record>/.ship/<kind>.json`
  per remote, read and written under the copy's ship lock
  (`storage/ship_state.py`); a ship forgets its entry before uploading, so a
  lost response is re-listed, never re-sent blindly.
- **Compaction never hides points.** A `.vmx` is named with the span it covers,
  `metrics/<stream>@000000-<last>.vmx`, and supersedes only segments up to
  `<last>`; a later segment stays visible beside it, the widest `.vmx` wins.
  The owner compacts its own stream from its local file under the ship lock
  and then retires the owner, so nothing is ever appended behind a `.vmx`
  (`local_streams.py:live_stream` redirects a late append of the retired owner
  to the current one). A foreign stream compacted by `vmn-exp compact` is built
  from the remote and stored remotely only. Seal (every 10M points) is the same
  compaction followed by a new stream; parts are gone.
- **Reads that fail raise.** S3 `read_range` raises on anything but a missing
  object, so a network blip is never taken for absence by a compaction that
  then deletes the segments.
- **Push** (`core/push_logs.py`, `core/push_metrics.py`) uses the same exclusive
  segment creates and span-named `.vmx`.
- **Displays** use `display_writer`: the merged log's `_writer`, UI writer
  columns, `export-metrics`, the `similar-backfill` creator.
- Index `SCHEMA_VERSION` → `exp-index-13` (metric object names changed). No
  migration of old records: clean break.

## Deleted

- `storage/cached_log_merge.py` (seed, merge, catch-up) and the `LocalLogLock`
  / `_local_log_held` locking in `storage/cached_logs.py`; `_seed_failed`,
  `_claimed`, the buffered storage's `_initial_sync_state`/`_ship` overrides.
- Metric parts (`@p<k>.vmx`), `reopen_writer`, `drop_indexed`.
- Tests of those mechanisms only (`test_index_log_rewrite_offline.py`,
  `test_ui_parsed_logs_rewrite.py`, `test_storage_cached_log_rewrite_lock.py`,
  `test_storage_cached_log_lock_interrupt.py`, the part tests); the outcomes
  they guarded are covered by `test_storage_multi_clone_*.py`.

## Known limits (not covered by tests)

- Two processes of one record copy: an append landing between the owner's
  compaction reading the local stream and the owner's retirement.
- A log buffer (`storage/buffered.py`) whose stream another root compacted
  while the buffer still held an unshipped tail.
