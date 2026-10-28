"""Plan 28 P3: an outer run's counts and durations split by one tag or param
(``tags.kind``), one tally per (parent, value) carried across index
generations by deltas, must answer what a brute-force walk of the same
snapshot answers; a parent keeps at most 12 values (the rest under
``other``), and an answer names at most 12."""
import datetime

import pytest
from job_rollup_reference import STATES, annotated, exact_quantile, jobs, settled_of, subtree
from leaderboard_fleet import T0, Fleet
from vmn_exp.core.tree import children_by_parent
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_group_fields import key_of

from vmn_exp.core import status as status_mod
from vmn_exp.ui import job_rollup
from vmn_exp.ui.job_split import MAX_VALUES, SplitSpec, SplitTallies, check_split

KINDS = ["trial", "refit", "refit_final", "assembler", "pod/train", "pod/eval", "study", None]


class KindFleet(Fleet):
    """A fleet whose runs carry a ``kind`` tag (None: untagged)."""

    def __init__(self, seed, kinds=KINDS):
        super().__init__(seed)
        self.kinds = kinds

    def _fold(self, i):
        spec = self.specs[i]
        if "kind" not in spec:
            spec["kind"] = self.rng.choice(self.kinds)
        row = super()._fold(i)
        return dict(row, tags={"kind": spec["kind"]} if spec["kind"] else {})

    def add(self, parent, kind, state):
        verstr = self.new_verstr()
        self.specs.append({"verstr": verstr, "parent": parent, "values": {}, "archived": False,
                           "branch": "b0", "opt": "adam", "kind": kind, "ts": "2026-01-01T00:00:00Z"})
        self.rows.append(self._fold(len(self.specs) - 1))
        self.states[verstr], self.observed[verstr] = state, None
        return verstr


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _members(rows, verstr):
    by_verstr = {row["verstr"]: row for row in rows}
    return [by_verstr[v] for v in subtree(verstr, children_by_parent(rows))
            if v in by_verstr and not by_verstr[v].get("archived")]


def reference(rows, verstr, field):
    """``{key: {total, counts, done, never_started, lost, failed_pct, durations}}``."""
    by_verstr, key = {row["verstr"]: row for row in rows}, key_of(field)
    out = {}
    for row in _members(rows, verstr):
        entry = out.setdefault(key(row), {
            "counts": dict.fromkeys(STATES.values(), 0), "never_started": 0, "lost": 0,
            "durations": []})
        settled = settled_of(row, by_verstr)
        if settled:
            entry[settled] += 1
        else:
            entry["counts"][STATES[row["status"]]] += 1
        if row["status"] in ("succeeded", "failed") and row.get("finished_at"):
            entry["durations"].append(row["duration_sec"])
    for entry in out.values():
        counts = entry["counts"]
        entry["total"] = sum(counts.values()) + entry["never_started"] + entry["lost"]
        entry["done"] = counts["succeeded"] + counts["failed"] + entry["lost"]
        entry["failed_pct"] = round(100 * (counts["failed"] + entry["lost"]) / entry["total"], 2)
    return out


def _close(got, want):
    return abs(got - want) <= 0.011 * abs(want) + 1e-9


def _check_entry(got, want):
    for name in ("total", "counts", "done", "never_started", "lost", "failed_pct"):
        assert got[name] == want[name], name
    assert got["duration"]["n"] == len(want["durations"])
    for name, q in (("p50", 0.5), ("p90", 0.9)):
        if want["durations"]:
            assert _close(got["duration"][name], exact_quantile(want["durations"], q))
        else:
            assert got["duration"][name] is None


def _merged(entries):
    out = {"counts": dict.fromkeys(STATES.values(), 0), "never_started": 0, "lost": 0,
           "durations": [], "total": 0, "done": 0}
    for entry in entries:
        for state, n in entry["counts"].items():
            out["counts"][state] += n
        for name in ("never_started", "lost", "total", "done"):
            out[name] += entry[name]
        out["durations"] += entry["durations"]
    failed = out["counts"]["failed"] + out["lost"]
    out["failed_pct"] = round(100 * failed / out["total"], 2) if out["total"] else 0.0
    return out


def _check_split(got, want, named):
    """*got* names *named* in that order, then ``other`` holds the rest."""
    assert [e["key"] for e in got if not e.get("other")] == named
    for entry in got:
        if not entry.get("other"):
            _check_entry(entry, want[entry["key"]])
    rest = [want[k] for k in want if k not in named]
    others = [e for e in got if e.get("other")]
    if not rest:
        assert others == []
        return
    (other,) = others
    assert got[-1] is other
    _check_entry(other, _merged(rest))


def _by_total(want):
    return sorted(want, key=lambda k: (-want[k]["total"], k))[:MAX_VALUES]


def _check_all(cache, snap, field="tags.kind"):
    rows = annotated(snap)
    for verstr in jobs(rows):
        want = reference(rows, verstr, field)
        _check_split(cache.jobs.split_rollup(snap, field, verstr), want, _by_total(want))


@pytest.mark.parametrize("seed", range(5))
def test_split_rollups_match_a_brute_force_walk_across_generations(monkeypatch, seed):
    fleet = KindFleet(seed)
    fleet.seed(240, T0, sweeps=4, live=12)
    for i in fleet.rng.sample(range(len(fleet.specs)), 100):
        fleet.set_state(i, fleet.ended(T0) if fleet.rng.random() < 0.8 else None)
    cache, now = LeaderboardCache(), T0
    for _ in range(12):
        monkeypatch.setattr(status_mod, "_now", lambda when=None, at=now: when or at)
        snap = fleet.snapshot()
        _check_all(cache, snap)
        _check_all(cache, snap, "params.opt")
        now += datetime.timedelta(seconds=fleet.rng.choice([0, 3, 45, 70]))
        fleet.mutate(now, fleet.rng.choice([1, 4, 12]))
        for i in fleet.rng.sample(range(len(fleet.specs)), 3):
            fleet.edit(i, kind=fleet.rng.choice(KINDS))


def test_a_value_moved_by_a_tag_change_leaves_one_bucket_for_another():
    fleet = KindFleet(3, kinds=["trial"])
    (job,) = fleet.seed_jobs(1, 20, T0)
    cache = LeaderboardCache()
    assert [e["key"] for e in cache.jobs.split_rollup(fleet.snapshot(), "tags.kind", job)] == ["trial"]
    for i in range(1, 6):
        fleet.edit(i, kind="refit")
    snap = fleet.snapshot()
    got = cache.jobs.split_rollup(snap, "tags.kind", job)
    assert [(e["key"], e["total"]) for e in got] == [("trial", 15), ("refit", 5)]
    _check_all(cache, snap)


def _single_parent(kinds):
    fleet = KindFleet(4)
    job = fleet.add(None, None, fleet.ended(T0))
    for kind in kinds:
        fleet.add(job, kind, fleet.ended(T0))
    return fleet, job


def test_a_parent_keeps_its_twelve_first_values_and_the_rest_as_other():
    kinds = [f"k{n:02d}" for n in range(20) for _ in range(1 + n % 3)]
    fleet, job = _single_parent(kinds)
    cache = LeaderboardCache()

    def check():
        snap = fleet.snapshot()
        want = reference(annotated(snap), job, "tags.kind")
        kept = sorted(want)[:MAX_VALUES]
        _check_split(cache.jobs.split_rollup(snap, "tags.kind", job), want,
                     sorted(kept, key=lambda k: (-want[k]["total"], k)))

    check()
    # Every k03 run leaves: k12 comes out of other.
    for i in reversed([i for i, s in enumerate(fleet.specs) if s["kind"] == "k03"]):
        fleet.remove(i)
    check()
    # A value sorting first joins: k12 goes back under other.
    fleet.add(job, "a", fleet.ended(T0))
    check()


def test_a_value_another_parent_may_hold_under_other_is_never_named():
    fleet = KindFleet(5)
    top = fleet.add(None, None, fleet.ended(T0))
    a, b = (fleet.add(top, "zgroup", fleet.ended(T0)) for _ in range(2))
    for n in range(13):
        fleet.add(a, f"k{n:02d}", fleet.ended(T0))
    for _ in range(3):
        fleet.add(b, "k12", fleet.ended(T0))
    snap = fleet.snapshot()
    rows = annotated(snap)
    got = LeaderboardCache().jobs.split_rollup(snap, "tags.kind", top)
    want = reference(rows, top, "tags.kind")
    # a holds k12 under other, past its twelve: k12 (4 runs) and the
    # values after it ("zgroup") count under other.
    _check_split(got, want, [f"k{n:02d}" for n in range(12)])
    assert got[-1]["total"] == 6
    sub = LeaderboardCache().jobs.split_rollup(snap, "tags.kind", b)
    assert [(e["key"], e["total"]) for e in sub] == [("k12", 3)]


def test_an_answer_names_its_twelve_largest_values():
    fleet = KindFleet(6)
    top = fleet.add(None, None, fleet.ended(T0))
    for p in range(3):
        parent = fleet.add(top, "zz", fleet.ended(T0))
        for n in range(6):
            for _ in range(1 + (p * 6 + n) % 5):
                fleet.add(parent, f"v{p}{n}", fleet.ended(T0))
    snap = fleet.snapshot()
    want = reference(annotated(snap), top, "tags.kind")
    assert len(want) == 19
    got = LeaderboardCache().jobs.split_rollup(snap, "tags.kind", top)
    _check_split(got, want, _by_total(want))
    assert sum(e["total"] for e in got) == sum(w["total"] for w in want.values())


def test_an_entry_carries_the_clause_selecting_its_runs():
    fleet = KindFleet(7)
    top = fleet.add(None, None, fleet.ended(T0))
    for kind in ["trial", "trial", "refit", None] + [f"x{n:02d}" for n in range(12)]:
        fleet.add(top, kind, fleet.ended(T0))
    got = LeaderboardCache().jobs.split_rollup(fleet.snapshot(), "tags.kind", top)
    by_key = {e["key"]: e for e in got}
    assert by_key["trial"]["clause"] == 'tags.kind = "trial"'
    assert by_key["trial"]["label"] == "trial"
    other = got[-1]
    assert other["other"] is True and other["label"] == "other" and other["key"] is None
    named = [e for e in got if not e.get("other")]
    assert len(named) == MAX_VALUES
    assert other["clause"].startswith("tags.kind not in (")
    if "∅" in by_key:
        assert by_key["∅"]["clause"] == "tags.kind = null"
        assert by_key["∅"]["label"] == "(none)"


def test_a_tally_keeps_at_most_twelve_values_whatever_it_is_given():
    spec, tallies = SplitSpec("params.seed"), SplitTallies()
    rows = [{"verstr": f"r{n:03d}", "status": "succeeded", "params": {"seed": n},
             "finished_at": "2026-03-01T12:00:00Z", "duration_sec": n} for n in range(100)]
    for row in rows:
        tallies.add(row, spec)
    assert len(tallies.named) == MAX_VALUES
    assert tallies.other.total == 100 - MAX_VALUES
    copy = tallies.copy()
    for row in reversed(rows):
        tallies.add(row, spec, by=-1)
    assert tallies.empty()
    assert len(copy.named) == MAX_VALUES and copy.other.total == 100 - MAX_VALUES


@pytest.mark.parametrize("field", ["tags.kind", "params.lr", "params.odd key"])
def test_split_takes_a_tag_or_a_param(field):
    assert check_split(field) == field


@pytest.mark.parametrize("field", ["kind", "tags.", "metrics.loss", "parent", "", None])
def test_split_refuses_any_other_field(field):
    with pytest.raises(ValueError):
        check_split(field)


def test_a_generation_moves_the_split_rollups_on_instead_of_rebuilding(monkeypatch):
    fleet = KindFleet(8)
    fleet.seed_jobs(3, 80, T0, live=8)
    cache = LeaderboardCache()
    cache.jobs.split_rollup(fleet.snapshot(), "tags.kind", fleet.specs[0]["verstr"])
    builds = []
    real = job_rollup.StaticRollups.build
    monkeypatch.setattr(job_rollup.StaticRollups, "build",
                        classmethod(lambda cls, *a: builds.append(1) or real(*a)))
    for _ in range(3):
        fleet.mutate(T0, 5, removals=False, reparent=False)
        snap = fleet.snapshot()
        _check_all(cache, snap)
    assert builds == []


def test_split_answers_are_memoized_per_generation():
    fleet = KindFleet(9)
    fleet.seed_jobs(1, 10, T0, live=2)
    cache, snap = LeaderboardCache(), fleet.snapshot()
    job = fleet.specs[0]["verstr"]
    assert cache.jobs.split_rollup(snap, "tags.kind", job) is cache.jobs.split_rollup(
        snap, "tags.kind", job)
    assert cache.jobs.split_rollup(snap, "tags.kind", fleet.specs[1]["verstr"]) is None
