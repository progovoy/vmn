"""Bulk run actions by query (plan 23 S4): ``{scope, q, status}`` bodies on
``exp_archive``/``exp_unarchive``/``exp_tag``, ``dry_run`` previews, and
batched, idempotent jobs with progress."""
import os
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "my_app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
JOB = "0.0.1-dev.job.000"


def _v(i):
    return f"0.0.1-dev.run.{i:04d}"


def _manager(tmp_path, matching=3, other=2, archived=()):
    """A store workspace: a job with *matching* ``branch = "a"`` children and
    *other* ``branch = "b"`` ones; *archived* children start archived."""
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    storage.save(APP, JOB, {"verstr": JOB, "timestamp": "2026-01-01T00:00:00Z"}, {})
    for i in range(matching + other):
        meta = {"verstr": _v(i), "timestamp": "2026-01-01T00:00:01Z", "parent": JOB,
                "branch": "a" if i < matching else "b"}
        if i in archived:
            meta["archived"] = True
        storage.save(APP, _v(i), meta, {})
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    return manager


def _client(tmp_path, **kw):
    from vmn_exp.ui.server import create_app

    return TestClient(create_app(_manager(tmp_path, **kw)))


def _wait(client, job_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _act(client, action, body):
    r = client.post(f"{BASE}/actions/{action}", json=body)
    assert r.status_code == 202, r.text
    job = _wait(client, r.json()["id"])
    assert job["status"] == "succeeded", job["log"]
    return job


def _rows(client):
    r = client.get(f"{BASE}/experiments", params={"archived": 1, "limit": 1000})
    return {row["verstr"]: row for row in r.json()["rows"]}


QUERY = {"scope": JOB, "q": 'branch = "a"'}


def test_dry_run_counts_and_samples_the_matching_runs(tmp_path):
    client = _client(tmp_path, matching=12, other=3)
    r = client.post(f"{BASE}/actions/exp_archive", json={**QUERY, "dry_run": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 12
    assert len(body["sample"]) == 10
    assert set(body["sample"]) <= {_v(i) for i in range(12)}
    assert not any(row.get("archived") for row in _rows(client).values())


def test_archive_by_query_acts_on_exactly_the_matching_runs_in_batches(tmp_path):
    client = _client(tmp_path, matching=503, other=2)
    job = _act(client, "exp_archive", QUERY)
    assert job["progress"] == {"done": 503, "total": 503}
    rows = _rows(client)
    archived = {v for v, row in rows.items() if row.get("archived")}
    assert archived == {_v(i) for i in range(503)}


def test_archive_by_query_is_idempotent(tmp_path):
    client = _client(tmp_path, matching=3, other=2, archived={0})
    r = client.post(f"{BASE}/actions/exp_archive", json={**QUERY, "dry_run": True})
    assert r.json()["count"] == 2
    _act(client, "exp_archive", QUERY)
    r = client.post(f"{BASE}/actions/exp_archive", json={**QUERY, "dry_run": True})
    assert r.json() == {"count": 0, "sample": []}
    assert _act(client, "exp_archive", QUERY)["progress"] == {"done": 0, "total": 0}


def test_unarchive_by_query_counts_the_archived_runs(tmp_path):
    client = _client(tmp_path, matching=3, other=2, archived={0, 1, 4})
    r = client.post(f"{BASE}/actions/exp_unarchive", json={**QUERY, "dry_run": True})
    assert r.json()["count"] == 2
    _act(client, "exp_unarchive", QUERY)
    archived = {v for v, row in _rows(client).items() if row.get("archived")}
    assert archived == {_v(4)}


def test_status_narrows_the_query(tmp_path):
    client = _client(tmp_path)
    r = client.post(f"{BASE}/actions/exp_archive",
                    json={**QUERY, "status": "failed", "dry_run": True})
    assert r.json()["count"] == 0


def test_tag_by_query(tmp_path):
    client = _client(tmp_path)
    body = {**QUERY, "set": {"stage": "x"}}
    r = client.post(f"{BASE}/actions/exp_tag", json={**body, "dry_run": True})
    assert r.json()["count"] == 3
    _act(client, "exp_tag", body)
    tagged = {v for v, row in _rows(client).items() if row.get("tags", {}).get("stage") == "x"}
    assert tagged == {_v(i) for i in range(3)}
    r = client.post(f"{BASE}/actions/exp_tag", json={**body, "dry_run": True})
    assert r.json()["count"] == 0


def test_tag_by_query_still_validates_the_tags(tmp_path):
    client = _client(tmp_path)
    r = client.post(f"{BASE}/actions/exp_tag", json={**QUERY, "set": {"-bad": "x"}})
    assert r.status_code == 400


def test_a_verstrs_body_still_archives_those_runs(tmp_path):
    client = _client(tmp_path)
    _act(client, "exp_archive", {"verstrs": [_v(3)]})
    archived = {v for v, row in _rows(client).items() if row.get("archived")}
    assert archived == {_v(3)}


def test_a_bad_query_is_a_400(tmp_path):
    client = _client(tmp_path)
    r = client.post(f"{BASE}/actions/exp_archive", json={"scope": JOB, "q": "branch = = ("})
    assert r.status_code == 400


def test_an_invalid_scope_is_a_400(tmp_path):
    client = _client(tmp_path)
    r = client.post(f"{BASE}/actions/exp_archive", json={"scope": "../x", "dry_run": True})
    assert r.status_code == 400


def test_an_unknown_scope_is_a_404(tmp_path):
    client = _client(tmp_path)
    r = client.post(f"{BASE}/actions/exp_archive", json={"scope": "0.9.9-dev.no.run", "dry_run": True})
    assert r.status_code == 404


def test_read_only_refuses_even_a_preview(tmp_path):
    from vmn_exp.ui.server import create_app

    client = TestClient(create_app(_manager(tmp_path), read_only=True))
    r = client.post(f"{BASE}/actions/exp_archive", json={**QUERY, "dry_run": True})
    assert r.status_code == 403


def test_a_viewer_is_refused(tmp_path):
    from vmn_exp.ui.auth import AuthenticatorChain
    from vmn_exp.ui.auth.principal import EDITOR, VIEWER, Principal
    from vmn_exp.ui.server import create_app

    people = {"Bearer v": Principal("v", "v", {"ws": VIEWER}),
              "Bearer e": Principal("e", "e", {"ws": EDITOR})}

    class Fixed:
        def authenticate(self, request):
            return people.get(request.headers.get("Authorization", ""))

    client = TestClient(create_app(_manager(tmp_path), auth=AuthenticatorChain([Fixed()])))
    url = f"{BASE}/actions/exp_archive"
    body = {**QUERY, "dry_run": True}
    assert client.post(url, json=body, headers={"Authorization": "Bearer v"}).status_code == 403
    r = client.post(url, json=body, headers={"Authorization": "Bearer e"})
    assert r.status_code == 200 and r.json()["count"] == 3
