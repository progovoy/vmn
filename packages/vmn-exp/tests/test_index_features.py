"""A run's ``features``, ``intent`` and hypothesis through the experiment index.

They stay off the lean rows the leaderboard pages are made of: the snapshot
keeps them per verstr (``features_of``/``intent_of``/``hypothesis_of``, None
when a run has none), filled the same by the index and by the direct read,
and kept right as logs grow. Rows carry only ``author`` and ``has_intent``,
and the row copies the CLI and reader hand out stay what they were.
"""
import sqlite3

import pytest
from vmn_exp.core.index import (
    ExperimentIndex,
    direct_rows,
    direct_snapshot,
    indexed_snapshot,
    indexed_status_rows,
)
from vmn_exp.core.index_store import SCHEMA_VERSION, IndexStore, SqliteStore
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
A, B = "0.0.1-dev.aaa.r1", "0.0.1-dev.bbb.r2"
AUTHOR = {"writer": "gpu-07", "git_user_email": "a@x.io", "os_user": "alice", "source": "git"}
FACTS = ("features", "intent", "hypothesis")


def _features(ts, version=1, files=("src/loss.py",), author=AUTHOR):
    return {"timestamp": ts, "type": "features", "features_version": version,
            "source": "capture", "author": dict(author), "changed": {"files": list(files)}}


def _intent(ts, text):
    return {"timestamp": ts, "type": "intent", "text": text, "keywords": ["focal loss"],
            "source": "user"}


@pytest.fixture
def st(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")


def _seed(st):
    for verstr, second in ((A, 1), (B, 2)):
        st.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{second}Z"}, {})
    st.append_log_entry(APP, A, "w", {"timestamp": "2026-01-01T00:00:01Z", "type": "create",
                                      "params": {"lr": 0.1}, "hypothesis": "focal loss helps"})
    st.append_log_entry(APP, A, "w", _features("2026-01-01T00:00:02Z"))
    st.append_log_entry(APP, A, "w", _intent("2026-01-01T00:00:03Z", "try focal loss"))
    st.append_log_entry(APP, B, "w", {"timestamp": "2026-01-01T00:00:02Z", "type": "create",
                                      "params": {"lr": 0.2}})


@pytest.fixture(params=["index", "direct"])
def snapshot_of(request, tmp_path):
    if request.param == "index":
        cache = str(tmp_path / "idx.sqlite")
        return lambda st: indexed_snapshot(st, APP, cache_path=cache, wait=True)
    return lambda st: direct_snapshot(st, APP)


def _tables(snap):
    return {v: (snap.features_of(v), snap.intent_of(v), snap.hypothesis_of(v)) for v in (A, B)}


def test_rows_stay_lean_and_the_facts_sit_beside_them(st, snapshot_of):
    _seed(st)
    snap = snapshot_of(st)
    assert all(not set(FACTS) & set(row) for row in snap.rows)
    assert snap.features_of(A) == {"features_version": 1, "source": "capture",
                                   "author": AUTHOR, "changed": {"files": ["src/loss.py"]}}
    assert snap.intent_of(A) == {"text": "try focal loss", "keywords": ["focal loss"],
                                 "source": "user"}
    assert snap.hypothesis_of(A) == "focal loss helps"
    assert (snap.features_of(B), snap.intent_of(B), snap.hypothesis_of(B)) == (None, None, None)
    assert snap.features_of("0.0.1-dev.nope") is None


def test_rows_carry_author_and_has_intent(st, snapshot_of):
    _seed(st)
    rows = {r["verstr"]: r for r in snapshot_of(st).rows}
    assert (rows[A]["author"], rows[A]["has_intent"]) == ("a@x.io", True)
    assert (rows[B]["author"], rows[B]["has_intent"]) == (None, False)


def test_index_and_direct_snapshots_fill_the_same_side_tables(st, tmp_path):
    _seed(st)
    indexed = indexed_snapshot(st, APP, cache_path=str(tmp_path / "idx.sqlite"), wait=True)
    direct = direct_snapshot(st, APP)
    assert _tables(indexed) == _tables(direct)
    assert (indexed.features, indexed.intents, indexed.hypotheses) == (
        direct.features, direct.intents, direct.hypotheses)
    assert list(indexed.rows) == list(direct.rows)


def test_an_incremental_refresh_keeps_the_side_tables_right(st, tmp_path):
    _seed(st)
    cache = str(tmp_path / "idx.sqlite")
    indexed_snapshot(st, APP, cache_path=cache, wait=True)
    st.append_log_entry(APP, A, "h2", _features("2026-01-01T00:00:05Z", files=["new.py"],
                                                author={"os_user": "bob"}))
    st.append_log_entry(APP, A, "h3", _features("2026-01-01T00:00:06Z", version=0))
    st.append_log_entry(APP, A, "w", _intent("2026-01-01T00:00:07Z", ""))  # clears it
    st.append_log_entry(APP, B, "w", _intent("2026-01-01T00:00:04Z", "label smoothing"))
    st.append_log_entry(APP, B, "w", _features("2026-01-01T00:00:05Z", version=2))
    snap = indexed_snapshot(st, APP, cache_path=cache, wait=True)
    assert snap.features_of(A)["changed"] == {"files": ["new.py"]}
    assert snap.intent_of(A) is None
    assert snap.intent_of(B)["text"] == "label smoothing"
    assert snap.features_of(B)["features_version"] == 2
    rows = {r["verstr"]: r for r in snap.rows}
    assert (rows[A]["author"], rows[A]["has_intent"]) == ("bob", False)
    assert (rows[B]["author"], rows[B]["has_intent"]) == ("a@x.io", True)
    assert _tables(snap) == _tables(direct_snapshot(st, APP))
    assert list(snap.rows) == list(direct_snapshot(st, APP).rows)


def test_a_follower_of_the_persisted_cache_serves_the_same_side_tables(st, tmp_path):
    _seed(st)
    db = str(tmp_path / "idx.sqlite")
    leader = ExperimentIndex(st, APP, cache_path=db).refresh().snapshot()
    follower = ExperimentIndex.follower(SqliteStore(db), APP).refresh().snapshot()
    assert _tables(follower) == _tables(leader) == _tables(direct_snapshot(st, APP))
    assert list(follower.rows) == list(leader.rows)


def test_row_copies_are_unchanged_by_the_side_tables(st, tmp_path):
    _seed(st)
    rows, _, _ = indexed_status_rows(st, APP, cache_path=str(tmp_path / "idx.sqlite"))
    assert rows == direct_rows(st, APP)[0]
    assert all(not set(FACTS) & set(row) for row in rows)
    assert [r["author"] for r in rows] == ["a@x.io", None]


def test_index_schema_version_bumped_refolds_old_records(tmp_path):
    assert SCHEMA_VERSION != "exp-index-11"
    path = str(tmp_path / "idx.sqlite")
    IndexStore(path).save("app", {"k": {"verstr": "0.0.1"}}, set(), {})
    conn = sqlite3.connect(path)
    conn.execute("UPDATE exp_index_meta SET v = 'exp-index-11' WHERE k = 'schema'")
    conn.commit()
    conn.close()
    assert IndexStore(path).load("app") == {}
