"""What default-on system metrics cost the run they observe.

* The collector is built off the heartbeat thread (importing psutil and
  ``nvmlInit()`` can take seconds), and a beat never sleeps for it.
* Enumerating the process tree scans every process on the host, so it is
  re-done within a small time budget, not blindly on every tick.
* A child's unique memory (USS) parses its smaps; it is re-read every
  ``USS_EVERY_N_TICKS`` ticks and estimated from RSS in between.
* Under ``vmn-exp run`` the supervisor already samples the child's tree, so an
  SDK run inside it does not sample again unless asked to.
"""
import os
import threading
import time
import types

import pytest

from vmn_exp.sdk import start_run, sysmetrics
from exp_helpers import _PY, _bootstrap, _experiment

from test_fix_sysmetrics import _FakeProc, _fake_psutil, _use

_MB = 1024 * 1024


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _CountingProc(_FakeProc):
    def __init__(self, *args, clock=None, walk_cost=0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.walks = 0
        self.uss_reads = 0
        self._clock = clock
        self._walk_cost = walk_cost

    def children(self, recursive=True):
        self.walks += 1
        if self._clock is not None:
            self._clock.now += self._walk_cost
        return super().children(recursive)

    def memory_full_info(self):
        self.uss_reads += 1
        return super().memory_full_info()


# --- the heartbeat never waits for the collector --------------------------------


def test_a_slow_collector_build_does_not_block_a_tick(monkeypatch):
    release = threading.Event()
    recorded = []

    def _slow_build(pid=None):
        release.wait(5)
        return lambda: {"sys_cpu_percent": 1.0}

    monkeypatch.setattr(sysmetrics, "build_collector", _slow_build)
    sampler = sysmetrics.Sampler(recorded.append, True)

    started = time.monotonic()
    sampler.tick()
    assert time.monotonic() - started < 0.5
    assert recorded == []

    release.set()
    deadline = time.monotonic() + 5
    while not recorded and time.monotonic() < deadline:
        time.sleep(0.05)
        sampler.tick()
    assert recorded == [{"sys_cpu_percent": 1.0}]


# --- the process tree ------------------------------------------------------------


def test_an_expensive_tree_walk_is_not_repeated_every_tick(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(sysmetrics, "_clock", clock)
    root = _CountingProc(1, rss_mb=100, clock=clock, walk_cost=0.05)
    _use(monkeypatch, psutil=_fake_psutil(root))
    collector = sysmetrics.build_collector(1)
    walks_at_start = root.walks

    for _ in range(10):  # a 1s heartbeat for 10s
        clock.now += 1
        collector()

    # 0.05s per walk: within the budget a walk is due every 0.05/duty seconds.
    budget_walks = 10 * sysmetrics.TREE_WALK_DUTY / 0.05 + 1
    assert root.walks - walks_at_start <= budget_walks
    assert root.walks - walks_at_start >= 1


def test_a_cheap_tree_walk_still_finds_new_workers_every_tick(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(sysmetrics, "_clock", clock)
    root = _CountingProc(1, rss_mb=100, clock=clock, walk_cost=0.0)
    _use(monkeypatch, psutil=_fake_psutil(root))
    collector = sysmetrics.build_collector(1)
    collector()

    clock.now += 1
    root.kids = [_FakeProc(2, rss_mb=7)]
    assert collector()["sys_rss_mb"] == pytest.approx(107)


# --- memory ------------------------------------------------------------------------


def test_uss_is_read_every_nth_tick_and_estimated_from_rss_in_between(monkeypatch):
    root = _CountingProc(1, rss_mb=420)
    kid = _CountingProc(2, rss_mb=400, uss_mb=10)
    root.kids = [kid]
    _use(monkeypatch, psutil=_fake_psutil(root))
    collector = sysmetrics.build_collector(1)

    n = sysmetrics.USS_EVERY_N_TICKS
    readings = [collector()["sys_rss_mb"] for _ in range(2 * n + 1)]

    assert kid.uss_reads == 3  # ticks 0, n and 2n
    assert root.uss_reads == 0  # the root is measured by its RSS
    kid._rss = 800 * _MB  # the worker grew; its private share scales with it
    assert collector()["sys_rss_mb"] == pytest.approx(420 + 20)
    assert readings == [pytest.approx(430)] * (2 * n + 1)


# --- no double sampling under vmn-exp run ---------------------------------------------


def test_an_sdk_run_inside_a_sampling_supervisor_defaults_off(monkeypatch):
    monkeypatch.delenv(sysmetrics.SYSTEM_METRICS_ENV, raising=False)
    monkeypatch.setenv(sysmetrics.SUPERVISOR_SAMPLES_ENV, "1")
    assert sysmetrics.sdk_enabled(None) is False
    assert sysmetrics.sdk_enabled(True) is True  # asked for explicitly

    monkeypatch.delenv(sysmetrics.SUPERVISOR_SAMPLES_ENV)
    assert sysmetrics.sdk_enabled(None) is True
    assert sysmetrics.sdk_enabled(None, {"system_metrics": False}) is False


def test_start_run_under_a_sampling_supervisor_does_not_sample(app_layout, monkeypatch):
    _bootstrap(app_layout)
    built = []
    monkeypatch.setattr(
        sysmetrics, "build_collector", lambda pid=None: built.append(pid) or dict
    )
    monkeypatch.delenv(sysmetrics.SYSTEM_METRICS_ENV, raising=False)
    monkeypatch.setenv(sysmetrics.SUPERVISOR_SAMPLES_ENV, "1")
    with start_run(app_layout.app_name, heartbeat_interval_sec=0.1):
        time.sleep(0.3)
    assert built == []


def _child_env_marker(app_layout, capfd, tmp_path, *flags):
    out = tmp_path / "marker"
    script = (
        "import os\n"
        f"open({str(out)!r}, 'w').write("
        f"os.environ.get({sysmetrics.SUPERVISOR_SAMPLES_ENV!r}, 'unset'))\n"
    )
    capfd.readouterr()
    code = _experiment(
        app_layout.app_name,
        action="run",
        run_cmd=[_PY, "-c", script],
        extra_args=list(flags),
    )
    assert code == 0
    return out.read_text()


def test_vmn_exp_run_tells_its_child_it_samples_the_tree(
    app_layout, capfd, tmp_path, monkeypatch
):
    _bootstrap(app_layout)
    monkeypatch.delenv(sysmetrics.SYSTEM_METRICS_ENV, raising=False)
    monkeypatch.delenv(sysmetrics.SUPERVISOR_SAMPLES_ENV, raising=False)
    assert _child_env_marker(app_layout, capfd, tmp_path) == "1"
    assert os.environ.get(sysmetrics.SUPERVISOR_SAMPLES_ENV) is None


def test_a_non_sampling_supervisor_leaves_the_child_to_sample(
    app_layout, capfd, tmp_path, monkeypatch
):
    _bootstrap(app_layout)
    monkeypatch.delenv(sysmetrics.SUPERVISOR_SAMPLES_ENV, raising=False)
    marker = _child_env_marker(app_layout, capfd, tmp_path, "--no-system-metrics")
    assert marker == "unset"
