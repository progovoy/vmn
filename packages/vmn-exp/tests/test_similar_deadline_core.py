"""A similar-runs search under a ``deadline`` (a ``time.monotonic()`` value)
stops its work once past it: building the inverted index and scoring the
candidates check the clock every ``DEADLINE_CHECK_EVERY`` rows/candidates and
raise ``SimilarDeadlineExceeded``. An interrupted build caches nothing."""
import pytest
from similar_fixtures import FakeSnapshot, changed, run, verstrs
from vmn_exp.core import similar, similar_index
from vmn_exp.core.similar import (
    SimilarDeadlineExceeded,
    similar_runs,
    similar_runs_multi,
)
from vmn_exp.core.similar_index import DEADLINE_CHECK_EVERY, index_for

RUNS = 10 * DEADLINE_CHECK_EVERY
LOSS = changed(files=["src/loss.py"], symbols=["src/loss.py::focal_loss"])


def _snapshot(prefix="r"):
    rows = [run(f"{prefix}{i}", params={"lr": 0.1}) for i in range(RUNS)]
    return FakeSnapshot(rows, features={row["verstr"]: LOSS for row in rows})


def _target():
    return {"row": run("t", params={"lr": 0.1}), "features": LOSS, "intent": None,
            "hypothesis": None, "text": None, "text_only": False}


class _Clock:
    """A clock standing still at 0 until :meth:`expire` moves it far past any deadline."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def expire(self):
        self.now = 1e9


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(similar_index, "_clock", fake)
    return fake


def _counting(monkeypatch, module, name, after=None, then=None):
    """Count the calls of *module.name*; call *then* once *after* calls ran."""
    calls, real = [], getattr(module, name)

    def counted(*args, **kwargs):
        calls.append(1)
        if then is not None and len(calls) == after:
            then()
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, counted)
    return calls


def test_a_deadline_in_the_past_raises_before_any_run_is_scored(clock, monkeypatch):
    scored = _counting(monkeypatch, similar, "score")
    with pytest.raises(SimilarDeadlineExceeded):
        similar_runs(_snapshot(), _target(), deadline=-1.0)
    assert scored == []


def test_a_deadline_in_the_past_raises_before_scoring_on_a_built_index(clock, monkeypatch):
    snapshot = _snapshot()
    index_for(snapshot)
    scored = _counting(monkeypatch, similar, "score")
    with pytest.raises(SimilarDeadlineExceeded):
        similar_runs(snapshot, _target(), deadline=-1.0)
    assert scored == []


def test_a_deadline_passing_mid_scoring_stops_within_a_check_interval(clock, monkeypatch):
    snapshot = _snapshot()
    index_for(snapshot)
    expire_at = 3 * DEADLINE_CHECK_EVERY + 1
    scored = _counting(monkeypatch, similar, "score", after=expire_at, then=clock.expire)
    with pytest.raises(SimilarDeadlineExceeded):
        similar_runs(snapshot, _target(), deadline=1.0)
    assert expire_at <= len(scored) <= expire_at + DEADLINE_CHECK_EVERY


def test_a_deadline_passing_mid_build_stops_it_and_caches_no_index(clock, monkeypatch):
    snapshot = _snapshot()
    expire_at = 2 * DEADLINE_CHECK_EVERY + 1
    built = _counting(monkeypatch, similar_index, "build_profile", after=expire_at,
                      then=clock.expire)
    with pytest.raises(SimilarDeadlineExceeded):
        similar_runs(snapshot, _target(), deadline=1.0)
    assert len(built) <= expire_at + DEADLINE_CHECK_EVERY
    # A later search without a deadline builds the whole index.
    assert len(similar_runs(snapshot, _target(), top=RUNS)) == RUNS


def test_a_search_within_its_deadline_answers_as_without_one(clock):
    snapshot = _snapshot()
    assert (verstrs(similar_runs(snapshot, _target(), deadline=1.0))
            == verstrs(similar_runs(snapshot, _target())))


def test_the_multi_app_search_takes_the_deadline_too(clock):
    scopes = [("a", _snapshot("a"), None), ("b", _snapshot("b"), None)]
    with pytest.raises(SimilarDeadlineExceeded):
        similar_runs_multi(scopes, _target(), deadline=-1.0)
    assert len(similar_runs_multi(scopes, _target(), deadline=1.0)) == 10
