"""The similar-runs routes serve a malformed ``intent`` log entry's keywords
as a list of strings, whatever the entry holds, so the web UI can render them."""
import os

import pytest
from similar_ui_fixture import TARGET, write_run

pytest.importorskip("fastapi")

FEATURES = {"type": "features", "features_version": 1, "source": "capture",
            "changed": {"files": ["loss.py"], "symbols": ["loss.py::focal_loss"]}}
MALFORMED = {
    "0.0.1-dev.kwstr": "focal loss",
    "0.0.1-dev.kwmixed": [{"a": 1}, 3, None, "focal loss"],
    "0.0.1-dev.kwdict": {"focal": "loss"},
}


@pytest.fixture(params=[False, True], ids=["direct", "index"])
def client(request, tmp_path):
    from fastapi.testclient import TestClient
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = str(tmp_path / "ws1")
    os.makedirs(os.path.join(root, ".vmn"))
    write_run(root, "app1", TARGET, [
        FEATURES, {"type": "intent", "text": "focal loss", "keywords": ["focal loss"]},
    ], second=1)
    for second, (verstr, keywords) in enumerate(MALFORMED.items(), start=2):
        write_run(root, "app1", verstr, [
            FEATURES, {"type": "intent", "text": "focal loss tweak", "keywords": keywords},
        ], second=second)
    manager = WorkspaceManager(str(tmp_path / "ui_data"))
    manager.attach_path("ws1", root)
    return TestClient(create_app(manager, use_index=request.param))


def _intents(response):
    assert response.status_code == 200, response.text
    return {item["verstr"]: item["intent"] for item in response.json()["items"]}


def test_a_malformed_intents_keywords_are_served_as_its_strings_only(client):
    intents = _intents(client.get(f"/api/v1/workspaces/ws1/apps/app1/experiments/{TARGET}/similar"))
    assert {v: intents[v]["keywords"] for v in MALFORMED} == {
        "0.0.1-dev.kwstr": [], "0.0.1-dev.kwmixed": ["focal loss"], "0.0.1-dev.kwdict": [],
    }
    assert all(intents[v]["text"] == "focal loss tweak" for v in MALFORMED)


def test_the_text_route_serves_them_the_same_way(client):
    intents = _intents(client.get("/api/v1/workspaces/ws1/apps/app1/similar",
                                  params={"text": "focal loss tweak"}))
    assert intents["0.0.1-dev.kwmixed"]["keywords"] == ["focal loss"]
    assert intents["0.0.1-dev.kwstr"]["keywords"] == []
