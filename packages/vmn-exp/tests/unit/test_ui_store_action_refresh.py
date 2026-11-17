"""A store action refreshes the app index once per app it changed, after it
ran, not once per run: a bulk archive of a batch is one refresh, not one full
re-listing of the app per run (which made a 500-run batch quadratic)."""
import pytest

from fakes.clock import FakeClock
from fakes.env import FakeEnv
from fakes.host import FakeHost
from vmn_exp.ui.bulk_actions import BulkSpec
from vmn_exp.ui.jobs_store import StoreActionError, build_store_action, run_refreshing_once

APP = "my_app"
RUNS = [f"0.0.1-dev.run.{i:04d}" for i in range(3)]


class FakeStorage:
    def __init__(self, missing=()):
        self.archived, self._missing = [], set(missing)

    def update_metadata(self, app_name, verstr, update):
        if verstr in self._missing:
            return False
        self.archived.append(verstr)
        return True


def _archive(verstrs):
    action, err = build_store_action("exp_archive", APP, {"verstrs": verstrs}, FakeEnv(), FakeHost())
    assert err is None
    return action


def test_an_action_on_many_runs_refreshes_their_app_once():
    storage, touched = FakeStorage(), []
    run_refreshing_once([_archive(RUNS[:2]), _archive(RUNS[2:])], storage, touched.append, FakeClock().now())
    assert storage.archived == RUNS
    assert touched == [APP]


def test_a_failing_action_still_refreshes_the_runs_it_changed():
    storage, touched = FakeStorage(missing={RUNS[1]}), []
    with pytest.raises(StoreActionError):
        run_refreshing_once([_archive(RUNS)], storage, touched.append, FakeClock().now())
    assert storage.archived == RUNS[:1]
    assert touched == [APP]


class _RefreshFailing:
    """``touched`` that fails for the first app it is given."""

    def __init__(self):
        self.refreshed = []

    def __call__(self, app_name):
        self.refreshed.append(app_name)
        if len(self.refreshed) == 1:
            raise OSError("index refresh failed")


def _archive_in(app_name, verstrs):
    action, err = build_store_action("exp_archive", app_name, {"verstrs": verstrs}, FakeEnv(), FakeHost())
    assert err is None
    return action


def test_a_failing_refresh_still_refreshes_the_other_apps():
    touched = _RefreshFailing()
    actions = [_archive_in("app_a", RUNS[:1]), _archive_in("app_b", RUNS[1:])]
    log = run_refreshing_once(actions, FakeStorage(), touched, FakeClock().now())
    assert touched.refreshed == ["app_a", "app_b"]
    assert log == "\n".join(RUNS)


def test_a_failing_refresh_does_not_mask_the_actions_error():
    storage, touched = FakeStorage(missing={RUNS[1]}), _RefreshFailing()
    with pytest.raises(StoreActionError):
        run_refreshing_once([_archive(RUNS)], storage, touched, FakeClock().now())
    assert touched.refreshed == [APP]


def test_an_action_changing_nothing_refreshes_nothing():
    touched = []
    run_refreshing_once([], FakeStorage(), touched.append, FakeClock().now())
    assert touched == []


def test_a_bulk_batch_refreshes_the_app_once():
    storage, touched = FakeStorage(), []
    spec = BulkSpec("exp_archive", APP, {"q": 'branch = "a"'})
    log = spec.apply(storage, RUNS, touched=touched.append, now=FakeClock().now(), env=FakeEnv(), host=FakeHost())
    assert storage.archived == RUNS and log == "\n".join(RUNS)
    assert touched == [APP]
