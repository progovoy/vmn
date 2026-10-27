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
RATE = index_sweep.MAX_RECHECK_PER_SEC
FINISHED = {"state": "finished", "exit_code": 0}


class Watch:
    """A listing watch over *names*, recording what each refresh lists."""

    from_journal = False
    names_at = None

    def __init__(self, names, rolling=True):
        self.rolling = rolling
        self.names = set(names)
        self._fresh = set(names)  # names not reported by name_changes yet
        self.sliced, self.listed = [], []

    def add(self, name):
        self.names.add(name)
        self._fresh.add(name)

    def name_changes(self, wall=None, journal=False):
        new, self._fresh = self._fresh, set()
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
        self._fresh = set(self.names)


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
    watch.add(new)
    watch.listed.clear()
    sweep.listing(records, now + 10_000)
    assert new in set().union(*watch.listed)


def _sweep(size, full_sweep_sec, journaled):
    """``(sweep, watch, records, now)`` over *size* finished records, listed once."""
    records = dict.fromkeys(map(_key, range(size)), _finished())
    watch = Watch(records)
    sweep = Sweep(None, APP, full_sweep_sec=full_sweep_sec, watch=watch)
    sweep.journaled = journaled
    now = 1000.0
    sweep.listing(records, now)
    watch.sliced.clear()
    return sweep, watch, records, now


def test_the_recheck_rate_is_a_few_dozen_records_a_second():
    assert 10 <= RATE <= 200


def test_an_hour_of_journaled_refreshes_rechecks_at_most_the_rate():
    # 40k store records every 300 s would be 133 a second (S3 LISTs), forever.
    sweep, watch, records, now = _sweep(N, 300, journaled=True)
    hour = 3600
    for _ in range(hour):
        now += 1
        sweep.listing(records, now)
    assert sum(_slice_sizes(watch, records)) <= RATE * hour + BUDGET


@pytest.mark.parametrize("journaled", [True, False])
def test_a_store_below_the_rate_completes_a_round_within_full_sweep_sec(journaled):
    size, full_sweep_sec = 100_000, 3600  # 28 a second
    assert size / full_sweep_sec < RATE
    sweep, watch, records, now = _sweep(size, full_sweep_sec, journaled)
    seen = set()
    for _ in range(full_sweep_sec + 5):
        now += 1
        sweep.listing(records, now)
        for keys in watch.sliced:
            seen.update(keys)
        watch.sliced.clear()
    assert seen == records.keys()


def test_a_local_rolling_sweep_is_not_rate_capped():
    # Local stat()s are cheap: 40k records still come round every 300 s.
    size, full_sweep_sec = N, 300
    assert size / full_sweep_sec > RATE
    sweep, watch, records, now = _sweep(size, full_sweep_sec, journaled=False)
    seen = set()
    for _ in range(full_sweep_sec + 5):
        now += 1
        sweep.listing(records, now)
        for keys in watch.sliced:
            seen.update(keys)
        watch.sliced.clear()
    assert seen == records.keys()
