"""`vmn-exp ui` on a large store is bound by the GIL: request threads and the
refresher share one core (~26 rps at 100k runs on 3.9, ~300 rps on 3.14t).
When a watched index is large and the GIL is on, the ui says once how to run
it on a free-threaded Python."""
import logging
import threading
from types import SimpleNamespace

from vmn_exp.ui import gil_hint
from vmn_exp.ui.gil_hint import LARGE_STORE_RECORDS, GilHint
from vmn_exp.ui.refresher import Refresher

# The user-facing logger `vmn-exp ui` prints through (a module logger only
# reaches the log file).
LOGGER = "vmn"


def _hints(caplog):
    return [r for r in caplog.records if r.name == LOGGER]


def test_a_large_store_with_the_gil_on_logs_the_free_threaded_hint(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    GilHint(gil_enabled=lambda: True).note(LARGE_STORE_RECORDS)
    [hint] = _hints(caplog)
    assert hint.levelno == logging.WARNING
    assert "3.14t" in hint.getMessage()
    assert "uvx --python 3.14t" in hint.getMessage()


def test_the_hint_is_logged_once_per_process(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    hint = GilHint(gil_enabled=lambda: True)
    for _ in range(3):
        hint.note(LARGE_STORE_RECORDS * 2)
    assert len(_hints(caplog)) == 1


def test_a_small_store_logs_nothing(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    GilHint(gil_enabled=lambda: True).note(LARGE_STORE_RECORDS - 1)
    assert _hints(caplog) == []


def test_a_free_threaded_interpreter_logs_nothing(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    GilHint(gil_enabled=lambda: False).note(LARGE_STORE_RECORDS * 10)
    assert _hints(caplog) == []


def test_an_interpreter_without_is_gil_enabled_counts_as_gil_on(monkeypatch):
    monkeypatch.delattr(gil_hint.sys, "_is_gil_enabled", raising=False)
    assert gil_hint.gil_enabled() is True


class _Index:
    def __init__(self, records):
        self._snap = SimpleNamespace(rows=(None,) * records)
        self.refreshed = threading.Event()

    def refresh(self):
        self.refreshed.set()
        return self

    def snapshot(self):
        return self._snap


def test_the_refresher_notes_each_refreshed_index_size():
    noted = []
    refresher = Refresher(interval_sec=0.01, idle_sec=5)
    refresher.gil_hint = SimpleNamespace(note=noted.append)
    try:
        index = _Index(LARGE_STORE_RECORDS)
        refresher.snapshot(index)
        assert index.refreshed.wait(5)
    finally:
        refresher.stop()
    assert LARGE_STORE_RECORDS in noted
