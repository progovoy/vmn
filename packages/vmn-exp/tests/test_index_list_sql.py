"""Plan 25 §2: `vmn-exp list` answers from the persisted ``exp_rows`` —
``--last N`` and the status/parent/archived clauses of ``--query`` narrow
the rows in SQL, and only those rows and their trees are read — printing
exactly what the full-snapshot path printed."""
import datetime
import json

import pytest
from exp_helpers import _exp, _storage
from vmn_exp.core import index as experiment_index
from vmn_exp.core import index_lean_store, index_list, index_list_sql, index_store
from vmn_exp.core import status as experiment_status
from vmn_exp.core.index_snapshot import RowCache

FINISHED = "state: finished\nexit_code: 0\n"
FAILED = "state: finished\nexit_code: 1\n"
OUTER, I1, I2, I2A = (f"0.0.1-dev.tree{i}" for i in range(4))
GONE_PARENT, ORPHAN, ARCHIVED, METRICS, LIVE, CREATED = (
    "0.0.1-dev.gone", "0.0.1-dev.orphan", "0.0.1-dev.archived", "0.0.1-dev.metrics",
    "0.0.1-dev.live", "0.0.1-dev.fresh",
)
FILLER = [f"0.0.1-dev.fill{i:02d}" for i in range(12)]


def _ts(second):
    return f"2026-01-01T00:{second // 60:02d}:{second % 60:02d}Z"


def _iso(delta_sec=0):
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now + datetime.timedelta(seconds=delta_sec)).isoformat().replace("+00:00", "Z")


def _running(heartbeat_age_sec):
    return (f"state: running\nheartbeat: '{_iso(-heartbeat_age_sec)}'\n"
            "heartbeat_interval_sec: 30\npid: 1\nhost: h\n")


def _run(st, app, verstr, second, state=None, note=None, **meta):
    st.save(app, verstr, {"verstr": verstr, "timestamp": _ts(second), **meta}, {})
    st.append_log_entry(app, verstr, "w", {"timestamp": _ts(second), "type": "create",
                                           "note": note or f"made {verstr}"})
    if state:
        st.save_file(app, verstr, "run_state.yml", state)


def _metric(st, app, verstr, second, **values):
    st.append_log_entry(app, verstr, "w",
                        {"timestamp": _ts(second), "type": "metrics", "values": values})


@pytest.fixture
def store(app_layout):
    app, st = app_layout.app_name, _storage(app_layout)
    _run(st, app, OUTER, 10, FINISHED, name="outer")
    _run(st, app, I1, 11, FAILED, parent=OUTER)
    _run(st, app, I2, 12, _running(0), parent=OUTER)
    _run(st, app, I2A, 13, FINISHED, parent=I2)
    _run(st, app, ORPHAN, 14, FAILED, parent=GONE_PARENT)
    _run(st, app, ARCHIVED, 15, FAILED, archived=True)
    _run(st, app, METRICS, 16, FINISHED, note="metric run")
    st.append_log_entry(app, METRICS, "w", {"timestamp": _ts(16), "type": "define_metric",
                                            "name": "loss", "goal": "min"})
    _metric(st, app, METRICS, 17, loss=0.9, acc=0.1)
    _metric(st, app, METRICS, 18, loss=0.4, acc=0.5)
    _run(st, app, LIVE, 19, _running(3600))
    _run(st, app, CREATED, 20)
    for i, verstr in enumerate(FILLER):
        _run(st, app, verstr, 30 + i, FAILED if i % 3 == 0 else FINISHED)
        _metric(st, app, verstr, 30 + i, loss=1.0 / (i + 1))
    return app_layout


def _timeless(out, as_json):
    if not as_json:
        return out
    rows = json.loads(out)
    for row in rows:
        for key in ("stale_sec", "duration_sec"):
            row.pop(key, None)
    return rows


def _list(capfd, layout, *args):
    capfd.readouterr()
    rc = _exp(layout.app_name, action="list", extra_args=list(args))
    out = capfd.readouterr().out
    return rc, _timeless(out, "--json" in args)


def _full_path(monkeypatch):
    monkeypatch.setattr(index_list, "list_view", lambda *a, **kw: None)


CASES = [
    (), ("--json",), ("--last", "3"), ("--last", "3", "--json"), ("--last", "5", "--archived"),
    ("--query", 'status = "failed"'), ("--query", 'status = "failed"', "--json"),
    ("--query", 'status in ("running", "stuck")', "--json"),
    ("--query", f'parent = "{OUTER}"', "--json"), ("--query", 'tree_status = "failed"'),
    ("--query", 'status = "failed" and metrics.loss < 0.5', "--last", "2"),
    ("--query", 'status = "succeeded"', "--sort", "loss", "--top", "2"),
    ("--query", f'under("{OUTER}")', "--json"), ("--query", "archived = true", "--archived"),
    ("--query", 'not status = "failed"', "--json"),
]


@pytest.mark.parametrize("args", CASES)
def test_list_prints_what_the_full_snapshot_printed(store, capfd, monkeypatch, args):
    fast = _list(capfd, store, *args)
    with monkeypatch.context() as m:
        _full_path(m)
        full = _list(capfd, store, *args)
    assert fast == full
    assert fast[0] == 0 and fast[1]


def _no_full_read(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("read every row of the app")

    monkeypatch.setattr(RowCache, "snapshot", refuse)
    monkeypatch.setattr(index_lean_store, "read_lean", refuse)
    monkeypatch.setattr(index_store, "decode_records", refuse)
    monkeypatch.setattr(experiment_index, "_SHARED", {})  # a fresh process


def _counting_reads(monkeypatch):
    read = []
    rows_of = index_list_sql.rows_of

    def counted(conn, app, keys):
        read.extend(keys)
        return rows_of(conn, app, keys)

    monkeypatch.setattr(index_list_sql, "rows_of", counted)
    return read


def test_list_last_reads_only_the_rows_it_shows(store, capfd, monkeypatch):
    with monkeypatch.context() as m:
        _full_path(m)
        before = _list(capfd, store, "--last", "3", "--json")
    _no_full_read(monkeypatch)
    read = _counting_reads(monkeypatch)
    assert _list(capfd, store, "--last", "3", "--json") == before
    assert sorted(read) == sorted(FILLER[-3:])


def test_a_status_query_reads_the_matching_runs_and_their_trees(store, capfd, monkeypatch):
    _list(capfd, store)
    _no_full_read(monkeypatch)
    read = _counting_reads(monkeypatch)
    rc, rows = _list(capfd, store, "--query", 'status = "failed"', "--json")
    assert rc == 0
    assert [r["verstr"] for r in rows] == [I1, ORPHAN] + FILLER[0::3]
    assert set(read) == {I1, OUTER, ORPHAN, *FILLER[0::3]}  # I1's parent for its depth


def test_list_sees_runs_changed_created_and_removed_since(store, capfd, monkeypatch):
    _list(capfd, store)
    _no_full_read(monkeypatch)
    app, st = store.app_name, _storage(store)
    st.update_note(app, FILLER[-1], "edited since")
    _run(st, app, "0.0.1-dev.zlate", 99, FINISHED)
    st.delete(app, FILLER[-2])
    rc, rows = _list(capfd, store, "--last", "2", "--json")
    assert [(r["verstr"], r["note"]) for r in rows] == [
        (FILLER[-1], "edited since"), ("0.0.1-dev.zlate", None)]


def test_a_running_run_gone_stale_since_it_was_indexed_lists_as_stuck(
        store, capfd, monkeypatch):
    _list(capfd, store)
    real_now = experiment_status._now
    later = real_now() + datetime.timedelta(hours=2)
    monkeypatch.setattr(experiment_status, "_now", lambda now=None: now or later)
    _no_full_read(monkeypatch)
    rc, rows = _list(capfd, store, "--query", 'status = "stuck"', "--json")
    assert sorted(r["verstr"] for r in rows) == sorted([I2, LIVE])
