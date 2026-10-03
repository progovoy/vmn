"""``vmn-exp compact`` and ``vmn-exp watch --compact`` build the ``.vmx`` of
writers that died before compacting; a rewind of a finished run rebuilds it
(plan 12 §6, §5.2)."""
import datetime

import yaml
from exp_helpers import _bootstrap, _exp, _experiment, _storage, extract_dev_verstr

from vmn_exp.core.log import metric_series
from vmn_exp.core.metric_compact import compact_record, record_compacted
from vmn_exp.core.metric_files import is_indexed_file
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.status import RUN_STATE_FILE

T0 = 1_767_225_600_000_000


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(app_layout, capfd, exit_code=1, steps=4):
    """A run whose writer died with its points still on a stream."""
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="create") == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    storage = _storage(app_layout)
    w = MetricWriter(storage, app_layout.app_name, verstr, "w")
    for step in range(1, steps + 1):
        w.add("loss", 1.0 / step, step=step, ts_us=T0 + step)
    w.flush()
    now = _iso(datetime.datetime.now(datetime.timezone.utc))
    state = {"state": "finished" if exit_code is not None else "running",
             "pid": 1, "host": "h", "started_at": now, "heartbeat": now,
             "heartbeat_interval_sec": 30, "exit_code": exit_code}
    storage.save_file(app_layout.app_name, verstr, RUN_STATE_FILE,
                      yaml.dump(state, sort_keys=False))
    return verstr


def _indexed(app_layout, verstr):
    objects = _storage(app_layout).metric_objects(app_layout.app_name, verstr)
    return bool(objects) and all(
        all(is_indexed_file(n) for n, _ in objs) for objs in objects.values())


def _compact(app_layout, *args):
    return _exp(app_layout.app_name, action="compact", extra_args=list(args))


def test_compact_builds_the_named_runs_vmx(app_layout, capfd):
    _bootstrap(app_layout)
    a, b = _run(app_layout, capfd), _run(app_layout, capfd)
    capfd.readouterr()
    assert _compact(app_layout, "-v", a) == 0
    assert f"{a} compacted (1 writer)" in capfd.readouterr().out
    assert _indexed(app_layout, a) and not _indexed(app_layout, b)
    assert _compact(app_layout, "-v", a) == 0
    assert f"{a} up-to-date" in capfd.readouterr().out


def test_compact_all_finished_skips_live_runs(app_layout, capfd):
    _bootstrap(app_layout)
    failed = _run(app_layout, capfd, exit_code=1)
    ok = _run(app_layout, capfd, exit_code=0)
    live = _run(app_layout, capfd, exit_code=None)
    capfd.readouterr()
    assert _compact(app_layout, "--all-finished") == 0
    assert _indexed(app_layout, failed) and _indexed(app_layout, ok)
    assert not _indexed(app_layout, live)


def test_compact_refuses_a_running_run(app_layout, capfd):
    _bootstrap(app_layout)
    live = _run(app_layout, capfd, exit_code=None)
    assert _compact(app_layout, "-v", live) == 1
    assert not _indexed(app_layout, live)


def test_compact_needs_refs_or_all_finished(app_layout, capfd):
    _bootstrap(app_layout)
    assert _compact(app_layout) == 1


def test_watch_compact_compacts_failed_runs_without_alert_sinks(app_layout, capfd, monkeypatch):
    for key in ("VMN_EXP_ALERT_WEBHOOK_URL", "VMN_EXP_ALERT_SLACK_URL",
                "VMN_EXP_ALERT_COMMAND", "VMN_EXP_ALERT_ON"):
        monkeypatch.delenv(key, raising=False)
    _bootstrap(app_layout)
    failed = _run(app_layout, capfd, exit_code=1)
    ok = _run(app_layout, capfd, exit_code=0)
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="watch", extra_args=["--compact"]) == 0
    assert f"{failed} compacted" in capfd.readouterr().out
    assert _indexed(app_layout, failed) and not _indexed(app_layout, ok)


def test_rewind_of_a_compacted_run_rebuilds_its_vmx(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _run(app_layout, capfd, exit_code=0)
    storage = _storage(app_layout)
    assert compact_record(storage, app_layout.app_name, verstr) == ["w"]
    assert _exp(app_layout.app_name, action="rewind",
                extra_args=["-v", verstr, "--step", "2"]) == 0
    assert _indexed(app_layout, verstr)
    [(name, size)] = storage.metric_objects(app_layout.app_name, verstr)["w"]
    from vmn_exp.core.metric_index_reader import MetricIndexReader
    read = lambda off, n: storage.read_range(app_layout.app_name, verstr, name, off, n)  # noqa: E731
    assert MetricIndexReader(read, size).footer["rewinds_applied"] is True
    log = storage.load_merged_log(app_layout.app_name, verstr)
    assert [p["step"] for p in metric_series(log)["loss"]] == [1, 2]


def test_record_compacted(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _run(app_layout, capfd)
    storage = _storage(app_layout)
    assert record_compacted(storage, app_layout.app_name, verstr) is False
    compact_record(storage, app_layout.app_name, verstr)
    assert record_compacted(storage, app_layout.app_name, verstr) is True
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="create") == 0
    bare = extract_dev_verstr(capfd.readouterr().out)
    assert record_compacted(storage, app_layout.app_name, bare) is None
