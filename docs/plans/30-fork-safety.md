# Plan 30: fork safety you can rely on (wishlist #10, answered and closed)

> fgm (app `fastglobalmacro`, plans 28 and 29) asked, as wishlist #10 (P3): *"A
> public fork-safety API, or confirmation that fork safety is solid."* Their code
> keeps about 60 lines of fork hooks that pause SDK threads through private
> attributes. They keep them because of past "exit-75" hangs in forked workers
> (`multiprocessing`, torch DataLoader, optuna `n_jobs`), where workers hung on exit.
>
> This plan answers them (§0), states the guarantee we will publish (§1), designs the
> changes that make it true (§2-§5), and lists the tests that back it (§6).
> Wishlist #2 (fast queries on big stores) is plan 29. This plan is the only fork-safety
> plan: it supersedes plan 29 §13 (F1-F5), whose content is merged here (§7 replaces
> that section with a pointer).
>
> Paths: `core/`, `storage/`, `sdk/` = `packages/vmn-exp-sdk/src/vmn_exp/…`;
> tests are in `packages/vmn-exp/tests/`.

Status: **proposal, revised after review** (2026-10-30). Code read at `eefb74e9`
(vmn_exp 0.1.27).

## 0. Answer for the client

**Short answer.** Since `vmn_exp_0.1.21` (commit `4cc0087a`, 2026-10-22) the SDK has
had a public fork-safety API, and it installs `os.register_at_fork` handlers itself.
That covers the *pause* half of what their hooks probably do. It does not yet cover
what a child does with inherited runs and storage (G3-G5, G8), and some threads are
ungated (G6). So: **keep the hooks for now.** Send us the hook code so we can check
what else it does (for example, stopping or no-op'ing inherited runs, which 0.1.21-0.1.27
do not do). Delete the hooks after upgrading to the release that ships W2, W3, W5 and W7
(§8). We cannot yet call fork safety "solid": this plan closes the gaps and adds tests
that back a written guarantee.

### 0.1 What is guaranteed today

The API (`sdk/fork_safety.py`, `sdk/background_gate.py`, exported in
`sdk/__init__.py:56-82`, documented in `docs/vmn-exp/sdk.md:874-907`):
- `vmn_exp.sdk.pause_background(timeout=None) -> bool`
- `vmn_exp.sdk.resume_background()`
- `vmn_exp.sdk.background_paused(timeout=None)` (a context manager)
- The same three methods on `Run`, `NoOpRun` and rank runs (`sdk/ranks.py:79-86`).

These are run-scoped: they pause the open runs' background workers, and SDK calls the
user makes while paused (logging, `log_artifact`, readers) keep working
(`sdk.md:886-907`).

Automatic handlers (`sdk/fork_safety.py:70-95`, registered when `sdk.run` is
imported, `sdk/run.py:65`):
- **Before a fork**, every *open* run's `BackgroundGate` is closed, and the handler
  waits for calls in flight with a 10 s total budget (`FORK_PAUSE_TIMEOUT_SEC`). Runs
  already inside `_close_attempt` are not open any more and are not waited for (G8).
- **After the fork**, the parent resumes the runs that thread paused.
- **In the child**, the gates, the log-buffer locks and `context._LOCK` are fresh, and
  `current_run()` is `None`.

The gate covers the heartbeat (publish, sysmetrics tick, log flush, `maybe_sync`),
`vmn-log-flush`, the `vmn-exp-sync`, `vmn-run-state` and output-upload `Coalescing`
workers, and the media uploader (`sdk/run.py:351-373,731-760`,
`sdk/log_buffer.py:58-64,111-118`, `sdk/state_publisher.py:60-61`,
`sdk/output_capture.py:83-86`). It does **not** cover the sysmetrics init thread
(`sdk/sysmetrics.py:322-324`), the output-capture pump threads
(`sdk/output_capture.py:52-58`), the alert sender, foreground calls on user threads, or
a run that is finishing. Their private hooks reach `run._gate`, `_heartbeat`,
`_log_buffer._flusher`, `_log_sync`, `_state_publisher._remote`, `_output._uploader`,
`_media_uploads` and `_sampler`; the SDK's gate covers all of those except `_sampler`'s
init thread.

Tests today: two subprocess scenarios in `test_sdk_fork_safety.py` (the fork waits for
a flusher write; the wait is bounded) and 12 gate unit tests in
`test_sdk_background_pause.py`. Children always leave via `os._exit`.

### 0.2 Gaps confirmed in the code

Each gap becomes a test in §6.

| # | Gap | Evidence | Effect |
|---|---|---|---|
| G1a | **Shared pooled sockets (any fork).** Even a fully quiesced fork leaves the parent's idle keep-alive TLS connections in the inherited urllib3 pool. A child using the inherited client (G5, or a reader on a cached storage) writes on the same TLS session as the parent. | `storage/s3_base.py:126` (one client per `S3Base`), `:132-137` (`copy.copy` area clones share it) | Corrupts the TLS stream in **both** processes: MAC errors, wrong responses, retries, possibly a hang. |
| G1b | **Locks held (forked through).** When the 10 s budget runs out, the fork goes ahead with the call still running (`_pause`'s result is ignored). The child inherits the pool lock, prefix-cap semaphores and C-level library state caught mid-call. | `sdk/fork_safety.py:70-73`, `storage/s3_prefix_cap.py:34,66` | The child hangs on a pool lock, on a semaphore slot it never gets back, or in OpenSSL/libc (§1 item 2). |
| G2 | Foreground S3 calls on user threads are not gated: `log_artifact`, reader or cleanup queries, `fanout` pools. | `storage/fanout.py:28-29,63`, `storage/listing.py:62` | Same as G1b, with no wait at all. |
| G3 | **Data damage and exit hang (raw fork only).** A raw `os.fork` child that leaves through `sys.exit`, a normal return, or `SystemExit` under `sigterm_exit='raise'` runs the atexit handlers `storage/buffered.close_all` and `storage/journal._flush_all`, which are not pid-filtered. The child ships the parent's buffered lines under the parent's stream owner, then `rmtree`s the parent's `vmn-log-buffer-<uuid>` directory, which both share. `_flush_all` also takes each `_JournalState.lock`, which a parent thread may have held at fork. `multiprocessing` fork workers do not hit this: `popen_fork._launch` calls `atexit._clear()` and leaves via `os._exit`, and SIGTERM re-delivers `SIG_DFL` (`sdk/signals.py:85-91`). | `storage/buffered.py:37-46,59-61,176-214`, `storage/journal.py:41,48-58,182-188` | A non-owner writes the stream (breaks owner-only-ships). The child hangs forever on the journal lock, or exits slowly (30 s read timeout × 5 retries per call over inherited TLS). The parent loses lines not yet shipped. |
| G4 | `Run.finish()`, `__exit__` and `_close_attempt` have no pid guard. | `sdk/run.py:422,526-535,593-605` | A raw-fork child that leaves a `with start_run():` block finalizes the parent's run. sdk.md says the opposite. |
| G5 | Recording on an inherited `Run` in a child writes synchronously to the parent's record (`LogBuffer.append` pid-mismatch path). | `sdk/log_buffer.py:49-54` | A second writer on the parent's stream, on the caller's thread, ungated, over the parent's sockets (G1a). |
| G6 | The alert sender (`vmn-alert`), the sysmetrics init thread (`nvmlInit`) and the output pump threads are not gated. | `core/alerts/dispatch.py:75-80`, `sdk/sysmetrics.py:309-337`, `sdk/output_capture.py:52-58` | A fork during `nvmlInit` leaves NVML/driver state half-built in the child: the same kind of hang as the DataLoader pynvml one in `test_fix_sysmetrics_fork.py`. |
| G7 | Module and per-instance locks, executors and queues are not reset in the child (full list in §2.7). | `storage/ship_state.py:35,40-54,176-182`, `storage/s3_prefix_cap.py:34-36`, `storage/s3_stats.py:44`, `core/background.py:31`, `core/index_load_pool.py:46-52`, `core/gc_pause.py:17-36` | Child readers block 30 s (`LOCK_WAIT_SEC`) then raise "held by a stuck thread"; `result()` on an inherited `ThreadPoolExecutor` at `max_workers` hangs forever (3.14 only clears `_threads_queues`, not `_threads`/`_idle_semaphore`); a fork during a bulk load leaves `gc` disabled for the child's whole life. |
| G8 | **A finishing run is not quiesced at fork.** `_close_attempt` calls `_gate.release()` first and `context.unregister(self)` in its `finally`. Only after that do `_close_remote_writers` (final state, log sync, output `Coalescing` uploads) and `compact_by` (S3 on the caller's thread) run. `_before_fork` lists only open runs. | `sdk/run.py:540,568,570-576`, `sdk/fork_safety.py:32-34` | A fork in that window goes ahead with no wait. Common: a sweep finishes trial N, then forks DataLoader workers for trial N+1. |

Also untested today: `multiprocessing`/`ProcessPoolExecutor`/DataLoader workers, real
S3 over HTTPS, the forked-through child, `subprocess` with `preexec_fn`, and the
output-capture pipe with workers.

### 0.3 Exit-75: what it probably was

Code 75 (`EX_TEMPFAIL`) appears nowhere in vmn-exp production code. Its only use is
this repo's hang sentinel (`test_sdk_fork_safety.py:64-67`). So the client's "exit
75" is their own watchdog code, probably copied from that harness. The real cause
depends on their version:
1. **Before 0.1.21** there were no at-fork handlers. A heartbeat or log-flush thread
   inside a boto3 call when a DataLoader or `multiprocessing` fork happens leaves the
   urllib3 pool lock or an SDK lock held in the worker. Workers hang, and the parent
   hangs on exit joining them. **Most likely.**
2. **Before the sysmetrics fix**, workers deadlocked importing `pynvml` because the
   init thread held its import lock. Fixed, but `nvmlInit` is still ungated (G6).
3. **On 0.1.21 or later**, G1a/G1b, G2, G6 and G8 can still hang a worker or corrupt
   a shared TLS session. G3 hangs or damages the parent's run only for raw `os.fork`
   children (or `sigterm_exit='raise'`), not `multiprocessing` workers.
4. **forkserver + output capture** (§4): workers forked from a forkserver started
   during a capturing run write into that run's capture pipe. After the parent's pump
   threads are gone, a worker's stdout flush fails with EPIPE and Python exits 120 at
   shutdown. Not 75, but a "workers die on exit" report.
5. **Plausible, unconfirmed:** a thread writing through `sys.stderr`'s buffered writer
   at fork (SDK threads log outside gated calls: `heartbeat.py:66`,
   `background.py:73`, `run.py:579`) leaves that io buffer lock held in the child.
   `logging` reinitialises its own handler locks at fork, not the stream's buffer
   lock. Test 6 checks it.

Optuna `n_jobs>1` uses threads, not forks (`integrations/optuna_study.py:18`), so it
is not a fork scenario by itself.

To pin it down, ask them for: their `vmn_exp` version; their hook code; their start
method (`multiprocessing.get_start_method()` and DataLoader's
`multiprocessing_context`); whether they use `capture_output`; `py-spy dump` of a hung
worker.

## 1. The guarantee we will publish (after this plan)

> On `os.fork()` (raw, `multiprocessing` "fork", `ProcessPoolExecutor` with the fork
> context, DataLoader fork workers, and `subprocess.Popen(preexec_fn=...)`, which runs
> the at-fork handlers too):
> 1. **Quiesce, bounded.** Before the fork, the SDK holds new SDK storage calls on
>    every thread (background *and* foreground, including runs that are finishing) and
>    waits for the calls in flight, up to `FORK_PAUSE_TIMEOUT_SEC` (10 s) in total. With
>    nothing in flight this costs microseconds. Streaming body reads after the response
>    headers are covered where the SDK reads the body itself (§2.2).
> 2. **The child never shares the parent's sockets or Python-level I/O state.** S3,
>    GCS and Azure clients, connection pools, prefix-cap semaphores, fan-out slots, SDK
>    module and instance locks, executors, record locks, SQLite connections and index
>    caches are rebuilt lazily in the child. **If the fork went through a call still in
>    flight** (the 10 s ran out), this is best-effort only: C-level process-global state
>    caught mid-call (OpenSSL 3 global/provider locks and DRBG during a handshake or
>    record write, the libc resolver during connect) comes along, and a fresh client's
>    first TLS handshake could still deadlock. So the parent warns, and the child refuses
>    SDK storage use (§2.3): `start_run()` returns a `NoOpRun` with one warning, and
>    readers raise `ForkedThroughError`. A clear error instead of a possible hang.
> 3. **The child never writes the parent's runs.** Inherited `Run` objects do nothing
>    in the child: recording calls are dropped with one warning, and
>    `finish`/`__exit__`/`release` do nothing. `current_run()` is `None`.
>    `start_run()` in the child makes a new inner run under the inherited
>    `VMN_EXPERIMENT_ID`, with its own owner, buffer and client.
> 4. **The child's exit never ships, deletes or waits on anything of the parent's**,
>    whether it exits via `os._exit`, `sys.exit`, a normal return or SIGTERM.
> 5. `spawn` and `forkserver` (the default since 3.14 on Linux; `spawn` on macOS)
>    start a **fresh interpreter**: no Python objects, threads or locks are inherited,
>    and items 1-4 do not apply. **stdio fds and the environment are inherited**: fds
>    1/2 are the run's capture pipe while `capture_output` is on, and
>    `VMN_EXPERIMENT_ID` auto-parents `start_run()` in the worker. A forkserver is
>    started once; every worker it forks later writes into whatever fds 1/2 were then
>    (§4).
>
> Not covered: C-level state in third-party libraries that a fork catches mid-call
> (CUDA itself, NCCL, OpenSSL/libc after a forked-through fork, your own threads). Use
> `spawn`/`forkserver` for CUDA workers, as PyTorch recommends.

## 2. Architecture

### 2.1 Child-reset registry: `core/fork_reset.py` (new, ~100 lines)
- Factories `fork_reset.lock()`, `rlock()`, `condition()`, `semaphore(n)`,
  `bounded_semaphore(n)`, `event()` return normal `threading` primitives and record
  them (weakly) with a reinit callback. Locks use `_at_fork_reinit()` (CPython
  3.9-3.15t; `threading` and `logging` use it). Semaphores rebuild `_cond` and restore
  their initial `_value`. Used for **module-level** state.
- `fork_reset.on_child(fn)` registers a module-state reset (`_caps.clear()`,
  `_PENDING.clear()`, `_SHARED` → graveyard, …).
- **Instances use one pattern, not the registry:** `fork_reset.PerProcess`, a small
  mixin that stamps `os.getpid()` at construction and calls the instance's
  `_rebuild_after_fork()` on first use from another pid (as `LogBuffer` does today).
  It rebuilds that instance's locks, conditions, queues and executors, and never joins
  or shuts down the inherited ones. Cheap: one `os.getpid()` per entry.
- One `os.register_at_fork(after_in_child=...)` runs the module resets in registration
  order. `ship_state._close_all_fds` and `autolog._ACTIVE.reset` move into it: one
  ordering point.
- Child hooks must be cheap and safe in a `preexec_fn` child, which runs them between
  fork and exec: no I/O, no logging, no imports, no allocation-heavy work. They only
  swap or clear objects.
- In `core/`, so `storage/` and `sdk/` may use it; it imports nothing from vmn-exp.
- `fork_safety` imports `concurrent.futures.thread` before calling
  `register_at_fork`. Before-fork handlers run LIFO, so `concurrent.futures`'
  `before=_global_shutdown_lock.acquire` must be registered first and therefore run
  after ours; otherwise it holds that lock while we wait, and an in-flight call that
  needs `executor.submit` (s3transfer parts, `fan_out`) stalls for the whole budget.
  Today `vmn_exp.sdk` happens to import it first; test 4 pins it.

### 2.2 Process-wide storage quiesce: `storage/fork_quiesce.py` (new, ~100 lines)
- A process-wide `CallGate`, a counting gate like `BackgroundGate`, closed **only by
  `fork_safety._before_fork`** (never by `pause_background`, §3).
- **In-flight counting per thread ident.** Entry is counted in the existing botocore
  `before-call` hook of `s3_prefix_cap.cap_prefixes`, so s3transfer's `upload_file`
  threads are covered. botocore emits `after-call-error` only for `Exception`, so a
  `KeyboardInterrupt`, or `SystemExit` from `sigterm_exit='raise'`, mid-call would leak
  the count (and, today, the prefix-cap slot). Two fixes together:
  1. The client that `S3Base._s3` returns is a thin proxy whose methods record the
     thread's depth on entry and restore it (and release any prefix-cap slot it took)
     in `finally`. `BaseException`s are delivered to the main thread, which always calls
     through the proxy; s3transfer pool threads do not get them.
  2. The fork wait treats idents of threads no longer alive (`threading._active`) as
     idle.
- **Body reads.** botocore's `after-call` fires before a `GetObject` body is read. The
  SDK helpers that read a body immediately (grep `["Body"]` in `storage/s3_*.py`) hold
  the gate across `get_object` + `read()`/`iter_chunks()`. A body left for the caller
  to stream is documented as not covered.
- **GCS and Azure** do not use botocore. The `object_client` adapter primitives
  `_get`/`_put`/`_iter`/`_upload`/`_download` enter the `CallGate` themselves (with
  `try/finally`), for both `storage/gcs.py` and `storage/azure.py`.
- Cost per call: one uncontended Condition acquire/release, twice, plus a dict update.
- `fork_safety._before_fork` closes the open runs' gates, the finishing runs' gates
  (§2.4) *and* the `CallGate` under one shared deadline, and keeps the result. If it
  forked through, the parent logs one WARNING (`fork waited 10.0s; 2 storage calls
  still in flight (vmn-exp-sync: PutObject …); the child will refuse SDK storage
  calls`) and bumps the `s3_stats` counter `forks_through`. It sets
  `fork_quiesce.FORKED_THROUGH = True` just before returning, so the child inherits it;
  the parent's `after` clears it and resumes. The child resets the gate but keeps the
  flag.
- A call the forking thread is itself inside does not block its own fork (exclusion by
  thread ident, as `BackgroundGate._wait_idle` does).

### 2.3 Per-process clients
- `storage/s3_base.py`: `self._s3` becomes a property. Clients are cached in a module
  table keyed by `(pid, endpoint_url)`, so every `copy.copy` area clone of a store
  shares one rebuilt client and pool per process, as they share one today. A pid change
  builds a new client with `boto3_client(endpoint_url)`. An injected client keeps the
  factory that built it; a bare injected client (tests) raises a clear error on pid
  mismatch instead of reusing the parent's.
- The child resets `boto3.DEFAULT_SESSION` (`sigv4_client`, `s3_base.py:57-69`, uses
  it), so the child never takes an inherited `RefreshableCredentials` refresh lock or
  shares its credential cache.
- Same for `gcs.py`, `object_client.py` and `azure.py` (`_container_client`,
  `_default_credential` and its token cache are per pid).
- **Forked-through child.** When `fork_quiesce.FORKED_THROUGH` is set, the per-pid
  client factory raises `ForkedThroughError` ("this process was forked while an SDK
  storage call was in flight; vmn-exp storage is disabled in it, use forkserver/spawn
  or a shorter call"). `start_run()` catches it and returns a `NoOpRun` with one
  warning, so a DataLoader worker keeps training. No env var to override it.
- Cost: one client build per child that touches storage, plus, with IRSA/web-identity
  or container credentials, one STS/IMDS round trip (§5, §9).

### 2.4 Inert inherited runs and finishing runs (`sdk/run.py`, `sdk/log_buffer.py`, `sdk/context.py`)
- `Run._in_owner()` (`os.getpid() == self.pid`) guards `finish`, `__exit__`,
  `_close_attempt`, `release`, `_append`, `log_*`, `alert` and `save/log_artifact`.
  In a child they return what a finished run returns and log one warning per run per
  process: `run 1.2.3-dev.x was opened by pid N; in a forked worker call start_run()
  to record`.
- `LogBuffer.append` drops the synchronous `os.getpid() != self._pid` write path. No
  compat shim: that path was a second-writer bug.
- **G8:** `context` keeps a `_CLOSING` set. `_close_attempt` moves the run there in its
  `finally` instead of dropping it, and the run leaves it only after
  `_close_remote_writers` returns. `_before_fork` pauses open *and* closing runs. A
  released gate admits new calls, but `pause()` still waits for its busy calls
  (`background_gate.py:83`), which is what the fork needs. `compact_by` and other
  caller-thread S3 calls in that window are covered by the `CallGate` (§2.2). The
  child clears `_CLOSING`.

### 2.5 Child hygiene in storage (`storage/buffered.py`, `storage/journal.py`)
- `BufferedRemoteStorage` remembers its pid. A `fork_reset.on_child` hook clears
  `_PENDING` and marks each inherited instance `_inherited`: it forgets
  `_flushed_at`/`_metrics_flushed_at`/`_unshipped` without shipping, and gets a **new**
  `_buffer_root` and `_owner` for any writes the child makes. It never `rmtree`s the
  parent's directory. `close_all` skips instances of another pid.
- **Journal.** Each `JournaledStorage` holds its `_JournalState` directly
  (`journal.py:154`), so clearing `_STATES` alone would not detach inherited storages.
  `_JournalState` stamps its creating pid. On a pid mismatch, `JournaledStorage` swaps
  in a fresh state (same sink, empty pending list, new lock, new `threading.local`)
  without flushing, so a child writing through an inherited storage (a cleanup tool's
  storage, an `index_point`/shared store) never takes a lock a parent thread held at
  fork. `_flush_all` skips states of another pid.

### 2.6 Remaining ungated threads (`core/alerts/dispatch.py`, `sdk/sysmetrics.py`, `sdk/output_capture.py`)
- `send_async` runs `send` through the owning run's gate (`gate.wrap`). An alert with
  no run uses the process `CallGate` (its HTTP calls are not S3).
- In the sysmetrics init thread, only the `build_collector()` call (`nvmlInit`) runs
  inside the run's gate. The priming `time.sleep(MIN_SAMPLE_INTERVAL_SEC)` after it
  (`sysmetrics.py:326-337`) stays outside, so a fork during startup does not wait for
  the sleep. Optional imports stay on the calling thread (existing fix).
- The output pump threads only `read`/`write` fds and append to a buffer. They are not
  gated, but their buffer lock is `PerProcess` (§2.7), and the child never runs them.

### 2.7 Locks, executors and readers (module and instance state)
**Module state** (`fork_reset` factories or `on_child`):
- `fanout._SLOTS`/`_REQUEST_SLOTS`, `s3_prefix_cap._lock`/`_caps`, `s3_stats._lock`,
  `ship_state._THREAD_LOCKS_GUARD` (and `_THREAD_LOCKS`, `_DEPTH` cleared).
- `run_hint._LOCK`, `index_derive._LOCKS_LOCK`, `best_effort._warned_lock`,
  `similar._MEMO_LOCK`, `metric_compact._SEAL_LOCK`, `store_marker._lock`,
  `usage._USED_LOCK`, `registry/view._RUN_MODELS_LOCK`, the `ship_state._FINALIZING`
  `Event` (fresh, cleared).
- `gc_pause._LOCK`/`_depth`: the child hook resets `_depth = 0` and, if the parent had
  paused collection (`_depth > 0` with `_resume` set), calls `gc.enable()`.
- The network-FS `FileLock` path keeps no state across holds and needs no change.

**Instance state** (`PerProcess`):
- `core/background.Coalescing._cond` (and its worker: the child never inherits the
  thread, so the instance is idle until rebuilt); `sdk/media_uploads.MediaUploads`
  `_lock` and `queue.Queue`; `Heartbeat._stop`; `OutputArtifact._upload_lock`;
  `core/index_load_pool.LoadPool` `_lock` and its persistent `ThreadPoolExecutor` (a
  fresh executor; the inherited one is dropped, never `shutdown()`); `s3_prefix_cap
  ._PrefixCap.slots`; `_JournalState.lock` (§2.5); the `sqlite_conn` `_Connection
  .tx_lock`. Most of these belong to inherited runs that W2 makes inert; the reset
  keeps any path that still reaches them from hanging.

**SQLite and index caches** (`core/index.py`, `core/index_point.py`,
`core/index_store_conn.py`, `core/sqlite_conn.py`):
- `_SHARED`, `_STORES` and the similar-corpus caches move their entries into a module
  **graveyard** list in the child, which the child never frees. Clearing them instead
  would drop the last reference and `IndexStoreConn.__del__` (`index_store_conn.py:
  155-158`) would close the inherited connections.
- Why not close: not because of the parent's locks (POSIX `fcntl` locks belong to the
  process and are not inherited, so a child close cannot release the parent's). The
  hazard is SQLite's process-global unix-VFS inode and shm bookkeeping, which *is*
  inherited. Closing an inherited connection updates that bookkeeping for a connection
  the child does not really own. Opening a **new** connection in the child to a file
  the parent had open can find inherited lock counts and skip taking real locks. So
  the child must not trust the inherited VFS state either way.
- Proposed: a child that needs the index reads it read-only through a fresh connection
  opened by a short-lived `subprocess` helper if the test below shows the in-process
  path is unsafe; otherwise opens it read-only in-process. In both cases a forked child
  never calls `IndexStoreConn.recover()` (`index_store_conn.py:120-139`), which flips
  the live index generation the parent or the UI server uses: `sqlite_conn` records the
  opening pid, refuses use of a connection from another pid, and `recover()` refuses in
  a process whose pid differs from the one that imported `index_store_conn`. All of it
  stays in `core/sqlite_conn.py`. Verdict on the in-process path: **PLAUSIBLE** until
  test 8 runs.

### 2.8 A ratchet so it does not come back
`test_fork_reset_coverage.py`, two halves:
1. **Module globals.** Import every `vmn_exp` module of the `vmn-exp-sdk` package and
   fail on any `threading.Lock`, `RLock`, `Semaphore`, `Condition`, `Event`,
   `queue.Queue` or `ThreadPoolExecutor` global that `fork_reset` does not know.
2. **Instances.** In a subprocess, run a representative workload (start a run with
   sysmetrics, output capture and media; log; query a reader; build an index; finish),
   then walk `gc.get_objects()` for objects of `vmn_exp`-owned classes whose
   attributes hold those primitives or executors, and fail on any class that is not
   `PerProcess` or allowlisted.
A small allowlist with reasons covers the exceptions.

## 3. Public API (final)
- **No new functions.** `pause_background`, `resume_background`, `background_paused`
  (module-level and per run) stay **run-scoped, as today**: they pause the open runs'
  background workers, and SDK storage calls the caller makes inside a paused block
  (`log_artifact`, a reader query, `start_run`, `similar()`) still work. They do
  **not** close the process-wide `CallGate`; only `_before_fork` does. (Closing it from
  `pause_background` would hold a thread's own new calls forever under the default
  `timeout=None`.) A regression test asserts that SDK storage calls inside
  `with background_paused():` complete.
- `vmn_exp.sdk.fork_safety.FORK_PAUSE_TIMEOUT_SEC` stays a documented module constant.
  **No env var** (this replaces plan 29 F4's `VMN_EXP_FORK_PAUSE_SEC`): the child no
  longer depends on the wait except when forked through, which the warning and the
  child's `ForkedThroughError` make visible; tuning would only trade fork latency.
- `vmn_exp.sdk.ForkedThroughError` is the one new exported name (an exception, §2.3).
- The §1 contract is the "confirmation" the client asked for.

### What the client's ~60 lines become
- **Until the release that ships W2, W3, W5 and W7: keep them.** Send us the code; if
  it also no-ops inherited runs or stops threads the SDK does not gate, it is doing
  work 0.1.21-0.1.27 do not.
- **After upgrading to that release: delete them.** Nothing to call.
- To log whether background work was idle before a hand-managed fork pool:
  ```python
  from vmn_exp.sdk import background_paused
  with background_paused(timeout=10) as quiesced:
      pool = multiprocessing.get_context("fork").Pool(8)
  ```
  The fork handlers still do the process-wide wait inside it.
- For CUDA DataLoader workers use `multiprocessing_context="forkserver"` (or `spawn`).
  Workers inherit no Python state, and `start_run()` in them makes inner runs. With
  `capture_output`, see §4.

## 4. Failure modes after the change
- **Hung S3 call at fork:** the fork waits at most 10 s and warns. The child gets
  `ForkedThroughError` on SDK storage use (`start_run()` returns a `NoOpRun`) rather
  than risking a handshake through inherited OpenSSL state. No hang from vmn-exp's side.
- **Non-persistent DataLoader workers re-forking each epoch during a long call:** each
  fork waits up to 10 s and logs it. Fix: `persistent_workers=True` or forkserver.
- **Fork right after `finish()`:** waits for the final state, log and output uploads and
  `compact_by` (G8), within the same budget.
- **Child calls `start_run()`:** own client, buffer, owner and journal state.
- **Child is SIGTERMed:** the inherited handler finalizes only the child's runs
  (`_finalize_open_runs` filters by pid, `sdk/run.py:755-787`, `sdk/context.py:35-50`).
- **`subprocess.Popen(preexec_fn=...)`:** runs the at-fork handlers, so it waits like
  a fork (up to 10 s if a call is in flight) and runs the child resets before exec;
  those are cheap swaps (§2.1). vmn-exp itself never uses `preexec_fn`, `os.fork` or
  `multiprocessing` (its helpers `core/index_workers.py`, `core/index_io_process.py`
  start fresh interpreters through `subprocess`).
- **Output capture with fork workers holding the pipe:** `stop()` waits at most 2 s, as
  today (`sdk/output_capture.py:45-71`). Worker prints land in the parent's
  `output.log`; intended, now documented.
- **forkserver/spawn + `capture_output`:** a worker inherits fds 1/2. A forkserver
  started while a run captures keeps that run's pipe as its stdio, so workers it forks
  for *later* runs write into the old run's pipe. Once the parent's pump threads are
  gone (parent exit, or after `stop()` gives up), worker writes get EPIPE and the
  worker exits 120 at shutdown when flushing stdout fails. Documented: start the
  forkserver before `start_run()` (`multiprocessing.get_context("forkserver")` with a
  first `Pool`) or set `capture_output=False` for runs that use worker pools. A code
  fix (the pump keeps draining until the process exits) is a follow-up if test 6 shows
  it matters.
- **A thread mid-write to `sys.stderr` at fork (PLAUSIBLE):** the child could block on
  the io buffer lock on its first write. Not fixable from Python; test 6 measures it,
  and if confirmed the SDK's background loggers move to a handler that writes with
  `os.write` (no buffered-writer lock).
- **`_at_fork_reinit` missing on a future CPython:** the factory rebuilds the primitive
  and swaps the module global; the ratchet catches it on each tested Python.

## 5. Performance
Fork safety does not depend on store size. Targets:
- Fork with nothing in flight: ≤ 1 ms added with 10 open runs.
- Gated S3 call: ≤ 5 µs added (serial microbenchmark).
- Child's first S3 call: one boto3 client build (~30-80 ms) per `(pid, endpoint)`,
  only in children that touch storage. With IRSA/web-identity or container credentials,
  add one STS/IMDS round trip per child (often 50-300 ms; STS throttles
  `AssumeRoleWithWebIdentity` per account). DataLoader-style re-forking that records
  from workers at scale should use persistent workers or forkserver.
- 667k or 10M runs: no change. Index caches are dropped (graveyarded) in the child,
  so a child reader opens the on-disk index (a warm file) and never inherits the
  parent's in-memory one. That matters for plan 29's shared index.

## 6. Test plan (TDD: each test written red before its worktree's code)
Each scenario runs in its own interpreter (the `_PRELUDE` pattern of
`test_sdk_fork_safety.py`) with a hard timeout and the hang sentinel. `s3_helpers.py`
uses in-process `mock_aws`, which opens no sockets, pool or TLS, so it cannot reproduce
pool or socket hangs. S3 scenarios that need real sockets (3, 6) use
`moto.server.ThreadedMotoServer` (`moto[s3,server]` is already in
`test_requirements.txt`; `uiload/s3bench_moto.py` is an HTTP moto server to reuse),
over HTTPS: a test helper fronts it with a TLS listener using a self-signed cert, and
the client trusts that cert.

| # | Test file | Scenario → assertion | Gaps |
|---|---|---|---|
| 1 | `test_sdk_fork_child_inert.py` | Raw-fork child leaves `with start_run()`, calls `finish()` and `log_metrics()` → parent's state, log and streams unchanged; one warning; parent finishes normally | G4, G5 |
| 2 | `test_storage_fork_exit.py` | Raw-fork child with buffered lines exits via `sys.exit(0)`, return, `os._exit`, SIGTERM with `sigterm_exit='raise'` → exits < 1 s, no remote PUT, parent buffer dir intact, parent ships each line exactly once. Journal case: a parent thread holds `_JournalState.lock` at fork; the child writes through the inherited `JournaledStorage` and exits normally → no hang. `multiprocessing` fork and default-SIGTERM variants kept as regression checks | G3 |
| 3 | `test_fork_forked_through.py` | HTTPS moto PUT blocked past the budget (patched to 0.3 s) on (a) flusher, (b) user-thread `log_artifact`, (c) `fanout` pool → one parent warning; `forks_through == 1`; the child's reader raises `ForkedThroughError` and its `start_run()` returns a `NoOpRun`, all < 2 s. Quiesced fork with idle keep-alive sockets in the pool → the child's fresh client opens new connections (server sees a new TLS session) and the parent's next call succeeds | G1a, G1b, G2 |
| 4 | `test_fork_quiesce_foreground.py` | Fork waits for a foreground call, holds new calls during the fork, resumes them; own-thread exclusion holds; a `KeyboardInterrupt` raised mid-call leaves no count (next fork does not wait); a dead thread's count is ignored; GCS/Azure adapter primitives are gated; the at-fork handler order puts `concurrent.futures`' lock after ours; SDK storage calls inside `with background_paused():` complete | G2 |
| 5 | `test_fork_ungated_threads.py` | Fork during a slow fake `nvmlInit` waits, but not for the priming sleep; fork during an alert send waits | G6 |
| 6 | `test_fork_pools.py` | `get_context("fork").Pool(4)`, `ProcessPoolExecutor(mp_context=fork)`, DataLoader-like loop (8 workers × 20 epochs re-forking while heartbeat, sync and media upload hit HTTPS moto); workers see `current_run() is None` and `start_run()` makes inner runs → no hang, parent `succeeded`, inner runs complete. forkserver and spawn variants with `capture_output` on, where workers print after the parent run finished. A stderr variant: a parent thread logs in a tight loop while workers fork and write to stderr. `subprocess.Popen(preexec_fn=...)` during a heartbeat | all |
| 7 | `test_fork_reset_coverage.py` | The §2.8 ratchet, both halves | G7 |
| 8 | `test_sqlite_conn_fork.py` | Adversarial: the parent holds a read transaction on the index; a third process writes and checkpoints; the child opens fresh and reads → consistent data, no corruption, no lock skipped (the third process's next checkpoint sees the child's reader). The parent's connection used from the child raises; `recover()` in the child refuses | G7 |
| 9 | (3 and 6 under 3.14t/3.15t) | Plan 26's Linux harness. **Blocked on plan 26 F0** (`uiload/ft_bench.py` does not exist yet) | — |
| 10 | serial microbenchmarks | §5 fork-overhead and gated-call budgets (`@pytest.mark.serial`) | — |
| 11 | `test_sdk_fork_finishing_run.py` | Fork during `finish()` with the final state PUT blocked → the fork waits for it (within budget); `compact_by` in flight is waited for | G8 |

## 7. Docs
- `docs/vmn-exp/sdk.md`, Forks and Fork safety sections (today `:860-907`): replace
  with the §1 contract, a start-method table (fork / forkserver / spawn, with what each
  inherits: stdio and env always), the forkserver + `capture_output` note,
  `preexec_fn`, `ForkedThroughError`, the "keep, then delete" note, the DataLoader
  recommendation and the exit-75 note. Correct today's claim that a child never
  finalizes the parent's run (true only once G4 is fixed), and drop the "alerts and
  sysmetrics init are not gated" caveat once W7 lands.
- `docs/vmn-exp/client-guide.md`: a three-line pointer under in-job SDK.
- `docs/plans/README.md`: a row for this plan.
- `docs/plans/29-shared-query-index.md`: replace §13 with one line ("Wishlist #10 is
  plan 30") and change line 14 ("#10 is planned in §13") to point to plan 30. Plan
  29's F1-F5 are merged here: F1 = W2, F2 = W3, F3 = W1b/W4, F4 = §2.3's forked-through
  child (without its env var), F5 = W7.
- Fork-with-threads `DeprecationWarning`: Python raises it on every build since 3.12
  (not only free-threaded); docs say so and how to filter it.

## 8. Work breakdown (worktrees, ~200-300 lines each, tests first)
1. **W1 fork_reset core**: `core/fork_reset.py` (factories, `on_child`, `PerProcess`),
   move `ship_state`/`autolog` hooks in, `concurrent.futures.thread` import order,
   ratchet half 1 (7) with a temporary allowlist. Blocks W1b, W3, W4, W6.
2. **W1b instance resets**: `PerProcess` on `Coalescing`, `MediaUploads`, `Heartbeat`,
   `OutputArtifact`, `LoadPool`, `_PrefixCap`; the §2.7 module list; `gc_pause` child
   reset; ratchet half 2. Needs W1.
3. **W2 inert inherited runs**: pid guards in `sdk/run.py`, `sdk/log_buffer.py`;
   test 1. Independent.
4. **W3 storage child hygiene**: `buffered.py`, `journal.py` (pid-stamped state);
   test 2. Needs W1.
5. **W4 per-pid clients and module locks**: `s3_base.py` (`(pid, endpoint)` client
   table, `DEFAULT_SESSION` reset), `gcs.py`, `azure.py`, `object_client.py`,
   `s3_prefix_cap.py`, `s3_stats.py`, `fanout.py`, `ship_state.py`; the HTTPS moto
   helper; test 3's quiesced-fork half. Needs W1.
6. **W5 process-wide quiesce**: `storage/fork_quiesce.py`, the hook + proxy counting,
   body-read gating, `object_client` primitives (gcs and azure), the shared deadline,
   the closing-runs set (`context._CLOSING`, G8), warning, counter, `FORKED_THROUGH`
   and `ForkedThroughError`; tests 3, 4 and 11. Needs W4.
7. **W6 readers and SQLite**: `index.py`, `index_point.py`, `index_store_conn.py`,
   `similar_corpus.py`, `sqlite_conn.py`; test 8. Needs W1. **Sequence after plan 29's
   index-cache changes** (same `_SHARED`/`_STORES`).
8. **W7 ungated threads**: `alerts/dispatch.py`, `sysmetrics.py` (gate only
   `build_collector`); test 5. Independent.
9. **W8 integration and docs**: tests 6, 10 (9 once plan 26 F0 exists); sdk.md,
   client-guide, plan 29 §13 pointer; remove the ratchet allowlist; then /simplify.

**Rollout:** one vmn-exp release. Release notes: the fork-safety contract now holds;
private-attribute hooks can be deleted after upgrading; inherited `Run`s are inert in
children, and a forked-through child refuses SDK storage (behaviour changes, see
risks).

## 9. Risks
- `_at_fork_reinit` is private CPython; a 3.15t/3.16 change could break lock reinit.
  Mitigation: rebuild-and-swap fallback plus the ratchet on each supported Python.
- Inert inherited Runs change behaviour: a child that called `run.log_metrics` on the
  parent's Run used to write (wrongly) into the parent's stream; now it drops with a
  warning. The client may rely on it; release notes must say so.
- A forked-through child now gets `ForkedThroughError` / a `NoOpRun` where it used to
  try (and maybe hang). Rare (a call stuck ≥ 10 s at fork), loud, and the parent's
  warning names the call.
- The process `CallGate` adds lock traffic to every S3 call, including the UI server's
  index refresher on free-threaded 3.15. Check with the serial microbenchmark and plan
  26's harness before merging.
- Per-pid client rebuild adds ~30-80 ms to a child's first storage call, plus an
  STS/IMDS round trip with web-identity or container credentials; many re-forking
  workers that each record can hit STS throttling. Persistent workers or forkserver
  avoid it.
- Graveyarded inherited SQLite connections and caches leak fds and memory per child.
  Bounded per child, since children are short-lived; a long-lived forked child that
  re-forks pays it once per generation.
- Gating `nvmlInit` and alert sends lets a slow driver or webhook delay a fork by up to
  10 s; visible through the warning, but may surprise users who fork often.
- Python raises a fork-with-threads `DeprecationWarning` on all builds since 3.12;
  under `-W error` that becomes an error. The SDK cannot fix it; docs must say so.
- C-level library state after a forked-through fork stays outside the guarantee
  (§1 item 2); the child's refusal is the mitigation.

## 10. Open questions
1. Which `vmn_exp` version does fgm run, and what do their ~60 lines do beyond pausing?
   Before 0.1.21 explains the private hooks and cause 1 of §0.3.
2. Their start method: Python 3.14+ defaults to forkserver on Linux, and torch's
   DataLoader default on their version is unverified. If their workers never fork, the
   cause is elsewhere (forkserver + `capture_output`, §0.3 item 4; their own threads;
   CUDA); a `py-spy dump` decides it.
3. Are their jobs free-threaded too, or only the UI server? It decides whether test 9
   is a gate for them.
4. Not yet traced: whether `OutputArtifact.write`, `append_metric_entries` or
   `CachedSnapshotStorage.append_log_entries` make synchronous remote calls in a child
   beyond the buffered eager ship. W2's guards make it moot for inherited runs; W3
   should confirm.
5. Do the installed boto3/urllib3 register their own at-fork pool resets? Assumed not;
   §2.3 makes the answer irrelevant for Python state.
6. Forked-through child: `NoOpRun` from `start_run()` plus `ForkedThroughError` from
   readers (proposed), or a warning and best-effort fresh clients? Decide with the
   client's answer to question 2.

Closed: `vmn-exp run`'s child launch path and the `vmn_exp.ui` server use no
`os.fork`, `multiprocessing` or `preexec_fn` (grep over `packages/vmn-exp-sdk/src` and
`packages/vmn-exp/src`); their helpers start fresh interpreters through `subprocess`.
