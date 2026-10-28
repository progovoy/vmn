"""Plan 28 §4.5 over HTTP: ``experiments-columns`` takes the Jobs view's
``top``, ``top_q`` and ``match_subtree``, so a select-all on a Live or
Review page selects the outer runs the page shows, not every run ``q``
matches; and ``top_q`` reads ``live_below``."""
import pytest

pytest.importorskip("fastapi")
from test_ui_search_index_route import APP, _verstr, client  # noqa: F401

URL = f"/api/v1/workspaces/ws/apps/{APP}/experiments-columns"
PAGE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"
OUTERS = 'kind = "outer"'


def _verstrs(client, params):  # noqa: F811
    return client.get(URL, params=params).json()["verstrs"]


def test_top_keeps_the_top_level_runs(client):  # noqa: F811
    assert set(_verstrs(client, {"top": 1})) == {_verstr(1), _verstr(4)}


def test_top_q_keeps_the_outer_runs(client):  # noqa: F811
    assert _verstrs(client, {"top": 1, "top_q": OUTERS}) == [_verstr(1)]


def test_match_subtree_keeps_the_trees_q_matches(client):  # noqa: F811
    params = {"top": 1, "match_subtree": 1, "q": 'name ~ "t2"'}
    assert _verstrs(client, params) == [_verstr(1)]


def test_the_columns_are_the_pages_rows(client):  # noqa: F811
    params = {"top": 1, "top_q": "live_below = 0", "limit": 50}
    page = client.get(PAGE, params=params).json()
    assert _verstrs(client, params) == [r["verstr"] for r in page["rows"]]


def test_top_q_without_top_is_a_400(client):  # noqa: F811
    assert client.get(URL, params={"top_q": OUTERS}).status_code == 400
