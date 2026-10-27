"""The consistency check re-lists a bounded slice per refresh, whatever the
store's size: at 486k records on S3 one refresh used to re-list a tenth of
them (48k records, ~150k LISTs) and took 97 minutes, during which no new run
appeared. A round now just takes more refreshes; the journal's hints, live
runs and new names are listed at once as before."""
import datetime

import pytest

from vmn_exp.core import index_sweep
from vmn_exp.core.index_listing import METADATA_FILE
from vmn_exp.core.index_sweep import Sweep

APP = "app"
N = 40_000
BUDGET = index_sweep.SLICE_BUDGET
FINISHED = {"state": "finished", "exit_code": 0}


class Watch:
    """A listing watch over *names*, recording what each refresh lists."""

    from_journal = False
    names_at = None

    def __init__(self, names, rolling=True):
        self.rolling = rolling
        self.names = set(names)
        self._told = set()
        self.sliced, self.listed = [], []

    def name_changes(self, wall=None, journal=False):
        new, self._told = self.names - self._told, set(self.names)
        return dict.fromkeys(new, 1), set()

    def files(self, keys):
        self.listed.append(set(keys))
        return {k: {METADATA_FILE: (1,)} for k in keys if k in self.names}

    def full_changes(self):
        return {}, set(self.names)

    def slice_changes(self, keys):
        self.sliced.append(list(keys))
        return {}, set()

    def reset(self):
        self._told = set()


def _finished():
    return {"meta": {}, "run_state": dict(FINISHED)}


def _running():
    beat = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {"meta": {}, "run_state": {"state": "running", "heartbeat": beat,
                                      "heartbeat_interval_sec": 30}}


def _key(i):
    return f"0.0.1-dev.abc.r{i:06d}"


@pytest.fixture(params=["journaled", "rolling"])
def setup(request):
    """``(sweep, watch, records, now)`` after the first (full) listing."""
    records = {_key(i): _finished() for i in range(N)}
    watch = Watch(records)
    sweep = Sweep(None, APP, full_sweep_sec=3600, watch=watch)
    sweep.journaled = request.param == "journaled"
    now = 1000.0
    sweep.listing(records, now)
    watch.sliced.clear()
    return sweep, watch, records, now


def _slice_sizes(watch, records):
    """Sizes of the consistency slices of known records the refreshes took."""
    return [len(keys) for keys in watch.sliced if set(keys) <= records.keys()]


def test_the_budget_is_a_few_hundred_records():
    assert 100 <= BUDGET <= 1000


def test_a_refresh_after_a_long_gap_relists_at_most_the_budget(setup):
    sweep, watch, records, now = setup
    for gap in (10_000, 5_000, 3600, 1):
        now += gap
        sweep.listing(records, now)
    assert max(_slice_sizes(watch, records)) <= BUDGET


def test_credit_does_not_pile_up_beyond_the_budget(setup):
    sweep, watch, records, now = setup
    sweep.listing(records, now + 10_000)
    sweep.listing(records, now + 10_000)
    assert sum(_slice_sizes(watch, records)) <= BUDGET


def test_every_record_still_comes_round(setup):
    sweep, watch, records, now = setup
    seen = set()
    for _ in range(N // BUDGET + 2):
        now += 1000
        sweep.listing(records, now)
    for keys in watch.sliced:
        seen.update(keys)
    assert seen == records.keys()


def test_a_small_store_still_completes_a_round_within_full_sweep_sec():
    records = {_key(i): _finished() for i in range(1000)}
    watch = Watch(records)
    sweep = Sweep(None, APP, full_sweep_sec=300, watch=watch)
    sweep.journaled = True
    now = 1000.0
    sweep.listing(records, now)
    for _ in range(301):
        now += 1
        sweep.listing(records, now)
    assert set().union(*map(set, watch.sliced)) == records.keys()


def test_a_hinted_record_is_listed_at_once_after_a_long_gap(setup):
    sweep, watch, records, now = setup
    if not sweep.journaled:
        pytest.skip("hints drive journaled sweeps")
    hinted = _key(N - 1)
    sweep.hint(hinted)
    watch.listed.clear()
    sweep.listing(records, now + 10_000)
    assert hinted in set().union(*watch.listed)


def test_a_live_record_is_listed_at_its_cadence_after_a_long_gap(setup):
    sweep, watch, records, now = setup
    live = _key(N - 2)
    records[live] = _running()
    sweep.track(live, records[live])
    sweep.listing(records, now + 1)  # starts its cadence clock
    watch.listed.clear()
    sweep.listing(records, now + 10_000)
    assert live in set().union(*watch.listed)


def test_a_new_name_is_listed_at_once(setup):
    sweep, watch, records, now = setup
    if sweep.journaled:
        pytest.skip("a journaled sweep learns new names from hints")
    new = _key(N + 1)
    watch.names.add(new)
    watch.listed.clear()
    sweep.listing(records, now + 10_000)
    assert new in set().union(*watch.listed)
