"""System-metrics accuracy fixes, against fake ``psutil`` / ``pynvml`` modules.

* The first CPU sample was taken microseconds after priming, which Linux psutil
  reports as 0.0 — the very "flat zero" signal the feature exists to surface.
* A child first seen in a tick contributed 0.0, so per-epoch DataLoader workers
  were never counted.
* RSS was summed over the tree, so forked workers sharing the parent's pages
  inflated memory N-fold.
* GPU metrics covered every device on the node regardless of
  ``CUDA_VISIBLE_DEVICES``, and one unsupported NVML query dropped them all.
"""
import time
import types

import pytest

from version_stamp.exp import sysmetrics

_MB = 1024 * 1024


class _FakeProc:
    """A psutil.Process stand-in whose cpu_percent mimics Linux's short-interval 0.0."""

    def __init__(self, pid, rss_mb, uss_mb=None, busy=50.0, cpu_sec=0.0, created=None):
        self.pid = pid
        self._rss = rss_mb * _MB
        self._uss = (uss_mb if uss_mb is not None else rss_mb) * _MB
        self._busy = busy
        self._cpu_sec = cpu_sec
        self._created = created if created is not None else time.time() - 3600
        self._last_cpu_call = None
        self.kids = []

    # psutil API -------------------------------------------------------------
    def children(self, recursive=True):
        return list(self.kids)

    def oneshot(self):
        class _Ctx:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        return _Ctx()

    def cpu_percent(self, interval=None):
        now = time.monotonic()
        last, self._last_cpu_call = self._last_cpu_call, now
        if last is None or now - last < 0.05:
            return 0.0  # what Linux psutil reports for a (near-)zero interval
        return self._busy

    def cpu_times(self):
        return types.SimpleNamespace(user=self._cpu_sec, system=0.0)

    def create_time(self):
        return self._created

    def memory_info(self):
        return types.SimpleNamespace(rss=self._rss)

    def memory_full_info(self):
        return types.SimpleNamespace(rss=self._rss, uss=self._uss)


def _fake_psutil(root):
    procs = {root.pid: root}
    return types.SimpleNamespace(Process=lambda pid=None: procs.get(pid, root))


def _use(monkeypatch, psutil=None, pynvml=None):
    modules = {"psutil": psutil, "pynvml": pynvml}
    monkeypatch.setattr(sysmetrics, "_import_optional", lambda name: modules.get(name))


# --- CPU ---------------------------------------------------------------------


def test_the_first_cpu_sample_is_not_a_spurious_zero(monkeypatch):
    root = _FakeProc(1, rss_mb=100, busy=87.0)
    _use(monkeypatch, psutil=_fake_psutil(root))

    collector = sysmetrics.build_collector(1)
    values = collector()  # immediately, as the first heartbeat tick does

    assert values["sys_cpu_percent"] == pytest.approx(87.0)


def test_a_child_born_since_the_last_sample_is_counted(monkeypatch):
    root = _FakeProc(1, rss_mb=100, busy=10.0)
    _use(monkeypatch, psutil=_fake_psutil(root))
    collector = sysmetrics.build_collector(1)
    collector()

    # A dataloader worker spawned after that sample, which has burned CPU since.
    time.sleep(0.2)
    born = time.time() - 0.15
    root.kids = [_FakeProc(2, rss_mb=5, busy=0.0, cpu_sec=0.1, created=born)]
    values = collector()

    assert values["sys_cpu_percent"] > 10.0 + 20.0  # ~0.1 cpu-s over ~0.2 s wall


# --- memory ------------------------------------------------------------------


def test_forked_workers_sharing_pages_are_not_counted_n_times(monkeypatch):
    root = _FakeProc(1, rss_mb=420)
    root.kids = [_FakeProc(p, rss_mb=400, uss_mb=10) for p in (2, 3, 4)]
    _use(monkeypatch, psutil=_fake_psutil(root))

    values = sysmetrics.build_collector(1)()

    assert values["sys_rss_mb"] == pytest.approx(420 + 3 * 10)


# --- GPU ---------------------------------------------------------------------


class _NVMLError(Exception):
    pass


def _fake_pynvml(devices, running=None, broken_util=()):
    """*devices*: list of (uuid, used_mb, util). *running*: {index: [(pid, mb)]}."""
    running = running or {}

    def handle(index):
        return index

    def util(index):
        if index in broken_util:
            raise _NVMLError("Not Supported")
        return types.SimpleNamespace(gpu=devices[index][2])

    return types.SimpleNamespace(
        NVMLError=_NVMLError,
        nvmlInit=lambda: None,
        nvmlDeviceGetCount=lambda: len(devices),
        nvmlDeviceGetHandleByIndex=handle,
        nvmlDeviceGetUUID=lambda index: devices[index][0],
        nvmlDeviceGetMemoryInfo=lambda index: types.SimpleNamespace(
            used=devices[index][1] * _MB
        ),
        nvmlDeviceGetUtilizationRates=util,
        nvmlDeviceGetComputeRunningProcesses=lambda index: [
            types.SimpleNamespace(pid=pid, usedGpuMemory=mb * _MB)
            for pid, mb in running.get(index, [])
        ],
    )


_FOUR = [
    ("GPU-a", 1000, 100),
    ("GPU-b", 2000, 0),
    ("GPU-c", 3000, 50),
    ("GPU-d", 4000, 0),
]


def test_gpu_metrics_respect_cuda_visible_devices(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2,3")
    _use(monkeypatch, psutil=_fake_psutil(_FakeProc(1, 10)), pynvml=_fake_pynvml(_FOUR))

    values = sysmetrics.build_collector(1)()

    assert values["sys_gpu_node_mem_mb"] == pytest.approx(3000 + 4000)
    assert values["sys_gpu_node_util_percent"] == pytest.approx(25.0)


def test_cuda_visible_devices_by_uuid(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-b")
    _use(monkeypatch, psutil=_fake_psutil(_FakeProc(1, 10)), pynvml=_fake_pynvml(_FOUR))

    values = sysmetrics.build_collector(1)()

    assert values["sys_gpu_node_mem_mb"] == pytest.approx(2000)


def test_no_visible_devices_reports_no_gpu_metrics(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    _use(monkeypatch, psutil=_fake_psutil(_FakeProc(1, 10)), pynvml=_fake_pynvml(_FOUR))

    values = sysmetrics.build_collector(1)()

    assert not any(k.startswith("sys_gpu") for k in values)


def test_one_unsupported_nvml_query_keeps_the_other_values(monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    _use(
        monkeypatch,
        psutil=_fake_psutil(_FakeProc(1, 10)),
        pynvml=_fake_pynvml(_FOUR[:2], broken_util=(0,)),
    )

    values = sysmetrics.build_collector(1)()

    assert values["sys_gpu_node_mem_mb"] == pytest.approx(3000)
    assert values["sys_gpu_node_util_percent"] == pytest.approx(0.0)  # device 1 only


def test_gpu_memory_is_attributed_to_the_run_process_tree(monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    root = _FakeProc(10, 10)
    root.kids = [_FakeProc(11, 5)]
    running = {0: [(10, 300), (99, 700)], 1: [(11, 200), (98, 1800)]}
    pynvml = _fake_pynvml(_FOUR[:2], running)
    _use(monkeypatch, psutil=_fake_psutil(root), pynvml=pynvml)

    values = sysmetrics.build_collector(10)()

    assert values["sys_gpu_mem_mb"] == pytest.approx(300 + 200)
    assert values["sys_gpu_node_mem_mb"] == pytest.approx(3000)


def test_every_reported_key_is_a_declared_sys_metric(monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    root = _FakeProc(10, 10)
    pynvml = _fake_pynvml(_FOUR, {0: [(10, 1)]})
    _use(monkeypatch, psutil=_fake_psutil(root), pynvml=pynvml)

    values = sysmetrics.build_collector(10)()

    assert values and all(k in sysmetrics.SYS_METRIC_NAMES for k in values)
