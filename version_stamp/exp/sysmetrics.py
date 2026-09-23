#!/usr/bin/env python3
"""Sampling a run's own resource usage, as ordinary metrics.

A heartbeat answers "is this process alive". It cannot answer "is it getting
anywhere" — a run wedged on a lock keeps beating and reads ``running`` forever.
CPU flat at zero for an hour is the signal that closes that gap, so the samples
are recorded as plain metrics and inherit the charts, series, sorting and schema
the metrics path already has.

Three things are deliberate:

* **the target is a process tree, not this process.** ``vmn exp run``'s workload
  is the child it supervises (and that child's own workers); vmn's poll loop is
  idle by construction, so sampling it would report exactly the flat zero this
  feature exists to make meaningful. An SDK run passes no pid and gets itself.
* **names carry an underscore, not a dot.** ``row["metrics"]`` is a flat fold of
  every ``values`` dict (``core.experiment_log.latest_metrics``), and the query
  language resolves ``metrics.<key>`` as a two-part path, so a nested
  ``sys.cpu_percent`` would name nothing. ``autolog`` keys the same way.
* **nothing here is a hard dependency.** ``psutil`` and ``pynvml`` are imported
  lazily and independently; whichever is missing contributes no metrics, and
  with neither installed sampling is a *silent* no-op — it runs once per
  heartbeat, so a warning per tick would be worse than no metrics at all.
"""
import importlib
import logging
import os
import time

# Stdlib logging, not VMN_LOGGER: this is reached from the SDK too, which never
# calls init_stamp_logger.
_LOGGER = logging.getLogger(__name__)

CPU_PERCENT = "sys_cpu_percent"
# Resident memory of the tree: the root's RSS plus each child's *unique* memory,
# so forked workers sharing the parent's pages are not counted N times.
RSS_MB = "sys_rss_mb"
# GPU memory held by this run's process tree (per-process NVML accounting).
GPU_MEM_MB = "sys_gpu_mem_mb"
# Node-level figures over the visible devices, whoever is using them.
GPU_NODE_MEM_MB = "sys_gpu_node_mem_mb"
GPU_NODE_UTIL_PERCENT = "sys_gpu_node_util_percent"

SYS_METRIC_NAMES = (
    CPU_PERCENT,
    RSS_MB,
    GPU_MEM_MB,
    GPU_NODE_MEM_MB,
    GPU_NODE_UTIL_PERCENT,
)

# psutil's cpu_percent() over a (near-)zero interval reads 0.0 on Linux, so a
# sample never follows the previous one sooner than this.
MIN_SAMPLE_INTERVAL_SEC = 0.1

_MB = float(1024 * 1024)


def _import_optional(name):
    """Import *name* or return None. The single seam tests use to fake absence."""
    try:
        return importlib.import_module(name)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Probes: each is a callable returning a metrics dict, or None when unavailable
# ---------------------------------------------------------------------------


class _ProcessProbe:
    """Summed CPU percent and memory (without shared-page double counting)
    over a process and its children.

    The tree, not one process: ``bash train.sh`` puts the real consumer one level
    down and a dataloader puts it two. The ``psutil.Process`` objects are held
    between samples because ``cpu_percent()`` reports usage since *that
    instance's* previous call — a fresh object every tick would read 0.0 forever.
    """

    def __init__(self, root):
        self._root = root
        self._tracked = {root.pid: root}
        # Prime every process's CPU interval; a first reading is always 0.0.
        for proc in self._tree()[0]:
            self._read_cpu(proc)
        self._last_mono = time.monotonic()
        self._last_wall = time.time()

    def pids(self):
        """The pids sampled last tick — the run's process tree."""
        return set(self._tracked)

    def _tree(self):
        """This tick's processes (reusing held objects) and the newly seen pids."""
        found = [self._root]
        try:
            found.extend(self._root.children(recursive=True))
        except Exception:
            # The root exited, or we lost the right to look.
            _LOGGER.debug("Could not enumerate child processes", exc_info=True)
            found = list(self._tracked.values())

        new = {p.pid for p in found} - set(self._tracked)
        # Rebuilt rather than pruned, so a finished worker stops being sampled.
        self._tracked = {p.pid: self._tracked.get(p.pid, p) for p in found}
        return list(self._tracked.values()), new

    @staticmethod
    def _read_cpu(proc):
        try:
            return proc.cpu_percent(None)
        except Exception:
            return 0.0

    def _newborn_cpu(self, proc, elapsed):
        """CPU percent of a process first seen this tick.

        Its ``cpu_percent()`` has no previous call to measure from and reads 0.0,
        which under-counts dataloader workers respawned every epoch. One born
        since the last sample spent all its CPU time inside this interval.
        """
        self._read_cpu(proc)  # prime it for the next tick
        try:
            if elapsed <= 0 or proc.create_time() < self._last_wall:
                return 0.0
            times = proc.cpu_times()
            return 100.0 * (times.user + times.system) / elapsed
        except Exception:
            return 0.0

    def _memory(self, proc):
        """The root's RSS; a child's unique set size, falling back to its RSS."""
        if proc is not self._root:
            try:
                return proc.memory_full_info().uss
            except Exception:
                pass
        return proc.memory_info().rss

    def __call__(self):
        wait = MIN_SAMPLE_INTERVAL_SEC - (time.monotonic() - self._last_mono)
        if wait > 0:
            time.sleep(wait)  # at most once, right after the probe was built
        procs, new = self._tree()
        elapsed = time.monotonic() - self._last_mono
        cpu = 0.0
        memory = 0
        for proc in procs:
            try:
                with proc.oneshot():  # one read per process, not several
                    if proc.pid in new:
                        cpu += self._newborn_cpu(proc, elapsed)
                    else:
                        cpu += proc.cpu_percent(None)
                    memory += self._memory(proc)
            except Exception:
                continue  # exited between listing and reading: normal
        self._last_mono, self._last_wall = time.monotonic(), time.time()
        return {CPU_PERCENT: round(cpu, 1), RSS_MB: round(memory / _MB, 1)}


def _process_probe(pid=None):
    """A probe for *pid*'s tree, or this process's when *pid* is None."""
    psutil = _import_optional("psutil")
    if psutil is None:
        return None
    try:
        return _ProcessProbe(psutil.Process(pid or os.getpid()))
    except Exception:
        _LOGGER.debug("psutil is installed but unusable here", exc_info=True)
        return None


def _visible_handles(pynvml):
    """NVML handles of the devices ``CUDA_VISIBLE_DEVICES`` exposes to the run.

    NVML enumerates every physical device on the node; CUDA only the listed
    ones — by index or by (a unique prefix of) UUID, stopping at the first
    invalid index. Unset means all; empty means none.
    """
    count = pynvml.nvmlDeviceGetCount()
    handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
    raw = os.environ.get("CUDA_VISIBLE_DEVICES")
    if raw is None:
        return handles
    visible = []
    for token in (t.strip() for t in raw.split(",")):
        if not token:
            continue
        if token.lstrip("-").isdigit():
            index = int(token)
            if index < 0 or index >= count:
                break
            visible.append(handles[index])
            continue
        match = [h for h in handles if _uuid(pynvml, h).startswith(token)]
        if len(match) != 1:
            break
        visible.append(match[0])
    return visible


def _uuid(pynvml, handle):
    try:
        uuid = pynvml.nvmlDeviceGetUUID(handle)
    except Exception:
        return ""
    return uuid.decode() if isinstance(uuid, bytes) else str(uuid)


def _gpu_probe(pids=None):
    """GPU memory of the run's processes, plus node memory and utilization.

    *pids* returns the run's process tree each tick. Every NVML query is guarded
    on its own, so a query a device does not support (utilization on MIG, say)
    costs that value, not the whole sample.
    """
    pynvml = _import_optional("pynvml")
    if pynvml is None:
        return None

    try:
        pynvml.nvmlInit()
        # Handles are stable for the process's lifetime, so resolve them once
        # instead of per device per tick.
        handles = _visible_handles(pynvml)
    except Exception:
        # No driver, no device, a container without /dev/nvidia*: all normal.
        _LOGGER.debug("pynvml is installed but no GPU is reachable", exc_info=True)
        return None
    if not handles:
        return None

    def probe():
        tree = pids() if pids else set()
        used, util, owned = [], [], []
        for h in handles:
            _collect(used, lambda h=h: pynvml.nvmlDeviceGetMemoryInfo(h).used)
            _collect(util, lambda h=h: pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
            _collect(owned, lambda h=h: _tree_gpu_memory(pynvml, h, tree))
        values = {}
        if used:
            values[GPU_NODE_MEM_MB] = round(sum(used) / _MB, 1)
        if util:
            values[GPU_NODE_UTIL_PERCENT] = round(float(sum(util)) / len(util), 1)
        owned = [o for o in owned if o is not None]
        if owned:
            values[GPU_MEM_MB] = round(sum(owned) / _MB, 1)
        return values

    return probe


def _collect(into, query):
    try:
        into.append(query())
    except Exception:
        _LOGGER.debug("An NVML query failed", exc_info=True)


def _tree_gpu_memory(pynvml, handle, tree):
    """Bytes the run's processes hold on *handle*, or None if none is listed.

    None rather than 0 when nothing matches: inside a container NVML reports
    host pids, and "unknown" must not read as "uses no GPU memory".
    """
    matched = [
        p.usedGpuMemory or 0
        for p in pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        if p.pid in tree
    ]
    return sum(matched) if matched else None


def build_collector(pid=None):
    """A callable returning ``{name: number}``, or None if nothing can be read.

    *pid* is the process to measure, together with its children; None means this
    process. Degrades per probe rather than all-or-nothing, so a host with
    psutil and no GPU reports CPU and RSS alone.
    """
    process = _process_probe(pid)
    root = pid or os.getpid()
    gpu = _gpu_probe(process.pids if process is not None else (lambda: {root}))
    probes = [p for p in (process, gpu) if p is not None]
    if not probes:
        return None

    def collect():
        values = {}
        for probe in probes:
            try:
                values.update(probe())
            except Exception:
                # A device can disappear mid-run. Report what still answers.
                _LOGGER.debug("A system-metrics probe failed", exc_info=True)
        return values

    return collect


# ---------------------------------------------------------------------------
# The tick the callers drive
# ---------------------------------------------------------------------------


class Sampler:
    """Records one metrics entry per :meth:`tick`, and never raises.

    Callers tick from a timer they already own — ``vmn exp run``'s poll loop and
    the SDK's :class:`~version_stamp.exp.heartbeat.Heartbeat` thread — so the
    cadence is the heartbeat's and no second thread leaks. (Should those two ever
    share one heartbeat mechanism, ticking belongs inside it.)

    Args:
        record: called with a ``{name: number}`` mapping to persist a sample.
        enabled: False makes every tick a no-op, which is the default for a run
            that did not ask for system metrics.
        pid: the process to measure, with its children; None means this process.
        collector: an explicit collector, bypassing :func:`build_collector`.
    """

    def __init__(self, record, enabled, pid=None, collector=None):
        self._record = record
        self._enabled = enabled
        self._pid = pid
        self._collector = collector

    def tick(self):
        if not self._enabled:
            return
        if self._collector is None:
            # Built on the first tick, not in __init__: importing psutil and
            # calling nvmlInit() can take seconds on a host with a sulking
            # driver, and neither belongs on a caller's start_run() path.
            self._collector = build_collector(self._pid)
            if self._collector is None:
                self._enabled = False  # nothing to read; stop trying, stay quiet
                return
        try:
            values = self._collector()
            if values:
                self._record(values)
        except Exception:
            # Sampling is an observation of the run, never a part of it: a bad
            # probe or a failed append must not end the run or the heartbeat.
            _LOGGER.debug("System-metrics sampling failed", exc_info=True)
