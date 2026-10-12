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
  directory's absolute path and the retired ids), created exclusively by the
  first process that needs it, read by every other process of the copy. A file
  naming another path (the directory was copied) or a copy deleted and fetched
  again mints a new owner. The brief suggested a root-level id; a per-record
  owner also covers `prune --local-only` / a cleared cache followed by a
  re-fetch, which would otherwise append to a stream whose local file is
  shorter than its remote copy.
  - No local copy (straight to a bucket): the process's owner
    (`process_owner`, re-minted after `fork`).
  - A log buffer (`storage/buffered.py`): its own owner, rotated when the
    buffer is cleaned up.
  - `core/writer.py:own_stream(storage, app, verstr)` is the one way callers get
    it; `append_to_log`, metric writers, registry/comment logs, `similar-backfill`
    and compaction all go through it.
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
