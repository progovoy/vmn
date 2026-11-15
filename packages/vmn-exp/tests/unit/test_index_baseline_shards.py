"""The listing baseline's shards (plan 25 §2): what a cold process decodes on
every refresh, so it must come back exactly as saved and cost little to
decode at 100k records."""
import json

from vmn_exp.core.index_baseline import SHARD_SIZE, ListingBaseline

APP = "app"


class FakeKV:
    """The cache store's key-value table: payloads round-trip through JSON."""

    def __init__(self):
        self.rows = {}

    def kv_get(self, scope, fingerprint):
        row = self.rows.get(scope)
        return json.loads(row[1]) if row and row[0] == fingerprint else None

    def kv_put(self, scope, fingerprint, payload):
        self.rows[scope] = (fingerprint, json.dumps(payload))


class FakeWatch:
    def __init__(self, names=None, prints=None, moved=None):
        self.names, self.prints, self.moved = names or {}, prints or {}, moved

    def baseline(self):
        moved, self.moved = self.moved, set()
        return self.names, self.prints, moved

    def restore(self, names, prints):
        self.names, self.prints, self.moved = names, prints, set()


class FakeSweep:
    def __init__(self, watch):
        self.watch, self.state = watch, None

    def wall(self):
        return 0.0

    def export_state(self, now, wall):
        return {"last_full": now}

    def restore_state(self, state, names, now, wall):
        self.state = state


def _saved(store, names, prints):
    sweep = FakeSweep(FakeWatch(names, prints))
    baseline = ListingBaseline(store, APP)
    baseline.save(sweep, 1.0)
    return baseline, sweep


def _loaded(store):
    sweep = FakeSweep(FakeWatch())
    baseline = ListingBaseline(store, APP)
    baseline.load(sweep, 2.0)
    return baseline, sweep


def _dir_sigs(n):
    return {f"0.0.1-dev.abc.r{i}": (1794685079776546684 + i, 282769465 + i) for i in range(n)}


def test_a_baseline_comes_back_as_saved():
    names = _dir_sigs(250)
    prints = {key: (2 ** 64 - 1 - i) for i, key in enumerate(names)}
    store = FakeKV()
    _saved(store, names, prints)
    _, sweep = _loaded(store)
    assert sweep.watch.names == names
    assert sweep.watch.prints == prints
    assert sweep.state == {"last_full": 1.0}


def test_signatures_of_any_shape_and_missing_prints_come_back_as_saved():
    names = {"a": (-5, 2), "b": None, "c": (1, 2, 3), "d": "etag", "e": (2 ** 63, 7), "f": ()}
    prints = {"a": 1, "d": 2 ** 64 - 1, "f": 0}
    store = FakeKV()
    _saved(store, names, prints)
    _, sweep = _loaded(store)
    assert sweep.watch.names == names
    assert sweep.watch.prints == prints


def test_a_cold_process_s_moves_persist_over_its_loaded_baseline():
    names = _dir_sigs(300)
    prints = dict.fromkeys(names, 9)
    store = FakeKV()
    _saved(store, names, prints)
    baseline, sweep = _loaded(store)
    moved, gone = "0.0.1-dev.abc.r7", "0.0.1-dev.abc.r8"
    sweep.watch.names[moved] = (1, 1)
    sweep.watch.prints[moved] = 10
    del sweep.watch.names[gone], sweep.watch.prints[gone]
    sweep.watch.names["new"] = None
    sweep.watch.moved = {moved, gone, "new"}
    baseline.save(sweep, 3.0)

    _, again = _loaded(store)
    assert again.watch.names == {**{k: v for k, v in names.items() if k != gone},
                                 moved: (1, 1), "new": None}
    assert again.watch.prints == {**{k: v for k, v in prints.items() if k != gone}, moved: 10}


def test_a_shard_decodes_to_a_few_containers_however_many_records_it_holds():
    # Decoding a JSON list or object per record is what made a cold refresh
    # of a 100k store slow: a shard's records travel as a few columns.
    names = _dir_sigs(4 * SHARD_SIZE)
    store = FakeKV()
    _saved(store, names, {key: 2 ** 63 + i for i, key in enumerate(names)})
    shards = [text for scope, (_, text) in store.rows.items() if scope.count(":") == 2]
    assert shards
    assert all(text.count("[") + text.count("{") <= 8 for text in shards)
