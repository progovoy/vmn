"""A lone surrogate already stored in a run (a hand-written log, an intent
keyword from before ``build_intent_entry`` refused them) reads as ``?`` on
every way out of similar runs — the JSON items of ``vmn-exp similar``, the
submission hint and the SDK reader, their text lines, the UI routes and the
UI's JSON renderer — so one bad string never fails a combined answer."""
import json

import pytest
from exp_helpers import _bootstrap, _exp, _storage
from similar_fixtures import FakeSnapshot, changed, run
from similar_seed import TRAIN_STEP, features, seed, verstr
from vmn_exp.core.similar_search import intent_excerpt, search

BAD = "focal \ud800 loss"
SHOWN = "focal ? loss"
SURROGATE_RUN = "0.0.1-dev.surrogate"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _all_utf8(value):
    for text in _strings(value):
        text.encode("utf-8")
    return True


def test_an_intent_excerpts_keywords_and_generator_read_question_marks():
    excerpt = intent_excerpt({"text": "focal loss", "keywords": [BAD, "ok"],
                              "generator": "model \udc80"})
    assert excerpt["keywords"] == [SHOWN, "ok"]
    assert excerpt["generator"] == "model ?"


def test_every_string_of_a_search_item_is_utf8():
    metric = "val\ud800loss"
    row = run("a", name="sweep \ud800", note="note \ud800", tags={"k\ud800": "v\ud800"},
              branch="feat/\ud800", metrics={metric: 0.3})
    snap = FakeSnapshot(
        [row], features={"a": changed(["tr\ud800in.py"], ["tr\ud800in.py::step"])},
        intents={"a": {"text": BAD, "keywords": [BAD], "generator": "m\ud800"}},
        declared={metric: {"goal": "min"}})
    target = {"row": run("t", branch="feat/\ud800", metrics={metric: 0.4}),
              "features": changed(["tr\ud800in.py"], ["tr\ud800in.py::step"]),
              "intent": {"text": "focal loss", "keywords": [BAD]}}

    [item] = search(None, "app", snap, target)

    assert _all_utf8(item)
    json.dumps(item, ensure_ascii=False).encode("utf-8")
    assert item["goal"]["metric"] == "val?loss"
    assert item["intent"]["keywords"] == [SHOWN]
    assert any(SHOWN in reason for reason in item["reasons"])


@pytest.fixture(params=["orjson", "stdlib"])
def renderer(request, monkeypatch):
    pytest.importorskip("fastapi")
    from vmn_exp.ui import responses

    if request.param == "orjson":
        pytest.importorskip("orjson")
    else:
        monkeypatch.setattr(responses, "orjson", None)
    return responses.render_json


def test_the_ui_renderer_writes_a_lone_surrogate_as_a_question_mark(renderer):
    body = renderer({"reason": "shared: " + BAD, "x": float("nan")})
    assert json.loads(body) == {"reason": "shared: " + SHOWN, "x": None}


@pytest.fixture(params=[False, True], ids=["direct", "index"])
def client(request, tmp_path):
    pytest.importorskip("fastapi")
    from similar_ui_fixture import FOCAL, _features, client_for, write_run

    client = client_for(tmp_path, use_index=request.param)
    intent = {"type": "intent", "text": "focal loss tweak", "keywords": [BAD], "source": "user"}
    write_run(str(tmp_path / "ws1"), "app1", SURROGATE_RUN, [_features(*FOCAL), intent],
              second=9)
    return client


@pytest.mark.parametrize("path, params", [
    ("/api/v1/workspaces/ws1/apps/app1/experiments/0.0.1-dev.target/similar", {}),
    ("/api/v1/workspaces/ws1/apps/app1/similar", {"text": "focal loss"}),
    ("/api/v1/similar", {"text": "focal loss"}),
], ids=["run", "app-text", "global-text"])
def test_every_ui_similar_route_serves_a_stored_surrogate_keyword(client, path, params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    [item] = [i for i in response.json()["items"] if i["verstr"] == SURROGATE_RUN]
    assert item["intent"]["keywords"] == [SHOWN]
    assert any(SHOWN in reason for reason in item["reasons"])


@pytest.mark.parametrize("as_json", [True, False], ids=["json", "text"])
def test_vmn_exp_similar_prints_a_stored_surrogate_keyword(app_layout, capfd, as_json):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    changes = features(["train.py"], [TRAIN_STEP])
    target = seed(storage, app, verstr(1), changes=changes,
                  intent={"text": "focal loss", "keywords": ["focal loss"]})
    seed(storage, app, verstr(2), changes=changes, intent={"text": "focal", "keywords": [BAD]})
    capfd.readouterr()

    code = _exp(app, action="similar", extra_args=["-v", target] + (["--json"] if as_json else []))

    out = capfd.readouterr()
    assert code == 0, out.err
    if as_json:
        [item] = json.loads(out.out)
        assert item["intent"]["keywords"] == [SHOWN]
    assert SHOWN in out.out
