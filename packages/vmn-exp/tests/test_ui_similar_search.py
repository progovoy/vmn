"""``GET /api/v1/similar?text=``: a free-text similar-runs query over every app
of every workspace the caller may view (plan 18, next to ``/api/v1/search``)."""
import pytest
from similar_ui_fixture import CROSS, OTHER, SMOOTH, TARGET, TWIN, client_for

pytest.importorskip("fastapi")

from vmn_exp.ui.auth import AuthenticatorChain
from vmn_exp.ui.auth.principal import VIEWER, Principal

SIMILAR = "/api/v1/similar"


class _Fixed:
    PRINCIPALS = {
        "Bearer one": Principal("one", "one", {"ws1": VIEWER}),
        "Bearer two": Principal("two", "two", {"ws2": VIEWER}),
        "Bearer all": Principal("all", "all", {"*": VIEWER}),
        "Bearer none": Principal("none", "none", {}),
    }

    def authenticate(self, request):
        return self.PRINCIPALS.get(request.headers.get("Authorization", ""))


def _hits(response):
    assert response.status_code == 200, response.text
    return [(i["workspace"], i["app"], i["verstr"]) for i in response.json()["items"]]


def _get(client, text, who=None, **params):
    headers = {"Authorization": f"Bearer {who}"} if who else {}
    return client.get(SIMILAR, params={"text": text, **params}, headers=headers)


def test_text_spans_every_workspace(tmp_path):
    client = client_for(tmp_path)
    hits = _hits(_get(client, "focal loss"))
    assert {("ws1", "app1", TARGET), ("ws1", "app1", TWIN), ("ws1", "app2", CROSS)} <= set(hits)
    assert ("ws1", "app1", OTHER) not in hits
    assert _hits(_get(client, "label smoothing")) == [("ws2", "app3", SMOOTH)]


def test_an_item_names_its_workspace_and_status(tmp_path):
    item = _get(client_for(tmp_path), "label smoothing").json()["items"][0]
    assert item["status"] == "created"
    assert item["intent"]["text"] == "Label smoothing on imagenet"
    assert item["reasons"]


def test_top_truncates(tmp_path):
    body = _get(client_for(tmp_path), "focal loss", top=1).json()
    assert len(body["items"]) == 1 and body["truncated"] is True


@pytest.mark.parametrize("text", ["", "  ", "y" * 4097], ids=["empty", "blank", "oversized"])
def test_a_missing_or_oversized_text_is_400(tmp_path, text):
    assert _get(client_for(tmp_path), text).status_code == 400


@pytest.mark.parametrize("top", [0, 101])
def test_a_top_out_of_range_is_400(tmp_path, top):
    assert _get(client_for(tmp_path), "focal", top=top).status_code == 400


def test_only_the_callers_workspaces_are_searched(tmp_path):
    client = client_for(tmp_path, auth=AuthenticatorChain([_Fixed()]))
    one = _hits(_get(client, "focal loss label smoothing", who="one"))
    assert one and {ws for ws, _, _ in one} == {"ws1"}
    two = _hits(_get(client, "focal loss label smoothing", who="two"))
    assert two == [("ws2", "app3", SMOOTH)]
    every = _hits(_get(client, "focal loss label smoothing", who="all"))
    assert {ws for ws, _, _ in every} == {"ws1", "ws2"}
    assert _get(client, "focal", who="none").status_code == 403
