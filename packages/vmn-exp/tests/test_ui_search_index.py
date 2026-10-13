"""Plan 23 S8: the per-snapshot search index finds exactly the runs a brute
force scan finds, on every field, and ranks ⌘K results like the reference —
on random fleets, across generations moved on by deltas."""
import pytest
from leaderboard_fleet import T0
from search_fleet import WORDS, TextFleet, hits, ranked
from vmn_exp.ui.search_index import FIELDS, SearchIndex, SearchIndexes

NEEDLES = [w.lower() for w in WORDS] + ["t1", "-t", "dev.r0000", "1.0.0", "e", "@example",
                                       "runtimeerror", "python", "b1", "adam", "Σ", "ü", "zzz"]


def _fleet(seed, n=300):
    fleet = TextFleet(seed, links=True)
    fleet.seed(n, T0, sweeps=5, live=10)
    for i in fleet.rng.sample(range(n), 40):
        fleet.set_intent(i, fleet._phrase(3))
    return fleet


def _check_finds(index, snap, needles):
    for needle in needles:
        for field in FIELDS:
            assert index.find(needle, [field]) == hits(snap, needle, [field]), (needle, field)
        assert index.find(needle) == hits(snap, needle, FIELDS), needle


@pytest.mark.parametrize("seed", range(4))
def test_find_matches_a_brute_force_scan(seed):
    fleet = _fleet(seed)
    snap = fleet.snapshot()
    _check_finds(SearchIndex.build(snap, chunk=64), snap, NEEDLES)


def test_find_is_case_insensitive_and_refuses_control_characters():
    fleet = _fleet(1)
    snap = fleet.snapshot()
    index = SearchIndex.build(snap)
    assert index.find("GRID") == index.find("grid") != []
    assert index.find("a\x01b") is None
    assert index.find("") is None


@pytest.mark.parametrize("seed", range(4))
def test_a_moved_index_matches_a_fresh_one_every_generation(seed):
    fleet = _fleet(seed)
    indexes = SearchIndexes()
    for step in range(12):
        fleet.mutate(T0, 8, removals=step % 4 == 3)
        fleet.mutate_text(6)
        snap = fleet.snapshot()
        index = indexes.get(snap)
        assert index.snapshot is snap
        _check_finds(index, snap, fleet.rng.sample(NEEDLES, 6))
        for text in fleet.rng.sample(NEEDLES, 4) + ["@3", "7", "1.0.0-dev.r00001"]:
            assert index.ranked(text, 20) == ranked(snap, text, 20), text


def test_a_small_delta_rebuilds_only_the_chunks_it_touched():
    fleet = _fleet(2, n=2000)
    indexes = SearchIndexes(chunk=128)
    first = indexes.get(fleet.snapshot())
    fleet.retext(5)
    fleet.append(state=None)
    second = indexes.get(fleet.snapshot())
    shared = sum(a is b for a, b in zip(first.chunks, second.chunks))
    assert shared == len(first.chunks) - 2  # the retexted run's and the tail's


def test_a_heartbeat_rebuilds_nothing():
    fleet = _fleet(3, n=1000)
    indexes = SearchIndexes(chunk=128)
    first = indexes.get(fleet.snapshot())
    live = [i for i, s in enumerate(fleet.specs) if (fleet.states[s["verstr"]] or {})
            .get("exit_code", 0) is None]
    for i in live:
        fleet.set_state(i, dict(fleet.states[fleet.specs[i]["verstr"]], heartbeat="later"))
    second = indexes.get(fleet.snapshot())
    assert all(a is b for a, b in zip(first.chunks, second.chunks))


@pytest.mark.parametrize("seed", range(3))
def test_ranked_matches_the_reference(seed):
    fleet = _fleet(seed)
    fleet.edit(4, archived=True)
    snap = fleet.snapshot()
    index = SearchIndex.build(snap, chunk=32)
    for text in NEEDLES + ["@5", "5", "1.0.0-dev.r0001", " grid ", "@99999"]:
        for limit in (1, 5, 20):
            assert index.ranked(text, limit) == ranked(snap, text, limit), (text, limit)
        assert index.ranked(text, 50, archived=True) == ranked(snap, text, 50, archived=True)


def test_ranked_of_blank_text_is_empty():
    snap = _fleet(0).snapshot()
    assert SearchIndex.build(snap).ranked("  ", 20) == []
