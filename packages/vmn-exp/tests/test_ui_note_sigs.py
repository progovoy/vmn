"""Plan 28 N7 on the board: a run's note signatures (the snapshot's
``note_sigs`` side table) give board rows ``note_sig`` (the latest) and
``note_minutes``; a failed run without an ``error_summary`` clusters by its
latest note signature; a job's timeline counts signatures per minute
(``notes``); scoped facets list the top 20 signatures (``note_sigs``)."""
import datetime

import pytest
from leaderboard_fleet import T0, finished, iso
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.log import experiment_row
from vmn_exp.core.query import QueryError
from vmn_exp.ui.failure_signature import label, signature, signed
from vmn_exp.ui.job_rollup_payload import job_payload
from vmn_exp.ui.job_tally import RollupSpec, Tally
from vmn_exp.ui.leaderboard_answers import TOP_NOTE_SIGS
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.query_sql import compile_sql

from vmn_exp.core import status as status_mod

SIGTERM = "Received SIGTERM at step <n>"
OOM = "OOMKilled, retry <n>"


def _at(minutes_ago):
    return iso(T0 - datetime.timedelta(minutes=minutes_ago))


def _sigs(**sigs):
    """``{sig: {count, last_at}}`` from ``name=(count, minutes ago)``."""
    names = {"sigterm": SIGTERM, "oom": OOM}
    return {names.get(k, k): {"count": n, "last_at": _at(ago)} for k, (n, ago) in sigs.items()}


def test_a_failed_run_without_an_error_summary_clusters_by_its_latest_note():
    row = {"verstr": "a", "status": "failed", "exit_code": 143}
    signed(row, _sigs(oom=(1, 9), sigterm=(2, 3)))
    assert row["note_sig"] == SIGTERM
    assert row["failure_sig"] == f"failed | exit=143 | note={SIGTERM}"
    assert label(row["failure_sig"]) == f"Last note: {SIGTERM} (exit 143)"
    other = signed({"verstr": "b", "status": "failed", "exit_code": 143},
                   _sigs(sigterm=(1, 50)))
    assert other["failure_sig"] == row["failure_sig"]


def test_an_error_summary_still_beats_the_notes():
    row = signed({"verstr": "a", "status": "failed", "exit_code": 1,
                  "error_summary": "boom 3"}, _sigs(sigterm=(1, 3)))
    assert row["failure_sig"] == "failed | exit=1 | msg=boom <n>"


def test_notes_never_make_a_healthy_run_a_failure():
    row = signed({"verstr": "a", "status": "succeeded"}, _sigs(sigterm=(1, 3)))
    assert row["failure_sig"] is None and row["note_sig"] == SIGTERM


def test_a_run_without_notes_gets_no_note_fields():
    row = signed({"verstr": "a", "status": "failed", "exit_code": 1})
    assert "note_sig" not in row and "note_minutes" not in row
    assert row["failure_sig"] == signature(row) == "failed | exit=1"


def _minute_t(ago):
    return int((T0 - datetime.timedelta(minutes=ago)).timestamp() // 60) * 60


def _timeline(rows):
    spec = RollupSpec({})
    return job_payload({"verstr": "job", "params": {}}, [Tally.of(rows, spec)], spec,
                       T0)["timeline"]


def _job_row(n, sigs):
    return signed({"verstr": f"v{n}", "parent": "job", "status": "running",
                   "metrics": {}, "started_at": _at(30)}, sigs)


def test_the_timeline_counts_signatures_by_the_minute_they_were_last_seen():
    rows = [_job_row(0, _sigs(sigterm=(5, 3), oom=(1, 10))), _job_row(1, _sigs(sigterm=(1, 3))),
            _job_row(2, None)]
    buckets = {b["t"]: b for b in _timeline(rows)["buckets"]}
    assert buckets[_minute_t(3)]["notes"] == 2
    assert buckets[_minute_t(10)]["notes"] == 1
    assert "notes" not in buckets[_minute_t(30)]
    spec = RollupSpec({})
    tally = Tally.of(rows, spec)
    tally.add(rows[0], spec, by=-1)
    assert _timeline(rows[1:])["buckets"] == job_payload(
        {"verstr": "job", "params": {}}, [tally], spec, T0)["timeline"]["buckets"]


def _snap(note_sigs):
    rows, states = [], {}
    for i, verstr in enumerate(["job", *note_sigs], 1):
        meta = {"verstr": verstr, "timestamp": _at(60 - i), "branch": "main"}
        if verstr != "job":
            meta["parent"] = "job"
        rows.append(experiment_row(i, meta, []))
        states[verstr] = finished(143 if verstr.startswith("f") else 0)
    sides = {v: s for v, s in note_sigs.items() if s}
    return IndexSnapshot.build("app", 1, rows, states, note_sigs=sides)


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def test_board_rows_carry_the_note_fields_and_cluster_failures_by_them(now):
    snap = _snap({"f1": _sigs(sigterm=(1, 3)), "f2": _sigs(sigterm=(2, 4)), "ok": None})
    rows = {r["verstr"]: r for r in LeaderboardCache().page(snap, {}, limit=10)["rows"]}
    assert rows["f1"]["note_sig"] == SIGTERM
    assert rows["f1"]["failure_sig"] == rows["f2"]["failure_sig"]
    assert "note_sig" not in rows["ok"]


def test_scoped_facets_list_the_top_signatures_by_runs(now):
    many = {f"r{i}": _sigs(**{f"sig {chr(97 + i % 26)}{i // 26}": (1, 5)}) for i in range(30)}
    snap = _snap({"f1": _sigs(sigterm=(3, 3), oom=(1, 9)), "f2": _sigs(sigterm=(1, 4)),
                  "ok": None, **many})
    got = LeaderboardCache().facets(snap, scope="job")["note_sigs"]
    assert len(got) == TOP_NOTE_SIGS == 20
    assert got[0] == {"sig": SIGTERM, "runs": 2, "count": 4}
    assert got[1] == {"sig": OOM, "runs": 1, "count": 1}
    filtered = LeaderboardCache().facets(snap, scope="job", status="failed")["note_sigs"]
    assert [s["sig"] for s in filtered] == [SIGTERM, OOM]


def test_scoped_facets_without_notes_have_no_signatures(now):
    snap = _snap({"a": None, "b": None})
    assert "note_sigs" not in LeaderboardCache().facets(snap, scope="job")


def test_the_sql_backend_refuses_notes():
    with pytest.raises(QueryError):
        compile_sql('notes ~ "sigterm"')
