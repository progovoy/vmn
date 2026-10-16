"""``GET .../experiments/{verstr}/similar`` and ``GET .../apps/{app}/similar?text=``:
the runs most like a run, or like a text, in its app or (``all_apps``) every
app of its workspace (plan 18)."""
import pytest
from similar_ui_fixture import (
    ARCHIVED,
    CROSS,
    LONG_INTENT,
    OTHER,
    RERUN,
    SMOOTH,
    TARGET,
    TWIN,
    client_for,
)

pytest.importorskip("fastapi")

APP1 = "/api/v1/workspaces/ws1/apps/app1"


@pytest.fixture(params=[False, True], ids=["direct", "index"])
def client(request, tmp_path):
    return client_for(tmp_path, use_index=request.param)


def _similar(client, verstr=TARGET, **params):
    return client.get(f"{APP1}/experiments/{verstr}/similar", params=params)


def _text(client, text, **params):
    return client.get(f"{APP1}/similar", params={"text": text, **params})


def _verstrs(response):
    assert response.status_code == 200, response.text
    return [item["verstr"] for item in response.json()["items"]]


def test_a_runs_twin_ranks_first_and_its_own_code_is_left_out(client):
    found = _verstrs(_similar(client))
    assert found[0] == TWIN
    assert TARGET not in found and RERUN not in found
    assert CROSS not in found  # another app: only with all_apps


def test_an_item_carries_who_when_how_it_did_and_why(client):
    item = _similar(client).json()["items"][0]
    assert item["workspace"] == "ws1" and item["app"] == "app1"
    assert item["name"] == "twin" and item["note"] == "focal loss again"
    assert item["author"] == "bob@x.io"
    assert item["timestamp"].startswith("2026-09-21T12:00:02")
    assert item["status"] == "succeeded"
    assert item["goal"] == {"metric": "loss", "goal": "min", "value": 0.3}
    assert 0 < item["score"] <= 1 and item["group_size"] == 1
    assert any("focal_loss" in reason for reason in item["reasons"])
    assert item["signals"]["files"] == 1.0
    assert "row" not in item and "features" not in item


def test_an_intent_is_served_as_a_2kb_excerpt(client):
    intent = _similar(client).json()["items"][0]["intent"]
    assert intent["keywords"] == ["focal loss"]
    assert intent["truncated"] is True
    assert len(intent["text"].encode()) <= 2048
    assert LONG_INTENT.startswith(intent["text"])
    other = next(i for i in _similar(client).json()["items"] if i["verstr"] == OTHER)
    assert other["intent"] is None


def test_top_cuts_the_list_and_says_more_matched(client):
    body = _similar(client, top=1).json()
    assert [i["verstr"] for i in body["items"]] == [TWIN]
    assert body["truncated"] is True
    assert _similar(client, top=100).json()["truncated"] is False


def test_archived_runs_show_only_when_asked(client):
    assert ARCHIVED not in _verstrs(_similar(client))
    assert ARCHIVED in _verstrs(_similar(client, archived=1))


def test_all_apps_looks_in_every_app_of_the_workspace(client):
    items = _similar(client, all_apps=1).json()["items"]
    assert ("app2", CROSS) in [(i["app"], i["verstr"]) for i in items]
    assert SMOOTH not in [i["verstr"] for i in items]  # another workspace


def test_an_unknown_run_is_404(client):
    response = _similar(client, "0.0.9-dev.nope")
    assert response.status_code == 404
    assert "0.0.9-dev.nope" in response.json()["detail"]


@pytest.mark.parametrize("top", [0, 101, -3])
def test_a_top_out_of_range_is_400(client, top):
    assert _similar(client, top=top).status_code == 400
    assert _text(client, "focal", top=top).status_code == 400


def test_an_unsafe_verstr_or_app_is_400(client):
    assert _similar(client, "a%5Cb").status_code == 400
    assert client.get("/api/v1/workspaces/ws1/apps/..-x/similar?text=a").status_code == 400


def test_an_unknown_workspace_is_404(client):
    assert client.get(f"/api/v1/workspaces/nope/apps/app1/experiments/{TARGET}/similar").status_code == 404


def test_an_unchanged_answer_is_304(client):
    first = _similar(client)
    again = client.get(f"{APP1}/experiments/{TARGET}/similar",
                       headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


def test_text_finds_runs_by_intent_and_note(client):
    found = _verstrs(_text(client, "focal loss"))
    assert set(found[:2]) == {TARGET, TWIN}
    assert OTHER not in found
    item = _text(client, "focal loss").json()["items"][0]
    assert item["reasons"] and set(item["signals"]) == {"text"}


def test_text_all_apps_spans_the_workspace_only(client):
    found = _verstrs(_text(client, "focal loss", all_apps=1))
    assert CROSS in found and SMOOTH not in found


@pytest.mark.parametrize("text", ["", "   ", "x" * 4097], ids=["empty", "blank", "oversized"])
def test_a_missing_or_oversized_text_is_400(client, text):
    assert _text(client, text).status_code == 400


def test_a_text_of_stopwords_finds_nothing(client):
    assert _verstrs(_text(client, "the and of")) == []


def test_without_fts5_the_similar_routes_say_so(client, monkeypatch):
    from vmn_exp.core import similar_fts

    monkeypatch.setattr(similar_fts, "_FTS5", [False])
    for response in (_similar(client), _text(client, "focal")):
        assert response.status_code == 501
        assert "SQLite with FTS5" in response.json()["detail"]
