"""Plan 23 S6 over HTTP: a flat ``.../experiments`` page carries
``next_cursor``, ``cursor=`` answers the page after it, and a cursor from
another sort (or with ``group=``) is the caller's error."""
import pytest

pytest.importorskip("fastapi")
from test_ui_leaderboard_groups_route import BASE, _client, repo  # noqa: F401


def test_cursor_pages_follow_the_order(tmp_path, repo):  # noqa: F811
    root, _ = repo
    client = _client(tmp_path, root)
    want = [r["verstr"] for r in client.get(BASE, params={"sort": "loss", "limit": 50})
            .json()["rows"]]
    got, cursor = [], None
    for _ in range(10):
        params = {"sort": "loss", "limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = client.get(BASE, params=params).json()
        got += [r["verstr"] for r in body["rows"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert got == want and len(want) == 7


def test_a_cursor_from_another_sort_is_a_400(tmp_path, repo):  # noqa: F811
    root, _ = repo
    client = _client(tmp_path, root)
    cursor = client.get(BASE, params={"sort": "loss", "limit": 3}).json()["next_cursor"]
    assert client.get(BASE, params={"limit": 3, "cursor": cursor}).status_code == 400
    assert client.get(BASE, params={"sort": "loss", "limit": 3, "cursor": "!!"}).status_code == 400
    grouped = {"sort": "loss", "group": "parent", "cursor": cursor}
    assert client.get(BASE, params=grouped).status_code == 400
