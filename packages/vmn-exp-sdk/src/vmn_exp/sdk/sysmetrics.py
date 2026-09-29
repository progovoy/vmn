#!/usr/bin/env python3
"""Sampling a run's own resource usage, as ordinary metrics.

A heartbeat answers "is this process alive". It cannot answer "is it getting
anywhere" — a run wedged on a lock keeps beating and reads ``running`` forever.
CPU flat at zero for an hour is the signal that closes that gap, so the samples
are recorded as plain metrics and inherit the charts, series, sorting and schema
the metrics path already has.

Three things are deliberate:

* **the target is a process tree, not this process.** ``vmn-exp run``'s workload
  is the child it supervises (and that child's own workers); vmn's poll loop is
  idle by construction, so sampling it would report exactly the flat zero this
  feature exists to make meaningful. An SDK run passes no pid and gets itself.
* **names carry an underscore, not a dot.** ``row["metrics"]`` is a flat fold of
  every ``values`` dict (``core.experiment_log.latest_metrics``), and the query
  language resolves ``metrics.<key>`` as a two-part path, so a nested
  ``sys.cpu_percent`` would name nothing. ``autolog`` keys the same way.
* **on by default, and silent when it cannot read.** ``psutil`` is a dependency
  of vmn-exp-sdk and ``pynvml`` an optional one; both are still imported lazily
  and independently, so whichever is missing contributes no metrics, and with
  neither sampling is a *silent* no-op — it runs on every run's heartbeat, so a
  warning per run would be worse than no metrics at all. Opt out with
  ``start_run(system_metrics=False)``, ``vmn-exp run --no-system-metrics``,
  ``VMN_SYSTEM_METRICS=0`` or conf ``experiment.system_metrics: false``.
"""
import importlib
import logging
import os
import threading
import time

from vmn_exp.core.env import opted_in
from vmn_exp.sdk.sysmetrics_gpu import (
    GPU_MEM_MB,
    GPU_NODE_MEM_MB,
    GPU_NODE_UTIL_PERCENT,
    gpu_probe,
)

# Stdlib logging, not VMN_LOGGER: this is reached from the SDK too, which never
# calls init_stamp_logger.
_LOGGER = logging.getLogger(__name__)

CPU_PERCENT = "sys_cpu_percent"
# Resident memory of the tree: the root's RSS plus each child's *unique* memory,
# so forked workers sharing the parent's pages are not counted N times.
RSS_MB = "sys_rss_mb"

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

#: Set to ``0``/``false``/``no``/``off`` to turn system metrics off.
SYSTEM_METRICS_ENV = "VMN_SYSTEM_METRICS"
#: Set by ``vmn-exp run`` in its child's env when it samples the child's tree.
SUPERVISOR_SAMPLES_ENV = "VMN_EXP_SUPERVISOR_SAMPLES"

# Enumerating the tree scans every process on the host: re-walk it only once
# the time since the last walk is this many times what that walk cost.
TREE_WALK_DUTY = 0.01
# A child's USS parses its smaps; between reads it is estimated from its RSS.
USS_EVERY_N_TICKS = 10

# The clock the tree-walk budget reads; a seam for tests.
_clock = time.monotonic


def enabled(explicit, exp_conf=None):
    """Whether a run samples system metrics: on unless something opts out.

    Precedence: explicit (``False`` from ``--no-system-metrics`` or the SDK
    kwarg) > ``VMN_SYSTEM_METRICS`` > conf ``experiment.system_metrics`` > True.
    """
    return opted_in(explicit, SYSTEM_METRICS_ENV, "system_metrics", exp_conf)


def sdk_enabled(explicit, exp_conf=None):
    """:func:`enabled`, but off by default under a ``vmn-exp run`` that
    already samples this process's tree — explicit ``True`` still samples."""
    if explicit is None and os.environ.get(SUPERVISOR_SAMPLES_ENV):
        return False
    return enabled(explicit, exp_conf)


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
        self._walked_at = None
        self._walk_cost = 0.0
        self._ticks = 0
        self._uss_ratio = {}  # pid -> USS / RSS at its last USS read
        # Prime every process's CPU interval; a first reading is always 0.0.
        for proc in self._tree()[0]:
            self._read_cpu(proc)
        self._last_mono = time.monotonic()
        self._last_wall = time.time()

    def pids(self):
        """The pids sampled last tick — the run's process tree."""
        return set(self._tracked)

    def _walk_due(self):
        if self._walked_at is None:
            return True
        return _clock() - self._walked_at >= self._walk_cost / TREE_WALK_DUTY

    def _tree(self):
        """This tick's processes (reusing held objects) and the newly seen pids."""
        if not self._walk_due():
            return list(self._tracked.values()), set()
        found = [self._root]
        started = _clock()
        try:
            found.extend(self._root.children(recursive=True))
        except Exception:
            # The root exited, or we lost the right to look.
            _LOGGER.debug("Could not enumerate child processes", exc_info=True)
            found = list(self._tracked.values())
        self._walked_at, self._walk_cost = started, _clock() - started

        new = {p.pid for p in found} - set(self._tracked)
        # Rebuilt rather than pruned, so a finished worker stops being sampled.
        self._tracked = {p.pid: self._tracked.get(p.pid, p) for p in found}
        self._uss_ratio = {
            pid: r for pid, r in self._uss_ratio.items() if pid in self._tracked
        }
        return list(self._tracked.values()), new

    @staticmethod
    def _read_cpu(proc):
        try:
            return proc.cpu_percent(None)
        except Exception:
            return 0.0

    def _forget(self, proc):
        if proc is not self._root:
            self._tracked.pop(proc.pid, None)
            self._uss_ratio.pop(proc.pid, None)

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

    def _memory(self, proc, read_uss):
        """The root's RSS; a child's unique set size — read when *read_uss* or
        first seen, else its RSS scaled by the USS share last read."""
        if proc is self._root:
            return proc.memory_info().rss
        if read_uss or proc.pid not in self._uss_ratio:
            try:
                info = proc.memory_full_info()
                self._uss_ratio[proc.pid] = info.uss / info.rss if info.rss else 1.0
                return info.uss
            except Exception:
                self._uss_ratio[proc.pid] = 1.0
        return proc.memory_info().rss * self._uss_ratio[proc.pid]

    def __call__(self):
        wait = MIN_SAMPLE_INTERVAL_SEC - (time.monotonic() - self._last_mono)
        if wait > 0:
            time.sleep(wait)  # only when called right after the probe was built
        procs, new = self._tree()
        elapsed = time.monotonic() - self._last_mono
        read_uss = self._ticks % USS_EVERY_N_TICKS == 0
        self._ticks += 1
        cpu = 0.0
        memory = 0
        for proc in procs:
            try:
                with proc.oneshot():  # one read per process, not several
                    if proc.pid in new:
                        cpu += self._newborn_cpu(proc, elapsed)
                    else:
                        cpu += proc.cpu_percent(None)
                    memory += self._memory(proc, read_uss)
            except Exception:
                self._forget(proc)  # exited between listing and reading: normal
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


def build_collector(pid=None):
    """A callable returning ``{name: number}``, or None if nothing can be read.

    *pid* is the process to measure, together with its children; None means this
    process. Degrades per probe rather than all-or-nothing, so a host with
    psutil and no GPU reports CPU and RSS alone.
    """
    process = _process_probe(pid)
    root = pid or os.getpid()
    pynvml = _import_optional("pynvml")
    tree = process.pids if process is not None else (lambda: {root})
    gpu = gpu_probe(pynvml, tree) if pynvml is not None else None
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

    Callers tick from a timer they already own — ``vmn-exp run``'s poll loop and
    the SDK's :class:`~vmn_exp.sdk.heartbeat.Heartbeat` thread — so the
    cadence is the heartbeat's; the only other thread is a one-off that builds
    the collector. (Should those two ever share one heartbeat mechanism,
    ticking belongs inside it.)

    Args:
        record: called with a ``{name: number}`` mapping to persist a sample.
        enabled: False makes every tick a no-op — a run that opted out
            (see :func:`enabled`).
        pid: the process to measure, with its children; None means this process.
        collector: an explicit collector, bypassing :func:`build_collector`.
    """

    def __init__(self, record, enabled, pid=None, collector=None):
        self._record = record
        self._enabled = enabled
        self._pid = pid
        self._collector = collector
        if enabled and collector is None:
            # Off-thread, and started now so the first tick finds it ready:
            # importing psutil and nvmlInit() can take seconds on a host with
            # a sulking driver, and belong on neither start_run() nor a beat.
            threading.Thread(
                target=self._build, name="vmn-sysmetrics-init", daemon=True
            ).start()

    def _build(self):
        try:
            collector = build_collector(self._pid)
        except Exception:
            _LOGGER.debug("Building the system-metrics collector failed", exc_info=True)
            collector = None
        if collector is None:
            self._enabled = False  # nothing to read; stop trying, stay quiet
            return
        # The probe's first CPU reading needs this long since it was primed;
        # waited here so that a beat never sleeps for it.
        time.sleep(MIN_SAMPLE_INTERVAL_SEC)
        self._collector = collector

    def tick(self):
        if not self._enabled or self._collector is None:
            return  # opted out, or the collector is still being built
        try:
            values = self._collector()
            if values:
                self._record(values)
        except Exception:
            # Sampling is an observation of the run, never a part of it: a bad
            # probe or a failed append must not end the run or the heartbeat.
            _LOGGER.debug("System-metrics sampling failed", exc_info=True)
