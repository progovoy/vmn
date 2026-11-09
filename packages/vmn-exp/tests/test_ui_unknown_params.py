"""An API request with a query parameter its route does not accept answers 400
naming it (with a "did you mean" when one is close) instead of ignoring it;
the web page and unknown API paths are not affected."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

API = "/api/v1"
BASE = f"{API}/workspaces/ws/apps/my_app"


@pytest.fixture
def client(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    v = "0.0.1-dev.0000abcd.0"
    open_storage(uri, area=RUNS).save("my_app", v, {"verstr": v}, {})
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", uri)
    return TestClient(create_app(manager, background_refresh=False))


def test_an_unknown_param_is_refused_with_a_suggestion(client):
    resp = client.get(f"{BASE}/experiments", params={"limt": "5"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Unknown query parameter 'limt'; did you mean 'limit'?"


def test_an_unknown_param_far_from_any_is_refused_without_a_suggestion(client):
    resp = client.get(f"{API}/workspaces", params={"zzzzzz": "1"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Unknown query parameter 'zzzzzz'"


def test_accepted_params_still_answer(client):
    assert client.get(f"{BASE}/experiments", params={"limit": "5", "q": ""}).status_code == 200


def test_a_route_without_params_refuses_any(client):
    resp = client.get(f"{API}/meta", params={"x": "1"})

    assert resp.status_code == 400
    assert "'x'" in resp.json()["detail"]


def test_the_events_stream_accepts_scope_and_refuses_others(client):
    resp = client.get(f"{BASE}/events", params={"scop": "x"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Unknown query parameter 'scop'; did you mean 'scope'?"


def test_the_web_page_params_keep_their_hint(client):
    resp = client.get(f"{BASE}/experiments", params={"view": "jobs", "limt": "1"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "view is a web page parameter; use top=jobs or q=…"


def test_an_unknown_api_path_is_still_a_404(client):
    assert client.get(f"{API}/no-such-route", params={"x": "1"}).status_code == 404


def test_the_web_page_ignores_params(client):
    resp = client.get("/experiments", params={"view": "jobs", "anything": "1"})

    assert resp.status_code != 400
