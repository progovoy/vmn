#!/usr/bin/env python3
"""K5/K6: error states for the tree and diff endpoints.

K5: non-repo git workspace -> 409 with reason ``not_a_repo``
K6: diff materialisation failures -> 422 with reason
"""
import os
from unittest import mock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(tmp_path, ws_path=None):
    """Build a TestClient whose ``main`` workspace points at *ws_path*."""
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "ui_data"))
    manager.attach_path("main", ws_path or str(tmp_path / "repo"))
    return TestClient(create_app(manager))


# ---- K5: non-repo workspace -> 409 ----------------------------------------

def test_tree_non_repo_returns_409(tmp_path):
    """GET /tree on a workspace whose path has a corrupt .git -> 409 not_a_repo.

    The workspace was valid when registered (has a .git dir), but the git
    repo is corrupt or otherwise not a valid git repository.
    """
    bad_path = tmp_path / "not-a-repo"
    bad_path.mkdir()
    # Create a .git dir so workspace manager accepts it, but make it corrupt
    (bad_path / ".git").mkdir()
    (bad_path / ".git" / "HEAD").write_text("garbage")

    client = _client(tmp_path, ws_path=str(bad_path))
    r = client.get("/api/v1/workspaces/main/apps/myapp/tree")
    assert r.status_code == 409
    body = r.json()
    assert body["reason"] == "not_a_repo"
    assert "path" in body
    assert "detail" in body


# ---- K6: diff failures carry a reason -------------------------------------

def test_diff_materialize_failure_returns_422(tmp_path):
    """When the diff materialisation fails, the endpoint returns 422 with a reason."""
    from vmn_exp.ui.readers import diffs as diff_reader

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    os.system(f"git init {repo_path}")
    client = _client(tmp_path, ws_path=str(repo_path))

    # Simulate materialisation failure by raising DiffMaterializeError
    with mock.patch.object(
        diff_reader, "cached_experiment_diff",
        side_effect=diff_reader.DiffMaterializeError(
            "Failed to materialize snapshots for diff", "code_missing"
        ),
    ):
        r = client.get(
            "/api/v1/workspaces/main/apps/myapp/experiments-diff?v=a&to=b"
        )
    assert r.status_code == 422
    body = r.json()
    assert body["reason"] == "code_missing"
    assert "detail" in body


def test_diff_no_base_commit_still_200(tmp_path):
    """When the record has no base commit the diff is None but the response is 200."""
    from vmn_exp.ui.readers import diffs as diff_reader

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    os.system(f"git init {repo_path}")
    client = _client(tmp_path, ws_path=str(repo_path))

    fake_result = (
        {"diff": None, "truncated": False,
         "diff_unavailable": "tree diff unavailable: a has no base commit",
         "from_verstr": "a", "to_verstr": "b", "metrics_delta": {}},
        None,
    )
    with mock.patch.object(
        diff_reader, "cached_experiment_diff", return_value=fake_result
    ):
        r = client.get(
            "/api/v1/workspaces/main/apps/myapp/experiments-diff?v=a&to=b"
        )
    assert r.status_code == 200
    body = r.json()
    assert body["diff"] is None
    assert "diff_unavailable" in body
