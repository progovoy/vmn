"""The board's bases are kept per app: a server (or a /metrics scrape)
going round several apps builds each app's base once, not once a turn."""
import dataclasses

from leaderboard_group_rows import run, snapshot
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui.memo import GroupedLRU


def _snapshots(names):
    return {name: dataclasses.replace(snapshot([run(1), run(2)]), app_name=name)
            for name in names}


def test_going_round_apps_builds_each_base_once(monkeypatch):
    builds, build = [], lb._Base.build

    def counted(snap, *args):
        builds.append(snap.app_name)
        return build(snap, *args)

    monkeypatch.setattr(lb._Base, "build", staticmethod(counted))
    cache = lb.LeaderboardCache()
    snaps = _snapshots(["a", "b", "c", "d"])
    for _ in range(3):
        for snap in snaps.values():
            assert len(cache.ordered(snap, {})) == 2
    assert sorted(builds) == ["a", "b", "c", "d"]


def test_a_group_keeps_its_newest_entries_and_the_oldest_groups_go():
    lru = GroupedLRU(per_group=2, groups=2, group_of=lambda value: value[0])
    for key in ["a1", "a2", "a3", "b1"]:
        lru.put(key, (key[0], key))
    assert [v for _, v in lru.values()] == ["a2", "a3", "b1"]
    lru.put("c1", ("c", "c1"))  # a third group: the least recent one leaves whole
    assert [v for _, v in lru.values()] == ["b1", "c1"]
