"""An intent excerpt — one implementation for ``vmn-exp similar --json``, the
SDK reader and the UI routes — never raises on a lone surrogate (only a
hand-written log holds one: ``build_intent_entry`` refuses it): it is served
as ``?``, so one bad run never breaks its neighbours' similar answers."""
import pytest
from similar_ui_fixture import FOCAL, TARGET, _features, write_run
from vmn_exp.core.similar_search import INTENT_EXCERPT_BYTES, intent_excerpt

SURROGATE_TEXT = "focal \ud800 loss"
SURROGATE_RUN = "0.0.1-dev.surrogate"


def test_a_lone_surrogate_in_an_intent_text_is_served_as_a_question_mark():
    excerpt = intent_excerpt({"text": SURROGATE_TEXT, "keywords": ["focal loss"]})
    assert excerpt["text"] == "focal ? loss"
    assert excerpt["keywords"] == ["focal loss"]


def test_a_long_text_of_surrogates_is_cut_within_the_limit():
    excerpt = intent_excerpt({"text": "\udc80" * (INTENT_EXCERPT_BYTES + 10)})
    assert excerpt["text"] == "?" * INTENT_EXCERPT_BYTES
    assert excerpt["truncated"] is True


@pytest.fixture(params=[False, True], ids=["direct", "index"])
def client(request, tmp_path):
    pytest.importorskip("fastapi")
    from similar_ui_fixture import client_for

    client = client_for(tmp_path, use_index=request.param)
    intent = {"type": "intent", "text": SURROGATE_TEXT, "source": "user"}
    write_run(str(tmp_path / "ws1"), "app1", SURROGATE_RUN, [_features(*FOCAL), intent],
              second=9)
    return client


def _surrogate_item(response):
    assert response.status_code == 200, response.text
    [item] = [i for i in response.json()["items"] if i["verstr"] == SURROGATE_RUN]
    return item


def test_the_ui_serves_a_runs_similar_runs_past_a_surrogate_intent(client):
    item = _surrogate_item(client.get(
        f"/api/v1/workspaces/ws1/apps/app1/experiments/{TARGET}/similar"))
    assert item["intent"] == {"text": "focal ? loss", "keywords": [], "truncated": False}


@pytest.mark.parametrize("path", ["/api/v1/workspaces/ws1/apps/app1/similar", "/api/v1/similar"])
def test_the_ui_text_routes_serve_a_surrogate_intent_too(client, path):
    item = _surrogate_item(client.get(path, params={"text": "focal loss"}))
    assert item["intent"]["text"] == "focal ? loss"
