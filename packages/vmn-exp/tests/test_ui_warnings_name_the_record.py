"""A warning about one run names its app and verstr, so an operator reading
the server's log can go to the record (a client had to work ``.vmx`` run
keys out of diagnostic dumps): the store failing a record's read (the
record is set aside), store upkeep's marking and compaction failures, and a
compaction left undone at a run's end."""
import logging
import time

import vmn_exp.core.index as index_module
from test_ui_store_upkeep import APP, _Index, _run, _snap, storage  # noqa: F401
from vmn_exp.core import metric_compact
from vmn_exp.ui import store_upkeep
from vmn_exp.ui.store_upkeep import AppUpkeep, StoreUpkeep


def _store_fails_reading(monkeypatch, bad):
    real = index_module.refresh_record

    def refresh_record(key, *args, **kwargs):
        if key == bad:
            raise ConnectionResetError("connection reset by peer")
        return real(key, *args, **kwargs)

    monkeypatch.setattr(index_module, "refresh_record", refresh_record)


def test_a_store_failure_reading_a_record_names_it(storage, monkeypatch, tmp_path,  # noqa: F811
                                                   caplog):
    bad = _run(storage, points=False)
    _store_fails_reading(monkeypatch, bad)
    index = index_module.ExperimentIndex(storage, APP, str(tmp_path / "i.sqlite"))

    with caplog.at_level(logging.WARNING, logger="vmn_exp.core.index"):
        index.refresh()  # set aside, not failed

    warned = [r.getMessage() for r in caplog.records if r.name == "vmn_exp.core.index"]
    assert len(warned) == 1 and APP in warned[0] and bad in warned[0]


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_failed_child_marker_names_the_app_and_both_runs(storage, monkeypatch, caplog):  # noqa: F811
    outer = _run(storage, points=False)
    kid = _run(storage, parent=outer, points=False)
    storage.unmark_child(APP, outer, kid)

    def boom(*a):
        raise OSError("denied")

    monkeypatch.setattr(storage, "mark_child", boom)
    AppUpkeep(storage, APP).run(_snap(storage))

    assert any(APP in m and kid in m and outer in m for m in _warnings(caplog))


def test_a_failed_compaction_names_the_app_and_the_run(storage, monkeypatch, caplog):  # noqa: F811
    dead = _run(storage, exit_code=1)

    def boom(*a):
        raise OSError("denied")

    monkeypatch.setattr(store_upkeep, "compact_record", boom)
    AppUpkeep(storage, APP).run(_snap(storage))

    assert any(APP in m and dead in m for m in _warnings(caplog))


def test_a_failed_upkeep_pass_names_the_app(storage, monkeypatch, caplog):  # noqa: F811
    def boom(self, snapshot, budget_sec):
        raise RuntimeError("bug")

    monkeypatch.setattr(AppUpkeep, "run", boom)
    upkeep, index = StoreUpkeep(interval_sec=0), _Index()
    try:
        upkeep.note(index, storage, APP)
        upkeep.refreshed(index, _snap(storage))
        assert upkeep.wait_idle(10)
    finally:
        upkeep.stop()

    assert any("Store upkeep" in m and APP in m for m in _warnings(caplog))


def test_a_compaction_left_undone_names_the_app_and_the_run(storage, monkeypatch, caplog):  # noqa: F811
    verstr = _run(storage)
    monkeypatch.setattr(metric_compact, "_compact_quietly", lambda *a: time.sleep(0.5))
    caplog.set_level(logging.WARNING)

    assert metric_compact.compact_by(storage, APP, verstr, "w", time.monotonic() + 0.05) is False

    assert any(APP in m and verstr in m for m in _warnings(caplog))
