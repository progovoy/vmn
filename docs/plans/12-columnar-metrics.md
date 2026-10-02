# 12 — Columnar metric storage

Status: **design, not started**. Builds on [11-central-server.md](11-central-server.md)
(journal, read-only server). No old clients need supporting, so this plan changes the
record format outright (§9 covers existing data).

Paths are under `packages/`; `S` = `vmn-exp-sdk/src/vmn_exp`, `U` = `vmn-exp/src/vmn_exp/ui`,
`W` = `vmn-exp/webui/src`.

---

## 1. Why

### How metrics are stored and read today

- A metric write is a JSONL line in the writer's log:
  `{"timestamp":"…Z","type":"metrics","values":{"loss":0.5,"acc":0.9},"step":12}`
  (`S/core/writer.py:103`). `sys_*` metrics are the same entries without `step`.
- Every reader parses the whole log as JSON:
  - `metric_series` (`S/core/log.py:57`) builds `{key: [{step, ts, value}]}` from it.
  - The UI keeps parsed logs in a 64 MB / 128-record LRU (`U/readers/parsed_logs.py`) and
    thins with min/max buckets (`U/readers/series.py`).
  - The SDK's `get_metric_history` loads the full log to return one metric
    (`S/sdk/reader.py:218-312`).
- The index folds summaries entry by entry; it's incremental over appends
  (`S/core/index_logs.py`), but every point is still parsed once.

### Where that stops scaling

Fine at what we test: the uiload `load` profile runs 20 keys × ≤5000 steps, with series p95
at 500 ms. W&B users log far more:

| Case | Points | JSONL today | Cost |
|---|---|---|---|
| LLM pretraining, 1M steps × 50 keys | 50M | ~2–3 GB of log | A run page parses all of it; the 64 MB cache can't hold it; `get_metric_history` takes minutes |
| Per-layer stats, 10k steps × 5000 keys | 50M | same | Every point is re-parsed to draw one key |
| 1000-run overlay of 1 key, 100k steps each | 100M | 1000 full logs | One chart reads every log in full |

The problem is the shape, not the parser. JSON lines force reading every key and every
point to get any one key at any resolution.

### Goals

1. Reading one key at chart resolution costs **O(chart points)**, not O(log size), for
   finished runs. That holds on object stores too, using byte-range reads.
2. Zooming fetches full-fidelity points for the visible range (W&B's zoom).
3. Folding summaries costs O(blocks), not O(points).
4. Writers stay **stdlib-only** (`struct`, `array`, `zlib`): the SDK keeps its three
   dependencies. No pyarrow or numpy in the write path.
5. A storage size reduction: about 4–6× vs JSONL for typical series.

### Non-goals

- Histograms, media and tables. They stay as they are; histograms could move to this format
  later.
- A query engine over series (DuckDB-style SQL). Parquet export (§8.3) covers that.
- Server-side compaction in SaaS. The server's storage access is read-only by default
  (plan 11 §6.3), so writers compact (§6).

---

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Metrics leave the JSONL log.** Writers append metric points to a per-writer binary **metric stream**; the JSONL keeps everything else (params, notes, tags, rewind, define_metric, inputs, artifacts, media, run). | Storing both would double the size and keep the JSON parse on the hot path. No old clients to keep. |
| D2 | **Custom block format, not Parquet**, for the write path. Parquet is an **export** (§8.3). | A Parquet writer needs pyarrow (~40 MB with native code) in every job. The block format is ~300 lines of stdlib Python and decodes with `array.frombytes`. |
| D3 | **Two files per writer:** an append-only stream during the run, and an **indexed** file (per-key columns, a LOD pyramid, a footer) written when the run finishes. | Appends need a log shape; range reads need columns. The stream is the write-ahead log of the indexed file. |
| D4 | **The LOD pyramid uses the same min/max buckets the UI thins with today** (`U/readers/series.py`). | Charts look the same as now; the precomputed levels are exactly what `SeriesThinner` would compute. |
| D5 | Values are **float64**; steps int64; timestamps int64 microseconds. | Lossless against today (values are already coerced to float, `S/core/values.py`). |
| D6 | Bump `RECORD_FORMAT_VERSION` to **2**. v1 records are converted once (§9); readers drop the v1 metric path. | One read path. |

---

## 3. File formats

### 3.1 Metric stream: `metrics/<writer>.vms`

An append-only sequence of self-delimiting **blocks**. A writer appends one block per flush
(the SDK's `LogBuffer` already flushes every 1s or 1000 entries, `S/sdk/log_buffer.py`).

```
block := MAGIC "VMSB" | u8 version=1 | u32 header_len | u32 body_len | u32 crc32(header+body)
         | header (JSON, utf-8) | body (zlib)

header := {
  "keys": [                                   # one entry per key present in this block
    {"k": "loss", "n": 1000,
     "has_step": true,
     "s": [first_step, last_step],
     "t": [first_ts_us, last_ts_us],
     "sum": {"n": 998, "sum": 512.3, "min": [v, step, ts], "max": [v, step, ts]},  # finite only
     "first": [v, step, ts], "last": [v, step, ts]}
  ],
  "inherited": false                          # true for blocks copied by fork (§5.4)
}

body (decompressed) := for each key, in header order:
    steps   int64[n]   delta-encoded (first absolute)      — omitted when has_step is false
    ts_us   int64[n]   delta-encoded
    values  float64[n]                                     — NaN/inf stored as IEEE values
```

- **Long-by-key layout.** Each key has its own arrays, so sparse logging (different keys at
  different steps) costs nothing. A `log_metrics({"a":1,"b":2}, step=5)` call adds one point
  to `a` and one to `b`.
- **Step-less points** (`sys_*`, `log_metric` without a step) live in keys with
  `has_step: false`. That's the same rule as today: a key is step-less if logged without
  a step. A key logged both ways is split into `<key>` and an internal step-less twin; the
  reader merges them back.
- **Crash safety.** A torn final block (short read or CRC mismatch) is ignored, just as a
  torn last JSON line is today (`S/core/jsonl_tail.py`). The writer truncates it before its
  next append, once it has checked the CRC.
- **Per-block summaries** in the header make the fold O(blocks) (§5.3), and let a reader skip
  a block's body when a key isn't in it.
- Blocks are written only by their writer, so no locking is needed. Every append is
  journaled (plan 11 §5.2) and synced like logs (§4.2).

### 3.2 Indexed file: `metrics/<writer>.vmx`

Written once, when the writer finishes (§6). Immutable.

```
file := MAGIC "VMSX" | u8 version=1
        | column chunks …
        | footer (JSON, zlib) | u32 footer_len | u32 crc32(footer) | MAGIC "VMSX"

per key:
  raw chunks:   steps / ts_us / values, each split into chunks of 65,536 points,
                each chunk zlib-compressed separately (a range read of one chunk is useful alone)
  LOD levels:   L1 (bucket = 64 points), L2 (1,024), L3 (16,384), L4 (262,144) — only levels
                with ≥ 2 buckets. Each bucket = 8 float64:
                [min_v, min_step, min_ts, max_v, max_step, max_ts, n_finite, sum]
                (min/max over finite values; the bucket's first and last points are
                the min/max ones of the adjacent level, or come from the raw chunk at the edges)

footer := {
  "writer": "...", "format": 1, "rows": total_points,
  "keys": {
    "loss": {"n": 1000000, "has_step": true, "s": [0, 999999], "t": [...],
             "summary": {... as in block headers, for the whole key ...},
             "raw":  [{"off": 123, "len": 4567, "n": 65536, "s": [0, 65535]}, …] × 3 columns,
             "lod":  {"64": {"off": …, "len": …, "buckets": 15625}, "1024": {…}, …}},
    …
  },
  "rewinds_applied": false
}
```

- **Reading a key at resolution P over a range** = read the footer (one range GET from the
  end of the file, cached per record), pick the coarsest level with at least P/2 buckets in
  range, then read that level's slice. At P = 2000 over 1M points that's L2: about 1000
  buckets = 64 KB. Full-fidelity zoom on a narrow range reads one or two raw chunks.
- **Size.** Steps and timestamps delta-compress to about 1–2 bytes per point, values to about
  6–8. LOD adds about 1 byte per point at L1 and much less above it. So roughly
  **10 bytes/point vs 40–60 in JSONL**.
- **Rewinds** are applied when the file is built (hidden points dropped, summaries
  recomputed). That's why a rewind of a finished writer rebuilds its `.vmx` (§5.2).

---

## 4. Write path

### 4.1 `MetricWriter` (`S/core/metric_stream.py`)

One class, used by every writer:
- the SDK's `run.log_metric(s)` (`S/sdk/run_metrics.py`)
- `vmn-exp run`'s metrics-file ingestion
- `import-mlflow`
- fork (`S/core/fork.py`)
- `vmn-exp add` metrics

Behaviour:
- `add(key, value, step, ts)` appends to per-key Python `array('q')`/`array('d')` buffers.
  `sanitize_entry` keeps doing value coercion and dropping (`S/core/values.py`).
- `flush()` encodes one block (see §3.1) and appends it through storage
  (`append_metric_block`). It's called from `LogBuffer`'s existing flush points: every ~1s,
  on heartbeat, on finish, SIGTERM and exit.
- `commit=False` and the step counter (`S/sdk/steps.py`) are unchanged. They decide `step`;
  the writer only records it.
- `finish()` = final flush, then build the `.vmx` (§6).

### 4.2 Storage

New backend methods, mirroring the log ones:

| Method | Local | S3 / GCS / Azure (object-client halves) |
|---|---|---|
| `append_metric_block(app, verstr, writer, data)` | append to `metrics/<w>.vms` (same atomic-append rules as logs, `S/storage/local.py:315`) | local-first: append locally and ship new bytes as segments `metrics/<w>@<seq>.vms` on sync (`S/storage/cached_logs.py`); pure remote: `BufferedRemoteStorage` does the same from its temp dir |
| `metric_objects(app, verstr)` | `{writer: [(name, size)]}` | listing of `metrics/` |
| `read_range(app, verstr, name, offset, length)` | seek + read | S3 `Range` GET, GCS `download_as_bytes(start, end)`, Azure `download_blob(offset, length)` |
| `put_indexed(app, verstr, writer, path)` | atomic rename | upload with `IfNoneMatch`, then delete the writer's stream objects (as `compact_log_segments` does today, `S/storage/s3_logs.py:148`) |

- Grouping of stream objects reuses the log naming rules (`S/core/logfiles.py`
  `group_log_names`): the same seq scheme, with a `.vms` suffix.
- `.vmx` supersedes the stream objects it was built from. A reader that sees both (deletion
  in progress) uses only the `.vmx`.
- `vmn-exp push` copies `.vmx` files by sha and streams by offset, like logs
  (`S/core/push_logs.py`).

---

## 5. Read path

### 5.1 `SeriesReader` (`S/core/series_reader.py`, pure; exp-sdk)

The one way to get metric series, used by the SDK readers, the CLI, the index and the UI.

- `keys()`: key names with counts and summaries. Read from `.vmx` footers, plus the block
  headers of streams; never values.
- `points(key, step_range=None, ts_range=None)`: raw `(steps, ts, values)` arrays.
- `thinned(key, max_points, step_range=None)`: the LOD level or raw chunks, as in §3.2; for
  streams (live writers), `SeriesThinner` over decoded blocks. The output is the same min/max
  bucket shape as today.
- **Several writers:** a k-way merge per key by `(ts, writer)`, matching today's merged-log
  order (a stable sort on timestamp, `S/storage/files.py:116`). Most runs have one metrics
  writer (`all_ranks=False`), so the merge is usually a no-op.
- **Decoding** uses `array.frombytes` + `zlib`. If numpy is importable, the SDK frames path
  uses `numpy.frombuffer` to skip list conversion (optional, as `S/core/histogram.py` already
  does).

### 5.2 Rewind

Rewind markers stay in the JSONL (`S/core/rewind.py`): `{type: rewind, step: N}` hides
stepped points with step > N whose timestamp is before the marker.
- **Streams:** the reader applies markers while decoding (per point, by `(step, ts)`). Block
  summaries for affected keys are recomputed from the points.
- **`.vmx`:** markers older than the file are already applied (`rewinds_applied`). A marker
  newer than the `.vmx` can only come from `vmn-exp rewind` on a finished run. That command
  rebuilds the writer's `.vmx` (it has write access; it holds the repo lock as today). Until
  the rebuild lands, readers apply the marker over raw chunks (slow path, correct).

### 5.3 Fold and index

- `S/core/fold.py` metric folding works over block-header summaries and `.vmx` footer
  summaries, instead of entries: last/first by `(ts, writer, pos)`, min/max/sum/count
  combined. That's exact, because each summary covers whole blocks.
- `S/core/index_logs.py` tracks `consumed` bytes for `.vms` objects like it does for logs.
  A grown stream reads only its new blocks' **headers** (the header length is in the
  prefix; the body is skipped with a range read or seek).
- `metric_summary` (`last/first/min/max/mean`) is unchanged for callers.
- Bump the index `SCHEMA_VERSION`.

### 5.4 Fork

`start_run(fork_from=…, fork_step=N)` copies the source's points with step ≤ N into the new
run's stream as blocks marked `inherited: true` (today: copied JSONL entries with
`inherited: true`, `S/core/fork.py:53-89`). For a finished source it reads ranges from the
`.vmx`, not the whole series.

### 5.5 Where log entries used to carry metrics

Every consumer of `type == "metrics"` log entries moves to `SeriesReader`. Phase 0
inventories them with a grep; known ones:

- `metric_series` (`S/core/log.py`): becomes a thin wrapper.
- `U/readers/parsed_logs.py`: series come from the reader; the log cache keeps events only.
- `S/sdk/reader.py` `get_run` / `get_metric_history`, and `S/sdk/frames.py`.
- `step_metric` joins (`S/core/step_metric.py`): join on raw `points()` in range, then thin.
  There's no pyramid for joined series.
- Sweeps median stopping (`S/core/sweep/`), alerts, `importance` (it uses rows, so it's
  unaffected), `compare`.
- **Log views** (`vmn-exp show` prints the last 50 entries; the UI `RunLog`; `.../log?offset`)
  show metrics interleaved with events. `merged_log_view(record, offset, limit)` synthesizes
  `{type: metrics, values, step, timestamp}` entries from the stream for display only. It
  groups points with the same `(step, ts)` back into one entry, so output looks as it does
  today.

---

## 6. Compaction: who builds the `.vmx`

The server can't, because its storage access is read-only by default (plan 11 §6.3). So:

1. **The writer at finish** (SDK `finish()`/exit handler, `vmn-exp run` at child exit,
   importers at the end). It builds from its local copy of the stream (local-first) or from
   its temp buffer (pure remote), uploads the `.vmx`, then deletes the stream objects. This
   costs about 1–2 s per 10M points, inside the existing final-upload window
   (`VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC`). If it times out, the stream stays and readers use it.
2. **`vmn-exp compact <app> [-v <ref>…] [--all-finished]`**: for crashed or killed writers. It
   reads the streams and writes the `.vmx` (needs write access, run by the user or CI).
3. **`vmn-exp watch`** (already cron-friendly, `S/cli/…watch`) gains `--compact`: compacts
   runs that it sees as `failed` or `stuck` past their window.

Readers never need a `.vmx`. An uncompacted finished run is just slower to read (block
decode instead of a pyramid), and the UI shows "not compacted" in run details so it's
visible.

Live runs are read from their stream: decoded blocks are cached per record in the UI LRU
(bounded by decoded bytes) and thinned incrementally, as `SeriesThinner` does today. For very
long live runs, the writer also **seals intermediate `.vmx` parts** every 10M points per
writer (`metrics/<w>@p<k>.vmx`, covering the stream up to a block boundary), so a 3-week run
isn't read from the start on every poll. At finish the parts are merged into one `.vmx`.

---

## 7. UI and API

- **Series endpoints** (`GET .../experiments/{verstr}?series=…`, `POST .../series`) read
  through `SeriesReader.thinned`. The response shape is unchanged.
- **New range parameters:** `step_min`, `step_max` (or `ts_min`/`ts_max` for wall-clock axes).
  The chart's zoom (`W/components/useAxisBrush.ts`) refetches the visible range at full
  `max_points`, debounced, keeping the coarse series as the background while it loads. That
  gives full-fidelity zoom.
- **Many keys:** `GET .../experiments/{verstr}/metric-keys?prefix=&limit=` from footers and
  headers. The run page's metric picker becomes a searchable, virtualized list
  (`@tanstack/react-virtual` is already a dependency) and loads series only for visible or
  selected keys. With 5000 keys, nothing is fetched until it's shown.
- **Overlay of many runs:** `POST .../series` reads one footer plus one level slice per run,
  so a 1000-run overlay of one key reads about 1000 × 64 KB, in parallel on the existing
  8-thread pool.
- **Limits** stay as today (`MAX_SERIES_POINTS = 20_000`, `MAX_TOTAL_POINTS = 200_000` per
  response).
- **Smoothing** stays client-side EMA (`W/hooks/useSmoothing.ts`). Smoothing over downsampled
  points differs slightly from smoothing over raw ones, which is also true today. Server-side
  smoothing over raw points is a possible follow-up, not in this plan.

---

## 8. SDK and CLI

### 8.1 SDK readers

- `get_metric_history(run, key, step_range=None, max_points=None)` reads one key only.
  `max_points` returns the thinned series. The pandas frame is built from arrays.
- `get_run(..., keys=…)` loads only the requested keys' series.
- New: `iter_metric_keys(run)` for runs with thousands of keys.

### 8.2 CLI

- `vmn-exp compact` (§6).
- `vmn-exp show` is unchanged in output (via `merged_log_view`).
- `vmn-exp export` includes `.vms`/`.vmx` files as they are.

### 8.3 Parquet export

`vmn-exp export-metrics <app> -v <ref>… [--keys] -o metrics.parquet` writes a long table
`(run, writer, key, step, ts, value)`. It needs `pip install "vmn-exp[parquet]"` (pyarrow) and
is never required to write or read runs. With this, DuckDB, Polars and pandas users get
their own tooling.

---

## 9. Existing data

There are no old clients, but stores may hold v1 records.

- Folded into the store migration, `vmn-exp migrate` ([14-store-layout.md](14-store-layout.md)
  §4): for each v1 run it moves the `metrics`
  entries from its JSONL into a `.vmx` per writer, rewrites the JSONL without them (atomic
  replace locally; on object stores, a new compacted log object superseding the old ones,
  the same mechanism as `compact_log_segments`), and bumps `format_version` to 2. It's
  idempotent and resumable (record by record; a record is v2 only once `metadata.yml` says
  so).
- Readers refuse v1 records with a clear message pointing at the command.
- Running runs are skipped (`running`/`stuck`). Finish them or wait, then migrate.

---

## 10. Implementation plan

TDD per CLAUDE.md. Pure codec code in exp-sdk with property tests; storage tests on local and
MinIO; UI tests through `TestClient`; scale checked with a new uiload profile.

### Phase 0 — inventory and codec

| Worktree | Tests first | Code |
|---|---|---|
| 0a inventory | a test that greps the packages for readers of `type == "metrics"` entries and fails on any not on the §5.5 allow-list (keeps the migration honest) | `tests/test_metric_consumers.py` |
| 0b block codec | round-trip property tests (random keys, sparse steps, step-less keys, NaN/±inf, empty blocks, 1M points); a torn tail or bad CRC is ignored; header summaries equal a brute-force fold | `S/core/metric_block.py` |
| 0c indexed codec | round-trip; footer read from the end; LOD buckets equal `SeriesThinner` buckets on the same data (D4); a range read of one level slice decodes alone | `S/core/metric_index_file.py` |

### Phase 1 — write path

| Worktree | Tests first | Code |
|---|---|---|
| 1a writer | the SDK, `vmn-exp run` ingestion, the importer and fork all produce streams; the JSONL has no `metrics` entries; `commit=False` and step semantics unchanged (existing tests green); `format_version: 2` | `S/core/metric_stream.py`, call sites |
| 1b storage | `append_metric_block`, segments on sync, `read_range`, `put_indexed` on local, S3 (MinIO), GCS (fake), Azure (Azurite); journal entries for each | backend halves |
| 1c finish compaction | the `.vmx` is built at finish; streams are deleted; a timeout leaves the stream readable; intermediate parts sealed at the threshold | `MetricWriter.finish`, `S/sdk/run.py` exit hooks |

### Phase 2 — read path

| Worktree | Tests first | Code |
|---|---|---|
| 2a reader | `points`/`thinned`/`keys` equal today's `metric_series` + thinning on the same logical data (golden comparison: generate a run, compute v1 output with the old code kept in the test, compare); multi-writer merge order; rewind on streams and on `.vmx` | `S/core/series_reader.py` |
| 2b fold + index | summaries from headers equal entry folds; index reads only headers of grown streams (byte-count spy); `SCHEMA_VERSION` bump | `S/core/fold.py`, `S/core/index_logs.py` |
| 2c consumers | each allow-listed consumer from 0a ported: SDK readers/frames, step-metric joins, sweeps median, compare, `merged_log_view` (show/RunLog output unchanged) | call sites |

### Phase 3 — UI and CLI

| Worktree | Tests first | Code |
|---|---|---|
| 3a API | range params; `metric-keys` paging; responses unchanged in shape; reads per request bounded (spy on `read_range` sizes) | `U/routes_series.py`, `U/readers/experiment_detail.py` |
| 3b webui | zoom refetch (debounced, coarse background kept); virtualized key picker; "not compacted" badge | `W/components/TrainingCurves.tsx`, `useAxisBrush.ts`, picker |
| 3c CLI | `compact`, `watch --compact`, `export-metrics` (skipped without pyarrow) | `vmn_exp/cli/compact.py`, `cli/export_metrics.py` |

### Phase 4 — migration and scale

| Worktree | Tests first | Code |
|---|---|---|
| 4a migrate | v1 → v2 is idempotent and resumable (kill mid-run, rerun); running runs skipped; readers refuse v1 with the hint | the metrics step of `vmn_exp/cli/migrate.py` (plan 14) |
| 4b uiload `bigseries` | profile: 50 runs × 1M steps × 50 keys, plus 1 run × 10k steps × 5000 keys, plus a 1000-run overlay. SLOs: series p95 ≤ 150 ms at 2000 points; zoom p95 ≤ 150 ms; run page first paint fetches ≤ 1 MB; overlay of 1000 runs ≤ 2 s | `tests/uiload/scenario.py`, `slo.py` |

### Benchmarks to record in the PR (local SSD and MinIO)

- Write overhead per `log_metrics` call ≤ today's.
- Decode 1M points of one key from `.vmx` raw chunks: < 50 ms.
- Fold of a 1M-step × 50-key finished run: < 50 ms (footer only).
- Size per point vs JSONL on the `bigseries` data.

After each phase: `/simplify`, docs (`docs/vmn-exp/experiments.md` storage format and
`compact`/`export-metrics`; `sdk.md` readers; `ui.md` range params and
`metric-keys`), CLAUDE.md, then the full suites once on master.

---

## 11. Decisions (agreed 2026-10-02)

1. **Metrics move out of the JSONL (D1).** No sidecar copy.
2. **v1 data is migrated** with `vmn-exp migrate` (plan 14 §4); readers have no v1 metric path.

Still open:
3. **float32 option** for very large runs (halves the value bytes). Recommended: not now;
   float64 is lossless.
4. **Histograms into the same format** later. Recommended: a follow-up once this lands.
