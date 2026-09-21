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

# Stdlib logging, not VMN_LOGGER: this is reached from the SDK too, which never
# calls init_stamp_logger.
_LOGGER = logging.getLogger(__name__)

CPU_PERCENT = "sys_cpu_percent"
RSS_MB = "sys_rss_mb"
GPU_MEM_MB = "sys_gpu_mem_mb"
GPU_UTIL_PERCENT = "sys_gpu_util_percent"

SYS_METRIC_NAMES = (CPU_PERCENT, RSS_MB, GPU_MEM_MB, GPU_UTIL_PERCENT)

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
    """Summed CPU percent and resident memory over a process and its children.

    The tree, not one process: ``bash train.sh`` puts the real consumer one level
    down and a dataloader puts it two. The ``psutil.Process`` objects are held
    between samples because ``cpu_percent()`` reports usage since *that
    instance's* previous call — a fresh object every tick would read 0.0 forever.
    """

    def __init__(self, root):
        self._root = root
        self._tracked = {root.pid: root}
        self._sample()  # prime the CPU interval; the first reading is always 0.0

    def _tree(self):
        """This tick's processes, reusing the objects held since the last one."""
        found = [self._root]
        try:
            found.extend(self._root.children(recursive=True))
        except Exception:
            # The root exited, or we lost the right to look.
            _LOGGER.debug("Could not enumerate child processes", exc_info=True)
            found = list(self._tracked.values())

        # Rebuilt rather than pruned, so a finished worker stops being sampled.
        self._tracked = {p.pid: self._tracked.get(p.pid, p) for p in found}
        return list(self._tracked.values())

    def _sample(self):
        cpu = 0.0
        rss = 0
        for proc in self._tree():
            try:
                with proc.oneshot():  # one read per process, not two
                    cpu += proc.cpu_percent(None)
                    rss += proc.memory_info().rss
            except Exception:
                continue  # exited between listing and reading: normal
        return cpu, rss

    def __call__(self):
        cpu, rss = self._sample()
        return {CPU_PERCENT: round(cpu, 1), RSS_MB: round(rss / _MB, 1)}


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


def _gpu_probe():
    """Summed GPU memory and mean utilization across visible devices, via pynvml."""
    pynvml = _import_optional("pynvml")
    if pynvml is None:
        return None

    try:
        pynvml.nvmlInit()
        # Handles are stable for the process's lifetime, so resolve them once
        # instead of per device per tick.
        handles = [
            pynvml.nvmlDeviceGetHandleByIndex(index)
            for index in range(pynvml.nvmlDeviceGetCount())
        ]
    except Exception:
        # No driver, no device, a container without /dev/nvidia*: all normal.
        _LOGGER.debug("pynvml is installed but no GPU is reachable", exc_info=True)
        return None
    if not handles:
        return None

    def probe():
        used = 0
        util = 0
        for handle in handles:
            used += pynvml.nvmlDeviceGetMemoryInfo(handle).used
            util += pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
        return {
            GPU_MEM_MB: round(used / _MB, 1),
            GPU_UTIL_PERCENT: round(float(util) / len(handles), 1),
        }

    return probe


def build_collector(pid=None):
    """A callable returning ``{name: number}``, or None if nothing can be read.

    *pid* is the process to measure, together with its children; None means this
    process. Degrades per probe rather than all-or-nothing, so a host with
    psutil and no GPU reports CPU and RSS alone.
    """
    probes = [p for p in (_process_probe(pid), _gpu_probe()) if p is not None]
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
