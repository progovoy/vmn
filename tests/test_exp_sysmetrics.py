#!/usr/bin/env python3
"""System-metrics sampling: the other half of the liveness signal.

A heartbeat proves a run is alive; it cannot prove the run is *progressing*. A
process hung on a lock beats forever and reads ``running``. Sampling the
process's own CPU and memory alongside the heartbeat is what makes "alive but
flat at zero for an hour" visible.

Sampling is opt-in and best-effort, so the contracts under test are mostly
negative: with no ``psutil``/``pynvml`` installed it must be a *silent* no-op,
and a collector that raises must cost a sample, never the run or its heartbeat.
"""
import logging
import os
import time

import pytest

from version_stamp.core.experiment_query import QueryError, compile_query
from version_stamp.core.experiment_status import load_run_state
from version_stamp.exp import start_run, sysmetrics
from version_stamp.exp.reader import get_run
from helpers import _PY, _bootstrap, _experiment, _storage, extract_dev_verstr

_FAKE_SAMPLE = {"sys_cpu_percent": 12.5, "sys_rss_mb": 64.0}


def _use_collector(monkeypatch, collector):
    monkeypatch.setattr(sysmetrics, "build_collector", lambda pid=None: collector)


def _use_fake_collector(monkeypatch):
    _use_collector(monkeypatch, lambda: dict(_FAKE_SAMPLE))


def _no_optional_deps(monkeypatch):
    """Simulate psutil and pynvml both being absent, however the host is set up."""
    monkeypatch.setattr(sysmetrics, "_import_optional", lambda name: None)


def _log(app_layout, verstr):
    return _storage(app_layout).load_merged_log(app_layout.app_name, verstr)


def _sys_entries(app_layout, verstr):
    return [
        e
        for e in _log(app_layout, verstr)
        if e.get("type") == "metrics"
        and any(k in sysmetrics.SYS_METRIC_NAMES for k in e.get("values") or {})
    ]


def _row(app_layout, verstr):
    return get_run(app_layout.app_name, ref=verstr, storage=_storage(app_layout))


# ---------------------------------------------------------------------------
# the metric names
# ---------------------------------------------------------------------------


def test_metric_names_are_query_addressable():
    """Names use an underscore prefix so ``metrics.<name>`` stays a two-part path."""
    for name in sysmetrics.SYS_METRIC_NAMES:
        assert name.startswith("sys_")
        assert "." not in name
        compile_query("metrics.%s > 0" % name)

    # The dotted form the feature was first sketched with cannot work: a row's
    # `metrics` is a flat fold of every values dict, and the query language
    # resolves `metrics.<key>` only — so `metrics.sys.cpu_percent` names nothing.
    with pytest.raises(QueryError):
        compile_query("metrics.sys.cpu_percent > 0")


# ---------------------------------------------------------------------------
# recording, both entry points
# ---------------------------------------------------------------------------


def test_sdk_run_records_system_metrics(app_layout, monkeypatch):
    _bootstrap(app_layout)
    _use_fake_collector(monkeypatch)

    with start_run(
        app_layout.app_name, heartbeat_interval_sec=0.2, system_metrics=True
    ) as run:
        verstr = run.id
        time.sleep(0.7)

    assert _sys_entries(app_layout, verstr)
    metrics = _row(app_layout, verstr)["metrics"]
    assert metrics["sys_cpu_percent"] == 12.5
    assert metrics["sys_rss_mb"] == 64.0


def test_exp_run_records_system_metrics(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    _use_fake_collector(monkeypatch)

    capfd.readouterr()
    assert (
        _experiment(
            app_layout.app_name,
            action="run",
            run_cmd=[_PY, "-c", "import time; time.sleep(2.4)"],
            extra_args=["--system-metrics", "--heartbeat-interval", "1"],
        )
        == 0
    )
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    entries = _sys_entries(app_layout, verstr)
    assert len(entries) >= 2
    assert entries[0]["values"]["sys_cpu_percent"] == 12.5

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=verstr) == 0
    assert "sys_cpu_percent" in capfd.readouterr().out


def test_exp_run_samples_the_child_not_the_supervisor(app_layout, capfd, monkeypatch):
    """The workload is the child process; vmn's poll loop is idle by construction.

    Sampling the wrong process would report a CPU flat at zero for every CLI run
    — precisely the reading this feature exists to make meaningful.
    """
    _bootstrap(app_layout)
    seen = {}

    def _build(pid=None):
        seen["pid"] = pid
        return lambda: dict(_FAKE_SAMPLE)

    monkeypatch.setattr(sysmetrics, "build_collector", _build)

    pid_path = os.path.join(app_layout.repo_path, "child.pid")
    script = "import os, time; open(%r, 'w').write(str(os.getpid())); time.sleep(2.4)"

    capfd.readouterr()
    assert (
        _experiment(
            app_layout.app_name,
            action="run",
            run_cmd=[_PY, "-c", script % pid_path],
            extra_args=["--system-metrics", "--heartbeat-interval", "1"],
        )
        == 0
    )

    with open(pid_path) as f:
        child_pid = int(f.read())
    assert seen["pid"] == child_pid
    assert seen["pid"] != os.getpid()


def test_sdk_samples_its_own_process(app_layout, monkeypatch):
    """An SDK run *is* the workload, so the default target is this process."""
    _bootstrap(app_layout)
    seen = {}

    def _build(pid=None):
        seen["pid"] = pid
        return lambda: dict(_FAKE_SAMPLE)

    monkeypatch.setattr(sysmetrics, "build_collector", _build)

    with start_run(
        app_layout.app_name, heartbeat_interval_sec=0.1, system_metrics=True
    ) as run:
        time.sleep(0.4)
        assert run.id

    assert seen["pid"] in (None, os.getpid())


# ---------------------------------------------------------------------------
# cadence
# ---------------------------------------------------------------------------


def test_run_shorter_than_one_interval_records_at_most_one_sample(
    app_layout, monkeypatch
):
    _bootstrap(app_layout)
    _use_fake_collector(monkeypatch)

    with start_run(
        app_layout.app_name, heartbeat_interval_sec=30, system_metrics=True
    ) as run:
        verstr = run.id

    assert len(_sys_entries(app_layout, verstr)) <= 1


def test_longer_run_records_several_samples(app_layout, monkeypatch):
    _bootstrap(app_layout)
    _use_fake_collector(monkeypatch)

    with start_run(
        app_layout.app_name, heartbeat_interval_sec=0.15, system_metrics=True
    ) as run:
        verstr = run.id
        time.sleep(1.0)

    assert len(_sys_entries(app_layout, verstr)) >= 3


# ---------------------------------------------------------------------------
# degradation
# ---------------------------------------------------------------------------


def test_build_collector_returns_none_without_optional_deps(monkeypatch):
    _no_optional_deps(monkeypatch)
    assert sysmetrics.build_collector() is None


def test_no_collector_is_a_silent_noop(app_layout, monkeypatch, caplog):
    """Neither psutil nor pynvml: the run is normal and nothing is logged loudly."""
    _bootstrap(app_layout)
    _no_optional_deps(monkeypatch)

    with caplog.at_level(logging.DEBUG):
        with start_run(
            app_layout.app_name, heartbeat_interval_sec=0.1, system_metrics=True
        ) as run:
            verstr = run.id
            time.sleep(0.5)

    assert _row(app_layout, verstr)["status"] == "succeeded"
    assert _sys_entries(app_layout, verstr) == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_raising_collector_breaks_neither_the_run_nor_the_heartbeat(
    app_layout, monkeypatch
):
    def _boom():
        raise RuntimeError("no such device")

    _bootstrap(app_layout)
    _use_collector(monkeypatch, _boom)

    with start_run(
        app_layout.app_name, heartbeat_interval_sec=0.15, system_metrics=True
    ) as run:
        verstr = run.id
        time.sleep(0.4)
        first = load_run_state(_storage(app_layout), app_layout.app_name, verstr)[
            "heartbeat"
        ]
        time.sleep(0.6)
        second = load_run_state(_storage(app_layout), app_layout.app_name, verstr)[
            "heartbeat"
        ]

    assert second > first  # the heartbeat thread survived the failure
    assert _row(app_layout, verstr)["status"] == "succeeded"
    assert _sys_entries(app_layout, verstr) == []


# ---------------------------------------------------------------------------
# off by default
# ---------------------------------------------------------------------------


def test_sdk_records_nothing_without_the_kwarg(app_layout, monkeypatch):
    _bootstrap(app_layout)
    _use_fake_collector(monkeypatch)

    with start_run(app_layout.app_name, heartbeat_interval_sec=0.1) as run:
        verstr = run.id
        time.sleep(0.4)

    assert _sys_entries(app_layout, verstr) == []
    assert "sys_cpu_percent" not in _row(app_layout, verstr)["metrics"]


def test_exp_run_records_nothing_without_the_flag(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    _use_fake_collector(monkeypatch)

    capfd.readouterr()
    assert (
        _experiment(
            app_layout.app_name,
            action="run",
            run_cmd=[_PY, "-c", "import time; time.sleep(2.4)"],
            extra_args=["--heartbeat-interval", "1"],
        )
        == 0
    )
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert _sys_entries(app_layout, verstr) == []


# ---------------------------------------------------------------------------
# the real collector, when the optional dependency is installed
# ---------------------------------------------------------------------------


def test_real_collector_reports_plausible_values():
    psutil = pytest.importorskip("psutil")

    for pid in (None, os.getpid()):  # both mean "this process and its children"
        collector = sysmetrics.build_collector(pid)
        assert collector is not None
        values = collector()

        assert 0 <= values["sys_cpu_percent"] <= 100 * (psutil.cpu_count() or 1)
        assert values["sys_rss_mb"] > 0
        assert all(isinstance(v, (int, float)) for v in values.values())
        assert all(k in sysmetrics.SYS_METRIC_NAMES for k in values)
