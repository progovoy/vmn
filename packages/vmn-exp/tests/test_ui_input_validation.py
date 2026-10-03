"""Plan 13 §8.1: revision ``base`` and comment ``resolved`` are type-checked."""
import pytest

pytest.importorskip("fastapi")

from report_api_helpers import WS, create_report, make_client

RUN = "run:myapp:1.0.0-dev.abc"


def _save(client, rid, base, body="x"):
    return client.post(f"{WS}/reports/{rid}/revisions", json={"base": base, "body": body})


def test_base_ahead_of_latest_is_a_conflict(tmp_path):
    client = make_client(tmp_path)
    rid = create_report(client, body="one")
    r = _save(client, rid, 100)
    assert r.status_code == 409
    assert r.json()["rev"] == 1 and r.json()["body"] == "one"
    assert [x["rev"] for x in client.get(f"{WS}/reports/{rid}").json()["revisions"]] == [1]
    assert _save(client, rid, 1).json() == {"rev": 2}


@pytest.mark.parametrize("base", [True, False, 1.0, "1"])
def test_base_must_be_an_integer(tmp_path, base):
    client = make_client(tmp_path)
    rid = create_report(client)
    assert _save(client, rid, base).status_code == 400
    assert client.get(f"{WS}/reports/{rid}").json()["rev"] == 1


@pytest.mark.parametrize("resolved", ["false", "true", 0, 1, None])
def test_resolved_must_be_a_boolean(tmp_path, resolved):
    client = make_client(tmp_path)
    r = client.post(f"{WS}/comments", json={"target": RUN, "text": "hi"})
    cid = r.json()["id"]
    r = client.patch(f"{WS}/comments/{RUN}/{cid}", json={"resolved": resolved})
    assert r.status_code == 400
    thread = client.get(f"{WS}/comments", params={"target": RUN}).json()["comments"]
    assert not thread[0].get("resolved")
