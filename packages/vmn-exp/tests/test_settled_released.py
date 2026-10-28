"""A released run (plan 28 API2, D2) is waiting (``created``) while its
outer run may still reopen it; once the outer run has ended it settles as
``lost``, not ``never_started``: it ran and never finished. Every place that
settles agrees: the tree annotation, one run's subtree, the fleet, the
board's incremental generations, and the job timeline counts releases per
minute."""
import datetime
import os

from leaderboard_fleet import T0, Fleet, finished, iso, running
from vmn_exp.core.query import filter_rows
from vmn_exp.core.status import CREATED, FAILED, SUCCEEDED, status_fields
from vmn_exp.core.tree import annotate_tree, fleet_summary, subtree_status
from vmn_exp.ui.job_rollup_payload import job_payload
from vmn_exp.ui.job_tally import RollupSpec, Tally
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod

LOST, NEVER = "lost", "never_started"
SPEC = RollupSpec({})


def _released_state(**extra):
    return dict({"state": "released", "exit_code": None, "end_reason": "released",
                 "released_at": iso(T0), "started_at": iso(T0), "resume_count": 2}, **extra)


def _row(verstr, status, parent=None, **fields):
    return dict({"verstr": verstr, "status": status, "parent": parent}, **fields)


def _released(verstr, parent="o"):
    return _row(verstr, CREATED, parent, end_reason="released", released_at=iso(T0))


def test_status_fields_carry_the_release_and_the_attempts():
    fields = status_fields(_released_state(signal="SIGTERM"))
    assert fields["status"] == CREATED
    assert (fields["end_reason"], fields["signal"]) == ("released", "SIGTERM")
    assert (fields["released_at"], fields["resume_count"]) == (iso(T0), 2)


class TestTree:
    def _tree(self, outer_status):
        rows = annotate_tree([_row("o", outer_status), _released("r"), _row("w", CREATED, "o")])
        return {r["verstr"]: r for r in rows}

    def test_a_released_run_under_an_ended_outer_is_lost(self):
        rows = self._tree(SUCCEEDED)
        assert (rows["r"]["settled"], rows["w"]["settled"]) == (LOST, NEVER)
        assert rows["r"]["status"] == CREATED
        assert rows["o"]["tree_status"] == FAILED
        assert [r["verstr"] for r in filter_rows(list(rows.values()), 'settled = "lost"')] == ["r"]

    def test_a_released_run_under_a_running_outer_is_waiting(self):
        rows = self._tree("running")
        assert rows["r"]["settled"] is None

    def test_a_lost_released_container_settles_its_children(self):
        rows = annotate_tree([_row("o", SUCCEEDED), _released("mid"),
                              _row("leaf", CREATED, "mid")])
        assert [r["settled"] for r in rows] == [None, LOST, NEVER]


STATES = {"o": finished(0), "r": _released_state(), "w": None}
PARENT_OF = {"o": None, "r": "o", "w": "o"}


def test_one_runs_subtree_settles_a_released_run_as_lost():
    _, tree = subtree_status("r", PARENT_OF, STATES.get)
    assert tree["settled"] == LOST
    _, outer = subtree_status("o", PARENT_OF, STATES.get)
    assert outer["tree_status"] == FAILED


def test_the_fleet_counts_a_released_run_of_an_ended_outer_as_lost():
    fleet = fleet_summary("o", {"o": ["r", "w"]}, STATES.get, closed=True)
    assert (fleet[LOST], fleet[NEVER]) == (1, 1)
    open_fleet = fleet_summary("o", {"o": ["r", "w"]}, STATES.get)
    assert open_fleet["counts"][CREATED] == 2


def test_the_board_settles_a_released_run_when_its_outer_ends(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(5)
    for _ in range(100):
        fleet.append(state=finished(0))
    outer = fleet.append(state=running(T0))
    released = fleet.append(parent=outer, state=_released_state())
    cache = LeaderboardCache()
    assert cache.job_rollup(fleet.snapshot(), {}, outer)["counts"]["waiting"] == 1

    fleet.set_state(fleet.index(outer), finished(0))
    snap = fleet.snapshot()
    rollup = cache.job_rollup(snap, {}, outer)
    assert (rollup[LOST], rollup[NEVER]) == (1, 0)
    rows = {r["verstr"]: r for r in cache.rows(snap, archived=True)}
    assert rows[released]["settled"] == LOST
    fresh = {r["verstr"]: r["settled"] for r in LeaderboardCache().rows(snap, archived=True)}
    assert fresh[released] == LOST


def _timeline_row(n, released_ago=None, status=CREATED):
    row = {"verstr": f"v{n}", "parent": "job", "status": status, "metrics": {},
           "started_at": iso(T0 - datetime.timedelta(seconds=900))}
    if released_ago is not None:
        row["released_at"] = iso(T0 - datetime.timedelta(seconds=released_ago))
    return row


def test_the_job_timeline_counts_releases_per_minute():
    rows = [_timeline_row(0, 120), _timeline_row(1, 100), _timeline_row(2, 60, "running"),
            _timeline_row(3)]
    tally = Tally.of(rows, SPEC)
    buckets = job_payload({"verstr": "job", "params": {}}, [tally], SPEC, T0)["timeline"]["buckets"]
    minute = int((T0 - datetime.timedelta(seconds=120)).timestamp() // 60) * 60
    by_t = {b["t"]: b for b in buckets}
    assert by_t[minute]["released"] == 2
    assert sum(b.get("released", 0) for b in buckets) == 3  # a retried run's last release too
    tally.add(rows[0], SPEC, by=-1)
    again = job_payload({"verstr": "job", "params": {}}, [tally], SPEC, T0)["timeline"]["buckets"]
    assert {b["t"]: b for b in again}[minute]["released"] == 1


def test_the_query_suggestions_know_the_release_fields():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(root, "vmn-exp", "webui", "src", "util", "querySuggest.ts")
    with open(path) as f:
        fields = f.read().split("ROW_FIELDS = [", 1)[1].split("]", 1)[0]
    assert '"released_at"' in fields and '"resume_count"' in fields
