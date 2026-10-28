"""Plan 28 FS + N4 over HTTP: the list endpoint sorts and filters by
``duration_ratio`` and ``queue_sec``, and the ratio compares siblings by
the app's ``experiment.ui.split_by`` when its conf sets one."""
import pytest
from test_ui_job_split_route import _client, _conf, _record, _verstr

pytest.importorskip("fastapi")

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"


@pytest.fixture
def repo(tmp_path):
    """r1 launches r2-r6 trials (2-6 min), r7-r9 refits (7-9 min), r10 untagged (10 min)."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    root = str(root)
    _record(root, 1, kind="launch")
    for n in range(2, 7):
        _record(root, n, kind="trial", parent=1)
    for n in range(7, 10):
        _record(root, n, kind="refit", parent=1)
    _record(root, 10, parent=1)
    return root


def _rows(client, **params):
    resp = client.get(BASE, params=dict(limit=100, **params))
    assert resp.status_code == 200, resp.text
    return resp.json()["rows"]


def _ratio(rows, n):
    return next(r["duration_ratio"] for r in rows if r["verstr"] == _verstr(n))


def test_siblings_are_the_parents_children_without_a_split(tmp_path, repo):
    client = _client(tmp_path, repo)
    rows = _rows(client, sort="duration_ratio", order="desc")
    assert rows[0]["verstr"] == _verstr(10)
    assert _ratio(rows, 9) == pytest.approx(540 / 360, rel=0.02)
    assert _ratio(rows, 1) is None and rows[-1]["verstr"] == _verstr(1)
    assert [r["verstr"] for r in _rows(client, q="duration_ratio > 1.4")] == [
        _verstr(n) for n in (9, 10)]


def test_the_apps_split_compares_refits_with_refits(tmp_path, repo):
    _conf(repo, {"ui": {"split_by": "tags.kind"}})
    rows = _rows(_client(tmp_path, repo), sort="duration_ratio", order="desc")
    assert rows[0]["verstr"] == _verstr(6)  # 360 s over the trials' 240 s
    assert _ratio(rows, 9) == pytest.approx(540 / 480, rel=0.02)
    assert _ratio(rows, 10) is None  # alone in its value


def test_rows_carry_queue_time_and_sort_by_a_tag(tmp_path, repo):
    client = _client(tmp_path, repo)
    rows = _rows(client, sort="tags.kind")
    assert [r["tags"].get("kind") for r in rows][:2] == ["launch", "refit"]
    assert rows[-1]["verstr"] == _verstr(10)
    assert {r["queue_sec"] for r in rows} == {0}
    assert len(_rows(client, q="queue_sec >= 0", sort="queue_sec", order="desc")) == 10
