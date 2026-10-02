"""Plan 13 §8.1: the /comments routes."""
import pytest

pytest.importorskip("fastapi")

from report_api_helpers import WS, create_report, make_client, user

RUN = "run:myapp:1.0.0-dev.abc"


def _post(client, target=RUN, text="hello", headers=None, **extra):
    r = client.post(f"{WS}/comments", json={"target": target, "text": text, **extra},
                    headers=headers or {})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _thread(client, target=RUN, headers=None):
    r = client.get(f"{WS}/comments", params={"target": target}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["comments"]


def test_post_and_get_run_thread(tmp_path):
    client = make_client(tmp_path)
    cid = _post(client)
    reply = _post(client, text="re", reply_to=cid, anchor={"panel": "p1"})
    comments = _thread(client)
    assert [c["id"] for c in comments] == [cid, reply]
    assert comments[1]["reply_to"] == cid and comments[1]["anchor"] == {"panel": "p1"}


def test_report_thread(tmp_path):
    client = make_client(tmp_path)
    rid = create_report(client)
    _post(client, target=f"report:{rid}", text="nice")
    assert [c["text"] for c in _thread(client, f"report:{rid}")] == ["nice"]


def test_bad_target_400(tmp_path):
    client = make_client(tmp_path)
    assert client.get(f"{WS}/comments", params={"target": "bogus"}).status_code == 400
    r = client.post(f"{WS}/comments", json={"target": "run:onlyapp", "text": "x"})
    assert r.status_code == 400
    assert client.post(f"{WS}/comments", json={"target": RUN, "text": ""}).status_code == 400


def test_patch_text_resolved_and_delete(tmp_path):
    client = make_client(tmp_path)
    cid = _post(client)
    assert client.patch(f"{WS}/comments/{RUN}/{cid}", json={"text": "edited"}).status_code == 200
    assert client.patch(f"{WS}/comments/{RUN}/{cid}", json={"resolved": True}).status_code == 200
    got = _thread(client)[0]
    assert got["text"] == "edited" and got["resolved"] is True
    assert client.delete(f"{WS}/comments/{RUN}/{cid}").status_code == 200
    assert _thread(client)[0]["deleted"] is True


def test_patch_unknown_comment_404(tmp_path):
    client = make_client(tmp_path)
    assert client.patch(f"{WS}/comments/{RUN}/cnope", json={"text": "x"}).status_code == 404


def test_author_or_admin(tmp_path):
    client = make_client(tmp_path, auth=True)
    cid = _post(client, headers=user("alice", "editor"))
    assert _thread(client, headers=user("v", "viewer"))[0]["author"]["id"] == "alice"
    bob = user("bob", "editor")
    assert client.patch(f"{WS}/comments/{RUN}/{cid}", json={"text": "x"}, headers=bob).status_code == 403
    assert client.delete(f"{WS}/comments/{RUN}/{cid}", headers=bob).status_code == 403
    alice = user("alice", "editor")
    assert client.patch(f"{WS}/comments/{RUN}/{cid}", json={"text": "mine"}, headers=alice).status_code == 200
    assert client.delete(f"{WS}/comments/{RUN}/{cid}", headers=user("root", "admin")).status_code == 200


def test_viewer_cannot_post(tmp_path):
    client = make_client(tmp_path, auth=True)
    r = client.post(f"{WS}/comments", json={"target": RUN, "text": "x"}, headers=user("v", "viewer"))
    assert r.status_code == 403


def test_read_only_refuses_mutations(tmp_path):
    cid = _post(make_client(tmp_path))
    client = make_client(tmp_path, read_only=True)
    assert client.post(f"{WS}/comments", json={"target": RUN, "text": "x"}).status_code == 403
    assert client.patch(f"{WS}/comments/{RUN}/{cid}", json={"text": "x"}).status_code == 403
    assert client.delete(f"{WS}/comments/{RUN}/{cid}").status_code == 403
    assert len(_thread(client)) == 1


def test_foreign_origin_refused(tmp_path):
    client = make_client(tmp_path)
    r = client.post(f"{WS}/comments", json={"target": RUN, "text": "x"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
