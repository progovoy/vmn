"""Who issued the S3 calls: each in-flight and slow request of the dump's
``requests`` section carries its calls per operation, and calls made off any
request are tallied per thread name in ``s3.by_thread``."""
import threading

import pytest

from vmn_exp.storage import s3_stats
from vmn_exp.storage.s3_stats import S3Call
from vmn_exp.ui import diag
from vmn_exp.ui.diag import registry, s3_attribution
from vmn_exp.ui.diag.requests import _CURRENT, RequestTracker


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(registry, "_SECTIONS", dict(registry._SECTIONS))
    monkeypatch.setattr(s3_attribution, "_threads", {})


def _call(op="GetObject", ms=12.5, error=None):
    return S3Call(op, "vmn/runs/a/v/metadata.yml", ms, 404 if error else 200, error, 0, 0)


def _in_request(entry, fn):
    token = _CURRENT.set(entry)
    try:
        fn()
    finally:
        _CURRENT.reset(token)


def test_calls_inside_a_request_add_up_on_its_in_flight_entry():
    tracker = RequestTracker(slow_sec=0.0)
    entry = tracker.started({"method": "GET", "path": "/experiments"})

    def calls():
        s3_attribution.record(_call(ms=10))
        s3_attribution.record(_call(ms=5, error="NoSuchKey"))
        s3_attribution.record(_call(op="ListObjectsV2", ms=1))

    _in_request(entry, calls)
    flying = tracker.section()["in_flight"][0]
    assert flying["s3"] == {"GetObject": {"n": 2, "ms": 15.0, "err": 1},
                            "ListObjectsV2": {"n": 1, "ms": 1.0, "err": 0}}

    tracker.finished(entry, 200)
    assert tracker.section()["slow"][-1]["s3"]["GetObject"]["n"] == 2
    assert s3_attribution.by_thread() == {}


def test_a_request_without_calls_reports_no_s3():
    tracker = RequestTracker(slow_sec=0.0)
    entry = tracker.started({"method": "GET", "path": "/meta"})
    assert tracker.section()["in_flight"][0]["s3"] == {}
    tracker.finished(entry, 200)
    assert tracker.section()["slow"][-1]["s3"] == {}


@pytest.mark.parametrize("name,label", [
    ("ThreadPoolExecutor-3_7", "ThreadPoolExecutor-3"),
    ("vmn-ui-detail_12", "vmn-ui-detail"),
    ("vmn-ui-refresh", "vmn-ui-refresh"),
    ("MainThread", "MainThread"),
])
def test_thread_labels_drop_the_pool_worker_number(name, label):
    assert s3_attribution.thread_label(name) == label


def _on_thread(name, fn):
    t = threading.Thread(target=fn, name=name)
    t.start()
    t.join(10)


def test_calls_off_any_request_are_tallied_per_thread_name():
    for worker in ("ThreadPoolExecutor-3_0", "ThreadPoolExecutor-3_1"):
        _on_thread(worker, lambda: s3_attribution.record(_call(ms=2)))
    _on_thread("vmn-ui-refresh", lambda: s3_attribution.record(_call(op="ListObjectsV2")))
    assert s3_attribution.by_thread() == {
        "ThreadPoolExecutor-3": {"GetObject": {"n": 2, "ms": 4.0, "err": 0}},
        "vmn-ui-refresh": {"ListObjectsV2": {"n": 1, "ms": 12.5, "err": 0}},
    }


def test_the_thread_table_is_bounded():
    for i in range(s3_attribution.MAX_THREADS + 10):
        _on_thread(f"worker-{i}", lambda: s3_attribution.record(_call(ms=1)))
    table = s3_attribution.by_thread()
    assert len(table) == s3_attribution.MAX_THREADS + 1
    assert table[s3_attribution.OTHER]["GetObject"]["n"] == 10


def test_the_default_sections_attribute_real_calls_once(monkeypatch):
    monkeypatch.setattr(s3_stats, "_listeners", ())
    diag.install_default_sections()
    diag.install_default_sections()
    assert s3_stats._listeners == (s3_attribution.record,)
    s3_stats._notify(_call())
    section = diag.build_dump()["sections"]["s3"]
    assert section["by_thread"]["MainThread"]["GetObject"]["n"] == 1
    assert "operations" in section and "by_kind" in section
