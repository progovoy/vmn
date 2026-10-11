"""The similar routes narrow their candidates like ``vmn-exp similar --query
... --archived``: ``q`` (the query language, over status-annotated rows) and
``archived=1`` — what the leaderboard's filters send in its "similar" mode."""
import pytest
from similar_ui_fixture import OTHER, TARGET, TWIN, client_for, write_run

pytest.importorskip("fastapi")

APP1 = "/api/v1/workspaces/ws1/apps/app1"
SHELVED = "0.0.1-dev.shelved"


@pytest.fixture(params=[False, True], ids=["direct", "index"])
def client(request, tmp_path):
    client = client_for(tmp_path, use_index=request.param)
    write_run(str(tmp_path / "ws1"), "app1", SHELVED, second=9, archived=True,
              note="focal loss, shelved")
    return client


def _text(client, **params):
    return client.get(f"{APP1}/similar", params={"text": "focal loss", **params})


def _verstrs(response):
    assert response.status_code == 200, response.text
    return [item["verstr"] for item in response.json()["items"]]


def test_a_text_search_keeps_only_the_runs_its_query_matches(client):
    assert {TARGET, TWIN} <= set(_verstrs(_text(client)))
    assert _verstrs(_text(client, q='note ~ "again"')) == [TWIN]


def test_the_query_sees_each_runs_status(client):
    assert _verstrs(_text(client, q='status = "succeeded"')) == [TWIN]
    assert TWIN not in _verstrs(_text(client, q='status in ("created", "failed")'))


def test_archived_runs_join_a_text_search_only_when_asked(client):
    assert SHELVED not in _verstrs(_text(client))
    assert SHELVED in _verstrs(_text(client, archived=1))
    assert _verstrs(_text(client, archived=1, q='note ~ "shelved"')) == [SHELVED]


def test_a_runs_similar_runs_take_the_query_too(client):
    url = f"{APP1}/experiments/{TARGET}/similar"
    assert OTHER in _verstrs(client.get(url))
    assert _verstrs(client.get(url, params={"q": 'note ~ "bigger"'})) == [OTHER]


def test_the_cross_workspace_text_search_takes_the_query_too(client):
    found = _verstrs(client.get("/api/v1/similar", params={"text": "focal loss",
                                                          "q": 'note ~ "again"'}))
    assert found == [TWIN]


@pytest.mark.parametrize("url", [f"{APP1}/similar", f"{APP1}/experiments/{TARGET}/similar",
                                 "/api/v1/similar"])
def test_a_bad_query_is_400_with_its_message(client, url):
    response = client.get(url, params={"text": "focal loss", "q": "metrics.loss <"})
    assert response.status_code == 400
    assert response.json()["detail"]
