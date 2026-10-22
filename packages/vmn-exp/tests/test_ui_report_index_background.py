"""With background refresh a request never refreshes the report index
itself: a journal catch-up took minutes on a busy store and held every
experiments list waiting on its comment counts."""
import threading
import types

from vmn_exp.ui import report_index
from vmn_exp.ui.report_index import ReportIndexes


class _SlowIndex:
    def __init__(self):
        self.release = threading.Event()
        self.refreshes = 0
        self.done = threading.Event()

    def refresh(self):
        self.refreshes += 1
        self.release.wait(10)
        self.done.set()


def test_get_returns_at_once_while_a_refresh_runs_elsewhere(monkeypatch):
    slow = _SlowIndex()
    indexes = ReportIndexes(background=True)
    monkeypatch.setattr(indexes, "_new", lambda ws, storage: slow)
    monkeypatch.setattr(report_index, "FOLLOW_INTERVAL_SEC", 0)
    ws = types.SimpleNamespace(name="ws")
    caller = threading.current_thread()
    seen = []
    real = slow.refresh
    slow.refresh = lambda: seen.append(threading.current_thread()) or real()

    assert indexes.get(ws, None) is slow
    assert indexes.get(ws, None) is slow  # one refresh in flight, not two

    slow.release.set()
    assert slow.done.wait(5)
    assert slow.refreshes == 1 and caller not in seen


def test_without_background_refresh_a_request_sees_every_write(monkeypatch):
    slow = _SlowIndex()
    slow.release.set()
    indexes = ReportIndexes(background=False)
    monkeypatch.setattr(indexes, "_new", lambda ws, storage: slow)

    indexes.get(types.SimpleNamespace(name="ws"), None)

    assert slow.refreshes == 1 and slow.done.is_set()
