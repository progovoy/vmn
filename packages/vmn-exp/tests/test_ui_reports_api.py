"""Plan 13 §8.1: the /reports routes."""
import pytest

pytest.importorskip("fastapi")

from report_api_helpers import WS, create_report, make_client, user


def test_create_list_get(tmp_path):
    client = make_client(tmp_path)
    rid = create_report(client, "Sweep", "# body")
    listed = client.get(f"{WS}/reports").json()["reports"]
    assert [r["rid"] for r in listed] == [rid]
    got = client.get(f"{WS}/reports/{rid}").json()
    assert got["title"] == "Sweep" and got["body"] == "# body" and got["rev"] == 1
    assert [r["rev"] for r in got["revisions"]] == [1]


def test_get_unknown_report_404(tmp_path):
    client = make_client(tmp_path)
    assert client.get(f"{WS}/reports/rnope").status_code == 404
    assert client.get(f"{WS}/reports/rnope/revisions/1").status_code == 404


def test_list_archived_filter(tmp_path):
    client = make_client(tmp_path)
    rid = create_report(client)
    keep = create_report(client)
    assert client.patch(f"{WS}/reports/{rid}", json={"archived": True}).status_code == 200
    live = [r["rid"] for r in client.get(f"{WS}/reports").json()["reports"]]
    archived = [r["rid"] for r in client.get(f"{WS}/reports?archived=true").json()["reports"]]
    assert live == [keep] and archived == [rid]


def test_save_revision_and_conflict_body(tmp_path):
    client = make_client(tmp_path)
    rid = create_report(client, body="v1")
    r = client.post(f"{WS}/reports/{rid}/revisions", json={"base": 1, "body": "v2", "message": "m"})
    assert r.status_code == 201 and r.json() == {"rev": 2}
    r = client.post(f"{WS}/reports/{rid}/revisions", json={"base": 1, "body": "other"})
    assert r.status_code == 409
    assert r.json()["rev"] == 2 and r.json()["body"] == "v2" and "author" in r.json()
    one = client.get(f"{WS}/reports/{rid}/revisions/2").json()
    assert one["body"] == "v2" and one["message"] == "m" and one["data"] == []


def test_patch_title_pinned(tmp_path):
    client = make_client(tmp_path)
    rid = create_report(client)
    assert client.patch(f"{WS}/reports/{rid}", json={"title": "New", "pinned": True}).status_code == 200
    got = client.get(f"{WS}/reports/{rid}").json()
    assert got["title"] == "New" and got["pinned"] is True


@pytest.mark.parametrize("body", [{"title": ""}, {"title": 3}, {"pinned": "yes"}, {"archived": 1}])
def test_patch_bad_types_400(tmp_path, body):
    client = make_client(tmp_path)
    rid = create_report(client)
    assert client.patch(f"{WS}/reports/{rid}", json=body).status_code == 400
    assert client.get(f"{WS}/reports/{rid}").json()["title"] == "T"


def test_publish_and_read_panel_data(tmp_path):
    client = make_client(tmp_path)
    rid = create_report(client)
    r = client.post(f"{WS}/reports/{rid}/publish", json={"rev": 1, "data": {"p1": {"rows": [1, 2]}}})
    assert r.status_code == 200, r.text
    assert client.get(f"{WS}/reports/{rid}").json()["published_rev"] == 1
    assert client.get(f"{WS}/reports/{rid}/revisions/1").json()["data"] == ["p1"]
    assert client.get(f"{WS}/reports/{rid}/revisions/1/data/p1").json() == {"rows": [1, 2]}
    assert client.get(f"{WS}/reports/{rid}/revisions/1/data/p2").status_code == 404


def test_publish_size_cap_413(tmp_path, monkeypatch):
    from vmn_exp.ui import reports_publish

    monkeypatch.setattr(reports_publish, "MAX_PANEL_BYTES", 50)
    client = make_client(tmp_path)
    rid = create_report(client)
    r = client.post(f"{WS}/reports/{rid}/publish", json={"rev": 1, "data": {"p": {"x": "y" * 100}}})
    assert r.status_code == 413
    monkeypatch.setattr(reports_publish, "MAX_PANEL_BYTES", 10_000)
    monkeypatch.setattr(reports_publish, "MAX_REVISION_BYTES", 100)
    data = {"a": {"x": "y" * 60}, "b": {"x": "y" * 60}}
    assert client.post(f"{WS}/reports/{rid}/publish", json={"rev": 1, "data": data}).status_code == 413


def test_publish_unknown_verstr_refused(tmp_path):
    client = make_client(tmp_path)
    rid = create_report(client)
    data = {"p": {"app": "myapp", "verstrs": ["0.0.1-dev.nope"]}}
    r = client.post(f"{WS}/reports/{rid}/publish", json={"rev": 1, "data": data})
    assert r.status_code == 400 and "0.0.1-dev.nope" in r.text


def test_publish_bad_shape_and_unknown_rev(tmp_path):
    client = make_client(tmp_path)
    rid = create_report(client)
    assert client.post(f"{WS}/reports/{rid}/publish", json={"rev": 1, "data": []}).status_code == 400
    assert client.post(f"{WS}/reports/{rid}/publish", json={"rev": 9, "data": {}}).status_code == 404


def test_delete_report_and_thread(tmp_path):
    client = make_client(tmp_path)
    rid = create_report(client)
    client.post(f"{WS}/comments", json={"target": f"report:{rid}", "text": "hi"})
    assert client.delete(f"{WS}/reports/{rid}").status_code == 200
    assert client.get(f"{WS}/reports/{rid}").status_code == 404
    assert client.get(f"{WS}/comments?target=report:{rid}").json()["comments"] == []


@pytest.mark.parametrize("method,path,body", [
    ("post", "/reports", {"title": "t", "body": "b"}),
    ("post", "/reports/{rid}/revisions", {"base": 1, "body": "b"}),
    ("post", "/reports/{rid}/publish", {"rev": 1, "data": {}}),
    ("patch", "/reports/{rid}", {"title": "x"}),
    ("delete", "/reports/{rid}", None),
])
def test_mutations_refused_read_only(tmp_path, method, path, body):
    rid = create_report(make_client(tmp_path))
    client = make_client(tmp_path, read_only=True)
    kwargs = {"json": body} if body is not None else {}
    r = getattr(client, method)(WS + path.format(rid=rid), **kwargs)
    assert r.status_code == 403
    assert client.get(f"{WS}/reports/{rid}").status_code == 200


def test_foreign_origin_refused(tmp_path):
    client = make_client(tmp_path)
    r = client.post(f"{WS}/reports", json={"title": "t", "body": "b"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_roles(tmp_path):
    client = make_client(tmp_path, auth=True)
    viewer, editor, admin = user("v", "viewer"), user("e", "editor"), user("a", "admin")
    assert client.post(f"{WS}/reports", json={"title": "t", "body": "b"}, headers=viewer).status_code == 403
    rid = create_report(client, headers=editor)
    assert client.get(f"{WS}/reports/{rid}", headers=viewer).status_code == 200
    assert client.delete(f"{WS}/reports/{rid}", headers=editor).status_code == 403
    assert client.delete(f"{WS}/reports/{rid}", headers=admin).status_code == 200


def test_author_is_request_principal(tmp_path):
    client = make_client(tmp_path, auth=True)
    rid = create_report(client, headers=user("alice", "editor"))
    got = client.get(f"{WS}/reports/{rid}", headers=user("alice", "viewer")).json()
    assert got["author"]["id"] == "alice" and got["created_by"]["id"] == "alice"
