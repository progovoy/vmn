"""Lineage over a very common digest: a dataset every trial of a large sweep
consumes (and may store again) links each trial to all the others. A walk
costs its node limit, not the fan-out: edges are produced lazily, the walk
stops at the first node past its limit, and a digest group already walked at
an earlier level is not walked again."""
import time

from vmn_exp.core.lineage import LineageIndex, resolve_lineage

DATA = "d" * 64
FANOUT = 50_000


class _Counted(list):
    """A list counting the items iterated out of it into *counter*."""

    def __init__(self, items, counter):
        super().__init__(items)
        self.counter = counter

    def __iter__(self):
        for item in super().__iter__():
            self.counter[0] += 1
            yield item


def _counted(index):
    counter = [0]
    for groups in (index.producers, index.digest_consumers, index.uri_consumers):
        for key, entries in groups.items():
            groups[key] = _Counted(entries, counter)
    return counter


def _consumer(verstr, idx, also_stores=False):
    row = {"verstr": verstr, "idx": idx,
           "inputs": {"data": {"uri": "s3://b/data.csv", "digest": f"sha256:{DATA}"}}}
    if also_stores:
        row["outputs"] = {"data.csv": {"path": "data.csv", "digest": f"sha256:{DATA}"}}
    return row


def _producer():
    return {"verstr": "prep", "idx": 1,
            "outputs": {"data.csv": {"path": "data.csv", "digest": f"sha256:{DATA}"}}}


def _index(rows):
    index = LineageIndex(rows)
    return (lambda app: index if app == "app" else None), _counted(index)


def test_a_common_digest_costs_the_limit_not_the_fanout():
    rows = [_producer()] + [_consumer(f"t{i}", i + 2) for i in range(FANOUT)]
    index_for, counter = _index(rows)
    result = resolve_lineage("app", "prep", index_for, limit=100)
    assert len(result["downstream"]) == 100
    assert result["truncated"] is True
    assert counter[0] <= 2 * 100


def test_deeper_walks_over_a_common_digest_stay_bounded():
    rows = [_consumer(f"t{i}", i + 1, also_stores=True) for i in range(FANOUT)]
    index_for, counter = _index(rows)
    result = resolve_lineage("app", "t7", index_for, depth=3, limit=100)
    assert len(result["upstream"]) == len(result["downstream"]) == 100
    assert result["truncated"] is True
    assert counter[0] <= 3 * 2 * 100


def test_a_digest_group_is_walked_once_across_levels():
    size = 150
    rows = [_consumer(f"t{i}", i + 1, also_stores=True) for i in range(size)]
    index_for, counter = _index(rows)
    result = resolve_lineage("app", "t0", index_for, depth=3, limit=1000)
    assert [n["depth"] for n in result["upstream"]] == [1] * (size - 1)
    assert [n["depth"] for n in result["downstream"]] == [1] * (size - 1)
    assert result["truncated"] is False
    assert counter[0] <= 2 * size


def test_many_links_to_one_node_dedupe_in_constant_time():
    paths = 20_000
    producer = {"verstr": "prep", "idx": 1, "outputs": {
        f"media/x/{i}.png": {"path": f"media/x/{i}.png", "digest": DATA} for i in range(paths)
    }}
    index_for, _ = _index([producer, _consumer("t0", 2)])
    started = time.monotonic()
    result = resolve_lineage("app", "t0", index_for)
    assert time.monotonic() - started < 2
    assert [len(n["links"]) for n in result["upstream"]] == [paths]
