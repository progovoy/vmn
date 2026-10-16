"""A similar-runs search under a ``deadline`` (a ``time.monotonic()`` value)
stops its work once past it: a SQLite progress handler looks at the clock
every ``PROGRESS_OPS`` steps and interrupts the query under way, raising
``SimilarDeadlineExceeded``; the connection answers as before afterwards."""
import pytest
from similar_fixtures import FakeSnapshot, changed, run, similar_runs, similar_runs_multi, verstrs
from vmn_exp.core import similar, similar_match
from vmn_exp.core.similar import SimilarDeadlineExceeded

RUNS = 300
LOSS = changed(files=["src/loss.py"], symbols=["src/loss.py::focal_loss"])


def _snapshot(prefix="r"):
    rows = [run(f"{prefix}{i}", params={"lr": 0.1}) for i in range(RUNS)]
    return FakeSnapshot(rows, features={row["verstr"]: LOSS for row in rows})


def _target():
    return {"row": run("t", params={"lr": 0.1}), "features": LOSS, "intent": None,
            "hypothesis": None, "text": None, "text_only": False}


class _Clock:
    """A clock standing still at 0 until it has been read *expire_after* times."""

    def __init__(self, expire_after=None):
        self.reads, self.expire_after = 0, expire_after

    def __call__(self):
        self.reads += 1
        return 1e9 if self.expire_after is not None and self.reads > self.expire_after else 0.0


def _counting(monkeypatch, module, name):
    calls, real = [], getattr(module, name)

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, counted)
    return calls


def test_a_deadline_in_the_past_raises_before_any_query(monkeypatch):
    snapshot = _snapshot()
    ranked = _counting(monkeypatch, similar, "rank")
    with pytest.raises(SimilarDeadlineExceeded):
        similar_runs(snapshot, _target(), deadline=-1.0)
    assert ranked == []


def test_a_deadline_passing_mid_query_interrupts_it(monkeypatch):
    snapshot = _snapshot()
    similar_runs(snapshot, _target())  # filed: what follows is the query alone
    clock = _Clock(expire_after=3)
    monkeypatch.setattr(similar_match, "_clock", clock)
    monkeypatch.setattr(similar_match, "PROGRESS_OPS", 10)
    with pytest.raises(SimilarDeadlineExceeded):
        similar_runs(snapshot, _target(), deadline=1.0)
    assert clock.reads > 3
    monkeypatch.setattr(similar_match, "_clock", _Clock())
    assert len(similar_runs(snapshot, _target(), top=RUNS)) == RUNS


def test_a_search_within_its_deadline_answers_as_without_one(monkeypatch):
    monkeypatch.setattr(similar_match, "_clock", _Clock())
    snapshot = _snapshot()
    assert (verstrs(similar_runs(snapshot, _target(), deadline=1.0))
            == verstrs(similar_runs(snapshot, _target())))


def test_the_multi_app_search_takes_the_deadline_too(monkeypatch):
    monkeypatch.setattr(similar_match, "_clock", _Clock())
    scopes = [("a", _snapshot("a"), None), ("b", _snapshot("b"), None)]
    with pytest.raises(SimilarDeadlineExceeded):
        similar_runs_multi(scopes, _target(), deadline=-1.0)
    assert len(similar_runs_multi(scopes, _target(), deadline=1.0)) == 10
